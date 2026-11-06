#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ccs_agents.py - 多 agent 适配层。

ccs 原本只认识 Claude Code（--session-id / --resume）。本模块把它抽象成
"agent 适配器"，让 ccs 的会话命名 / 持久化 / 重启恢复也能用于其它 CLI：

    claude   : --session-id <uuid> 创建 / --resume <uuid> 恢复（最完整）
    codex    : 无预置 id；codex resume <id> / codex resume --last；扫 ~/.codex/sessions
    pi       : pi --session <id|path> / pi -c；扫 ~/.pi 下的会话文件
    gemini   : --resume <id> / --continue；扫 ~/.gemini/tmp/*/chats
    opencode : --session <id> / --continue
    qwen     : gemini 分支，同 gemini
    kimi / cursor-agent / copilot / aider ... : 尽力而为（探测 help）
    未知命令 : 探测 --help 里的 --resume / --continue，找不到则不恢复（只重建）

用户可在 %USERPROFILE%\\.ccs\\agents.json 里加自定义适配器：
    {
      "myagent": {
        "aliases": ["myagent"],
        "new": ["{exe}", "--session-id", "{sid}"],
        "resume": ["{exe}", "--resume", "{sid}"],
        "continue": ["{exe}", "--continue"],
        "id_regex": "session id[: ]+([0-9a-f-]{36})"
      }
    }

仅使用标准库。
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

HOME = Path(os.environ.get("CCS_HOME") or (Path.home() / ".ccs"))
CACHE = HOME / "agents_cache.json"
CONFIG = HOME / "agents.json"

UUID_RE = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

DEFAULTS = {
    "claude": {
        "aliases": ["claude"],
        "new": ["{exe}", "--session-id", "{sid}", "--name", "{name}"],
        "new_flag": "--session-id",
        "name_flag": "--name",
        "resume": ["{exe}", "--resume", "{sid}"],
        "continue": ["{exe}", "--continue"],
        "id_regex": [r"session[_ -]?id[:\s]+(" + UUID_RE + ")"],
        "store": [],
    },
    "codex": {
        "aliases": ["codex"],
        "new": ["{exe}"],
        "resume": ["{exe}", "resume", "{sid}"],
        "continue": ["{exe}", "resume", "--last"],
        "id_regex": [r"session[_ -]?id[:\s]+(" + UUID_RE + ")"],
        "store": [{"root": "~/.codex/sessions", "glob": "**/*.jsonl", "id_from": "filename"}],
    },
    "pi": {
        "aliases": ["pi", "pi.coding-agent"],
        "new": ["{exe}"],
        "resume": ["{exe}", "--session", "{sid}"],
        "continue": ["{exe}", "-c"],
        "id_regex": [r"session[_ -]?id[:\s]+(" + UUID_RE + ")"],
        "store": [{"root": "~/.pi", "glob": "**/*.jsonl", "id_from": "filename"}],
    },
    "gemini": {
        "aliases": ["gemini"],
        "new": ["{exe}"],
        "resume": ["{exe}", "--resume", "{sid}"],
        "continue": ["{exe}", "--continue"],
        "id_regex": [r"session[_ -]?id[:\s]+(" + UUID_RE + ")"],
        "store": [{"root": "~/.gemini/tmp", "glob": "**/session-*.json", "id_from": "filename"}],
    },
    "opencode": {
        "aliases": ["opencode"],
        "new": ["{exe}"],
        "resume": ["{exe}", "--session", "{sid}"],
        "continue": ["{exe}", "--continue"],
        "id_regex": [r"session[_ -]?id[:\s]+([A-Za-z0-9_-]{10,})"],
        "store": [{"root": "~/.local/share/opencode", "glob": "**/ses_*.json", "id_from": "filename"}],
    },
    "qwen": {
        "aliases": ["qwen"],
        "new": ["{exe}"],
        "resume": ["{exe}", "--resume", "{sid}"],
        "continue": ["{exe}", "--continue"],
        "id_regex": [r"session[_ -]?id[:\s]+(" + UUID_RE + ")"],
        "store": [{"root": "~/.qwen/tmp", "glob": "**/session-*.json", "id_from": "filename"}],
    },
    "kimi": {
        "aliases": ["kimi"],
        "new": ["{exe}"],
        "resume": ["{exe}", "--resume", "{sid}"],
        "continue": ["{exe}", "--continue"],
        "id_regex": [r"session[_ -]?id[:\s]+([A-Za-z0-9_-]{6,})"],
        "store": [],
    },
    "cursor": {
        "aliases": ["cursor-agent", "cursor"],
        "new": ["{exe}"],
        "resume": ["{exe}", "--resume", "{sid}"],
        "continue": ["{exe}", "--continue"],
        "id_regex": [r"session[_ -]?id[:\s]+([A-Za-z0-9_-]{6,})"],
        "store": [],
    },
    "copilot": {
        "aliases": ["copilot"],
        "new": ["{exe}"],
        "resume": ["{exe}", "--resume", "{sid}"],
        "continue": ["{exe}", "--continue"],
        "id_regex": [r"session[_ -]?id[:\s]+([A-Za-z0-9_-]{6,})"],
        "store": [],
    },
    "aider": {
        "aliases": ["aider"],
        "new": ["{exe}"],
        "resume": ["{exe}", "--restore-chat-history"],
        "continue": ["{exe}", "--restore-chat-history"],
        "id_regex": [],
        "store": [],
    },
}

_CACHE = {"mtime": 0.0, "data": {}}
_CONFIG_CACHE = {"mtime": 0.0, "data": {}}


# --------------------------------------------------------------------------
def base_name(exe):
    name = Path(str(exe)).name.lower()
    for suffix in (".exe", ".cmd", ".bat", ".ps1"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


def load_config():
    try:
        mtime = CONFIG.stat().st_mtime
    except OSError:
        return {}
    if _CONFIG_CACHE["mtime"] == mtime:
        return _CONFIG_CACHE["data"]
    try:
        data = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    _CONFIG_CACHE["mtime"] = mtime
    _CONFIG_CACHE["data"] = data
    return data


def registry():
    reg = {name: dict(spec) for name, spec in DEFAULTS.items()}
    for name, spec in load_config().items():
        if isinstance(spec, dict):
            base = reg.get(name, {})
            merged = dict(base)
            merged.update(spec)
            reg[name] = merged
    return reg


def detect(exe):
    """根据可执行文件名识别 agent 类型，未知返回 'generic'。"""
    base = base_name(exe)
    reg = registry()
    for name, spec in reg.items():
        aliases = spec.get("aliases") or [name]
        if base in [str(a).lower() for a in aliases]:
            return name
    return "generic"


def spec_for(kind):
    return registry().get(kind) or {}


# --------------------------------------------------------------------------
def _run_help(exe):
    """运行 '<exe> --help'；Windows 的 .cmd/.bat 需要经 cmd.exe。"""
    resolved = shutil.which(exe) or exe
    cmd = [resolved, "--help"]
    kwargs = dict(capture_output=True, text=True, timeout=20,
                  encoding="utf-8", errors="replace")
    try:
        proc = subprocess.run(cmd, **kwargs)
    except (OSError, ValueError):
        if str(resolved).lower().endswith((".cmd", ".bat")):
            comspec = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
            proc = subprocess.run([comspec, "/d", "/s", "/c", subprocess.list2cmdline(cmd)], **kwargs)
        else:
            raise
    return (proc.stdout or "") + (proc.stderr or "")


def _help_text(exe, refresh=False):
    """缓存 '<exe> --help' 的输出（用于能力探测）。"""
    try:
        mtime = CACHE.stat().st_mtime
        if not refresh and _CACHE["mtime"] == mtime:
            return _CACHE["data"].get(exe, "")
    except OSError:
        pass
    text = ""
    try:
        text = _run_help(exe)
    except Exception:
        text = ""
    try:
        data = json.loads(CACHE.read_text(encoding="utf-8-sig")) if CACHE.exists() else {}
    except Exception:
        data = {}
    data[exe] = text
    try:
        HOME.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        _CACHE["mtime"] = CACHE.stat().st_mtime
    except Exception:
        pass
    _CACHE["data"] = data
    return text


def supports_flag(exe, flag):
    if not flag:
        return False
    return flag in _help_text(exe)


# --------------------------------------------------------------------------
def new_session_id():
    return str(uuid.uuid4())


def prepare(name, argv, cwd):
    """创建会话时的 argv 处理。返回 (argv, session_id, agent_kind)。"""
    argv = [str(part) for part in argv]
    kind = detect(argv[0])
    spec = spec_for(kind)
    exe = argv[0]

    if not spec:
        return argv, None, kind

    template = spec.get("new")
    if not template:
        return argv, None, kind

    new_flag = spec.get("new_flag")
    if new_flag:
        if not shutil.which(exe):
            return argv, None, kind
        if not supports_flag(exe, new_flag):
            return argv, None, kind
    sid = new_session_id()
    try:
        built = [part.format(exe=exe, name=name, sid=sid) for part in template]
    except (KeyError, IndexError):
        return argv, None, kind
    # 用户额外参数追加在后面
    return built + argv[1:], sid, kind


def resume_argv(record):
    """根据会话记录生成恢复用的 argv；返回 (argv 或 None, session_id, 说明)。"""
    argv = list(record.get("argv") or [])
    if not argv:
        return None, None, "会话记录里没有 argv"
    kind = record.get("agent") or detect(argv[0])
    spec = spec_for(kind)

    sid = record.get("session_id") or record.get("claude_sid")
    if not sid:
        sid = capture_from_store(kind, record)

    exe = argv[0]
    template = spec.get("resume")
    if sid and template:
        try:
            return [part.format(exe=exe, name=record.get("name", ""), sid=sid) for part in template], sid, ""
        except (KeyError, IndexError):
            pass

    cont = spec.get("continue")
    if cont:
        try:
            return [part.format(exe=exe, name=record.get("name", ""), sid=sid or "") for part in cont], sid, \
                   "" if sid else "未捕获到会话 id，使用 --continue 恢复该 agent 的最近一次会话"
        except (KeyError, IndexError):
            pass
    return None, sid, "该 agent 没有可用的恢复方式（可在 agents.json 里配置）"


# --------------------------------------------------------------------------
def match_session_id(kind, text):
    """从终端输出里抓 session id。"""
    spec = spec_for(kind)
    for pattern in spec.get("id_regex") or []:
        try:
            m = re.search(pattern, text, re.IGNORECASE)
        except re.error:
            continue
        if m:
            return m.group(1)
    return None


def capture_from_store(kind, record, window=4 * 3600):
    """在 agent 的会话目录里找本次会话产生的 session id（尽力而为）。"""
    spec = spec_for(kind)
    stores = spec.get("store") or []
    if not stores:
        return None
    created = float(record.get("created") or 0)
    best = None
    for store in stores:
        root = Path(os.path.expanduser(store.get("root", "")))
        if not root.is_dir():
            continue
        pattern = store.get("glob", "**/*")
        id_from = store.get("id_from", "filename")
        for path in glob.iglob(str(root / pattern), recursive=True):
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            if created and mtime < created - 120:
                continue
            if created and mtime > created + window:
                continue
            if best is None or mtime > best[0]:
                best = (mtime, path)
        if best and id_from == "filename":
            m = re.search(UUID_RE, os.path.basename(best[1]))
            if m:
                return m.group(0)
        if best and id_from == "content":
            try:
                head = Path(best[1]).read_text(encoding="utf-8", errors="replace")[:4000]
            except OSError:
                head = ""
            for pattern in spec.get("id_regex") or []:
                m = re.search(pattern, head, re.IGNORECASE)
                if m:
                    return m.group(1)
            m = re.search(UUID_RE, head)
            if m:
                return m.group(0)
    return None


# --------------------------------------------------------------------------
def discover():
    """列出所有适配器及本机安装情况。"""
    rows = []
    for kind, spec in sorted(registry().items()):
        aliases = spec.get("aliases") or [kind]
        found = None
        for alias in aliases:
            exe = shutil.which(alias)
            if exe:
                found = exe
                break
        caps = {"new": bool(spec.get("new_flag")), "resume": bool(spec.get("resume")),
                "continue": bool(spec.get("continue"))}
        if found and spec.get("new_flag"):
            caps["new"] = supports_flag(found, spec["new_flag"])
        rows.append({"agent": kind, "aliases": aliases, "found": found,
                     "path": found or "", "caps": caps})
    return rows


def describe_for_version():
    rows = [r for r in discover() if r["found"]]
    if not rows:
        return "未检测到已安装的 agent CLI"
    return ", ".join("%s%s" % (r["agent"], "" if r["caps"]["resume"] else "(不可恢复)") for r in rows)
