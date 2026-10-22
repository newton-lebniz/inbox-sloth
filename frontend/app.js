// Inbox Sloth - Day 1 frontend: onboarding, load/analyse, commitment list with sources.
// All text from emails is inserted with textContent (never innerHTML): emails are untrusted.

const $ = (id) => document.getElementById(id);
const PRIORITY_OPTIONS = ["deadlines", "exams", "meetings", "replies", "club activities", "internships", "invoices"];
const FLAG_LABELS = {
  deadline_changed: ["changed", "Date changed"],
  uncertain_date: ["uncertain", "Date unsure"],
  no_date: ["uncertain", "No date given"],
  unverified: ["uncertain", "Needs review"],
};

async function api(path, options = {}) {
  const res = await fetch("/api" + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const c of children) el.append(c);
  return el;
}

function fmtDue(c) {
  if (!c.due_at) return ["No date", ""];
  const d = new Date(c.due_at);
  const day = d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
  const time = c.all_day ? "all day" : d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
  return [day, time];
}

// ---------- health + profile ----------
async function loadHealth() {
  const pill = $("health");
  try {
    const hres = await api("/health");
    pill.className = "pill " + (hres.ok ? "pill-ok" : "pill-bad");
    pill.textContent = hres.ok ? `${hres.model} ready` : "model not ready";
    pill.title = hres.error || "Running locally via Ollama";
  } catch (e) {
    pill.className = "pill pill-bad";
    pill.textContent = "backend offline";
  }
}

async function loadProfile() {
  const p = await api("/profile");
  const form = $("profile-form");
  form.role.value = p.role;
  form.study_start.value = p.study_start;
  form.study_end.value = p.study_end;
  form.reminder_style.value = p.reminder_style;
  const box = $("priorities");
  box.replaceChildren();
  for (const opt of PRIORITY_OPTIONS) {
    const input = h("input", { type: "checkbox", value: opt });
    input.checked = p.priorities.includes(opt);
    box.append(h("label", {}, input, opt));
  }
  if (p.onboarded) $("profile-saved").textContent = "Saved";
}

$("profile-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = ev.target;
  const priorities = [...document.querySelectorAll("#priorities input:checked")].map((i) => i.value);
  await api("/profile", {
    method: "PUT",
    body: { role: f.role.value, study_start: f.study_start.value, study_end: f.study_end.value,
            priorities, reminder_style: f.reminder_style.value },
  });
  $("profile-saved").textContent = "Saved. Your priorities will shape what the sloth flags.";
});

// ---------- emails + processing ----------
async function refreshEmailCount() {
  const emails = await api("/emails");
  const processed = emails.filter((e) => e.status === "processed").length;
  $("email-count").textContent = emails.length ? `${emails.length} emails (${processed} analysed)` : "No emails loaded";
}

$("btn-sample").addEventListener("click", async () => {
  const r = await api("/emails/sample", { method: "POST" });
  $("email-count").textContent = `${r.total} emails loaded`;
  await refreshEmailCount();
});

$("btn-reset").addEventListener("click", async () => {
  if (!confirm("Remove all emails and commitments?")) return;
  await api("/reset", { method: "POST" });
  await refreshAll();
});

$("btn-process").addEventListener("click", async () => {
  $("btn-process").disabled = true;
  $("errors").hidden = true;
  try {
    await api("/process", { method: "POST" });
  } catch (e) {
    $("btn-process").disabled = false;
    $("errors").hidden = false;
    $("errors").textContent = /503/.test(e.message)
      ? "The local model is not ready. Start Ollama and run: ollama pull gemma3:1b"
      : String(e.message);
    return;
  }
  $("progress").hidden = false;
  pollProgress();
});

async function pollProgress() {
  const s = await api("/process/status");
  const pct = s.total ? Math.round((s.done / s.total) * 100) : 0;
  $("bar-fill").style.width = pct + "%";
  $("progress-text").textContent = s.state === "done"
    ? `Done: ${s.done} emails in ${s.elapsed_s}s`
    : `Reading ${s.done + 1} of ${s.total}${s.current ? ": " + s.current : ""}`;
  await loadTasks();                       // tasks appear as emails are processed
  if (s.state === "running") return setTimeout(pollProgress, 1500);
  $("btn-process").disabled = false;
  if (s.errors.length) {
    $("errors").hidden = false;
    $("errors").textContent = `${s.errors.length} email(s) failed. Is Ollama running? First error: ${s.errors[0].error}`;
  }
  await refreshEmailCount();
}

// ---------- commitments ----------
async function loadTasks() {
  const all = await api("/commitments");
  const showDone = $("show-done").checked;
  const items = all.filter((c) => c.status !== "dismissed" && (showDone || c.status !== "done"));
  const list = $("tasks");
  list.replaceChildren();
  $("empty").hidden = items.length > 0;
  for (const c of items) list.append(renderTask(c));
}

function renderTask(c) {
  const [day, time] = fmtDue(c);
  const badges = h("div", { class: "badges" }, h("span", { class: "badge kind" }, c.kind));
  for (const f of c.flags) {
    const [cls, label] = FLAG_LABELS[f] || ["", f];
    let text = label;
    if (f === "deadline_changed" && c.previous_due_at) {
      const old = new Date(c.previous_due_at).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
      text = `Changed (was ${old})`;
    }
    badges.append(h("span", { class: "badge " + cls }, text));
  }
  const check = h("input", { type: "checkbox", "aria-label": "Mark done" });
  check.checked = c.status === "done";
  check.addEventListener("change", async () => {
    await api(`/commitments/${c.id}`, { method: "PATCH", body: { status: check.checked ? "done" : "pending" } });
    loadTasks();
  });
  return h("li", { class: "task" + (c.status === "done" ? " done" : "") },
    h("div", { class: "due" }, h("strong", {}, day), time),
    h("div", {}, h("div", { class: "title" }, c.title), badges),
    h("div", { class: "row" }, check, h("button", { class: "btn ghost small", onclick: () => openSource(c.id) }, "Source")),
  );
}

async function openSource(id) {
  const c = await api(`/commitments/${id}`);
  const email = await api(`/emails/${c.source_email_id}`);
  $("src-title").textContent = c.title;
  $("src-meta").textContent = `${email.sender}  ·  ${email.subject}  ·  ${new Date(email.sent_at).toLocaleString("en-IN")}`;

  const body = $("src-body");
  body.replaceChildren();
  const q = (c.source_quote || "").trim();
  const idx = q ? email.body.toLowerCase().indexOf(q.toLowerCase()) : -1;
  if (idx >= 0) {
    body.append(email.body.slice(0, idx), h("mark", {}, email.body.slice(idx, idx + q.length)), email.body.slice(idx + q.length));
  } else {
    body.append(email.body);
  }

  const hist = $("src-history");
  hist.replaceChildren();
  const fmt = (iso) => (iso ? new Date(iso).toLocaleString("en-IN", { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "no date");
  for (const e of c.events) {
    const label = {
      created: `Created from email ${e.email_id} (${fmt(e.new_due_at)})`,
      deadline_changed: `Email ${e.email_id} changed it: ${fmt(e.old_due_at)} → ${fmt(e.new_due_at)}`,
      date_added: `Email ${e.email_id} added a date: ${fmt(e.new_due_at)}`,
      confirmed: `Email ${e.email_id} confirmed it`,
      stale_ignored: `Older email ${e.email_id} ignored`,
    }[e.event] || e.event;
    hist.append(h("li", {}, label));
  }
  $("source").showModal();
}

$("show-done").addEventListener("change", loadTasks);

async function refreshAll() {
  await Promise.all([loadHealth(), loadProfile(), refreshEmailCount(), loadTasks()]);
}
refreshAll();
