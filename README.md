# ccs-herdr

把 **ccs**（命名会话 / 跨重启恢复 / 多 agent / 消息总线）集成进 **Herdr TUI**（[herdrdev/herdr](https://github.com/herdrdev/herdr)，终端界面版 agent multiplexer）。

- **语言与 Herdr 生态一致**：纯 Rust 实现（Herdr core/UI 与官方插件框架均为 Rust）；
- **跨平台**：Windows / Linux / macOS 同一套代码，CI 三平台构建与测试；
- **零第三方依赖**：只用 Rust 标准库，离线可编译；
- **数据独立**：所有 Herdr 相关数据放在独立目录，不与 ccs、其他项目混在一起；
- **Git 管理**：本目录是独立仓库。

## 它做什么

| 命令 | 作用 |
|---|---|
| ccs-herdr list [--json] | 列出 ccs 会话 |
| ccs-herdr open | 在 Herdr 新建 ccs 工作区，每个运行中的会话一个窗格 |
| ccs-herdr attach NAME [--pane ID] | 把会话接入当前/指定 Herdr 窗格 |
| ccs-herdr restore [--open] [NAME...] | 恢复 ccs 会话 |
| ccs-herdr sync | 把 ccs 的 session id 报告给 Herdr（Herdr 重启恢复同一对话） |
| ccs-herdr bus-inbox / bus-send | 多 agent 消息总线 |
| ccs-herdr install-plugin | 把 plugin/ 链接进 Herdr |
| ccs-herdr pane | 会话面板（行式，跨平台） |
| ccs-herdr doctor | 诊断路径/依赖/守护进程 |

## 目标 Herdr 版本

本工具针对 **Herdr TUI（herdrdev/herdr）** 开发与验证：

- 已验证版本：**herdr 0.9.5**（Windows 官方包 `herdr-windows-x86_64.zip`，含 `herdr.exe` + ConPTY 运行时）；
- 用真实二进制验证过：`herdr plugin link <本仓库>/plugin` 被接受，动作（list/open/restore/bus-inbox）和 overlay 面板 `ccs 会话` 均出现在插件清单里；
- 使用的 CLI：`herdr workspace create`、`herdr tab create`、`herdr pane run/rename`、`herdr pane report-agent-session <PANE_ID>`、`herdr plugin link`；
- Herdr TUI 安装：下载 release 的 Windows zip 解压，或运行 `powershell -c "irm https://herdr.dev/install.ps1 | iex"`。

> 桌面版 herdr-app（Herdr 2，基于 herdr-core）不是本工具的目标；两者 CLI/插件接口不同。

## 一键安装（推荐）

下载 `ccs-herdr-setup-0.2.0.exe` 双击安装即可，**不需要另外安装 ccs**：

- 安装包内置 ccs 引擎（ccs 0.3.1，含 Python 运行时）、ccs-herdr 桥接、Herdr 插件；
- 装到 `%LOCALAPPDATA%\Programs\ccs-herdr`，自动加 PATH、创建「ccs 控制台」和「ccs-herdr 面板」快捷方式；
- 检测到 Herdr TUI 时自动 `herdr plugin link`；没装 Herdr 可在安装界面勾选自动安装（走官方 `https://herdr.dev/install.ps1`，即 TUI 安装器，需要网络）；
- 卸载：设置 → 应用 → ccs-herdr，或安装目录下 `ccs-herdr-uninstall.exe`。

静默安装：`ccs-herdr-setup-0.2.0.exe /S /DIR="D:\Tools\ccs-herdr" /herdr`

## 构建

    cargo build --release
    cargo test

产物：target/release/ccs-herdr（Windows 为 ccs-herdr.exe）。

安装到 PATH：

- Linux/macOS: cp target/release/ccs-herdr ~/.local/bin/
- Windows: 把 target\release\ccs-herdr.exe 放进 PATH 目录，或 cargo install --path .

## 安装到 Herdr

    ccs-herdr install-plugin
    herdr plugin list
    herdr plugin action list --plugin ccs.sessions

## 数据目录（独立、不与其他项目混放）

| 平台 | 默认位置 |
|---|---|
| Windows | %APPDATA%\ccs-herdr |
| macOS | ~/Library/Application Support/ccs-herdr |
| Linux | $XDG_CONFIG_HOME/ccs-herdr 或 ~/.config/ccs-herdr |

内容：herdr-map.json（ccs 会话 ↔ Herdr 窗格映射）。
覆盖：CCS_HERDR_HOME=<目录>。

ccs 自己的状态仍在 ccs 的 CCS_HOME（默认 ~/.ccs），本工具只读。

## 环境变量

| 变量 | 说明 |
|---|---|
| CCS_HOME | ccs 状态目录 |
| CCS_BIN | ccs 可执行文件路径 |
| HERDR_BIN_PATH | herdr 可执行文件路径 |
| HERDR_PANE_ID | 当前 Herdr 窗格（Herdr 注入） |
| CCS_HERDR_HOME | 本工具数据目录 |
| CCS_HERDR_PLUGIN_DIR | 插件目录覆盖 |

## 与 ccs 的关系

- ccs 的守护进程继续用 ConPTY 管住会话，关掉 Herdr 不影响会话；
- Herdr 负责窗口/分屏/状态灯/多机，本工具只做桥接；
- sync 会把 session id 同步给 Herdr，让 Herdr 自己的重启恢复也用同一段对话。

## 平台说明

- 代码只用 std：路径、进程、TCP（127.0.0.1）在三个平台行为一致；
- 面板使用行式交互（不需要 Unix termios / Windows 控制台 API）；
- CI（.github/workflows/ci.yml）在 ubuntu/windows/macos 上 cargo test + build。

## 验证

- `cargo check --all-targets`、`cargo fmt --check`、`cargo clippy --all-targets -- -D warnings` 通过；
- `cargo build --release` 在本机产出 Windows 二进制（约 480 KB），已实测 `version` / `doctor` / `list` / `restore`
  与 ccs 守护进程（TCP JSON-RPC）正常通信；
- `cargo test` 由 CI 在 ubuntu / windows / macos 三个平台运行（见 .github/workflows/ci.yml）；
- 用真实 Herdr TUI 0.9.5 二进制验证插件：`herdr plugin link` 成功，插件动作/面板被 Herdr 识别（见“目标 Herdr 版本”）。

## License

MIT
