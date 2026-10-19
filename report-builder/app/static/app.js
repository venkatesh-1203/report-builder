"use strict";

const STEPS = [
  ["uploaded", "Uploaded"], ["cleaning", "Cleaning"], ["validating", "Checking"], ["stored", "Saved"],
  ["analyzing", "Analyzing"], ["charting", "Charts"], ["summarizing", "Summary"], ["ready", "Ready"],
];
const DONE = new Set(["ready", "rejected", "failed"]);
const $ = (id) => document.getElementById(id);
const keyBox = $("apikey");
keyBox.value = sessionStorage.getItem("apikey") || "";
keyBox.addEventListener("input", () => sessionStorage.setItem("apikey", keyBox.value.trim()));

let pollTimer = null;
let blobUrls = [];

// Build elements safely: text is always set with textContent, never innerHTML.
function el(tag, props = {}, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v; else if (k === "text") node.textContent = v; else node[k] = v;
  }
  kids.flat().forEach((c) => c != null && node.append(c));
  return node;
}

function say(text, kind = "") { const m = $("msg"); m.textContent = text; m.className = "msg " + kind; }

function summarySentences(summary) {
  const text = String(summary || "").trim();
  if (!text) return [];

  const sentences = typeof Intl.Segmenter === "function"
    ? [...new Intl.Segmenter(undefined, { granularity: "sentence" }).segment(text)].map(({ segment }) => segment.trim())
    : text.split(/(?<=[.!?])\s+|\n+/).map((sentence) => sentence.trim());
  return sentences.filter(Boolean).map((sentence) => /[.!?]$/.test(sentence) ? sentence : `${sentence}.`);
}

async function api(path, options = {}) {
  const res = await fetch(path, { ...options, headers: { "X-API-Key": keyBox.value.trim(), ...(options.headers || {}) } });
  if (!res.ok) {
    let message = "Request failed (" + res.status + ").";
    try { const body = await res.json(); message = body.error?.message || body.detail || message; } catch (_) {}
    const err = new Error(message); err.status = res.status; throw err;
  }
  return res;
}
const json = async (path, options) => (await api(path, options)).json();

const fmt = (n) => (n == null ? "-" : Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 }));
const fmtDecimal = (n) => (n == null ? "-" : Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 }));
function money(n, currency) {
  if (n == null) return "-";
  try {
    return new Intl.NumberFormat(undefined, { style: "currency", currency, maximumFractionDigits: 0 }).format(Number(n));
  } catch (_) {
    return `${currency} ${fmt(n)}`;
  }
}

const SVG_NS = "http://www.w3.org/2000/svg";
const CHART_COLORS = ["#234e9d", "#2e8b70", "#d58128", "#8756a5", "#c34856", "#3e859f", "#7a8f35", "#bb6b91"];
function svgNode(tag, attributes = {}, text = "") {
  const node = document.createElementNS(SVG_NS, tag);
  Object.entries(attributes).forEach(([name, value]) => node.setAttribute(name, String(value)));
  if (text) node.textContent = text;
  return node;
}

function chartSvg(title) {
  const svg = svgNode("svg", { viewBox: "0 0 760 320", role: "img", "aria-label": title });
  return svg;
}

function axisChart(items, type, currency) {
  const svg = chartSvg(type === "line" ? "Revenue trend line chart" : "Revenue bar chart");
  const left = 74, right = 16, top = 18, bottom = 58;
  const width = 760 - left - right, height = 320 - top - bottom;
  const values = items.map((item) => Number(item.value) || 0);
  const minValue = Math.min(0, ...values), maxValue = Math.max(1, ...values);
  const y = (value) => top + (maxValue - value) / (maxValue - minValue || 1) * height;
  const zeroY = y(0);
  for (let i = 0; i <= 4; i++) {
    const value = minValue + (maxValue - minValue) * i / 4;
    const lineY = y(value);
    svg.append(svgNode("line", { x1: left, y1: lineY, x2: 744, y2: lineY, class: "chart-gridline" }));
    svg.append(svgNode("text", { x: left - 10, y: lineY + 4, "text-anchor": "end", class: "chart-axis-label" }, money(value, currency)));
  }
  const x = (index) => left + width * (items.length === 1 ? 0.5 : index / (items.length - 1));
  if (type === "line") {
    const points = items.map((item, index) => `${x(index)},${y(Number(item.value) || 0)}`).join(" ");
    svg.append(svgNode("polyline", { points, class: "chart-line" }));
    items.forEach((item, index) => {
      const circle = svgNode("circle", { cx: x(index), cy: y(Number(item.value) || 0), r: 4, class: "chart-point", tabindex: 0 });
      circle.append(svgNode("title", {}, `${item.label}: ${money(item.value, currency)}`));
      svg.append(circle);
    });
  } else {
    const slot = width / Math.max(1, items.length);
    const barWidth = Math.max(2, Math.min(34, slot * 0.7));
    items.forEach((item, index) => {
      const valueY = y(Number(item.value) || 0);
      const rect = svgNode("rect", {
        x: x(index) - barWidth / 2, y: Math.min(valueY, zeroY), width: barWidth,
        height: Math.max(1, Math.abs(zeroY - valueY)), rx: 2, class: "chart-bar", tabindex: 0,
      });
      rect.append(svgNode("title", {}, `${item.label}: ${money(item.value, currency)}`));
      svg.append(rect);
    });
  }
  const step = Math.max(1, Math.ceil(items.length / 8));
  items.forEach((item, index) => {
    if (index % step !== 0 && index !== items.length - 1) return;
    const label = item.label.length > 15 ? item.label.slice(0, 14) + "…" : item.label;
    svg.append(svgNode("text", { x: x(index), y: 320 - 23, "text-anchor": "middle", class: "chart-axis-label" }, label));
  });
  return svg;
}

function pieChart(items, type, currency) {
  const svg = chartSvg(type === "pie" ? "Revenue pie chart" : "Revenue doughnut chart");
  const cx = 205, cy = 158, radius = 112;
  const values = items.map((item) => Math.max(0, Number(item.value) || 0));
  const total = values.reduce((sum, value) => sum + value, 0);
  if (!total) {
    svg.append(svgNode("text", { x: 380, y: 160, "text-anchor": "middle", class: "chart-axis-label" }, "No revenue to display"));
    return svg;
  }
  let angle = -Math.PI / 2;
  items.forEach((item, index) => {
    const slice = values[index] / total * Math.PI * 2;
    const end = angle + slice;
    const sx = cx + radius * Math.cos(angle), sy = cy + radius * Math.sin(angle);
    const ex = cx + radius * Math.cos(end), ey = cy + radius * Math.sin(end);
    let path;
    if (slice >= Math.PI * 2 - 0.000001) {
      const mx = cx + radius * Math.cos(angle + Math.PI), my = cy + radius * Math.sin(angle + Math.PI);
      path = `M ${cx} ${cy} L ${sx} ${sy} A ${radius} ${radius} 0 1 1 ${mx} ${my} A ${radius} ${radius} 0 1 1 ${sx} ${sy} Z`;
    } else {
      path = `M ${cx} ${cy} L ${sx} ${sy} A ${radius} ${radius} 0 ${slice > Math.PI ? 1 : 0} 1 ${ex} ${ey} Z`;
    }
    const sector = svgNode("path", { d: path, fill: CHART_COLORS[index % CHART_COLORS.length], class: "chart-sector", tabindex: 0 });
    sector.append(svgNode("title", {}, `${item.label}: ${money(item.value, currency)} (${fmt(values[index] / total * 100)}%)`));
    svg.append(sector);
    const legendY = 36 + index * 34;
    svg.append(svgNode("rect", { x: 400, y: legendY - 12, width: 12, height: 12, rx: 2,
      fill: CHART_COLORS[index % CHART_COLORS.length] }));
    const legendLabel = item.label.length > 24 ? item.label.slice(0, 23) + "…" : item.label;
    svg.append(svgNode("text", { x: 420, y: legendY, class: "chart-legend-label" },
      `${legendLabel} · ${fmt(values[index] / total * 100)}%`));
    svg.append(svgNode("text", { x: 420, y: legendY + 16, class: "chart-legend-value" }, money(item.value, currency)));
    angle = end;
  });
  if (type === "doughnut") svg.append(svgNode("circle", { cx, cy, r: radius * 0.53, fill: "#fff" }));
  return svg;
}

function makeChartCard(title, items, types, currency) {
  const toolbar = el("div", { class: "chart-toolbar", role: "group" });
  toolbar.setAttribute("aria-label", `${title} chart type`);
  const visual = el("div", { class: "chart-visual" });
  let selected = types[0];
  const redraw = () => {
    visual.replaceChildren(selected === "pie" || selected === "doughnut"
      ? pieChart(items, selected, currency)
      : axisChart(items, selected, currency));
    toolbar.querySelectorAll("button").forEach((button) => {
      const active = button.dataset.chartType === selected;
      button.classList.toggle("selected", active);
      button.setAttribute("aria-pressed", String(active));
    });
  };
  types.forEach((type) => {
    const label = type === "doughnut" ? "Doughnut" : type[0].toUpperCase() + type.slice(1);
    const button = el("button", { type: "button", class: "chart-choice", text: label });
    button.dataset.chartType = type;
    button.addEventListener("click", () => { selected = type; redraw(); });
    toolbar.append(button);
  });
  const card = el("section", { class: "chart-card" },
    el("div", { class: "chart-heading" }, el("h3", { text: title }), toolbar),
    visual);
  redraw();
  return card;
}

// ---------- upload ----------
const drop = $("drop"), fileInput = $("file");
drop.addEventListener("click", () => fileInput.click());
drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); } });
drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]); });
fileInput.addEventListener("change", () => { if (fileInput.files[0]) upload(fileInput.files[0]); fileInput.value = ""; });

async function upload(file) {
  if (!keyBox.value.trim()) return say("Enter your API key first.", "error");
  if (!/\.(csv|xlsx)$/i.test(file.name)) return say("Please choose a .csv or .xlsx file.", "error");
  if (file.size > 10 * 1024 * 1024) return say("That file is over 10 MB.", "error");
  say("Uploading…");
  const form = new FormData();
  form.append("file", file);
  try {
    const { id } = await json("/api/reports", { method: "POST", body: form });
    say("Upload accepted. Building your report…", "ok");
    follow(id);
    loadList();
  } catch (err) { say(err.message, "error"); }
}

$("run-scheduled").addEventListener("click", async () => {
  try { const r = await json("/api/reports/scheduled/run", { method: "POST" }); say(r.message, "ok"); setTimeout(loadList, 3000); }
  catch (err) { say(err.message, "error"); }
});

// ---------- follow a report until it is finished ----------
function follow(id) {
  clearTimeout(pollTimer);
  const tick = async () => {
    try {
      const report = await json("/api/reports/" + id);
      render(report);
      if (!DONE.has(report.status)) pollTimer = setTimeout(tick, 1200); else loadList();
    } catch (err) { say(err.message, "error"); }
  };
  tick();
}

function renderSteps(status) {
  const box = $("steps");
  box.hidden = false; box.replaceChildren();
  const idx = STEPS.findIndex(([s]) => s === status);
  STEPS.forEach(([s, label], i) => {
    let cls = "";
    if (status === "ready" || i < idx) cls = "done"; else if (i === idx) cls = "now";
    if ((status === "rejected" || status === "failed") && i === STEPS.findIndex(([x]) => x === "validating")) cls = "stop";
    box.append(el("li", { class: cls, text: label }));
  });
}

function table(headers, rows) {
  return el("div", { class: "scroll" }, el("table", {},
    el("thead", {}, el("tr", {}, headers.map((h) => el("th", { text: h })))),
    el("tbody", {}, rows.map((r) => el("tr", {}, r.map((c) => el("td", { text: String(c ?? "") })))))));
}

function render(r) {
  $("placeholder").hidden = true;
  blobUrls.forEach(URL.revokeObjectURL); blobUrls = [];
  renderSteps(r.status);
  const out = $("result"); out.replaceChildren();

  if (r.status === "rejected" || r.status === "failed") {
    const card = el("div", { class: "card" }, el("h2", { text: r.status === "rejected" ? "This file could not be used" : "Something went wrong" }),
      el("p", { class: "error-text", text: r.error || "Unknown error." }));
    if (r.issues?.length) {
      card.append(el("h3", { text: "Problems found (first " + r.issues.length + ")" }),
        table(["Row", "Problem"], r.issues.map((i) => [i.row, i.problem])));
    }
    return out.append(card);
  }
  if (r.status !== "ready") return out.append(el("p", { class: "muted", text: "Working on it…" }));

  const a = r.analysis, t = a.totals, currency = a.currency || "INR";
  const kpis = el("div", { class: "kpis" },
    [["Revenue", money(t.revenue, currency)], ["Orders", fmt(t.orders)],
      ["Avg. order value", money(t.avg_order_value, currency)],
      ["Avg. daily revenue", money(t.avg_daily_revenue, currency)],
      ["Units sold", fmt(t.units)], ["Products", fmt(a.product_count)]]
      .map(([k, v]) => el("div", { class: "kpi" }, el("b", { text: v }), el("span", { text: k }))));

  const download = el("button", { type: "button", text: "Download PDF" });
  download.addEventListener("click", async () => {
    try {
      const blob = await (await api(`/api/reports/${r.id}/pdf`)).blob();
      const url = URL.createObjectURL(blob);
      const a2 = el("a", { href: url, download: `report-${r.id.slice(0, 8)}.pdf` });
      document.body.append(a2); a2.click(); a2.remove(); setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch (err) { say(err.message, "error"); }
  });

  out.append(el("div", { class: "card" },
    el("h2", { text: r.filename }), el("p", { class: "muted", text: `${a.period.start} to ${a.period.end}` }),
    kpis, el("div", { class: "actions" }, download)));

  const summaryPoints = el("ul", { class: "summary-points" },
    summarySentences(r.summary).map((sentence) => el("li", { class: "summary-point", text: sentence })));
  out.append(el("div", { class: "card" }, el("h2", { text: "Summary" }),
    summaryPoints,
    el("p", { class: "muted", text: r.summary_source === "ai" ? "Written by AI from the totals above." : "Generated from the totals above." })));

  const trendItems = a.trend.points.map((point) => ({ label: point.date, value: point.revenue }));
  const productItems = a.top_products.map((product) => ({ label: product.name, value: product.revenue }));
  const chartCards = [
    makeChartCard("Revenue trend", trendItems, ["line", "bar"], currency),
    makeChartCard("Revenue by product", productItems, ["bar", "pie", "doughnut"], currency),
  ];
  if (a.by_region.length) {
    chartCards.push(makeChartCard("Revenue by region",
      a.by_region.map((region) => ({ label: region.name, value: region.revenue })),
      ["bar", "pie", "doughnut"], currency));
  }
  out.append(el("div", { class: "card" }, el("h2", { text: "Interactive analytics" }),
    el("p", { class: "muted", text: "Switch chart types and hover or focus a data point to inspect its value." }),
    el("div", { class: "analytics-grid" }, chartCards)));

  const insights = el("div", { class: "card" }, el("h2", { text: "Sales insights" }),
    el("div", { class: "insight-grid" },
      el("div", { class: "insight" }, el("span", { text: "Best sales day" }),
        el("strong", { text: `${a.best_day.date} · ${money(a.best_day.revenue, currency)}` })),
      el("div", { class: "insight" }, el("span", { text: "Active sales days" }),
        el("strong", { text: `${fmt(a.active_days)} of ${fmt(a.period.days)} days` })),
      el("div", { class: "insight" }, el("span", { text: "Average units per order" }),
        el("strong", { text: fmtDecimal(t.avg_units_per_order) }))));
  if (a.week_over_week) {
    const change = a.week_over_week.change_pct;
    insights.append(el("p", { class: change == null ? "muted" : change >= 0 ? "trend-up" : "trend-down",
      text: change == null
        ? `Last 7 days: ${money(a.week_over_week.last_7_days, currency)} · Previous 7 days: ${money(a.week_over_week.previous_7_days, currency)}`
        : `Last 7 days: ${money(a.week_over_week.last_7_days, currency)} · ${change >= 0 ? "+" : ""}${fmtDecimal(change)}% vs previous 7 days` }));
  }
  out.append(insights);

  const q = el("div", { class: "card" }, el("h2", { text: "Data quality" }),
    el("p", { text: `${fmt(r.rows_read)} rows read, ${fmt(r.rows_valid)} used, ${fmt(r.rows_rejected)} skipped as invalid.` }));
  (r.warnings || []).forEach((w) => q.append(el("p", { class: "warn", text: w })));
  const log = r.cleaning_log;
  if (log) {
    q.append(el("h3", { text: "What was cleaned" }), table(["Step", "Count"], [
      ["Title rows above the header skipped", Math.max(0, log.header_row - 1)],
      ["Footer rows (like Total) removed", log.footer_rows_removed],
      ["Duplicate rows removed", log.duplicates_removed],
      ["Names made consistent", log.names_unified],
      ["Missing revenue calculated (qty × price)", log.revenue_calculated],
    ]));
  }
  if (r.issues?.length) q.append(el("h3", { text: "Rows that were skipped" }), table(["Row", "Problem"], r.issues.map((i) => [i.row, i.problem])));
  out.append(q);
}

// ---------- recent list ----------
async function loadList() {
  if (!keyBox.value.trim()) return;
  try {
    const rows = await json("/api/reports");
    const ul = $("list"); ul.replaceChildren();
    $("list-empty").hidden = rows.length > 0;
    rows.forEach((r) => {
      const btn = el("button", { type: "button" },
        el("span", { class: "name", text: r.filename }),
        el("span", { class: "meta" }, el("span", { class: "tag " + r.status, text: r.status }),
          " " + new Date(r.created_at).toLocaleString()));
      btn.addEventListener("click", () => follow(r.id));
      ul.append(el("li", {}, btn));
    });
  } catch (err) { if (err.status === 401) say("API key not accepted.", "error"); }
}
keyBox.addEventListener("change", loadList);
loadList();
