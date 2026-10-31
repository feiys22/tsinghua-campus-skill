"""构建合成规范化 index.db（无真实微信数据），供冒烟测试。"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "campus" / "wechat" / "scripts"))
from _store import create_writable_index  # noqa: E402


def build(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = create_writable_index(path)
    now = int(time.time())
    sessions = [
        ("wxid_alice", "Alice同学", "private", now - 60, "记得交作业 ddl 明天", 1),
        ("coursegroup@chatroom", "学堂互助群", "group", now - 120, "本周五开会", 0),
        ("wxid_bob", "Bob", "private", now - 3600, "晚上吃啥", 0),
    ]
    for s in sessions:
        conn.execute(
            "INSERT INTO sessions(talker, display_name, kind, last_time, last_preview, unread) VALUES(?,?,?,?,?,?)",
            s,
        )
    messages = [
        ("wxid_alice", "Alice同学", "wxid_alice", 0, now - 3600, "text", "你好"),
        ("wxid_alice", "Alice同学", "wxid_alice", 0, now - 60, "text", "记得交作业 ddl 明天，别忘了"),
        ("wxid_alice", "me", "wxid_me", 1, now - 50, "text", "好的我写上待办"),
        ("coursegroup@chatroom", "组长", "wxid_lead", 0, now - 200, "text", "本周五开会，务必到场"),
        ("coursegroup@chatroom", "me", "wxid_me", 1, now - 120, "text", "收到"),
        ("wxid_bob", "Bob", "wxid_bob", 0, now - 3600, "text", "晚上吃啥"),
    ]
    for m in messages:
        conn.execute(
            "INSERT INTO messages(talker, sender, sender_wxid, is_from_me, time_unix, kind, text) VALUES(?,?,?,?,?,?,?)",
            m,
        )
    conn.commit()
    conn.close()
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out = build(Path(args.out))
    print(out)


if __name__ == "__main__":
    main()
