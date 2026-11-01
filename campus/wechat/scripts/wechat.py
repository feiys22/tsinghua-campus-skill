"""wechat.py — 微信子技能统一入口

调用本机 wx-cli 读取已登录的微信桌面版数据库。不走 CAS，不发消息，不标已读。

CLI:
  wechat.py status
  wechat.py sessions [--limit N] [--filter private,group]
  wechat.py unread [--limit N] [--filter private,group]
  wechat.py history --chat <名称> [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--limit N] [--type text]
  wechat.py search --query <关键词> [--chat <名称>] [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--limit N] [--type text]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "shared", "scripts"))
import common

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
FILTERS = {"all", "private", "group", "official", "folded"}
MSG_TYPES = {"text", "image", "voice", "video", "sticker", "location", "link", "file", "call", "system"}
MAX_LIMIT = 200


def _fail(message, code="wechat_error"):
    common.output_json({"status": "error", "code": code, "message": message})
    return 1


def _wx_bin():
    return shutil.which("wx") or shutil.which("wx.exe")


def _run(args, timeout=90):
    exe = _wx_bin()
    if not exe:
        return None, "未找到 wx 命令。请先安装 wx-cli，完成 wx init，并保持微信桌面版已登录。"
    common.log(f"[wechat] run {' '.join(args)}")
    try:
        proc = subprocess.run(
            [exe, *args],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, "wx 命令超时。微信桌面版可能未登录，或 wx-cli 尚未完成 init。"
    stdout = proc.stdout.decode("utf-8", "replace").strip()
    stderr = proc.stderr.decode("utf-8", "replace").strip()
    if proc.returncode != 0:
        detail = stderr or stdout or f"exit {proc.returncode}"
        return None, detail[:300]
    return stdout, None


def _parse_json(text, kind):
    if not text:
        return _fail(f"wx {kind} 没有返回内容", "empty_output")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return _fail(f"wx {kind} 返回的不是 JSON", "bad_json")
    common.output_json({"status": "ok", "type": kind, "data": data})
    return 0


def _limit(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("limit 必须是整数")
    if number < 1 or number > MAX_LIMIT:
        raise argparse.ArgumentTypeError(f"limit 必须在 1 到 {MAX_LIMIT} 之间")
    return number


def _date(value):
    if not DATE_RE.match(value):
        raise argparse.ArgumentTypeError("日期必须是 YYYY-MM-DD")
    return value


def _filters(value):
    parts = [p.strip() for p in value.split(",") if p.strip()]
    bad = [p for p in parts if p not in FILTERS]
    if not parts or bad:
        raise argparse.ArgumentTypeError("filter 只能是 all/private/group/official/folded")
    return parts


def cmd_status():
    exe = _wx_bin()
    if not exe:
        return _fail("未找到 wx 命令。请先安装 wx-cli，完成 wx init，并保持微信桌面版已登录。", "wx_missing")
    text, err = _run(["--version"], timeout=20)
    if err:
        return _fail(err, "wx_version_failed")
    common.output_json({
        "status": "ok",
        "type": "status",
        "wx": exe,
        "version": (text or "").splitlines()[0][:80],
        "pin_supported": False,
        "note": "会话列表没有可靠置顶字段。不能把最近会话当成置顶。",
    })
    return 0


def cmd_sessions(limit, filters):
    text, err = _run(["sessions", "--json", "-n", str(limit)])
    if err:
        return _fail(err, "sessions_failed")
    try:
        data = json.loads(text or "[]")
    except json.JSONDecodeError:
        return _fail("wx sessions 返回的不是 JSON", "bad_json")
    if filters and "all" not in filters:
        data = [item for item in data if item.get("chat_type") in filters]
    common.output_json({
        "status": "ok",
        "type": "sessions",
        "pin_supported": False,
        "data": data,
    })
    return 0


def cmd_unread(limit, filters):
    args = ["unread", "--json", "-n", str(limit)]
    if filters:
        args.extend(["--filter", ",".join(filters)])
    text, err = _run(args)
    if err:
        return _fail(err, "unread_failed")
    return _parse_json(text, "unread")


def cmd_history(chat, since, until, limit, msg_type):
    args = ["history", chat, "--json", "-n", str(limit)]
    if since:
        args.extend(["--since", since])
    if until:
        args.extend(["--until", until])
    if msg_type:
        args.extend(["--type", msg_type])
    text, err = _run(args)
    if err:
        return _fail(err, "history_failed")
    return _parse_json(text, "history")


def cmd_search(query, chat, since, until, limit, msg_type):
    args = ["search", query, "--json", "-n", str(limit)]
    if chat:
        args.extend(["--in", chat])
    if since:
        args.extend(["--since", since])
    if until:
        args.extend(["--until", until])
    if msg_type:
        args.extend(["--type", msg_type])
    text, err = _run(args)
    if err:
        return _fail(err, "search_failed")
    return _parse_json(text, "search")


def main():
    ap = argparse.ArgumentParser(description="读取本机微信消息（wx-cli）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="检查 wx-cli 是否可用")

    sp = sub.add_parser("sessions", help="最近会话")
    sp.add_argument("--limit", type=_limit, default=20)
    sp.add_argument("--filter", type=_filters, default=None)

    up = sub.add_parser("unread", help="未读会话")
    up.add_argument("--limit", type=_limit, default=20)
    up.add_argument("--filter", type=_filters, default=None)

    hp = sub.add_parser("history", help="查看一个会话")
    hp.add_argument("--chat", required=True)
    hp.add_argument("--since", type=_date)
    hp.add_argument("--until", type=_date)
    hp.add_argument("--limit", type=_limit, default=50)
    hp.add_argument("--type", dest="msg_type", choices=sorted(MSG_TYPES))

    qp = sub.add_parser("search", help="按关键词搜索")
    qp.add_argument("--query", required=True)
    qp.add_argument("--chat")
    qp.add_argument("--since", type=_date)
    qp.add_argument("--until", type=_date)
    qp.add_argument("--limit", type=_limit, default=20)
    qp.add_argument("--type", dest="msg_type", choices=sorted(MSG_TYPES))

    args = ap.parse_args()
    if args.cmd == "status":
        code = cmd_status()
    elif args.cmd == "sessions":
        code = cmd_sessions(args.limit, args.filter)
    elif args.cmd == "unread":
        code = cmd_unread(args.limit, args.filter)
    elif args.cmd == "history":
        code = cmd_history(args.chat, args.since, args.until, args.limit, args.msg_type)
    else:
        code = cmd_search(args.query, args.chat, args.since, args.until, args.limit, args.msg_type)
    return code


if __name__ == "__main__":
    sys.exit(main())
