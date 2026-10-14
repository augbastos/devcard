"use strict";
const $ = (id) => document.getElementById(id);
const number = (n) => Number(n).toLocaleString("en-US");
const palette = ["#3572a5", "#b07219", "#3178c6", "#a33a32", "#6e5494", "#16847d", "#bd6714", "#ad4674"];
const svgNS = "http://www.w3.org/2000/svg";
let summary;

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}
function svgNode(tag, attributes, text) {
  const element = document.createElementNS(svgNS, tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  if (text !== undefined) element.textContent = text;
  return element;
}
async function get(path) {
  const response = await fetch(path, {cache: "no-store", credentials: "omit"});
  if (!response.ok) throw new Error(`Local request failed (${response.status}). Check the date range or database and refresh.`);
  return response.json();
}
function tableRows(id, rows) {
  $(id).replaceChildren(...rows.map((values) => {
    const row = node("tr");
    values.forEach((value) => row.append(node("td", value)));
    return row;
  }));
}
function drawSummary(value) {
  summary = value;
  $("lines").textContent = number(value.totals.lines_added);
  $("bytes").textContent = number(value.totals.bytes_added);
  $("streak").textContent = `${number(value.streak)} days`;
  $("repos").textContent = number(value.totals.repo_count);
  $("counting").textContent = `${number(value.totals.actions)} edit/write actions · ${number(value.totals.diffs)} commit diffs · ${number(value.totals.commits)} commits. These are different units; capture one mode per machine.`;
  $("timezone").textContent = `day boundaries: ${value.timezone}; activity/usage: ${value.usage_timezone}`;
  $("usage-warning").hidden = !value.usage_incomplete;
  $("language-bar").replaceChildren();
  $("language-legend").replaceChildren();
  value.languages.forEach((language, i) => {
    const fraction = value.totals.lines_added ? language.lines_added / value.totals.lines_added : 0;
    const color = palette[i % palette.length];
    const label = `${language.language}: ${number(language.lines_added)} lines (${(fraction * 100).toFixed(1)}%)`;
    const segment = node("span", undefined, "language-segment");
    segment.style.width = `${fraction * 100}%`;
    segment.style.backgroundColor = color;
    segment.title = label;
    segment.setAttribute("aria-label", label);
    $("language-bar").append(segment);
    const item = node("li");
    const swatch = node("span", undefined, "swatch");
    swatch.style.backgroundColor = color;
    item.append(swatch, node("span", label));
    $("language-legend").append(item);
  });
  if (!value.languages.length) $("language-legend").append(node("li", "No recorded language activity yet."));
  $("heatmap").replaceChildren(...value.heatmap.map((week) => {
    const column = node("div", undefined, "week");
    week.forEach((day) => {
      const button = node("button", undefined, `cell level-${day.level}`);
      button.type = "button";
      button.title = `${day.day}: ${number(day.lines)} lines`;
      button.setAttribute("aria-label", button.title);
      button.setAttribute("aria-pressed", "false");
      button.disabled = day.day > value.today;
      button.addEventListener("click", () => {
        $("heatmap").querySelectorAll("button").forEach((cell) => cell.setAttribute("aria-pressed", "false"));
        button.setAttribute("aria-pressed", "true");
        $("from").value = $("to").value = day.day;
        loadDays().catch(showError);
      });
      column.append(button);
    });
    return column;
  }));
}
function drawDays(rows) {
  const totals = new Map();
  // Include zero days; UTC here advances calendar keys, not event timestamps.
  const end = Date.parse(`${$("to").value}T00:00:00Z`);
  const start = Date.parse(`${$("from").value}T00:00:00Z`);
  // Keep a very long export range usable without drawing millions of SVG nodes.
  const chartStart = Math.max(start, end - 365 * 86400000);
  for (let day = chartStart; day <= end; day += 86400000) totals.set(new Date(day).toISOString().slice(0, 10), 0);
  for (const row of rows) if (totals.has(row.day)) totals.set(row.day, totals.get(row.day) + row.lines_added);
  const max = Math.max(1, ...totals.values());
  const chart = $("chart");
  chart.replaceChildren(svgNode("line", {x1: 32, x2: 790, y1: 150, y2: 150}));
  const width = 750 / Math.max(1, totals.size);
  [...totals.entries()].forEach(([day, lines], index) => {
    const height = lines / max * 125;
    const rect = svgNode("rect", {x: 35 + index * width, y: 150 - height, width: Math.max(1, width - 1), height});
    rect.append(svgNode("title", {}, `${day}: ${number(lines)} lines`));
    chart.append(rect);
  });
  chart.append(svgNode("text", {x: 0, y: 22}, number(max)), svgNode("text", {x: 0, y: 153}, "0"));
  const keys = [...totals.keys()];
  if (keys.length) chart.append(svgNode("text", {x: 35, y: 175}, keys[0]), svgNode("text", {x: 790, y: 175, "text-anchor": "end"}, keys[keys.length - 1]));
  const total = rows.reduce((sum, row) => sum + row.lines_added, 0);
  $("chart-caption").textContent = `${number(total)} lines added in the selected range.${start < chartStart ? " Chart shows the last 366 days; the table and export include the whole selected range." : ""}`;
  chart.setAttribute("aria-label", $("chart-caption").textContent);
  tableRows("daily-rows", rows.map((r) => [r.day, r.language || "Unclassified / commit", number(r.lines_added), number(r.lines_removed), number(r.bytes_added)]));
  $("daily-caption").textContent = rows.length ? "Daily activity by language" : "No recorded events in this range.";
}
async function loadDays() {
  const params = new URLSearchParams({from: $("from").value, to: $("to").value});
  const rows = await get(`/api/days?${params}`);
  drawDays(rows);
  $("csv-export").href = `/api/export.csv?${params}`;
  $("json-export").href = `/api/export.json?${params}`;
  $("status").textContent = "Local data loaded. Refresh to include new activity.";
}
function showError(error) { $("status").textContent = error.message; }
async function refresh() {
  $("refresh").disabled = true;
  $("status").textContent = "Loading local activity…";
  try {
    const [value, agents, usage] = await Promise.all([get("/api/summary"), get("/api/agents"), get("/api/usage")]);
    drawSummary(value);
    if (!$("from").value) $("from").value = value.heatmap[0][0].day;
    if (!$("to").value) $("to").value = value.today;
    tableRows("agent-rows", agents.map((a) => [a.agent, number(a.lines_added), number(a.lines_removed), number(a.bytes_added), number(a.events), a.active_minutes === null ? "—" : number(a.active_minutes)]));
    const activeDays = agents.flatMap((a) => a.active_days.map((day) => ({...day, agent: a.agent})));
    activeDays.sort((a, b) => a.day.localeCompare(b.day) || a.agent.localeCompare(b.agent));
    tableRows("agent-active-rows", activeDays.map((a) => [a.day, a.agent, number(a.active_minutes)]));
    $("agent-empty").hidden = agents.length !== 0;
    tableRows("usage-rows", usage.map((u) => [u.date, `${u.agent} / ${u.model_family}`, number(u.input_tokens), number(u.output_tokens), number(u.cache_read_tokens), number(u.cache_write_tokens), number(u.total_tokens), u.estimated_cost_usd === null ? "—" : `$${Number(u.estimated_cost_usd).toFixed(4)}`]));
    $("usage-empty").hidden = usage.length !== 0;
    await loadDays();
    const preview = $("preview");
    const theme = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    // Reassigning the source reloads a no-store local image without outbound fetches.
    preview.parentElement.querySelector("source").srcset = "/api/card.svg?theme=dark";
    preview.src = `/api/card.svg?theme=${theme}`;
  } catch (error) { showError(error); }
  finally { $("refresh").disabled = false; }
}
$("refresh").addEventListener("click", refresh);
$("range").addEventListener("submit", (event) => { event.preventDefault(); loadDays().catch(showError); });
refresh();
