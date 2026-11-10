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

async function api(path, { method = "GET", body, auth = true } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (auth && state.token) headers.Authorization = `Bearer ${state.token}`;
  const res = await fetch(API + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await res.json().catch(() => ({}));
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
  destroyCharts();
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
        body: { username: fd.get("username"), password: fd.get("password"), claim_code: fd.get("claim_code").trim() },
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
      <div class="card tile"><div class="k">Energy today</div><div class="v" id="t-e">–</div></div>
      <div class="card tile"><div class="k">Neutral current</div><div class="v" id="t-n">–</div></div>
      <div class="card tile"><div class="k">Last reading</div><div class="v" id="t-age">–</div></div>
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
        <div><span class="k">Energy (counter)</span><span class="v" data-f="energy_kwh"></span></div>
        <div><span class="k">THD V</span><span class="v" data-f="voltage_thd"></span></div>
        <div><span class="k">THD I</span><span class="v" data-f="current_thd"></span></div>
      </div>`;
    el.dataset.phase = p;
    $("#phases").appendChild(el);
  }
  const fmt = {
    power_watt: (v) => `${num(v, 0)} W`, voltage_rms: (v) => `${num(v, 1)} V`, current_rms: (v) => `${num(v, 2)} A`,
    voltage_freq: (v) => `${num(v, 2)} Hz`, power_var: (v) => `${num(v, 0)} var`, power_va: (v) => `${num(v, 0)} VA`,
    energy_kwh: (v) => `${num(v, 3)} kWh`, voltage_thd: (v) => `${num(v, 1)} %`, current_thd: (v) => `${num(v, 1)} %`,
    pf: (v) => `PF ${num(v, 2)}`,
  };

  const live = chart($("#live"), "line", [], [...PHASES.map((p) => ({ label: `Phase ${p}`, data: [], borderColor: color(p), backgroundColor: color(p) })),
    { label: "Total", data: [], borderColor: css("--ink"), backgroundColor: css("--ink"), borderDash: [4, 3] }], { yTitle: "W" });
  let lastTs = null;

  every(2000, async () => {
    let data;
    try { data = await api(`/api/latest-values?${dev()}`); } catch (e) { $("#t-age").textContent = e.message; return; }
    if (!data.R) { $("#t-age").textContent = "no data yet"; return; }
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
      $("#t-e").textContent = `${num(today, 3)} kWh`;
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
    <div class="grid cols-2">${charts.map(([f, t]) =>
      `<div class="card"><h2>${t}</h2><div class="chart-box"><canvas id="q-${f}"></canvas></div></div>`).join("")}</div>`;
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
    <p class="muted">Switching OFF disconnects the supply to that phase. The state shown is what the meter
      confirmed, not just what was requested.</p>
    <div class="row"><button id="all-on">All phases ON</button><button id="all-off" class="danger">All phases OFF</button>
      <span id="online" class="chip">–</span></div>
    <div class="grid cols-4" id="relays" style="margin-bottom:14px"></div>
    <div class="card"><h2>Recent commands</h2><table><thead><tr><th>Time</th><th>User</th><th>Phase</th><th>Command</th><th>Result</th></tr></thead><tbody id="hist"></tbody></table></div>`;

  for (const p of PHASES) {
    const el = document.createElement("div");
    el.className = "card phase-card relay";
    el.style.setProperty("--pc", color(p));
    el.innerHTML = `<h2>Phase ${p}</h2><div class="state" data-state>–</div>
      <div class="btns"><button data-cmd="on">Turn ON</button><button data-cmd="off" class="danger">Turn OFF</button></div>`;
    el.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => send(p, b.dataset.cmd)));
    el.dataset.phase = p;
    $("#relays").appendChild(el);
  }
  $("#all-on").addEventListener("click", () => send("ALL", "on"));
  $("#all-off").addEventListener("click", () => send("ALL", "off"));

  const show = (s) => {
    $("#online").textContent = s.online ? "meter online" : "meter offline";
    $("#online").className = `chip ${s.online ? "ok" : "bad"}`;
    for (const p of PHASES) {
      const st = (s.relays || {})[p];
      const el = $(`[data-phase="${p}"] [data-state]`);
      el.textContent = st ? st.toUpperCase() : "unknown";
      el.className = `state ${st || ""}`;
    }
  };
  const history = async () => {
    try {
      const rows = await api(`/remote-control/history?${dev()}`);
      $("#hist").innerHTML = rows.map((r) => `<tr><td>${esc(new Date(r.created_at).toLocaleString("en-GB", { timeZone: TZ }))}</td>
        <td>${esc(r.username || "–")}</td><td>${esc(r.phase || "–")}</td><td>${esc(r.command)}</td>
        <td>${r.ok ? "confirmed" : `failed${r.detail ? ": " + esc(r.detail) : ""}`}</td></tr>`).join("") || '<tr><td colspan="5" class="muted">No commands yet</td></tr>';
    } catch { /* ignore */ }
  };

  async function send(phase, command) {
    if (command === "off" && !confirm(`Disconnect the supply to ${phase === "ALL" ? "ALL phases" : "phase " + phase}?`)) return;
    const buttons = view.querySelectorAll("button");
    buttons.forEach((b) => { b.disabled = true; });
    try {
      const r = await api("/remote-control", { method: "POST", body: { device_id: state.device.device_id, phase, command } });
      show({ online: true, relays: r.relays });
      toast(`Phase ${phase} ${command.toUpperCase()} - confirmed by the meter`);
    } catch (e) {
      toast(e.message);
    } finally {
      buttons.forEach((b) => { b.disabled = false; });
      history();
    }
  }

  api(`/remote-control/status?refresh=true&${dev()}`).then(show).catch((e) => toast(e.message));
  history();
  state.timers.push(setInterval(() => api(`/remote-control/status?refresh=false&${dev()}`).then(show).catch(() => {}), 5000));
}

// ---------------------------------------------------------------- router
const routes = { login, signup, dashboard, monitor, analysis, quality, control };

async function render() {
  cleanup();
  const raw = location.hash.replace(/^#\/?/, "");
  const [name, qs] = raw.split("?");
  const route = name || "dashboard";
  const params = new URLSearchParams(qs || "");
  const view = $("#view");

  if (!state.token && route !== "login" && route !== "signup") { location.hash = "#/login"; return; }
  if (state.token && (route === "login" || route === "signup") && !params.get("code")) { location.hash = "#/dashboard"; return; }
  if (state.token && !state.user) {
    try { await loadMe(); } catch (e) { if (e.status !== 401) view.innerHTML = `<p class="error">${esc(e.message)}</p>`; return; }
  }
  $("#topbar").hidden = !state.token;
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === route));
  if (state.token && !state.device && routes[route] && route !== "login" && route !== "signup") { noDevice(view); return; }
  (routes[route] || dashboard)(view, params);
}

$("#logout").addEventListener("click", () => logout());
window.addEventListener("hashchange", render);
render();
