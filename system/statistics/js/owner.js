"use strict";

/* =====================================================================
   Biri-Go OWNER page  (template/owner.html  +  statistics/js/owner.js)

   VIEW-ONLY copy of the HR page.
   - Only ever sends GET requests to /api/owner/<resource>.
   - No add / edit / delete / approve controls, no demo-mode fallback.
   - Adds a Salaries page (monthly salary + latest net pay per employee).
   ===================================================================== */

/* ---------- tiny helpers ---------- */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const iso = d => { const z = new Date(d.getTime() - d.getTimezoneOffset() * 60000); return z.toISOString().slice(0, 10); };
const today = () => iso(new Date());
const addDays = (s, n) => { const d = new Date(s + "T00:00:00"); d.setDate(d.getDate() + n); return iso(d); };
const addMonths = (s, n) => { const d = new Date(s + "T00:00:00"); d.setMonth(d.getMonth() + n); return iso(d); };
const fmtDate = s => s ? new Date(s + "T00:00:00").toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "-";
const slug = s => String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, "-");
const badge = s => `<span class="badge badge-${slug(s)}">${esc(s)}</span>`;
const peso = n => "₱" + Number(n || 0).toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// GET only. The owner portal never writes.
async function api(url) {
    const res = await fetch(url, {
        method: "GET",
        headers: { "Accept": "application/json" },
        credentials: "same-origin"
    });

    if (res.status === 401) {
        window.location.href = "/";
        return new Promise(() => {});
    }

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
        const e = new Error(data.error || "Request failed (" + res.status + ")");
        e.status = res.status;
        throw e;
    }
    return data;
}

/* ---------- state ---------- */
const RES = ["employees", "departments", "jobs", "applicants", "processes", "attendance",
    "leaves", "reviews", "trainings", "announcements", "holidays", "payroll"];
const S = { settings: {} };
const ui = { query: "", empPage: 1, perPage: 10 };

const STAGES = ["Applied", "Screening", "Interview", "Offer", "Hired"];
const EMP_TYPES = ["Full-time", "Part-time", "Contract", "Intern"];
const LEAVE_TYPES = ["Vacation Leave (PTO)", "Sick Leave", "Emergency Leave", "Bereavement Leave", "Maternity Leave",
    "Paternity Leave", "Parental Leave", "Special Leave (Mandated)", "Unpaid Leave (LOA)"];
const LEAVE_CAP = { "Vacation Leave (PTO)": "leave_vacation", "Sick Leave": "leave_sick", "Emergency Leave": "leave_emergency" };

async function load(...names) {
    await Promise.all((names.length ? names : [...RES, "settings"]).map(async r => {
        const d = await api("/api/owner/" + r);
        S[r] = r === "settings" ? d : (Array.isArray(d) ? d : d.items || []);
    }));
}

/* ---------- lookups ---------- */
const emp = id => S.employees.find(e => e.id == id);
const empName = id => { const e = emp(id); return e ? `${e.first_name} ${e.last_name}` : "(removed)"; };
const deptName = id => (S.departments.find(d => d.id == id) || {}).name || "-";
const jobTitle = id => (S.jobs.find(j => j.id == id) || {}).title || "-";
const initials = e => ((e.first_name || "?")[0] + (e.last_name || "")[0]).toUpperCase();
const deptOpts = () => S.departments.map(d => ({ v: d.id, l: d.name }));
const onLeaveOn = date => S.leaves.filter(l => l.status === "Approved" && l.from <= date && l.to >= date);
const isGone = e => e.status === "Resigned" || e.status === "Terminated";

// Every value that reaches HTML is encoded with esc().
const empty = (msg, cols) => cols
    ? `<tr><td colspan="${Number(cols) || 1}" class="muted" style="text-align:center;padding:1.2rem">${esc(msg)}</td></tr>`
    : `<li class="muted">${esc(msg)}</li>`;

const btn = (act, id, icon, label, cls = "btn-secondary") =>
    `<button type="button" class="btn ${esc(cls)} btn-sm" data-act="${esc(act)}" data-id="${esc(id)}" title="${esc(label)}" aria-label="${esc(label)}"><i class="fas fa-${esc(icon)}"></i></button>`;

/* ---------- toast & modal ---------- */
let toastT;
function toast(msg, isErr) {
    const t = $("#toast"); t.textContent = msg; t.hidden = false; t.className = "toast " + (isErr ? "toast-error" : "toast-success");
    clearTimeout(toastT); toastT = setTimeout(() => { t.hidden = true; }, 3200);
}
const closeModals = () => $$(".modal").forEach(m => { m.hidden = true; });
function openView(title, html) {
    $("#view-title").textContent = title; $("#view-body").innerHTML = html;
    const m = $("#view-modal"); m.hidden = false;
    const f = $("button", m); if (f) f.focus();
}

/* ---------- renderers ---------- */
function fillSelect(sel, options, blank, keep = true) {
    const old = sel.value;
    sel.innerHTML = (blank ? `<option value="">${esc(blank)}</option>` : "") + options.map(o => {
        o = typeof o === "object" ? o : { v: o, l: o };
        return `<option value="${esc(o.v)}">${esc(o.l)}</option>`;
    }).join("");
    if (keep && [...sel.options].some(o => o.value === old)) sel.value = old;
}

function bars(rows) {
    const max = Math.max(1, ...rows.map(r => r[1]));
    return rows.length ? rows.map(([l, n]) => `<div class="bar-row"><span>${esc(l)}</span><div class="bar"><i style="width:${(n / max) * 100}%"></i></div><b>${n}</b></div>`).join("")
        : '<p class="muted">No data yet.</p>';
}
const countBy = (arr, fn) => { const m = {}; arr.forEach(x => { const k = fn(x); m[k] = (m[k] || 0) + 1; }); return Object.entries(m); };

function renderDashboard() {
    const t = today(), mo = t.slice(5, 7), y = +t.slice(0, 4);
    const act = S.employees.filter(e => e.status === "Active");
    $("#d-total").textContent = S.employees.length;
    $("#d-active").textContent = act.length;
    $("#d-onleave").textContent = onLeaveOn(t).length;
    $("#d-jobs").textContent = S.jobs.filter(j => j.status === "Open").length;
    $("#d-applicants").textContent = S.applicants.filter(a => a.stage === "Applied").length;
    const pending = S.leaves.filter(l => l.status === "Pending");
    $("#d-pending").textContent = pending.length;
    $("#hero-date").textContent = new Date().toLocaleDateString(undefined, { weekday: "long", year: "numeric", month: "long", day: "numeric" });
    $("#h-dashboard").textContent = "Welcome, " + $("#me-name").textContent;
    $("#hero-sub").textContent = pending.length ? `${pending.length} leave request(s) are waiting for HR approval.` : "Everything is up to date.";

    $("#dash-leaves").innerHTML = pending.slice(0, 5).map(l => `<li><span><strong>${esc(empName(l.employee_id))}</strong><br><small class="muted">${esc(l.type)} · ${fmtDate(l.from)} – ${fmtDate(l.to)}</small></span>${badge("Pending")}</li>`).join("") || empty("No pending requests.");
    $("#dash-announcements").innerHTML = [...S.announcements].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 4)
        .map(a => `<li><span><strong>${esc(a.title)}</strong><br><small class="muted">${fmtDate(a.date)}</small></span></li>`).join("") || empty("No announcements.");
    $("#dash-birthdays").innerHTML = act.filter(e => e.birthday && e.birthday.slice(5, 7) === mo).sort((a, b) => a.birthday.slice(8) - b.birthday.slice(8))
        .map(e => `<li><span>${esc(e.first_name + " " + e.last_name)}</span><small class="muted">${fmtDate(e.birthday).replace(/,?\s*\d{4}/, "")}</small></li>`).join("") || empty("None this month.");
    $("#dash-anniversaries").innerHTML = act.filter(e => e.hired && e.hired.slice(5, 7) === mo && +e.hired.slice(0, 4) < y)
        .map(e => `<li><span>${esc(e.first_name + " " + e.last_name)}</span><small class="muted">${y - +e.hired.slice(0, 4)} yr(s)</small></li>`).join("") || empty("None this month.");
    const pm = +S.settings.probation_months || 6;
    $("#dash-probation").innerHTML = act.map(e => ({ e, end: addMonths(e.hired, pm) })).filter(x => x.end >= t && x.end <= addDays(t, 30))
        .sort((a, b) => a.end.localeCompare(b.end)).map(x => `<li><span>${esc(x.e.first_name + " " + x.e.last_name)}</span><small class="muted">ends ${fmtDate(x.end)}</small></li>`).join("") || empty("No one nearing the end of probation.");
    $("#dash-headcount").innerHTML = bars(S.departments.map(d => [d.name, act.filter(e => e.department_id == d.id).length]));
}

function filteredEmployees() {
    const d = $("#f-emp-dept").value, s = $("#f-emp-status").value, t = $("#f-emp-type").value, q = ui.query.toLowerCase();
    return S.employees.filter(e => (!d || e.department_id == d) && (!s || e.status === s) && (!t || e.type === t) &&
        (!q || [e.first_name + " " + e.last_name, e.code, e.email].some(x => String(x || "").toLowerCase().includes(q))));
}

function renderEmployees() {
    const list = filteredEmployees(), pages = Math.max(1, Math.ceil(list.length / ui.perPage));
    ui.empPage = Math.min(ui.empPage, pages);
    const rows = list.slice((ui.empPage - 1) * ui.perPage, ui.empPage * ui.perPage);
    $("#employees-table tbody").innerHTML = rows.map(e => `<tr>
        <td><span class="avatar">${esc(initials(e))}</span> ${esc(e.first_name + " " + e.last_name)}<br><small class="muted">${esc(e.email)}</small></td>
        <td>${esc(e.code || e.id)}</td><td>${esc(deptName(e.department_id))}</td><td>${esc(e.position)}</td><td>${esc(e.type)}</td>
        <td>${fmtDate(e.hired)}</td><td>${badge(e.status)}</td>
        <td>${btn("view:employees", e.id, "eye", "View")}</td></tr>`).join("") || empty("No employees match.", 8);
    $("#emp-count").textContent = `${list.length} employee(s)`;
    $("#page-info").textContent = `Page ${ui.empPage} of ${pages}`;
    $("#prev-page").disabled = ui.empPage <= 1; $("#next-page").disabled = ui.empPage >= pages;
}

function renderRecruitment() {
    fillSelect($("#f-job"), S.jobs.map(j => ({ v: j.id, l: j.title })), "All jobs");
    const jid = $("#f-job").value, apps = S.applicants.filter(a => !jid || a.job_id == jid);
    $("#board").innerHTML = [...STAGES, "Rejected"].map(st => `<div class="board-col"><h4>${esc(st)} <span class="muted">(${apps.filter(a => a.stage === st).length})</span></h4>` +
        apps.filter(a => a.stage === st).map(a =>
            `<div class="board-card"><strong>${esc(a.name)}</strong><br><small class="muted">${esc(jobTitle(a.job_id))}</small></div>`).join("") + "</div>").join("");
    $("#jobs-table tbody").innerHTML = S.jobs.map(j => `<tr><td>${j.id}</td><td>${esc(j.title)}</td><td>${esc(deptName(j.department_id))}</td><td>${esc(j.type)}</td>
        <td class="num">${j.openings}</td><td class="num">${S.applicants.filter(a => a.job_id == j.id).length}</td><td>${fmtDate(j.posted)}</td><td>${badge(j.status)}</td></tr>`).join("") || empty("No job openings.", 8);
}

function renderProcesses() {
    const k = $("#f-process").value;
    $("#process-list").innerHTML = S.processes.filter(p => !k || p.kind === k).map(p => {
        const done = p.tasks.filter(t => t.done).length, pct = p.tasks.length ? Math.round(done / p.tasks.length * 100) : 0;
        return `<article class="report-box"><h3>${esc(empName(p.employee_id))} ${badge(p.kind)}</h3>
            <div class="bar"><i style="width:${pct}%"></i></div><p class="muted">${done}/${p.tasks.length} tasks · ${pct === 100 ? "Completed" : "In progress"}</p>
            <ul class="list">${p.tasks.map(t => `<li><label><input type="checkbox" disabled${t.done ? " checked" : ""}> ${esc(t.title)}</label></li>`).join("")}</ul></article>`;
    }).join("") || '<p class="muted">No processes yet.</p>';
}

function renderAttendance() {
    const d = $("#a-date").value || today(), dep = $("#a-dept").value;
    const people = S.employees.filter(e => !isGone(e) && (!dep || e.department_id == dep));
    const leaveIds = new Set(onLeaveOn(d).map(l => l.employee_id));
    const recs = people.map(e => ({ e, r: S.attendance.find(a => a.employee_id == e.id && a.date === d) }));
    const c = s => recs.filter(x => x.r && x.r.status === s).length;
    $("#a-present").textContent = c("Present"); $("#a-late").textContent = c("Late"); $("#a-absent").textContent = c("Absent");
    $("#a-leave").textContent = people.filter(e => leaveIds.has(e.id)).length;
    $("#attendance-table tbody").innerHTML = recs.map(({ e, r }) => {
        const hrs = r && r.time_in && r.time_out ? ((new Date("1970-01-01T" + r.time_out) - new Date("1970-01-01T" + r.time_in)) / 36e5).toFixed(2) : "-";
        const status = r ? r.status : leaveIds.has(e.id) ? "On Leave" : "No record";
        return `<tr><td>${esc(e.first_name + " " + e.last_name)}</td><td>${esc(deptName(e.department_id))}</td><td>${esc(r?.time_in || "-")}</td><td>${esc(r?.time_out || "-")}</td>
            <td class="num">${hrs}</td><td>${badge(status)}</td><td>${esc(r?.remarks || "")}</td></tr>`;
    }).join("") || empty("No employees.", 7);
}

function renderLeaves() {
    const L = S.leaves, c = s => L.filter(l => l.status === s).length;
    $("#l-pending").textContent = c("Pending"); $("#l-approved").textContent = c("Approved"); $("#l-rejected").textContent = c("Rejected");
    const fs = $("#f-leave-status").value, ft = $("#f-leave-type").value;
    $("#leaves-table tbody").innerHTML = L.filter(l => (!fs || l.status === fs) && (!ft || l.type === ft)).sort((a, b) => b.from.localeCompare(a.from)).map(l => `<tr>
        <td>${l.id}</td><td>${esc(empName(l.employee_id))}</td><td>${esc(l.type)}</td><td>${fmtDate(l.from)}</td><td>${fmtDate(l.to)}</td><td class="num">${l.days}</td>
        <td>${esc(l.reason)}</td><td>${badge(l.status)}</td></tr>`).join("") || empty("No leave requests.", 8);
    $("#balances-table tbody").innerHTML = S.employees.filter(e => !isGone(e)).map(e => {
        const left = t => Math.max(0, (+S.settings[LEAVE_CAP[t]] || 0) - L.filter(l => l.employee_id == e.id && l.type === t && l.status === "Approved" && l.from.slice(0, 4) === today().slice(0, 4)).reduce((n, l) => n + l.days, 0));
        return `<tr><td>${esc(e.first_name + " " + e.last_name)}</td><td>${esc(deptName(e.department_id))}</td><td class="num">${left("Vacation Leave (PTO)")}</td><td class="num">${left("Sick Leave")}</td><td class="num">${left("Emergency Leave")}</td></tr>`;
    }).join("") || empty("No employees.", 5);
    const t = today();
    $("#out-table tbody").innerHTML = L.filter(l => l.status === "Approved" && l.to >= t && l.from <= addDays(t, 30)).sort((a, b) => a.from.localeCompare(b.from)).map(l => {
        const e = emp(l.employee_id);
        return `<tr><td>${esc(empName(l.employee_id))}</td><td>${esc(e ? deptName(e.department_id) : "-")}</td><td>${esc(l.type)}</td><td>${fmtDate(l.from)}</td><td>${fmtDate(l.to)}</td><td>${fmtDate(addDays(l.to, 1))}</td></tr>`;
    }).join("") || empty("Nobody is out in the next 30 days.", 6);
}

function stars(n) { n = Number(n) || 0; return n ? "★".repeat(Math.round(n)) + "☆".repeat(5 - Math.round(n)) + ` <small class="muted">${n}</small>` : "-"; }
function renderPerformance() {
    const done = S.reviews.filter(r => r.status === "Completed" && r.rating > 0);
    $("#p-avg").textContent = done.length ? (done.reduce((n, r) => n + Number(r.rating), 0) / done.length).toFixed(1) : "-";
    $("#p-done").textContent = S.reviews.filter(r => r.status === "Completed").length;
    $("#p-draft").textContent = S.reviews.filter(r => r.status === "Draft").length;
    $("#reviews-table tbody").innerHTML = S.reviews.map(r => `<tr><td>${esc(empName(r.employee_id))}</td><td>${esc(r.period)}</td><td>${esc(r.reviewer)}</td><td>${stars(r.rating)}</td><td>${badge(r.status)}</td></tr>`).join("") || empty("No reviews yet.", 5);
}

function renderTraining() {
    $("#training-table tbody").innerHTML = [...S.trainings].sort((a, b) => b.date.localeCompare(a.date)).map(t => `<tr><td>${esc(t.title)}</td><td>${esc(t.trainer)}</td><td>${fmtDate(t.date)}</td>
        <td class="num">${t.hours}</td><td>${esc(t.venue)}</td><td class="num">${t.enrolled}</td><td>${badge(t.status)}</td></tr>`).join("") || empty("No trainings.", 7);
}

function renderAnnouncements() {
    $("#announcement-list").innerHTML = [...S.announcements].sort((a, b) => b.date.localeCompare(a.date)).map(a => `<article class="report-box"><h3>${esc(a.title)}</h3>
        <p class="muted">${fmtDate(a.date)}</p><p>${esc(a.body).replace(/\n/g, "<br>")}</p></article>`).join("") || '<p class="muted">No announcements yet.</p>';
}

function renderDepartments() {
    $("#departments-table tbody").innerHTML = S.departments.map(d => `<tr><td>${d.id}</td><td>${esc(d.name)}</td><td>${esc(d.head || (d.head_employee_id ? empName(d.head_employee_id) : "-"))}</td>
        <td class="num">${S.employees.filter(e => e.department_id == d.id).length}</td><td class="num">${S.jobs.filter(j => j.department_id == d.id && j.status === "Open").length}</td></tr>`).join("") || empty("No departments.", 5);
}

function renderReports() {
    const E = S.employees, act = E.filter(e => e.status === "Active"), t = today(), y = t.slice(0, 4);
    const left = E.filter(isGone).length;
    const ten = act.length ? act.reduce((n, e) => n + (new Date(t) - new Date(e.hired)) / 31557600000, 0) / act.length : 0;
    const taken = S.leaves.filter(l => l.status === "Approved" && l.from.slice(0, 4) === y).reduce((n, l) => n + l.days, 0);
    const kpi = (cls, h, v, i) => `<div class="card card-${cls}"><h3>${h}</h3><p>${v}</p><i class="fas fa-${i} card-icon"></i></div>`;
    $("#report-kpis").innerHTML = kpi("blue", "Headcount", act.length, "users") + kpi("pink", "Turnover", (E.length ? (left / E.length * 100).toFixed(1) : 0) + "%", "right-from-bracket") +
        kpi("green", "Avg. Tenure (yrs)", ten.toFixed(1), "hourglass-half") + kpi("orange", "Leave Days Taken", taken, "umbrella-beach");
    const box = (h, body) => `<section class="report-box"><h3>${h}</h3><div class="bars">${body}</div></section>`;
    $("#report-grid").innerHTML = box("Headcount by Department", bars(S.departments.map(d => [d.name, act.filter(e => e.department_id == d.id).length]))) +
        box("Employment Type", bars(countBy(act, e => e.type))) + box("Employee Status", bars(countBy(E, e => e.status))) +
        box("Approved Leave Days by Type", bars(LEAVE_TYPES.map(k => [k, S.leaves.filter(l => l.type === k && l.status === "Approved").reduce((n, l) => n + l.days, 0)]))) +
        box("Hiring Pipeline", bars([...STAGES, "Rejected"].map(s => [s, S.applicants.filter(a => a.stage === s).length])));
}

function renderSettings() {
    const row = (k, v) => `<dt>${esc(k)}</dt><dd>${v === "" || v == null ? "-" : esc(v)}</dd>`;
    const s = S.settings;
    $("#settings-schedule").innerHTML = row("Start time", s.work_start) + row("End time", s.work_end) + row("Grace period (minutes)", s.grace_minutes);
    $("#settings-policy").innerHTML = row("Vacation days / year", s.leave_vacation) + row("Sick days / year", s.leave_sick) +
        row("Emergency days / year", s.leave_emergency) + row("Probation (months)", s.probation_months);
    $("#holiday-list").innerHTML = [...S.holidays].sort((a, b) => a.date.localeCompare(b.date))
        .map(h => `<li><span>${esc(h.name)} <small class="muted">${fmtDate(h.date)}</small></span></li>`).join("") || empty("No holidays added.");
}

function renderChrome() {
    fillSelect($("#f-emp-dept"), deptOpts(), "All");
    fillSelect($("#f-emp-type"), EMP_TYPES, "All");
    fillSelect($("#a-dept"), deptOpts(), "All");
    fillSelect($("#s-dept"), deptOpts(), "All");
    fillSelect($("#f-leave-type"), LEAVE_TYPES, "All");
    const n = { onboarding: S.processes.filter(p => p.tasks.some(t => !t.done)).length, recruitment: S.applicants.filter(a => a.stage === "Applied").length, leaves: S.leaves.filter(l => l.status === "Pending").length };
    Object.entries(n).forEach(([k, v]) => { const el = $("#nc-" + k); el.textContent = v; el.hidden = !v; });
    const items = [];
    S.leaves.filter(l => l.status === "Pending").forEach(l => items.push(`<a href="#leaves"><i class="fas fa-calendar-check"></i> ${esc(empName(l.employee_id))} requested ${esc(l.type.toLowerCase())} </a>`));
    if (n.recruitment) items.push(`<a href="#recruitment"><i class="fas fa-user-tie"></i> ${n.recruitment} new applicant(s)</a>`);
    if (n.onboarding) items.push(`<a href="#onboarding"><i class="fas fa-clipboard-check"></i> ${n.onboarding} process(es) in progress</a>`);
    $("#notif-panel").innerHTML = items.join("") || '<p class="muted" style="padding:.8rem">Nothing new.</p>';
    const nc = $("#notif-count"); nc.textContent = items.length; nc.hidden = !items.length;
}

/* ---------- Salaries (monthly salary + latest net pay) ---------- */
// Most recent payroll record for each employee.
function latestPayrollByEmployee() {
    const m = {};
    S.payroll.forEach(p => {
        const cur = m[p.employee_id];
        const a = String(p.pay_period || ""), b = cur ? String(cur.pay_period || "") : "";
        if (!cur || a > b || (a === b && p.id > cur.id)) m[p.employee_id] = p;
    });
    return m;
}

function salaryRows() {
    const dep = $("#s-dept").value, st = $("#s-status").value, latest = latestPayrollByEmployee();
    return S.employees
        .filter(e => (!dep || e.department_id == dep) && (!st || e.status === st))
        .map(e => ({ e, pay: latest[e.id] }))
        .sort((a, b) => (a.e.last_name + a.e.first_name).localeCompare(b.e.last_name + b.e.first_name));
}

function renderSalaries() {
    const active = S.employees.filter(e => e.status === "Active").map(e => Number(e.salary) || 0);
    const total = active.reduce((n, v) => n + v, 0);
    $("#sal-total").textContent = peso(total);
    $("#sal-average").textContent = peso(active.length ? total / active.length : 0);
    $("#sal-highest").textContent = peso(active.length ? Math.max(...active) : 0);

    $("#salaries-table tbody").innerHTML = salaryRows().map(({ e, pay }) => `<tr>
        <td><span class="avatar">${esc(initials(e))}</span> ${esc(e.first_name + " " + e.last_name)}<br><small class="muted">${esc(e.code || e.id)}</small></td>
        <td>${esc(deptName(e.department_id))}</td><td>${esc(e.position || "-")}</td><td>${badge(e.status)}</td>
        <td class="num">${e.salary == null ? "-" : peso(e.salary)}</td>
        <td>${pay ? esc(String(pay.pay_period || "").slice(0, 7)) : "-"}</td>
        <td class="num">${pay ? peso(pay.net_pay) : "-"}</td></tr>`).join("") || empty("No employees found.", 7);
}

function renderPayroll() {
    const rows = S.payroll || [];
    $("#payroll-table tbody").innerHTML = rows.map(p => `<tr>
        <td>${esc(p.employee_name || empName(p.employee_id))}</td>
        <td>${esc(String(p.pay_period || "").slice(0, 7) || "-")}</td>
        <td class="num">${peso(p.gross_pay)}</td><td class="num">${peso(p.deductions)}</td><td class="num">${peso(p.net_pay)}</td>
        <td>${badge(p.payment_status || "Pending")}</td></tr>`).join("") || empty("No payroll records found.", 6);
}

function renderAll() {
    renderChrome(); renderDashboard(); renderEmployees(); renderRecruitment(); renderProcesses(); renderAttendance();
    renderSalaries(); renderPayroll(); renderLeaves(); renderPerformance(); renderTraining(); renderAnnouncements();
    renderDepartments(); renderReports(); renderSettings();
}

/* ---------- routing ---------- */
function showSection(name) {
    if (!$("#page-" + name)) name = "dashboard";
    $$(".page").forEach(p => p.classList.toggle("active", p.id === "page-" + name));
    $$("#nav a").forEach(a => a.classList.toggle("active", a.dataset.section === name));
    $("#sidebar").classList.remove("open"); $("#menu-btn").setAttribute("aria-expanded", "false");
    window.scrollTo(0, 0);
}
const route = () => showSection(location.hash.replace("#", "") || "dashboard");

/* ---------- CSV ---------- */
function exportCsv(what) {
    const rows = {
        employees: [["ID", "Name", "Email", "Department", "Position", "Type", "Hired", "Status"],
            ...filteredEmployees().map(e => [e.code || e.id, e.first_name + " " + e.last_name, e.email, deptName(e.department_id), e.position, e.type, e.hired, e.status])],
        attendance: [["Date", "Employee", "Time In", "Time Out", "Status", "Remarks"],
            ...S.attendance.map(a => [a.date, empName(a.employee_id), a.time_in, a.time_out, a.status, a.remarks])],
        leaves: [["ID", "Employee", "Type", "From", "To", "Days", "Reason", "Status"],
            ...S.leaves.map(l => [l.id, empName(l.employee_id), l.type, l.from, l.to, l.days, l.reason, l.status])],
        salaries: [["Employee ID", "Name", "Department", "Position", "Status", "Monthly Salary", "Latest Payroll", "Net Salary"],
            ...salaryRows().map(({ e, pay }) => [e.code || e.id, e.first_name + " " + e.last_name, deptName(e.department_id), e.position, e.status,
                Number(e.salary || 0).toFixed(2), pay ? String(pay.pay_period).slice(0, 7) : "", pay ? Number(pay.net_pay || 0).toFixed(2) : ""])],
    }[what];
    if (!rows) return;
    const csv = rows.map(r => r.map(c => '"' + String(c ?? "").replace(/"/g, '""') + '"').join(",")).join("\r\n");
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv" })), download: `${what}-${today()}.csv` });
    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(a.href);
}

/* ---------- actions (view / export / print only) ---------- */
async function run(fn) { try { await fn(); } catch (e) { toast(e.message, true); } }
const ACTIONS = {
    print: () => window.print(),
    export: el => exportCsv(el.dataset.what),
};

function viewEmployee(id) {
    const e = emp(id), yr = today().slice(0, 4);
    const used = t => S.leaves.filter(l => l.employee_id == id && l.type === t && l.status === "Approved" && l.from.slice(0, 4) === yr).reduce((n, l) => n + l.days, 0);
    const rows = o => `<dl class="detail-list">${o.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v === "" || v == null ? "-" : esc(v)}</dd>`).join("")}</dl>`;
    openView(e.first_name + " " + e.last_name, rows([["Employee ID", e.code || e.id], ["Email", e.email], ["Phone", e.phone], ["Birthday", fmtDate(e.birthday)],
        ["Department", deptName(e.department_id)], ["Position", e.position], ["Type", e.type], ["Hired", fmtDate(e.hired)], ["Status", e.status],
        ["Monthly salary", e.salary == null ? "-" : peso(e.salary)],
        ["Probation ends", fmtDate(addMonths(e.hired, +S.settings.probation_months || 6))],
        ["Leave used this year", `Vacation ${used("Vacation Leave (PTO)")} · Sick ${used("Sick Leave")} · Emergency ${used("Emergency Leave")}`]]));
}

document.addEventListener("click", e => {
    const a = e.target.closest("[data-action]");
    if (a) { e.preventDefault(); return run(() => ACTIONS[a.dataset.action]?.(a)); }

    const q = e.target.closest("[data-quick]");
    if (q) {
        const [k, v] = q.dataset.quick.split(":");
        if (k === "status") { $("#f-emp-status").value = v; ui.empPage = 1; renderEmployees(); }
        if (k === "pending") { $("#f-leave-status").value = "Pending"; renderLeaves(); }
        if (k === "board") $$('[data-tabs="recruitment"] .tab')[0].click();
    }

    const b = e.target.closest("[data-act]");
    if (b) {
        const [kind, arg] = b.dataset.act.split(":");
        if (kind === "view" && arg === "employees") viewEmployee(b.dataset.id);
        return;
    }

    const tab = e.target.closest(".tab");
    if (tab) {
        const group = tab.closest("[data-tabs]").dataset.tabs;
        $$(`[data-tabs="${group}"] .tab`).forEach(t => t.classList.toggle("active", t === tab));
        $$(`[data-panel^="${group}:"]`).forEach(p => p.classList.toggle("active", p.dataset.panel === `${group}:${tab.dataset.tab}`));
    }

    if (e.target.closest("[data-close]") || e.target.classList.contains("modal")) closeModals();
    if (!e.target.closest(".notif-wrap")) { $("#notif-panel").hidden = true; $("#notif-btn").setAttribute("aria-expanded", "false"); }
});

document.addEventListener("keydown", e => { if (e.key === "Escape") closeModals(); });

function bind() {
    window.addEventListener("hashchange", route);
    $("#menu-btn").addEventListener("click", () => { const o = $("#sidebar").classList.toggle("open"); $("#menu-btn").setAttribute("aria-expanded", o); });
    $("#notif-btn").addEventListener("click", ev => { ev.stopPropagation(); const p = $("#notif-panel"); p.hidden = !p.hidden; $("#notif-btn").setAttribute("aria-expanded", !p.hidden); });

    /* ----- user menu + sign out ----- */
    const userBtn = $("#user-btn"), userMenu = $("#user-menu");
    const setUserMenu = open => { userMenu.hidden = !open; userBtn.setAttribute("aria-expanded", String(open)); };
    userBtn.addEventListener("click", ev => { ev.stopPropagation(); setUserMenu(userMenu.hidden); });
    document.addEventListener("click", ev => { if (!ev.target.closest(".user-menu")) setUserMenu(false); });
    document.addEventListener("keydown", ev => { if (ev.key === "Escape") setUserMenu(false); });
    userMenu.addEventListener("click", ev => { if (ev.target.closest("a") && !ev.target.closest(".menu-danger")) setUserMenu(false); });
    $(".menu-danger", userMenu).addEventListener("click", ev => { if (!confirm("Sign out of the owner portal?")) ev.preventDefault(); });

    $("#search-form").addEventListener("submit", ev => {
        ev.preventDefault(); ui.query = $("#search-input").value.trim(); ui.empPage = 1;
        location.hash = "#employees"; renderEmployees();
    });
    ["f-emp-dept", "f-emp-status", "f-emp-type"].forEach(id => $("#" + id).addEventListener("change", () => { ui.empPage = 1; renderEmployees(); }));
    $("#f-emp-reset").addEventListener("click", () => {
        ["f-emp-dept", "f-emp-status", "f-emp-type"].forEach(id => { $("#" + id).value = ""; });
        ui.query = ""; $("#search-input").value = ""; ui.empPage = 1; renderEmployees();
    });
    $("#prev-page").addEventListener("click", () => { ui.empPage--; renderEmployees(); });
    $("#next-page").addEventListener("click", () => { ui.empPage++; renderEmployees(); });

    $("#help-btn").addEventListener("click", () => toast("Need help? Contact the system administrator."));
    $("#f-job").addEventListener("change", renderRecruitment);
    $("#f-process").addEventListener("change", renderProcesses);
    $("#a-date").value = today();
    $("#a-date").addEventListener("change", renderAttendance);
    $("#a-dept").addEventListener("change", renderAttendance);
    $("#a-today").addEventListener("click", () => { $("#a-date").value = today(); renderAttendance(); });
    $("#f-leave-status").addEventListener("change", renderLeaves);
    $("#f-leave-type").addEventListener("change", renderLeaves);
    $("#s-dept").addEventListener("change", renderSalaries);
    $("#s-status").addEventListener("change", renderSalaries);
}

/* ---------- boot ---------- */
document.addEventListener("DOMContentLoaded", async () => {
    const name = $("#me-name"), pill = $("#me-status"), pillText = $("#me-status-text");
    bind();

    let me = null;
    try {
        me = await api("/api/owner/me");
    } catch (err) {
        name.textContent = "Owner"; pill.dataset.state = "offline"; pillText.textContent = "Server error";
        toast(err.message, true);
    }

    if (me) {
        name.textContent = me.name || "Owner";
        $("#me-avatar").textContent = (me.name || "Owner").split(/\s+/).map(w => w[0]).join("").slice(0, 2).toUpperCase();
        pill.dataset.state = "online"; pillText.textContent = "Connected";
        try { await load(); }
        catch (err) { pill.dataset.state = "offline"; pillText.textContent = "Data error"; toast(err.message, true); }
    }

    RES.forEach(r => { S[r] = S[r] || []; });
    renderAll();
    route();
});