# ccs-herdr-all

ccs（多 agent 会话管理）+ Herdr TUI（终端 agent 多路复用）一体化项目的**统一目录**，由一个 git 仓库管理。

## 目录结构

```
ccs-herdr-all/
  ccs-tool/        ccs 本体（Python 引擎）
    ccs.py            ConPTY 守护进程 / attach / restore / web 入口
    ccs_agents.py     多 agent 适配（claude/codex/pi/gemini/...）
    ccs_bus.py        消息总线（SQLite）
    ccs_mcp.py        MCP server
    ccs_web.py        可视化控制台后端
    web/              可视化前端（xterm.js）
    build/            打包脚本（PyInstaller 等）
  ccs-herdr/       Herdr 集成（Rust 桥接 + 插件 + 安装器）
    src/              ccs-herdr CLI（零依赖 Rust）
    plugin/           Herdr 插件清单
    installer/        一体化安装器（C#）
    packaging/        打包脚本（生成 setup.exe）
  herdr-src/       上游 Herdr 源码（仅参考，不入库）
    herdr/            Herdr TUI 0.9.5
    herdr-core/       herdr-core
    herdr-app/        Herdr 2 桌面版
    herdr-tui-bin/    Windows 官方发布包解压（安装包内置的就是它）
  artifacts/       发布产物（不入库）
    ccs-herdr-setup-0.3.0.exe        离线一体化安装包（推荐）
    ccs-herdr-0.1.0-win64.exe        单文件 Rust 桥接
    ccs-setup-0.3.1.exe              ccs 本体安装包
    ccs-portable-0.3.1.zip           ccs 便携版
```

## 构建

```
# Rust 桥接
cd ccs-herdr
cargo build --release

# 一体化离线安装包（需要 ccs 引擎 dist 与 herdr TUI 目录）
cd ccs-herdr
python packaging/build_setup.py

# ccs 本体（PyInstaller）
cd ccs-tool
python build/build_exe.py
```

## 运行

```
# ccs 引擎
ccs daemon start
ccs new claude1 -- claude
ccs attach claude1
ccs restore

# Herdr 集成
ccs-herdr list / open / restore / sync
ccs-herdr install-plugin
```

## Git

- 仓库根：本目录（`git log` 可见历史）；
- 忽略：构建产物（target/build/dist/pylib）、发布产物（artifacts/）、上游源码（herdr-src/）；
- 代码：ccs-tool 与 ccs-herdr 全部受版本管理。

## 说明

- 一体化安装包**离线**内置 ccs 引擎、ccs-herdr、Herdr TUI 0.9.5 与插件，装一次即可用；
- 数据目录：ccs 状态在 `%USERPROFILE%\.ccs`，ccs-herdr 数据在 `%APPDATA%\ccs-herdr`；
- 上游 Herdr 源码仅作参考，不纳入版本管理（可重新下载）。
