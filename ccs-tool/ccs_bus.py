#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ccs_bus.py - ccs-tool 的本地多 agent 消息总线。

仅使用 Python 标准库（sqlite3 / argparse / json），数据库使用 WAL 模式，
可被多个 ccs 会话或守护进程并发读写。

数据库位置
    CCS_HOME/bus.sqlite3
    CCS_HOME 未设置时默认 ~/.ccs（Windows 即 %USERPROFILE%/.ccs）

数据表
    peers(name PRIMARY KEY, first_seen, last_seen)
    groups(name, member, PRIMARY KEY(name, member))
    messages(id INTEGER PRIMARY KEY AUTOINCREMENT, ts, sender, target,
             group_name, body, read INTEGER DEFAULT 0)

投递语义
    inbox(as_name) 返回 target == as_name 的消息，以及 group_name 属于
    as_name 已加入的组的消息。
    send() 会自动 upsert 发送者与直接收件人，并刷新 last_seen。

库函数
    send(sender, body, to=None, group=None) -> int
    inbox(as_name, limit=50, unread_only=False, mark_read=True) -> list[dict]
    peers() -> list[dict]
    groups() -> dict[str, list[str]]
    join_group(name, group) -> bool
    leave_group(name, group) -> bool

命令行
    python ccs_bus.py send --from X (--to Y | --group G) "msg"
    python ccs_bus.py inbox --as X [--limit N] [--unread] [--json]
    python ccs_bus.py peers [--json]
    python ccs_bus.py groups [--json]
    python ccs_bus.py join --as X --group G
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from contextlib import contextmanager
from datetime import datetime

__all__ = [
    "home",
    "db_path",
    "connect",
    "send",
    "inbox",
    "peers",
    "groups",
    "join_group",
    "leave_group",
    "format_ts",
    "format_message",
    "main",
]

DB_NAME = "bus.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS peers (
    name TEXT PRIMARY KEY,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS groups (
    name TEXT NOT NULL,
    member TEXT NOT NULL,
    PRIMARY KEY (name, member)
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    sender TEXT,
    target TEXT,
    group_name TEXT,
    body TEXT NOT NULL,
    read INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_messages_target ON messages(target);
CREATE INDEX IF NOT EXISTS idx_messages_group ON messages(group_name);
"""


# ---------------------------------------------------------------------------
# 路径与连接
# ---------------------------------------------------------------------------

def home() -> str:
    """返回 ccs 状态目录：CCS_HOME 优先，否则用户目录下的 .ccs。"""
    custom = os.environ.get("CCS_HOME")
    if custom:
        return os.path.abspath(os.path.expanduser(custom))
    return os.path.join(os.path.expanduser("~"), ".ccs")


def db_path() -> str:
    """返回总线数据库的绝对路径（CCS_HOME/bus.sqlite3）。"""
    return os.path.join(home(), DB_NAME)


def connect() -> sqlite3.Connection:
    """打开（必要时创建）总线数据库，并确保 WAL 模式与表结构就绪。"""
    directory = home()
    os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(db_path(), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


@contextmanager
def _db():
    """短连接事务上下文：正常提交，异常回滚，最后关闭。"""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except BaseException:
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


def _peer_name(value, default=None):
    """把可能是 None / 非字符串的 peer 名规范成去空白字符串。"""
    if value is None:
        return default
    name = str(value).strip()
    return name or default


def _touch_peer(conn: sqlite3.Connection, name: str, ts: float) -> None:
    """upsert peers：首次出现记录 first_seen，每次都刷新 last_seen。"""
    conn.execute(
        "INSERT INTO peers(name, first_seen, last_seen) VALUES(?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET last_seen = excluded.last_seen",
        (name, float(ts), float(ts)),
    )


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------

def send(sender, body, to=None, group=None) -> int:
    """投递一条消息，返回新消息 id。

    sender: 发送者名字（空则记为 "unknown"）
    body:   消息正文（任意类型会被 str()）
    to:     直接收件人名字，可选
    group:  组名，可选；组内成员都会在 inbox 里看到
    """
    sender = _peer_name(sender, "unknown")
    target = _peer_name(to)
    group_name = _peer_name(group)
    if body is None:
        body = ""
    elif not isinstance(body, str):
        body = str(body)
    ts = time.time()
    with _db() as conn:
        _touch_peer(conn, sender, ts)
        if target:
            _touch_peer(conn, target, ts)
        cursor = conn.execute(
            "INSERT INTO messages(ts, sender, target, group_name, body, read) "
            "VALUES(?, ?, ?, ?, ?, 0)",
            (ts, sender, target, group_name, body),
        )
        return int(cursor.lastrowid)


def inbox(as_name, limit=50, unread_only=False, mark_read=True) -> list:
    """读取发给 as_name 的消息（含其加入的组），按时间从旧到新返回。

    返回 list[dict]，键为 id, ts, sender, target, group_name, body, read。
    默认会把这些消息标记为已读（mark_read=False 可保留未读）。
    最多返回最近 limit 条。
    """
    as_name = _peer_name(as_name, "unknown")
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 50
    if limit <= 0:
        limit = 50

    sql = (
        "SELECT id, ts, sender, target, group_name, body, read "
        "FROM messages "
        "WHERE (target = ? OR (group_name IS NOT NULL AND group_name IN "
        "(SELECT name FROM groups WHERE member = ?)))"
    )
    params = [as_name, as_name]
    if unread_only:
        sql += " AND read = 0"
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    with _db() as conn:
        _touch_peer(conn, as_name, time.time())
        rows = conn.execute(sql, params).fetchall()
        rows = list(reversed(rows))
        ids = [int(row["id"]) for row in rows]
        if mark_read and ids:
            placeholders = ",".join("?" for _ in ids)
            conn.execute(
                "UPDATE messages SET read = 1 WHERE id IN (%s)" % placeholders,
                ids,
            )
        return [dict(row) for row in rows]


def peers() -> list:
    """返回所有已知 peer（按最近活跃倒序），每项含 name/first_seen/last_seen。"""
    with _db() as conn:
        rows = conn.execute(
            "SELECT name, first_seen, last_seen FROM peers "
            "ORDER BY last_seen DESC, name ASC"
        ).fetchall()
        return [dict(row) for row in rows]


def groups() -> dict:
    """返回 {组名: [成员, ...]}（组名与成员均排序）。"""
    with _db() as conn:
        rows = conn.execute(
            "SELECT name, member FROM groups ORDER BY name ASC, member ASC"
        ).fetchall()
    result = {}
    for row in rows:
        result.setdefault(row["name"], []).append(row["member"])
    return result


def join_group(name, group) -> bool:
    """把 peer 加入组；重复加入是幂等的。"""
    name = _peer_name(name, "unknown")
    group = _peer_name(group)
    if not group:
        raise ValueError("join_group() 需要非空的 group 名")
    ts = time.time()
    with _db() as conn:
        _touch_peer(conn, name, ts)
        conn.execute(
            "INSERT OR IGNORE INTO groups(name, member) VALUES(?, ?)",
            (group, name),
        )
    return True


def leave_group(name, group) -> bool:
    """把 peer 从组里移除；不在组里也返回 False。"""
    name = _peer_name(name, "unknown")
    group = _peer_name(group)
    if not group:
        raise ValueError("leave_group() 需要非空的 group 名")
    with _db() as conn:
        cursor = conn.execute(
            "DELETE FROM groups WHERE name = ? AND member = ?",
            (group, name),
        )
        return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# 展示辅助（CLI 与 MCP server 共用）
# ---------------------------------------------------------------------------

def format_ts(ts) -> str:
    """把 epoch 秒格式化为本地时间字符串。"""
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError, OverflowError):
        return str(ts)


def format_message(message, mark_unread=True) -> str:
    """把一条消息格式化为单行文本：
    #<id> <时间> <发送者> -> <目标|#组|*> : <正文>
    未读消息带 "* " 前缀。
    """
    group_name = message.get("group_name")
    target = message.get("target")
    if group_name:
        destination = "#" + str(group_name)
    elif target:
        destination = str(target)
    else:
        destination = "*"
    prefix = ""
    if mark_unread and not message.get("read"):
        prefix = "* "
    return "%s#%s %s %s -> %s: %s" % (
        prefix,
        message.get("id"),
        format_ts(message.get("ts")),
        message.get("sender") or "unknown",
        destination,
        message.get("body") or "",
    )


def _json_dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _setup_stdio() -> None:
    """Windows 控制台 / 管道下强制 UTF-8 输出，无法编码的字符替换掉。"""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_send(args) -> int:
    message = " ".join(args.message)
    message_id = send(args.sender, message, to=args.to, group=args.group)
    print("sent #%d" % message_id)
    return 0


def _cmd_inbox(args) -> int:
    messages = inbox(
        args.as_name,
        limit=args.limit,
        unread_only=args.unread,
        mark_read=True,
    )
    if args.json:
        print(_json_dump(messages))
        return 0
    if not messages:
        print("(no messages)")
        return 0
    for message in messages:
        print(format_message(message))
    return 0


def _cmd_peers(args) -> int:
    rows = peers()
    if args.json:
        print(_json_dump(rows))
        return 0
    if not rows:
        print("(no peers)")
        return 0
    for row in rows:
        print("%s\t%s\t%s" % (
            row["name"],
            format_ts(row["last_seen"]),
            format_ts(row["first_seen"]),
        ))
    return 0


def _cmd_groups(args) -> int:
    membership = groups()
    if args.json:
        print(_json_dump(membership))
        return 0
    if not membership:
        print("(no groups)")
        return 0
    for group_name in sorted(membership):
        print("%s\t%s" % (group_name, ", ".join(membership[group_name])))
    return 0


def _cmd_join(args) -> int:
    join_group(args.as_name, args.group)
    print("joined %s -> %s" % (args.as_name, args.group))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ccs_bus.py",
        description="ccs-tool 本地多 agent 消息总线（SQLite / WAL）",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_send = subparsers.add_parser("send", help="发送消息")
    p_send.add_argument("--from", dest="sender", required=True, metavar="NAME",
                        help="发送者名字")
    target = p_send.add_mutually_exclusive_group(required=True)
    target.add_argument("--to", metavar="NAME", help="直接收件人")
    target.add_argument("--group", metavar="GROUP", help="发送到组")
    p_send.add_argument("message", nargs="+", help="消息正文")
    p_send.set_defaults(func=_cmd_send)

    p_inbox = subparsers.add_parser("inbox", help="读取收件箱")
    p_inbox.add_argument("--as", dest="as_name", required=True, metavar="NAME",
                         help="以谁的身份读取")
    p_inbox.add_argument("--limit", type=int, default=50, metavar="N",
                         help="最多返回最近 N 条（默认 50）")
    p_inbox.add_argument("--unread", action="store_true", help="只看未读")
    p_inbox.add_argument("--json", action="store_true", help="输出 JSON")
    p_inbox.set_defaults(func=_cmd_inbox)

    p_peers = subparsers.add_parser("peers", help="列出已知 peer")
    p_peers.add_argument("--json", action="store_true", help="输出 JSON")
    p_peers.set_defaults(func=_cmd_peers)

    p_groups = subparsers.add_parser("groups", help="列出组与成员")
    p_groups.add_argument("--json", action="store_true", help="输出 JSON")
    p_groups.set_defaults(func=_cmd_groups)

    p_join = subparsers.add_parser("join", help="加入组")
    p_join.add_argument("--as", dest="as_name", required=True, metavar="NAME")
    p_join.add_argument("--group", required=True, metavar="GROUP")
    p_join.set_defaults(func=_cmd_join)

    return parser


def main(argv=None) -> int:
    _setup_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except sqlite3.Error as exc:
        print("ccs_bus: database error: %s" % exc, file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print("ccs_bus: error: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
