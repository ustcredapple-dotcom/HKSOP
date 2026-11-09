"""Administrator-controlled guest policy, persisted alongside shared snapshots."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone

from bom import APIError

DEFAULT_STATE = {"guestAccessEnabled": False, "guestManufacturingDownloadsEnabled": True,
                 "revision": 0, "updatedAt": None}
MAX_REVISION = 2**63 - 2


class AccessSettings:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _ensure_schema(db):
        db.execute("""CREATE TABLE IF NOT EXISTS optics_access_settings (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            guest_enabled INTEGER NOT NULL CHECK(guest_enabled IN (0,1)),
            guest_manufacturing_downloads_enabled INTEGER NOT NULL DEFAULT 1
                CHECK(guest_manufacturing_downloads_enabled IN (0,1)),
            revision INTEGER NOT NULL CHECK(revision>0),
            updated_at TEXT NOT NULL,
            updated_by TEXT NOT NULL)""")
        columns = {row[1] for row in db.execute("PRAGMA table_info(optics_access_settings)")}
        if "guest_manufacturing_downloads_enabled" not in columns:
            try:
                db.execute("""ALTER TABLE optics_access_settings ADD COLUMN
                    guest_manufacturing_downloads_enabled INTEGER NOT NULL DEFAULT 1
                    CHECK(guest_manufacturing_downloads_enabled IN (0,1))""")
            except sqlite3.OperationalError:
                # Another worker/process may finish this additive migration
                # between the table inspection and ALTER. Other errors fail closed.
                if "guest_manufacturing_downloads_enabled" not in {
                        row[1] for row in db.execute("PRAGMA table_info(optics_access_settings)")}:
                    raise

    @staticmethod
    def _read(db):
        row = db.execute("""SELECT guest_enabled,guest_manufacturing_downloads_enabled,
                         revision,updated_at,updated_by FROM optics_access_settings WHERE singleton=1""").fetchone()
        if row is None:
            return dict(DEFAULT_STATE)
        enabled, manufacturing_enabled, revision, stamp, actor = row
        if (type(enabled) is not int or enabled not in (0, 1) or
                type(manufacturing_enabled) is not int or manufacturing_enabled not in (0, 1) or type(revision) is not int or
                not 1 <= revision <= MAX_REVISION or not isinstance(stamp, str) or
                not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", stamp) or
                not isinstance(actor, str) or not re.fullmatch(r"[1-9][0-9]{0,39}", actor)):
            raise APIError("access_settings_unavailable", "暂时无法确认访客访问设置。", 503)
        try:
            datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise APIError("access_settings_unavailable", "暂时无法确认访客访问设置。", 503) from exc
        return {"guestAccessEnabled": bool(enabled), "guestManufacturingDownloadsEnabled": bool(manufacturing_enabled),
                "revision": revision, "updatedAt": stamp}

    def read(self):
        try:
            with self.store.connect() as db:
                self._ensure_schema(db)
                return self._read(db)
        except (OSError, sqlite3.Error) as exc:
            raise APIError("access_settings_unavailable", "暂时无法确认访客访问设置。", 503) from exc

    def enabled(self):
        """Fail closed, including unavailable/corrupt settings or backing files."""
        try:
            return self.read()["guestAccessEnabled"]
        except APIError:
            return False

    def manufacturing_downloads_enabled(self):
        """Both switches must permit guest CAD/drawing delivery, on every request."""
        try:
            state = self.read()
            return state["guestAccessEnabled"] and state["guestManufacturingDownloadsEnabled"]
        except APIError:
            return False

    def update(self, payload, identity):
        if identity.role != "admin" or not identity.id or not re.fullmatch(r"[1-9][0-9]{0,39}", identity.id):
            raise APIError("forbidden", "只有已登录的管理员可以修改访客访问设置。", 403)
        if (not isinstance(payload, dict) or not {"guestAccessEnabled", "revision"} <= set(payload) or
                set(payload) - {"guestAccessEnabled", "guestManufacturingDownloadsEnabled", "revision"} or
                type(payload["guestAccessEnabled"]) is not bool or type(payload["revision"]) is not int or
                ("guestManufacturingDownloadsEnabled" in payload and type(payload["guestManufacturingDownloadsEnabled"]) is not bool) or
                not 0 <= payload["revision"] < MAX_REVISION):
            raise APIError("invalid_access_settings", "请提交访客访问开关及有效的设置版本。")
        try:
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                self._ensure_schema(db)
                current = self._read(db)
                if payload["revision"] != current["revision"]:
                    raise APIError("access_settings_conflict", "访问设置已被其他管理员修改，请重新载入后再保存。", 409, current)
                stamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
                revision = current["revision"] + 1
                # An old administrator page may submit only the original switch.
                # It must not silently re-enable a separately revoked download right.
                manufacturing_enabled = payload.get("guestManufacturingDownloadsEnabled", current["guestManufacturingDownloadsEnabled"])
                db.execute("""INSERT INTO optics_access_settings(singleton,guest_enabled,guest_manufacturing_downloads_enabled,revision,updated_at,updated_by)
                    VALUES(1,?,?,?,?,?) ON CONFLICT(singleton) DO UPDATE SET
                    guest_enabled=excluded.guest_enabled,
                    guest_manufacturing_downloads_enabled=excluded.guest_manufacturing_downloads_enabled,
                    revision=excluded.revision,
                    updated_at=excluded.updated_at,updated_by=excluded.updated_by""",
                           (int(payload["guestAccessEnabled"]), int(manufacturing_enabled), revision, stamp, identity.id))
                result = {"guestAccessEnabled": payload["guestAccessEnabled"],
                          "guestManufacturingDownloadsEnabled": manufacturing_enabled,
                          "revision": revision, "updatedAt": stamp}
        except (OSError, sqlite3.Error) as exc:
            raise APIError("access_settings_unavailable", "设置暂未保存，请稍后重试。", 503) from exc
        return {**result, "backup": self.store.backup()}
