"""_backends.py — 探测用户本机已安装的解密/导出工具（不调用抽 key）。

只做 which / 路径存在性检查，供 status 汇报。真正解密由用户按 SKILL.md 自行执行。
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from _paths import candidate_wechat_data_dirs


def which_tools() -> dict[str, Any]:
    """探测常见 CLI 是否在 PATH / 常见路径。"""
    # 延迟导入，避免循环
    try:
        from _wxcli import wx_probe
        wx = wx_probe()
    except Exception as e:
        wx = {"found": False, "path": None, "error": str(e)[:120]}
    tools = {
        "wx_cli": wx,  # 优先：jackwener/wx-cli-again 系 `wx` 二进制
        "wcdb_key_tool": _find_wcdb_key_tool(),
        "wxextract": _find_cmd("wxextract"),
        "wxchat_export": _find_cmd("wxchat-export"),
        "gdb": _find_cmd("gdb"),
    }
    return tools


def _find_cmd(name: str) -> dict[str, Any]:
    path = shutil.which(name)
    return {"found": bool(path), "path": path}


def _find_wcdb_key_tool() -> dict[str, Any]:
    """wcdb-key-tool 多为单文件脚本，不在 PATH；探测常见 clone 位置与 env。"""
    env = os.environ.get("WCDB_KEY_TOOL", "").strip()
    cands: list[Path] = []
    if env:
        cands.append(Path(env).expanduser())
    home = Path.home()
    cands.extend(
        [
            home / "src" / "wcdb-key-tool" / "wcdb_key_tool.py",
            home / "src" / "wcdb-key-tool" / "wcdb_key_tool_windows.py",
            home / "tools" / "wcdb-key-tool" / "wcdb_key_tool.py",
            home / "tools" / "wcdb-key-tool" / "wcdb_key_tool_windows.py",
            home / "wcdb-key-tool" / "wcdb_key_tool.py",
            home / "wcdb-key-tool" / "wcdb_key_tool_windows.py",
        ]
    )
    # also accept directory pointing to repo
    for p in list(cands):
        if p.is_dir():
            cands.append(p / "wcdb_key_tool.py")
            cands.append(p / "wcdb_key_tool_windows.py")
    for p in cands:
        try:
            if p.is_file():
                return {"found": True, "path": str(p.resolve())}
        except Exception:
            continue
    return {
        "found": False,
        "path": None,
        "hint": "git clone https://github.com/TANGandXUE/wcdb-key-tool 并用 WCDB_KEY_TOOL 指向脚本",
    }


def detect_status_extra() -> dict[str, Any]:
    return {
        "tools": which_tools(),
        "wechat_data_dirs_found": candidate_wechat_data_dirs(),
    }
