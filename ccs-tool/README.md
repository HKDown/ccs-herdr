# ccs-tool —— Windows 上的 tmux for Claude CLI

**一句话定位：给 Windows 原生的 Claude Code CLI（以及任何命令行程序）配上“可命名、关窗不丢、重启可恢复、多 agent 互通”的会话管理，不依赖 WSL、不依赖任何第三方 Python 包。**

> 状态目录默认 `%USERPROFILE%\.ccs`，可用环境变量 `CCS_HOME` 覆盖。
> 全部实现只使用 Python 标准库，Windows 上的进程隔离基于 ConPTY。

---

## 目录

- [它解决什么问题](#它解决什么问题)
- [能力对照表](#能力对照表)
- [环境要求](#环境要求)
- [安装](#安装)
- [快速开始（5 条命令）](#快速开始5-条命令)
- [命令表](#命令表)
- [多 agent：消息总线与 MCP](#多-agent消息总线与-mcp)
- [重启恢复原理](#重启恢复原理)
- [开机自启](#开机自启)
- [状态目录与数据](#状态目录与数据)
- [冒烟测试](#冒烟测试)
- [FAQ](#faq)
- [目录结构](#目录结构)

---

## 它解决什么问题

在 Windows 上直接开一个终端跑 `claude`，会遇到三个问题：

1. **关掉窗口，会话就没了** —— 没法像 tmux 那样 detach，第二天回来接着聊。
2. **重启电脑，上下文要重来** —— 进程不跨重启；即使 `claude --resume` 能接回对话，也得手动记住 session id。
3. **多个 agent 之间没法互相通知** —— 各跑各的，协调只能靠人复制粘贴。

ccs-tool 的做法：

- 一个常驻**守护进程**（detached，不开窗口）用 ConPTY 托管每个会话的进程；
- 会话**有名字**，可 `attach` / `detach`（`Ctrl-]`）、可 `send` / `type` / `key` 注入输入；
- 会话定义和 Claude session id 写入 `state.json`，重启后 `restore` 重建会话并 `claude --resume <id>` 接回原对话；
- 内置 SQLite **消息总线**（`ccs bus ...`）和 **MCP server**（`ccs_mcp.py`），让多个 agent 互相发消息。

---

## 能力对照表

| 能力 | ccs-tool | tmux（Linux/macOS/WSL） | 直接开终端窗口 |
| --- | --- | --- | --- |
| 会话命名 | ✅ | ✅ | ❌ |
| 关闭终端后进程继续跑 | ✅ | ✅ | ❌ |
| detach / attach | ✅（`Ctrl-]` 退出） | ✅（`Ctrl-b d`） | ❌ |
| 会话列表 / 重命名 | ✅ | ✅ | ❌ |
| 向会话注入文本、发送按键 | ✅ | ✅ | ❌ |
| 回看最近输出 | ✅（原始字节） | ✅ | ❌ |
| **重启机器后恢复** | ✅（`restore`） | ❌（tmux 会话随系统重启消失） | ❌ |
| **恢复 Claude 对话上下文** | ✅（`claude --resume <session-id>`） | ❌（需自己记 id） | ❌（需自己记 id） |
| agent 之间消息总线 | ✅（SQLite） | ❌ | ❌ |
| MCP server 集成 | ✅（stdio JSON-RPC） | ❌ | ❌ |
| Windows 原生、无需 WSL | ✅ | ❌（WSL 内） | ✅ |
| 第三方依赖 | 无（仅 Python 标准库） | 需安装 tmux | 无 |
| 终端分屏 / 窗口布局 | ❌（交给 Windows Terminal 多标签/多窗口） | ✅ | ❌ |

---

## 环境要求

| 项目 | 要求 |
| --- | --- |
| 操作系统 | Windows 10 1809+ / Windows 11（需要 ConPTY） |
| Python | 3.10+，命令为 `python`（安装时勾选 Add to PATH） |
| 第三方 Python 包 | 无，只用标准库 |
| Claude Code CLI | 可选。只跑普通命令（`cmd.exe` / `powershell` / 脚本）时不需要；要用“恢复对话”能力需要支持 `--session-id` 与 `--resume` 的 Claude Code CLI 版本 |
| Node.js | 可选，仅当你要用 Claude Code 的 MCP 客户端时才需要 |

> PowerShell 版本：脚本同时兼容 Windows PowerShell 5.1（`powershell.exe`）和 PowerShell 7（`pwsh`）。
> 只有 5.1 的机器（Windows 默认自带）请用下面的 `powershell -NoProfile -ExecutionPolicy Bypass -File ...` 写法。

---

## 安装

### 方式 A：不安装，直接在源码目录运行

```powershell
cd D:\he271\Desktop\其他\ccs-tool
.\ccs.cmd version
# 等价于：
python .\ccs.py version
```

`ccs.cmd` 会先 `chcp 65001` 再调用 `python ccs.py`，保证中文输出不乱码。

### 方式 B：install.ps1（推荐，生成全局 `ccs` 命令）

```powershell
cd D:\he271\Desktop\其他\ccs-tool
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1

# 开机自启（可选）：
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Autostart

# 如果机器上有 PowerShell 7，也可以：
pwsh -NoProfile -File .\install.ps1
```

install.ps1 做的事（幂等，可反复运行，**不需要管理员权限**）：

1. 检查 `python` 是否存在、版本是否 >= 3.10；
2. 在 `%USERPROFILE%\.ccs\bin\ccs.cmd` 生成启动器（shim），内容指向**本源码目录的绝对路径** `ccs.py`；
3. 把 `%USERPROFILE%\.ccs\bin` 加入**当前用户**的 `PATH`（已包含则跳过，不会重复追加）；
4. 可选 `-Autostart`：执行 `python ccs.py autostart on` 注册开机自启；
5. 打印每一步的结果与警告。

安装完成后**重新打开一个终端**（让 PATH 生效），验证：

```powershell
ccs version
# ccs 0.1.0  python 3.14.7
# state: C:\Users\<你>\.ccs
# claude: found, session-id=True name=True   （未安装则显示 未安装）
```

> 如果不想改 PATH，也可以始终用 `python ccs.py ...` 或源码目录的 `.\ccs.cmd ...`。

### 方式 C：安装包（给不想装 Python 的人）

双击 `ccs-setup-0.1.0.exe`，按向导点“安装”即可：

- 默认装到 `%LOCALAPPDATA%\Programs\ccs`（无需管理员权限），**自带 Python 运行时**，目标机器不需要另外装 Python；
- 自动把安装目录加入当前用户 PATH、创建开始菜单快捷方式；可选“开机自启”和“桌面快捷方式”；
- 装完后**新开一个终端**，直接敲 `ccs` 就能用（命令与源码模式完全相同，只是把 `python ccs.py` 换成 `ccs`）：

```powershell
ccs daemon start
ccs new claude1 -- claude
ccs attach claude1
```

- 卸载：Windows「设置 → 应用 → ccs-tool → 卸载」，或运行安装目录下的 `ccs-uninstall.exe`；
- 静默安装（适合脚本批量）：`ccs-setup-0.1.0.exe /S /DIR="D:\Tools\ccs"`；静默卸载：`ccs-uninstall.exe /uninstall /S`；
- 便携版：解压 `ccs-portable-0.1.0.zip`，直接运行 `ccs\ccs.exe`（不加 PATH 也能用，只是要写全路径）；
- 安装包没有代码签名，首次运行 Windows 可能提示“已保护你的电脑”，点「更多信息 → 仍要运行」即可。

> 安装包和便携版都是用 PyInstaller 打包的，Python 运行时已内置；源码方式（方式 A/B）仍然可用，两者共用同一个状态目录 `%USERPROFILE%\.ccs`。

---

## 快速开始（5 条命令）

```powershell
# 1. 启动常驻守护进程（后台运行，不占窗口）
python ccs.py daemon start

# 2. 新建一个名为 claude1 的会话，运行 claude（-- 之后是要运行的命令；省略则默认 claude）
python ccs.py new claude1 -- claude

# 3. 列出所有会话（--json 供脚本使用）
python ccs.py ls

# 4. 接入会话（Ctrl-] 退出 attach，会话继续在后台跑）
python ccs.py attach claude1

# 5. 不进入会话，直接向它发一条消息并回车（适合脚本/其它 agent 调用）
python ccs.py send claude1 "请总结一下当前项目的目录结构"
```

装过 install.ps1 后，以上命令中的 `python ccs.py` 都可以简写成 `ccs`。

---

## 命令表

所有命令都支持 `--help`，例如 `python ccs.py new --help`。

| 命令 | 说明 |
| --- | --- |
| `python ccs.py daemon start [--restore] [--quiet]` | 启动守护进程；`--restore` 启动后立即恢复所有已记录会话 |
| `python ccs.py daemon stop` | 停止守护进程 |
| `python ccs.py daemon status` | 查看守护进程是否运行（运行返回 0，未运行返回 1） |
| `python ccs.py new NAME [--cwd DIR] [--] [CMD...]` | 新建命名会话。`CMD` 省略时默认 `claude`；`--cwd` 指定工作目录；`--` 之后的参数都当作命令 |
| `python ccs.py ls [--json]` | 列出会话；`--json` 输出 JSON 数组（字段：`name/argv/cwd/status/exit_code/pid/age/last_active/claude_sid`） |
| `python ccs.py attach NAME` | 接入会话，键盘输入直达会话；**`Ctrl-]` detach** |
| `python ccs.py send NAME TEXT` | 向会话注入文本并回车（TEXT 可含空格，如 `"请执行测试"`） |
| `python ccs.py type NAME TEXT` | 只注入文本，**不**回车 |
| `python ccs.py key NAME KEY` | 发送特殊键。KEY 支持：`Enter Esc Tab Space Backspace Up Down Left Right Home End Delete PgUp PgDn C-c C-d C-z C-l` |
| `python ccs.py log NAME [--bytes N]` | 输出会话最近 N 字节原始输出（含 ANSI 转义序列）；`--bytes 0` 表示缓冲区全部（上限 2 MiB） |
| `python ccs.py rename OLD NEW` | 重命名会话（会话进程不受影响） |
| `python ccs.py kill NAME` | 结束会话进程，但**保留记录**；默认不会被 `restore` 复活，`restore NAME` 可强制恢复 |
| `python ccs.py rm NAME` | 删除会话（结束进程 + 删除记录，**不可恢复**） |
| `python ccs.py restore [NAME...]` | 重启后恢复已记录会话（不带 NAME 恢复全部）；会话按原 `argv` 重建，Claude 会话自动 `claude --resume <session-id>` |
| `python ccs.py autostart on|off` | 开启/关闭登录时自动启动守护进程并恢复会话（写 HKCU Run，无管理员权限） |
| `python ccs.py bus ...` | 多 agent 消息总线，参数透传给 `ccs_bus.py`（见下一节） |
| `python ccs.py mcp` | 启动 stdio MCP server（等价于直接运行 `ccs_mcp.py`） |
| `python ccs.py version` / `--version` | 版本、状态目录、Claude CLI 能力检测 |

补充说明：

- `new` 的 `--cwd` 必须写在命令之前：`python ccs.py new dev --cwd D:\proj -- cmd.exe`。
- 命令里带 `-` 开头的参数时，用 `--` 分隔，避免被 ccs 自己解析：`python ccs.py new dev -- powershell -NoLogo`。
- `kill` 与 `rm` 的区别：`kill` 只结束进程、记录还在（默认不被 `restore` 复活，`restore NAME` 可强制恢复）；`rm` 连记录一起删掉，无法恢复。

---

## 多 agent 会话恢复

ccs 的"命名会话 + 重启恢复"不再只支持 Claude Code，内置了适配层（`ccs_agents.py`）：

```powershell
ccs agents          # 查看支持的 agent、本机是否安装、是否支持建会话/恢复
```

| agent | 创建时指定会话 id | 恢复方式 | 会话 id 来源 |
|---|---|---|---|
| **claude** | ✅ `--session-id <uuid>` | `claude --resume <uuid>`（+ `--name`） | 创建时注入 |
| **codex** | ❌ | `codex resume <id>` / `codex resume --last` | 输出抓取 + 扫 `~/.codex/sessions` |
| **pi** | ❌ | `pi --session <id>` / `pi -c` | 输出抓取 + 扫 `~/.pi` |
| **gemini** | ❌ | `gemini --resume <id>` / `--continue` | 输出抓取 + 扫 `~/.gemini/tmp` |
| **opencode** | ❌ | `opencode --session <id>` / `--continue` | 扫 `~/.local/share/opencode` |
| **qwen** | ❌ | `qwen --resume <id>` / `--continue` | 扫 `~/.qwen/tmp` |
| **kimi / cursor-agent / copilot** | ❌ | 探测 `--resume` / `--continue` | 尽力而为 |
| **aider** | ❌ | `--restore-chat-history` | 无 id |

工作方式（三层降级）：

1. **能指定 id 的**（claude）：创建时直接注入会话 id，重启后精确 `--resume`；
2. **不能指定、但会打印 id 的**（codex 等）：后台从终端输出里抓 `session id: ...`；
3. **两者都没有的**：按 agent 的 `--continue`（最近一次会话）恢复，并在 `restore` 的输出里提示；
4. 都做不到（比如未知命令）：只重建进程、不恢复对话，并在错误列表里说明。

### 自定义 agent

在 `%USERPROFILE%\.ccs\agents.json` 里加一条即可（支持 `{exe}` / `{sid}` / `{name}` 占位符）：

```json
{
  "myagent": {
    "aliases": ["myagent"],
    "new": ["{exe}", "--session-id", "{sid}"],
    "new_flag": "--session-id",
    "resume": ["{exe}", "--resume", "{sid}"],
    "continue": ["{exe}", "--continue"],
    "id_regex": ["session id[: ]+([0-9a-fA-F-]{36})"]
  }
}
```

> 说明：非 claude 的恢复依赖各 agent 自己的会话存储/参数，升级 CLI 后可能变化；
> `ccs agents` 会显示实际探测结果，`ccs restore` 会列出恢复失败或降级的会话。

---

## 可视化控制台（ccs web）

不想记命令时，用浏览器操作：

```powershell
ccs web            # 打开 http://127.0.0.1:8787/
ccs web --open     # 启动后自动打开浏览器
ccs web --port 9000
```

界面包含：左侧会话列表（状态灯、命令、目录、运行时长，点击即接入）、右侧 xterm.js 真终端
（关掉页面不影响会话）、新建/重命名/停止、消息总线面板。安装包里已加入「ccs 控制台」开始菜单快捷方式。

安全说明：默认只监听 `127.0.0.1`，无鉴权；不要改成 `--host 0.0.0.0`。

---

## Herdr 集成

Herdr 相关的代码、插件和数据已经拆分到**独立仓库** `ccs-herdr`（Rust 实现，与 Herdr 同语言生态，
支持 Windows/Linux/macOS，独立数据目录，git 管理）：

```powershell
cd <ccs-herdr>
cargo build --release
ccs-herdr install-plugin    # 把 plugin/ 链接进 Herdr
ccs-herdr open              # 在 Herdr 新建 ccs 工作区并打开所有会话窗格
```

ccs 本体不再携带 Herdr 代码，两者通过 ccs 守护进程的本地 RPC 协作。

---

## 多 agent：消息总线与 MCP

ccs 自带两条互通通道，都是**本机**范围，不经过网络：

- **CLI 总线**：`python ccs.py bus ...`（SQLite，数据库在 `%USERPROFILE%\.ccs\bus.sqlite3`）；
- **MCP server**：`ccs_mcp.py`，让 Claude Code 这类 MCP 客户端直接调用 `bus_send` / `bus_inbox` / `bus_peers` / `session_list` / `session_send`。

### 1) 命令行总线

```powershell
# 加入一个组（组内广播）
python ccs.py bus join --as agent-a --group team

# A 发给 B（按名字点对点）
python ccs.py bus send --from agent-a --to agent-b "接口改完了，帮我跑一下集成测试"

# A 广播给组
python ccs.py bus send --from agent-a --group team "构建挂了，大家先别合"

# B 读收件箱（--unread 只看未读，--json 供脚本解析）
python ccs.py bus inbox --as agent-b
python ccs.py bus inbox --as agent-b --unread --json

# 查看已知 peer、组与成员
python ccs.py bus peers
python ccs.py bus groups
```

也可以直接运行 `python ccs_bus.py ...`，参数完全相同。

### 2) 注册 MCP server（给 Claude Code 用）

把 `ccs_mcp.py` 的绝对路径注册给 Claude Code：

```powershell
claude mcp add ccs -- python "D:\he271\Desktop\其他\ccs-tool\ccs_mcp.py"
```

或在项目根目录写 `.mcp.json`（Windows 路径里的反斜杠要写两遍）：

```json
{
  "mcpServers": {
    "ccs": {
      "command": "python",
      "args": ["D:\\he271\\Desktop\\其他\\ccs-tool\\ccs_mcp.py"],
      "env": { "CCS_SESSION": "agent-a" }
    }
  }
}
```

注册后，Claude 就能直接调用这些工具：

| MCP 工具 | 作用 |
| --- | --- |
| `bus_send` | 发总线消息：`message` 必填，`to`（点对点）或 `group`（组广播）二选一；发送者取环境变量 `CCS_SESSION` |
| `bus_inbox` | 读发给当前 agent（及其所在组）的消息：`limit`、`unread_only` |
| `bus_peers` | 列出 peer、组和成员 |
| `session_list` | 列出 ccs 会话（读 `state.json`） |
| `session_send` | 向指定 ccs 会话注入文本并回车：`session`、`text` |

> **身份约定**：MCP 里的发送者名字来自 `CCS_SESSION` 环境变量（未设置为 `unknown`）。
> 建议在每个 agent 的 MCP 配置 `env` 里写不同的 `CCS_SESSION`（如上例 `agent-a`），
> 或在启动 `claude` 前 `set CCS_SESSION=agent-a`（Claude 及其 MCP 子进程会继承）。
> 用 CLI 时则直接用 `--from` 明确身份，不依赖环境变量。

### 典型多 agent 流程

```powershell
# 终端 1：协调者
python ccs.py new lead -- claude

# 终端 2：执行者
python ccs.py new worker -- claude

# 协调者给执行者发指令（不用切窗口）
python ccs.py send lead "去 bus 里看看 worker 的消息"

# 或者脚本里：
python ccs.py bus send --from lead --to worker "跑完测试把结果发我"
```

---

## 重启恢复原理

**关键事实：进程不跨重启。** 守护进程、ConPTY、会话里的 `claude` / `cmd.exe` 都活在内存里，电脑重启后全部消失；`state.json` 里留下的是“会话定义”。

恢复 = **重建会话进程 + 接回 Claude 对话**：

```text
重启前                                    重启后
------                                    ------
会话 "claude1"                             ccs restore
  argv: ["claude", ...]          ──读──▶     ↓ 新建 ConPTY 会话，名称仍为 claude1
  cwd : D:\proj                            argv: ["claude", "--resume", "<session-id>"]
  claude_sid: xxxxxxxx-....                ↓
                                            claude 用 --resume 接回 xxxxxxxx 这段对话
```

具体行为：

- `claude_sid` 来自创建会话时传给 `claude` 的 `--session-id <uuid>`（前提是你的 Claude Code CLI 支持该参数，创建时会自动检测并缓存到 `%USERPROFILE%\.ccs\claude.json`）；
- `restore` 时，若会话的 `argv` 是 `claude` 且记录了 `claude_sid`，则用 `claude --resume <sid>` 重建（CLI 支持时还会带上 `--name <会话名>`）；
- 若会话是自定义命令（如 `cmd.exe`、脚本），则按原 `argv` 重新拉起，进程内状态不保证；
- `kill` 过的会话记录仍在，默认不会被 `restore` 复活（避免把故意停掉的会话又拉起来），但 `restore NAME` 可强制恢复；`rm` 掉的会话无法恢复；
- 手动恢复：`python ccs.py restore`（或 `python ccs.py restore claude1`）；
- 守护进程一起恢复：`python ccs.py daemon start --restore`；
- 配合开机自启，登录后自动 `daemon start --restore`，等于“打开电脑会话就回来了”。

> 注意：恢复的是原 session 的对话（同一 session id），不是新开一个对话。

---

## 开机自启

```powershell
python ccs.py autostart on     # 注册登录自启
python ccs.py autostart off    # 取消
```

实现：在 `HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run` 写入名为 `ccs-daemon` 的值，内容等价于：

```text
pythonw.exe "D:\he271\Desktop\其他\ccs-tool\ccs.py" daemon start --restore --quiet
```

- 只写当前用户（HKCU），**不需要管理员权限**；
- 用 `pythonw.exe` 启动，登录时不会弹黑框；
- `--restore` 是关键：登录后不仅起守护进程，还会把上次的会话（含 Claude 对话）恢复回来；
- 想确认是否注册成功：

```powershell
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v ccs-daemon
```

> 如果 `ccs.py` 的源码目录移动了，需要重新执行 `python ccs.py autostart on`（以及重跑 install.ps1 更新 shim）。

---

## 状态目录与数据

默认位置：`%USERPROFILE%\.ccs`（可用 `CCS_HOME` 覆盖，例如设置到 D 盘）。

| 文件 / 目录 | 内容 |
| --- | --- |
| `state.json` | 会话定义：`name`、`argv`、`cwd`、`claude_sid`、`pid`、`created`、`last_active`、`exit_code` |
| `daemon.json` | 当前守护进程的端口、pid、启动时间、版本（守护进程运行时存在） |
| `daemon.log` | 守护进程日志（排查启动/恢复问题先看这里） |
| `bus.sqlite3` | 多 agent 消息总线（peers / groups / messages，WAL 模式） |
| `claude.json` | Claude CLI 能力检测缓存（`found` / `session_id` / `name`） |
| `bin\ccs.cmd` | install.ps1 生成的全局启动器 |

常用操作：

```powershell
python ccs.py version          # 显示实际使用的状态目录
python ccs.py ls --json        # 查看记录
python ccs.py rm NAME          # 删除单个会话记录
python ccs.py daemon stop      # 停守护进程后，可整体备份/删除状态目录
```

迁移/备份：先 `daemon stop`，再复制整个 `%USERPROFILE%\.ccs` 目录即可（`state.json` 与 `bus.sqlite3` 都是普通文件；运行中复制 SQLite 可能不一致，建议先停）。

---

## 冒烟测试

`test_smoke.ps1` 会端到端跑一遍：

```text
daemon start → new smoke -- cmd.exe → ls --json 含 smoke → send "echo SMOKE_OK"
→ 等 1s → log 含 SMOKE_OK → rename smoke smoke2 → ls 含 smoke2
→ kill smoke2 → rm smoke2 → ls 无残留 → daemon stop
```

每一步打印 `[PASS]` / `[FAIL]`，最后汇总；全部通过 exit 0，否则 exit 1。

```powershell
cd D:\he271\Desktop\其他\ccs-tool
powershell -NoProfile -ExecutionPolicy Bypass -File .\test_smoke.ps1
# 有 PowerShell 7 时等价：
pwsh -NoProfile -File .\test_smoke.ps1
```

可选参数：

| 参数 | 说明 |
| --- | --- |
| `-CcsHome DIR` | 显式指定测试用状态目录（默认 `%USERPROFILE%\.ccs`，已设置 `CCS_HOME` 时用 `CCS_HOME`） |
| `-KeepDaemon` | 测试结束不执行 `daemon stop` |
| `-KeepState` | 不清理自动回退出来的临时状态目录 |
| `-CcsPy PATH` | 指定 ccs.py 路径（默认脚本同目录） |

说明：

- 测试**不需要 claude**，用 `cmd.exe` 作为被测会话；
- 如果默认状态目录不可写（受限环境/只读配置），脚本会自动回退到 `%TEMP%\ccs-smoke-<PID>`（再不行用脚本目录下 `.ccs-smoke-<PID>`），测试结束后清理，**不会破坏你已有的会话**；
- 在受限沙箱里运行时，`log` 等依赖 ConPTY 实时输出的步骤可能受环境限制而 FAIL，请在实际桌面环境重跑。

---

## FAQ

### Q1. 和 tmux 有什么区别？

- 定位相同（会话持久化 + detach/attach），但 ccs 是**面向 Windows 原生 + Claude CLI** 的：ConPTY 托管、不需要 WSL/msys；
- 会话默认就是 `claude`，并额外记录 Claude session id，重启后能 `--resume` 接回**对话内容**（tmux 只能恢复 shell，Claude 对话要自己 `claude --resume`）；
- 额外提供 tmux 没有的东西：多 agent 消息总线、MCP server、`send/type/key/log` 这类可脚本化的注入接口；
- 不提供 tmux 的分屏/窗口布局，那部分交给 Windows Terminal 的标签/分屏；
- detach 快捷键是 `Ctrl-]`（tmux 是 `Ctrl-b` 前缀）。

### Q2. 为什么不是 WSL + tmux？

- Claude Code CLI 有 Windows 原生版本，直接跑没有 WSL 的路径映射、性能、剪贴板、IDE 集成问题；
- 不是所有目标机器都能装 WSL（公司策略/虚拟化限制），ccs 只要求 Python；
- WSL 里跑 Claude 时，项目文件在 `/mnt/c` 上性能差，且 Windows 原生工具链（PowerShell、MSBuild、`claude mcp` 等）跨边界麻烦。

### Q3. 没装 Claude Code CLI 怎么办？

- 照常可用：`python ccs.py new dev -- cmd.exe`、`python ccs.py new ps -- powershell`，任何命令都能托管；
- 只有 `new NAME`（不带命令，默认 `claude`）或 `restore` Claude 会话时会报“未找到 claude 命令”，按提示安装 Claude Code CLI 后重试即可；
- install.ps1 和冒烟测试都不依赖 claude。

### Q4. 数据存在哪里？能改位置吗？

- 默认 `%USERPROFILE%\.ccs`，见[状态目录与数据](#状态目录与数据)；
- 设置环境变量 `CCS_HOME` 即可整体迁移（新开终端生效，例如 `setx CCS_HOME D:\ccs-data`）；
- 会话记录、消息总线、daemon 日志、Claude 能力缓存都在这个目录下，备份/删除都很直接。

### Q5. 重启后会话为什么没自己回来？

- 需要执行 `restore`；最省心的做法是 `python ccs.py autostart on`（登录自动 `daemon start --restore`）；
- 如果 `daemon status` 显示未运行，先 `python ccs.py daemon start --restore`；
- 如果会话被 `rm` 过，记录已删除，无法恢复；`kill` 过的记录还在，用 `restore NAME` 可手动恢复。

### Q6. 多个 ccs 会话能同时跑吗？

- 能，同一个守护进程托管多个会话，名字唯一；`rename` 可改名；
- 多个 agent 协作时，用 `bus` 通讯（见[多 agent](#多-agent消息总线与-mcp)），或 `send` 直接给对方会话注入输入。

### Q7. 端口/安全问题？

- 守护进程只监听 `127.0.0.1`，端口随机（记录在 `daemon.json`），默认只允许本机访问；
- 总线是本地 SQLite 文件，不联网；
- 不写系统级注册表/环境变量；开机自启只写 HKCU。

### Q8. 已知限制

- 需要 Windows 10 1809+（ConPTY）；
- `log` 输出的是原始字节（含 ANSI 转义），重定向到文件查看更清晰：`python ccs.py log dev --bytes 5000 > out.bin`；
- 会话恢复的是“进程重建 + Claude 对话接回”，进程内部状态（例如 `cmd.exe` 里的临时变量）不会恢复；
- 分屏/布局请用 Windows Terminal。

---

## 目录结构

```text
ccs-tool/
├─ ccs.py            # 核心：ConPTY 守护进程 + CLI（daemon/new/ls/attach/send/...）
├─ ccs_bus.py        # 多 agent 消息总线（SQLite，WAL）
├─ ccs_mcp.py        # MCP stdio server（bus_send/bus_inbox/...）
├─ ccs.cmd           # 源码目录直接可用的启动器（chcp 65001 + python ccs.py）
├─ install.ps1       # 安装：生成 %USERPROFILE%\.ccs\bin\ccs.cmd + 加 PATH + 可选自启
├─ test_smoke.ps1    # 端到端冒烟测试（PASS/FAIL + 汇总 exit code）
└─ README.md         # 本文档
```
