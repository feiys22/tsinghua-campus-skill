"""_paths.py — campus/wechat 私有目录与数据路径（仓外）。

密钥、解密库、配置一律落在用户本机私有目录，不进 git。
可通过环境变量 CAMPUS_WECHAT_HOME 覆盖（冒烟测试用）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "shared", "scripts"))
import common  # noqa: E402


def default_home() -> Path:
    """私有数据根目录（仓外）。"""
    override = os.environ.get("CAMPUS_WECHAT_HOME", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    plat = common.detect_platform()
    if plat == "windows":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
        return Path(base) / "campus-wechat"
    # linux / macos / wsl
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg:
        return Path(xdg).expanduser() / "campus-wechat"
    return Path.home() / ".local" / "share" / "campus-wechat"


def ensure_home(home: Path | None = None) -> Path:
    h = home or default_home()
    h.mkdir(parents=True, exist_ok=True)
    (h / "decrypted").mkdir(parents=True, exist_ok=True)
    # 收紧权限（Windows 上 chmod 可能无效，忽略）
    try:
        os.chmod(h, 0o700)
        os.chmod(h / "decrypted", 0o700)
    except Exception:
        pass
    return h


def config_path(home: Path | None = None) -> Path:
    return (home or default_home()) / "config.json"


def ack_path(home: Path | None = None) -> Path:
    return (home or default_home()) / "TOS_ACKNOWLEDGED"


def index_db_path(home: Path | None = None) -> Path:
    return (home or default_home()) / "index.db"


def decrypted_dir(home: Path | None = None) -> Path:
    return (home or default_home()) / "decrypted"


def candidate_wechat_data_dirs() -> list[str]:
    """各 OS 上常见微信数据目录（只探测路径是否存在，不读内容）。"""
    home = Path.home()
    plat = common.detect_platform()
    cands: list[Path] = []
    if plat == "windows":
        docs = Path(os.environ.get("USERPROFILE", str(home))) / "Documents"
        cands.extend([
            docs / "xwechat_files",
            home / "Documents" / "xwechat_files",
            Path(os.environ.get("APPDATA", "")) / "Tencent" / "xwechat_files",
        ])
    else:
        cands.extend([
            home / ".local" / "share" / "WeChat_Data" / "xwechat_files",
            home / ".xwechat" / "xwechat_files",
            home / ".xwechat",
            home / "Documents" / "WeChat_Data" / "xwechat_files",
            home / ".local" / "share" / "xwechat_files",
        ])
    out: list[str] = []
    seen = set()
    for p in cands:
        try:
            if not p or str(p) in ("", "."):
                continue
            rp = str(p.expanduser().resolve()) if p.exists() else str(p.expanduser())
            if rp in seen:
                continue
            seen.add(rp)
            if p.exists():
                out.append(rp)
        except Exception:
            continue
    return out
