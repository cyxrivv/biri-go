"use strict";

/* =====================================================================

   Biri-Go HR page  (template/hr.html  +  statistics/js/hr.js)

   - Talks to /api/hr/<resource> (REST: GET list, POST, PUT /<id>, DELETE /<id>)

   - If the API is unreachable it falls back to in-memory demo data.

   ===================================================================== */



/* ---------- tiny helpers ---------- */

const $ = (s, r = document) => r.querySelector(s);

const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const iso = d => { const z = new Date(d.getTime() - d.getTimezoneOffset() * 60000); return z.toISOString().slice(0, 10); };

const today = () => iso(new Date());

const addDays = (s, n) => { const d = new Date(s + "T00:00:00"); d.setDate(d.getDate() + n); return iso(d); };

const fmtDate = s => s ? new Date(s + "T00:00:00").toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "-";

const daysBetween = (a, b) => Math.round((new Date(b + "T00:00:00") - new Date(a + "T00:00:00")) / 864e5) + 1;

const slug = s => String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, "-");

const badge = s => `<span class="badge badge-${slug(s)}">${esc(s)}</span>`;



async function api(url, options = {}) {

    const res = await fetch(url, {
        ...options,
        credentials: "same-origin",
        headers: {
            ...(options.headers || {}),
            "Content-Type": "application/json",
            "X-CSRF-Token": document.querySelector('meta[name="csrf-token"]')?.content || "",
        },
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

let DEMO = false;

const ui = { query: "", empPage: 1, perPage: 10 };

const STAGES = ["Applied", "Screening", "Interview", "Offer", "Hired"];

const EMP_TYPES = ["Full-time", "Part-time", "Contract", "Intern"];

const LEAVE_TYPES = ["Vacation Leave (PTO)", "Sick Leave", "Emergency Leave", "Bereavement Leave", "Maternity Leave",

    "Paternity Leave", "Parental Leave", "Special Leave (Mandated)", "Unpaid Leave (LOA)"];

const LEAVE_CAP = { "Vacation Leave (PTO)": "leave_vacation", "Sick Leave": "leave_sick", "Emergency Leave": "leave_emergency" };

const TASKS = {

    Onboarding: ["Sign employment contract", "Submit government IDs", "Set up email & accounts", "Issue equipment", "Orientation & team intro"],

    Offboarding: ["Resignation / termination letter", "Return equipment", "Revoke system access", "Exit interview", "Release final pay"],

};



/* ---------- data layer (API or demo) ---------- */

const mem = {};

function seed() {

    const t = today(), y = t.slice(0, 4), m = t.slice(5, 7);

    const dep = ["Operations", "Sales", "Finance", "IT", "Human Resources"].map((name, i) => ({ id: i + 1, name, head: "" }));

    const names = [["Maria", "Santos"], ["Juan", "Dela Cruz"], ["Ana", "Reyes"], ["Carlo", "Bautista"], ["Liza", "Garcia"],

        ["Mark", "Villanueva"], ["Joy", "Mendoza"], ["Paolo", "Ramos"], ["Grace", "Aquino"], ["Ken", "Castillo"],

        ["Rhea", "Flores"], ["Noel", "Torres"]];

    const emps = names.map((n, i) => ({

        id: i + 1, code: "biri-" + String(100000 + i * 137).slice(0, 6), first_name: n[0], last_name: n[1],

        email: (n[0] + "." + n[1]).toLowerCase().replace(/\s/g, "") + "@biri-go.test", phone: "0917" + (1000000 + i * 4321),

        department_id: (i % 5) + 1, position: ["Associate", "Specialist", "Supervisor", "Analyst"][i % 4],

        type: EMP_TYPES[i % 4 === 3 ? 2 : 0], hired: addDays(t, -(i * 83 + 20)),

        birthday: `${1990 + (i % 8)}-${i % 3 === 0 ? m : String((i % 12) + 1).padStart(2, "0")}-${String(5 + i).padStart(2, "0")}`,

        status: i === 9 ? "Resigned" : "Active",

    }));

    emps[0].hired = `${+y - 2}-${m}-10`;

    emps[1].hired = addDays(t, -150);

    dep.forEach(d => { d.head = (emps.find(e => e.department_id === d.id) || {}).first_name || ""; });

    mem.departments = dep; mem.employees = emps;

    mem.jobs = [

        { id: 1, title: "Customer Support Rep", department_id: 1, type: "Full-time", openings: 3, posted: addDays(t, -12), status: "Open" },

        { id: 2, title: "Backend Developer", department_id: 4, type: "Full-time", openings: 1, posted: addDays(t, -30), status: "Open" },

        { id: 3, title: "Accounting Intern", department_id: 3, type: "Intern", openings: 2, posted: addDays(t, -60), status: "Closed" },

    ];

    mem.applicants = [

        { id: 1, job_id: 1, name: "Pia Lopez", email: "pia@mail.test", phone: "", stage: "Applied" },

        { id: 2, job_id: 1, name: "Rico Tan", email: "rico@mail.test", phone: "", stage: "Interview" },

        { id: 3, job_id: 2, name: "Dina Cruz", email: "dina@mail.test", phone: "", stage: "Screening" },

        { id: 4, job_id: 2, name: "Ed Uy", email: "ed@mail.test", phone: "", stage: "Applied" },

    ];

    mem.processes = [{ id: 1, employee_id: 2, kind: "Onboarding", status: "In Progress",

        tasks: TASKS.Onboarding.map((title, i) => ({ title, done: i < 2 })) }];

    mem.attendance = emps.slice(0, 6).map((e, i) => ({

        id: i + 1, employee_id: e.id, date: t, time_in: ["08:00", "08:45", "", "07:55", "08:02", "09:10"][i],

        time_out: i < 2 ? "17:00" : "", status: ["Present", "Late", "Absent", "Present", "Present", "Late"][i], remarks: "" }));

    mem.leaves = [

        { id: 1, employee_id: 3, type: "Vacation Leave (PTO)", from: addDays(t, -1), to: addDays(t, 2), days: 4, reason: "Family trip", status: "Approved" },

        { id: 2, employee_id: 4, type: "Sick Leave", from: addDays(t, 3), to: addDays(t, 4), days: 2, reason: "Flu", status: "Pending" },

        { id: 3, employee_id: 5, type: "Emergency Leave", from: addDays(t, 6), to: addDays(t, 6), days: 1, reason: "Family matter", status: "Pending" },

        { id: 4, employee_id: 6, type: "Vacation Leave (PTO)", from: addDays(t, -40), to: addDays(t, -38), days: 3, reason: "Rest", status: "Rejected" },

    ];

    mem.reviews = [

        { id: 1, employee_id: 1, period: `${y} H1`, reviewer: "HR Admin", rating: 4, status: "Completed" },

        { id: 2, employee_id: 2, period: `${y} H1`, reviewer: "HR Admin", rating: 3, status: "Completed" },

        { id: 3, employee_id: 3, period: `${y} H2`, reviewer: "HR Admin", rating: 0, status: "Draft" },

    ];

    mem.trainings = [

        { id: 1, title: "Data Privacy Basics", trainer: "J. Ocampo", date: addDays(t, 7), hours: 4, venue: "Conference Room A", enrolled: 12, status: "Scheduled" },

        { id: 2, title: "Customer Service Excellence", trainer: "M. Lim", date: addDays(t, -20), hours: 8, venue: "Online", enrolled: 9, status: "Completed" },

    ];

    mem.announcements = [{ id: 1, title: "Welcome to the new HR portal", body: "You can now file leaves and view announcements here.", date: t }];

    mem.holidays = [{ id: 1, name: "New Year's Day", date: `${+y + 1}-01-01` }];

    mem.settings = { work_start: "08:00", work_end: "17:00", grace_minutes: 15, leave_vacation: 15, leave_sick: 7, leave_emergency: 3, probation_months: 6 };

    mem._id = 1000;

}

async function demoCall(method, path, body) {

    const [res, id] = path.split("/");

    if (res === "settings") { if (method === "PUT") Object.assign(mem.settings, body); return { ...mem.settings }; }

    const list = mem[res];

    if (!list) throw new Error("Unknown resource: " + res);

    if (method === "GET") return JSON.parse(JSON.stringify(list));

    if (method === "POST") { const r = { ...body, id: ++mem._id }; list.push(r); return r; }

    const i = list.findIndex(x => String(x.id) === id);

    if (i < 0) throw new Error("Record not found.");

    if (method === "PUT") { Object.assign(list[i], body); return list[i]; }

    if (method === "DELETE") { list.splice(i, 1); return { ok: true }; }

}

const call = (method, path, body) => DEMO

    ? demoCall(method, path, body)

    : api("/api/hr/" + path, { method, body: body ? JSON.stringify(body) : undefined });



async function load(...names) {

    await Promise.all((names.length ? names : [...RES, "settings"]).map(async r => {

        const d = await call("GET", r);

        S[r] = r === "settings" ? d : (Array.isArray(d) ? d : d.items || []);

    }));

}

async function save(res, rec, id) {

    const result = await call(id ? "PUT" : "POST", id ? `${res}/${id}` : res, rec);

    await load(res);

    return result;

}

async function remove(res, id) { await call("DELETE", `${res}/${id}`); await load(res); }



/* ---------- lookups ---------- */

const emp = id => S.employees.find(e => e.id == id);

const empName = id => { const e = emp(id); return e ? `${e.first_name} ${e.last_name}` : "(removed)"; };

const deptName = id => (S.departments.find(d => d.id == id) || {}).name || "-";

const jobTitle = id => (S.jobs.find(j => j.id == id) || {}).title || "-";

const initials = e => ((e.first_name || "?")[0] + (e.last_name || "")[0]).toUpperCase();

const empOpts = (activeOnly = true) => S.employees.filter(e => !activeOnly || e.status !== "Resigned" && e.status !== "Terminated")

    .map(e => ({ v: e.id, l: `${e.first_name} ${e.last_name}` }));

const deptOpts = () => S.departments.map(d => ({ v: d.id, l: d.name }));

const onLeaveOn = date => S.leaves.filter(l => l.status === "Approved" && l.from <= date && l.to >= date);

const empty = (msg, cols) => cols ? `<tr><td colspan="${cols}" class="muted" style="text-align:center;padding:1.2rem">${msg}</td></tr>` : `<li class="muted">${msg}</li>`;

const btn = (act, id, icon, label, cls = "btn-secondary") =>

    `<button type="button" class="btn ${cls} btn-sm" data-act="${act}" data-id="${id}" title="${label}" aria-label="${label}"><i class="fas fa-${icon}"></i></button>`;



/* ---------- toast & modals ---------- */

let toastT;

function toast(msg, isErr) {

    const t = $("#toast"); t.textContent = msg; t.hidden = false; t.className = "toast " + (isErr ? "toast-error" : "toast-success");

    clearTimeout(toastT); toastT = setTimeout(() => { t.hidden = true; }, 3200);

}

const openModal = m => { m.hidden = false; const f = $("input,select,textarea,button:not(.modal-x)", m); if (f) f.focus(); };

const closeModals = () => $$(".modal").forEach(m => { m.hidden = true; });



let formHandler = null;

function openForm(title, fields, onSubmit) {

    $("#form-title").textContent = title;

    $("#form-error").hidden = true;

    $("#form-fields").innerHTML = fields.map(f => {

        const v = f.value ?? "", req = f.required ? " required" : "", id = "ff-" + f.name;

        let input;

        if (f.type === "select") {

            const opts = (f.options || []).map(o => typeof o === "object" ? o : { v: o, l: o });

            input = `<select id="${id}" name="${f.name}"${req}>${f.blank ? `<option value="">${esc(f.blank)}</option>` : ""}` +

                opts.map(o => `<option value="${esc(o.v)}"${String(o.v) === String(v) ? " selected" : ""}>${esc(o.l)}</option>`).join("") + "</select>";

        } else if (f.type === "textarea") {

            input = `<textarea id="${id}" name="${f.name}" rows="3"${req}>${esc(v)}</textarea>`;

        } else {

            input = `<input id="${id}" name="${f.name}" type="${f.type || "text"}" value="${esc(v)}"${req}` +

                (f.min != null ? ` min="${f.min}"` : "") + (f.max != null ? ` max="${f.max}"` : "") + (f.step ? ` step="${f.step}"` : "") + ` maxlength="${f.maxlength || 200}">`;

        }

        return `<label class="${f.full ? "full" : ""}">${esc(f.label)}${f.required ? " *" : ""} ${input}</label>`;

    }).join("");

    formHandler = async () => {

        const out = {};

        for (const f of fields) {

            let v = $("#ff-" + f.name).value.trim();

            if (f.required && !v) throw new Error(f.label + " is required.");

            if (f.type === "number" || f.num) v = v === "" ? 0 : Number(v);

            out[f.name] = v;

        }

        await onSubmit(out);

    };

    openModal($("#form-modal"));

}

function openView(title, html) { $("#view-title").textContent = title; $("#view-body").innerHTML = html; openModal($("#view-modal")); }



/* ---------- generic add/edit forms ---------- */

const formDefs = {

    employees: r => ({ title: r ? "Edit Employee" : "Add Employee", fields: [

        { name: "first_name", label: "First name", required: true, value: r?.first_name },

        { name: "last_name", label: "Last name", required: true, value: r?.last_name },

        { name: "email", label: "Email", type: "email", required: true, value: r?.email },

        { name: "phone", label: "Phone", value: r?.phone },

        { name: "sex", label: "Sex", type: "select", options: ["Male", "Female"], required: true, value: r?.sex },

        { name: "birthday", label: "Birthday", type: "date", required: true, value: r?.birthday },

        { name: "hired", label: "Date hired", type: "date", required: true, value: r?.hired || today() },

        { name: "department_id", label: "Department", type: "select", options: deptOpts(), num: true, required: true, value: r?.department_id },

        { name: "position", label: "Position", required: true, value: r?.position },

        { name: "salary", label: "Monthly Salary (₱)", type: "number", min: 0, step: "0.01", required: true, value: r?.salary ?? 0 },

        { name: "type", label: "Employment type", type: "select", options: EMP_TYPES, value: r?.type || "Full-time" },

        { name: "status", label: "Status", type: "select", options: ["Active", "On Leave", "Resigned", "Terminated"], value: r?.status || "Active" },

    ] }),

    jobs: r => ({ title: r ? "Edit Job" : "Post Job", fields: [

        { name: "title", label: "Job title", required: true, full: true, value: r?.title },

        { name: "department_id", label: "Department", type: "select", options: deptOpts(), num: true, required: true, value: r?.department_id },

        { name: "type", label: "Type", type: "select", options: EMP_TYPES, value: r?.type },

        { name: "openings", label: "Openings", type: "number", min: 1, value: r?.openings ?? 1 },

        { name: "status", label: "Status", type: "select", options: ["Open", "Closed"], value: r?.status || "Open" },

    ], defaults: { posted: today() } }),

    applicants: r => ({ title: r ? "Edit Applicant" : "Add Applicant", fields: [

        { name: "name", label: "Full name", required: true, value: r?.name },

        { name: "email", label: "Email", type: "email", required: true, value: r?.email },

        { name: "phone", label: "Phone", value: r?.phone },

        { name: "job_id", label: "Job", type: "select", options: S.jobs.filter(j => j.status === "Open" || j.id == r?.job_id).map(j => ({ v: j.id, l: j.title })), num: true, required: true, value: r?.job_id },

    ], defaults: { stage: "Applied" } }),

    leaves: r => ({ title: r ? "Edit Leave" : "File Leave", fields: [

        { name: "employee_id", label: "Employee", type: "select", options: empOpts(), num: true, required: true, value: r?.employee_id },

        { name: "type", label: "Leave type", type: "select", options: LEAVE_TYPES, value: r?.type },

        { name: "from", label: "From", type: "date", required: true, value: r?.from || today() },

        { name: "to", label: "To", type: "date", required: true, value: r?.to || today() },

        { name: "reason", label: "Reason", type: "textarea", full: true, value: r?.reason },



        ...(r ? [{

            name: "pay_status",

            label: "Payment Status",

            type: "select",

            options: ["Paid", "Unpaid"],

            value: r?.pay_status || "Paid"

        }] : []),

    ], 

    defaults: { status: "Pending" },

        check: v => { if (v.to < v.from) throw new Error("End date can't be before the start date."); v.days = daysBetween(v.from, v.to); } }),

    reviews: r => ({ title: r ? "Edit Review" : "New Review", fields: [

        { name: "employee_id", label: "Employee", type: "select", options: empOpts(), num: true, required: true, value: r?.employee_id },

        { name: "period", label: "Period (e.g. 2026 H2)", required: true, value: r?.period },

        { name: "reviewer", label: "Reviewer", required: true, value: r?.reviewer || $("#hr-name").textContent },

        { name: "rating", label: "Rating (0-5)", type: "number", min: 0, max: 5, step: "0.5", value: r?.rating ?? 0 },

        { name: "status", label: "Status", type: "select", options: ["Draft", "Completed"], value: r?.status || "Draft" },

    ] }),

    trainings: r => ({ title: r ? "Edit Training" : "New Training", fields: [

        { name: "title", label: "Title", required: true, full: true, value: r?.title },

        { name: "trainer", label: "Trainer", value: r?.trainer },

        { name: "date", label: "Date", type: "date", required: true, value: r?.date || today() },

        { name: "hours", label: "Hours", type: "number", min: 0, step: "0.5", value: r?.hours ?? 1 },

        { name: "venue", label: "Venue", value: r?.venue },

        { name: "enrolled", label: "Enrolled", type: "number", min: 0, value: r?.enrolled ?? 0 },

        { name: "status", label: "Status", type: "select", options: ["Scheduled", "Completed", "Cancelled"], value: r?.status || "Scheduled" },

    ] }),

    announcements: r => ({ title: r ? "Edit Announcement" : "Post Announcement", fields: [

        { name: "title", label: "Title", required: true, full: true, value: r?.title },

        { name: "body", label: "Message", type: "textarea", required: true, full: true, value: r?.body },

    ], defaults: { date: today() } }),

    attendance: r => ({ title: r?.id ? "Correct Attendance" : "Add Attendance", fields: [

        { name: "employee_id", label: "Employee", type: "select", options: empOpts(), num: true, required: true, value: r?.employee_id },

        { name: "date", label: "Date", type: "date", required: true, value: r?.date || $("#a-date").value || today() },

        { name: "time_in", label: "Time in", type: "time", value: r?.time_in },

        { name: "time_out", label: "Time out", type: "time", value: r?.time_out },

        { name: "overtime_hours", label: "Approved Overtime Hours", type: "number", min: 0, step: "0.25", value: r?.overtime_hours ?? 0 },

        { name: "status", label: "Status", type: "select", options: ["Auto", "Present", "Late", "Absent", "On Leave"], value: r?.status || "Auto" },

        { name: "remarks", label: "Remarks", value: r?.remarks },

    ], check: v => {

        if (v.status === "Auto") {

            const lim = addMinutes(S.settings.work_start || "08:00", +S.settings.grace_minutes || 0);

            v.status = !v.time_in ? "Absent" : v.time_in > lim ? "Late" : "Present";

        }

    } }),

};

function addMinutes(hhmm, n) { const [h, m] = hhmm.split(":").map(Number); const t = h * 60 + m + n; return String(Math.floor(t / 60) % 24).padStart(2, "0") + ":" + String(t % 60).padStart(2, "0"); }



function editRecord(res, rec, preset) {

    const def = formDefs[res](rec || preset);

    openForm(def.title, def.fields, async v => {

        if (def.check) def.check(v);

        if (res === "attendance" && !rec?.id) {

            const dup = S.attendance.find(a => a.employee_id == v.employee_id && a.date === v.date);

            if (dup) rec = dup;

        }

        const result = await save(res, { ...(rec ? {} : def.defaults), ...v }, rec?.id);

        closeModals(); renderAll(); toast("Saved.");

        if (res === "employees" && result && result.temp_password) {

            openView("Employee created", `<p>Share these login details with the employee. The password is shown only once.</p>

                <dl class="detail-list"><dt>Employee ID</dt><dd>${esc(result.code)}</dd><dt>Temporary password</dt><dd>${esc(result.temp_password)}</dd></dl>`);

        }

    });

}



/* ---------- renderers ---------- */

function fillSelect(sel, options, blank, keep = true) {

    const old = sel.value;

    sel.innerHTML = (blank ? `<option value="">${blank}</option>` : "") + options.map(o => {

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

    $("#h-dashboard").textContent = "Welcome, " + $("#hr-name").textContent;

    $("#hero-sub").textContent = pending.length ? `${pending.length} leave request(s) are waiting for your approval.` : "Everything is up to date.";



    $("#dash-leaves").innerHTML = pending.slice(0, 5).map(l => `<li><span><strong>${esc(empName(l.employee_id))}</strong><br><small class="muted">${esc(l.type)} · ${fmtDate(l.from)} – ${fmtDate(l.to)}</small></span>

        <span>${btn("leave-approve", l.id, "check", "Approve", "btn-primary")} ${btn("leave-reject", l.id, "xmark", "Reject")}</span></li>`).join("") || empty("No pending requests.");

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

function addMonths(s, n) { const d = new Date(s + "T00:00:00"); d.setMonth(d.getMonth() + n); return iso(d); }



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

        <td>${btn("view:employees", e.id, "eye", "View")} ${btn("edit:employees", e.id, "pen", "Edit")} ${btn("del:employees", e.id, "trash", "Delete")}</td></tr>`).join("") || empty("No employees match.", 8);

    $("#emp-count").textContent = `${list.length} employee(s)`;

    $("#page-info").textContent = `Page ${ui.empPage} of ${pages}`;

    $("#prev-page").disabled = ui.empPage <= 1; $("#next-page").disabled = ui.empPage >= pages;

}



function renderRecruitment() {

    fillSelect($("#f-job"), S.jobs.map(j => ({ v: j.id, l: j.title })), "All jobs");

    const jid = $("#f-job").value, apps = S.applicants.filter(a => !jid || a.job_id == jid);

    $("#board").innerHTML = [...STAGES, "Rejected"].map(st => `<div class="board-col"><h4>${st} <span class="muted">(${apps.filter(a => a.stage === st).length})</span></h4>` +

        apps.filter(a => a.stage === st).map(a => {

            const i = STAGES.indexOf(a.stage);

            return `<div class="board-card"><strong>${esc(a.name)}</strong><br><small class="muted">${esc(jobTitle(a.job_id))}</small><div class="board-actions">

                ${i > 0 ? btn("stage:" + STAGES[i - 1], a.id, "arrow-left", "Move back") : ""}

                ${i >= 0 && i < STAGES.length - 1 ? btn("stage:" + STAGES[i + 1], a.id, "arrow-right", "Advance", "btn-primary") : ""}

                ${st !== "Rejected" && st !== "Hired" ? btn("stage:Rejected", a.id, "ban", "Reject") : ""}

                ${st === "Hired" ? btn("hire", a.id, "user-plus", "Create employee", "btn-primary") : ""}

                ${btn("view:applicants", a.id, "eye", "View")} ${btn("del:applicants", a.id, "trash", "Delete")}</div></div>`;

        }).join("") + "</div>").join("");

    $("#jobs-table tbody").innerHTML = S.jobs.map(j => `<tr><td>${j.id}</td><td>${esc(j.title)}</td><td>${esc(deptName(j.department_id))}</td><td>${esc(j.type)}</td>

        <td class="num">${j.openings}</td><td class="num">${S.applicants.filter(a => a.job_id == j.id).length}</td><td>${fmtDate(j.posted)}</td><td>${badge(j.status)}</td>

        <td>${btn("edit:jobs", j.id, "pen", "Edit")} ${btn("toggle-job", j.id, j.status === "Open" ? "lock" : "lock-open", j.status === "Open" ? "Close job" : "Reopen job")} ${btn("del:jobs", j.id, "trash", "Delete")}</td></tr>`).join("") || empty("No job openings.", 9);

}



function renderProcesses() {

    const k = $("#f-process").value;

    $("#process-list").innerHTML = S.processes.filter(p => !k || p.kind === k).map(p => {

        const done = p.tasks.filter(t => t.done).length, pct = p.tasks.length ? Math.round(done / p.tasks.length * 100) : 0;

        return `<article class="report-box"><h3>${esc(empName(p.employee_id))} ${badge(p.kind)}</h3>

            <div class="bar"><i style="width:${pct}%"></i></div><p class="muted">${done}/${p.tasks.length} tasks · ${pct === 100 ? "Completed" : "In progress"}</p>

            <ul class="list">${p.tasks.map((t, i) => `<li><label><input type="checkbox" data-proc="${p.id}" data-i="${i}"${t.done ? " checked" : ""}> ${esc(t.title)}</label></li>`).join("")}</ul>

            <div class="modal-actions">${btn("del:processes", p.id, "trash", "Delete")}</div></article>`;

    }).join("") || '<p class="muted">No processes yet. Click "Start Process".</p>';

}



function renderAttendance() {

    const d = $("#a-date").value || today(), dep = $("#a-dept").value;

    const people = S.employees.filter(e => e.status !== "Resigned" && e.status !== "Terminated" && (!dep || e.department_id == dep));

    const leaveIds = new Set(onLeaveOn(d).map(l => l.employee_id));

    const recs = people.map(e => ({ e, r: S.attendance.find(a => a.employee_id == e.id && a.date === d) }));

    const c = s => recs.filter(x => x.r && x.r.status === s).length;

    $("#a-present").textContent = c("Present"); $("#a-late").textContent = c("Late"); $("#a-absent").textContent = c("Absent");

    $("#a-leave").textContent = people.filter(e => leaveIds.has(e.id)).length;

    $("#attendance-table tbody").innerHTML = recs.map(({ e, r }) => {

        const hrs = r && r.time_in && r.time_out ? ((new Date("1970-01-01T" + r.time_out) - new Date("1970-01-01T" + r.time_in)) / 36e5).toFixed(2) : "-";

        const status = r ? r.status : leaveIds.has(e.id) ? "On Leave" : "No record";

        return `<tr><td>${esc(e.first_name + " " + e.last_name)}</td><td>${esc(deptName(e.department_id))}</td><td>${esc(r?.time_in || "-")}</td><td>${esc(r?.time_out || "-")}</td>

            <td class="num">${hrs}</td><td>${badge(status)}</td><td>${esc(r?.remarks || "")}</td>

            <td>${r ? btn("edit:attendance", r.id, "pen", "Correct") + " " + btn("del:attendance", r.id, "trash", "Delete")

                : btn("att-new", e.id, "plus", "Add record")}</td></tr>`;

    }).join("") || empty("No employees.", 8);

}



function renderLeaves() {

    const L = S.leaves, c = s => L.filter(l => l.status === s).length;

    $("#l-pending").textContent = c("Pending"); $("#l-approved").textContent = c("Approved"); $("#l-rejected").textContent = c("Rejected");

    const fs = $("#f-leave-status").value, ft = $("#f-leave-type").value;

    $("#leaves-table tbody").innerHTML = L.filter(l => (!fs || l.status === fs) && (!ft || l.type === ft)).sort((a, b) => b.from.localeCompare(a.from)).map(l => `<tr>

        <td>${l.id}</td><td>${esc(empName(l.employee_id))}</td><td>${esc(l.type)}</td><td>${fmtDate(l.from)}</td><td>${fmtDate(l.to)}</td><td class="num">${l.days}</td>

        <td>${esc(l.reason)}</td><td>${badge(l.status)}</td><td>${l.status === "Pending" ? btn("leave-approve", l.id, "check", "Approve", "btn-primary") + " " + btn("leave-reject", l.id, "xmark", "Reject") + " " : ""}

        ${btn("edit:leaves", l.id, "pen", "Edit")} ${btn("del:leaves", l.id, "trash", "Delete")}</td></tr>`).join("") || empty("No leave requests.", 9);

    $("#balances-table tbody").innerHTML = S.employees.filter(e => e.status !== "Resigned" && e.status !== "Terminated").map(e => {

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

    $("#reviews-table tbody").innerHTML = S.reviews.map(r => `<tr><td>${esc(empName(r.employee_id))}</td><td>${esc(r.period)}</td><td>${esc(r.reviewer)}</td><td>${stars(r.rating)}</td><td>${badge(r.status)}</td>

        <td>${btn("edit:reviews", r.id, "pen", "Edit")} ${btn("del:reviews", r.id, "trash", "Delete")}</td></tr>`).join("") || empty("No reviews yet.", 6);

}

function renderTraining() {

    $("#training-table tbody").innerHTML = [...S.trainings].sort((a, b) => b.date.localeCompare(a.date)).map(t => `<tr><td>${esc(t.title)}</td><td>${esc(t.trainer)}</td><td>${fmtDate(t.date)}</td>

        <td class="num">${t.hours}</td><td>${esc(t.venue)}</td><td class="num">${t.enrolled}</td><td>${badge(t.status)}</td>

        <td>${btn("edit:trainings", t.id, "pen", "Edit")} ${btn("del:trainings", t.id, "trash", "Delete")}</td></tr>`).join("") || empty("No trainings.", 8);

}

function renderAnnouncements() {

    $("#announcement-list").innerHTML = [...S.announcements].sort((a, b) => b.date.localeCompare(a.date)).map(a => `<article class="report-box"><h3>${esc(a.title)}</h3>

        <p class="muted">${fmtDate(a.date)}</p><p>${esc(a.body).replace(/\n/g, "<br>")}</p>

        <div class="modal-actions">${btn("edit:announcements", a.id, "pen", "Edit")} ${btn("del:announcements", a.id, "trash", "Delete")}</div></article>`).join("") || '<p class="muted">No announcements yet.</p>';

}

function renderDepartments() {

    $("#departments-table tbody").innerHTML = S.departments.map(d => `<tr><td>${d.id}</td><td>${esc(d.name)}</td><td>${esc(d.head || (d.head_employee_id ? empName(d.head_employee_id) : "-"))}</td>

        <td class="num">${S.employees.filter(e => e.department_id == d.id).length}</td><td class="num">${S.jobs.filter(j => j.department_id == d.id && j.status === "Open").length}</td>

        <td>${btn("dept-head", d.id, "user-tie", "Set head")} ${btn("del:departments", d.id, "trash", "Delete")}</td></tr>`).join("") || empty("No departments.", 6);

}

function renderReports() {

    const E = S.employees, act = E.filter(e => e.status === "Active"), t = today(), y = t.slice(0, 4);

    const left = E.filter(e => e.status === "Resigned" || e.status === "Terminated").length;

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

    ["settings-schedule", "settings-policy"].forEach(id => $$("[name]", $("#" + id)).forEach(i => { i.value = S.settings[i.name] ?? ""; }));

    $("#holiday-list").innerHTML = [...S.holidays].sort((a, b) => a.date.localeCompare(b.date)).map(h => `<li><span>${esc(h.name)} <small class="muted">${fmtDate(h.date)}</small></span>${btn("del:holidays", h.id, "trash", "Delete")}</li>`).join("") || empty("No holidays added.");

}

function renderChrome() {

    fillSelect($("#f-emp-dept"), deptOpts(), "All");

    fillSelect($("#f-emp-type"), EMP_TYPES, "All");

    fillSelect($("#a-dept"), deptOpts(), "All");

    fillSelect($("#f-leave-type"), LEAVE_TYPES, "All");

    const n = { onboarding: S.processes.filter(p => p.tasks.some(t => !t.done)).length, recruitment: S.applicants.filter(a => a.stage === "Applied").length, leaves: S.leaves.filter(l => l.status === "Pending").length };

    Object.entries(n).forEach(([k, v]) => { const el = $("#nc-" + k); el.textContent = v; el.hidden = !v; });

    const items = [];

    S.leaves.filter(l => l.status === "Pending").forEach(l => items.push(`<a href="#leaves"><i class="fas fa-calendar-check"></i> ${esc(empName(l.employee_id))} requested ${esc(l.type.toLowerCase())} leave</a>`));

    if (n.recruitment) items.push(`<a href="#recruitment"><i class="fas fa-user-tie"></i> ${n.recruitment} new applicant(s)</a>`);

    if (n.onboarding) items.push(`<a href="#onboarding"><i class="fas fa-clipboard-check"></i> ${n.onboarding} process(es) in progress</a>`);

    $("#notif-panel").innerHTML = items.join("") || '<p class="muted" style="padding:.8rem">Nothing new.</p>';

    const nc = $("#notif-count"); nc.textContent = items.length; nc.hidden = !items.length;

}

async function renderPayroll() {
    const tableBody = $("#payroll-table tbody");
    const employeeSelect = $("#payroll-employee");
    if (!tableBody || !employeeSelect) return;

    const selectedEmployee = employeeSelect.value;
    employeeSelect.innerHTML = '<option value="">Select Employee</option>' +
        empOpts().map(e => `<option value="${esc(e.v)}">${esc(e.l)}</option>`).join("");
    if (selectedEmployee) employeeSelect.value = selectedEmployee;

    const records = S.payroll || [];
    if (!records.length) {
        tableBody.innerHTML = empty("No payroll records found.", 6);
        return;
    }

    tableBody.innerHTML = records.map(p => `
        <tr>
            <td>${esc(p.employee_name || `${p.first_name || ""} ${p.last_name || ""}`.trim() || empName(p.employee_id))}</td>
            <td>${esc(String(p.pay_period || "").slice(0, 7) || "-")}</td>
            <td>₱${Number(p.gross_pay || 0).toLocaleString("en-PH", { minimumFractionDigits: 2 })}</td>
            <td>₱${Number(p.deductions || 0).toLocaleString("en-PH", { minimumFractionDigits: 2 })}</td>
            <td>₱${Number(p.net_pay || 0).toLocaleString("en-PH", { minimumFractionDigits: 2 })}</td>
            <td>${badge(p.payment_status || "Pending")}</td>
        </tr>
    `).join("");
}

function renderAll() {

    renderChrome(); renderDashboard(); renderEmployees(); renderRecruitment(); renderProcesses(); renderAttendance(); renderPayroll();

    renderLeaves(); renderPerformance(); renderTraining(); renderAnnouncements(); renderDepartments(); renderReports(); renderSettings();

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

    }[what];

    const csv = rows.map(r => r.map(c => '"' + String(c ?? "").replace(/"/g, '""') + '"').join(",")).join("\r\n");

    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(new Blob(["\ufeff" + csv], { type: "text/csv" })), download: `${what}-${today()}.csv` });

    document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(a.href);

}



/* ---------- actions ---------- */

async function run(fn) { try { await fn(); } catch (e) { toast(e.message, true); } }



const ACTIONS = {

    "add-employee": () => editRecord("employees"),

    "add-job": () => editRecord("jobs"),

    "add-leave": () => editRecord("leaves"),

    "add-announcement": () => editRecord("announcements"),

    "add-applicant": () => editRecord("applicants"),

    "add-attendance": () => editRecord("attendance"),

    "add-review": () => editRecord("reviews"),

    "add-training": () => editRecord("trainings"),

    print: () => window.print(),

    export: el => exportCsv(el.dataset.what),

    "start-process": () => openForm("Start Process", [

        { name: "employee_id", label: "Employee", type: "select", options: empOpts(false), num: true, required: true },

        { name: "kind", label: "Process", type: "select", options: ["Onboarding", "Offboarding"] },

    ], async v => {

        await save("processes", { employee_id: v.employee_id, kind: v.kind, status: "In Progress", tasks: TASKS[v.kind].map(title => ({ title, done: false })) });

        closeModals(); renderAll(); toast("Process started.");

    }),

};



const ROW = {

    async "leave-approve"(id) { await setLeave(id, "Approved"); },

    async "leave-reject"(id) { await setLeave(id, "Rejected"); },

    async hire(id) {

        const a = S.applicants.find(x => x.id == id), j = S.jobs.find(x => x.id == a.job_id) || {};

        const [first, ...rest] = a.name.split(" ");

        editRecord("employees", null, { first_name: first, last_name: rest.join(" "), email: a.email, phone: a.phone, department_id: j.department_id, position: j.title, type: j.type });

    },

    async "toggle-job"(id) { const j = S.jobs.find(x => x.id == id); await save("jobs", { status: j.status === "Open" ? "Closed" : "Open" }, id); renderAll(); },

    "att-new"(id) { editRecord("attendance", null, { employee_id: +id, date: $("#a-date").value || today() }); },

    "dept-head"(id) {

        const d = S.departments.find(x => x.id == id);

        const people = S.employees.filter(e => e.department_id == id && e.status !== "Resigned" && e.status !== "Terminated")

            .map(e => ({ v: e.id, l: `${e.first_name} ${e.last_name}` }));

        openForm("Department Head \u2014 " + d.name,

            [{ name: "head_employee_id", label: "Head", type: "select", options: people, blank: "No head assigned", value: d.head_employee_id ?? "" }],

            async v => {

                await save("departments", { head_employee_id: v.head_employee_id === "" ? null : Number(v.head_employee_id) }, id);

                closeModals(); renderAll(); toast("Saved.");

            });

    },

};

async function setLeave(id, status) { await save("leaves", { status }, id); renderAll(); toast("Leave " + status.toLowerCase() + "."); }



function viewRecord(res, id) {

    const rows = o => `<dl class="detail-list">${o.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v === "" || v == null ? "-" : esc(v)}</dd>`).join("")}</dl>`;

    if (res === "employees") {

        const e = emp(id), yr = today().slice(0, 4);

        const used = t => S.leaves.filter(l => l.employee_id == id && l.type === t && l.status === "Approved" && l.from.slice(0, 4) === yr).reduce((n, l) => n + l.days, 0);

        openView(e.first_name + " " + e.last_name, rows([["Employee ID", e.code || e.id], ["Email", e.email], ["Phone", e.phone], ["Birthday", fmtDate(e.birthday)],

            ["Department", deptName(e.department_id)], ["Position", e.position], ["Type", e.type], ["Hired", fmtDate(e.hired)], ["Status", e.status],

            ["Probation ends", fmtDate(addMonths(e.hired, +S.settings.probation_months || 6))],

            ["Leave used this year", `Vacation ${used("Vacation Leave (PTO)")} · Sick ${used("Sick Leave")} · Emergency ${used("Emergency Leave")}`]]));

    } else if (res === "applicants") {

        const a = S.applicants.find(x => x.id == id);

        openView(a.name, rows([["Email", a.email], ["Phone", a.phone], ["Applied for", jobTitle(a.job_id)], ["Stage", a.stage]]) +

            `<div class="modal-actions">${btn("edit:applicants", a.id, "pen", "Edit")}</div>`);

    }

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

        const [kind, arg] = b.dataset.act.split(":"), id = b.dataset.id;

        return run(async () => {

            if (kind === "edit") { closeModals(); editRecord(arg, S[arg].find(x => x.id == id)); }

            else if (kind === "view") viewRecord(arg, id);

            else if (kind === "del") {

                if (!confirm("Delete this record? This can't be undone.")) return;

                if (arg === "departments" && S.employees.some(x => x.department_id == id)) throw new Error("Move or remove this department's employees first.");

                await remove(arg, id); renderAll(); toast("Deleted.");

            } else if (kind === "stage") { await save("applicants", { stage: arg }, id); renderAll(); }

            else await ROW[kind]?.(id, b);

        });

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



document.addEventListener("change", e => {

    const c = e.target.closest("[data-proc]");

    if (!c) return;

    run(async () => {

        const p = S.processes.find(x => x.id == c.dataset.proc);

        const tasks = p.tasks.map((t, i) => i == c.dataset.i ? { ...t, done: c.checked } : t);

        await save("processes", { tasks, status: tasks.every(t => t.done) ? "Completed" : "In Progress" }, p.id);

        renderProcesses(); renderChrome();

    });

});

document.addEventListener("keydown", e => { if (e.key === "Escape") closeModals(); });



function bind() {

    window.addEventListener("hashchange", route);

    $("#menu-btn").addEventListener("click", () => { const o = $("#sidebar").classList.toggle("open"); $("#menu-btn").setAttribute("aria-expanded", o); });

    $("#notif-btn").addEventListener("click", ev => { ev.stopPropagation(); const p = $("#notif-panel"); p.hidden = !p.hidden; $("#notif-btn").setAttribute("aria-expanded", !p.hidden); });



    /* ----- user menu + sign out ----- */

    const userBtn = $("#user-btn"), userMenu = $("#user-menu");

    const setUserMenu = open => {

        userMenu.hidden = !open;

        userBtn.setAttribute("aria-expanded", String(open));

    };

    userBtn.addEventListener("click", ev => {

        ev.stopPropagation();

        setUserMenu(userMenu.hidden);

    });

    document.addEventListener("click", ev => {

        if (!ev.target.closest(".user-menu")) setUserMenu(false);

    });

    document.addEventListener("keydown", ev => {

        if (ev.key === "Escape") setUserMenu(false);

    });

    // Close the menu when a menu link is used (e.g. HR settings)

    userMenu.addEventListener("click", ev => {

        if (ev.target.closest("a") && !ev.target.closest(".menu-danger")) setUserMenu(false);

    });

    // Confirm before signing out

    $(".menu-danger", userMenu).addEventListener("click", ev => {

        if (!confirm("Sign out of the HR portal?")) ev.preventDefault();

    });



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



    $("#form-body").addEventListener("submit", async ev => {

        ev.preventDefault();

        const err = $("#form-error"), sub = $("#form-submit");

        err.hidden = true; sub.disabled = true;

        try { await formHandler(); }

        catch (x) { err.textContent = x.message; err.hidden = false; }

        finally { sub.disabled = false; }

    });



    $("#dept-form").addEventListener("submit", ev => {

        ev.preventDefault();

        run(async () => {

            const name = $("#dept-name").value.trim();

            if (!name) return;

            if (S.departments.some(d => d.name.toLowerCase() === name.toLowerCase())) throw new Error("That department already exists.");

            await save("departments", { name }); $("#dept-name").value = ""; renderAll(); toast("Department added.");

        });

    });

    ["settings-schedule", "settings-policy"].forEach(id => $("#" + id).addEventListener("submit", ev => {

        ev.preventDefault();

        run(async () => {

            const body = {};

            $$("[name]", ev.target).forEach(i => { body[i.name] = i.type === "number" ? Number(i.value) : i.value; });

            await call("PUT", "settings", body); await load("settings"); renderAll(); toast("Settings saved.");

        });

    }));

    const payrollButton = $("#generate-payroll");
    if (payrollButton) payrollButton.addEventListener("click", () => run(async () => {
        const employeeId = $("#payroll-employee").value;
        const month = $("#payroll-month").value;
        if (!employeeId || !month) {
            toast("Select an employee and payroll month.", true);
            return;
        }
        payrollButton.disabled = true;
        try {
            await api("/api/hr/payroll", {
                method: "POST",
                body: JSON.stringify({ employee_id: Number(employeeId), pay_period: `${month}-01` })
            });
            await load("payroll");
            renderPayroll();
            toast("Payroll generated successfully.");
        } catch (err) {
            toast(err.message || "Unable to generate payroll.", true);
        } finally {
            payrollButton.disabled = false;
        }
    }));

    $("#holiday-form").addEventListener("submit", ev => {

        ev.preventDefault();

        run(async () => {

            await save("holidays", { name: $("#hol-name").value.trim(), date: $("#hol-date").value });

            ev.target.reset(); renderAll(); toast("Holiday added.");

        });

    });

}



/* ---------- boot ---------- */

document.addEventListener("DOMContentLoaded", async () => {

    const name = $("#hr-name"), pill = $("#hr-status"), pillText = $("#hr-status-text");

    bind();

    let me = null;

    try {

        me = await api("/api/hr/me");

    } catch (err) {

        if (err.status && err.status !== 404) {          // server answered with a real error

            name.textContent = "HR"; pill.dataset.state = "offline"; pillText.textContent = "Server error";

            toast(err.message, true);

        } else {                                          // API missing / server unreachable -> demo

            DEMO = true; seed();

            name.textContent = "HR Admin"; $("#hr-avatar").textContent = "HA";

            pill.dataset.state = "demo"; pillText.textContent = "Demo mode";

            $("#demo-banner").hidden = false;

        }

    }

    if (me) {

        name.textContent = me.name || "HR";

        $("#hr-avatar").textContent = (me.name || "HR").split(/\s+/).map(w => w[0]).join("").slice(0, 2).toUpperCase();

        pill.dataset.state = "online"; pillText.textContent = "Connected";

    }

    if (me || DEMO) {

        try { await load(); }

        catch (err) { pill.dataset.state = "offline"; pillText.textContent = "Data error"; toast(err.message, true); }

    }

    RES.forEach(r => { S[r] = S[r] || []; });

    renderAll();

    route();

});