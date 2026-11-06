# -*- coding: utf-8 -*-
import io, json, os, tarfile, urllib.request

BASE = r"D:\he271\Desktop\其他\herdr-src"
os.makedirs(BASE, exist_ok=True)

def get(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": "ccs-research"})
    return urllib.request.urlopen(req, timeout=timeout)

repo = "herdrdev/herdr"
meta = json.loads(get("https://api.github.com/repos/" + repo).read().decode())
print("repo:", meta.get("full_name"), "| lang:", meta.get("language"),
      "| archived:", meta.get("archived"), "| stars:", meta.get("stargazers_count"),
      "| size:", meta.get("size"), "KB")
print("description:", meta.get("description"))
print("default_branch:", meta.get("default_branch"), "| pushed:", meta.get("pushed_at"))

releases = json.loads(get("https://api.github.com/repos/%s/releases?per_page=5" % repo).read().decode())
for r in releases[:5]:
    print("release:", r.get("tag_name"), r.get("published_at"), "prerelease:", r.get("prerelease"))
    for a in (r.get("assets") or [])[:8]:
        print("   asset:", a["name"], a["size"] // 1024, "KB")

tar = get("https://codeload.github.com/%s/tar.gz/%s" % (repo, meta["default_branch"]), timeout=300).read()
print("tarball", len(tar) // 1024, "KB")
with tarfile.open(fileobj=io.BytesIO(tar), mode="r:gz") as tf:
    root = tf.getmembers()[0].name.split("/")[0]
    tf.extractall(BASE)
dest = os.path.join(BASE, "herdr")
if os.path.isdir(dest):
    import shutil; shutil.rmtree(dest)
os.rename(os.path.join(BASE, root), dest)
print("extracted to", dest)
