# -*- coding: utf-8 -*-
import io, json, os, tarfile, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # ccs-tool
WEB = os.path.join(ROOT, "web")
os.makedirs(WEB, exist_ok=True)

def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "ccs-web-build", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))

meta = get_json("https://registry.npmjs.org/xterm")
latest = meta["dist-tags"]["latest"]
tgz = meta["versions"][latest]["dist"]["tarball"]
print("xterm latest", latest, tgz)

data = urllib.request.urlopen(urllib.request.Request(tgz, headers={"User-Agent": "ccs-web-build"}), timeout=120).read()
print("tarball bytes", len(data))

want = {
    "package/lib/xterm.js": "xterm.js",
    "package/css/xterm.css": "xterm.css",
}
found = {}
with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
    for member in tf.getmembers():
        name = member.name
        if name in want:
            found[name] = tf.extractfile(member).read()

for name, content in found.items():
    target = os.path.join(WEB, want[name])
    with open(target, "wb") as f:
        f.write(content)
    print("wrote", target, len(content))

missing = [k for k in want if k not in found]
print("missing", missing)
