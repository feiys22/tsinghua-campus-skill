"""_store.py — 只读打开已解密库；优先 campus 规范化 index.db。

不实现密钥提取。不把密钥/路径细节写进日志（仅写高层状态）。
"""
from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from _paths import decrypted_dir, index_db_path


SCHEMA_VERSION = "1"

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  talker TEXT PRIMARY KEY,
  display_name TEXT,
  kind TEXT DEFAULT 'private',
  last_time INTEGER,
  last_preview TEXT,
  unread INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  talker TEXT NOT NULL,
  sender TEXT,
  sender_wxid TEXT,
  is_from_me INTEGER DEFAULT 0,
  time_unix INTEGER NOT NULL,
  kind TEXT DEFAULT 'text',
  text TEXT
);
CREATE INDEX IF NOT EXISTS idx_wechat_msg_talker_time ON messages(talker, time_unix);
CREATE INDEX IF NOT EXISTS idx_wechat_msg_text ON messages(text);
"""


@dataclass
class StoreInfo:
    path: Path
    layout: str  # campus_index | wechat_fts_best_effort | empty
    read_only: bool = True


def _connect_ro(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = ON")
    except Exception:
        pass
    return conn


def create_writable_index(path: Path) -> sqlite3.Connection:
    """创建规范化 index.db（仅 setup / 测试 / import 使用）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(CREATE_SQL)
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
        ("schema_version", SCHEMA_VERSION),
    )
    conn.commit()
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass
    return conn


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {r[0] if not isinstance(r, sqlite3.Row) else r["name"] for r in rows}


def _is_campus_index(conn: sqlite3.Connection) -> bool:
    names = _table_names(conn)
    return {"sessions", "messages"}.issubset(names)


def find_store(home: Path) -> Optional[StoreInfo]:
    """定位可用的只读库：优先 index.db，其次 decrypted/ 下含规范化表的 .db。"""
    idx = index_db_path(home)
    if idx.exists() and idx.stat().st_size > 0:
        try:
            conn = _connect_ro(idx)
            ok = _is_campus_index(conn)
            conn.close()
            if ok:
                return StoreInfo(path=idx, layout="campus_index")
        except Exception:
            pass

    dec = decrypted_dir(home)
    if dec.exists():
        for p in sorted(dec.rglob("*.db")):
            # 跳过明显的临时/wal 名
            if p.name.endswith("-wal") or p.name.endswith("-shm"):
                continue
            try:
                conn = _connect_ro(p)
                ok = _is_campus_index(conn)
                conn.close()
                if ok:
                    return StoreInfo(path=p, layout="campus_index")
            except Exception:
                continue
    return None


def open_store(home: Path) -> tuple[sqlite3.Connection, StoreInfo]:
    info = find_store(home)
    if not info:
        raise FileNotFoundError(
            "未找到已解密可读库。请先 setup --ack，再用外部工具解密后写入 "
            f"{index_db_path(home)} 或 {decrypted_dir(home)}/（规范化 sessions/messages 表），"
            "或 wechat.py import-jsonl 导入。"
        )
    return _connect_ro(info.path), info


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def list_sessions(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT talker, display_name, kind, last_time, last_preview, unread
        FROM sessions
        ORDER BY COALESCE(last_time, 0) DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    out = []
    for r in rows:
        d = _row_to_dict(r)
        d["last_time_iso"] = _fmt_ts(d.get("last_time"))
        out.append(d)
    return out


def history(
    conn: sqlite3.Connection,
    talker: str,
    limit: int = 50,
    since: Optional[int] = None,
    until: Optional[int] = None,
) -> list[dict[str, Any]]:
    talker_key = resolve_talker(conn, talker)
    clauses = ["talker = ?"]
    args: list[Any] = [talker_key]
    if since is not None:
        clauses.append("time_unix >= ?")
        args.append(since)
    if until is not None:
        clauses.append("time_unix <= ?")
        args.append(until)
    args.append(limit)
    sql = f"""
        SELECT id, talker, sender, sender_wxid, is_from_me, time_unix, kind, text
        FROM messages
        WHERE {' AND '.join(clauses)}
        ORDER BY time_unix DESC
        LIMIT ?
    """
    rows = conn.execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = _row_to_dict(r)
        d["is_from_me"] = bool(d.get("is_from_me"))
        d["time_iso"] = _fmt_ts(d.get("time_unix"))
        out.append(d)
    out.reverse()  # chronological for reading
    return out


def search(
    conn: sqlite3.Connection,
    query: str,
    talker: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    q = f"%{query}%"
    clauses = ["text LIKE ?"]
    args: list[Any] = [q]
    resolved = None
    if talker:
        resolved = resolve_talker(conn, talker)
        clauses.append("talker = ?")
        args.append(resolved)
    args.append(limit)
    sql = f"""
        SELECT id, talker, sender, sender_wxid, is_from_me, time_unix, kind, text
        FROM messages
        WHERE {' AND '.join(clauses)}
        ORDER BY time_unix DESC
        LIMIT ?
    """
    rows = conn.execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = _row_to_dict(r)
        d["is_from_me"] = bool(d.get("is_from_me"))
        d["time_iso"] = _fmt_ts(d.get("time_unix"))
        # attach display_name if possible
        dn = conn.execute(
            "SELECT display_name FROM sessions WHERE talker = ?", (d["talker"],)
        ).fetchone()
        d["display_name"] = dn["display_name"] if dn else None
        out.append(d)
    return out


_TODO_PATTERNS = [
    re.compile(p, re.I)
    for p in [
        r"作业",
        r"ddl",
        r"截止",
        r"deadline",
        r"待办",
        r"\btodo\b",
        r"记得",
        r"别忘",
        r"明天.*交",
        r"请.*提交",
        r"考试",
        r"开会",
        r"约.*时间",
        r"务必",
        r"asap",
        r"尽快",
        r"提醒",
    ]
]


def export_todos(
    conn: sqlite3.Connection,
    talker: Optional[str] = None,
    since: Optional[int] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses = ["text IS NOT NULL", "length(trim(text)) > 0"]
    args: list[Any] = []
    if talker:
        clauses.append("talker = ?")
        args.append(resolve_talker(conn, talker))
    if since is not None:
        clauses.append("time_unix >= ?")
        args.append(since)
    args.append(max(limit * 20, 200))  # oversample then filter
    sql = f"""
        SELECT id, talker, sender, sender_wxid, is_from_me, time_unix, kind, text
        FROM messages
        WHERE {' AND '.join(clauses)}
        ORDER BY time_unix DESC
        LIMIT ?
    """
    rows = conn.execute(sql, args).fetchall()
    todos = []
    for r in rows:
        text = (r["text"] or "").strip()
        if not text:
            continue
        if not any(p.search(text) for p in _TODO_PATTERNS):
            continue
        dn = conn.execute(
            "SELECT display_name FROM sessions WHERE talker = ?", (r["talker"],)
        ).fetchone()
        todos.append(
            {
                "id": r["id"],
                "talker": r["talker"],
                "display_name": dn["display_name"] if dn else None,
                "sender": r["sender"],
                "time_unix": r["time_unix"],
                "time_iso": _fmt_ts(r["time_unix"]),
                "text": text,
                "source": "wechat_heuristic",
            }
        )
        if len(todos) >= limit:
            break
    return todos


def resolve_talker(conn: sqlite3.Connection, name_or_id: str) -> str:
    """按 talker / display_name 模糊解析。"""
    exact = conn.execute(
        "SELECT talker FROM sessions WHERE talker = ? OR display_name = ? LIMIT 1",
        (name_or_id, name_or_id),
    ).fetchone()
    if exact:
        return exact["talker"]
    like = conn.execute(
        """
        SELECT talker FROM sessions
        WHERE talker LIKE ? OR display_name LIKE ?
        ORDER BY COALESCE(last_time, 0) DESC
        LIMIT 2
        """,
        (f"%{name_or_id}%", f"%{name_or_id}%"),
    ).fetchall()
    if len(like) == 1:
        return like[0]["talker"]
    if len(like) > 1:
        raise ValueError(
            f"会话名 '{name_or_id}' 匹配到多个: {[r['talker'] for r in like]}，请用更精确的 talker"
        )
    # also search messages.talker directly
    msg = conn.execute(
        "SELECT DISTINCT talker FROM messages WHERE talker = ? OR talker LIKE ? LIMIT 1",
        (name_or_id, f"%{name_or_id}%"),
    ).fetchone()
    if msg:
        return msg["talker"]
    raise ValueError(f"未找到会话: {name_or_id}")


def import_jsonl(home: Path, jsonl_path: Path) -> dict[str, Any]:
    """从 JSONL（每行一条消息）导入到规范化 index.db。

    期望字段（宽松）: talker, text, time_unix|time|time_iso, sender, display_name, kind, is_from_me
    """
    import json

    idx = index_db_path(home)
    conn = create_writable_index(idx)
    n_msg = 0
    sessions: dict[str, dict[str, Any]] = {}
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            talker = str(obj.get("talker") or obj.get("chat") or obj.get("session") or "").strip()
            if not talker:
                continue
            text = obj.get("text") or obj.get("content") or ""
            ts = obj.get("time_unix") or obj.get("timestamp")
            if ts is None and obj.get("time_iso"):
                ts = _parse_iso(obj["time_iso"])
            if ts is None and obj.get("time"):
                try:
                    ts = int(obj["time"])
                except Exception:
                    ts = _parse_iso(str(obj["time"]))
            if ts is None:
                ts = 0
            sender = obj.get("sender") or obj.get("from") or ""
            kind = obj.get("kind") or obj.get("type") or "text"
            is_from_me = 1 if obj.get("is_from_me") in (True, 1, "1", "true") else 0
            display = obj.get("display_name") or obj.get("chat_name") or talker
            conn.execute(
                """
                INSERT INTO messages(talker, sender, sender_wxid, is_from_me, time_unix, kind, text)
                VALUES(?,?,?,?,?,?,?)
                """,
                (
                    talker,
                    sender,
                    obj.get("sender_wxid") or "",
                    is_from_me,
                    int(ts),
                    kind,
                    text,
                ),
            )
            n_msg += 1
            prev = sessions.get(talker)
            if not prev or int(ts) >= int(prev.get("last_time") or 0):
                sessions[talker] = {
                    "talker": talker,
                    "display_name": display,
                    "kind": obj.get("session_kind") or ("group" if "chatroom" in talker else "private"),
                    "last_time": int(ts),
                    "last_preview": (text or "")[:120],
                    "unread": 0,
                }
    for s in sessions.values():
        conn.execute(
            """
            INSERT INTO sessions(talker, display_name, kind, last_time, last_preview, unread)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(talker) DO UPDATE SET
              display_name=excluded.display_name,
              kind=excluded.kind,
              last_time=excluded.last_time,
              last_preview=excluded.last_preview
            """,
            (
                s["talker"],
                s["display_name"],
                s["kind"],
                s["last_time"],
                s["last_preview"],
                s["unread"],
            ),
        )
    conn.commit()
    conn.close()
    return {"messages": n_msg, "sessions": len(sessions), "index_db": str(idx)}


def _fmt_ts(ts: Any) -> Optional[str]:
    if ts is None:
        return None
    try:
        t = int(ts)
        # ms vs s
        if t > 10_000_000_000:
            t = t // 1000
        return datetime.fromtimestamp(t, tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    except Exception:
        return None


def _parse_iso(s: str) -> int:
    s = s.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return 0
