# 数据布局

## 仓库（代码 + 插件，git 管理）

    ccs-herdr/
      Cargo.toml
      src/            # Rust 源码
      plugin/         # Herdr 插件清单与说明
      docs/
      .github/workflows/ci.yml

## 运行时数据（独立目录，不放在仓库里）

    <data_dir>/
      herdr-map.json   # ccs 会话名 -> Herdr pane id

平台默认：

| 平台 | 路径 |
|---|---|
| Windows | %APPDATA%\ccs-herdr |
| macOS | ~/Library/Application Support/ccs-herdr |
| Linux | $XDG_CONFIG_HOME/ccs-herdr 或 ~/.config/ccs-herdr |

覆盖：CCS_HERDR_HOME。

## 与 ccs 的边界

- ccs 状态（state.json、daemon.json、bus.sqlite3）在 CCS_HOME，本工具只读/通过 RPC 访问；
- 本工具自己的映射数据只写 data_dir；
- 插件目录属于仓库（plugin/），通过 herdr plugin link 注册。
