# 更新日志

## [0.3.0] - 2026-11-07

### 新增

- ccs-herdr：Rust 桥接 + Herdr 插件（list / open / restore / bus-inbox + 会话面板），零第三方依赖，跨平台。
- 离线一体化安装包：内置 ccs 0.3.1 引擎、Herdr TUI 0.9.5、Herdr 插件，安装全程无需联网。
- 多平台桥接二进制：Linux x86_64 / macOS arm64 / Windows x64，由 GitHub Actions 自动构建并附带 SHA256 校验和。
- GitHub Actions：CI（三平台 Rust fmt/clippy/test/build + Windows Python 检查）、tag 触发 Release 工作流。
- 文档：README、NOTICE（Herdr Apache-2.0 说明）、docs/BUILD-ENV.md（构建环境恢复）。

### 修复

- herdr pane report-agent-session 调用缺少 PANE_ID 参数，导致 sync 无法同步会话 id。
- 安装器原先依赖联网下载 Herdr，离线环境无法安装；改为内置 Herdr TUI。

### 变更

- ccs 引擎与 Herdr 集成合并到单仓库（ccs-herdr-all 布局），统一由 git 管理。
- 目标版本明确为 Herdr TUI 0.9.5（herdrdev/herdr），桌面版 herdr-app 不在支持范围。