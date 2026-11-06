import json, os, urllib.request, zipfile, shutil
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if "__file__" in dir() else "."
base = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".rustsetup")
# 兼容直接运行
base = r"D:\he271\Desktop\其他\.rustsetup"
os.makedirs(base, exist_ok=True)
api = "https://api.github.com/repos/brechtsanders/winlibs_mingw/releases/latest"
req = urllib.request.Request(api, headers={"User-Agent": "ccs-herdr-build"})
data = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
assets = data.get("assets", [])
pick = None
for a in assets:
    n = a["name"]
    if n.endswith(".zip") and "x86_64" in n and "posix-seh" in n:
        pick = a
        break
print("asset:", pick["name"], pick["size"] // 1024 // 1024, "MB", flush=True)
dest = os.path.join(base, "mingw.zip")
if not os.path.exists(dest) or os.path.getsize(dest) != pick["size"]:
    with urllib.request.urlopen(pick["browser_download_url"], timeout=600) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f, 1024 * 1024)
print("downloaded", os.path.getsize(dest) // 1024 // 1024, "MB", flush=True)
target = os.path.join(base, "mingw")
shutil.rmtree(target, ignore_errors=True)
with zipfile.ZipFile(dest) as z:
    z.extractall(target)
print("extracted", flush=True)
for base2, dirs, files in os.walk(target):
    if "gcc.exe" in files:
        print("gcc:", os.path.join(base2, "gcc.exe"))
        break
