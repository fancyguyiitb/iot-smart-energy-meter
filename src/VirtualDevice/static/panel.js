// Control panel for the virtual meter board. Polls /api/state and posts control changes.
const PHASES = ["R", "Y", "B"];
const phaseEls = {};
let lastSpi = null;
let editing = false; // don't overwrite a slider while the user is dragging it

async function post(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) console.warn(path, await res.text());
  refresh();
}

const fmt = {
  voltage: (v) => `${v.toFixed(1)} V`,
  current: (v) => `${v.toFixed(2)} A`,
  active_w: (v) => `${v.toFixed(0)} W`,
  reactive_var: (v) => `${v.toFixed(0)} var`,
  apparent_va: (v) => `${v.toFixed(0)} VA`,
  pf: (v) => v.toFixed(3),
  voltage_thd: (v) => `${v.toFixed(1)} %`,
  current_thd: (v) => `${v.toFixed(1)} %`,
  frequency: (v) => `${v.toFixed(2)} Hz`,
  energy_import_wh: (v) => `${v.toFixed(1)} Wh`,
  energy_export_wh: (v) => `${v.toFixed(1)} Wh`,
};

function buildPhases() {
  const tpl = document.getElementById("phase-template");
  const container = document.getElementById("phases");
  for (const p of PHASES) {
    const node = tpl.content.firstElementChild.cloneNode(true);
    node.style.setProperty("--pc", `var(--${p})`);
    node.querySelector(".pname").textContent = `Phase ${p}`;
    node.querySelectorAll(".modes button").forEach((b) =>
      b.addEventListener("click", () => post(`/api/phase/${p}`, { mode: b.dataset.mode })));
    const custom = node.querySelector(".in-custom");
    const customOut = node.querySelector(".out-custom");
    custom.addEventListener("input", () => { editing = true; customOut.textContent = `${(+custom.value).toFixed(1)} kW`; });
    custom.addEventListener("change", () => { editing = false; post(`/api/phase/${p}`, { custom_kw: +custom.value }); });
    node.querySelector(".in-ct").addEventListener("change", (e) =>
      post(`/api/phase/${p}`, { ct_reversed: e.target.checked }));
    container.appendChild(node);
    phaseEls[p] = node;
  }
}

function bindGrid() {
  const sliders = [
    ["in-freq", "out-freq", "frequency", (v) => `${(+v).toFixed(2)} Hz`],
    ["in-vthd", "out-vthd", "voltage_thd", (v) => `${(+v).toFixed(1)} %`],
    ["in-ln", "out-ln", "loose_neutral", (v) => (+v).toFixed(2)],
  ];
  for (const [inId, outId, key, f] of sliders) {
    const el = document.getElementById(inId);
    el.addEventListener("input", () => { editing = true; document.getElementById(outId).textContent = f(el.value); });
    el.addEventListener("change", () => { editing = false; post("/api/grid", { [key]: +el.value }); });
  }
  document.getElementById("in-noise").addEventListener("change", (e) => post("/api/grid", { noise: e.target.checked }));
  document.querySelectorAll("[data-scenario]").forEach((b) =>
    b.addEventListener("click", () => post(`/api/scenario/${b.dataset.scenario}`)));
  document.getElementById("btn-reset-truth").addEventListener("click", () => post("/api/reset-truth-energy"));
  document.getElementById("btn-power-cycle").addEventListener("click", () => {
    if (confirm("Simulate a board power loss? The firmware must re-initialise the ADE9000.")) post("/api/chip/power-cycle");
  });
}

function render(s) {
  const dsp = document.getElementById("chip-dsp");
  dsp.textContent = `ADE9000 DSP: ${s.chip.running ? "running" : "stopped (RUN=0)"}`;
  dsp.className = `chip ${s.chip.running ? "ok" : "bad"}`;
  const fw = document.getElementById("chip-fw");
  fw.textContent = `Firmware: ${s.chip.firmware_connected ? "reading SPI" : "no SPI activity"}`;
  fw.className = `chip ${s.chip.firmware_connected ? "ok" : "bad"}`;
  if (lastSpi) {
    const rate = (s.chip.spi_transactions - lastSpi.n) / Math.max((Date.now() - lastSpi.t) / 1000, 0.1);
    document.getElementById("chip-spi").textContent = `SPI: ${rate.toFixed(0)} frames/s`;
  }
  lastSpi = { n: s.chip.spi_transactions, t: Date.now() };

  if (!editing) {
    document.getElementById("in-freq").value = s.grid.frequency;
    document.getElementById("out-freq").textContent = `${s.grid.frequency.toFixed(2)} Hz`;
    document.getElementById("in-vthd").value = s.grid.voltage_thd;
    document.getElementById("out-vthd").textContent = `${s.grid.voltage_thd.toFixed(1)} %`;
    document.getElementById("in-ln").value = s.grid.loose_neutral;
    document.getElementById("out-ln").textContent = s.grid.loose_neutral.toFixed(2);
  }
  document.getElementById("in-noise").checked = s.grid.noise;

  let totalP = 0, totalE = 0;
  for (const p of PHASES) {
    const el = phaseEls[p];
    const truth = s.phases[p];
    const supply = s.supply[p];
    totalP += truth.active_w;
    totalE += truth.energy_import_wh;
    const gpio = s.gpio.find((g) => g.phase === p);
    const closed = s.relays[p];
    el.querySelector(".led").className = `led ${closed ? "on" : ""}`;
    el.querySelector(".relay-text").textContent =
      `Relay ${closed ? "CLOSED" : "OPEN"} · GPIO${gpio ? gpio.pin : "?"}=${gpio ? gpio.level : "?"}${gpio && !gpio.mode ? " (not set up)" : ""}`;
    el.querySelectorAll(".modes button").forEach((b) => b.classList.toggle("active", b.dataset.mode === supply.mode));
    for (const span of el.querySelectorAll("[data-f]")) span.textContent = fmt[span.dataset.f](truth[span.dataset.f]);
    if (!editing) {
      el.querySelector(".in-custom").value = supply.custom_kw;
      el.querySelector(".out-custom").textContent = `${supply.custom_kw.toFixed(1)} kW`;
    }
    el.querySelector(".in-ct").checked = supply.ct_reversed;

    const list = el.querySelector(".appliances");
    const items = s.appliances.filter((a) => a.phase === p);
    if (list.children.length !== items.length) {
      list.innerHTML = "";
      for (const a of items) {
        const li = document.createElement("li");
        li.innerHTML = `<span><span class="dot"></span>${a.name}<br><span class="meta">${a.watts} W · PF ${a.pf} · THD ${a.thd}%${a.cycle_on_s ? " · cycles" : ""}</span></span>
          <label class="toggle"><input type="checkbox"> On</label>`;
        li.querySelector("input").addEventListener("change", (e) => post(`/api/appliance/${a.id}`, { on: e.target.checked }));
        list.appendChild(li);
      }
    }
    items.forEach((a, i) => {
      const li = list.children[i];
      li.querySelector("input").checked = a.on;
      li.querySelector(".dot").className = `dot ${a.drawing ? "on" : ""}`;
    });
  }
  document.getElementById("tot-p").textContent = `${(totalP / 1000).toFixed(2)} kW`;
  document.getElementById("tot-n").textContent = `${s.neutral_current.toFixed(2)} A`;
  document.getElementById("tot-e").textContent = `${(totalE / 1000).toFixed(4)} kWh`;
  const acc = s.chip.energy_accumulator_wh;
  document.getElementById("tot-acc").textContent = PHASES.map((p) => `${p}: ${acc[p].toFixed(1)} Wh`).join(" · ");
}

async function refresh() {
  try {
    const res = await fetch("/api/state");
    render(await res.json());
  } catch (e) {
    console.warn(e);
  }
}

buildPhases();
bindGrid();
refresh();
setInterval(refresh, 1000);
