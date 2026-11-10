/*
 * Hawaii Local – switch cards styled like Hawaii Automations wall switches.
 *
 * Loaded automatically by the integration (no resource to add). Pick any one
 * entity of a switch and the card shows the whole switch: every key, with its
 * own name and indicator light. Works with any Home Assistant switch, light,
 * cover or fan, not only Hawaii Local ones.
 *
 *   type: custom:hawaii-key-switch-card     – 1 to 10 keys (columns, rows or grid)
 *   type: custom:hawaii-key-socket-card     – keys + universal socket (4 module)
 *   type: custom:hawaii-curtain-switch-card – open / pause / close, 1 or 2 curtains
 *   type: custom:hawaii-knob-dimmer-card    – rotary dimmer with round display
 *   type: custom:hawaii-knob-keys-card      – rotary dimmer ringed by 4 keys
 *
 * Common options: entity (any one entity of the switch), entities (pick keys
 * yourself), exclude, names, finish, indicator, show_names, name.
 */
const VERSION = "0.3.4";

/* ------------------------------------------------------------------ looks */

export const FINISHES = {
  black: {
    label: "Black glass",
    plate: "linear-gradient(160deg,#2b2c30 0%,#1a1b1e 55%,#141517 100%)",
    rim: "#0b0b0c", line: "rgba(0,0,0,.75)", lineHi: "rgba(255,255,255,.07)",
    text: "rgba(232,236,241,.78)", dot: "rgba(255,255,255,.32)", engrave: "rgba(255,255,255,.55)",
    lcd: "#050607",
  },
  grey: {
    label: "Aluminium grey",
    plate: "linear-gradient(160deg,#56606d 0%,#3f4854 55%,#353d48 100%)",
    rim: "#262c34", line: "rgba(10,14,20,.55)", lineHi: "rgba(255,255,255,.09)",
    text: "rgba(236,240,245,.82)", dot: "rgba(255,255,255,.38)", engrave: "rgba(255,255,255,.6)",
    lcd: "#07090c",
  },
  gold: {
    light: true,
    label: "Champagne gold",
    plate: "linear-gradient(160deg,#e6d4b3 0%,#cdb48a 55%,#bc9f73 100%)",
    rim: "#8f7650", line: "rgba(92,70,38,.38)", lineHi: "rgba(255,255,255,.28)",
    text: "rgba(62,47,26,.82)", dot: "rgba(70,52,28,.42)", engrave: "rgba(62,47,26,.7)",
    lcd: "#0b0906",
  },
  white: {
    light: true,
    label: "White glass",
    plate: "linear-gradient(160deg,#ffffff 0%,#f1f1ef 55%,#e6e6e3 100%)",
    rim: "#c9c9c5", line: "rgba(0,0,0,.13)", lineHi: "rgba(255,255,255,.9)",
    text: "rgba(60,63,68,.8)", dot: "rgba(0,0,0,.28)", engrave: "rgba(50,52,56,.62)",
    lcd: "#0a0b0c",
  },
  silver: {
    light: true,
    label: "Brushed silver",
    plate: "repeating-linear-gradient(90deg,rgba(255,255,255,.06) 0 1px,rgba(0,0,0,.03) 1px 3px),linear-gradient(160deg,#eef0f2 0%,#cdd1d6 55%,#b7bcc3 100%)",
    rim: "#8e949c", line: "rgba(40,46,54,.28)", lineHi: "rgba(255,255,255,.6)",
    text: "rgba(42,47,54,.82)", dot: "rgba(30,36,44,.36)", engrave: "rgba(40,45,52,.68)",
    lcd: "#07080a",
  },
};

export const INDICATORS = {
  blue: { label: "Ice blue", color: "#4cc3ff" },
  white: { label: "Warm white", color: "#fff4dc" },
  amber: { label: "Amber", color: "#ffb03b" },
  green: { label: "Green", color: "#4fe08b" },
};

const KEY_DOMAINS = ["switch", "light", "fan", "input_boolean", "scene", "script", "button", "lock"];

/* ------------------------------------------------------------------ data */

const ON_STATES = new Set(["on", "open", "opening", "unlocked", "playing"]);
const isOn = (st) => !!st && ON_STATES.has(st.state);
const unavailable = (st) => !st || st.state === "unavailable";
const domainOf = (id) => id.split(".")[0];
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

/** Natural sort that understands "Switch 2" < "Switch 10" and Hawaii Local data points. */
function sortKey(hass, id) {
  const dp = hass.states[id]?.attributes?.dp;
  const n = dp !== undefined && /^\d+$/.test(String(dp)) ? Number(dp) : Infinity;
  return [n, id];
}
function naturalSort(hass, ids) {
  const coll = new Intl.Collator(undefined, { numeric: true });
  return [...ids].sort((a, b) => {
    const [na, ia] = sortKey(hass, a);
    const [nb, ib] = sortKey(hass, b);
    return na !== nb ? na - nb : coll.compare(ia, ib);
  });
}

/** All usable entities of the device that `entity` (or `device`) belongs to. */
export function deviceEntities(hass, { entity, device }, domains) {
  const deviceId = device || hass.entities?.[entity]?.device_id;
  if (!deviceId) return entity && hass.states[entity] ? [entity] : [];
  const ids = Object.values(hass.entities || {})
    .filter(
      (e) =>
        e.device_id === deviceId &&
        domains.includes(domainOf(e.entity_id)) &&
        !e.hidden &&
        !e.entity_category &&
        hass.states[e.entity_id],
    )
    .map((e) => e.entity_id);
  return naturalSort(hass, ids);
}

/** The keys a card shows: explicit list, else the whole device of `entity`. */
export function resolveKeys(hass, config, domains = KEY_DOMAINS) {
  let ids;
  if (Array.isArray(config.entities) && config.entities.length) {
    ids = config.entities.map((e) => (typeof e === "string" ? e : e.entity)).filter(Boolean);
  } else {
    ids = deviceEntities(hass, config, domains);
  }
  const exclude = new Set(config.exclude || []);
  return ids.filter((id) => !exclude.has(id));
}

/** Short key label: user name, else friendly name without the device name. */
export function keyName(hass, config, id) {
  const fromList = (config.entities || []).find((e) => typeof e === "object" && e.entity === id)?.name;
  if (fromList) return fromList;
  if (config.names && config.names[id]) return config.names[id];
  const reg = hass.entities?.[id];
  const st = hass.states[id];
  let name = st?.attributes?.friendly_name || id.split(".")[1];
  const dev = reg?.device_id ? hass.devices?.[reg.device_id] : null;
  const devName = dev?.name_by_user || dev?.name;
  if (devName && name.toLowerCase().startsWith(devName.toLowerCase() + " ")) {
    name = name.slice(devName.length + 1);
  }
  return name;
}

function deviceTitle(hass, config, ids) {
  if (config.name !== undefined) return config.name;
  const first = config.entity || ids[0];
  const dev = first ? hass.devices?.[hass.entities?.[first]?.device_id] : null;
  return dev?.name_by_user || dev?.name || "";
}

function toggleCall(hass, id) {
  const domain = domainOf(id);
  const st = hass.states[id];
  if (domain === "scene" || domain === "script") return hass.callService(domain, "turn_on", { entity_id: id });
  if (domain === "button") return hass.callService("button", "press", { entity_id: id });
  if (domain === "lock") return hass.callService("lock", st?.state === "locked" ? "unlock" : "lock", { entity_id: id });
  return hass.callService("homeassistant", "toggle", { entity_id: id });
}

/* ------------------------------------------------------------------ layout */

/**
 * Where each key goes. Mirrors the real panels: "columns" are vertical bars
 * (a bar holds two keys, top and bottom, once there are more than 3 keys),
 * "rows" are horizontal bars (two keys each, left and right), "grid" shows
 * every split. Returns {cols, rows, cells:[{c,r}], module, lines:{v:[],h:[]}}.
 */
export function panelLayout(n, layout = "auto", columns = null) {
  n = Math.max(1, Math.min(n, 12));
  let mode = layout === "auto" ? (n === 4 || n > 8 ? "grid" : "columns") : layout;
  if (n > 10 && mode === "columns") mode = "grid"; // no real panel has more than 5 bars
  const force = Number(columns) > 0 ? Math.min(Number(columns), n, 6) : null;
  let cols;
  let rows;
  if (mode === "rows") {
    cols = force || (n <= 3 ? 1 : 2);
    rows = Math.ceil(n / cols);
  } else if (mode === "grid") {
    const best = { 1: 1, 2: 2, 3: 3, 4: 2, 5: 3, 6: 3, 7: 4, 8: 4, 9: 3, 10: 5, 11: 4, 12: 4 };
    cols = force || best[n];
    rows = Math.ceil(n / cols);
  } else {
    cols = force || (n <= 3 ? n : Math.ceil(n / 2));
    rows = Math.ceil(n / cols);
  }
  // Fill order: bars top-to-bottom for "columns", left-to-right otherwise. A gap
  // left at the end is filled by stretching the last key (like a single tall key).
  const cells = [];
  const spare = cols * rows - n;
  if (mode === "columns") {
    for (let c = 0; c < cols; c++) for (let r = 0; r < rows; r++) cells.push({ c, r, cs: 1, rs: 1 });
    cells.length = n;
    if (spare) cells[n - 1].rs = rows - cells[n - 1].r;
    // if a whole bar would be left over, spread it: stretch the last key across it too
    const last = cells[n - 1];
    if (last.c < cols - 1) last.cs = cols - last.c;
  } else {
    for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) cells.push({ c, r, cs: 1, rs: 1 });
    cells.length = n;
    if (spare) cells[n - 1].cs = cols - cells[n - 1].c;
  }
  const module = cols >= 5 ? 8 : cols === 4 ? 4 : 2;
  // taller than a real 2-row panel: keep keys roughly square
  const ratio = rows > 2 && module > 2 ? (MODULE_RATIO[module] * 2) / rows : MODULE_RATIO[module];
  // grooves between neighbouring keys (columns: only between bars; rows: only between rows)
  const vs = new Map();
  const hs = new Map();
  for (const k of cells) {
    const right = k.c + k.cs;
    if (right < cols && !(mode === "rows" && cols > 1)) {
      for (let r = k.r; r < k.r + k.rs; r++) vs.set(`${right}:${r}`, { x: right, y1: r, y2: r + 1 });
    }
    const bottom = k.r + k.rs;
    if (bottom < rows && !(mode === "columns" && rows > 1)) {
      for (let c = k.c; c < k.c + k.cs; c++) hs.set(`${bottom}:${c}`, { y: bottom, x1: c, x2: c + 1 });
    }
  }
  return { mode, cols, rows, cells, module, ratio, segs: { v: [...vs.values()], h: [...hs.values()] } };
}

const MODULE_RATIO = { 2: 1, 4: 135 / 75, 8: 230 / 79 };
const MODULE_WIDTH = { 2: 300, 4: 470, 8: 640 };

/* ------------------------------------------------------------------ drawing */

const SEGMENTS = {
  0: "abcdef", 1: "bc", 2: "abdeg", 3: "abcdg", 4: "bcfg", 5: "acdfg",
  6: "acdefg", 7: "abc", 8: "abcdefg", 9: "abcdfg", "-": "g", " ": "",
};
const SEG_PATHS = {
  a: "M4 1h12l-2.4 3.2H6.4z", b: "M17 2.2v13.4l-3 2.2-.6-.4V5.4z", c: "M17 20.4v13.4l-3.6-3.2V18.6l.6-.4z",
  d: "M4 35h12l-2.4-3.2H6.4z", e: "M3 20.4v13.4l3.6-3.2V18.6L6 18.2z", f: "M3 2.2v13.4l3 2.2.6-.4V5.4z",
  g: "M4.6 18l2-1.6h6.8l2 1.6-2 1.6H6.6z",
};

/** Seven-segment digits like the knob panel's display. */
export function sevenSegment(text, on, off) {
  const chars = String(text).split("");
  const w = 20;
  const body = chars
    .map((ch, i) => {
      const lit = SEGMENTS[ch] ?? "";
      return `<g transform="translate(${i * (w + 3)},0)">${Object.entries(SEG_PATHS)
        .map(([s, d]) => `<path d="${d}" fill="${lit.includes(s) ? on : off}"/>`)
        .join("")}</g>`;
    })
    .join("");
  return `<svg class="seg" viewBox="0 0 ${chars.length * (w + 3) - 3} 36" aria-hidden="true">${body}</svg>`;
}

const ICONS = {
  open: '<path d="M6 15l6-6 6 6" />',
  close: '<path d="M6 9l6 6 6-6" />',
  pause: '<path d="M9.5 7v10M14.5 7v10" />',
  power: '<path d="M12 4v7" /><path d="M7.2 7.2a7 7 0 1 0 9.6 0" />',
  bulb: '<path d="M9.2 17.5h5.6M10 20.5h4" /><path d="M12 3.5a5.8 5.8 0 0 0-3.4 10.5c.6.5 1 1.1 1 1.9v.6h4.8V16c0-.8.4-1.4 1-1.9A5.8 5.8 0 0 0 12 3.5z" /><path d="M2.8 9.5h1.4M19.8 9.5h1.4M5.2 3.4l1 1M18.8 3.4l-1 1" />',
};
const icon = (name) =>
  `<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${ICONS[name]}</svg>`;

const SOCKET_SVG = `<svg class="socket" viewBox="0 0 100 100" aria-hidden="true">
  <circle cx="50" cy="50" r="40" class="sk-ring"/>
  <circle cx="50" cy="27" r="7.5" class="sk-hole"/>
  <circle cx="31" cy="60" r="5.6" class="sk-hole"/><circle cx="69" cy="60" r="5.6" class="sk-hole"/>
  <rect x="21" y="40" width="4.6" height="13" rx="1.6" class="sk-hole"/><rect x="74.4" y="40" width="4.6" height="13" rx="1.6" class="sk-hole"/>
  <circle cx="40" cy="74" r="3" class="sk-hole"/><circle cx="60" cy="74" r="3" class="sk-hole"/>
</svg>`;

/* ------------------------------------------------------------------ styles */

const STYLE = `
:host { display:block; }
ha-card { display:block; padding:16px; background:var(--hl-card-bg, var(--ha-card-background, var(--card-background-color))); box-sizing:border-box; }
ha-card.bare { background:none; box-shadow:none; border:none; padding:6px 0; }
.wrap { display:flex; flex-direction:column; align-items:center; gap:10px; }
.title { font: 500 13px/1.2 var(--ha-font-family-body, system-ui); letter-spacing:.06em; text-transform:uppercase; color:var(--secondary-text-color); text-align:center; }
.plate { position:relative; width:100%; container-type:inline-size; border-radius:var(--hl-radius,7px); background:var(--hl-plate); box-shadow:
  0 0 0 1px var(--hl-rim), 0 1px 0 1px rgba(255,255,255,.04), 0 10px 24px -8px rgba(0,0,0,.55), 0 2px 6px rgba(0,0,0,.25);
  overflow:hidden; user-select:none; -webkit-user-select:none; -webkit-tap-highlight-color:transparent; touch-action:manipulation; }
.plate::after { content:""; position:absolute; inset:0; pointer-events:none; border-radius:inherit;
  background:linear-gradient(155deg, rgba(255,255,255,.16) 0%, rgba(255,255,255,.04) 28%, transparent 46%),
             radial-gradient(120% 60% at 50% 120%, rgba(0,0,0,.18), transparent 60%); }
.grid { position:absolute; inset:0; display:grid; }
.vline, .hline { position:absolute; pointer-events:none; z-index:2; }
.vline { top:0; bottom:0; width:1px; background:var(--hl-line); box-shadow:1px 0 0 var(--hl-line-hi); }
.hline { left:0; right:0; height:1px; background:var(--hl-line); box-shadow:0 1px 0 var(--hl-line-hi); }
.key { position:relative; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:9px;
  cursor:pointer; outline:none; transition:transform .12s ease, background .25s ease; }
.key:focus-visible { box-shadow: inset 0 0 0 2px var(--hl-ind); }
.key.pressed { transform:scale(.97); background:rgba(255,255,255,.035); }
.key.on { background: radial-gradient(70% 60% at 50% 45%, color-mix(in srgb, var(--hl-ind) 12%, transparent), transparent 70%); }
.key.off-line { opacity:.42; cursor:default; }
.dot { width:5px; height:5px; border-radius:50%; background:var(--hl-dot); transition: all .25s ease; flex:none; }
.key.on .dot { background:var(--hl-ind); box-shadow:0 0 6px 1px var(--hl-ind), 0 0 14px 2px color-mix(in srgb, var(--hl-ind) 55%, transparent); }
.label { font: 500 clamp(7.5px, calc(100cqw / var(--hl-cols, 3) / 9.5), 11px)/1.25 var(--ha-font-family-body, system-ui); letter-spacing:.09em; text-transform:uppercase;
  color:var(--hl-text); text-align:center; max-width:88%; overflow:hidden; text-overflow:ellipsis; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; }
.key.on .label { color: var(--hl-on-text); }
.ico { width:22px; height:22px; color:var(--hl-engrave); }
.key.on .ico { color:var(--hl-ind); filter: drop-shadow(0 0 4px color-mix(in srgb, var(--hl-ind) 70%, transparent)); }
.ripple { position:absolute; border-radius:50%; pointer-events:none; transform:scale(0); opacity:.35; background:var(--hl-ind);
  animation: hl-ripple .55s ease-out forwards; }
@keyframes hl-ripple { to { transform:scale(1); opacity:0; } }
.socket { width:78%; max-width:150px; }
.sk-ring { fill:rgba(0,0,0,.08); stroke:var(--hl-line); stroke-width:1.2; }
.sk-hole { fill:rgba(0,0,0,.72); stroke:var(--hl-line-hi); stroke-width:.6; }
.key.on .sk-ring { stroke:var(--hl-ind); filter: drop-shadow(0 0 3px var(--hl-ind)); }
.pos { position:absolute; left:14%; right:14%; bottom:11%; height:3px; border-radius:2px; background:var(--hl-dot); opacity:.6; z-index:3; pointer-events:none; }
.pos > i { position:absolute; left:0; top:0; bottom:0; border-radius:2px; background:var(--hl-ind); box-shadow:0 0 6px var(--hl-ind); }
.corner { position:absolute; width:4px; height:4px; border-radius:50%; background:var(--hl-dot); }
.knob { position:absolute; left:50%; top:50%; transform:translate(-50%,-50%); width:var(--hl-knob,64%); aspect-ratio:1; border-radius:50%;
  background: radial-gradient(circle at 50% 38%, #1c1f24 0%, var(--hl-lcd) 70%); box-shadow: 0 0 0 2px rgba(0,0,0,.55), 0 0 0 3px rgba(255,255,255,.06), inset 0 2px 10px rgba(0,0,0,.9), 0 6px 18px rgba(0,0,0,.45);
  touch-action:none; cursor:grab; z-index:4; }
.knob:active { cursor:grabbing; }
.knob svg.ring { position:absolute; inset:0; width:100%; height:100%; overflow:visible; }
.knob .track { fill:none; stroke:rgba(255,255,255,.08); stroke-width:5; stroke-linecap:round; }
.knob .arc { fill:none; stroke:var(--hl-ind); stroke-width:5; stroke-linecap:round; filter: drop-shadow(0 0 4px var(--hl-ind)); transition: stroke-dashoffset .2s ease; }
.knob.off .arc { stroke:rgba(255,255,255,.18); filter:none; }
.knob .thumb { fill:#fff; filter: drop-shadow(0 0 3px var(--hl-ind)); }
.knob.off .thumb { fill:rgba(255,255,255,.35); filter:none; }
.knob .readout { position:absolute; inset:24%; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:5%; pointer-events:none; }
.knob .seg { width:62%; }
.knob .unit { font: 600 9px/1 var(--ha-font-family-body, system-ui); letter-spacing:.14em; color: color-mix(in srgb, var(--hl-ind) 80%, #fff); text-transform:uppercase; }
.knob.off .unit { color: rgba(255,255,255,.35); }
.knob .center { position:absolute; inset:30%; border-radius:50%; cursor:pointer; }
.knob.glass { background:
    radial-gradient(circle, rgba(255,255,255,.085) 0 1.1px, transparent 1.7px) 50% 50% / 6.4% 6.4%,
    radial-gradient(circle at 50% 32%, #16181c 0%, var(--hl-lcd) 72%);
  box-shadow: 0 0 0 1.5px rgba(0,0,0,.65), 0 0 0 3px rgba(255,255,255,.07), inset 0 4px 16px rgba(0,0,0,.9), 0 10px 26px -6px rgba(0,0,0,.6); }
.knob.glass::after { content:""; position:absolute; inset:0; border-radius:50%; pointer-events:none;
  background: linear-gradient(160deg, rgba(255,255,255,.18) 0%, rgba(255,255,255,.03) 30%, transparent 48%); }
.knob.glass .track { stroke-width:2.4; stroke:rgba(255,255,255,.07); }
.knob.glass .arc { stroke-width:2.4; }
.knob.glass .halo { fill:none; stroke:var(--hl-ind); stroke-width:1.1; opacity:.9; filter: drop-shadow(0 0 2px var(--hl-ind)); }
.knob.glass.off .halo { opacity:.25; filter:none; }
.knob.glass .readout { flex-direction:row; gap:4%; inset:26%; }
.knob.glass .seg { width:66%; }
.knob.glass .pct { font: 600 11px/1 var(--ha-font-family-body, system-ui); color:var(--hl-ind); align-self:center; opacity:.95; }
.knob.glass.off .pct { color:rgba(255,255,255,.35); }
.ck { position:absolute; width:50%; height:50%; box-sizing:border-box; padding:8.5%; display:flex; flex-direction:row; z-index:3; }
.ck .cklabel { font: 700 clamp(10px, 5.2cqw, 17px)/1 var(--ha-font-family-body, system-ui); letter-spacing:.01em; white-space:nowrap;
  color: color-mix(in srgb, var(--hl-label) 78%, transparent); text-shadow: 0 0 4px color-mix(in srgb, var(--hl-label) 35%, transparent); transition: all .25s ease; }
.ck .cklabel.name { font-size: clamp(8px, 3.4cqw, 12px); letter-spacing:.06em; text-transform:uppercase; white-space:normal; max-width:70%; line-height:1.2; }
.ck.on .cklabel { color: var(--hl-label); text-shadow: 0 0 6px var(--hl-label), 0 0 14px color-mix(in srgb, var(--hl-label) 60%, transparent); }
.ck .ico { width:clamp(18px, 8cqw, 28px); height:auto; color: color-mix(in srgb, var(--hl-ind) 70%, transparent); }
.ck.on .ico { color: var(--hl-ind); filter: drop-shadow(0 0 5px var(--hl-ind)); }
.ck.on { background:none; }
.scenes { position:absolute; left:0; right:0; bottom:7%; display:flex; justify-content:center; gap:22%; z-index:5; }
.scene { font: 600 9px/1 var(--ha-font-family-body, system-ui); letter-spacing:.12em; color:var(--hl-text); padding:6px 8px; cursor:pointer; border-radius:6px; text-transform:uppercase; }
.scene.on { color:var(--hl-ind); text-shadow:0 0 6px var(--hl-ind); }
.empty { padding:18px; text-align:center; color:var(--secondary-text-color); font: 14px var(--ha-font-family-body, system-ui); }
`;

/* ------------------------------------------------------------------ base card */

class HawaiiBaseCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._sig = "";
  }

  setConfig(config) {
    if (!config) throw new Error("Invalid configuration");
    this._config = { finish: "black", indicator: "blue", show_names: true, background: true, ...config };
    this._sig = "";
    if (this._hass) this._update();
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  get hass() {
    return this._hass;
  }

  /** Entities whose state changes require a re-render. */
  _watched() {
    return [];
  }

  _update() {
    if (!this._hass || !this._config || this._dragging) return;
    const ids = this._watched();
    const sig = JSON.stringify([
      this._config,
      ids.map((id) => {
        const s = this._hass.states[id];
        return s ? [s.state, s.attributes.brightness, s.attributes.current_position, s.attributes.friendly_name] : null;
      }),
    ]);
    if (sig === this._sig) return;
    this._sig = sig;
    this._render();
  }

  _vars(extra = "") {
    const f = FINISHES[this._config.finish] || FINISHES.black;
    const ind = (INDICATORS[this._config.indicator] || {}).color || this._config.indicator || INDICATORS.blue.color;
    const onText = f.light ? f.text.replace(/[\d.]+\)$/, "1)") : `color-mix(in srgb, ${f.text} 65%, ${ind})`;
    const baseLabel = (INDICATORS[this._config.label_color] || {}).color || this._config.label_color || INDICATORS.amber.color;
    const label = f.light ? `color-mix(in srgb, ${baseLabel} 62%, #2a1600)` : baseLabel; // stays readable on light plates
    return `--hl-label:${label};--hl-on-text:${onText};--hl-plate:${f.plate};--hl-rim:${f.rim};--hl-line:${f.line};--hl-line-hi:${f.lineHi};--hl-text:${f.text};--hl-dot:${f.dot};--hl-engrave:${f.engrave};--hl-lcd:${f.lcd};--hl-ind:${ind};${extra}`;
  }

  _frame(inner, module = 2, ratio = null, cols = 3) {
    const c = this._config;
    const title = this._title();
    const width = MODULE_WIDTH[module];
    this.shadowRoot.innerHTML = `<style>${STYLE}</style>
      <ha-card class="${c.background === false ? "bare" : ""}">
        <div class="wrap" style="${this._vars()}">
          <div class="plate" style="max-width:${width}px;aspect-ratio:${ratio || MODULE_RATIO[module]};--hl-cols:${cols}">${inner}</div>
          ${title ? `<div class="title">${esc(title)}</div>` : ""}
        </div>
      </ha-card>`;
    this._bind();
  }

  _title() {
    return "";
  }

  _empty(msg) {
    this.shadowRoot.innerHTML = `<style>${STYLE}</style><ha-card><div class="empty">${esc(msg)}</div></ha-card>`;
  }

  /** Tap = action, long press = more info; with ripple and haptic feedback. */
  _bind() {
    this.shadowRoot.querySelectorAll("[data-act]").forEach((el) => {
      let timer = null;
      let long = false;
      const start = (ev) => {
        if (el.classList.contains("off-line")) return;
        long = false;
        el.classList.add("pressed");
        this._ripple(el, ev);
        timer = setTimeout(() => {
          long = true;
          el.classList.remove("pressed");
          if (el.dataset.entity) this._moreInfo(el.dataset.entity);
        }, 550);
      };
      const end = (ev) => {
        clearTimeout(timer);
        el.classList.remove("pressed");
        if (ev.type === "pointerup" && !long && !el.classList.contains("off-line")) this._act(el);
      };
      el.addEventListener("pointerdown", start);
      el.addEventListener("pointerup", end);
      el.addEventListener("pointerleave", () => {
        clearTimeout(timer);
        el.classList.remove("pressed");
      });
      el.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          this._act(el);
        }
      });
      el.addEventListener("contextmenu", (ev) => ev.preventDefault());
    });
  }

  _ripple(el, ev) {
    const r = el.getBoundingClientRect();
    const size = Math.max(r.width, r.height) * 1.4;
    const dot = document.createElement("span");
    dot.className = "ripple";
    dot.style.cssText = `width:${size}px;height:${size}px;left:${(ev.clientX ?? r.left + r.width / 2) - r.left - size / 2}px;top:${(ev.clientY ?? r.top + r.height / 2) - r.top - size / 2}px`;
    el.appendChild(dot);
    setTimeout(() => dot.remove(), 600);
  }

  _act(el) {
    this._haptic();
    const { act, entity } = el.dataset;
    if (act === "toggle") toggleCall(this._hass, entity);
    else if (act === "preset") this._setLevel(entity, Number(el.dataset.pct));
    else if (act === "cover") this._hass.callService("cover", el.dataset.service, { entity_id: entity });
  }

  _haptic() {
    this.dispatchEvent(new CustomEvent("haptic", { detail: "light", bubbles: true, composed: true }));
  }

  _moreInfo(entityId) {
    this.dispatchEvent(new CustomEvent("hass-more-info", { detail: { entityId }, bubbles: true, composed: true }));
  }

  _keyHtml(id, { cls = "", inner = null, act = "toggle", extra = "" } = {}) {
    const st = this._hass.states[id];
    const name = this._config.show_names === false ? "" : keyName(this._hass, this._config, id);
    const state = unavailable(st) ? "off-line" : isOn(st) ? "on" : "";
    return `<div class="key ${state} ${cls}" role="button" tabindex="0" aria-label="${esc(name || id)}"
      aria-pressed="${isOn(st)}" data-act="${act}" data-entity="${esc(id)}" ${extra}>
      ${inner ?? `<span class="dot"></span>${name ? `<span class="label">${esc(name)}</span>` : ""}`}
    </div>`;
  }

  _lines(layout, origin = { left: 0, top: 0, width: 100, height: 100 }) {
    const { cols, rows } = layout;
    const X = (x) => origin.left + (origin.width * x) / cols;
    const Y = (y) => origin.top + (origin.height * y) / rows;
    const segs = layout.segs || {
      v: layout.lines.v.map((x) => ({ x, y1: 0, y2: rows })),
      h: layout.lines.h.map((y) => ({ y, x1: 0, x2: cols })),
    };
    const v = segs.v.map((g) => `<span class="vline" style="left:${X(g.x)}%;top:${Y(g.y1)}%;bottom:${100 - Y(g.y2)}%"></span>`);
    const h = segs.h.map((g) => `<span class="hline" style="top:${Y(g.y)}%;left:${X(g.x1)}%;right:${100 - X(g.x2)}%"></span>`);
    return v.join("") + h.join("");
  }

  getCardSize() {
    return 4;
  }
}

/* ------------------------------------------------------------------ key switch */

const FINISH_OPTIONS = Object.entries(FINISHES).map(([value, f]) => ({ value, label: f.label }));
const INDICATOR_OPTIONS = Object.entries(INDICATORS).map(([value, f]) => ({ value, label: f.label }));
const LOOK_SCHEMA = [
  {
    type: "grid",
    name: "",
    schema: [
      { name: "finish", selector: { select: { mode: "dropdown", options: FINISH_OPTIONS } } },
      { name: "indicator", selector: { select: { mode: "dropdown", options: INDICATOR_OPTIONS } } },
    ],
  },
  {
    type: "grid",
    name: "",
    schema: [
      { name: "show_names", selector: { boolean: {} } },
      { name: "background", selector: { boolean: {} } },
    ],
  },
  { name: "name", selector: { text: {} } },
];
const LABELS = {
  entity: "Switch (pick any one of its entities)",
  entities: "Keys (optional – leave empty to show every key of the switch)",
  exclude: "Hide these keys",
  layout: "Key layout",
  key_count: "Number of keys (empty = all)",
  columns: "Columns (empty = automatic)",
  finish: "Finish",
  indicator: "Indicator light",
  show_names: "Show key names",
  background: "Card background",
  name: "Caption (empty = switch name)",
  socket: "Socket (optional smart socket entity)",
  scenes: "Scene keys (up to 2)",
  keys: "Corner keys (up to 4)",
  knob_entity: "Dimmable light",
};
const computeLabel = (s) => LABELS[s.name] ?? s.name;

class HawaiiKeySwitchCard extends HawaiiBaseCard {
  _keys() {
    return resolveKeys(this._hass, this._config).slice(0, Number(this._config.key_count) || this._config.max_keys || 12);
  }

  _watched() {
    return this._keys();
  }

  _title() {
    return deviceTitle(this._hass, this._config, this._keys());
  }

  _render() {
    const ids = this._keys();
    if (!ids.length) return this._empty("Pick a switch: choose any one of its entities.");
    const layout = panelLayout(ids.length, this._config.layout || "auto", this._config.columns);
    const cells = ids
      .map((id, i) => {
        const { c, r, cs, rs } = layout.cells[i];
        return this._keyHtml(id, { extra: `style="grid-column:${c + 1} / span ${cs};grid-row:${r + 1} / span ${rs}"` });
      })
      .join("");
    this._frame(
      `<div class="grid" style="grid-template-columns:repeat(${layout.cols},1fr);grid-template-rows:repeat(${layout.rows},1fr)">${cells}</div>${this._lines(layout)}`,
      this._config.module || layout.module,
      this._config.module ? null : layout.ratio,
      layout.cols,
    );
  }

  getGridOptions() {
    const n = this._hass && this._config ? this._keys().length : 3;
    const wide = panelLayout(n, this._config?.layout, this._config?.columns).module > 2;
    return { columns: wide ? 12 : 6, min_columns: 4, rows: "auto" };
  }

  static getConfigElement() {
    const el = document.createElement("hawaii-keys-editor");
    el.kind = "switch";
    return el;
  }

  static getStubConfig(hass) {
    return { entity: pickEntity(hass, ["switch", "light"]) || "", layout: "auto", finish: "black", indicator: "blue" };
  }
}

/* ------------------------------------------------------------------ keys + socket */

class HawaiiKeySocketCard extends HawaiiKeySwitchCard {
  _keys() {
    return resolveKeys(this._hass, this._config)
      .filter((id) => id !== this._config.socket)
      .slice(0, Math.min(Number(this._config.key_count) || 6, 6));
  }

  _watched() {
    return [...this._keys(), this._config.socket].filter(Boolean);
  }

  _render() {
    const ids = this._keys();
    if (!ids.length) return this._empty("Pick a switch: choose any one of its entities.");
    // keys take the left part (like the real 4 / 6 key + socket panels), socket the right
    const keyArea = ids.length > 4 ? 62 : 50;
    const layout = panelLayout(ids.length, this._config.layout || (ids.length === 4 ? "grid" : "columns"), this._config.columns);
    const cells = ids
      .map((id, i) => {
        const { c, r, cs, rs } = layout.cells[i];
        return this._keyHtml(id, { extra: `style="grid-column:${c + 1} / span ${cs};grid-row:${r + 1} / span ${rs}"` });
      })
      .join("");
    const sock = this._config.socket;
    const socketHtml = sock
      ? this._keyHtml(sock, { inner: SOCKET_SVG, extra: 'style="height:100%"' })
      : `<div class="key" style="height:100%;cursor:default">${SOCKET_SVG}</div>`;
    this._frame(
      `<div class="grid" style="right:${100 - keyArea}%;grid-template-columns:repeat(${layout.cols},1fr);grid-template-rows:repeat(${layout.rows},1fr)">${cells}</div>
       ${this._lines(layout, { left: 0, top: 0, width: keyArea, height: 100 })}
       <span class="vline" style="left:${keyArea}%"></span>
       <div class="grid" style="left:${keyArea}%">${socketHtml}</div>`,
      4,
    );
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: "auto" };
  }

  static getConfigElement() {
    const el = document.createElement("hawaii-keys-editor");
    el.kind = "socket";
    return el;
  }
}

/* ------------------------------------------------------------------ curtain */

class HawaiiCurtainSwitchCard extends HawaiiBaseCard {
  _covers() {
    return resolveKeys(this._hass, this._config, ["cover"]).filter((id) => domainOf(id) === "cover").slice(0, 2);
  }

  _watched() {
    return this._covers();
  }

  _title() {
    return deviceTitle(this._hass, this._config, this._covers());
  }

  _render() {
    const covers = this._covers();
    if (!covers.length) return this._empty("Pick a curtain (cover entity).");
    const vertical = (this._config.layout || "rows") === "columns";
    const groups = covers.map((id, gi) => {
      const st = this._hass.states[id];
      const pos = st?.attributes?.current_position;
      const moving = st?.state === "opening" ? "open" : st?.state === "closing" ? "close" : null;
      const name = covers.length > 1 && this._config.show_names !== false ? keyName(this._hass, this._config, id) : "";
      const keys = [
        ["open", "open_cover", "Open"],
        ["pause", "stop_cover", "Pause"],
        ["close", "close_cover", "Close"],
      ]
        .map(([ico, service, label], i) => {
          const lit = moving === ico;
          const cell = vertical ? `grid-column:${i + 1};grid-row:1` : `grid-column:1;grid-row:${i + 1}`;
          const showLabel = this._config.show_names !== false && !vertical;
          return `<div class="key ${unavailable(st) ? "off-line" : lit ? "on" : ""}" role="button" tabindex="0"
            aria-label="${esc(label)} ${esc(name)}" data-act="cover" data-service="${service}" data-entity="${esc(id)}"
            style="${cell};flex-direction:${vertical ? "column" : "row"};gap:${vertical ? 8 : 10}px">
            ${icon(ico)}${showLabel ? `<span class="label">${esc(i === 1 && name ? name : label)}</span>` : ""}
          </div>`;
        })
        .join("");
      const posBar =
        typeof pos === "number" ? `<div class="pos" style="${covers.length > 1 ? `left:${gi * 50 + 7}%;right:${(1 - gi) * 50 + 7}%` : ""}"><i style="width:${pos}%"></i></div>` : "";
      return { keys, posBar };
    });
    const per = 100 / covers.length;
    const grids = groups
      .map(
        (g, gi) =>
          `<div class="grid" style="left:${gi * per}%;right:${100 - (gi + 1) * per}%;grid-template-columns:${vertical ? "repeat(3,1fr)" : "1fr"};grid-template-rows:${vertical ? "1fr" : "repeat(3,1fr)"}">${g.keys}</div>${g.posBar}`,
      )
      .join("");
    const lines = covers
      .map((_, gi) =>
        this._lines(vertical ? { cols: 3, rows: 1, lines: { v: [1, 2], h: [] } } : { cols: 1, rows: 3, lines: { v: [], h: [1, 2] } }, {
          left: gi * per,
          top: 0,
          width: per,
          height: 100,
        }),
      )
      .join("");
    const divider = covers.length > 1 ? `<span class="vline" style="left:50%"></span>` : "";
    this._frame(grids + lines + divider, covers.length > 1 ? 4 : 2);
  }

  getGridOptions() {
    return { columns: this._config && this._hass && this._covers().length > 1 ? 12 : 6, min_columns: 4, rows: "auto" };
  }

  static getConfigForm() {
    return {
      schema: [
        { name: "entity", required: true, selector: { entity: { domain: "cover" } } },
        {
          name: "layout",
          selector: {
            select: {
              mode: "dropdown",
              options: [
                { value: "rows", label: "Three rows (with names)" },
                { value: "columns", label: "Three columns (icons only)" },
              ],
            },
          },
        },
        ...LOOK_SCHEMA,
        { name: "entities", selector: { entity: { multiple: true, domain: "cover" } } },
      ],
      computeLabel: (s) => (s.name === "entities" ? "Curtains (optional – up to 2 for a double curtain switch)" : computeLabel(s)),
    };
  }

  static getStubConfig(hass) {
    return { entity: pickEntity(hass, ["cover"]) || "", finish: "black", indicator: "blue" };
  }
}

/* ------------------------------------------------------------------ knob dimmer */

const ARC_START = 135; // degrees, clockwise from +x
const ARC_SWEEP = 270;

/** Pointer position on the knob -> 0..100 (null in the dead zone at the bottom). */
export function angleToPercent(dx, dy) {
  let deg = (Math.atan2(dy, dx) * 180) / Math.PI; // -180..180, 0 = right, 90 = down
  if (deg < 0) deg += 360;
  let rel = deg - ARC_START;
  if (rel < 0) rel += 360;
  if (rel > ARC_SWEEP) return rel - ARC_SWEEP < (360 - ARC_SWEEP) / 2 ? 100 : 0;
  return Math.round((rel / ARC_SWEEP) * 100);
}

function arcPath(cx, cy, r) {
  const a0 = (ARC_START * Math.PI) / 180;
  const a1 = ((ARC_START + ARC_SWEEP) * Math.PI) / 180;
  const p = (a) => `${(cx + r * Math.cos(a)).toFixed(2)} ${(cy + r * Math.sin(a)).toFixed(2)}`;
  return `M ${p(a0)} A ${r} ${r} 0 1 1 ${p(a1)}`;
}

class HawaiiKnobDimmerCard extends HawaiiBaseCard {
  _light() {
    if (this._config.knob_entity) return this._config.knob_entity;
    const id = this._config.entity;
    if (id && ["light", "fan", "cover"].includes(domainOf(id))) return id;
    return deviceEntities(this._hass, this._config, ["light"])[0] || id;
  }

  _extraKeys() {
    return (this._config.scenes || []).slice(0, 2);
  }

  _watched() {
    return [this._light(), ...this._extraKeys()].filter(Boolean);
  }

  _title() {
    const id = this._light();
    return this._config.name !== undefined ? this._config.name : id ? deviceTitle(this._hass, this._config, [id]) : "";
  }

  _percent(st) {
    if (!st) return 0;
    const d = domainOf(st.entity_id);
    if (d === "cover") return st.attributes.current_position ?? (st.state === "open" ? 100 : 0);
    if (d === "fan") return st.state === "on" ? st.attributes.percentage ?? 100 : 0;
    if (st.state !== "on") return 0;
    const b = st.attributes.brightness;
    return b == null ? 100 : Math.max(1, Math.round((b / 255) * 100));
  }

  _knobHtml(size = "64%", glass = false) {
    const id = this._light();
    const st = this._hass.states[id];
    const on = isOn(st);
    const pct = this._preview ?? this._percent(st);
    const r = 44;
    const len = (Math.PI * 2 * r * ARC_SWEEP) / 360;
    const thumbA = ((ARC_START + (ARC_SWEEP * pct) / 100) * Math.PI) / 180;
    const ind = (INDICATORS[this._config.indicator] || {}).color || INDICATORS.blue.color;
    const digits = on || this._preview != null ? String(pct).padStart(2, " ") : "--";
    const readout = glass
      ? `<div class="readout"><span class="pct">%</span>${sevenSegment(digits, on ? ind : "rgba(255,255,255,.55)", "rgba(255,255,255,.045)")}</div>`
      : `<div class="readout">${sevenSegment(digits, on ? ind : "rgba(255,255,255,.55)", "rgba(255,255,255,.05)")}<span class="unit">${domainOf(id || "light.x") === "cover" ? "% open" : "% level"}</span></div>`;
    return `<div class="knob ${glass ? "glass" : ""} ${on || this._preview != null ? "" : "off"} ${unavailable(st) ? "off-line" : ""}" style="--hl-knob:${size}" data-knob="${esc(id)}" data-glass="${glass ? 1 : ""}">
      <svg class="ring" viewBox="0 0 100 100">${glass ? '<circle class="halo" cx="50" cy="50" r="37"/>' : ""}
        <path class="track" d="${arcPath(50, 50, r)}"/>
        <path class="arc" d="${arcPath(50, 50, r)}" stroke-dasharray="${len}" stroke-dashoffset="${len * (1 - pct / 100)}"/>
        <circle class="thumb" cx="${(50 + r * Math.cos(thumbA)).toFixed(2)}" cy="${(50 + r * Math.sin(thumbA)).toFixed(2)}" r="3.2"/>
      </svg>
      ${readout}
      <div class="center" role="button" tabindex="0" aria-label="Toggle ${esc(keyName(this._hass, this._config, id))}" data-act="toggle" data-entity="${esc(id)}"></div>
    </div>`;
  }

  _corners() {
    return [
      [9, 9], [91, 9], [9, 91], [91, 91],
    ]
      .map(([x, y]) => `<span class="corner" style="left:calc(${x}% - 2px);top:calc(${y}% - 2px)"></span>`)
      .join("");
  }

  _scenesHtml() {
    const ids = this._extraKeys();
    if (!ids.length) return "";
    return `<div class="scenes">${ids
      .map((id, i) => {
        const st = this._hass.states[id];
        const label = this._config.names?.[id] || `Sc${i + 1}`;
        return `<span class="scene ${isOn(st) ? "on" : ""}" role="button" tabindex="0" data-act="toggle" data-entity="${esc(id)}">${esc(label)}</span>`;
      })
      .join("")}</div>`;
  }

  _render() {
    if (!this._light()) return this._empty("Pick a dimmable light.");
    this._frame(this._corners() + this._knobHtml() + this._scenesHtml(), 2);
    this._bindKnob();
  }

  _bindKnob() {
    const knob = this.shadowRoot.querySelector("[data-knob]");
    if (!knob || knob.classList.contains("off-line")) return;
    const id = knob.dataset.knob;
    const pctAt = (ev) => {
      const r = knob.getBoundingClientRect();
      return angleToPercent(ev.clientX - (r.left + r.width / 2), ev.clientY - (r.top + r.height / 2));
    };
    const inRing = (ev) => {
      const r = knob.getBoundingClientRect();
      const d = Math.hypot(ev.clientX - (r.left + r.width / 2), ev.clientY - (r.top + r.height / 2));
      return d > r.width * 0.22;
    };
    knob.addEventListener("pointerdown", (ev) => {
      if (!inRing(ev)) return; // centre = toggle (handled by data-act)
      ev.preventDefault();
      knob.setPointerCapture(ev.pointerId);
      this._dragging = true;
      this._preview = pctAt(ev);
      this._redrawKnob();
    });
    knob.addEventListener("pointermove", (ev) => {
      if (!this._dragging) return;
      this._preview = pctAt(ev);
      this._redrawKnob();
    });
    const finish = () => {
      if (!this._dragging) return;
      this._dragging = false;
      const pct = this._preview;
      this._preview = null;
      this._setLevel(id, pct);
      this._sig = "";
    };
    knob.addEventListener("pointerup", finish);
    knob.addEventListener("pointercancel", finish);
    knob.addEventListener(
      "wheel",
      (ev) => {
        ev.preventDefault();
        const base = this._preview ?? this._percent(this._hass.states[id]);
        this._preview = Math.max(0, Math.min(100, base + (ev.deltaY < 0 ? 5 : -5)));
        this._redrawKnob();
        clearTimeout(this._wheelTimer);
        this._wheelTimer = setTimeout(() => {
          const pct = this._preview;
          this._preview = null;
          this._setLevel(id, pct);
          this._sig = "";
        }, 450);
      },
      { passive: false },
    );
  }

  _redrawKnob() {
    const knob = this.shadowRoot.querySelector("[data-knob]");
    if (!knob) return;
    const tmp = document.createElement("div");
    tmp.innerHTML = this._knobHtml(knob.style.getPropertyValue("--hl-knob") || "64%", !!knob.dataset.glass);
    const fresh = tmp.firstElementChild;
    knob.querySelector("svg.ring").replaceWith(fresh.querySelector("svg.ring"));
    knob.querySelector(".readout").replaceWith(fresh.querySelector(".readout"));
    knob.classList.toggle("off", fresh.classList.contains("off"));
  }

  _setLevel(id, pct) {
    if (pct == null || !id) return;
    this._haptic();
    const d = domainOf(id);
    if (d === "cover") this._hass.callService("cover", "set_cover_position", { entity_id: id, position: pct });
    else if (d === "fan")
      pct > 0
        ? this._hass.callService("fan", "set_percentage", { entity_id: id, percentage: pct })
        : this._hass.callService("fan", "turn_off", { entity_id: id });
    else if (pct <= 0) this._hass.callService("light", "turn_off", { entity_id: id });
    else this._hass.callService("light", "turn_on", { entity_id: id, brightness_pct: pct });
  }

  getGridOptions() {
    return { columns: 6, min_columns: 4, rows: "auto" };
  }

  static getConfigForm() {
    return {
      schema: [
        { name: "entity", required: true, selector: { entity: { domain: ["light", "fan", "cover"] } } },
        { name: "scenes", selector: { entity: { multiple: true, domain: ["scene", "script", "switch", "light"] } } },
        ...LOOK_SCHEMA,
      ],
      computeLabel: (s) => (s.name === "entity" ? "Dimmable light (or fan / curtain)" : computeLabel(s)),
    };
  }

  static getStubConfig(hass) {
    return { entity: pickEntity(hass, ["light"]) || "", finish: "black", indicator: "blue" };
  }
}

/* ------------------------------------------------------------------ knob + keys */

/** Corner order: top-left, top-right, bottom-left, bottom-right – as on the real dimmer panel. */
const DEFAULT_PRESETS = ["60%", "100%", "power", "30%"];
const CORNERS = [
  "left:0;top:0;justify-content:flex-start;align-items:flex-start",
  "right:0;top:0;justify-content:flex-end;align-items:flex-start",
  "left:0;bottom:0;justify-content:flex-start;align-items:flex-end",
  "right:0;bottom:0;justify-content:flex-end;align-items:flex-end",
];

/** "30%" / "30" -> 30, "power" / "on/off" -> "power", "light.x" -> entity. */
export function parseCorner(item) {
  const raw = String(item ?? "").trim();
  if (!raw) return null;
  if (raw.includes(".")) return { kind: "entity", id: raw };
  if (/^(power|on\/off|onoff|toggle)$/i.test(raw)) return { kind: "power" };
  const n = parseInt(raw, 10);
  if (!Number.isNaN(n)) return { kind: "preset", pct: Math.max(1, Math.min(100, n)) };
  return null;
}

class HawaiiKnobKeysCard extends HawaiiKnobDimmerCard {
  setConfig(config) {
    super.setConfig({ label_color: "amber", ...config });
  }

  _cornerItems() {
    const c = this._config;
    let items;
    if (c.corner_keys === "keys" || (Array.isArray(c.keys) && c.keys.length && c.corner_keys !== "presets")) {
      let ids = Array.isArray(c.keys) && c.keys.length ? c.keys : null;
      if (!ids) {
        const light = this._light();
        ids = resolveKeys(this._hass, { ...c, entities: [] }).filter((id) => id !== light);
      }
      items = ids.map((id) => ({ kind: "entity", id }));
    } else {
      const list = typeof c.presets === "string" ? c.presets.split(",") : Array.isArray(c.presets) ? c.presets : DEFAULT_PRESETS;
      items = list.map(parseCorner);
    }
    return items.slice(0, 4);
  }

  _watched() {
    return [this._light(), ...this._cornerItems().filter((k) => k && k.kind === "entity").map((k) => k.id)].filter(Boolean);
  }

  _cornerHtml(item, i) {
    if (!item) return "";
    const light = this._light();
    const lst = this._hass.states[light];
    const off = unavailable(lst) ? "off-line" : "";
    if (item.kind === "power") {
      return `<div class="key ck ${isOn(lst) ? "on" : ""} ${off}" role="button" tabindex="0" aria-label="On / off" data-act="toggle" data-entity="${esc(light)}" style="${CORNERS[i]}">${icon("bulb")}</div>`;
    }
    if (item.kind === "preset") {
      const active = isOn(lst) && Math.abs(this._percent(lst) - item.pct) <= 3;
      return `<div class="key ck ${active ? "on" : ""} ${off}" role="button" tabindex="0" aria-label="${item.pct}%" data-act="preset" data-pct="${item.pct}" data-entity="${esc(light)}" style="${CORNERS[i]}"><span class="cklabel">${item.pct}%</span></div>`;
    }
    const st = this._hass.states[item.id];
    const name = keyName(this._hass, this._config, item.id);
    return `<div class="key ck ${isOn(st) ? "on" : ""} ${unavailable(st) ? "off-line" : ""}" role="button" tabindex="0" aria-label="${esc(name)}" data-act="toggle" data-entity="${esc(item.id)}" style="${CORNERS[i]}"><span class="cklabel name" style="text-align:${i % 2 ? "right" : "left"}">${esc(name)}</span></div>`;
  }

  _render() {
    if (!this._light()) return this._empty("Pick a dimmable light.");
    const corners = this._cornerItems().map((k, i) => this._cornerHtml(k, i)).join("");
    const cross = `<span class="vline" style="left:50%"></span><span class="hline" style="top:50%"></span>`;
    this._frame(cross + corners + this._knobHtml("60%", true), 2);
    this._bindKnob();
  }

  static getConfigForm() {
    return {
      schema: [
        { name: "entity", required: true, selector: { entity: { domain: ["light", "fan", "cover"] } } },
        {
          name: "corner_keys",
          selector: {
            select: {
              mode: "dropdown",
              options: [
                { value: "presets", label: "Dimmer keys (on/off and levels)" },
                { value: "keys", label: "Relays or scenes" },
              ],
            },
          },
        },
        { name: "presets", selector: { text: {} } },
        { name: "keys", selector: { entity: { multiple: true, domain: KEY_DOMAINS } } },
        {
          type: "grid",
          name: "",
          schema: [
            { name: "finish", selector: { select: { mode: "dropdown", options: FINISH_OPTIONS } } },
            { name: "indicator", selector: { select: { mode: "dropdown", options: INDICATOR_OPTIONS } } },
          ],
        },
        { name: "label_color", selector: { select: { mode: "dropdown", options: INDICATOR_OPTIONS } } },
        { name: "background", selector: { boolean: {} } },
        { name: "name", selector: { text: {} } },
      ],
      computeLabel: (s) =>
        ({
          entity: "Dimmable light (or fan / curtain)",
          corner_keys: "Corner keys",
          presets: "Dimmer keys, top-left → bottom-right (e.g. 60%, 100%, power, 30%)",
          keys: "Relay / scene keys (up to 4; empty = the switch's other keys)",
          indicator: "Display and on/off colour",
          label_color: "Key label colour",
        })[s.name] ?? computeLabel(s),
    };
  }

  static getStubConfig(hass) {
    return { entity: pickEntity(hass, ["light"]) || "", corner_keys: "presets", finish: "black", indicator: "blue", label_color: "amber" };
  }
}


/* ------------------------------------------------------------------ key editor */

/** General settings of the key cards (the keys themselves are edited row by row). */
function keyCardSchema(kind, custom) {
  return [
    { name: "entity", selector: { entity: { domain: KEY_DOMAINS } } },
    ...(kind === "socket" ? [{ name: "socket", selector: { entity: { domain: ["switch"] } } }] : []),
    {
      name: "layout",
      selector: {
        select: {
          mode: "dropdown",
          options: [
            { value: "auto", label: "Automatic" },
            { value: "columns", label: "Columns (vertical keys)" },
            { value: "rows", label: "Rows (horizontal keys)" },
            { value: "grid", label: "Grid" },
          ],
        },
      },
    },
    {
      type: "grid",
      name: "",
      schema: [
        ...(custom ? [] : [{ name: "key_count", selector: { number: { min: 1, max: 12, step: 1, mode: "box" } } }]),
        { name: "columns", selector: { number: { min: 1, max: 6, step: 1, mode: "box" } } },
      ],
    },
    ...LOOK_SCHEMA,
  ];
}

const SVG = {
  up: "M7 14l5-5 5 5",
  down: "M7 10l5 5 5-5",
  remove: "M7 7l10 10M17 7L7 17",
  add: "M12 6v12M6 12h12",
};
const btnIcon = (d) =>
  `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;

const EDITOR_STYLE = `
:host { display:block; }
.head { display:flex; align-items:baseline; justify-content:space-between; margin:20px 0 4px; }
.head b { font-weight:500; font-size:15px; color:var(--primary-text-color); }
.head span { font-size:12px; color:var(--secondary-text-color); }
.hint { font-size:12px; color:var(--secondary-text-color); margin:0 0 10px; line-height:1.4; }
.row { display:grid; grid-template-columns:24px minmax(0,1fr) minmax(0,38%) auto; gap:6px; align-items:center; margin-bottom:8px; }
.num { width:24px; height:24px; border-radius:50%; display:flex; align-items:center; justify-content:center;
  font-size:12px; font-weight:600; color:var(--text-primary-color, #fff); background:var(--primary-color); }
.row ha-selector { display:block; min-width:0; }
.nm { box-sizing:border-box; width:100%; height:56px; padding:0 12px; font:inherit; font-size:14px; color:var(--primary-text-color);
  background:var(--input-fill-color, var(--secondary-background-color)); border:none; border-bottom:1px solid var(--input-idle-line-color, var(--secondary-text-color));
  border-radius:4px 4px 0 0; outline:none; }
.nm:focus { border-bottom:2px solid var(--primary-color); }
.btns { display:flex; }
.btns button, .actions button { display:inline-flex; align-items:center; justify-content:center; gap:6px; border:none; background:none;
  color:var(--secondary-text-color); cursor:pointer; border-radius:50%; width:32px; height:32px; padding:0; }
.btns button:hover:not([disabled]) { background:rgba(127,127,127,.15); color:var(--primary-text-color); }
.btns button[disabled] { opacity:.3; cursor:default; }
.actions { display:flex; gap:12px; flex-wrap:wrap; margin-top:4px; }
.actions button { width:auto; height:36px; padding:0 14px; border-radius:18px; font:inherit; font-size:14px; font-weight:500;
  color:var(--primary-color); border:1px solid var(--divider-color, rgba(127,127,127,.3)); }
.actions button:hover { background:rgba(127,127,127,.1); }
.empty { font-size:13px; color:var(--secondary-text-color); padding:8px 0; }
`;

class HawaiiKeysEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.kind = "switch";
    this._rows = [];
    this._emitted = "";
  }

  setConfig(config) {
    const json = JSON.stringify(config);
    this._config = { ...config };
    if (json === this._emitted) return; // our own change coming back: keep focus
    this._rows = null;
    this._render();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    this.shadowRoot.querySelectorAll("ha-form, ha-selector").forEach((el) => {
      el.hass = hass;
    });
    if (first && this._config) {
      this._rows = null;
      this._render();
    }
  }

  get _custom() {
    return Array.isArray(this._config?.entities) && this._config.entities.length > 0;
  }

  /** Current keys as editable rows: the custom list, or the switch's keys (automatic). */
  _loadRows() {
    const c = this._config;
    if (this._custom) return c.entities.map((e) => (typeof e === "string" ? { entity: e, name: "" } : { entity: e.entity, name: e.name || "" }));
    if (!this._hass) return [];
    let ids = resolveKeys(this._hass, c);
    if (this.kind === "socket") ids = ids.filter((id) => id !== c.socket).slice(0, 6);
    return ids.slice(0, Number(c.key_count) || 12).map((id) => ({ entity: id, name: "" }));
  }

  _emit(config) {
    this._config = config;
    this._emitted = JSON.stringify(config);
    this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
  }

  /** Save the rows as the card's own key list (positions = row order). */
  _saveRows(rerender = true) {
    const keys = this._rows
      .filter((r) => r.entity)
      .map((r) => (r.name ? { entity: r.entity, name: r.name } : r.entity));
    const config = { ...this._config };
    delete config.exclude;
    delete config.key_count;
    if (keys.length) config.entities = keys;
    else delete config.entities;
    if (!config.entity && keys.length) config.entity = typeof keys[0] === "string" ? keys[0] : keys[0].entity;
    this._emit(config);
    if (rerender) this._render();
  }

  _render() {
    if (!this._config) return;
    if (!this._rows) this._rows = this._loadRows();
    const custom = this._custom;
    const order =
      (this._config.layout || "auto") === "rows" || (this._config.layout || "auto") === "grid"
        ? "left to right, row by row"
        : "top to bottom in each bar, bars left to right";
    this.shadowRoot.innerHTML = `<style>${EDITOR_STYLE}</style>
      <ha-form></ha-form>
      <div class="head"><b>Keys</b><span>${custom ? "Your own keys" : "Automatic – every key of the switch"}</span></div>
      <div class="hint">Each row is one key, in position order (${order}). Change a key to any entity, give it a name, or move it with the arrows.</div>
      <div class="rows">${this._rows.length ? "" : '<div class="empty">No keys yet – pick a switch above or add a key.</div>'}</div>
      <div class="actions">
        <button class="add">${btnIcon(SVG.add)}Add key</button>
        ${custom ? '<button class="reset">Use the whole switch again</button>' : ""}
      </div>`;

    const form = this.shadowRoot.querySelector("ha-form");
    form.hass = this._hass;
    form.data = this._config;
    form.schema = keyCardSchema(this.kind, custom);
    form.computeLabel = computeLabel;
    form.addEventListener("value-changed", (ev) => {
      const next = { ...this._config, ...ev.detail.value };
      for (const k of Object.keys(next)) if (next[k] === undefined || next[k] === "") delete next[k];
      const switchChanged = next.entity !== this._config.entity && !custom;
      const countChanged = next.key_count !== this._config.key_count && !custom;
      this._emit(next);
      if (switchChanged || countChanged) {
        this._rows = null;
        this._render();
      }
    });

    const list = this.shadowRoot.querySelector(".rows");
    this._rows.forEach((row, i) => {
      const el = document.createElement("div");
      el.className = "row";
      el.innerHTML = `<span class="num">${i + 1}</span><span class="pick"></span>
        <input class="nm" placeholder="${esc(row.entity && this._hass ? keyName(this._hass, {}, row.entity) : "Name")}" value="${esc(row.name)}" aria-label="Key ${i + 1} name">
        <span class="btns">
          <button class="up" title="Move up" ${i === 0 ? "disabled" : ""}>${btnIcon(SVG.up)}</button>
          <button class="down" title="Move down" ${i === this._rows.length - 1 ? "disabled" : ""}>${btnIcon(SVG.down)}</button>
          <button class="del" title="Remove key">${btnIcon(SVG.remove)}</button>
        </span>`;
      const picker = document.createElement("ha-selector");
      picker.hass = this._hass;
      picker.selector = { entity: { domain: KEY_DOMAINS } };
      picker.value = row.entity || "";
      picker.required = false;
      picker.addEventListener("value-changed", (ev) => {
        ev.stopPropagation();
        row.entity = ev.detail.value || "";
        row.name = row.name || "";
        this._saveRows(true);
      });
      el.querySelector(".pick").replaceWith(picker);
      el.querySelector(".nm").addEventListener("change", (ev) => {
        row.name = ev.target.value.trim();
        this._saveRows(false);
      });
      const move = (d) => {
        const j = i + d;
        [this._rows[i], this._rows[j]] = [this._rows[j], this._rows[i]];
        this._saveRows(true);
      };
      el.querySelector(".up").addEventListener("click", () => move(-1));
      el.querySelector(".down").addEventListener("click", () => move(1));
      el.querySelector(".del").addEventListener("click", () => {
        this._rows.splice(i, 1);
        this._saveRows(true);
      });
      list.appendChild(el);
    });

    this.shadowRoot.querySelector(".add").addEventListener("click", () => {
      this._rows.push({ entity: "", name: "" });
      this._render(); // saved once a key is picked
      const pickers = this.shadowRoot.querySelectorAll("ha-selector");
      pickers[pickers.length - 1]?.scrollIntoView({ block: "nearest" });
    });
    this.shadowRoot.querySelector(".reset")?.addEventListener("click", () => {
      const config = { ...this._config };
      delete config.entities;
      this._emit(config);
      this._rows = null;
      this._render();
    });
  }
}

if (!customElements.get("hawaii-keys-editor")) customElements.define("hawaii-keys-editor", HawaiiKeysEditor);

/* ------------------------------------------------------------------ register */

function pickEntity(hass, domains) {
  if (!hass) return "";
  const ours = Object.values(hass.entities || {}).filter((e) => e.platform === "hawaii_local");
  const pool = ours.length ? ours.map((e) => e.entity_id) : Object.keys(hass.states);
  return pool.find((id) => domains.includes(domainOf(id))) || "";
}

const CARDS = [
  ["hawaii-key-switch-card", HawaiiKeySwitchCard, "Hawaii Key Switch", "A whole wall switch – 1 to 12 keys in columns, rows or a grid, with indicator lights and five finishes."],
  ["hawaii-key-socket-card", HawaiiKeySocketCard, "Hawaii Keys + Socket", "4 module panel: keys on the left, universal socket on the right."],
  ["hawaii-curtain-switch-card", HawaiiCurtainSwitchCard, "Hawaii Curtain Switch", "Open / pause / close keys with position bar; one or two curtains."],
  ["hawaii-knob-dimmer-card", HawaiiKnobDimmerCard, "Hawaii Knob Dimmer", "Rotary dimmer with a round level display – drag the ring, tap the centre."],
  ["hawaii-knob-keys-card", HawaiiKnobKeysCard, "Hawaii Knob + 4 Keys", "Round dimmer display with four corner keys: on/off, 30%, 60%, 100% – or relays and scenes."],
];

for (const [tag, cls, name, description] of CARDS) {
  if (!customElements.get(tag)) customElements.define(tag, cls);
  window.customCards = window.customCards || [];
  if (!window.customCards.some((c) => c.type === tag)) {
    window.customCards.push({ type: tag, name, description, preview: true, documentationURL: "https://github.com/sariyamon/ha-hawaii-local-integration#cards" });
  }
}

console.info(`%c HAWAII LOCAL CARDS %c ${VERSION} `, "background:#1a1b1e;color:#4cc3ff;font-weight:600", "background:#4cc3ff;color:#1a1b1e");
