# -*- coding: utf-8 -*-
"""Download wheels from PyPI JSON API and extract them to build/pylib (no pip)."""
import io, json, os, sys, urllib.request, zipfile

DL = os.path.join("build", "dl")
LIB = os.path.join("build", "pylib")
os.makedirs(DL, exist_ok=True)
os.makedirs(LIB, exist_ok=True)

PKGS = [
    "pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "packaging",
    "pefile", "pywin32-ctypes", "setuptools",
]

def get_json(name):
    url = "https://pypi.org/pypi/%s/json" % name
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))

def pick(files):
    # prefer cp314 win_amd64, then py3-none-any, then any win_amd64 wheel
    cands = [f for f in files if f["filename"].endswith(".whl")]
    def score(f):
        fn = f["filename"]
        s = 0
        if "cp314" in fn: s += 100
        if "win_amd64" in fn: s += 50
        if "none-any" in fn: s += 40
        if "py2.py3" in fn or "py3" in fn: s += 30
        return s
    cands.sort(key=score, reverse=True)
    return cands[0] if cands else None

ok, fail = [], []
for name in PKGS:
    try:
        data = get_json(name)
        f = pick(data.get("urls", []))
        if not f:
            fail.append((name, "no wheel")); continue
        dest = os.path.join(DL, f["filename"])
        if not os.path.exists(dest):
            with urllib.request.urlopen(f["url"], timeout=120) as r:
                blob = r.read()
            with open(dest, "wb") as fh:
                fh.write(blob)
        with zipfile.ZipFile(dest) as z:
            z.extractall(LIB)
        ok.append((name, f["filename"], len(blob) if 'blob' in dir() else os.path.getsize(dest)))
    except Exception as e:
        fail.append((name, repr(e)))

print("OK:", len(ok))
for t in ok: print("  ", t)
print("FAIL:", len(fail))
for t in fail: print("  ", t)
