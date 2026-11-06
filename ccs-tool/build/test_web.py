# -*- coding: utf-8 -*-
import base64, json, os, socket, sys, time, urllib.request

BASE = "http://127.0.0.1:8787"

def get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as r:
        return r.status, r.read()

def post(path, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

print("index:", get("/")[0], len(get("/")[1]))
print("app.js:", get("/static/app.js")[0], len(get("/static/app.js")[1]))
print("xterm.js:", get("/static/xterm.js")[0], len(get("/static/xterm.js")[1]))
print("health:", json.loads(get("/api/health")[1]))
s = json.loads(get("/api/sessions")[1])
print("sessions:", [x["name"] for x in s.get("sessions", [])])

# --- WebSocket client ---
key = base64.b64encode(os.urandom(16)).decode()
sock = socket.create_connection(("127.0.0.1", 8787), timeout=10)
req = ("GET /ws?name=websmoke&cols=100&rows=30 HTTP/1.1\r\n"
       "Host: 127.0.0.1:8787\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
       "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % key)
sock.sendall(req.encode())
buf = b""
while b"\r\n\r\n" not in buf:
    buf += sock.recv(4096)
head, rest = buf.split(b"\r\n\r\n", 1)
print("handshake:", head.split(b"\r\n")[0].decode())
assert b"101" in head.split(b"\r\n")[0]

def send_text(obj):
    payload = json.dumps(obj).encode()
    mask = os.urandom(4)
    masked = bytes(payload[i] ^ mask[i % 4] for i in range(len(payload)))
    header = bytearray([0x81])
    n = len(payload)
    if n < 126:
        header.append(0x80 | n)
    elif n < 65536:
        header.append(0x80 | 126); header += n.to_bytes(2, "big")
    else:
        header.append(0x80 | 127); header += n.to_bytes(8, "big")
    sock.sendall(bytes(header) + mask + masked)

def recv_frame(sock, buf):
    while len(buf) < 2:
        buf += sock.recv(65536)
    opcode = buf[0] & 0x0f
    length = buf[1] & 0x7f
    off = 2
    if length == 126:
        while len(buf) < off + 2: buf += sock.recv(65536)
        length = int.from_bytes(buf[off:off+2], "big"); off += 2
    elif length == 127:
        while len(buf) < off + 8: buf += sock.recv(65536)
        length = int.from_bytes(buf[off:off+8], "big"); off += 8
    while len(buf) < off + length:
        buf += sock.recv(65536)
    payload = buf[off:off+length]
    return opcode, payload, buf[off+length:]

out = b""
deadline = time.time() + 8
text = ""
while time.time() < deadline and "WEB_OK" not in text:
    sock.settimeout(3)
    try:
        op, payload, rest = recv_frame(sock, rest)
    except socket.timeout:
        break
    if op == 1:
        msg = json.loads(payload.decode())
        if msg.get("t") in ("snap", "out"):
            out += base64.b64decode(msg["b64"])
            text = out.decode("utf-8", "replace")
    if "cmd.exe>" in text and "echo" not in text:
        send_text({"t": "in", "b64": base64.b64encode(b"echo WEB_OK\r").decode()})

if "WEB_OK" not in text:
    send_text({"t": "in", "b64": base64.b64encode(b"echo WEB_OK\r").decode()})
    deadline = time.time() + 8
    while time.time() < deadline and "WEB_OK" not in text:
        try:
            op, payload, rest = recv_frame(sock, rest)
        except socket.timeout:
            break
        if op == 1:
            m = json.loads(payload.decode())
            if m.get("t") in ("snap", "out"):
                out += base64.b64decode(m["b64"])
                text = out.decode("utf-8", "replace")
print("WS received bytes:", len(out))
print("WS contains WEB_OK:", "WEB_OK" in text)
send_text({"t": "resize", "cols": 120, "rows": 40})
sock.close()

# --- REST: new/bus ---
print("new via api:", post("/api/new", {"name": "web2", "cmd": "cmd.exe"}))
print("bus send:", post("/api/bus/send", {"from": "web", "to": "websmoke", "message": "hello from web ui"}))
print("bus inbox:", json.loads(get("/api/bus?agent=websmoke&limit=5")[1]))
