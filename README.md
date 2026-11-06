# ccs-herdr-all

给 coding agents 的**会话管理 + 终端工作区**一体化项目：

- **ccs**（Python）：命名会话、关窗不丢、跨重启恢复（Claude Code / Codex / Pi / Gemini / OpenCode / Qwen …）、SQLite 消息总线、MCP server、浏览器可视化控制台；
- **Herdr 集成**（Rust）：ccs-herdr 桥接 + Herdr 插件（会话列表 / 打开窗格 / 恢复 / 消息）+ 离线一体化安装器；
- **Herdr TUI** 作为终端界面：窗口、分屏、agent 状态、多机 SSH。

> 本项目是独立集成，与 Herdr 项目无隶属关系。安装包内置未修改的 Herdr TUI 二进制（Apache-2.0），仓库本身不包含 Herdr 源码。

## 功能

- 命名会话：ccs new NAME -- claude / codex / pi ...
- 关窗不丢 + 重启恢复：ccs restore（按 agent 能力自动 --resume / --continue / 仅重建）
- Herdr 集成：ccs-herdr open 把会话映射成 Herdr 窗格，ccs-herdr sync 同步 session id
- 多 agent 消息总线：ccs bus send/inbox，MCP 工具 bus_send/bus_inbox/session_send
- 可视化控制台：ccs web（本地 HTTP + xterm.js）
- 离线一体化安装包：内置 ccs 引擎 + 桥接 + Herdr TUI + 插件

## 安装

发布产物见 artifacts/（不纳入 git）：

- ccs-herdr-setup-0.3.0.exe：Windows 离线一体化安装包（推荐）
- ccs-setup-0.3.1.exe / ccs-portable-0.3.1.zip：仅 ccs 本体
- ccs-herdr-0.1.0-win64.exe：单文件 Rust 桥接

安装后新开终端：

```
ccs daemon start
ccs new claude1 -- claude
ccs-herdr install-plugin
ccs-herdr open
```

## 从源码构建

```
# Rust 桥接（零第三方依赖）
cd ccs-herdr
cargo build --release

# 一体化离线安装包（需要 ccs 引擎 dist 与 Herdr TUI 目录）
python packaging/build_setup.py

# ccs 本体（PyInstaller）
cd ccs-tool
python build/build_exe.py
```

构建环境恢复（Rust 工具链、PyInstaller 依赖、Herdr TUI 下载）见 [docs/BUILD-ENV.md](docs/BUILD-ENV.md)。

## 目录

```
ccs-tool/     ccs 本体（Python）：ccs.py / ccs_agents.py / ccs_bus.py / ccs_mcp.py / ccs_web.py / web
ccs-herdr/    Herdr 集成（Rust + 插件 + 安装器 + 打包脚本）
docs/         构建环境说明
artifacts/    发布产物（不入库）
herdr-src/    打包所需的 Herdr TUI 二进制（不入库，可从上游下载）
```

## 平台

- ccs 引擎：Windows（ConPTY，Python 3.10+）；Linux/macOS 尚未实现（ccs.py 直接依赖 Windows API）
- ccs-herdr：Windows / Linux / macOS（Rust，零依赖）
- 一体化安装包：目前为 Windows x64

## 许可证

MIT（见 LICENSE）。安装包内置的 Herdr TUI 为 Apache-2.0，详见 NOTICE 与随附的第三方许可文件。
