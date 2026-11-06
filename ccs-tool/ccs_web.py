#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ccs_web.py - ccs 可视化控制台。

本地 HTTP + WebSocket 服务：浏览器里查看/操作所有 ccs 会话。
    * 左侧会话列表（状态、命令、目录、运行时长）
    * 右侧终端（xterm.js，直接 attach 到会话，关浏览器不影响会话）
    * 新建 / 重命名 / 停止
    * 多 agent 消息总线面板

仅使用 Python 标准库（http.server / socket / hashlib / base64），
xterm.js 为本地静态资源（web/ 目录）。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import shlex
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_MAIN = sys.modules.get("__main__")
if _MAIN is not None and hasattr(_MAIN, "make_session_argv"):
    ccs = _MAIN            # 源码/打包模式下 ccs.py 都是入口模块
else:  # pragma: no cover - 被当作普通模块导入时
    import ccs  # type: ignore

try:
    import ccs_bus
except Exception:  # pragma: no cover
    ccs_bus = None

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
WEB_ROOT = ccs.web_dir()
START_TIME = time.time()


# --------------------------------------------------------------------------
# WebSocket 最小实现（文本帧 + ping/pong/close；不做分片与压缩）
# --------------------------------------------------------------------------
class WS:
    def __init__(self, rfile, wfile):
        self.rfile = rfile
        self.wfile = wfile
        self.lock = threading.Lock()
        self.closed = False

    def recv_frame(self):
        head = self.rfile.read(2)
        if not head or len(head) < 2:
            return None
        opcode = head[0] & 0x0F
        masked = head[1] & 0x80
        length = head[1] & 0x7F
        if length == 126:
            raw = self.rfile.read(2)
            if len(raw) < 2:
                return None
            length = int.from_bytes(raw, "big")
        elif length == 127:
            raw = self.rfile.read(8)
            if len(raw) < 8:
                return None
            length = int.from_bytes(raw, "big")
        mask = b""
        if masked:
            mask = self.rfile.read(4)
            if len(mask) < 4:
                return None
        payload = self.rfile.read(length) if length else b""
        if len(payload) < length:
            return None
        if masked and mask:
            payload = bytes(payload[i] ^ mask[i % 4] for i in range(len(payload)))
        return opcode, payload

    def send_frame(self, opcode, payload=b""):
        if self.closed:
            return
        header = bytearray()
        header.append(0x80 | opcode)
        n = len(payload)
        if n < 126:
            header.append(n)
        elif n < 65536:
            header.append(126)
            header += n.to_bytes(2, "big")
        else:
            header.append(127)
            header += n.to_bytes(8, "big")
        with self.lock:
            try:
                self.wfile.write(bytes(header) + payload)
                self.wfile.flush()
            except Exception:
                self.closed = True

    def send_text(self, text):
        self.send_frame(0x1, text.encode("utf-8"))

    def pong(self, payload):
        self.send_frame(0xA, payload)

    def close(self):
        if self.closed:
            return
        try:
            self.send_frame(0x8, b"")
        except Exception:
            pass
        self.closed = True


# --------------------------------------------------------------------------
# 业务逻辑
# --------------------------------------------------------------------------
def daemon_sessions():
    if not ccs.daemon_alive():
        ccs.start_daemon(quiet=True)
    try:
        resp = ccs._rpc({"k": "ls"})
    except Exception as exc:
        return {"ok": False, "error": "无法连接 ccs 守护进程: %s" % exc}
    if resp.get("k") == "err":
        return {"ok": False, "error": resp.get("msg")}
    return {"ok": True, "sessions": resp.get("sessions", [])}


def new_session(name, cmd, cwd):
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "会话名字不能为空"}
    cmd = (cmd or "").strip() or "claude"
    try:
        parts = shlex.split(cmd)
    except ValueError as exc:
        return {"ok": False, "error": "命令解析失败: %s" % exc}
    if not parts:
        parts = ["claude"]
    workdir = Path(cwd).expanduser() if cwd else Path.cwd()
    try:
        argv, sid, agent = ccs.make_session_argv(name, parts, workdir)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    if not ccs.ensure_daemon():
        return {"ok": False, "error": "守护进程启动失败，查看 %s" % ccs.DAEMON_LOG}
    resp = ccs._rpc({"k": "new", "name": name, "argv": argv,
                     "cwd": str(workdir), "session_id": sid, "agent": agent})
    if resp.get("k") == "err":
        return {"ok": False, "error": resp.get("msg")}
    return {"ok": True, "pid": resp.get("pid")}


def rename_session(old, new):
    old = (old or "").strip()
    new = (new or "").strip()
    if not old or not new:
        return {"ok": False, "error": "old/new 不能为空"}
    resp = ccs._rpc({"k": "rename", "old": old, "new": new})
    if resp.get("k") == "err":
        return {"ok": False, "error": resp.get("msg")}
    return {"ok": True}


def kill_session(name):
    resp = ccs._rpc({"k": "kill", "name": (name or "").strip()})
    if resp.get("k") == "err":
        return {"ok": False, "error": resp.get("msg")}
    return {"ok": True}


def bus_messages(agent, limit):
    if ccs_bus is None:
        return {"ok": False, "error": "ccs_bus 模块不可用"}
    try:
        items = ccs_bus.inbox(agent or "web", limit=int(limit or 50), mark_read=False)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    out = []
    for item in items:
        row = dict(item)
        ts = row.get("ts")
        if isinstance(ts, (int, float)):
            row["ts"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
        out.append(row)
    return {"ok": True, "messages": out}


def bus_send(sender, message, to=None, group=None):
    if ccs_bus is None:
        return {"ok": False, "error": "ccs_bus 模块不可用"}
    message = (message or "").strip()
    if not message:
        return {"ok": False, "error": "消息不能为空"}
    try:
        msg_id = ccs_bus.send(sender or "web", message, to=to or None, group=group or None)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "id": msg_id}


# --------------------------------------------------------------------------
# HTTP 处理
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "ccs-web/0.1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    # ---- helpers
    def send_json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_bytes(self, data, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def read_json(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def static(self, rel):
        rel = rel.replace("\\", "/").lstrip("/")
        if ".." in rel.split("/"):
            return self.send_error(403)
        path = (WEB_ROOT / rel).resolve()
        try:
            path.relative_to(WEB_ROOT.resolve())
        except ValueError:
            return self.send_error(403)
        if not path.is_file():
            return self.send_error(404)
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if path.suffix == ".css":
            ctype = "text/css; charset=utf-8"
        elif path.suffix == ".js":
            ctype = "application/javascript; charset=utf-8"
        elif path.suffix == ".html":
            ctype = "text/html; charset=utf-8"
        self.send_bytes(path.read_bytes(), ctype)

    # ---- GET
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/ws":
            return self.handle_ws(parsed, query)
        if path in ("/", "/index.html"):
            return self.static("index.html")
        if path.startswith("/static/"):
            return self.static(path[len("/static/"):])
        if path == "/api/sessions":
            return self.send_json(daemon_sessions())
        if path == "/api/bus":
            agent = query.get("agent", ["web"])[0]
            limit = query.get("limit", ["50"])[0]
            return self.send_json(bus_messages(agent, limit))
        if path == "/api/health":
            return self.send_json({"ok": True, "uptime": time.time() - START_TIME,
                                   "daemon": ccs.daemon_alive(), "port": ccs.daemon_port()})
        return self.send_error(404)

    # ---- POST
    def do_POST(self):
        parsed = urlparse(self.path)
        body = self.read_json()
        if parsed.path == "/api/new":
            return self.send_json(new_session(body.get("name"), body.get("cmd"), body.get("cwd")))
        if parsed.path == "/api/rename":
            return self.send_json(rename_session(body.get("old"), body.get("new")))
        if parsed.path == "/api/kill":
            return self.send_json(kill_session(body.get("name")))
        if parsed.path == "/api/bus/send":
            return self.send_json(bus_send(body.get("from"), body.get("message"),
                                           body.get("to"), body.get("group")))
        return self.send_error(404)

    # ---- WebSocket attach
    def handle_ws(self, parsed, query):
        key = self.headers.get("Sec-WebSocket-Key")
        if not key or (self.headers.get("Upgrade") or "").lower() != "websocket":
            return self.send_error(400, "expected websocket")
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode("ascii")).digest()).decode("ascii")
        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        self.end_headers()
        ws = WS(self.rfile, self.wfile)

        name = (query.get("name", [""])[0] or "").strip()
        try:
            cols = int(query.get("cols", ["120"])[0])
            rows = int(query.get("rows", ["32"])[0])
        except ValueError:
            cols, rows = 120, 32

        if not name:
            ws.send_text(json.dumps({"t": "err", "msg": "缺少会话名"}))
            ws.close()
            return
        if not ccs.ensure_daemon():
            ws.send_text(json.dumps({"t": "err", "msg": "守护进程未运行"}))
            ws.close()
            return
        try:
            sock = socket.create_connection(("127.0.0.1", ccs.daemon_port()), timeout=5)
            sock.settimeout(None)
        except Exception as exc:
            ws.send_text(json.dumps({"t": "err", "msg": "连接守护进程失败: %s" % exc}))
            ws.close()
            return

        sock.sendall((json.dumps({"k": "attach", "name": name, "cols": cols, "rows": rows}) + "\n").encode())
        rfile = sock.makefile("rb")
        stop = threading.Event()

        def pump_daemon():
            try:
                while not stop.is_set():
                    line = rfile.readline()
                    if not line:
                        break
                    msg = json.loads(line)
                    kind = msg.get("k")
                    if kind in ("snap", "out"):
                        ws.send_text(json.dumps({"t": kind, "b64": msg.get("b64", "")}))
                    elif kind == "exit":
                        ws.send_text(json.dumps({"t": "exit", "code": msg.get("code")}))
                        break
            except Exception:
                pass
            finally:
                stop.set()
                ws.close()

        pump_thread = threading.Thread(target=pump_daemon, daemon=True)
        pump_thread.start()

        try:
            while not stop.is_set():
                frame = ws.recv_frame()
                if frame is None:
                    break
                opcode, payload = frame
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    ws.pong(payload)
                    continue
                if opcode != 0x1:
                    continue
                try:
                    msg = json.loads(payload.decode("utf-8"))
                except Exception:
                    continue
                kind = msg.get("t")
                if kind == "in":
                    sock.sendall((json.dumps({"k": "in", "b64": msg.get("b64", "")}) + "\n").encode())
                elif kind == "resize":
                    sock.sendall((json.dumps({"k": "resize",
                                              "cols": int(msg.get("cols", 120)),
                                              "rows": int(msg.get("rows", 32))}) + "\n").encode())
        except Exception:
            pass
        finally:
            stop.set()
            try:
                sock.sendall(b'{"k":"detach"}\n')
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass
            ws.close()


# --------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(prog="ccs web", description="ccs 可视化控制台")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认仅本机）")
    parser.add_argument("--port", type=int, default=8787, help="端口（默认 8787）")
    parser.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    if not (WEB_ROOT / "index.html").is_file():
        print("找不到 web 资源目录: %s" % WEB_ROOT)
        return 1
    try:
        httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        print("无法监听 %s:%s - %s" % (args.host, args.port, exc))
        return 1
    url = "http://%s:%d/" % (args.host, args.port)
    print("ccs 控制台: %s" % url)
    print("（Ctrl+C 退出；关闭浏览器不会影响会话）")
    if args.open:
        threading.Thread(target=lambda: (time.sleep(0.3), webbrowser.open(url)), daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
