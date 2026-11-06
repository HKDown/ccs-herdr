# 构建环境与依赖恢复

本仓库只保留源码与打包脚本；构建工具链和大体积中间产物不入库，可按下面步骤恢复。

## 1. Rust 工具链（仅 Windows 本机构建需要）

    # 下载 rustup-init.exe（x86_64-pc-windows-msvc）
    # https://static.rust-lang.org/rustup/dist/x86_64-pc-windows-msvc/rustup-init.exe
    # 用独立目录安装，避免污染用户目录：
    RUSTUP_HOME=<dir>\rustup CARGO_HOME=<dir>\cargo rustup-init.exe -y --no-modify-path ^
        --profile minimal --default-host x86_64-pc-windows-gnu --default-toolchain stable
    rustup component add rustfmt clippy

Windows 上使用 GNU 目标编译需要 mingw-w64 的链接器：
下载 winlibs（mingw-w64）解压，把其 bin 目录加入 PATH 后再 cargo build。

## 2. ccs 引擎 dist（打包一体化安装包需要）

    cd ccs-tool
    python build/fetch_wheels.py     # 从 PyPI 下载 PyInstaller 及依赖到 build/pylib（需要网络）
    python build/build_exe.py        # 产出 build/dist/ccs/ccs.exe + _internal/

## 3. Herdr TUI（打包一体化安装包需要）

下载 herdrdev/herdr 的 Windows 发布包并解压到 herdr-src/herdr-tui-bin：

    https://github.com/herdrdev/herdr/releases/latest
    herdr-windows-x86_64.zip  ->  herdr.exe + conpty/ + THIRD-PARTY-NOTICES/

该目录是打包脚本的默认输入（可用 HERDR_TUI_DIR 覆盖）。

## 4. 打包一体化安装包

    cd ccs-herdr
    cargo build --release
    python packaging/build_setup.py
    # 产物: dist/ccs-herdr-setup-0.3.0.exe

## 清理说明

- herdr-src/ 只保留 herdr-tui-bin（打包必需）；上游源码（herdr、herdr-core、herdr-app）已删除，需要时重新下载。
- 已删除：.rustsetup 工具链、ccs-herdr/{build,dist,target}、ccs-tool/build 中间产物；源码与脚本完整。
- 发布产物保留在 artifacts/（不入库）。
