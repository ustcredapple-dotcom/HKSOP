#!/usr/bin/env python3
"""Loopback-only kit catalog and export service; no CAD model writes."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import mimetypes
import os
import re
import socket
import sqlite3
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from bom import APIError, aggregate, load_catalog
from access_settings import AccessSettings
from exports import export_result
from layout import choose_mounting_holes
from shared_kits import (Identity, MAX_SHARED_BODY, SharedKitStore, prepare_project,
                         shape, shared_bundle, strict_json, text, thumbnail_svg)
from cart import CartStore, MAX_CART_BYTES

ROOT = Path(__file__).resolve().parent
MAX_BODY = 1024 * 1024
PREFIX = "/optics-kits"
PUBLIC_STATIC_FILES = frozenset({"index.html", "app.css", "app.js", "layout.css", "layout.js", "stacked-boards.js", "measurement.js", "elevation.js", "laser-adapter.js", "global-height.js", "periscope-properties.js", "manual-source-mount.js", "metric-migration.js",
                                 "optical-interaction-language.js", "optical-engine.js", "optical-assembly-engine.js", "optical-hole-probe.js", "optical-renderer.js", "optical-renderer.css",
                                 "canvas-workspace.js", "canvas-workspace.css", "registered-boards.js", "objective-sideview.js",
                                 "table-mode.js", "table-mode.css", "moving-stages.js",
                                 "project.css", "project-file.js", "collision-engine.js", "collision-overrides.js",
                                 "shared-project.js", "shared-kits.css", "shared-kits.js", "access-management.js", "favicon.ico"})


def http_origin(value):
    """Parse a single serialized origin, including its effective port."""
    if not value or any(char.isspace() for char in value) or any(char in value for char in "\\,?#"):
        raise ValueError("invalid origin")
    parsed = urlsplit(value)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or
            parsed.username is not None or parsed.password is not None or
            parsed.path or parsed.netloc.endswith(":")):
        raise ValueError("invalid origin")
    port = parsed.port
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("invalid port")
    return parsed.scheme, parsed.hostname.lower(), port or (443 if parsed.scheme == "https" else 80)


@dataclass(frozen=True)
class Config:
    catalog: Path = ROOT / "catalog.json"
    assets: Path = ROOT / "assets"
    static: Path = ROOT / "static"
    auth_token: str | None = None
    shared_db: Path = ROOT / "var/shared-kits.sqlite3"
    shared_backup: Path | None = None


class Handler(BaseHTTPRequestHandler):
    server_version = "OpticsKits/2.0"

    @property
    def config(self):
        return self.server.config

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, format, *args):
        # Do not log request bodies, authentication headers, or local paths.
        return

    def route(self):
        parsed = urlsplit(self.path)
        path = unquote(parsed.path)
        if path == PREFIX or path.startswith(PREFIX + "/"):
            path = path[len(PREFIX):] or "/"
        return path, parse_qs(parsed.query, keep_blank_values=True)

    def authenticate(self):
        token = self.config.auth_token
        self.session_role = "user"
        guest = self.headers.get_all("X-ZZLAB-Guest", [])
        if token is None:
            if guest:
                raise APIError("authentication_required", "请先登录 ZZLab。", 401)
            return False
        supplied = self.headers.get_all("X-ZZLAB-Internal-Token", [])
        roles = self.headers.get_all("X-ZZLAB-Role", [])
        authenticated = self.headers.get_all("X-ZZLAB-Authenticated", [])
        if len(supplied) != 1 or not hmac.compare_digest(supplied[0].encode(), token.encode()) or len(roles) != 1:
            raise APIError("authentication_required", "请通过 ZZLab 网站访问此页面。", 401)
        role = roles[0].lower()
        if guest:
            prohibited = ("X-ZZLAB-Authenticated", "X-ZZLAB-User-ID", "X-ZZLAB-User", "X-ZZLAB-Display-Name", "X-ZZLAB-Policy-Probe")
            if (guest != ["1"] or role != "guest" or any(self.headers.get_all(k, []) for k in prohibited)
                    or not self.server.access_settings.enabled()):
                raise APIError("authentication_required", "请先登录 ZZLab。", 401)
            self.session_role = "guest"
            return True
        if len(authenticated) != 1 or authenticated[0].lower() not in ("true", "1"):
            raise APIError("authentication_required", "请先登录 ZZLab。", 401)
        if role not in ("readonly", "user", "admin"):
            raise APIError("forbidden", "当前账号没有此模块的访问权限。", 403)
        self.session_role = role
        return True

    def allow_limited_route(self, method, path):
        """Guest/readonly access cannot expand when another API is added later."""
        if self.session_role not in ("guest", "readonly"):
            return
        if self.session_role == "readonly" and ((method == "GET" and path == "/api/cart") or
                (method == "POST" and path in ("/api/cart/add", "/api/cart/update", "/api/cart/clear", "/api/cart/export"))):
            return
        if method == "POST":
            if path in ("/api/preview", "/api/export", "/api/mounting-holes"):
                return
            raise APIError("publish_forbidden", "访客和只读账号可以使用和下载；共享发布、撤下或恢复需要普通或管理员账号。", 403)
        if method == "GET":
            if path in ("/api/session", "/api/catalog", "/api/shared-kits", "/api/machining-atlas"):
                return
            if re.fullmatch(r"/api/shared-kits/[a-f0-9]{32}/(project|thumbnail|bundle)", path):
                return
            relative = "index.html" if path == "/" else path.removeprefix("/")
            if relative in PUBLIC_STATIC_FILES or re.fullmatch(r"topviews/[A-Za-z0-9][A-Za-z0-9_.-]*\.(svg|png|webp)", relative):
                return
        raise APIError("not_found", "接口或页面不存在。", 404)

    def check_origin(self, trusted_proxy=False):
        denied = APIError("cross_origin_denied", "只接受本站页面的请求。", 403)
        if self.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
            raise denied
        origins = self.headers.get_all("Origin", [])
        if not origins:
            return  # Existing authenticated non-browser API clients have no Origin.
        try:
            if len(origins) != 1:
                raise ValueError("multiple origins")
            scheme = "http"  # This service itself listens on loopback HTTP only.
            hosts = self.headers.get_all("Host", [])
            forwarded_hosts = self.headers.get_all("X-Forwarded-Host", [])
            forwarded_schemes = self.headers.get_all("X-Forwarded-Proto", [])
            # The authenticated ZZLab router strips client-supplied forwarded
            # headers and writes these itself. Unauthenticated development
            # requests must never use those headers to choose an allowed origin.
            if trusted_proxy and (forwarded_hosts or forwarded_schemes):
                if len(forwarded_hosts) != 1 or len(forwarded_schemes) != 1:
                    raise ValueError("ambiguous forwarded origin")
                hosts, scheme = forwarded_hosts, forwarded_schemes[0]
                if scheme not in ("http", "https"):
                    raise ValueError("invalid forwarded scheme")
            if len(hosts) != 1 or http_origin(origins[0]) != http_origin(f"{scheme}://{hosts[0]}"):
                raise ValueError("origin mismatch")
        except ValueError as exc:
            raise denied from exc

    def shared_identity(self, trusted_proxy):
        if not trusted_proxy:
            return Identity("dev", "本地开发", "user")
        if self.session_role in ("guest", "readonly"):
            # Even a readonly account that originally published a kit no longer
            # has ownership powers or visibility of withdrawn records.
            return Identity(None, "访客" if self.session_role == "guest" else "只读访问", self.session_role)
        ids = self.headers.get_all("X-ZZLAB-User-ID", [])
        user_id = None
        if len(ids) == 1 and re.fullmatch(r"[0-9]{1,40}", ids[0]) and int(ids[0]) > 0:
            user_id = str(int(ids[0]))
        name = "实验室成员"
        for field in ("X-ZZLAB-Display-Name", "X-ZZLAB-User"):
            values = self.headers.get_all(field, [])
            if len(values) == 1:
                try:
                    candidate = unquote(values[0], errors="strict").strip()
                    text(candidate, "账号显示名", 256, True)
                    name = candidate
                    break
                except (UnicodeError, APIError):
                    continue
        return Identity(user_id, name, self.session_role)

    def shared_route(self, path):
        match = re.fullmatch(r"/api/shared-kits(?:/([a-f0-9]{32})/(project|thumbnail|bundle|unpublish|restore))?", path)
        return match.groups() if match else None

    def cart_identity(self, trusted_proxy):
        # Personal order state does not grant shared-publication ownership.
        # In particular shared_identity must continue hiding readonly ownership.
        if not trusted_proxy:
            return Identity("dev", "本地开发", "user")
        ids = self.headers.get_all("X-ZZLAB-User-ID", [])
        if (self.session_role not in ("readonly", "user", "admin") or len(ids) != 1 or
                not re.fullmatch(r"[0-9]{1,40}", ids[0]) or int(ids[0]) <= 0):
            raise APIError("cart_identity_required", "请登录具有完整账号身份的账户后使用购物车。", 403)
        return Identity(str(int(ids[0])), "个人购物车", self.session_role)

    def require_policy_admin(self, trusted_proxy):
        identity = self.shared_identity(trusted_proxy)
        if not trusted_proxy or identity.role != "admin" or not identity.id:
            raise APIError("forbidden", "只有已登录的管理员可以管理访客访问设置。", 403)
        return identity

    def can_download_manufacturing(self):
        return (self.session_role != "guest" or
                self.server.access_settings.manufacturing_downloads_enabled())

    def require_manufacturing_download(self):
        if not self.can_download_manufacturing():
            raise APIError("manufacturing_download_forbidden",
                           "管理员已关闭游客的图纸和三维模型下载权限；仍可编辑方案、下载清单和工程文件。", 403)

    def internal_policy_probe(self):
        tokens = self.headers.get_all("X-ZZLAB-Internal-Token", [])
        probes = self.headers.get_all("X-ZZLAB-Policy-Probe", [])
        allowed = {"x-zzlab-internal-token", "x-zzlab-policy-probe"}
        forbidden_headers = any((k.lower().startswith("x-zzlab-") and k.lower() not in allowed) or
                                k.lower().startswith("x-forwarded-") or k.lower() == "origin" for k in self.headers)
        if (self.client_address[0] not in ("127.0.0.1", "::1") or self.config.auth_token is None or
                len(tokens) != 1 or not hmac.compare_digest(tokens[0].encode(), self.config.auth_token.encode()) or
                probes != ["1"] or forbidden_headers):
            raise APIError("authentication_required", "内部策略查询未获授权。", 401)
        return {"guestAccessEnabled": self.server.access_settings.enabled()}

    def send_bytes(self, status, content, content_type, filename=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'self'")
        if filename:
            fallback = {"麓邦采购.xlsx": "lubang-procurement.xlsx", "生产清单.xlsx": "manufacturing.xlsx",
                        "光路套件生产包.zip": "optics-kits-bundle.zip", "光路布局.json": "optics-layout.json",
                        "光路总俯视图.svg": "optics-layout.svg",
                        "共享套件工程.zzoptics.json": "shared-kit.zzoptics.json",
                        "共享套件生产包.zip": "shared-kit-bundle.zip"}.get(filename, "download")
            self.send_header("Content-Disposition", f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}")
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, status, value):
        self.send_bytes(status, json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(), "application/json; charset=utf-8")

    def error(self, exc):
        self.send_json(exc.status, exc.payload())

    def read_payload(self, trusted_proxy=False, max_body=MAX_BODY, strict=False):
        if self.headers.get("Transfer-Encoding"):
            raise APIError("invalid_request", "不支持分块请求。")
        if self.headers.get_content_type() != "application/json":
            raise APIError("invalid_content_type", "请求必须使用application/json。", 415)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise APIError("invalid_request", "请求长度无效。") from exc
        if not 0 < length <= max_body:
            raise APIError("request_too_large", "请求为空或超过允许大小。", 413)
        self.check_origin(trusted_proxy)
        try:
            data = self.rfile.read(length)
            if len(data) != length:
                raise ValueError("incomplete body")
            return (strict_json if strict else json.loads)(data.decode("utf-8"))
        except (UnicodeError, ValueError, RecursionError, socket.timeout) as exc:
            raise APIError("invalid_json", "请求不是有效的JSON。") from exc

    def do_GET(self):
        try:
            path, query = self.route()
            if path in ("/healthz", "/api/healthz"):
                self.send_json(200, {"ok": True, "service": "optics-kits"})
                return
            if path == "/internal/guest-access":
                if query:
                    raise APIError("invalid_request", "策略查询不接受查询参数。")
                self.send_json(200, self.internal_policy_probe())
                return
            trusted_proxy = self.authenticate()
            if path == "/api/admin/guest-access":
                self.require_policy_admin(trusted_proxy)
                self.check_origin(trusted_proxy)
                if query:
                    raise APIError("invalid_request", "访问设置接口不接受查询参数。")
                self.send_json(200, self.server.access_settings.read())
                return
            self.allow_limited_route("GET", path)
            if path == "/api/cart":
                if query:
                    raise APIError("invalid_request", "购物车接口不接受查询参数。")
                self.check_origin(trusted_proxy)
                self.send_json(200, self.server.cart_store.read(self.cart_identity(trusted_proxy)))
                return
            if path == "/api/session" and not query:
                identity = self.shared_identity(trusted_proxy)
                self.send_json(200, {"role": identity.role,
                                     "canPublish": identity.role in ("user", "admin") and bool(identity.id),
                                     "canDownload": True,
                                     "canDownloadManufacturing": self.can_download_manufacturing()})
                return
            shared = self.shared_route(path)
            if shared is not None:
                if query:
                    raise APIError("invalid_request", "共享套件接口不接受查询参数。")
                kit_id, action = shared
                identity = self.shared_identity(trusted_proxy)
                store = self.server.shared_store
                if kit_id is None:
                    self.send_json(200, store.listing(identity))
                elif action in ("project", "thumbnail", "bundle"):
                    row = store.get(kit_id, identity)
                    if action == "project":
                        self.send_bytes(200, row["project_json"], "application/json; charset=utf-8", "共享套件工程.zzoptics.json")
                    elif action == "thumbnail":
                        self.send_bytes(200, row["thumbnail_svg"], "image/svg+xml; charset=utf-8")
                    else:
                        self.require_manufacturing_download()
                        bundle = shared_bundle(row, load_catalog(self.config.catalog), self.config.assets, self.config.static)
                        # CAD generation can take time: a revocation while this
                        # request was running must prevent delivery as well.
                        self.require_manufacturing_download()
                        self.send_bytes(200, *bundle)
                else:
                    raise APIError("method_not_allowed", "此操作需要使用 POST。", 405)
                return
            if path == "/api/catalog" and not query:
                self.send_json(200, load_catalog(self.config.catalog))
                return
            if path == "/api/machining-atlas":
                self.require_manufacturing_download()
                if query:
                    raise APIError("invalid_request", "图册下载不接受查询参数。")
                root = (self.config.assets / "drawings" / "atlas").resolve()
                receipt = json.loads((root / "current.json").read_text())
                name = receipt.get("filename", "")
                if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.pdf", name) or
                        receipt.get("catalogSha256") != hashlib.sha256(self.config.catalog.read_bytes()).hexdigest()):
                    raise APIError("atlas_unavailable", "完整机加工图册正在更新，请稍后再试。", 503)
                target = (root / name).resolve()
                if not target.is_relative_to(root):
                    raise APIError("atlas_unavailable", "完整机加工图册正在更新，请稍后再试。", 503)
                data = target.read_bytes()
                if hashlib.sha256(data).hexdigest() != receipt.get("sha256"):
                    raise APIError("atlas_unavailable", "完整机加工图册正在更新，请稍后再试。", 503)
                self.require_manufacturing_download()
                self.send_bytes(200, data, "application/pdf", "完整机加工图册_万能柱底座6mm_B6_R1.pdf")
                return
            if path.startswith("/api/"):
                raise APIError("not_found", "接口不存在。", 404)
            relative = "index.html" if path == "/" else path.lstrip("/")
            if "\\" in relative or any(part in ("", ".", "..") for part in relative.split("/")):
                raise APIError("not_found", "页面不存在。", 404)
            root = self.config.static.resolve()
            target = (root / relative).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise APIError("not_found", "页面不存在。", 404) from exc
            if target.suffix.lower() not in (".html", ".css", ".js", ".svg", ".png", ".webp", ".ico") or not target.is_file():
                raise APIError("not_found", "页面不存在。", 404)
            content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            if target.suffix in (".html", ".css", ".js"):
                content_type += "; charset=utf-8"
            self.send_bytes(200, target.read_bytes(), content_type)
        except APIError as exc:
            self.error(exc)
        except (OSError, ValueError, sqlite3.Error):
            self.error(APIError("service_unavailable", "服务暂时无法读取所需文件。", 503))

    def do_POST(self):
        try:
            trusted_proxy = self.authenticate()
            path, query = self.route()
            if path == "/api/admin/guest-access":
                identity = self.require_policy_admin(trusted_proxy)
                if query:
                    raise APIError("invalid_request", "访问设置接口不接受查询参数。")
                payload = self.read_payload(trusted_proxy, max_body=4096, strict=True)
                self.send_json(200, self.server.access_settings.update(payload, identity))
                return
            self.allow_limited_route("POST", path)
            if path in ("/api/cart/add", "/api/cart/update", "/api/cart/clear", "/api/cart/export"):
                identity = self.cart_identity(trusted_proxy)
                if path == "/api/cart/export":
                    if set(query) != {"format"} or len(query["format"]) != 1 or query["format"][0] not in ("lubang", "manufacturing", "bundle"):
                        raise APIError("invalid_format", "购物车导出格式为lubang、manufacturing或bundle。")
                elif query:
                    raise APIError("invalid_request", "购物车接口不接受查询参数。")
                payload = self.read_payload(trusted_proxy, MAX_CART_BYTES + 16384, strict=True)
                store = self.server.cart_store
                if path == "/api/cart/add":
                    self.send_json(200, store.add(identity, payload, load_catalog(self.config.catalog)))
                elif path == "/api/cart/update":
                    self.send_json(200, store.update(identity, payload))
                elif path == "/api/cart/clear":
                    self.send_json(200, store.clear(identity, payload))
                else:
                    preview = store.for_export(identity, payload, load_catalog(self.config.catalog))
                    self.send_bytes(200, *export_result(preview, query["format"][0], self.config.assets, self.config.static, catalog=load_catalog(self.config.catalog)))
                return
            shared = self.shared_route(path)
            if shared is not None:
                if query:
                    raise APIError("invalid_request", "共享套件接口不接受查询参数。")
                kit_id, action = shared
                if action not in (None, "unpublish", "restore"):
                    raise APIError("method_not_allowed", "此接口只支持读取。", 405)
                identity = self.shared_identity(trusted_proxy)
                identity.require_id()
                payload = self.read_payload(trusted_proxy, MAX_SHARED_BODY, strict=True)
                store = self.server.shared_store
                if action is None:
                    shape(payload, {"name", "description", "project"}, {"name", "description", "project"}, "共享请求")
                    name = text(payload["name"], "共享套件名称", 120, True)
                    description = text(payload["description"], "共享说明", 2000)
                    preview = prepare_project(payload["project"], load_catalog(self.config.catalog))
                    thumbnail = thumbnail_svg(preview, self.config.static, catalog=load_catalog(self.config.catalog))
                    self.send_json(201, store.publish(name, description, payload["project"], thumbnail, identity))
                else:
                    shape(payload, set(), label="撤下或恢复请求")
                    self.send_json(200, store.change_visibility(kit_id, identity, action == "restore"))
                return
            if path not in ("/api/preview", "/api/export", "/api/mounting-holes"):
                raise APIError("not_found", "接口不存在。", 404)
            if path in ("/api/preview", "/api/mounting-holes") and query:
                raise APIError("invalid_request", "预览接口不接受查询参数。")
            if path == "/api/export" and (set(query) != {"format"} or len(query["format"]) != 1 or query["format"][0] not in ("lubang", "manufacturing", "bundle", "layout-json", "layout-svg")):
                raise APIError("invalid_format", "format必须为lubang、manufacturing、bundle、layout-json或layout-svg。")
            payload = self.read_payload(trusted_proxy)
            manufacturing_download = path == "/api/export" and query["format"][0] == "bundle"
            if manufacturing_download:
                self.require_manufacturing_download()
            if path == "/api/mounting-holes":
                self.send_json(200, choose_mounting_holes(load_catalog(self.config.catalog), payload))
                return
            preview = aggregate(load_catalog(self.config.catalog), payload, require_items=path == "/api/export" and query["format"][0] not in ("layout-json", "layout-svg"))
            if path == "/api/preview":
                self.send_json(200, preview)
            else:
                content, mime, filename = export_result(preview, query["format"][0], self.config.assets, self.config.static, catalog=load_catalog(self.config.catalog))
                if manufacturing_download:
                    self.require_manufacturing_download()
                self.send_bytes(200, content, mime, filename)
        except APIError as exc:
            self.error(exc)
        except (OSError, ValueError, sqlite3.Error):
            self.error(APIError("export_failed", "文件生成失败，请稍后重试。", 500))

    def do_OPTIONS(self):
        self.error(APIError("method_not_allowed", "不允许跨域调用。", 405))


def create_server(config, port=18923):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.config = config
    server.shared_store = SharedKitStore(config.shared_db, config.shared_backup)
    server.access_settings = AccessSettings(server.shared_store)
    server.cart_store = CartStore(server.shared_store, load_catalog(config.catalog))
    server.daemon_threads = True
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18923)
    parser.add_argument("--catalog", type=Path, default=Path(os.environ.get("OPTICS_KITS_CATALOG", ROOT / "catalog.json")))
    parser.add_argument("--assets", type=Path, default=Path(os.environ.get("OPTICS_KITS_ASSETS", ROOT / "assets")))
    parser.add_argument("--static", type=Path, default=Path(os.environ.get("OPTICS_KITS_STATIC", ROOT / "static")))
    parser.add_argument("--auth-token-file", type=Path, default=os.environ.get("ZZLAB_INTERNAL_TOKEN_FILE"))
    parser.add_argument("--shared-db", type=Path, default=Path(os.environ.get("OPTICS_KITS_SHARED_DB", ROOT / "var/shared-kits.sqlite3")))
    parser.add_argument("--shared-backup", type=Path, default=os.environ.get("OPTICS_KITS_SHARED_BACKUP"))
    args = parser.parse_args()
    token = None
    if args.auth_token_file:
        token = args.auth_token_file.read_text().strip()
        if not token:
            parser.error("内部令牌文件为空")
    config = Config(args.catalog, args.assets, args.static, token, args.shared_db, args.shared_backup)
    try:
        server = create_server(config, args.port)
    except OSError as exc:
        parser.exit(2, f"端口 {args.port} 无法监听：{exc.strerror}\n")
    print(f"Optics kits listening on http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
