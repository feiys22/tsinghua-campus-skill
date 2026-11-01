"""wechat.py — 微信本地消息只读薄封装（campus/wechat 统一入口）

不包含密钥提取/逆向代码。

后端优先级：
  1) 本机已安装的 wx-cli（`wx`，参考 https://github.com/jackwener/wx-cli-again）
  2) 私有目录下已解密的规范化 index.db / decrypted/*.db（wcdb-key-tool / wxextract / import-jsonl）

CLI（对齐 wx-cli 常用动词，campus 统一 --flag 风格）:
  wechat.py setup --ack
  wechat.py status
  wechat.py sessions [--limit N]
  wechat.py history --talker NAME [--limit N] [--since ...] [--until ...]
  wechat.py search --query Q [--in TALKER] [--limit N]
  wechat.py export-todos [--talker NAME] [--since UNIX] [--days N] [--limit N]
  wechat.py import-jsonl --file PATH
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "shared", "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common  # noqa: E402
from _backends import detect_status_extra  # noqa: E402
from _config import is_acked, load_config, require_ack, write_ack  # noqa: E402
from _paths import (  # noqa: E402
    candidate_wechat_data_dirs,
    decrypted_dir,
    default_home,
    ensure_home,
    index_db_path,
)
from _store import (  # noqa: E402
    export_todos as store_export_todos,
    find_store,
    history as store_history,
    import_jsonl,
    list_sessions as store_list_sessions,
    open_store,
    search as store_search,
)
from _wxcli import doctor as wx_doctor  # noqa: E402
from _wxcli import find_wx_binary, history as wx_history  # noqa: E402
from _wxcli import search as wx_search  # noqa: E402
from _wxcli import sessions as wx_sessions  # noqa: E402
from _wxcli import wx_probe  # noqa: E402


def _home() -> Path:
    return ensure_home(default_home())


def _fail(message: str, **extra):
    common.output_json({"status": "error", "message": message, **extra})
    sys.exit(1)


def _guard(home: Path):
    try:
        require_ack(home)
    except PermissionError as e:
        _fail(str(e), need="setup --ack")


def _prefer_wx(args) -> bool:
    """是否走 wx-cli。可用 --backend index|wx|auto 覆盖。"""
    backend = getattr(args, "backend", "auto") or "auto"
    if backend == "index":
        return False
    if backend == "wx":
        return True
    # auto
    force = os.environ.get("CAMPUS_WECHAT_BACKEND", "").strip().lower()
    if force == "index":
        return False
    if force == "wx":
        return True
    return find_wx_binary() is not None


def _wx_init_hint(exc: Optional[BaseException] = None) -> str:
    """未 init / daemon 失败时的统一下一步提示（不含密钥）。"""
    base = (
        "本机已装 wx 时请保持微信已登录，在终端执行：sudo wx init"
        "（ptrace_scope=1 需要 root；成功后日常 sessions/history 无需 sudo）。"
        "或改用 import-jsonl / 放入 index.db。"
    )
    if exc is None:
        return base
    msg = str(exc)
    if len(msg) > 180:
        msg = msg[:180] + "…"
    return f"wx-cli 调用失败：{msg}。{base}"


def _since_until_for_wx(since: Optional[int], until: Optional[int]) -> tuple[Optional[str], Optional[str]]:
    """wx-cli 接受 YYYY-MM-DD 或可解析日期；有 unix 则转本地日期。"""
    def fmt(ts: Optional[int]) -> Optional[str]:
        if ts is None:
            return None
        try:
            t = int(ts)
            if t > 10_000_000_000:
                t //= 1000
            return datetime.fromtimestamp(t).strftime("%Y-%m-%d")
        except Exception:
            return None
    return fmt(since), fmt(until)


_TODO_PATTERNS = [
    re.compile(p, re.I)
    for p in [
        r"作业", r"ddl", r"截止", r"deadline", r"待办", r"\btodo\b",
        r"记得", r"别忘", r"明天.*交", r"请.*提交", r"考试", r"开会",
        r"约.*时间", r"务必", r"asap", r"尽快", r"提醒",
    ]
]


def _msg_text(m: dict) -> str:
    for k in ("text", "content", "body", "message", "preview"):
        v = m.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _heuristic_todos_from_messages(messages: list[dict], limit: int) -> list[dict]:
    todos = []
    for m in messages:
        text = _msg_text(m)
        if not text or not any(p.search(text) for p in _TODO_PATTERNS):
            continue
        todos.append(
            {
                "talker": m.get("talker") or m.get("username") or m.get("chat"),
                "display_name": m.get("display_name") or m.get("display") or m.get("chat_name"),
                "sender": m.get("sender") or m.get("sender_contact_display"),
                "sender_username": m.get("sender_username"),
                "time": m.get("time") or m.get("time_iso") or m.get("timestamp"),
                "text": text,
                "chat_type": m.get("chat_type"),
                "source": "wechat_heuristic",
                "raw_id": m.get("id") or m.get("local_id"),
            }
        )
        if len(todos) >= limit:
            break
    return todos


def cmd_setup(args):
    home = _home()
    if not args.ack:
        _fail(
            "首次使用必须确认风险：加 --ack。"
            "详见 campus/wechat/SKILL.md「合规与风险」。"
        )
    info = write_ack(home, note=args.note or "")
    common.log("[wechat] tos acknowledged; private home ready")
    probe = wx_probe()
    common.output_json(
        {
            "status": "ok",
            "type": "setup",
            "ack": info,
            "preferred_backend": "wx-cli" if probe.get("found") else "index.db",
            "wx_cli": probe,
            "next": [
                "优先安装 wx-cli（参考 https://github.com/jackwener/wx-cli-again ），然后 sudo wx init / 管理员 wx init",
                "或用 wcdb-key-tool/wxextract 解密后 import-jsonl / 放入 index.db",
                "然后 wechat.py status / sessions",
            ],
            "platform": common.detect_platform(),
        }
    )


def cmd_status(args):
    home = _home()
    store = None
    try:
        store = find_store(home)
    except Exception:
        store = None
    extra = detect_status_extra()
    cfg = load_config(home)
    probe = wx_probe()
    doctor = None
    if probe.get("found") and is_acked(home) and not getattr(args, "skip_doctor", False):
        try:
            doctor = wx_doctor()
        except Exception as e:
            doctor = {"status": "error", "message": str(e)[:160]}
    preferred = "wx-cli" if probe.get("found") else ("campus_index" if store else None)
    common.output_json(
        {
            "status": "ok",
            "type": "status",
            "platform": common.detect_platform(),
            "home": str(home),
            "ack_tos": is_acked(home),
            "preferred_backend": preferred,
            "wx_cli": probe,
            "wx_doctor": doctor,
            "index_db": str(index_db_path(home)),
            "index_db_exists": index_db_path(home).exists(),
            "decrypted_dir": str(decrypted_dir(home)),
            "store": (
                {"path": str(store.path), "layout": store.layout} if store else None
            ),
            "config_keys": sorted(cfg.keys()),
            "wechat_data_dirs_found": candidate_wechat_data_dirs(),
            "tools": extra.get("tools"),
            "read_only": True,
            "vendors_key_extraction": False,
            "reference": "https://github.com/jackwener/wx-cli-again",
            "note": "本模块不提取密钥；优先调用本机 wx；否则只读规范化解密库。",
        }
    )


def cmd_sessions(args):
    home = _home()
    _guard(home)
    wx_err: Optional[BaseException] = None
    if _prefer_wx(args):
        try:
            data = wx_sessions(limit=args.limit)
            common.output_json(
                {
                    "status": "ok",
                    "type": "sessions",
                    "backend": "wx-cli",
                    "count": len(data.get("sessions") or []),
                    "sessions": data.get("sessions") or [],
                    "meta": data.get("meta"),
                }
            )
            return
        except Exception as e:
            wx_err = e
            if getattr(args, "backend", "auto") == "wx":
                _fail(f"wx-cli 失败: {e}", hint=_wx_init_hint(e))
            common.log("[wechat] wx sessions failed; fallback index")
    try:
        conn, info = open_store(home)
    except FileNotFoundError as e:
        _fail(str(e), hint=_wx_init_hint(wx_err))
    try:
        items = store_list_sessions(conn, limit=args.limit)
        common.output_json(
            {
                "status": "ok",
                "type": "sessions",
                "backend": "campus_index",
                "store": {"path": str(info.path), "layout": info.layout},
                "count": len(items),
                "sessions": items,
                "meta": {"status": "ok"},
            }
        )
    finally:
        conn.close()


def cmd_history(args):
    home = _home()
    _guard(home)
    talker = args.talker
    if _prefer_wx(args):
        since_s, until_s = _since_until_for_wx(args.since, args.until)
        try:
            data = wx_history(talker, limit=args.limit, since=since_s, until=until_s)
            common.output_json(
                {
                    "status": "ok",
                    "type": "history",
                    "backend": "wx-cli",
                    "talker_query": talker,
                    "count": len(data.get("messages") or []),
                    "messages": data.get("messages") or [],
                    "meta": data.get("meta"),
                }
            )
            return
        except Exception as e:
            wx_err = e
            if getattr(args, "backend", "auto") == "wx":
                _fail(f"wx-cli 失败: {e}", hint=_wx_init_hint(e))
            common.log("[wechat] wx history failed; fallback index")
    else:
        wx_err = None
    try:
        conn, info = open_store(home)
    except FileNotFoundError as e:
        _fail(str(e), hint=_wx_init_hint(wx_err))
    try:
        items = store_history(
            conn, talker=talker, limit=args.limit, since=args.since, until=args.until
        )
        common.output_json(
            {
                "status": "ok",
                "type": "history",
                "backend": "campus_index",
                "talker_query": talker,
                "store": {"path": str(info.path), "layout": info.layout},
                "count": len(items),
                "messages": items,
                "meta": {"status": "ok"},
            }
        )
    except ValueError as e:
        _fail(str(e))
    finally:
        conn.close()


def cmd_search(args):
    home = _home()
    _guard(home)
    if _prefer_wx(args):
        try:
            data = wx_search(
                args.query, talker=args.in_talker, limit=args.limit, since=None
            )
            common.output_json(
                {
                    "status": "ok",
                    "type": "search",
                    "backend": "wx-cli",
                    "query": args.query,
                    "in": args.in_talker,
                    "count": len(data.get("messages") or []),
                    "messages": data.get("messages") or [],
                    "meta": data.get("meta"),
                }
            )
            return
        except Exception as e:
            wx_err = e
            if getattr(args, "backend", "auto") == "wx":
                _fail(f"wx-cli 失败: {e}", hint=_wx_init_hint(e))
            common.log("[wechat] wx search failed; fallback index")
    else:
        wx_err = None
    try:
        conn, info = open_store(home)
    except FileNotFoundError as e:
        _fail(str(e), hint=_wx_init_hint(wx_err))
    try:
        items = store_search(conn, query=args.query, talker=args.in_talker, limit=args.limit)
        common.output_json(
            {
                "status": "ok",
                "type": "search",
                "backend": "campus_index",
                "query": args.query,
                "in": args.in_talker,
                "store": {"path": str(info.path), "layout": info.layout},
                "count": len(items),
                "messages": items,
                "meta": {"status": "ok"},
            }
        )
    except ValueError as e:
        _fail(str(e))
    finally:
        conn.close()


def cmd_export_todos(args):
    home = _home()
    _guard(home)
    since = args.since
    if since is None and args.days is not None:
        since = int((datetime.now(tz=timezone.utc) - timedelta(days=args.days)).timestamp())

    if _prefer_wx(args):
        try:
            # pull a window of messages then heuristic-filter
            if args.talker:
                since_s, _ = _since_until_for_wx(since, None)
                data = wx_history(args.talker, limit=max(args.limit * 20, 200), since=since_s)
                messages = data.get("messages") or []
                meta = data.get("meta")
            else:
                # search common keywords via wx search and merge
                messages = []
                meta = {"status": "ok", "merged_queries": True}
                for kw in ("作业", "ddl", "截止", "开会", "提醒", "todo"):
                    try:
                        part = wx_search(kw, talker=None, limit=args.limit)
                        messages.extend(part.get("messages") or [])
                    except Exception:
                        continue
            todos = _heuristic_todos_from_messages(messages, args.limit)
            common.output_json(
                {
                    "status": "ok",
                    "type": "export_todos",
                    "backend": "wx-cli",
                    "count": len(todos),
                    "todos": todos,
                    "meta": meta,
                    "heuristic": True,
                    "note": "基于关键词启发式抽取，需人工确认后再写入待办系统。",
                }
            )
            return
        except Exception as e:
            wx_err = e
            if getattr(args, "backend", "auto") == "wx":
                _fail(f"wx-cli 失败: {e}", hint=_wx_init_hint(e))
            common.log("[wechat] wx export-todos failed; fallback index")
    else:
        wx_err = None

    try:
        conn, info = open_store(home)
    except FileNotFoundError as e:
        _fail(str(e), hint=_wx_init_hint(wx_err))
    try:
        items = store_export_todos(
            conn, talker=args.talker, since=since, limit=args.limit
        )
        common.output_json(
            {
                "status": "ok",
                "type": "export_todos",
                "backend": "campus_index",
                "store": {"path": str(info.path), "layout": info.layout},
                "count": len(items),
                "todos": items,
                "meta": {"status": "ok"},
                "heuristic": True,
                "note": "基于关键词启发式抽取，需人工确认后再写入待办系统。",
            }
        )
    except ValueError as e:
        _fail(str(e))
    finally:
        conn.close()


def cmd_import_jsonl(args):
    home = _home()
    _guard(home)
    path = Path(args.file).expanduser()
    if not path.is_file():
        _fail(f"文件不存在: {path}")
    try:
        result = import_jsonl(home, path)
        common.log("[wechat] import-jsonl done")
        common.output_json({"status": "ok", "type": "import_jsonl", "backend": "campus_index", **result})
    except Exception as e:
        _fail(f"导入失败: {str(e)[:200]}")


def _add_backend_flag(p):
    p.add_argument(
        "--backend",
        choices=["auto", "wx", "index"],
        default="auto",
        help="auto=优先 wx-cli；wx=强制；index=只用规范化解密库",
    )


def main():
    ap = argparse.ArgumentParser(prog="wechat.py", description="campus/wechat 只读薄封装")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_setup = sub.add_parser("setup", help="初始化私有目录；首次必须 --ack")
    p_setup.add_argument("--ack", action="store_true", help="确认已阅读 ToS/账号风险说明")
    p_setup.add_argument("--note", default="", help="可选备注（不写密钥）")
    p_setup.set_defaults(func=cmd_setup)

    p_status = sub.add_parser("status", help="平台/确认/工具/库状态")
    p_status.add_argument("--skip-doctor", action="store_true", help="跳过 wx doctor")
    p_status.set_defaults(func=cmd_status)

    p_sess = sub.add_parser("sessions", help="最近会话（对齐 wx sessions）")
    p_sess.add_argument("--limit", "-n", type=int, default=50)
    _add_backend_flag(p_sess)
    p_sess.set_defaults(func=cmd_sessions)

    p_hist = sub.add_parser("history", help="某会话历史（对齐 wx history）")
    p_hist.add_argument("--talker", required=True, help="昵称/备注/群名/talker id")
    p_hist.add_argument("--limit", "-n", type=int, default=50)
    p_hist.add_argument("--since", type=int, default=None, help="unix 秒（index）；wx 后端会转成日期")
    p_hist.add_argument("--until", type=int, default=None)
    _add_backend_flag(p_hist)
    p_hist.set_defaults(func=cmd_history)

    p_search = sub.add_parser("search", help="关键词搜索（对齐 wx search）")
    p_search.add_argument("--query", "-q", required=True)
    p_search.add_argument("--in", dest="in_talker", default=None)
    p_search.add_argument("--limit", "-n", type=int, default=50)
    _add_backend_flag(p_search)
    p_search.set_defaults(func=cmd_search)

    p_todo = sub.add_parser("export-todos", help="启发式导出待办候选")
    p_todo.add_argument("--talker", default=None)
    p_todo.add_argument("--since", type=int, default=None)
    p_todo.add_argument("--days", type=int, default=14)
    p_todo.add_argument("--limit", "-n", type=int, default=50)
    _add_backend_flag(p_todo)
    p_todo.set_defaults(func=cmd_export_todos)

    p_imp = sub.add_parser("import-jsonl", help="导入 JSONL 到规范化 index.db（无 wx 时的后备）")
    p_imp.add_argument("--file", required=True)
    p_imp.set_defaults(func=cmd_import_jsonl)

    args = ap.parse_args()
    try:
        args.func(args)
    except BrokenPipeError:
        pass
    except SystemExit:
        raise
    except Exception as e:
        common.log(f"[wechat] unhandled: {type(e).__name__}")
        common.output_json({"status": "error", "message": str(e)[:300]})
        sys.exit(1)


if __name__ == "__main__":
    main()
