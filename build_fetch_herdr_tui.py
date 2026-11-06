# -*- coding: utf-8 -*-
import json, os, urllib.request, zipfile

BASE = r"D:\he271\Desktop\其他\herdr-src"
def get(url, timeout=300):
    req = urllib.request.Request(url, headers={"User-Agent": "ccs-research"})
    return urllib.request.urlopen(req, timeout=timeout)

rel = json.loads(get("https://api.github.com/repos/herdrdev/herdr/releases/latest").read().decode())
print("tag:", rel["tag_name"])
asset = None
for a in rel["assets"]:
    if "windows-x86_64" in a["name"]:
        asset = a
        break
print("asset:", asset["name"], asset["size"] // 1024, "KB")
dest = os.path.join(BASE, "herdr-tui-bin")
os.makedirs(dest, exist_ok=True)
zip_path = os.path.join(BASE, "herdr-windows.zip")
if not os.path.exists(zip_path) or os.path.getsize(zip_path) != asset["size"]:
    with get(asset["browser_download_url"]) as r, open(zip_path, "wb") as f:
        f.write(r.read())
print("downloaded", os.path.getsize(zip_path) // 1024, "KB")
with zipfile.ZipFile(zip_path) as z:
    for n in z.namelist():
        print(" zip:", n)
    z.extractall(dest)
print("extracted to", dest)
