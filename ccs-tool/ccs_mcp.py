#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ccs_mcp.py - ccs-tool 的 MCP stdio server（JSON-RPC 2.0，每行一条消息）。

运行
    python ccs_mcp.py

约定
    * stdout 只允许输出协议消息（一行一个 JSON），不得打印任何日志；
    * 所有日志/异常都写到 stderr；
    * 输入输出统一 UTF-8，Windows 管道/控制台编码问题已处理；
    * 没有 MCP 客户端时可以直接用管道测试，例如：
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' |
            python ccs_mcp.py

支持的方法
    initialize / notifications/initialized / ping / tools/list / tools/call
    未知方法返回 JSON-RPC error -32601。

工具
    bus_send     发送总线消息（sender 取环境变量 CCS_SESSION，缺省 unknown）
    bus_inbox    读取总线收件箱
    bus_peers    列出 peer 与组
    session_list 读取 CCS_HOME/state.json 的会话列表
    session_send 通过 ccs.py send 向指定会话 PTY 注入文本
"""

from __future__ import annotations

import json
import locale
import os
import subprocess
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import ccs_bus  # noqa: E402  （依赖同目录 ccs_bus.py）

SERVER_NAME = "ccs"
SERVER_VERSION = "0.1.0"
DEFAULT_PROTOCOL_VERSION = "2024-11-05"
CCS_PY = os.path.join(HERE, "ccs.py")


def _ccs_cmd():
    """调用 ccs 自身：源码模式用 python ccs.py，打包模式用 ccs.exe（由 ccs.py 通过 CCS_CMD_JSON 告知）。"""
    raw = os.environ.get("CCS_CMD_JSON")
    if raw:
        try:
            cmd = json.loads(raw)
            if isinstance(cmd, list) and cmd:
                return [str(part) for part in cmd]
        except ValueError:
            pass
    return [sys.executable, CCS_PY]
_STATE_FILE = "state.json"

_CREATE_NO_WINDOW = 0x08000000


class ToolError(Exception):
    """工具执行失败：转成 isError=true 的 tools/call 结果。"""


# ---------------------------------------------------------------------------
# 基础辅助
# ---------------------------------------------------------------------------

def _log(message) -> None:
    """日志只写 stderr（stdout 是协议通道）。"""
    try:
        sys.stderr.write(str(message) + "\n")
        sys.stderr.flush()
    except (AttributeError, OSError, ValueError):
        pass


def _setup_stdio() -> None:
    try:
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", newline="\n")
    except (AttributeError, ValueError, OSError):
        pass
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass


def _sender() -> str:
    """当前 agent 名字：CCS_SESSION，缺省 unknown。"""
    return (os.environ.get("CCS_SESSION") or "unknown").strip() or "unknown"


def _state_path() -> str:
    return os.path.join(ccs_bus.home(), _STATE_FILE)


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(str(item) for item in value)
    return str(value)


def _decode_output(data) -> str:
    """把子进程输出字节解码为文本：优先 UTF-8，回退系统代码页。"""
    if not data:
        return ""
    fallback = locale.getpreferredencoding(False) or "utf-8"
    for encoding in ("utf-8", fallback):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# 工具实现
# ---------------------------------------------------------------------------

def _tool_bus_send(arguments) -> str:
    message = arguments.get("message")
    if not isinstance(message, str) or message == "":
        raise ToolError("bus_send: 缺少必填字符串参数 'message'")
    to = arguments.get("to")
    group = arguments.get("group")
    to = str(to).strip() if to not in (None, "") else None
    group = str(group).strip() if group not in (None, "") else None
    try:
        message_id = ccs_bus.send(_sender(), message, to=to, group=group)
    except Exception as exc:  # noqa: BLE001
        raise ToolError("bus_send: 发送失败: %s" % exc) from exc
    return "sent #%d" % message_id


def _tool_bus_inbox(arguments) -> str:
    limit = arguments.get("limit", 50)
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        raise ToolError("bus_inbox: 'limit' 必须是整数")
    unread_only = bool(arguments.get("unread_only", False))
    try:
        messages = ccs_bus.inbox(
            _sender(), limit=limit, unread_only=unread_only, mark_read=True
        )
    except Exception as exc:  # noqa: BLE001
        raise ToolError("bus_inbox: 读取失败: %s" % exc) from exc
    if not messages:
        return "(no messages)"
    return "\n".join(ccs_bus.format_message(m) for m in messages)


def _tool_bus_peers(arguments) -> str:
    try:
        rows = ccs_bus.peers()
        membership = ccs_bus.groups()
    except Exception as exc:  # noqa: BLE001
        raise ToolError("bus_peers: 读取失败: %s" % exc) from exc
    lines = []
    for row in rows:
        lines.append("%s\tlast_seen=%s\tfirst_seen=%s" % (
            row.get("name"),
            ccs_bus.format_ts(row.get("last_seen")),
            ccs_bus.format_ts(row.get("first_seen")),
        ))
    if membership:
        if lines:
            lines.append("")
        lines.append("groups:")
        for group_name in sorted(membership):
            lines.append("  %s\t%s" % (group_name, ", ".join(membership[group_name])))
    if not lines:
        return "(no peers)"
    return "\n".join(lines)


def _session_entries(data):
    """从 state.json 的内容里抽取会话条目列表，兼容 list/dict 两种布局。"""
    if isinstance(data, dict):
        sessions = data.get("sessions")
        if sessions is None:
            sessions = []
    elif isinstance(data, list):
        sessions = data
    else:
        return None

    if isinstance(sessions, dict):
        entries = []
        for name, info in sessions.items():
            if isinstance(info, dict):
                entry = dict(info)
                entry.setdefault("name", name)
                entries.append(entry)
        return entries
    if isinstance(sessions, list):
        return [item for item in sessions if isinstance(item, dict)]
    return None


def _tool_session_list(arguments) -> str:
    path = _state_path()
    if not os.path.isfile(path):
        return "(no sessions)"
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise ToolError("session_list: 无法读取 %s: %s" % (path, exc)) from exc
    entries = _session_entries(data)
    if entries is None:
        raise ToolError("session_list: %s 格式不认识（期望 {'sessions': [...]}）" % path)
    lines = []
    for entry in entries:
        raw_argv = entry.get("argv")
        if isinstance(raw_argv, list):
            cmd = " ".join(str(part) for part in raw_argv)
        else:
            cmd = _as_text(entry.get("cmd"))
        status = _as_text(entry.get("status"))
        if not status:
            status = "running" if entry.get("exit_code") is None else "exited"
        lines.append("%s\t%s\t%s\t%s" % (
            _as_text(entry.get("name")) or "?",
            status,
            cmd,
            _as_text(entry.get("cwd")),
        ))
    if not lines:
        return "(no sessions)"
    return "\n".join(lines)


def _tool_session_send(arguments) -> str:
    session = arguments.get("session")
    text = arguments.get("text")
    if not isinstance(session, str) or not session.strip():
        raise ToolError("session_send: 缺少必填字符串参数 'session'")
    if not isinstance(text, str):
        raise ToolError("session_send: 缺少必填字符串参数 'text'")
    session = session.strip()
    prefix = _ccs_cmd()
    if not os.environ.get("CCS_CMD_JSON") and not os.path.isfile(CCS_PY):
        raise ToolError(
            "session_send: 找不到同目录的 ccs.py（期望 %s）" % CCS_PY
        )
    command = prefix + ["send", session, text]
    kwargs = dict(
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )
    if os.name == "nt":
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    try:
        completed = subprocess.run(command, **kwargs)
    except subprocess.TimeoutExpired as exc:
        raise ToolError("session_send: 调用 ccs.py 超时（60s）") from exc
    except OSError as exc:
        raise ToolError("session_send: 无法启动 ccs.py: %s" % exc) from exc
    stdout = _decode_output(completed.stdout).strip()
    stderr = _decode_output(completed.stderr).strip()
    if completed.returncode != 0:
        detail = stderr or stdout or "无输出"
        raise ToolError(
            "session_send: ccs.py send 失败（exit %s）: %s"
            % (completed.returncode, detail)
        )
    return stdout or "ok"


_TOOL_HANDLERS = {
    "bus_send": _tool_bus_send,
    "bus_inbox": _tool_bus_inbox,
    "bus_peers": _tool_bus_peers,
    "session_list": _tool_session_list,
    "session_send": _tool_session_send,
}


# ---------------------------------------------------------------------------
# 工具清单（tools/list）
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "bus_send",
        "description": (
            "在 ccs 本地消息总线（SQLite）上给另一个 agent 或一个组发送消息。"
            "发送者取环境变量 CCS_SESSION。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "直接收件人 agent 名"},
                "group": {"type": "string", "description": "组名（组内成员都能收到）"},
                "message": {"type": "string", "description": "消息正文"},
            },
            "required": ["message"],
        },
    },
    {
        "name": "bus_inbox",
        "description": "读取发给当前 agent（CCS_SESSION）及其已加入组的消息，按时间从旧到新。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "最多返回最近 N 条，默认 50",
                    "minimum": 1,
                },
                "unread_only": {
                    "type": "boolean",
                    "description": "只返回未读消息，默认 false",
                },
            },
        },
    },
    {
        "name": "bus_peers",
        "description": "列出总线上的已知 peer（含最近活跃时间）以及所有组和成员。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "session_list",
        "description": "列出 ccs 会话（读取 CCS_HOME/state.json），每行 name\tstatus\tcmd\tcwd。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "session_send",
        "description": (
            "向指定的 ccs 会话 PTY 注入文本并回车（内部调用同目录 ccs.py send）。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session": {"type": "string", "description": "目标 ccs 会话名"},
                "text": {"type": "string", "description": "要注入的文本"},
            },
            "required": ["session", "text"],
        },
    },
]


# ---------------------------------------------------------------------------
# JSON-RPC 2.0
# ---------------------------------------------------------------------------

def _write_message(payload) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _result(message_id, result):
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _error(message_id, code, message):
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "error": {"code": code, "message": message},
    }


def _handle_initialize(params):
    params = params if isinstance(params, dict) else {}
    protocol = params.get("protocolVersion")
    if not isinstance(protocol, str) or not protocol.strip():
        protocol = DEFAULT_PROTOCOL_VERSION
    return {
        "protocolVersion": protocol.strip(),
        "capabilities": {"tools": {}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
    }


def _handle_tools_call(params):
    params = params if isinstance(params, dict) else {}
    name = params.get("name")
    arguments = params.get("arguments")
    if not isinstance(arguments, dict):
        arguments = {}
    handler = _TOOL_HANDLERS.get(name) if isinstance(name, str) else None
    if handler is None:
        raise KeyError(name)
    try:
        text = handler(arguments)
    except ToolError as exc:
        return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    except Exception as exc:  # noqa: BLE001
        _log(traceback.format_exc())
        return {
            "content": [{"type": "text", "text": "internal error: %s" % exc}],
            "isError": True,
        }
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _handle_message(message):
    """处理单条 JSON-RPC 消息；通知返回 None（不响应）。"""
    if not isinstance(message, dict):
        return _error(None, -32600, "Invalid Request")

    method = message.get("method")
    has_id = "id" in message
    message_id = message.get("id")

    if not isinstance(method, str):
        if has_id:
            return _error(message_id, -32600, "Invalid Request")
        return None

    # JSON-RPC 通知：没有 id，绝不响应。
    if not has_id:
        if method != "notifications/initialized":
            _log("ignored notification: %s" % method)
        return None

    if method == "initialize":
        return _result(message_id, _handle_initialize(message.get("params")))

    if method == "notifications/initialized":
        return _result(message_id, {})

    if method == "ping":
        return _result(message_id, {})

    if method == "tools/list":
        return _result(message_id, {"tools": TOOLS})

    if method == "tools/call":
        try:
            return _result(message_id, _handle_tools_call(message.get("params")))
        except KeyError:
            params = message.get("params")
            tool_name = params.get("name") if isinstance(params, dict) else None
            return _error(
                message_id, -32602, "Unknown tool: %s" % tool_name
            )

    return _error(message_id, -32601, "Method not found: %s" % method)


def _handle_payload(payload):
    """支持单条消息与 JSON-RPC 2.0 batch 数组。"""
    if isinstance(payload, list):
        if not payload:
            return _error(None, -32600, "Invalid Request")
        responses = []
        for item in payload:
            response = _handle_message(item)
            if response is not None:
                responses.append(response)
        return responses or None
    return _handle_message(payload)


def _process_line(line) -> None:
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        _write_message(_error(None, -32700, "Parse error"))
        return
    response = _handle_payload(payload)
    if response is not None:
        _write_message(response)


def main(argv=None) -> int:
    _setup_stdio()
    if os.environ.get("CCS_MCP_DEBUG"):
        _log("ccs_mcp %s starting (pid %d)" % (SERVER_VERSION, os.getpid()))
    while True:
        line = sys.stdin.readline()
        if line == "":
            break
        line = line.strip().lstrip("\ufeff")
        if not line:
            continue
        _process_line(line)
    if os.environ.get("CCS_MCP_DEBUG"):
        _log("ccs_mcp exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
