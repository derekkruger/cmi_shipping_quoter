"use strict";

const form = document.getElementById("quote-form");
const pkgBody = document.querySelector("#packages tbody");

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else node.setAttribute(k, v);
  }
  for (const c of children) node.append(c instanceof Node ? c : document.createTextNode(c ?? ""));
  return node;
}

function addPackageRow(values = {}) {
  const tr = el("tr");
  for (const key of ["weight_lb", "length_in", "width_in", "height_in"]) {
    const input = el("input", {
      type: "number", step: "0.1", min: "0", name: key,
      placeholder: key === "weight_lb" ? "required" : "optional",
    });
    if (key === "weight_lb") input.required = true;
    if (values[key]) input.value = values[key];
    tr.append(el("td", {}, input));
  }
  const remove = el("button", { type: "button", class: "link", title: "Remove package" }, "Remove");
  remove.addEventListener("click", () => {
    if (pkgBody.children.length > 1) tr.remove();
  });
  tr.append(el("td", {}, remove));
  pkgBody.append(tr);
}

async function loadDefaults() {
  const [settings, carriers] = await Promise.all([
    fetch("/api/settings").then(r => r.json()),
    fetch("/api/carriers").then(r => r.json()),
  ]);
  const o = settings.origin || {};
  for (const k of ["postal_code", "country_code", "city", "state"]) {
    if (o[k]) form.elements["o_" + k].value = o[k];
  }

  const status = document.getElementById("carrier-status");
  status.replaceChildren(el("strong", {}, "Carriers: "));
  let anyReady = false;
  for (const c of carriers) {
    const ready = c.enabled && c.configured;
    anyReady ||= ready;
    let label = c.display_name;
    if (!c.enabled) label += " — off";
    else if (!c.configured) label += " — needs API keys";
    else label += c.environment === "production" ? "" : " (sandbox)";
    status.append(el("span", { class: "badge " + (ready ? "on" : "off") }, label));
  }
  if (!anyReady) {
    status.append(el("span", { class: "muted" }, " No carriers ready. "),
      el("a", { href: "/settings" }, "Open Settings to add UPS / FedEx API keys."));
  }
}

function collect() {
  const f = form.elements;
  const packages = [...pkgBody.querySelectorAll("tr")].map(tr => {
    const p = {};
    tr.querySelectorAll("input").forEach(i => { p[i.name] = i.value; });
    return p;
  });
  return {
    origin: {
      postal_code: f.o_postal_code.value, country_code: f.o_country_code.value,
      city: f.o_city.value, state: f.o_state.value,
    },
    destination: {
      postal_code: f.d_postal_code.value, country_code: f.d_country_code.value,
      city: f.d_city.value, state: f.d_state.value, residential: f.d_residential.checked,
    },
    packages,
  };
}

function money(v, cur = "USD") {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: cur || "USD" }).format(v);
}

function renderResults(data) {
  const panel = document.getElementById("results-panel");
  const tbody = document.querySelector("#results tbody");
  const errors = document.getElementById("errors");
  panel.classList.remove("hidden");
  tbody.replaceChildren();
  errors.replaceChildren();

  for (const msg of Object.values(data.errors || {})) {
    errors.append(el("div", { class: "msg err" }, msg));
  }
  const rates = data.rates || [];
  document.getElementById("results").classList.toggle("hidden", !rates.length);
  document.getElementById("results-summary").textContent =
    rates.length ? `— ${rates.length} options, cheapest first` : "";
  if (!rates.length && !Object.keys(data.errors || {}).length) {
    errors.append(el("div", { class: "msg err" }, "No rates were returned."));
  }

  rates.forEach((r, i) => {
    const rateCell = el("td", { class: "num" });
    if (r.list_total != null && r.list_total > r.total) {
      rateCell.append(el("span", { class: "strike", title: "Published/list rate" }, money(r.list_total, r.currency)));
    }
    rateCell.append(el("strong", {}, money(r.total, r.currency)));
    const service = el("td", {}, r.service_name);
    for (const n of r.notes || []) service.append(el("div", { class: "muted" }, n));
    tbody.append(el("tr", { class: i === 0 ? "best" : "" },
      el("td", { class: "carrier " + r.carrier }, r.carrier),
      service,
      el("td", { class: "num" }, r.transit_days != null ? `${r.transit_days} day${r.transit_days === 1 ? "" : "s"}` : "—"),
      el("td", {}, r.delivery_date || "—"),
      rateCell,
    ));
  });
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = document.getElementById("submit");
  btn.disabled = true;
  btn.textContent = "Getting quotes…";
  try {
    const resp = await fetch("/api/quote", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collect()),
    });
    const data = await resp.json();
    if (!resp.ok) renderResults({ rates: [], errors: { form: data.error || "Request failed." } });
    else renderResults(data);
  } catch (err) {
    renderResults({ rates: [], errors: { app: "Could not reach the quoter app. Is it still running?" } });
  } finally {
    btn.disabled = false;
    btn.textContent = "Get quotes";
  }
});

document.getElementById("add-pkg").addEventListener("click", () => addPackageRow());
addPackageRow();
loadDefaults().catch(() => {
  document.getElementById("carrier-status").textContent = "Could not load settings.";
});
