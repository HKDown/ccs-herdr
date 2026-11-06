# ccs-herdr

把 **ccs**（命名会话 / 跨重启恢复 / 多 agent / 消息总线）集成进 **Herdr**（agent multiplexer）。

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
- `cargo test` 由 CI 在 ubuntu / windows / macos 三个平台运行（见 .github/workflows/ci.yml）。

## License

MIT
