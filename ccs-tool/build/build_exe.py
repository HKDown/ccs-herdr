import os, sys
sys.path.insert(0, "build/pylib")
from PyInstaller.__main__ import run
icon = os.path.abspath(os.path.join("build", "ccs.ico"))
web = os.path.abspath(os.path.join("web"))
run([
    "--noconfirm", "--clean", "--onedir", "--console", "--name", "ccs",
    "--distpath", os.path.abspath("build/dist"),
    "--workpath", os.path.abspath("build/work"),
    "--specpath", os.path.abspath("build"),
    "--icon", icon,
    "--hidden-import", "ccs_bus", "--hidden-import", "ccs_mcp",
    "--hidden-import", "ccs_web", "--hidden-import", "ccs_agents",
    "--add-data", web + os.pathsep + "web",
    os.path.abspath("ccs.py"),
])
