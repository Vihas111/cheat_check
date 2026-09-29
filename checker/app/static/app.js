// Upload by drag-and-drop, live progress polling, table refresh. No external libraries (runs offline).

function $(sel) { return document.querySelector(sel); }

function initUpload() {
  const drop = $("#drop");
  if (!drop) return;
  const input = $("#files");
  const log = $("#upload-log");

  async function send(files) {
    const pdfs = [...files].filter(f => f.name.toLowerCase().endsWith(".pdf"));
    if (!pdfs.length) { log.textContent = "Only PDF files can be added. Choose files ending in .pdf."; return; }
    const mode = (drop.querySelector("input[name=mode]:checked") || { value: drop.dataset.mode }).value;
    // batches keep each request small and give visible progress on large drops
    let added = 0, skipped = 0, errors = [];
    for (let i = 0; i < pdfs.length; i += 10) {
      log.textContent = `Uploading ${Math.min(i + 10, pdfs.length)} of ${pdfs.length}…`;
      const fd = new FormData();
      fd.append("mode", mode);
      pdfs.slice(i, i + 10).forEach(f => fd.append("files", f));
      try {
        const r = await fetch(drop.dataset.url, { method: "POST", body: fd });
        if (!r.ok) throw new Error(`server said ${r.status}`);
        const j = await r.json();
        added += j.added.length; skipped += j.skipped.length; errors.push(...j.errors);
      } catch (e) {
        errors.push(`upload failed: ${e.message}`);
      }
    }
    log.innerHTML = "";
    const p = document.createElement("p");
    p.textContent = `${added} ${added === 1 ? "file" : "files"} added` + (skipped ? `, ${skipped} already here` : "") + ".";
    log.appendChild(p);
    errors.forEach(e => { const d = document.createElement("p"); d.textContent = e; log.appendChild(d); });
    poll();
  }

  input.addEventListener("change", () => send(input.files));
  // the whole page is a drop target, the dashed box shows it
  ["dragenter", "dragover"].forEach(ev => document.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
  document.addEventListener("dragleave", e => { if (!e.relatedTarget) drop.classList.remove("over"); });
  document.addEventListener("drop", e => { e.preventDefault(); drop.classList.remove("over"); send(e.dataTransfer.files); });
}

let lastStamp = null, timer = null;

async function poll() {
  const box = $("#progress");
  if (!box) return;
  clearTimeout(timer);
  try {
    const s = await (await fetch(box.dataset.status)).json();
    const total = s.queued + s.processing + s.done + s.failed;
    $("#pbar").style.width = (total ? (s.done + s.failed) / total * 100 : 0) + "%";
    $("#ptext").innerHTML = `${s.done} read, ${s.processing} in progress, ${s.queued} waiting` +
      (s.failed ? `, <b>${s.failed} could not be read</b>` : "") + (s.rescanning ? ". Re-scanning." : "");
    if (lastStamp !== null && s.stamp !== lastStamp) {
      $("#table").innerHTML = await (await fetch(box.dataset.table)).text();
    }
    lastStamp = s.stamp;
    const busy = s.queued || s.processing || s.rescanning;
    timer = setTimeout(poll, busy ? 2000 : 10000);
  } catch (e) {
    timer = setTimeout(poll, 10000);
  }
}

// Submission page of a file still in the queue: reload once it is processed.
function initReload() {
  const el = document.querySelector("[data-reload-when-done]");
  if (!el) return;
  setInterval(async () => {
    const s = await (await fetch(el.dataset.reloadWhenDone)).json();
    if (!s.queued && !s.processing) location.reload();
  }, 3000);
}

// Grader: tabs, live total, keyboard shortcuts, and a warning before leaving unsaved marks.
function initGrader() {
  const tabs = [...document.querySelectorAll("[role=tab]")];
  const show = id => tabs.forEach(t => {
    const on = t.getAttribute("aria-controls") === id;
    t.setAttribute("aria-selected", on);
    document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
  });
  tabs.forEach(t => t.addEventListener("click", () => show(t.getAttribute("aria-controls"))));
  document.querySelectorAll("[data-tab]").forEach(b => b.addEventListener("click", () => show(b.dataset.tab)));

  const form = $("#marking");
  if (form) {
    const inputs = [...form.querySelectorAll("input[data-points]")];
    const total = () => {
      const filled = inputs.filter(i => i.value !== "");
      $("#total").textContent = filled.length ? +filled.reduce((s, i) => s + (+i.value || 0), 0).toFixed(2) : "–";
    };
    let dirty = false;
    form.addEventListener("input", () => { dirty = true; total(); });
    form.addEventListener("submit", () => { dirty = false; });
    window.addEventListener("beforeunload", e => { if (dirty) e.preventDefault(); });
    document.addEventListener("keydown", e => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault();
        form.querySelector("button[value=save]").click();
      }
    });
  }
  document.addEventListener("keydown", e => {
    if (e.ctrlKey || e.metaKey || e.altKey || /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
    const link = document.querySelector(`[data-key="${e.key}"]`);
    if (link) link.click();
  });
}

// Theme: "" follows the system, otherwise "light" or "dark". base.html applies the saved choice before paint.
function initTheme() {
  const names = { "": "System", light: "Light", dark: "Dark" }, order = ["", "light", "dark"];
  document.querySelectorAll("[data-theme-toggle]").forEach(btn => {
    // The icon is picked in CSS from data-theme; only the label for screen readers and the tooltip is set here.
    const show = () => { btn.title = "Theme: " + names[document.documentElement.dataset.theme || ""]; btn.setAttribute("aria-label", btn.title); };
    show();
    btn.addEventListener("click", () => {
      const next = order[(order.indexOf(document.documentElement.dataset.theme || "") + 1) % order.length];
      document.documentElement.dataset.theme = next;
      localStorage.setItem("theme", next);
      show();
    });
  });
}

document.addEventListener("DOMContentLoaded", () => { initUpload(); poll(); initReload(); initGrader(); initTheme(); });
