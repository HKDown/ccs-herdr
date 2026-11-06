(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  let sessions = [];
  let current = null;
  let ws = null;
  let term = null;
  let fitAddon = null;
  let busTimer = null;

  const b64enc = (u8) => {
    let s = "";
    const chunk = 0x8000;
    for (let i = 0; i < u8.length; i += chunk) {
      s += String.fromCharCode.apply(null, u8.subarray(i, i + chunk));
    }
    return btoa(s);
  };
  const b64dec = (b64) => {
    const s = atob(b64);
    const u8 = new Uint8Array(s.length);
    for (let i = 0; i < s.length; i++) u8[i] = s.charCodeAt(i);
    return u8;
  };

  async function api(path, body) {
    const opt = body === undefined ? {} : {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    };
    const r = await fetch(path, opt);
    let j = {};
    try { j = await r.json(); } catch (e) { throw new Error("响应不是 JSON（HTTP " + r.status + "）"); }
    if (!r.ok || j.ok === false) throw new Error(j.error || ("HTTP " + r.status));
    return j;
  }

  function setDaemonState(text, cls) {
    const el = $("daemon-state");
    el.textContent = text;
    el.style.color = cls === "ok" ? "var(--accent)" : cls === "bad" ? "var(--danger)" : "";
  }

  function fmtAge(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    if (sec < 60) return sec + "s";
    if (sec < 3600) return Math.floor(sec / 60) + "m";
    if (sec < 86400) return Math.floor(sec / 3600) + "h";
    return Math.floor(sec / 86400) + "d";
  }

  function renderSessions() {
    const box = $("sessions");
    box.innerHTML = "";
    if (!sessions.length) {
      box.innerHTML = '<div class="bus-empty" style="padding:8px">还没有会话，点击“＋ 新建”。</div>';
      return;
    }
    for (const s of sessions) {
      const card = document.createElement("div");
      card.className = "session" + (s.name === current ? " active" : "");
      const cmd = (s.argv || []).join(" ");
      card.innerHTML =
        '<div class="row1"><span class="dot ' + (s.status === "running" ? "running" : "exited") + '"></span>' +
        '<span class="name"></span><span class="meta">' + fmtAge(s.age) + '</span></div>' +
        '<div class="meta"></div>';
      card.querySelector(".name").textContent = s.name;
      card.querySelectorAll(".meta")[1].textContent = cmd + " · " + (s.cwd || "");
      card.title = s.name + "\n" + cmd + "\n" + (s.cwd || "");
      card.onclick = () => openSession(s.name);
      box.appendChild(card);
    }
  }

  async function refreshSessions() {
    try {
      const j = await api("/api/sessions");
      sessions = j.sessions || [];
      renderSessions();
      setDaemonState("守护进程在线 · " + sessions.length + " 个会话", "ok");
    } catch (e) {
      setDaemonState("无法连接守护进程：" + e.message, "bad");
    }
  }

  function markActive() {
    document.querySelectorAll(".session").forEach((el, i) => {
      el.classList.toggle("active", sessions[i] && sessions[i].name === current);
    });
  }

  function send(obj) {
    if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj));
  }

  function sendInput(text) {
    const u8 = new TextEncoder().encode(text);
    send({ t: "in", b64: b64enc(u8) });
  }

  function openSession(name) {
    if (current === name && ws && ws.readyState === 1) return;
    current = name;
    $("cur-name").textContent = name;
    showPane("term");
    if (ws) { try { ws.close(); } catch (e) {} ws = null; }
    if (term) { try { term.dispose(); } catch (e) {} term = null; }
    $("empty-tip").classList.add("hidden");
    term = new Terminal({
      fontFamily: "Consolas, 'Cascadia Mono', 'Microsoft YaHei Mono', monospace",
      fontSize: 14,
      cursorBlink: true,
      scrollback: 8000,
      theme: {
        background: "#0f1117", foreground: "#d8dee9", cursor: "#40e078",
        selectionBackground: "#2f3a52",
      },
    });
    fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    term.open($("term"));
    fitAddon.fit();
    term.onData((d) => sendInput(d));
    term.onResize((size) => send({ t: "resize", cols: size.cols, rows: size.rows }));

    const proto = location.protocol === "https:" ? "wss" : "ws";
    const url = proto + "://" + location.host + "/ws?name=" + encodeURIComponent(name) +
      "&cols=" + term.cols + "&rows=" + term.rows;
    ws = new WebSocket(url);
    ws.onopen = () => { fitAddon.fit(); send({ t: "resize", cols: term.cols, rows: term.rows }); };
    ws.onmessage = (ev) => {
      let m;
      try { m = JSON.parse(ev.data); } catch (e) { return; }
      if (m.t === "snap" || m.t === "out") { term.write(b64dec(m.b64)); }
      else if (m.t === "exit") { term.write("\r\n\x1b[33m[会话已退出 code=" + m.code + "]\x1b[0m\r\n"); }
      else if (m.t === "err") { term.write("\r\n\x1b[31m[" + m.msg + "]\x1b[0m\r\n"); }
    };
    ws.onclose = () => { if (current === name) setDaemonState("终端连接已断开", "bad"); };
  }

  async function createSession() {
    const name = $("f-name").value.trim();
    const cmd = $("f-cmd").value.trim();
    const cwd = $("f-cwd").value.trim();
    $("f-error").textContent = "";
    if (!name) { $("f-error").textContent = "请填写会话名字"; return; }
    try {
      const payload = { name: name, cmd: cmd };
      if (cwd) payload.cwd = cwd;
      await api("/api/new", payload);
      $("modal").classList.add("hidden");
      $("f-name").value = "";
      await refreshSessions();
      openSession(name);
    } catch (e) {
      $("f-error").textContent = e.message;
    }
  }

  async function renameCurrent() {
    if (!current) return;
    const next = window.prompt("新的会话名字：", current);
    if (!next || next === current) return;
    try {
      await api("/api/rename", { old: current, new: next.trim() });
      current = next.trim();
      $("cur-name").textContent = current;
      await refreshSessions();
    } catch (e) { alert("重命名失败：" + e.message); }
  }

  async function killCurrent() {
    if (!current) return;
    if (!window.confirm("结束会话 “" + current + "” 的进程？（记录保留，可 restore）")) return;
    try { await api("/api/kill", { name: current }); await refreshSessions(); }
    catch (e) { alert("操作失败：" + e.message); }
  }

  function showPane(which) {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.dataset.pane === which));
    $("term-pane").classList.toggle("hidden", which !== "term");
    $("bus-pane").classList.toggle("hidden", which !== "bus");
    if (which === "bus") { refreshBus(); startBusTimer(); } else { stopBusTimer(); }
    if (which === "term" && fitAddon) setTimeout(() => fitAddon.fit(), 30);
  }

  function startBusTimer() { stopBusTimer(); busTimer = setInterval(refreshBus, 3000); }
  function stopBusTimer() { if (busTimer) { clearInterval(busTimer); busTimer = null; } }

  async function refreshBus() {
    const from = $("bus-from").value.trim() || "web";
    try {
      const j = await api("/api/bus?agent=" + encodeURIComponent(from) + "&limit=80");
      const box = $("bus-messages");
      const items = j.messages || [];
      if (!items.length) { box.innerHTML = '<div class="bus-empty">暂无消息</div>'; return; }
      box.innerHTML = "";
      for (const m of items) {
        const div = document.createElement("div");
        div.className = "bus-msg";
        const who = document.createElement("span");
        who.className = "who";
        who.textContent = m.sender + (m.group_name ? " → #" + m.group_name : m.target ? " → " + m.target : "");
        const when = document.createElement("span");
        when.className = "when";
        when.textContent = m.ts || "";
        div.appendChild(who); div.appendChild(when);
        div.appendChild(document.createElement("br"));
        div.appendChild(document.createTextNode(m.body || ""));
        box.appendChild(div);
      }
      box.scrollTop = box.scrollHeight;
    } catch (e) { /* 静默 */ }
  }

  async function sendBus() {
    const text = $("bus-text").value.trim();
    if (!text) return;
    const payload = { from: $("bus-from").value.trim() || "web", message: text };
    const to = $("bus-to").value.trim();
    const group = $("bus-group").value.trim();
    if (to) payload.to = to;
    if (group) payload.group = group;
    try {
      await api("/api/bus/send", payload);
      $("bus-text").value = "";
      await refreshBus();
    } catch (e) { alert("发送失败：" + e.message); }
  }

  function bind() {
    $("btn-new").onclick = () => { $("f-error").textContent = ""; $("modal").classList.remove("hidden"); $("f-name").focus(); };
    $("f-cancel").onclick = () => $("modal").classList.add("hidden");
    $("f-ok").onclick = createSession;
    $("f-name").onkeydown = (e) => { if (e.key === "Enter") createSession(); };
    $("btn-rename").onclick = renameCurrent;
    $("btn-kill").onclick = killCurrent;
    $("bus-send").onclick = sendBus;
    $("bus-text").onkeydown = (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendBus(); }
    };
    document.querySelectorAll(".tab").forEach((t) => {
      t.onclick = () => { showPane(t.dataset.pane); if (t.dataset.pane === "term" && !current) $("empty-tip").classList.remove("hidden"); };
    });
    window.addEventListener("resize", () => { if (fitAddon) fitAddon.fit(); });
  }

  bind();
  refreshSessions();
  setInterval(refreshSessions, 2000);
})();
