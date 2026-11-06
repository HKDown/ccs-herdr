# ccs × Herdr 插件

由 [ccs-herdr](../README.md) 提供：把 ccs 的命名会话、跨重启恢复、多 agent、消息总线挂到 Herdr。

## 安装

    ccs-herdr install-plugin
    # 等价于
    herdr plugin link <ccs-herdr 仓库>/plugin

## 动作

| 动作 | 作用 |
|---|---|
| ccs: 列出会话 | 输出所有 ccs 会话（名字/状态/agent/session id/窗格） |
| ccs: 打开会话窗格 | 新建 ccs 工作区，每个运行中的会话一个窗格 |
| ccs: 恢复所有会话 | 恢复 ccs 会话后重新打开窗格 |
| ccs: 查看 agent 消息 | 消息总线收件箱 |
| ccs 会话面板 | overlay 面板，数字键 attach，r 刷新，q 退出 |

命令均使用 PATH 上的 ccs-herdr；没有安装到 PATH 时请改 herdr-plugin.toml 里的绝对路径。
