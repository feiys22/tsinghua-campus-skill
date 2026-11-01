"""_wxcli.py — 优先后端：用户本机安装的 wx-cli（参考 jackwener/wx-cli-again）。

不 vendoring 其抽 key 代码；仅 subprocess 调用已安装的 `wx` 二进制，
要求 `--json`，并把输出规整为 campus/wechat 统一 JSON。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional


def find_wx_binary() -> Optional[str]:
    env = os.environ.get("WX_CLI", "").strip() or os.environ.get("CAMPUS_WX_CLI", "").strip()
    if env:
        p = Path(env).expanduser()
        if p.is_file():
            return str(p.resolve())
    for name in ("wx", "wx.exe", "wx-cli"):
        path = shutil.which(name)
        if path:
            return path
    # common user-local installs
    home = Path.home()
    for p in (
        home / ".local" / "bin" / "wx",
        home / ".wx-cli" / "bin" / "wx",
        Path("/usr/local/bin/wx"),
    ):
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return None


def wx_probe() -> dict[str, Any]:
    bin_path = find_wx_binary()
    if not bin_path:
        return {
            "found": False,
            "path": None,
            "version": None,
            "hint": "安装参考 https://github.com/jackwener/wx-cli-again （二进制现多在 botiverse/wx-cli，需权限或源码构建）",
        }
    version = None
    try:
        r = subprocess.run(
            [bin_path, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        version = (r.stdout or r.stderr or "").strip().splitlines()[0][:80] if (r.stdout or r.stderr) else None
    except Exception:
        version = None
    return {"found": True, "path": bin_path, "version": version, "reference": "https://github.com/jackwener/wx-cli-again"}


def run_wx(args: list[str], timeout: int = 60) -> dict[str, Any]:
    """运行 `wx ... --json`，返回解析后的 dict；失败抛 RuntimeError。

    固定 cwd 为用户 HOME，避免在其它项目目录下误读 ./config.json
    （wx-cli 会优先 cwd 的 config.json，未 init 时还会默认写到 cwd）。
    """
    bin_path = find_wx_binary()
    if not bin_path:
        raise RuntimeError("未找到 wx 二进制（wx-cli）")
    cmd = [bin_path, *args]
    if "--json" not in cmd:
        cmd.append("--json")
    # Never log full cmd with secrets — there should be none; still avoid dumping stdout to log.
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=str(Path.home()),
        env={**os.environ, "HOME": str(Path.home())},
    )
    raw = (r.stdout or "").strip()
    if not raw:
        err = (r.stderr or "").strip()[:300]
        raise RuntimeError(f"wx 无 stdout（exit={r.returncode}）: {err or 'empty'}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # some builds wrap multiple JSON docs; take last object-looking blob
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            data = json.loads(raw[start : end + 1])
        else:
            raise RuntimeError(f"wx 输出非 JSON: {raw[:200]}")
    if not isinstance(data, dict):
        # list-only responses → wrap
        data = {"items": data}
    data.setdefault("_wx_exit", r.returncode)
    return data


def _pick_list(data: dict[str, Any], *keys: str) -> list:
    for k in keys:
        v = data.get(k)
        if isinstance(v, list):
            return v
    # sometimes top-level is under "data"
    inner = data.get("data")
    if isinstance(inner, dict):
        for k in keys:
            v = inner.get(k)
            if isinstance(v, list):
                return v
    return []


def sessions(limit: int = 50) -> dict[str, Any]:
    data = run_wx(["sessions", "-n", str(limit)])
    items = _pick_list(data, "sessions", "items", "data")
    # trim if wx ignored -n
    if len(items) > limit:
        items = items[:limit]
    return {
        "sessions": items,
        "meta": data.get("meta"),
        "raw_keys": sorted(data.keys()),
    }


def history(talker: str, limit: int = 50, since: Optional[str] = None, until: Optional[str] = None) -> dict[str, Any]:
    args = ["history", talker, "-n", str(limit)]
    if since:
        args.extend(["--since", str(since)])
    if until:
        args.extend(["--until", str(until)])
    data = run_wx(args)
    items = _pick_list(data, "messages", "items", "history", "data")
    if len(items) > limit:
        items = items[:limit]
    return {
        "messages": items,
        "meta": data.get("meta"),
        "talker": talker,
    }


def search(query: str, talker: Optional[str] = None, limit: int = 50, since: Optional[str] = None) -> dict[str, Any]:
    args = ["search", query, "-n", str(limit)]
    if talker:
        args.extend(["--in", talker])
    if since:
        args.extend(["--since", str(since)])
    data = run_wx(args)
    items = _pick_list(data, "messages", "items", "results", "data")
    if len(items) > limit:
        items = items[:limit]
    return {
        "messages": items,
        "meta": data.get("meta"),
        "query": query,
        "in": talker,
    }


def doctor() -> dict[str, Any]:
    try:
        return run_wx(["doctor", "--fix"])
    except Exception as e:
        return {"status": "error", "message": str(e)[:200]}
