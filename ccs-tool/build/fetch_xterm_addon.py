# -*- coding: utf-8 -*-
import io, json, os, tarfile, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "ccs-web-build", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))
meta = get_json("https://registry.npmjs.org/@xterm%2Faddon-fit")
latest = meta["dist-tags"]["latest"]
tgz = meta["versions"][latest]["dist"]["tarball"]
print("addon-fit", latest)
data = urllib.request.urlopen(urllib.request.Request(tgz, headers={"User-Agent": "ccs-web-build"}), timeout=120).read()
want = {"package/lib/addon-fit.js": "addon-fit.js"}
with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
    for m in tf.getmembers():
        if m.name in want:
            content = tf.extractfile(m).read()
            path = os.path.join(WEB, want[m.name])
            open(path, "wb").write(content)
            print("wrote", path, len(content))
