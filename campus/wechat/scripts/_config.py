"""_config.py — campus/wechat 本地配置（仓外 config.json + ToS 确认）。"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from _paths import ack_path, config_path, decrypted_dir, ensure_home, index_db_path


def load_config(home: Path) -> dict[str, Any]:
    p = config_path(home)
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(home: Path, data: dict[str, Any]) -> Path:
    ensure_home(home)
    p = config_path(home)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(p)
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass
    return p


def is_acked(home: Path) -> bool:
    if ack_path(home).exists():
        return True
    cfg = load_config(home)
    return bool(cfg.get("ack_tos"))


def require_ack(home: Path) -> None:
    if not is_acked(home):
        raise PermissionError(
            "尚未确认微信本地读取的合规风险。请先运行: "
            "python wechat.py setup --ack"
        )


def write_ack(home: Path, note: str = "") -> dict[str, Any]:
    ensure_home(home)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    ack = ack_path(home)
    with open(ack, "w", encoding="utf-8") as f:
        f.write(
            "I acknowledge that reading WeChat local databases via third-party "
            "decryption may violate WeChat ToS and carry account/legal risk.\n"
            f"acked_at={ts}\n"
        )
        if note:
            f.write(f"note={note}\n")
    try:
        os.chmod(ack, 0o600)
    except Exception:
        pass
    cfg = load_config(home)
    cfg.update(
        {
            "ack_tos": True,
            "ack_time": ts,
            "home": str(home),
            "decrypted_dir": str(decrypted_dir(home)),
            "index_db": str(index_db_path(home)),
        }
    )
    save_config(home, cfg)
    return {"ack_tos": True, "ack_time": ts, "ack_file": str(ack), "home": str(home)}
