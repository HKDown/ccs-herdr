#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""ccs — Claude Code Sessions.

Windows 上的 "tmux for Claude CLI":
  * 命名会话, 关掉终端窗口会话继续跑
  * attach / detach (Ctrl-])
  * 重启后 ccs restore 自动重建会话并 claude --resume 接回对话
  * 多 agent 互通: ccs bus (见 ccs_bus.py) + MCP (见 ccs_mcp.py)

仅使用 Python 标准库. 状态目录: %USERPROFILE%\.ccs (或 CCS_HOME).
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import ctypes.wintypes as wt
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

import ccs_agents

VERSION = "0.3.1"
FROZEN = bool(getattr(sys, "frozen", False))
SELF_EXE = Path(sys.executable).resolve()
SCRIPT_PATH = Path(__file__).resolve()
SELF_DIR = SCRIPT_PATH.parent
CCS_HOME = Path(os.environ.get("CCS_HOME") or (Path.home() / ".ccs"))
STATE_FILE = CCS_HOME / "state.json"
DAEMON_FILE = CCS_HOME / "daemon.json"
DAEMON_LOG = CCS_HOME / "daemon.log"
BUF_LIMIT = 2 * 1024 * 1024

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---------------------------------------------------------------- win32 glue
k32 = ctypes.WinDLL("kernel32", use_last_error=True)


class COORD(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", wt.DWORD), ("lpSecurityDescriptor", ctypes.c_void_p),
                ("bInheritHandle", wt.BOOL)]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD), ("lpReserved", wt.LPWSTR), ("lpDesktop", wt.LPWSTR),
        ("lpTitle", wt.LPWSTR), ("dwX", wt.DWORD), ("dwY", wt.DWORD),
        ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD), ("dwXCountChars", wt.DWORD),
        ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD), ("dwFlags", wt.DWORD),
        ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
        ("lpReserved2", ctypes.c_void_p), ("hStdInput", wt.HANDLE),
        ("hStdOutput", wt.HANDLE), ("hStdError", wt.HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE),
                ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]


HPCON = ctypes.c_void_p
CreatePseudoConsole = k32.CreatePseudoConsole
CreatePseudoConsole.argtypes = [COORD, wt.HANDLE, wt.HANDLE, wt.DWORD, ctypes.POINTER(HPCON)]
CreatePseudoConsole.restype = ctypes.c_long
ResizePseudoConsole = k32.ResizePseudoConsole
ResizePseudoConsole.argtypes = [HPCON, COORD]
ClosePseudoConsole = k32.ClosePseudoConsole
ClosePseudoConsole.argtypes = [HPCON]

CreatePipe = k32.CreatePipe
CreatePipe.argtypes = [ctypes.POINTER(wt.HANDLE), ctypes.POINTER(wt.HANDLE),
                       ctypes.POINTER(SECURITY_ATTRIBUTES), wt.DWORD]
CreatePipe.restype = wt.BOOL
ReadFile = k32.ReadFile
ReadFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
ReadFile.restype = wt.BOOL
WriteFile = k32.WriteFile
WriteFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
WriteFile.restype = wt.BOOL
CloseHandle = k32.CloseHandle
CloseHandle.argtypes = [wt.HANDLE]
TerminateProcess = k32.TerminateProcess
TerminateProcess.argtypes = [wt.HANDLE, wt.UINT]
InitializeProcThreadAttributeList = k32.InitializeProcThreadAttributeList
InitializeProcThreadAttributeList.argtypes = [ctypes.c_void_p, wt.DWORD, wt.DWORD,
                                              ctypes.POINTER(ctypes.c_size_t)]
InitializeProcThreadAttributeList.restype = wt.BOOL
UpdateProcThreadAttribute = k32.UpdateProcThreadAttribute
UpdateProcThreadAttribute.argtypes = [ctypes.c_void_p, wt.DWORD, ctypes.c_size_t, ctypes.c_void_p,
                                      ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p]
UpdateProcThreadAttribute.restype = wt.BOOL
DeleteProcThreadAttributeList = k32.DeleteProcThreadAttributeList
DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
CreateProcessW = k32.CreateProcessW
CreateProcessW.argtypes = [wt.LPCWSTR, wt.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wt.BOOL,
                           wt.DWORD, ctypes.c_void_p, wt.LPCWSTR,
                           ctypes.POINTER(STARTUPINFOEXW), ctypes.POINTER(PROCESS_INFORMATION)]
CreateProcessW.restype = wt.BOOL

PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_UNICODE_ENVIRONMENT = 0x00000400
DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200


def _h(v):
    """normalize a HANDLE-ish value to int."""
    if v is None:
        return 0
    return getattr(v, "value", v) or 0


def make_pipe(inheritable: bool):
    sa = SECURITY_ATTRIBUTES()
    sa.nLength = ctypes.sizeof(SECURITY_ATTRIBUTES)
    sa.bInheritHandle = 1 if inheritable else 0
    r = wt.HANDLE()
    w = wt.HANDLE()
    if not CreatePipe(ctypes.byref(r), ctypes.byref(w), ctypes.byref(sa), 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return _h(r), _h(w)


def read_handle(handle: int, n: int = 65536) -> bytes:
    buf = ctypes.create_string_buffer(n)
    got = wt.DWORD(0)
    if not ReadFile(handle, buf, n, ctypes.byref(got), None):
        raise OSError(ctypes.get_last_error(), "ReadFile failed")
    return buf.raw[: got.value]


def write_handle(handle: int, data: bytes) -> None:
    off = 0
    while off < len(data):
        chunk = data[off: off + 8192]
        buf = ctypes.create_string_buffer(chunk, len(chunk))
        wrote = wt.DWORD(0)
        if not WriteFile(handle, buf, len(chunk), ctypes.byref(wrote), None):
            raise OSError(ctypes.get_last_error(), "WriteFile failed")
        if wrote.value == 0:
            raise OSError(0, "WriteFile wrote 0 bytes")
        off += wrote.value


def close(h: int):
    if h:
        try:
            CloseHandle(h)
        except Exception:
            pass


def build_launch(argv):
    """Return (application, commandline) that CreateProcessW can run.

    Handles .cmd/.bat shims (npm installs claude.cmd on Windows) via cmd.exe.
    """
    exe = shutil.which(argv[0])
    if not exe:
        raise FileNotFoundError(argv[0])
    low = exe.lower()
    if low.endswith((".cmd", ".bat")):
        comspec = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
        inner = subprocess.list2cmdline([exe] + argv[1:])
        return comspec, "%s /d /s /c \"%s\"" % (subprocess.list2cmdline([comspec]), inner)
    return exe, subprocess.list2cmdline(argv)


class Pty:
    """One ConPTY + child process."""

    def __init__(self, argv, cwd, cols=120, rows=32, env=None):
        self.cols, self.rows = cols, rows
        app, cmdline = build_launch(argv)
        self.app = app
        h_in_r, h_in_w = make_pipe(True)
        h_out_r, h_out_w = make_pipe(True)
        self.h_in = h_in_w   # we write
        self.h_out = h_out_r  # we read
        hpc = HPCON()
        hr = CreatePseudoConsole(COORD(cols, rows), h_in_r, h_out_w, 0, ctypes.byref(hpc))
        if hr != 0:
            raise OSError("CreatePseudoConsole failed: 0x%08x" % (hr & 0xFFFFFFFF))
        self.hpc = hpc

        size = ctypes.c_size_t(0)
        InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        attr = ctypes.create_string_buffer(size.value)
        if not InitializeProcThreadAttributeList(attr, 1, 0, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        # 注意: lpValue 必须是 HPCON 句柄值本身, 不能是 &hpc (传指针会被静默忽略,
        # 子进程会挂到默认控制台, ConPTY 输出管道永远没有数据).
        if not UpdateProcThreadAttribute(attr, 0, PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
                                         ctypes.c_void_p(hpc.value),
                                         ctypes.sizeof(ctypes.c_void_p), None, None):
            raise ctypes.WinError(ctypes.get_last_error())

        si = STARTUPINFOEXW()
        si.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
        si.StartupInfo.dwFlags = 0x00000100  # STARTF_USESTDHANDLES
        si.lpAttributeList = ctypes.cast(attr, ctypes.c_void_p)
        pi = PROCESS_INFORMATION()
        buf = ctypes.create_unicode_buffer(cmdline)
        flags = EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT
        ok = CreateProcessW(None, buf, None, None, False, flags, None,
                            str(cwd) if cwd else None, ctypes.byref(si), ctypes.byref(pi))
        err = ctypes.get_last_error()
        DeleteProcThreadAttributeList(attr)
        close(h_in_r)
        close(h_out_w)
        if not ok:
            ClosePseudoConsole(hpc)
            raise ctypes.WinError(err)
        self.proc_handle = _h(pi.hProcess)
        self.thread_handle = _h(pi.hThread)
        self.pid = pi.dwProcessId
        close(self.thread_handle)
        self.exit_code = None

    def read(self, n=65536):
        return read_handle(self.h_out, n)

    def write(self, data: bytes):
        write_handle(self.h_in, data)

    def resize(self, cols, rows):
        self.cols, self.rows = cols, rows
        try:
            ResizePseudoConsole(self.hpc, COORD(cols, rows))
        except Exception:
            pass

    def poll(self):
        if self.exit_code is not None:
            return self.exit_code
        code = wt.DWORD(0)
        if k32.GetExitCodeProcess(self.proc_handle, ctypes.byref(code)):
            if code.value != 259:  # STILL_ACTIVE
                self.exit_code = code.value
                return self.exit_code
        return None

    def kill(self):
        if getattr(self, "_killed", False):
            return
        self._killed = True
        try:
            TerminateProcess(self.proc_handle, 1)
        except Exception:
            pass
        try:
            ClosePseudoConsole(self.hpc)
        except Exception:
            pass
        close(self.h_in)
        close(self.h_out)
        self.exit_code = self.exit_code if self.exit_code is not None else 1


# ---------------------------------------------------------------- state
def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"sessions": []}


def save_state(st):
    CCS_HOME.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_FILE)


def log_line(msg):
    CCS_HOME.mkdir(parents=True, exist_ok=True)
    with open(DAEMON_LOG, "a", encoding="utf-8") as f:
        f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))


# ---------------------------------------------------------------- sessions
class Session:
    def __init__(self, name, argv, cwd, claude_sid=None, cols=120, rows=32, agent=None):
        self.name = name
        self.argv = argv
        self.cwd = str(cwd)
        try:
            self.agent = agent or ccs_agents.detect(argv[0])
        except Exception:
            self.agent = agent or "generic"
        self.sid = claude_sid
        self.claude_sid = claude_sid  # 兼容旧字段名
        self.buf = bytearray()
        self.lock = threading.Lock()
        self.clients = set()
        self.clients_lock = threading.Lock()
        self.created = time.time()
        self.last_active = time.time()
        self.pid = None
        self.exit_code = None
        self.pty = Pty(argv, cwd, cols, rows)
        self.pid = self.pty.pid
        t = threading.Thread(target=self._pump, daemon=True)
        t.start()

    def _pump(self):
        try:
            while True:
                data = self.pty.read()
                if not data:
                    break
                self.last_active = time.time()
                with self.lock:
                    self.buf += data
                    if len(self.buf) > BUF_LIMIT:
                        del self.buf[: len(self.buf) - BUF_LIMIT]
                if self.sid is None and self.agent:
                    try:
                        found = ccs_agents.match_session_id(self.agent, data.decode("utf-8", "ignore"))
                    except Exception:
                        found = None
                    if found:
                        self.sid = found
                        self.claude_sid = found
                self.broadcast({"k": "out", "b64": base64.b64encode(data).decode()})
        except Exception as e:
            log_line("session %s read end: %r" % (self.name, e))
        self.exit_code = self.pty.poll()
        if self.exit_code is None:
            self.exit_code = 0
        self.broadcast({"k": "exit", "code": self.exit_code})
        with self.clients_lock:
            for c in list(self.clients):
                try:
                    c.close()
                except Exception:
                    pass
            self.clients.clear()

    def broadcast(self, msg):
        line = (json.dumps(msg) + "\n").encode()
        with self.clients_lock:
            dead = []
            for c in list(self.clients):
                try:
                    c.sendall(line)
                except Exception:
                    dead.append(c)
            for c in dead:
                self.clients.discard(c)
                try:
                    c.close()
                except Exception:
                    pass

    def snapshot(self):
        with self.lock:
            return bytes(self.buf)

    def display_snapshot(self, limit=65536):
        """attach 时重放的画面：从最后一次清屏处开始，避免把整段历史刷一屏。"""
        data = self.snapshot()
        cut = -1
        for marker in (b"\x1b[3J", b"\x1b[2J"):
            idx = data.rfind(marker)
            if idx > cut:
                cut = idx
        if cut > 0:
            data = data[cut:]
        return data[-limit:]

    def write(self, text):
        data = text.encode("utf-8") if isinstance(text, str) else text
        self.pty.write(data)
        self.last_active = time.time()

    def kill(self):
        self.pty.kill()

    def to_record(self):
        code = self.exit_code if self.exit_code is not None else self.pty.exit_code
        sid = self.sid if self.sid is not None else self.claude_sid
        return {
            "name": self.name, "argv": self.argv, "cwd": self.cwd,
            "agent": self.agent, "session_id": sid, "claude_sid": sid,
            "created": self.created, "last_active": self.last_active,
            "pid": self.pid, "exit_code": code,
        }


# ---------------------------------------------------------------- daemon
class Daemon:
    def __init__(self):
        self.sessions = {}
        self.lock = threading.Lock()
        self.sock = None
        self.port = None
        self.stop_flag = False

    # ---- persistence
    def persist(self):
        st = load_state()
        recs = {r["name"]: r for r in st.get("sessions", [])}
        with self.lock:
            for name, s in self.sessions.items():
                recs[name] = s.to_record()
        # keep records of sessions we no longer hold in memory only if they are known
        st["sessions"] = list(recs.values())
        save_state(st)

    def restore_records(self):
        st = load_state()
        self.persisted = st.get("sessions", [])

    # ---- rpc
    def handle(self, msg):
        k = msg.get("k")
        if k == "ping":
            return {"k": "pong", "pid": os.getpid()}
        if k == "new":
            return self.rpc_new(msg)
        if k == "ls":
            return {"k": "ls", "sessions": self.rpc_ls()}
        if k == "attach":
            return self.rpc_attach(msg)
        if k == "snapshot":
            s = self.get(msg.get("name"))
            return {"k": "snap", "b64": base64.b64encode(s.snapshot()).decode()} if s else {"k": "err", "msg": "no such session"}
        if k == "input":
            s = self.get(msg.get("name"))
            if not s:
                return {"k": "err", "msg": "no such session"}
            s.write(base64.b64decode(msg.get("b64", "")))
            return {"k": "ok"}
        if k in ("send", "type"):
            s = self.get(msg.get("name"))
            if not s:
                return {"k": "err", "msg": "no such session"}
            text = msg.get("text", "")
            s.write(text + ("\r" if k == "send" else ""))
            return {"k": "ok"}
        if k == "key":
            s = self.get(msg.get("name"))
            if not s:
                return {"k": "err", "msg": "no such session"}
            seq = KEYMAP.get(msg.get("key", ""))
            if seq is None:
                return {"k": "err", "msg": "unknown key"}
            s.write(seq)
            return {"k": "ok"}
        if k == "resize":
            s = self.get(msg.get("name"))
            if s:
                s.pty.resize(int(msg.get("cols", 120)), int(msg.get("rows", 32)))
            return {"k": "ok"}
        if k == "log":
            s = self.get(msg.get("name"))
            if not s:
                return {"k": "err", "msg": "no such session"}
            data = s.snapshot()
            n = int(msg.get("bytes", 0) or 0)
            if n:
                data = data[-n:]
            return {"k": "log", "b64": base64.b64encode(data).decode()}
        if k == "rename":
            return self.rpc_rename(msg)
        if k == "kill":
            s = self.get(msg.get("name"))
            if s:
                s.kill()
                if s.exit_code is None:
                    s.exit_code = s.pty.exit_code if s.pty.exit_code is not None else 1
                self.persist()
                return {"k": "ok"}
            return {"k": "err", "msg": "no such session"}
        if k == "rm":
            return self.rpc_rm(msg)
        if k == "restore":
            return self.rpc_restore(msg)
        if k == "shutdown":
            self.stop_flag = True
            return {"k": "ok"}
        return {"k": "err", "msg": "unknown command " + str(k)}

    def rpc_new(self, msg):
        name = msg["name"]
        argv = msg["argv"]
        cwd = msg.get("cwd") or os.getcwd()
        sid = msg.get("session_id") or msg.get("claude_sid")
        agent = msg.get("agent")
        with self.lock:
            old = self.sessions.get(name)
        if old and old.exit_code is None:
            return {"k": "err", "msg": "session '%s' already running" % name}
        try:
            s = Session(name, argv, cwd, sid, int(msg.get("cols", 120)), int(msg.get("rows", 32)), agent)
        except Exception as e:
            return {"k": "err", "msg": "%s: %s" % (type(e).__name__, e)}
        with self.lock:
            self.sessions[name] = s
        self.persist()
        return {"k": "ok", "pid": s.pid}

    def rpc_ls(self):
        out = []
        with self.lock:
            items = list(self.sessions.values())
        for s in items:
            code = s.exit_code if s.exit_code is not None else s.pty.poll()
            out.append({
                "name": s.name, "argv": s.argv, "cwd": s.cwd,
                "status": "running" if code is None else "exited",
                "exit_code": code, "pid": s.pid, "age": time.time() - s.created,
                "last_active": s.last_active, "agent": s.agent,
                "session_id": s.sid, "claude_sid": s.sid,
            })
        return out

    def rpc_attach(self, msg):
        s = self.get(msg.get("name"))
        if not s:
            return {"k": "err", "msg": "no such session"}
        s.pty.resize(int(msg.get("cols", 120)), int(msg.get("rows", 32)))
        return {"k": "ok"}

    def rpc_rename(self, msg):
        old, new = msg.get("old"), msg.get("new")
        with self.lock:
            if old not in self.sessions:
                return {"k": "err", "msg": "no such session"}
            if new in self.sessions:
                return {"k": "err", "msg": "name exists"}
            s = self.sessions.pop(old)
            s.name = new
            self.sessions[new] = s
        st = load_state()
        for r in st.get("sessions", []):
            if r.get("name") == old:
                r["name"] = new
        save_state(st)
        self.persist()
        return {"k": "ok"}

    def rpc_rm(self, msg):
        name = msg.get("name")
        with self.lock:
            s = self.sessions.pop(name, None)
        if s and s.exit_code is None:
            try:
                s.kill()
            except Exception:
                log_line("rm kill failed: " + traceback.format_exc())
        elif s:
            try:
                s.pty.kill()
            except Exception:
                pass
        st = load_state()
        st["sessions"] = [r for r in st.get("sessions", []) if r.get("name") != name]
        save_state(st)
        return {"k": "ok"}

    def rpc_restore(self, msg):
        recs = load_state().get("sessions", [])
        names = msg.get("names") or None
        started, errors = [], []
        for rec in recs:
            name = rec.get("name")
            if names and name not in names:
                continue
            if rec.get("exit_code") is not None and not names:
                continue  # 用户主动结束/退出的会话默认不在重启后复活, restore NAME 可强制恢复
            with self.lock:
                cur = self.sessions.get(name)
            if cur and cur.exit_code is None:
                continue
            if not (rec.get("session_id") or rec.get("claude_sid")):
                cur_s = self.get(name)
                if cur_s is not None and cur_s.sid:
                    rec["session_id"] = cur_s.sid
            argv, sid, note = ccs_agents.resume_argv(rec)
            if not argv:
                errors.append("%s: %s" % (name, note or "无法恢复"))
                continue
            try:
                self.rpc_new({"name": name, "argv": argv, "cwd": rec.get("cwd"),
                              "session_id": sid, "agent": rec.get("agent")})
                started.append(name)
            except Exception as e:
                errors.append("%s: %r" % (name, e))
        return {"k": "ok", "started": started, "errors": errors}

    def get(self, name):
        with self.lock:
            return self.sessions.get(name)

    # ---- server
    def serve(self):
        CCS_HOME.mkdir(parents=True, exist_ok=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(64)
        self.port = self.sock.getsockname()[1]
        with open(DAEMON_FILE, "w", encoding="utf-8") as f:
            json.dump({"port": self.port, "pid": os.getpid(), "started": time.time(),
                       "version": VERSION}, f)
        log_line("daemon started port=%d" % self.port)
        self.sock.settimeout(0.5)
        while not self.stop_flag:
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self.client_loop, args=(conn,), daemon=True).start()
        self.persist()
        try:
            self.sock.close()
        except Exception:
            pass
        try:
            DAEMON_FILE.unlink()
        except Exception:
            pass
        log_line("daemon stopped")

    def client_loop(self, conn):
        f = conn.makefile("rb")
        try:
            for line in f:
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line)
                except Exception:
                    conn.sendall((json.dumps({"k": "err", "msg": "bad json"}) + "\n").encode())
                    continue
                k = msg.get("k")
                if k == "attach":
                    s = self.get(msg.get("name"))
                    if not s:
                        conn.sendall((json.dumps({"k": "err", "msg": "no such session"}) + "\n").encode())
                        return
                    s.pty.resize(int(msg.get("cols", 120)), int(msg.get("rows", 32)))
                    with s.clients_lock:
                        s.clients.add(conn)
                    conn.sendall((json.dumps({"k": "snap",
                                              "b64": base64.b64encode(s.display_snapshot()).decode()}) + "\n").encode())
                    # keep connection open until client detaches
                    while True:
                        line2 = f.readline()
                        if not line2:
                            break
                        try:
                            m2 = json.loads(line2)
                        except Exception:
                            continue
                        if m2.get("k") == "detach":
                            break
                        if m2.get("k") == "in":
                            try:
                                s.write(base64.b64decode(m2.get("b64", "")))
                            except Exception:
                                pass
                        elif m2.get("k") == "resize":
                            s.pty.resize(int(m2.get("cols", 120)), int(m2.get("rows", 32)))
                    with s.clients_lock:
                        s.clients.discard(conn)
                    return
                resp = self.handle(msg)
                conn.sendall((json.dumps(resp) + "\n").encode())
        except ConnectionResetError:
            pass
        except Exception:
            log_line("client error: " + traceback.format_exc())
        finally:
            try:
                conn.close()
            except Exception:
                pass


KEYMAP = {
    "enter": "\r", "esc": "\x1b", "tab": "\t", "space": " ", "backspace": "\x7f",
    "up": "\x1b[A", "down": "\x1b[B", "left": "\x1b[D", "right": "\x1b[C",
    "home": "\x1b[H", "end": "\x1b[F", "delete": "\x1b[3~", "pgup": "\x1b[5~",
    "pgdn": "\x1b[6~", "c-c": "\x03", "c-d": "\x04", "c-z": "\x1a", "c-l": "\x0c",
}


# ---------------------------------------------------------------- agent helpers
def is_claude(argv):
    return ccs_agents.detect(argv[0]) == "claude"


def make_session_argv(name, argv, cwd):
    """按 agent 适配器生成创建参数；返回 (argv, session_id, agent_kind)。"""
    argv = [str(part) for part in argv]
    if not shutil.which(argv[0]):
        raise RuntimeError(
            "未找到命令 '%s'。先安装对应的 agent CLI，或用自定义命令: "
            "python ccs.py new %s -- cmd.exe" % (argv[0], name))
    return ccs_agents.prepare(name, argv, cwd)


def agent_display(agent, sid):
    if sid:
        return "%s session id: %s（重启后自动 --resume）" % (agent, sid)
    if agent == "generic":
        return ""
    return "%s: 未捕获到 session id，重启后按 agent 的 --continue 尽力恢复" % agent


# ---------------------------------------------------------------- rpc client
class DaemonClient:
    def __init__(self, port):
        self.port = port

    @classmethod
    def connect(cls, timeout=5):
        port = daemon_port()
        if not port:
            raise RuntimeError("daemon 未运行 (先执行: python ccs.py daemon start)")
        c = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        c.settimeout(None)
        return cls(c) if False else _wrap(c)

    def call(self, msg):
        raise NotImplementedError


class Conn:
    def __init__(self, sock):
        self.sock = sock
        self.f = sock.makefile("rb")

    def call(self, msg):
        self.sock.sendall((json.dumps(msg) + "\n").encode())
        line = self.f.readline()
        if not line:
            raise RuntimeError("daemon closed connection")
        return json.loads(line)

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


def _wrap(sock):
    return Conn(sock)


def daemon_port():
    try:
        info = json.loads(DAEMON_FILE.read_text(encoding="utf-8"))
        return int(info["port"])
    except Exception:
        return None


def daemon_alive():
    port = daemon_port()
    if not port:
        return False
    try:
        c = socket.create_connection(("127.0.0.1", port), timeout=1)
        c.sendall(b'{"k":"ping"}\n')
        c.settimeout(2)
        data = c.recv(4096)
        c.close()
        return b"pong" in data
    except Exception:
        return False


def start_daemon(restore=False, quiet=False):
    if daemon_alive():
        if restore:
            _rpc({"k": "restore"})
        return True
    CCS_HOME.mkdir(parents=True, exist_ok=True)
    logf = open(DAEMON_LOG, "ab")
    cmd = self_command(["_daemon"] + (["--restore"] if restore else []))
    subprocess.Popen(cmd, creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP,
                     stdin=subprocess.DEVNULL, stdout=logf, stderr=logf,
                     close_fds=True, cwd=str(SELF_DIR))
    deadline = time.time() + 15
    while time.time() < deadline:
        if daemon_alive():
            return True
        time.sleep(0.2)
    if not quiet:
        print("守护进程启动失败，查看日志: %s" % DAEMON_LOG)
    return False


def web_dir():
    """web/ 资源目录：源码模式在脚本旁；打包模式在 _MEIPASS 或 _internal 下。"""
    candidates = []
    if FROZEN:
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "web")
        candidates.append(SELF_EXE.parent / "_internal" / "web")
        candidates.append(SELF_EXE.parent / "web")
    candidates.append(SCRIPT_PATH.parent / "web")
    for cand in candidates:
        try:
            if cand and (cand / "index.html").is_file():
                return cand
        except OSError:
            continue
    return candidates[-1]


def self_command(args):
    """如何重新启动自己：源码模式用 python ccs.py，打包模式直接用 ccs.exe。"""
    if FROZEN:
        return [str(SELF_EXE)] + list(args)
    return [sys.executable, str(SCRIPT_PATH)] + list(args)


def ensure_daemon():
    if daemon_alive():
        return True
    return start_daemon()


def _rpc(msg, need_daemon=True):
    if need_daemon and not ensure_daemon():
        raise RuntimeError("无法连接守护进程")
    conn = Conn(socket.create_connection(("127.0.0.1", daemon_port())))
    try:
        return conn.call(msg)
    finally:
        conn.close()


# ---------------------------------------------------------------- console I/O
STD_INPUT_HANDLE = -10
STD_OUTPUT_HANDLE = -11
ENABLE_PROCESSED_INPUT = 0x0001
ENABLE_LINE_INPUT = 0x0002
ENABLE_ECHO_INPUT = 0x0004
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
ENABLE_VIRTUAL_TERMINAL_INPUT = 0x0200


def get_conmode(which):
    h = k32.GetStdHandle(which)
    mode = wt.DWORD(0)
    ok = k32.GetConsoleMode(h, ctypes.byref(mode))
    return (h, mode.value) if ok else (h, None)


def set_conmode(which, mode):
    h = k32.GetStdHandle(which)
    k32.SetConsoleMode(h, mode)


def enable_vt_out():
    h, mode = get_conmode(STD_OUTPUT_HANDLE)
    if mode is not None:
        set_conmode(STD_OUTPUT_HANDLE, mode | ENABLE_VIRTUAL_TERMINAL_PROCESSING)


def attach(name):
    if not ensure_daemon():
        return 1
    port = daemon_port()
    sock = socket.create_connection(("127.0.0.1", port))
    sock.settimeout(None)
    cols, rows = shutil.get_terminal_size((120, 32))
    sock.sendall((json.dumps({"k": "attach", "name": name, "cols": cols, "rows": rows}) + "\n").encode())
    f = sock.makefile("rb")

    first = f.readline()
    if not first:
        print("无法 attach")
        return 1
    msg = json.loads(first)
    if msg.get("k") == "err":
        print(msg.get("msg"))
        return 1
    sys.stdout.buffer.write(b"\x1b[2J\x1b[H" + base64.b64decode(msg.get("b64", "")))
    sys.stdout.buffer.flush()

    enable_vt_out()
    h_in, in_mode = get_conmode(STD_INPUT_HANDLE)
    raw = None
    if in_mode is not None:
        raw = in_mode & ~(ENABLE_LINE_INPUT | ENABLE_ECHO_INPUT | ENABLE_PROCESSED_INPUT)
        raw |= ENABLE_VIRTUAL_TERMINAL_INPUT
        set_conmode(STD_INPUT_HANDLE, raw)

    stop = threading.Event()
    out_lock = threading.Lock()

    def reader():
        try:
            while not stop.is_set():
                line = f.readline()
                if not line:
                    break
                m = json.loads(line)
                if m.get("k") in ("out", "snap"):
                    data = base64.b64decode(m.get("b64", ""))
                    with out_lock:
                        sys.stdout.buffer.write(data)
                        sys.stdout.buffer.flush()
                elif m.get("k") == "exit":
                    with out_lock:
                        sys.stdout.buffer.write(("\n[会话已退出, code=%s]\n" % m.get("code")).encode())
                        sys.stdout.buffer.flush()
                    break
        except Exception:
            pass
        finally:
            stop.set()

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    try:
        if in_mode is not None:
            # console: blocking ReadFile on stdin gives VT input bytes
            stdin_handle = ctypes.c_void_p(h_in)
            while not stop.is_set():
                try:
                    data = read_handle(_h(stdin_handle), 4096)
                except Exception:
                    break
                if not data:
                    break
                if b"\x1d" in data:  # Ctrl-]
                    sock.sendall(b'{"k":"detach"}\n')
                    break
                sock.sendall((json.dumps({"k": "in", "b64": base64.b64encode(data).decode()}) + "\n").encode())
        else:
            for line in sys.stdin.buffer:
                if stop.is_set():
                    break
                sock.sendall((json.dumps({"k": "in", "b64": base64.b64encode(line + b"\r").decode()}) + "\n").encode())
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        if raw is not None:
            set_conmode(STD_INPUT_HANDLE, in_mode)
        try:
            sock.close()
        except Exception:
            pass
    print("\n[已 detach, 会话仍在后台运行]")
    return 0


# ---------------------------------------------------------------- commands
def fmt_age(sec):
    sec = int(max(0, sec))
    if sec < 60:
        return "%ds" % sec
    if sec < 3600:
        return "%dm" % (sec // 60)
    if sec < 86400:
        return "%dh" % (sec // 3600)
    return "%dd" % (sec // 86400)


def cmd_ls(args):
    sessions = None
    if daemon_alive():
        sessions = _rpc({"k": "ls"}).get("sessions", [])
    else:
        recs = load_state().get("sessions", [])
        sessions = [{"name": r.get("name"), "argv": r.get("argv"), "cwd": r.get("cwd"),
                     "status": "stopped", "exit_code": None, "pid": r.get("pid"),
                     "age": time.time() - r.get("created", time.time()),
                     "last_active": r.get("last_active", 0)} for r in recs]
    if args.json:
        print(json.dumps(sessions, ensure_ascii=False, indent=1))
        return 0
    if not sessions:
        print("(没有会话)  python ccs.py new <名字> [--] [claude|命令...]")
        return 0
    print("%-18s %-8s %-8s %-6s %-6s %s" % ("名字", "状态", "PID", "运行", "退出码", "命令 / 目录"))
    for s in sessions:
        cmd = " ".join(s.get("argv") or [])
        print("%-18s %-8s %-8s %-6s %-6s %s  [%s]" % (
            s["name"], s["status"], str(s.get("pid") or "-"), fmt_age(s.get("age", 0)),
            str(s.get("exit_code") if s.get("exit_code") is not None else "-"),
            cmd, s.get("cwd", "")))
    return 0


def cmd_new(args):
    name = args.name
    cwd = Path(args.cwd).resolve() if args.cwd else Path.cwd()
    extra = [a for a in (args.cmd or []) if a != "--"]
    try:
        argv, sid, agent = make_session_argv(name, extra or ["claude"], cwd)
    except Exception as e:
        print("错误: %s" % e)
        return 1
    if not ensure_daemon():
        return 1
    resp = _rpc({"k": "new", "name": name, "argv": argv, "cwd": str(cwd),
                 "session_id": sid, "agent": agent})
    if resp.get("k") == "err":
        print("错误: %s" % resp.get("msg"))
        return 1
    hint = "ccs attach %s" % name if FROZEN else "python ccs.py attach %s" % name
    print("已创建会话 '%s' (agent=%s, pid=%s).  attach: %s" % (name, agent, resp.get("pid"), hint))
    note = agent_display(agent, sid)
    if note:
        print("  " + note)
    return 0


def cmd_attach(args):
    return attach(args.name)


def cmd_send(args):
    text = " ".join(args.text)
    resp = _rpc({"k": "send", "name": args.name, "text": text})
    return 0 if resp.get("k") == "ok" else (print(resp.get("msg")), 1)[1]


def cmd_type(args):
    text = " ".join(args.text)
    resp = _rpc({"k": "type", "name": args.name, "text": text})
    return 0 if resp.get("k") == "ok" else (print(resp.get("msg")), 1)[1]


def cmd_key(args):
    resp = _rpc({"k": "key", "name": args.name, "key": args.key})
    return 0 if resp.get("k") == "ok" else (print(resp.get("msg")), 1)[1]


def cmd_log(args):
    resp = _rpc({"k": "log", "name": args.name, "bytes": args.bytes or 0})
    if resp.get("k") == "err":
        print(resp.get("msg"))
        return 1
    data = base64.b64decode(resp.get("b64", ""))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()
    return 0


def cmd_rename(args):
    resp = _rpc({"k": "rename", "old": args.old, "new": args.new})
    if resp.get("k") == "err":
        print(resp.get("msg"))
        return 1
    print("已重命名: %s -> %s" % (args.old, args.new))
    return 0


def cmd_kill(args):
    resp = _rpc({"k": "kill", "name": args.name})
    print("已结束会话" if resp.get("k") == "ok" else resp.get("msg"))
    return 0


def cmd_rm(args):
    resp = _rpc({"k": "rm", "name": args.name})
    print("已删除会话" if resp.get("k") == "ok" else resp.get("msg"))
    return 0


def cmd_restore(args):
    if not start_daemon(restore=False):
        return 1
    resp = _rpc({"k": "restore", "names": args.names or None})
    started = resp.get("started", [])
    print("已恢复 %d 个会话: %s" % (len(started), ", ".join(started) if started else "-"))
    for e in resp.get("errors", []):
        print("  失败:", e)
    return 0


def cmd_daemon(args):
    if args.action == "start":
        ok = start_daemon(restore=args.restore, quiet=args.quiet)
        if ok and not args.quiet:
            print("守护进程已运行, port=%s" % daemon_port())
        return 0 if ok else 1
    if args.action == "stop":
        if not daemon_alive():
            print("守护进程未运行")
            return 0
        _rpc({"k": "shutdown"})
        print("已停止")
        return 0
    if args.action == "status":
        alive = daemon_alive()
        print("运行中 port=%s pid=%s" % (daemon_port(), _rpc({"k": "ping"}, need_daemon=False).get("pid"))
              if alive else "未运行")
        return 0 if alive else 1
    return 1


def cmd_autostart(args):
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                         r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
    try:
        if args.action == "on":
            if FROZEN:
                val = '"%s" daemon start --restore --quiet' % str(SELF_EXE)
            else:
                pyw = Path(sys.executable).with_name("pythonw.exe")
                exe = str(pyw if pyw.exists() else Path(sys.executable))
                script = str(Path(__file__).resolve())
                val = '"%s" "%s" daemon start --restore --quiet' % (exe, script)
            winreg.SetValueEx(key, "ccs-daemon", 0, winreg.REG_SZ, val)
            print("已设置开机自启(登录时自动恢复会话): %s" % val)
        else:
            try:
                winreg.DeleteValue(key, "ccs-daemon")
                print("已取消开机自启")
            except FileNotFoundError:
                print("本来就没有自启")
    finally:
        winreg.CloseKey(key)
    return 0


def cmd_version(args):
    print("ccs %s  python %s" % (VERSION, sys.version.split()[0]))
    print("state: %s" % CCS_HOME)
    print("agents: %s" % ccs_agents.describe_for_version())
    return 0


def cmd_agents(args):
    rows = ccs_agents.discover()
    print("%-10s %-8s %-8s %-8s %-6s %s" % ("agent", "已安装", "建会话", "可恢复", "continue", "路径"))
    for row in rows:
        caps = row["caps"]
        print("%-10s %-8s %-8s %-8s %-6s %s" % (
            row["agent"], "yes" if row["found"] else "-",
            "id" if caps.get("new") else "-",
            "yes" if caps.get("resume") else "-",
            "yes" if caps.get("continue") else "-",
            row["path"] or ""))
    print("\n提示: 自定义 agent 可在 %s 里配置（aliases/new/resume/continue/id_regex）。" % (CCS_HOME / "agents.json"))
    return 0


def cmd_bus(args):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ccs_bus
    return ccs_bus.main(args.rest)


def cmd_mcp(args):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ccs_mcp
    return ccs_mcp.main()


def cmd_web(args):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import ccs_web
    except Exception as exc:
        print("web 控制台不可用: %s" % exc)
        return 1
    argv = []
    if getattr(args, "port", None):
        argv += ["--port", str(args.port)]
    if getattr(args, "host", None):
        argv += ["--host", args.host]
    if getattr(args, "open", False):
        argv += ["--open"]
    return ccs_web.main(argv)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    os.environ["CCS_CMD_JSON"] = json.dumps(self_command([]))
    if argv and argv[0] == "_daemon":
        CCS_HOME.mkdir(parents=True, exist_ok=True)
        d = Daemon()
        d.restore_records()
        start_restore = "--restore" in argv
        if start_restore:
            # delay restore until server is up
            pass
        t = threading.Thread(target=d.serve, daemon=False)
        # serve in main thread instead for signal simplicity
        if start_restore:
            def delayed():
                time.sleep(0.5)
                recs = load_state().get("sessions", [])
                for rec in recs:
                    argv2, sid2, note = ccs_agents.resume_argv(rec)
                    if not argv2:
                        log_line("restore %s skipped: %s" % (rec.get("name"), note))
                        continue
                    try:
                        d.rpc_new({"name": rec.get("name"), "argv": argv2,
                                   "cwd": rec.get("cwd"), "session_id": sid2,
                                   "agent": rec.get("agent")})
                    except Exception as e:
                        log_line("restore %s failed: %r" % (rec.get("name"), e))
            threading.Thread(target=delayed, daemon=True).start()
        d.serve()
        return 0

    p = argparse.ArgumentParser(prog="ccs", description="Windows 上的 tmux for Claude CLI")
    p.add_argument("--version", action="store_true", help="打印版本")
    sub = p.add_subparsers(dest="command")

    pd = sub.add_parser("daemon", help="守护进程")
    pd.add_argument("action", choices=["start", "stop", "status"])
    pd.add_argument("--restore", action="store_true")
    pd.add_argument("--quiet", action="store_true")
    pd.set_defaults(func=cmd_daemon)

    pn = sub.add_parser("new", help="新建会话")
    pn.add_argument("name")
    pn.add_argument("--cwd", default=None)
    pn.add_argument("cmd", nargs=argparse.REMAINDER)
    pn.set_defaults(func=cmd_new)

    pL = sub.add_parser("ls", help="列出会话")
    pL.add_argument("--json", action="store_true")
    pL.set_defaults(func=cmd_ls)

    pa = sub.add_parser("attach", help="接入会话 (Ctrl-] detach)")
    pa.add_argument("name")
    pa.set_defaults(func=cmd_attach)

    ps = sub.add_parser("send", help="注入文本+回车")
    ps.add_argument("name")
    ps.add_argument("text", nargs=argparse.REMAINDER)
    ps.set_defaults(func=cmd_send)

    pt = sub.add_parser("type", help="只注入文本")
    pt.add_argument("name")
    pt.add_argument("text", nargs=argparse.REMAINDER)
    pt.set_defaults(func=cmd_type)

    pk = sub.add_parser("key", help="发送特殊键")
    pk.add_argument("name")
    pk.add_argument("key")
    pk.set_defaults(func=cmd_key)

    pl = sub.add_parser("log", help="输出会话近期原始输出")
    pl.add_argument("name")
    pl.add_argument("--bytes", type=int, default=0)
    pl.set_defaults(func=cmd_log)

    pr = sub.add_parser("rename", help="重命名会话")
    pr.add_argument("old")
    pr.add_argument("new")
    pr.set_defaults(func=cmd_rename)

    pkill = sub.add_parser("kill", help="结束会话进程")
    pkill.add_argument("name")
    pkill.set_defaults(func=cmd_kill)

    prm = sub.add_parser("rm", help="删除会话(含记录)")
    prm.add_argument("name")
    prm.set_defaults(func=cmd_rm)

    pre = sub.add_parser("restore", help="重启后恢复所有会话")
    pre.add_argument("names", nargs="*")
    pre.set_defaults(func=cmd_restore)

    pau = sub.add_parser("autostart", help="开机自启")
    pau.add_argument("action", choices=["on", "off"])
    pau.set_defaults(func=cmd_autostart)

    pb = sub.add_parser("bus", help="多 agent 消息总线 (见 ccs_bus.py)")
    pb.add_argument("rest", nargs=argparse.REMAINDER)
    pb.set_defaults(func=cmd_bus)

    pm = sub.add_parser("mcp", help="启动 MCP stdio server")
    pm.set_defaults(func=cmd_mcp)

    pw = sub.add_parser("web", help="浏览器可视化控制台")
    pw.add_argument("--port", type=int, default=None, help="端口（默认 8787）")
    pw.add_argument("--host", default=None, help="监听地址（默认 127.0.0.1）")
    pw.add_argument("--open", action="store_true", help="启动后打开浏览器")
    pw.set_defaults(func=cmd_web)

    pag = sub.add_parser("agents", help="查看支持的 agent 与恢复能力")
    pag.set_defaults(func=cmd_agents)

    pv = sub.add_parser("version", help="版本信息")
    pv.set_defaults(func=cmd_version)

    args = p.parse_args(argv)
    if args.version:
        return cmd_version(args)
    if not getattr(args, "command", None):
        p.print_help()
        if FROZEN:
            print("\n提示: 双击打开时请在新终端里执行 ccs 命令; 按回车关闭本窗口。")
            try:
                input()
            except Exception:
                pass
        return 1
    if args.command == "bus" and not args.rest:
        print("用法: python ccs.py bus send --from X --to Y 'msg' | inbox --as X")
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
