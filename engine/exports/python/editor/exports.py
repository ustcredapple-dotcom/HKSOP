"""Only the upstream safe image resolver; no ordering or manufacturing exports."""
from pathlib import Path
from bom import APIError

def safe_asset(asset_root, registered_name, label):
    if not registered_name:
        raise APIError("asset_missing", f"{label}未登记，无法生成完整生产包。", 409)
    root = Path(asset_root).resolve()
    candidate = root / registered_name
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except FileNotFoundError as exc:
        raise APIError("asset_missing", f"{label}文件不存在，无法生成完整生产包。", 409) from exc
    except (ValueError, OSError) as exc:
        raise APIError("asset_forbidden", f"{label}不在登记的资产目录内。", 409) from exc
    if not resolved.is_file():
        raise APIError("asset_missing", f"{label}不是可读取文件。", 409)
    # Do not follow symlinks even if the present target happens to be inside root.
    current = candidate
    while current != root:
        if current.is_symlink():
            raise APIError("asset_forbidden", f"{label}不允许使用符号链接。", 409)
        current = current.parent
    return resolved
