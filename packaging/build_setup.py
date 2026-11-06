# -*- coding: utf-8 -*-
"""构建 ccs-herdr 一体化安装包（内含 ccs 引擎 + Rust 桥接 + Herdr 插件）。

用法（在 ccs-herdr 仓库根目录）：
    python packaging/build_setup.py

依赖：
    - 已构建 engine：默认 ../ccs-tool/build/dist/ccs（可用 CCS_ENGINE_DIR 覆盖）
    - 已构建 Rust 二进制：target/release/ccs-herdr.exe（cargo build --release）
    - Windows csc（.NET Framework 自带）
"""
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = "0.2.0"
ENGINE = os.environ.get("CCS_ENGINE_DIR") or os.path.join(ROOT, "..", "ccs-tool", "build", "dist", "ccs")
BRIDGE = os.path.join(ROOT, "target", "release", "ccs-herdr.exe")
PLUGIN = os.path.join(ROOT, "plugin")
ICON = os.path.join(ROOT, "assets", "icon.ico")
CSC = r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe"

BUILD = os.path.join(ROOT, "build", "packaging")
PAYLOAD = os.path.join(BUILD, "payload")
DIST = os.path.join(ROOT, "dist")


def run(cmd):
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main():
    if not os.path.isdir(ENGINE):
        sys.exit("找不到 ccs 引擎目录: %s（设置 CCS_ENGINE_DIR 或先构建 ccs）" % ENGINE)
    if not os.path.isfile(BRIDGE):
        sys.exit("找不到 %s，先 cargo build --release" % BRIDGE)
    if not os.path.isfile(ICON):
        sys.exit("找不到图标: %s" % ICON)

    shutil.rmtree(BUILD, ignore_errors=True)
    os.makedirs(PAYLOAD)
    os.makedirs(DIST, exist_ok=True)

    print("复制 ccs 引擎…")
    shutil.copytree(ENGINE, os.path.join(PAYLOAD, "engine"))
    print("复制 ccs-herdr…")
    shutil.copy2(BRIDGE, os.path.join(PAYLOAD, "ccs-herdr.exe"))
    print("复制插件…")
    shutil.copytree(PLUGIN, os.path.join(PAYLOAD, "plugin"))
    shutil.copy2(os.path.join(ROOT, "README.md"), os.path.join(PAYLOAD, "README.md"))
    shutil.copy2(os.path.join(ROOT, "LICENSE"), os.path.join(PAYLOAD, "LICENSE"))

    # 1) 先编译卸载器（不带 payload），放进 payload
    src = os.path.join(ROOT, "installer", "Installer.cs")
    with open(src, encoding="utf-8") as f:
        text = f.read()
    src_bom = os.path.join(BUILD, "Installer.cs")
    with open(src_bom, "w", encoding="utf-8-sig", newline="") as f:
        f.write(text)

    csc_common = [
        CSC, "/nologo", "/target:winexe", "/optimize+",
        "/win32icon:" + ICON,
        "/r:System.Windows.Forms.dll", "/r:System.Drawing.dll",
        "/r:System.IO.Compression.dll", "/r:System.IO.Compression.FileSystem.dll",
        "/r:Microsoft.CSharp.dll",
    ]
    uninstaller = os.path.join(BUILD, "ccs-herdr-uninstall.exe")
    run(csc_common + ["/out:" + uninstaller, src_bom])
    shutil.copy2(uninstaller, os.path.join(PAYLOAD, "ccs-herdr-uninstall.exe"))

    # 2) 打 payload 包
    payload_zip = os.path.join(BUILD, "payload.zip")
    print("打包 payload…")
    with zipfile.ZipFile(payload_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for base, dirs, files in os.walk(PAYLOAD):
            for f in files:
                full = os.path.join(base, f)
                rel = os.path.relpath(full, PAYLOAD).replace(os.sep, "/")
                z.write(full, rel)

    # 3) 编译安装器（嵌入 payload）
    setup = os.path.join(DIST, "ccs-herdr-setup-%s.exe" % VERSION)
    run(csc_common + ["/out:" + setup, "/resource:" + payload_zip + ",payload.zip", src_bom])

    size_mb = os.path.getsize(setup) / 1024 / 1024
    print("完成: %s (%.1f MB)" % (setup, size_mb))
    print("payload: %.1f MB, %d 个文件" % (os.path.getsize(payload_zip) / 1024 / 1024,
                                         sum(len(files) for _, _, files in os.walk(PAYLOAD))))


if __name__ == "__main__":
    main()
