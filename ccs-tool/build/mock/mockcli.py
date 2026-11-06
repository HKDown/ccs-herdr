# -*- coding: utf-8 -*-
import os, sys, time, uuid

name = sys.argv[1]
args = sys.argv[2:]
log = os.environ.get("MOCK_LOG")
if log:
    with open(log, "a", encoding="utf-8") as f:
        f.write(name + " " + " ".join(args) + "\n")

if "--help" in args:
    print("Usage: %s [options]" % name)
    if name == "mockclaude":
        print("  --session-id <id>\n  --name <name>\n  --resume <id>\n  --continue")
    elif name == "mockcodex":
        print("  resume <id>\n  resume --last")
    sys.exit(0)

print("started %s" % name)
if name == "mockcodex":
    print("session id: " + str(uuid.uuid4()))
sys.stdout.flush()
# 模拟交互式 agent：保持运行直到被杀
while True:
    time.sleep(1)
