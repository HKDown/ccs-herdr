# -*- coding: utf-8 -*-
import os, shutil, zipfile
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
dist = os.path.join(root, "build", "dist", "ccs")
out = os.path.join(root, "build", "ccs-portable-0.3.1.zip")
tmp = os.path.join(root, "build", "portable")
shutil.rmtree(tmp, ignore_errors=True)
os.makedirs(tmp)
shutil.copytree(dist, os.path.join(tmp, "ccs"))
shutil.copy2(os.path.join(root, "README.md"), os.path.join(tmp, "ccs", "README.md"))
if os.path.exists(out):
    os.remove(out)
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for base, dirs, files in os.walk(tmp):
        for f in files:
            full = os.path.join(base, f)
            rel = os.path.relpath(full, tmp).replace(os.sep, "/")
            z.write(full, rel)
shutil.rmtree(tmp, ignore_errors=True)
print("portable zip", round(os.path.getsize(out) / 1024 / 1024, 1), "MB")
