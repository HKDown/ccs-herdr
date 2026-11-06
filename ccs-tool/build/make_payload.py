# -*- coding: utf-8 -*-
import os, shutil, zipfile
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # ccs-tool
dist = os.path.join(root, "build", "dist", "ccs")
payload = os.path.join(root, "build", "payload")
zpath = os.path.join(root, "build", "payload.zip")

shutil.rmtree(payload, ignore_errors=True)
os.makedirs(payload)
for name in os.listdir(dist):
    src = os.path.join(dist, name)
    dst = os.path.join(payload, name)
    if os.path.isdir(src):
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
shutil.copy2(os.path.join(root, "README.md"), os.path.join(payload, "README.md"))
shutil.copy2(os.path.join(root, "build", "ccs-uninstall.exe"), os.path.join(payload, "ccs-uninstall.exe"))

if os.path.exists(zpath):
    os.remove(zpath)
with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for base, dirs, files in os.walk(payload):
        for f in files:
            full = os.path.join(base, f)
            rel = os.path.relpath(full, payload).replace(os.sep, "/")
            z.write(full, rel)
size = os.path.getsize(zpath)
print("payload.zip", size, "bytes =", round(size/1024/1024, 1), "MB")
print("entries", len(zipfile.ZipFile(zpath).namelist()))
