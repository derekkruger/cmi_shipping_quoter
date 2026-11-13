"use strict";

const form = document.getElementById("settings-form");
const MASK = "********";

function getPath(obj, path) {
  return path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);
}
function setPath(obj, path, value) {
  const keys = path.split(".");
  const last = keys.pop();
  let o = obj;
  for (const k of keys) o = o[k] ??= {};
  o[last] = value;
}

function fill(settings) {
  for (const input of form.querySelectorAll("[name]")) {
    const value = getPath(settings, input.name);
    if (input.type === "checkbox") input.checked = !!value;
    else if (input.type === "password") {
      input.value = "";
      input.placeholder = value === MASK ? "saved — leave blank to keep" : "not set";
    } else input.value = value ?? "";
  }
  for (const section of form.querySelectorAll("[data-carrier]")) {
    const name = section.dataset.carrier;
    const badge = section.querySelector("[data-status]");
    const missing = settings.status?.[name]?.missing ?? [];
    const enabled = settings.carriers?.[name]?.enabled;
    badge.className = "badge " + (missing.length ? "off" : enabled ? "on" : "");
    badge.textContent = missing.length ? "needs " + missing.join(", ").replaceAll("_", " ")
      : enabled ? "ready" : "configured, turned off";
  }
}

function collect() {
  const out = {};
  for (const input of form.querySelectorAll("[name]")) {
    setPath(out, input.name, input.type === "checkbox" ? input.checked : input.value);
  }
  return out;
}

async function load() {
  fill(await fetch("/api/settings").then(r => r.json()));
}

async function save() {
  const resp = await fetch("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(collect()),
  });
  if (!resp.ok) throw new Error("Save failed");
  await load();
}

function showMsg(target, ok, text) {
  target.replaceChildren();
  const div = document.createElement("div");
  div.className = "msg " + (ok ? "ok" : "err");
  div.textContent = text;
  target.append(div);
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = document.getElementById("save-msg");
  try {
    await save();
    showMsg(msg, true, "Saved.");
  } catch {
    showMsg(msg, false, "Could not save settings.");
  }
  setTimeout(() => msg.replaceChildren(), 3000);
});

for (const btn of form.querySelectorAll("[data-test]")) {
  btn.addEventListener("click", async () => {
    const name = btn.dataset.test;
    const result = btn.closest("section").querySelector("[data-result]");
    btn.disabled = true;
    btn.textContent = "Testing…";
    try {
      await save(); // test what's on screen
      const data = await fetch(`/api/carriers/${name}/test`, { method: "POST" }).then(r => r.json());
      showMsg(result, data.ok, data.ok ? data.message : data.error);
    } catch {
      showMsg(result, false, "Could not reach the quoter app.");
    } finally {
      btn.disabled = false;
      btn.textContent = "Test connection";
    }
  });
}

load();
