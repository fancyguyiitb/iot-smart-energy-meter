// Voltix web client: a dependency-free single-page app over the Voltix REST API.
// Served by the server at /app; set window.VOLTIX_API to point at another origin.
"use strict";

const API = window.VOLTIX_API || "";
const TZ = "Asia/Kolkata";
const PHASES = ["R", "Y", "B"];
const state = {
  token: safeGet("voltix_token"),
  user: null,
  device: null,
  timers: [],
  charts: [],
  sockets: [],
  viewGen: 0, // bumped on every navigation
  globalTimer: null,
};

// ---------------------------------------------------------------- utilities
function safeGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function safeSet(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch { /* private mode */ } }
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const color = (p) => css(`--${p}`);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (v, d = 1) => (v == null || Number.isNaN(+v) ? "–" : (+v).toFixed(d));
const hhmm = (iso) => new Date(iso).toLocaleTimeString("en-GB", { timeZone: TZ, hour: "2-digit", minute: "2-digit" });
const dayLabel = (iso) => new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
const todayStr = () => new Date().toLocaleDateString("en-CA", { timeZone: TZ });
const monthStr = () => todayStr().slice(0, 7);
const $ = (sel, root = document) => root.querySelector(sel);

function toast(msg, ms = 3500) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.hidden = true; }, ms);
}

// A response that arrives after the user has navigated away must not touch the new page
// (it would write into elements that no longer exist). Such responses never resolve.
const STALE = () => new Promise(() => {});

async function api(path, { method = "GET", body, auth = true } = {}) {
  const gen = state.viewGen;
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (auth && state.token) headers.Authorization = `Bearer ${state.token}`;
  let res;
  try {
    res = await fetch(API + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch (e) {
    if (gen !== state.viewGen) return STALE();
    throw new Error("Can't reach the server. Check your connection.");
  }
  const data = await res.json().catch(() => ({}));
  if (gen !== state.viewGen) return STALE();
  if (res.status === 401 && auth) {
    logout("Your session has expired. Please log in again.");
    throw Object.assign(new Error("Session expired"), { status: 401 });
  }
  if (!res.ok) {
    const d = data && data.detail;
    const msg = typeof d === "string" ? d : Array.isArray(d) ? d.map((e) => `${(e.loc || []).slice(-1)[0]}: ${e.msg}`).join("; ") : res.statusText;
    throw Object.assign(new Error(msg), { status: res.status });
  }
  return data;
}

const dev = () => (state.device ? `device_id=${encodeURIComponent(state.device.device_id)}` : "");

function every(ms, fn) {
  fn();
  state.timers.push(setInterval(fn, ms));
}

function destroyCharts() {
  state.charts.forEach((c) => c.destroy());
  state.charts = [];
}

function cleanup() {
  state.timers.forEach(clearInterval);
  state.timers = [];
  state.sockets.forEach((ws) => { ws.onclose = null; ws.onmessage = null; ws.close(); });
  state.sockets = [];
  destroyCharts();
}

/** Live readings pushed over a WebSocket; falls back to polling while it's down. */
function liveFeed(onSample, pollMs = 5000) {
  let pollTimer = null;
  let retry = 1000;
  const poll = async () => {
    try { onSample(await api(`/api/latest-values?${dev()}`), "polling"); } catch (e) { onSample(null, e.message); }
  };
  const startPolling = () => { if (!pollTimer) { poll(); pollTimer = setInterval(poll, pollMs); state.timers.push(pollTimer); } };
  const stopPolling = () => { clearInterval(pollTimer); pollTimer = null; };
  const connect = () => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const base = API ? API.replace(/^http/, "ws") : `${proto}://${location.host}`;
    const ws = new WebSocket(`${base}/ws/live`);
    state.sockets.push(ws);
    // The token goes in the first message, never in the URL (URLs end up in access logs).
    ws.onopen = () => ws.send(JSON.stringify({ token: state.token, device_id: state.device && state.device.device_id }));
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "hello") { stopPolling(); retry = 1000; }
      if (msg.type === "sample") {
        const now = Date.now();
        for (const r of Object.values(msg.phases)) r.age_s = Math.max((now - new Date(r.timestamp)) / 1000, 0);
        onSample(msg.phases, "live");
      }
    };
    ws.onclose = (ev) => {
      state.sockets = state.sockets.filter((x) => x !== ws);
      startPolling();
      if (ev.code === 4401) return; // auth problem: polling will surface it (and log out on 401)
      setTimeout(connect, retry);
      retry = Math.min(retry * 2, 30000);
    };
  };
  startPolling();
  connect();
}

// ---------------------------------------------------------------- charts
function chart(canvas, type, labels, datasets, { yTitle = "", stacked = false } = {}) {
  if (!window.Chart) {
    canvas.parentElement.innerHTML = '<p class="muted">Charts need Chart.js from cdn.jsdelivr.net (check the internet connection).</p>';
    return null;
  }
  const muted = css("--muted");
  const line = css("--line");
  const c = new Chart(canvas, {
    type,
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { labels: { color: css("--ink"), boxWidth: 12 } } },
      scales: {
        x: { stacked, ticks: { color: muted, maxTicksLimit: 12, autoSkip: true }, grid: { color: line } },
        y: { stacked, title: { display: !!yTitle, text: yTitle, color: muted }, ticks: { color: muted }, grid: { color: line } },
      },
      elements: { point: { radius: 0 }, line: { borderWidth: 1.6 } },
    },
  });
  state.charts.push(c);
  return c;
}

/** Turn {R: [{timestamp, f}], Y: [...]} into shared labels + one dataset per phase. */
function phaseDatasets(series, field, transform = (v) => v) {
  const stamps = [...new Set(PHASES.flatMap((p) => (series[p] || []).map((r) => r.timestamp)))].sort();
  const datasets = PHASES.filter((p) => series[p] && series[p].length).map((p) => {
    const byTs = new Map(series[p].map((r) => [r.timestamp, r[field]]));
    return {
      label: `Phase ${p}`,
      data: stamps.map((t) => (byTs.has(t) && byTs.get(t) != null ? transform(byTs.get(t)) : null)),
      borderColor: color(p),
      backgroundColor: color(p),
    };
  });
  return { labels: stamps.map(hhmm), datasets };
}

// ---------------------------------------------------------------- auth
async function loadMe() {
  const me = await api("/auth/me");
  state.user = me;
  const saved = safeGet("voltix_device");
  state.device = me.devices.find((d) => d.device_id === saved) || me.devices[0] || null;
  $("#username").textContent = me.username;
  startGlobalStatus();
}

function logout(message) {
  state.token = null;
  state.user = null;
  state.device = null;
  safeSet("voltix_token", null);
  clearInterval(state.globalTimer);
  $("#topbar").hidden = true;
  location.hash = "#/login";
  if (message) toast(message);
}

function startGlobalStatus() {
  clearInterval(state.globalTimer);
  const update = async () => {
    if (!state.device) return;
    try {
      const devices = await api("/api/devices");
      const d = devices.find((x) => x.device_id === state.device.device_id);
      const chip = $("#device-chip");
      chip.textContent = `${d.name || d.device_id} · ${d.online ? "online" : "offline"}`;
      chip.className = `chip ${d.online ? "ok" : "bad"}`;
    } catch { /* shown elsewhere */ }
  };
  update();
  state.globalTimer = setInterval(update, 10000);
}

function authPage(view, title, inner) {
  view.innerHTML = `<div class="auth card"><h1>⚡ ${title}</h1>${inner}</div>`;
}

function login(view) {
  authPage(view, "Log in to Voltix", `
    <form id="f">
      <label>Username <input name="username" autocomplete="username" required></label>
      <label>Password <input name="password" type="password" autocomplete="current-password" required></label>
      <p class="error" id="err"></p>
      <button class="primary">Log in</button>
      <p class="muted"><a href="#/forgot">Forgot your password?</a></p>
      <p class="muted">New meter? <a href="#/signup">Create an account with its sign-up code</a></p>
    </form>`);
  $("#f").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      const r = await api("/auth/login", { method: "POST", auth: false, body: { username: fd.get("username"), password: fd.get("password") } });
      state.token = r.access_token;
      safeSet("voltix_token", r.access_token);
      location.hash = "#/dashboard";
    } catch (err) {
      $("#err").textContent = err.message;
    }
  });
}

function signup(view, params) {
  authPage(view, "Register your meter", `
    <form id="f">
      <label>Sign-up code
        <textarea name="claim_code" required placeholder="VOLTIX1:meter-001:...">${esc(params.get("code") || "")}</textarea>
      </label>
      <p class="muted">Open <b>Get QR</b> on the meter's screen and scan it, or run
        <code>python src/RPi/claim.py</code> on the device. Codes expire after 10 minutes and work once.</p>
      <label>Username <input name="username" autocomplete="username" minlength="3" required></label>
      <label>Email (optional, needed to reset a forgotten password) <input name="email" type="email" autocomplete="email"></label>
      <label>Password (8+ characters) <input name="password" type="password" autocomplete="new-password" minlength="8" required></label>
      <p class="error" id="err"></p>
      <button class="primary">Create account</button>
      <p class="muted">Already registered? <a href="#/login">Log in</a></p>
    </form>`);
  $("#f").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      const r = await api("/auth/sign-up", {
        method: "POST", auth: false,
        body: { username: fd.get("username"), password: fd.get("password"), claim_code: fd.get("claim_code").trim(),
          email: fd.get("email") || null },
      });
      state.token = r.access_token;
      safeSet("voltix_token", r.access_token);
      toast("Meter registered");
      location.hash = "#/dashboard";
    } catch (err) {
      $("#err").textContent = err.message;
    }
  });
}

function noDevice(view) {
  view.innerHTML = `<div class="auth card"><h1>No meter on this account</h1>
    <form id="f"><label>Sign-up code <textarea name="claim_code" required></textarea></label>
    <p class="error" id="err"></p><button class="primary">Add meter</button></form></div>`;
  $("#f").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/auth/claim-device", { method: "POST", body: { claim_code: new FormData(e.target).get("claim_code").trim() } });
      await loadMe();
      render();
    } catch (err) { $("#err").textContent = err.message; }
  });
}

// ---------------------------------------------------------------- dashboard
function dashboard(view) {
  view.innerHTML = `
    <h1>Live readings</h1>
    <div class="tiles">
      <div class="card tile"><div class="k">Total active power</div><div class="v" id="t-p">–</div></div>
      <div class="card tile"><div class="k">Energy today (chip)</div><div class="v" id="t-e">–</div></div>
      <div class="card tile"><div class="k">Software vs chip, today</div><div class="v" id="t-diff">–</div></div>
      <div class="card tile"><div class="k">Neutral current</div><div class="v" id="t-n">–</div></div>
      <div class="card tile"><div class="k">Last reading <span id="t-mode" class="chip">…</span></div><div class="v" id="t-age">–</div></div>
    </div>
    <div class="grid cols-4" id="phases" style="margin-bottom:14px"></div>
    <div class="card"><h2>Active power, this session</h2><div class="chart-box"><canvas id="live"></canvas></div></div>`;

  for (const p of PHASES) {
    const el = document.createElement("div");
    el.className = "card phase-card";
    el.style.setProperty("--pc", color(p));
    el.innerHTML = `<h2>Phase ${p}<span class="muted" data-f="pf"></span></h2>
      <div class="big" data-f="power_watt">–</div>
      <div class="kv">
        <div><span class="k">Voltage</span><span class="v" data-f="voltage_rms"></span></div>
        <div><span class="k">Current</span><span class="v" data-f="current_rms"></span></div>
        <div><span class="k">Frequency</span><span class="v" data-f="voltage_freq"></span></div>
        <div><span class="k">Reactive</span><span class="v" data-f="power_var"></span></div>
        <div><span class="k">Apparent</span><span class="v" data-f="power_va"></span></div>
        <div><span class="k">Energy · chip</span><span class="v" data-f="energy_kwh"></span></div>
        <div><span class="k">Energy · software</span><span class="v" data-f="energy_sw_kwh"></span></div>
        <div><span class="k">Exported</span><span class="v" data-f="export_kwh"></span></div>
        <div><span class="k">THD V</span><span class="v" data-f="voltage_thd"></span></div>
        <div><span class="k">THD I</span><span class="v" data-f="current_thd"></span></div>
      </div>`;
    el.dataset.phase = p;
    $("#phases").appendChild(el);
  }
  const fmt = {
    power_watt: (v) => `${num(v, 0)} W`, voltage_rms: (v) => `${num(v, 1)} V`, current_rms: (v) => `${num(v, 2)} A`,
    voltage_freq: (v) => `${num(v, 2)} Hz`, power_var: (v) => `${num(v, 0)} var`, power_va: (v) => `${num(v, 0)} VA`,
    energy_kwh: (v) => `${num(v, 4)} kWh`, energy_sw_kwh: (v) => `${num(v, 4)} kWh`, export_kwh: (v) => `${num(v, 4)} kWh`,
    voltage_thd: (v) => `${num(v, 1)} %`, current_thd: (v) => `${num(v, 1)} %`,
    pf: (v) => `PF ${num(v, 2)}`,
  };

  const live = chart($("#live"), "line", [], [...PHASES.map((p) => ({ label: `Phase ${p}`, data: [], borderColor: color(p), backgroundColor: color(p) })),
    { label: "Total", data: [], borderColor: css("--ink"), backgroundColor: css("--ink"), borderDash: [4, 3] }], { yTitle: "W" });
  let lastTs = null;

  liveFeed((data, mode) => {
    if (!data) { $("#t-age").textContent = mode; return; }
    if (!data.R) { $("#t-age").textContent = "no data yet"; return; }
    $("#t-mode").textContent = mode === "live" ? "● live" : "polling";
    $("#t-mode").className = `chip ${mode === "live" ? "ok" : "warn"}`;
    let total = 0;
    for (const p of PHASES) {
      const r = data[p] || {};
      total += r.power_watt || 0;
      const card = $(`[data-phase="${p}"]`);
      for (const span of card.querySelectorAll("[data-f]")) {
        const f = span.dataset.f;
        span.textContent = fmt[f](f === "pf" ? r.power_factor : r[f]);
      }
    }
    $("#t-p").textContent = `${num(total / 1000, 2)} kW`;
    $("#t-n").textContent = data.Neutral ? `${num(data.Neutral.current_rms, 2)} A` : "–";
    const age = data.R.age_s;
    $("#t-age").textContent = age < 10 ? `${num(age, 0)} s ago` : `${num(age / 60, 0)} min ago (stale)`;
    if (live && data.R.timestamp !== lastTs) {
      lastTs = data.R.timestamp;
      live.data.labels.push(new Date(lastTs).toLocaleTimeString("en-GB", { timeZone: TZ }));
      PHASES.forEach((p, i) => live.data.datasets[i].data.push(data[p] ? data[p].power_watt : null));
      live.data.datasets[3].data.push(total);
      if (live.data.labels.length > 300) { live.data.labels.shift(); live.data.datasets.forEach((d) => d.data.shift()); }
      live.update();
    }
  });

  every(30000, async () => {
    try {
      const m = await api(`/analytics/energy-daily?${dev()}`);
      const i = m.days.indexOf(todayStr());
      const today = i < 0 ? 0 : PHASES.reduce((s, p) => s + m.phases[p][i], 0);
      const todaySw = i < 0 ? 0 : PHASES.reduce((s, p) => s + m.phases_sw[p][i], 0);
      $("#t-e").textContent = `${num(today, 3)} kWh`;
      // The chip integrates continuously in hardware; the software figure is the old 1 Hz method.
      $("#t-diff").textContent = today > 1e-6 ? `${todaySw >= today ? "+" : ""}${num((todaySw - today) / today * 100, 2)} %` : "–";
    } catch { /* ignore */ }
  });
}

// ---------------------------------------------------------------- monitor
function monitor(view) {
  view.innerHTML = `
    <h1>Energy use</h1>
    <div class="row"><label>Day <input type="date" id="day" value="${todayStr()}"></label>
      <label>Month <input type="month" id="month" value="${monthStr()}"></label></div>
    <div class="tiles">
      <div class="card tile"><div class="k">Consumed on selected day</div><div class="v" id="t-day">–</div></div>
      <div class="card tile"><div class="k">Peak hour</div><div class="v" id="t-peak">–</div></div>
      <div class="card tile"><div class="k">Consumed in month</div><div class="v" id="t-month">–</div></div>
    </div>
    <div class="grid cols-2">
      <div class="card"><h2>Hourly consumption</h2><div class="chart-box"><canvas id="hourly"></canvas></div></div>
      <div class="card"><h2>Daily consumption</h2><div class="chart-box"><canvas id="daily"></canvas></div></div>
    </div>`;
  let hourly = null;
  let daily = null;

  const loadDay = async () => {
    const day = $("#day").value;
    const results = await Promise.all(PHASES.map((p) =>
      api(`/analytics/energy?date_str=${day}&phase=${p}&${dev()}`).catch(() => null)));
    const labels = Array.from({ length: 24 }, (_, h) => `${String(h).padStart(2, "0")}:00`);
    let total = 0;
    let peak = { kwh: 0, label: "–" };
    const perHour = new Array(24).fill(0);
    const datasets = PHASES.map((p, i) => {
      const data = new Array(24).fill(0);
      for (const b of (results[i] ? results[i].analytics_data.hourly : [])) {
        const h = +new Date(b.start).toLocaleTimeString("en-GB", { timeZone: TZ, hour: "2-digit" }).slice(0, 2);
        data[h] += b.kwh;
        perHour[h] += b.kwh;
        total += b.kwh;
      }
      return { label: `Phase ${p}`, data, backgroundColor: color(p) };
    });
    perHour.forEach((v, h) => { if (v > peak.kwh) peak = { kwh: v, label: labels[h] }; });
    $("#t-day").textContent = `${num(total, 3)} kWh`;
    $("#t-peak").textContent = peak.kwh > 0 ? `${peak.label} · ${num(peak.kwh, 3)} kWh` : "–";
    if (hourly) { hourly.destroy(); state.charts = state.charts.filter((c) => c !== hourly); }
    hourly = chart($("#hourly"), "bar", labels, datasets, { yTitle: "kWh", stacked: true });
  };

  const loadMonth = async () => {
    const m = await api(`/analytics/energy-daily?month=${$("#month").value}&${dev()}`);
    $("#t-month").textContent = `${num(m.month_total_kwh, 2)} kWh`;
    if (daily) { daily.destroy(); state.charts = state.charts.filter((c) => c !== daily); }
    daily = chart($("#daily"), "bar", m.days.map(dayLabel),
      PHASES.map((p) => ({ label: `Phase ${p}`, data: m.phases[p], backgroundColor: color(p) })), { yTitle: "kWh", stacked: true });
  };

  $("#day").addEventListener("change", loadDay);
  $("#month").addEventListener("change", loadMonth);
  loadDay().catch((e) => toast(e.message));
  loadMonth().catch((e) => toast(e.message));
  state.timers.push(setInterval(() => { if ($("#day").value === todayStr()) loadDay().catch(() => {}); }, 60000));
}

// ---------------------------------------------------------------- analysis
function analysis(view) {
  view.innerHTML = `
    <h1>Power analysis</h1>
    <div class="row"><label>Day <input type="date" id="day" value="${todayStr()}"></label>
      <label>Phase <select id="phase">${PHASES.map((p) => `<option>${p}</option>`).join("")}</select></label></div>
    <div class="tiles">
      <div class="card tile"><div class="k">Average power</div><div class="v" id="a-avg">–</div></div>
      <div class="card tile"><div class="k">Peak power</div><div class="v" id="a-max">–</div></div>
      <div class="card tile"><div class="k">Minimum power</div><div class="v" id="a-min">–</div></div>
      <div class="card tile"><div class="k">Energy consumed</div><div class="v" id="a-e">–</div></div>
    </div>
    <div class="grid cols-2">
      <div class="card"><h2>Active, reactive and apparent power (1-min averages)</h2><div class="chart-box"><canvas id="pw"></canvas></div></div>
      <div class="card"><h2>Cumulative energy during the day</h2><div class="chart-box"><canvas id="en"></canvas></div></div>
    </div>
    <p class="muted" id="note"></p>`;

  const load = async () => {
    destroyCharts();
    const day = $("#day").value;
    const phase = $("#phase").value;
    $("#note").textContent = "";
    try {
      const p = await api(`/analytics/power?date_str=${day}&phase=${phase}&${dev()}`);
      $("#a-avg").textContent = `${num(p.analytics_data.avg_power_watt, 0)} W`;
      $("#a-max").textContent = `${num(p.analytics_data.max_power_watt, 0)} W`;
      $("#a-min").textContent = `${num(p.analytics_data.min_power_watt, 0)} W`;
      const labels = p.power_data.map((r) => hhmm(r.timestamp));
      const c = color(phase);
      chart($("#pw"), "line", labels, [
        { label: "Active (W)", data: p.power_data.map((r) => r.power_watt), borderColor: c, backgroundColor: c },
        { label: "Reactive (var)", data: p.power_data.map((r) => r.power_var), borderColor: css("--muted"), backgroundColor: css("--muted") },
        { label: "Apparent (VA)", data: p.power_data.map((r) => r.power_va), borderColor: css("--ink"), backgroundColor: css("--ink"), borderDash: [4, 3] },
      ], { yTitle: "W / var / VA" });
    } catch (e) {
      $("#note").textContent = e.status === 404 ? "No power data for this day yet." : e.message;
      ["#a-avg", "#a-max", "#a-min"].forEach((s) => { $(s).textContent = "–"; });
    }
    try {
      const en = await api(`/analytics/energy?date_str=${day}&phase=${phase}&${dev()}`);
      $("#a-e").textContent = `${num(en.analytics_data.consumed_kwh, 3)} kWh`;
      // Running total of positive steps, so a counter reset doesn't show as a drop.
      let acc = 0;
      let prev = null;
      const data = en.energy_data.map((r) => {
        if (prev != null && r.energy_kwh > prev) acc += r.energy_kwh - prev;
        prev = r.energy_kwh;
        return acc;
      });
      chart($("#en"), "line", en.energy_data.map((r) => hhmm(r.timestamp)),
        [{ label: `Phase ${phase} (kWh since midnight)`, data, borderColor: color(phase), backgroundColor: color(phase), fill: false }], { yTitle: "kWh" });
    } catch (e) { $("#a-e").textContent = "–"; }
  };
  $("#day").addEventListener("change", load);
  $("#phase").addEventListener("change", load);
  load();
}

// ---------------------------------------------------------------- power quality
function quality(view) {
  const charts = [
    ["voltage_rms", "Voltage (V RMS)", "V"],
    ["voltage_freq", "Frequency", "Hz"],
    ["voltage_thd", "Voltage THD", "%"],
    ["current_thd", "Current THD", "%"],
    ["power_factor", "Power factor", "PF"],
    ["current_rms", "Current (A RMS)", "A"],
  ];
  view.innerHTML = `
    <h1>Power quality</h1>
    <div class="row"><label>Day <input type="date" id="day" value="${todayStr()}"></label>
      <span class="muted">1-minute averages. Sags, swells and outages show up in the voltage plot.</span></div>
    <div class="card" style="margin-bottom:14px"><h2>Supply interruptions (last 30 days)</h2>
      <table><thead><tr><th>Phase</th><th>Lost supply</th><th>Restored</th><th>Duration</th></tr></thead>
      <tbody id="outages"><tr><td colspan="4" class="muted">Loading…</td></tr></tbody></table></div>
    <div class="grid cols-2">${charts.map(([f, t]) =>
      `<div class="card"><h2>${t}</h2><div class="chart-box"><canvas id="q-${f}"></canvas></div></div>`).join("")}</div>`;
  const when = (iso) => new Date(iso).toLocaleString("en-GB", { timeZone: TZ, dateStyle: "medium", timeStyle: "medium" });
  const dur = (s) => (s == null ? "ongoing" : s < 60 ? `${num(s, 0)} s` : s < 3600 ? `${num(s / 60, 1)} min` : `${num(s / 3600, 1)} h`);
  const loadOutages = async () => {
    try {
      const ev = await api(`/api/events?days=30&${dev()}`);
      $("#outages").innerHTML = ev.map((e) => `<tr><td>${esc(e.phase)}</td><td>${esc(when(e.start))}</td>
        <td>${e.end ? esc(when(e.end)) : "–"}</td><td>${dur(e.duration_s)}</td></tr>`).join("")
        || '<tr><td colspan="4" class="muted">No interruptions recorded</td></tr>';
    } catch (e) { $("#outages").innerHTML = `<tr><td colspan="4" class="muted">${esc(e.message)}</td></tr>`; }
  };
  loadOutages();
  state.timers.push(setInterval(loadOutages, 15000));
  const load = async () => {
    destroyCharts();
    try {
      const s = await api(`/api/series?fields=${charts.map((c) => c[0]).join(",")}&date_str=${$("#day").value}&every=60&${dev()}`);
      for (const [f, , unit] of charts) {
        const { labels, datasets } = phaseDatasets(s, f);
        chart($(`#q-${f}`), "line", labels, datasets, { yTitle: unit });
      }
    } catch (e) { toast(e.message); }
  };
  $("#day").addEventListener("change", load);
  load();
  state.timers.push(setInterval(() => { if ($("#day").value === todayStr()) load(); }, 60000));
}

// ---------------------------------------------------------------- control
function control(view) {
  view.innerHTML = `
    <h1>Remote control</h1>
    <p class="muted">Switching OFF disconnects the supply to that phase. The meter has the final say: it checks
      with its own sensor that current really stopped, keeps a 3-minute minimum off-time to protect compressors,
      won't switch ON into a faulty supply, and trips on its own on overcurrent.</p>
    <div class="row"><button id="all-on">All phases ON</button><button id="all-off" class="danger">All phases OFF</button>
      <span id="online" class="chip">–</span></div>
    <div class="grid cols-4" id="relays" style="margin-bottom:14px"></div>
    <div class="card"><h2>Recent commands</h2><table><thead><tr><th>Time</th><th>User</th><th>Phase</th><th>Command</th><th>Result</th></tr></thead><tbody id="hist"></tbody></table></div>`;

  for (const p of PHASES) {
    const el = document.createElement("div");
    el.className = "card phase-card relay";
    el.style.setProperty("--pc", color(p));
    el.innerHTML = `<h2>Phase ${p}<span class="muted" data-amps></span></h2><div class="state" data-state>–</div>
      <div class="muted" data-reason></div>
      <div class="btns"><button data-cmd="on">Turn ON</button><button data-cmd="off" class="danger">Turn OFF</button></div>
      <div class="error" data-result></div>`;
    el.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => send(p, b.dataset.cmd)));
    el.dataset.phase = p;
    $("#relays").appendChild(el);
  }
  $("#all-on").addEventListener("click", () => send("ALL", "on"));
  $("#all-off").addEventListener("click", () => send("ALL", "off"));

  let lastStatus = null;
  const show = (s) => {
    lastStatus = { ...(lastStatus || {}), ...s, fetchedAt: Date.now() };
    $("#online").textContent = s.online ? "meter online" : "meter offline";
    $("#online").className = `chip ${s.online ? "ok" : "bad"}`;
    for (const p of PHASES) {
      const st = (lastStatus.relays || {})[p];
      const d = (lastStatus.details || {})[p] || {};
      const card = $(`[data-phase="${p}"]`);
      const el = card.querySelector("[data-state]");
      el.textContent = d.welded ? "WELDED" : st ? st.toUpperCase() : "unknown";
      el.className = `state ${d.welded ? "off" : st || ""}`;
      card.querySelector("[data-amps]").textContent = d.measured_a == null ? "" : `${num(d.measured_a, 2)} A`;
      const lines = [];
      if (d.reason) lines.push(d.reason);
      const left = Math.max((d.lockout_s || 0) - (Date.now() - lastStatus.fetchedAt) / 1000, 0);
      if (left > 0) lines.push(`ON allowed in ${Math.ceil(left)} s (minimum off-time)`);
      if ((lastStatus.mismatch || {})[p]) lines.push(`You asked for ${(lastStatus.desired || {})[p].toUpperCase()}; the meter overrode it`);
      card.querySelector("[data-reason]").textContent = lines.join(" · ");
      card.querySelector('[data-cmd="on"]').disabled = left > 0 || d.welded;
    }
  };
  state.timers.push(setInterval(() => { if (lastStatus) show({ online: lastStatus.online }); }, 1000));
  const history = async () => {
    try {
      const rows = await api(`/remote-control/history?${dev()}`);
      $("#hist").innerHTML = rows.map((r) => `<tr><td>${esc(new Date(r.created_at).toLocaleString("en-GB", { timeZone: TZ }))}</td>
        <td>${esc(r.username || (r.command.startsWith("auto:") ? "meter (automatic)" : "–"))}</td><td>${esc(r.phase || "–")}</td><td>${esc(r.command)}</td>
        <td>${r.ok ? "confirmed" : r.command.startsWith("auto:") ? `by the meter: ${esc(r.detail || "")}` : `refused / failed${r.detail ? ": " + esc(r.detail) : ""}`}</td></tr>`).join("") || '<tr><td colspan="5" class="muted">No commands yet</td></tr>';
    } catch { /* ignore */ }
  };

  async function send(phase, command) {
    if (command === "off" && !confirm(`Disconnect the supply to ${phase === "ALL" ? "ALL phases" : "phase " + phase}?`)) return;
    const buttons = view.querySelectorAll("button");
    buttons.forEach((b) => { b.disabled = true; });
    try {
      view.querySelectorAll("[data-result]").forEach((x) => { x.textContent = ""; });
      const r = await api("/remote-control", { method: "POST", body: { device_id: state.device.device_id, phase, command } });
      show({ online: true, relays: r.relays, details: r.details });
      toast(r.unverified && r.unverified.length
        ? `Phase ${phase} ${command.toUpperCase()} applied, but the meter had no readings to verify it`
        : `Phase ${phase} ${command.toUpperCase()} - verified by the meter's own measurement`);
    } catch (e) {
      const target = phase === "ALL" ? $("#relays") : $(`[data-phase="${phase}"] [data-result]`);
      if (phase === "ALL") toast(e.message, 8000); else target.textContent = e.message;
      api(`/remote-control/status?refresh=true&${dev()}`).then(show).catch(() => {});
    } finally {
      buttons.forEach((b) => { b.disabled = false; });
      if (lastStatus) show({ online: lastStatus.online });  // re-apply lockout / welded disables at once
      history();
    }
  }

  api(`/remote-control/status?refresh=true&${dev()}`).then(show).catch((e) => toast(e.message));
  history();
  state.timers.push(setInterval(() => api(`/remote-control/status?refresh=false&${dev()}`).then(show).catch(() => {}), 5000));
}

// ---------------------------------------------------------------- insights
function insights(view) {
  view.innerHTML = `
    <h1>Insights</h1>
    <div class="grid cols-2">
      <div class="card"><h2>Bill forecast</h2><div id="bill">Loading…</div></div>
      <div class="card"><h2>Phase balance</h2><div id="bal">Loading…</div></div>
    </div>
    <div class="card" style="margin-top:14px"><h2>Unbalance by hour of day</h2><div class="chart-box"><canvas id="ub"></canvas></div></div>
    <div class="card" style="margin-top:14px"><h2>Your tariff</h2>
      <p class="muted">Enter the slabs from your electricity bill. Rates are per unit (kWh); leave the last limit empty.</p>
      <form id="tf" style="display:grid;gap:10px">
        <div class="row"><label>Name <input name="name"></label><label>Currency <input name="currency" size="3"></label>
          <label>Fixed charge <input name="fixed_charge" type="number" step="0.01" min="0"></label>
          <label>Billing cycle starts on day <input name="cycle_start_day" type="number" min="1" max="28"></label></div>
        <table><thead><tr><th>Up to (units)</th><th>Rate</th></tr></thead><tbody id="slabs"></tbody></table>
        <div class="row"><button type="button" id="add-slab">Add slab</button><button class="primary">Save tariff</button></div>
        <p class="error" id="tf-err"></p>
      </form></div>`;

  const money = (t, v) => `${t.currency}${num(v, 2)}`;
  const loadBill = async () => {
    try {
      const f = await api(`/analytics/bill-forecast?${dev()}`);
      const t = f.tariff;
      $("#bill").innerHTML = `
        <div class="tiles">
          <div class="tile"><div class="k">So far (${esc(f.cycle.start)} →)</div><div class="v">${num(f.so_far.units, 1)} units</div><div class="muted">${money(t, f.so_far.total)}</div></div>
          <div class="tile"><div class="k">Projected by ${esc(f.cycle.end)}</div><div class="v">${num(f.projected.units, 0)} units</div><div class="muted">${money(t, f.projected.total)}</div></div>
          <div class="tile"><div class="k">Average daily use</div><div class="v">${num(f.average_daily_kwh, 1)} kWh</div><div class="muted">confidence: ${esc(f.confidence)} (${f.history_days} days of history)</div></div>
        </div>
        ${f.warnings.map((w) => `<p class="error">⚠ ${esc(w.text)}</p>`).join("")}
        ${f.tip ? `<p>${esc(f.tip)}</p>` : ""}
        <table><thead><tr><th>Slab</th><th>Units</th><th>Rate</th><th>Cost</th></tr></thead><tbody>
          ${f.projected.slabs.map((sl) => `<tr><td>${num(sl.from, 0)}–${sl.to == null ? "∞" : num(sl.to, 0)}</td><td>${num(sl.units, 1)}</td><td>${money(t, sl.rate)}</td><td>${money(t, sl.cost)}</td></tr>`).join("")}
          <tr><td>Fixed charge</td><td></td><td></td><td>${money(t, t.fixed_charge)}</td></tr></tbody></table>
        ${f.tariff_is_default ? '<p class="muted">Using an example tariff: set yours below for a real forecast.</p>' : ""}`;
    } catch (e) { $("#bill").textContent = e.message; }
  };

  const loadBalance = async () => {
    try {
      const b = await api(`/analytics/balance?days=14&${dev()}`);
      const share = b.phase_share_pct;
      $("#bal").innerHTML = `
        <div class="tiles">
          <div class="tile"><div class="k">Average unbalance</div><div class="v">${b.average_unbalance_pct == null ? "–" : num(b.average_unbalance_pct, 0) + " %"}</div><div class="muted">worst at ${esc(b.worst_hour || "–")} (${num(b.worst_hour_unbalance_pct, 0)} %)</div></div>
          <div class="tile"><div class="k">Average neutral current</div><div class="v">${num(b.average_neutral_a, 2)} A</div></div>
        </div>
        <p>Share of load: ${PHASES.map((p) => `<span style="color:${color(p)}">${p} ${num(share[p], 0)}%</span>`).join(" · ")}</p>
        ${b.recommendations.length ? b.recommendations.map((r) => `<p><b>💡 ${esc(r.text)}</b><br><span class="muted">Seen ${r.occurrences} times in the period.</span></p>`).join("")
          : `<p class="muted">No phase move would make a clear difference${b.days_of_data < 3 ? " yet (needs a few days of history)" : ""}.</p>`}
        <details><summary>Detected switchable loads (${b.loads.length})</summary><table><thead><tr><th>Phase</th><th>Size</th><th>Usually</th><th>Times</th><th>Avg run</th></tr></thead><tbody>
          ${b.loads.map((l) => `<tr><td>${l.phase}</td><td>${num(l.kw, 2)} kW</td><td>${esc(l.usual_hours)}</td><td>${l.occurrences}</td><td>${l.avg_duration_min} min</td></tr>`).join("")}</tbody></table></details>
        <p class="muted">Based on ${num(b.days_of_data, 1)} days. Moving a circuit to another phase is a job for an electrician.</p>`;
      const hours = Object.keys(b.unbalance_by_hour);
      chart($("#ub"), "bar", hours.map((h) => `${h}:00`), [{ label: "Unbalance (%)", data: Object.values(b.unbalance_by_hour), backgroundColor: css("--accent") }], { yTitle: "%" });
    } catch (e) { $("#bal").textContent = e.message; }
  };

  const slabRow = (sl = { upto: "", rate: "" }) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td><input type="number" min="1" step="1" value="${sl.upto ?? ""}" placeholder="no limit"></td>
      <td><input type="number" min="0" step="0.01" value="${sl.rate}"></td>`;
    $("#slabs").appendChild(tr);
  };
  const loadTariff = async () => {
    const { tariff } = await api("/analytics/tariff");
    const f = $("#tf");
    for (const k of ["name", "currency", "fixed_charge", "cycle_start_day"]) f[k].value = tariff[k];
    $("#slabs").innerHTML = "";
    tariff.slabs.forEach(slabRow);
  };
  $("#add-slab").addEventListener("click", () => slabRow());
  $("#tf").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target;
    const slabs = [...$("#slabs").querySelectorAll("tr")].map((tr) => {
      const [u, r] = tr.querySelectorAll("input");
      return { upto: u.value === "" ? null : +u.value, rate: +r.value };
    }).filter((sl) => !Number.isNaN(sl.rate));
    try {
      await api("/analytics/tariff", { method: "PUT", body: { name: f.name.value, currency: f.currency.value,
        fixed_charge: +f.fixed_charge.value, cycle_start_day: +f.cycle_start_day.value, slabs } });
      $("#tf-err").textContent = "";
      toast("Tariff saved");
      loadBill();
    } catch (err) { $("#tf-err").textContent = err.message; }
  });
  loadBill();
  loadBalance();
  loadTariff().catch((e) => { $("#tf-err").textContent = e.message; });
}

// ---------------------------------------------------------------- password reset / account
function forgot(view) {
  authPage(view, "Reset your password", `
    <form id="f">
      <label>Username or email <input name="identifier" autocomplete="username" required></label>
      <p class="error" id="err"></p><p class="muted" id="ok"></p>
      <button class="primary">Send reset link</button>
      <p class="muted">Links expire after 15 minutes and work once. <a href="#/login">Back to log in</a></p>
    </form>`);
  $("#f").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("#err").textContent = "";
    try {
      const r = await api("/auth/forgot-password", { method: "POST", auth: false, body: { identifier: new FormData(e.target).get("identifier") } });
      $("#ok").textContent = r.message;
    } catch (err) { $("#err").textContent = err.message; }
  });
}

function reset(view, params) {
  authPage(view, "Choose a new password", `
    <form id="f">
      <label>New password (8+ characters) <input name="p1" type="password" autocomplete="new-password" minlength="8" required></label>
      <label>Repeat it <input name="p2" type="password" autocomplete="new-password" minlength="8" required></label>
      <p class="error" id="err"></p>
      <button class="primary">Set password</button>
      <p class="muted">Every device signed in to this account will be logged out.</p>
    </form>`);
  $("#f").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    if (fd.get("p1") !== fd.get("p2")) { $("#err").textContent = "The passwords don't match"; return; }
    try {
      const r = await api("/auth/reset-password", { method: "POST", auth: false, body: { token: params.get("token") || "", new_password: fd.get("p1") } });
      state.token = null; safeSet("voltix_token", null); state.user = null;
      toast(r.message);
      location.hash = "#/login";
    } catch (err) { $("#err").textContent = err.message; }
  });
}

function account(view) {
  view.innerHTML = `
    <h1>Account</h1>
    <div class="grid cols-2">
      <div class="card"><h2>Change password</h2>
        <form id="pw" class="auth-form" style="display:grid;gap:10px">
          <label>Current password <input name="current" type="password" autocomplete="current-password" required></label>
          <label>New password <input name="new" type="password" autocomplete="new-password" minlength="8" required></label>
          <p class="error" id="pw-err"></p>
          <button class="primary">Change password</button>
          <p class="muted">Other devices signed in to this account will be logged out.</p>
        </form></div>
      <div class="card"><h2>Recovery email</h2>
        <form id="em" style="display:grid;gap:10px">
          <label>Email <input name="email" type="email" autocomplete="email" value="${esc(state.user.email || "")}"></label>
          <label>Current password <input name="current" type="password" autocomplete="current-password" required></label>
          <p class="error" id="em-err"></p>
          <button>Save email</button>
          <p class="muted">Used only to send password-reset links.</p>
        </form></div>
      <div class="card"><h2>Sessions</h2>
        <p class="muted">Lost a phone or used a shared computer? End every session, including this one.</p>
        <button id="all" class="danger">Log out everywhere</button></div>
    </div>`;
  $("#pw").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      const r = await api("/auth/change-password", { method: "POST", body: { current_password: fd.get("current"), new_password: fd.get("new") } });
      state.token = r.access_token; safeSet("voltix_token", r.access_token);
      e.target.reset(); $("#pw-err").textContent = ""; toast("Password changed; other devices were logged out");
    } catch (err) { $("#pw-err").textContent = err.message; }
  });
  $("#em").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      const r = await api("/auth/email", { method: "POST", body: { current_password: fd.get("current"), email: fd.get("email") || null } });
      state.user.email = r.email; $("#em-err").textContent = ""; e.target.current.value = ""; toast("Email saved");
    } catch (err) { $("#em-err").textContent = err.message; }
  });
  $("#all").addEventListener("click", async () => {
    if (!confirm("Log out of every device, including this one?")) return;
    try { await api("/auth/logout-all", { method: "POST" }); } catch { /* logging out anyway */ }
    logout("Logged out everywhere");
  });
}

// ---------------------------------------------------------------- router
const routes = { login, signup, forgot, reset, dashboard, monitor, analysis, quality, control, insights, account };
const PUBLIC = new Set(["login", "signup", "forgot", "reset"]);

async function render() {
  state.viewGen += 1;
  cleanup();
  const raw = location.hash.replace(/^#\/?/, "");
  const [name, qs] = raw.split("?");
  const route = name || "dashboard";
  const params = new URLSearchParams(qs || "");
  const view = $("#view");

  if (!state.token && !PUBLIC.has(route)) { location.hash = "#/login"; return; }
  if (state.token && (route === "login" || route === "signup" || route === "forgot") && !params.get("code")) { location.hash = "#/dashboard"; return; }
  if (state.token && !state.user) {
    try { await loadMe(); } catch (e) { if (e.status !== 401) view.innerHTML = `<p class="error">${esc(e.message)}</p>`; return; }
  }
  $("#topbar").hidden = !state.token;
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === route));
  if (state.token && !state.device && routes[route] && !PUBLIC.has(route) && route !== "account") { noDevice(view); return; }
  (routes[route] || dashboard)(view, params);
}

$("#logout").addEventListener("click", () => logout());
window.addEventListener("hashchange", render);
render();
