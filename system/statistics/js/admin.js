// Biringan Employee Management System - frontend logic
// Talks to the Flask API in main.py / routes/admin.py (/api/dashboard, /api/employees, ...)

const state = { page: 1, perPage: 10, search: "", status: "" };

async function api(url, options = {}) {
    const token = document.querySelector('meta[name="csrf-token"]')?.content || "";

    const res = await fetch(url, {
        ...options,
        headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": token,
            ...(options.headers || {})
        }
    });

    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "Request failed (" + res.status + ")");
    return data;
}

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

const byId = (id) => document.getElementById(id);

// ---------------------------------------------------------------- Dashboard
async function loadDashboard() {
    try {
        const d = await api("/api/dashboard");
        setText("total-employees", d.total_employees);
        setText("active-employees", d.active_employees);
        setText("total-departments", d.total_departments);
        setText("total-positions", d.total_positions);
        setText("pending-leaves", d.pending_leaves);
        updateBell(d.pending_leaves);

        const list = document.getElementById("activity-list");
        list.innerHTML = "";
        if (!d.recent_activity.length) {
            const li = document.createElement("li");
            li.className = "empty";
            li.textContent = "No recent activity yet.";
            list.appendChild(li);
            return;
        }
        d.recent_activity.forEach((a) => {
            const li = document.createElement("li");
            const when = new Date(a.created_at).toLocaleString();
            li.textContent = a.message + " - " + when;
            list.appendChild(li);
        });
    } catch (err) {
        console.error(err);
        alert("Dashboard error: " + err.message);
    }
}

// ---------------------------------------------------------------- Employees
async function loadEmployees() {
    const params = new URLSearchParams({
        page: state.page,
        per_page: state.perPage,
    });
    if (state.search) params.set("search", state.search);
    if (state.status) params.set("status", state.status);

    try {
        const d = await api("/api/employees?" + params.toString());
        renderEmployees(d.items);
        state.page = d.page;
        setText("page-info", "Page " + d.page + " of " + d.pages);
        document.getElementById("prev-page").disabled = d.page <= 1;
        document.getElementById("next-page").disabled = d.page >= d.pages;
    } catch (err) {
        console.error(err);
        alert("Could not load employees: " + err.message);
    }
}

function renderEmployees(items) {
    const tbody = document.querySelector("#employees-table tbody");
    tbody.innerHTML = "";
    if (!items.length) return emptyRow(tbody, 9, "No employees found.");

    items.forEach((e) => {
        const tr = document.createElement("tr");
        [e.id, e.employee_code || "-", e.name, e.department, e.position, e.email, e.phone || "-", e.status].forEach((v) => {
            const td = document.createElement("td");
            td.textContent = v;
            tr.appendChild(td);
        });

        const actions = document.createElement("td");
        actions.className = "actions";

        const edit = document.createElement("button");
        edit.className = "btn btn-secondary";
        edit.textContent = "Edit";
        edit.addEventListener("click", () => editEmployee(e.id));
        actions.appendChild(edit);

        const del = document.createElement("button");
        del.className = "btn btn-danger";
        del.textContent = "Delete";
        del.addEventListener("click", () => deleteEmployee(e.id, e.name));
        actions.appendChild(del);
        tr.appendChild(actions);

        tbody.appendChild(tr);
    });
}

async function deleteEmployee(id, name) {
    if (!confirm("Delete " + name + "?")) return;
    try {
        await api("/api/employees/" + id, { method: "DELETE" });
        await Promise.all([loadEmployees(), loadDashboard()]);
    } catch (err) {
        alert(err.message);
    }
}

// ---------------------------------------------------------------- Page navigation
// Shows one sidebar page. Used by the sidebar, the account menu AND the dashboard cards.
function showSection(section) {
    document.querySelectorAll(".sidebar nav li").forEach((x) =>
        x.classList.toggle("active", x.dataset.section === section));

    document.querySelectorAll(".main-content .page").forEach((p) => p.classList.remove("active"));
    const page = document.getElementById("page-" + section);
    if (page) page.classList.add("active");

    if (section === "employees") loadEmployees();
    if (section === "department") loadDepartments();
    if (section === "positions") loadPositions();
    if (section === "salaries") loadSalaries();
    if (section === "leaves") loadLeaves();
    if (section === "reports") loadReports();
    if (section === "setting") loadSettings();

    document.querySelector(".main-content").scrollTop = 0;
}

// ---------------------------------------------------------------- Topbar (menu, bell, account)
function initialsOf(name) {
    const parts = String(name || "").trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return "–";
    const first = parts[0][0];
    const last = parts.length > 1 ? parts[parts.length - 1][0] : "";
    return (first + last).toUpperCase();
}

async function loadHeaderUser() {
    try {
        const p = await api("/api/settings/profile");
        const name = p.name || p.email || "Administrator";
        setText("header-name", name);
        setText("avatar", initialsOf(name));
    } catch (err) {
        setText("header-name", "Administrator");
        setText("avatar", "A");
    }
}

function updateBell(pending) {
    const dot = byId("bell-dot");
    const n = Number(pending) || 0;
    dot.hidden = n === 0;
    byId("bell").setAttribute(
        "aria-label",
        n ? n + " pending leave request" + (n === 1 ? "" : "s") : "No pending leave requests"
    );
}

function setSidebar(open) {
    byId("sidebar").classList.toggle("collapsed", !open);
    byId("menu-toggle").setAttribute("aria-expanded", String(open));
    byId("menu-toggle").querySelector("i").className =
        open ? "far fa-square-caret-left" : "far fa-square-caret-right";
}

function setUserMenu(open) {
    byId("user-menu").hidden = !open;
    byId("user-btn").setAttribute("aria-expanded", String(open));
}

// ---------------------------------------------------------------- Events
document.addEventListener("DOMContentLoaded", () => {
    loadDashboard();
    loadEmployees();
    loadHeaderUser();

    // Sidebar starts closed on phones
    if (window.matchMedia("(max-width: 700px)").matches) setSidebar(false);
    byId("menu-toggle").addEventListener("click", () =>
        setSidebar(byId("sidebar").classList.contains("collapsed")));

    // Account menu
    byId("user-btn").addEventListener("click", (ev) => {
        ev.stopPropagation();
        setUserMenu(byId("user-menu").hidden);
    });
    byId("user-menu").addEventListener("click", (ev) => {
        const item = ev.target.closest("[data-section]");
        if (item) showSection(item.dataset.section);
        setUserMenu(false);
    });
    document.addEventListener("click", (ev) => {
        if (!ev.target.closest(".user-menu")) setUserMenu(false);
    });
    document.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape") setUserMenu(false);
    });

    // Bell jumps to pending leave requests
    byId("bell").addEventListener("click", () => {
        byId("leave-filter").value = "Pending";
        showSection("leaves");
    });

    // Help buttons (topbar + sidebar)
    document.querySelectorAll("[data-action='help']").forEach((b) =>
        b.addEventListener("click", () =>
            toast("Need help? Contact the system owner or your IT support.", "info")));

    const searchInput = document.getElementById("search-input");
    const runSearch = () => {
        state.search = searchInput.value.trim();
        state.page = 1;
        showSection("employees");   // jump to Employees from any page and load results
    };
    document.getElementById("search-btn").addEventListener("click", runSearch);
    searchInput.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") runSearch();
    });

    document.getElementById("prev-page").addEventListener("click", () => {
        if (state.page > 1) {
            state.page -= 1;
            loadEmployees();
        }
    });
    document.getElementById("next-page").addEventListener("click", () => {
        state.page += 1;
        loadEmployees();
    });

    // Simple status filter: Active, On Leave, Resigned, Terminated (blank = all)
    document.getElementById("filter-employees").addEventListener("click", () => {
        const choice = prompt(
            "Filter by status (Active, On Leave, Resigned, Terminated). Leave blank for all:",
            state.status
        );
        if (choice === null) return;
        state.status = choice.trim();
        state.page = 1;
        loadEmployees();
    });

    // Sidebar navigation (click + keyboard)
    document.querySelectorAll(".sidebar nav li").forEach((li) => {
        li.addEventListener("click", () => {
            showSection(li.dataset.section);
            if (window.matchMedia("(max-width: 700px)").matches) setSidebar(false);
        });
        li.addEventListener("keydown", (ev) => {
            if (ev.key === "Enter" || ev.key === " ") {
                ev.preventDefault();
                li.click();
            }
        });
    });

    // Dashboard cards act as shortcuts to their sidebar page
    document.querySelectorAll(".card[data-goto]").forEach((card) => {
        const go = () => {
            if (card.dataset.goto === "employees") {
                state.status = card.dataset.status || "";   // Active card pre-filters
                state.page = 1;
            }
            showSection(card.dataset.goto);
        };
        card.addEventListener("click", go);
        card.addEventListener("keydown", (ev) => {
            if (ev.key === "Enter" || ev.key === " ") {
                ev.preventDefault();
                go();
            }
        });
    });
});

// ---------------------------------------------------------------- Shared helpers
let toastTimer;
function toast(message, type = "success") {
    const el = document.getElementById("toast");
    el.textContent = message;
    el.className = "toast toast-" + type;
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 3500);
}

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (c) => (
        { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
}

const formOptions = { departments: [], positions: [] };

async function loadFormOptions() {
    const o = await api("/api/accounts/options");
    formOptions.departments = o.departments;
    formOptions.positions = o.positions;
}

function fillDepartmentSelect(select) {
    select.innerHTML = formOptions.departments
        .map((d) => `<option value="${d.id}">${escapeHtml(d.name)}</option>`)
        .join("");
}

function fillPositionSelect(deptSelect, posSelect, selectedId) {
    const deptId = Number(deptSelect.value);
    posSelect.innerHTML = formOptions.positions
        .filter((p) => p.department_id === deptId)
        .map((p) => `<option value="${p.id}">${escapeHtml(p.title)}</option>`)
        .join("");
    if (selectedId) posSelect.value = selectedId;
}

function updateAccountRoleFields() {
    const isAdmin = byId("acc-role").value === "admin";
    byId("acc-department-field").hidden = isAdmin;
    byId("acc-position-field").hidden = isAdmin;
}

// ---------------------------------------------------------------- Add Account
async function openAccountModal() {
    try {
        await loadFormOptions();
    } catch (err) {
        toast(err.message, "error");
        return;
    }

    byId("account-form").reset();
    byId("account-error").hidden = true;
    fillDepartmentSelect(byId("acc-department"));
    fillPositionSelect(byId("acc-department"), byId("acc-position"));
    updateAccountRoleFields();

    byId("acc-birthday").max = new Date().toISOString().slice(0, 10);
    byId("account-modal").hidden = false;
    byId("acc-first").focus();
}

function closeAccountModal() {
    byId("account-modal").hidden = true;
}

// ---------------------------------------------------------------- Edit Employee
async function editEmployee(id) {
    let emp;
    try {
        await loadFormOptions();
        emp = await api("/api/accounts/employees/" + id);
    } catch (err) {
        toast(err.message, "error");
        return;
    }

    byId("employee-error").hidden = true;
    byId("emp-id").value = emp.id;
    byId("emp-first").value = emp.first_name || "";
    byId("emp-middle").value = emp.middle_name || "";
    byId("emp-last").value = emp.last_name || "";
    byId("emp-suffix").value = emp.suffix || "None";
    byId("emp-sex").value = emp.sex || "";
    byId("emp-birthday").value = emp.birthday || "";
    byId("emp-birthday").max = new Date().toISOString().slice(0, 10);
    byId("emp-email").value = emp.email || "";
    byId("emp-phone").value = emp.phone || "";
    byId("emp-salary").value = emp.salary === "" || emp.salary == null ? "" : emp.salary;
    byId("emp-status").value = emp.status || "Active";

    fillDepartmentSelect(byId("emp-department"));
    byId("emp-department").value = emp.department_id;
    fillPositionSelect(byId("emp-department"), byId("emp-position"), emp.position_id);

    byId("employee-modal").hidden = false;
    byId("emp-first").focus();
}

function closeEmployeeModal() {
    byId("employee-modal").hidden = true;
}

// ---------------------------------------------------------------- Wiring
document.addEventListener("DOMContentLoaded", () => {
    // Add Account
    byId("add-account-btn").addEventListener("click", openAccountModal);
    byId("acc-department").addEventListener("change", () =>
        fillPositionSelect(byId("acc-department"), byId("acc-position")));
    byId("acc-role").addEventListener("change", updateAccountRoleFields);
    byId("account-close").addEventListener("click", closeAccountModal);
    byId("account-cancel").addEventListener("click", closeAccountModal);
    byId("account-modal").addEventListener("click", (e) => {
        if (e.target.id === "account-modal") closeAccountModal();
    });

    // Edit Employee
    byId("emp-department").addEventListener("change", () =>
        fillPositionSelect(byId("emp-department"), byId("emp-position")));
    byId("employee-close").addEventListener("click", closeEmployeeModal);
    byId("employee-cancel").addEventListener("click", closeEmployeeModal);
    byId("employee-modal").addEventListener("click", (e) => {
        if (e.target.id === "employee-modal") closeEmployeeModal();
    });

    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            closeAccountModal();
            closeEmployeeModal();
        }
    });

    // Submit: Add Account
    byId("account-form").addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const errBox = byId("account-error");
        const val = (id) => byId(id).value;

        if (val("acc-password") !== val("acc-confirm")) {
            errBox.textContent = "Passwords do not match.";
            errBox.hidden = false;
            return;
        }

        const isAdmin = val("acc-role") === "admin";
        const payload = {
            first_name: val("acc-first"),
            middle_name: val("acc-middle"),
            last_name: val("acc-last"),
            suffix: val("acc-suffix"),
            sex: val("acc-sex"),
            birthday: val("acc-birthday"),
            email: val("acc-email"),
            phone: val("acc-phone"),
            department_id: isAdmin ? null : val("acc-department"),
            position_id: isAdmin ? null : val("acc-position"),
            salary: val("acc-salary"),
            role: val("acc-role"),
            password: val("acc-password"),
        };

        try {
            const created = await api("/api/accounts", {
                method: "POST",
                body: JSON.stringify(payload),
            });
            closeAccountModal();
            alert("Account created for " + created.email + ".\n\nEmployee ID: " + created.employee_code + "\n\nWrite this down. The employee needs it to log in.");
            loadDashboard();
            loadEmployees();
        } catch (err) {
            errBox.textContent = err.message;
            errBox.hidden = false;
        }
    });

    // Submit: Edit Employee
    byId("employee-form").addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const errBox = byId("employee-error");
        const val = (id) => byId(id).value;

        const payload = {
            first_name: val("emp-first"),
            middle_name: val("emp-middle"),
            last_name: val("emp-last"),
            suffix: val("emp-suffix"),
            sex: val("emp-sex"),
            birthday: val("emp-birthday"),
            email: val("emp-email"),
            phone: val("emp-phone"),
            department_id: val("emp-department"),
            position_id: val("emp-position"),
            salary: val("emp-salary"),
            status: val("emp-status"),
        };

        try {
            await api("/api/accounts/employees/" + val("emp-id"), {
                method: "PUT",
                body: JSON.stringify(payload),
            });
            closeEmployeeModal();
            toast("Employee updated.");
            loadDashboard();
            loadEmployees();
            loadHeaderUser();   // in case the admin edited their own name
        } catch (err) {
            errBox.textContent = err.message;
            errBox.hidden = false;
        }
    });
});

// ---------------------------------------------------------------- Departments & Positions
function emptyRow(tbody, cols, text) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = cols;
    td.className = "empty-row";
    td.textContent = text;
    tr.appendChild(td);
    tbody.appendChild(tr);
}

function actionCell(onEdit, onDelete) {
    const td = document.createElement("td");
    td.className = "actions";
    const edit = document.createElement("button");
    edit.className = "btn btn-secondary";
    edit.textContent = "Edit";
    edit.addEventListener("click", onEdit);
    const del = document.createElement("button");
    del.className = "btn btn-danger";
    del.textContent = "Delete";
    del.addEventListener("click", onDelete);
    td.append(edit, del);
    return td;
}

async function loadDepartments() {
    const tbody = document.querySelector("#departments-table tbody");
    let rows;
    try {
        rows = await api("/api/departments");
    } catch (err) {
        toast(err.message, "error");
        return;
    }
    tbody.innerHTML = "";
    if (!rows.length) return emptyRow(tbody, 6, "No departments yet.");
    rows.forEach((d) => {
        const tr = document.createElement("tr");
        [d.id, d.name, d.head || "-", d.employees, d.positions].forEach((v) => {
            const td = document.createElement("td");
            td.textContent = v;
            tr.appendChild(td);
        });
        tr.appendChild(actionCell(() => editDepartment(d), () => deleteDepartment(d)));
        tbody.appendChild(tr);
    });
}

async function editDepartment(d) {
    const name = prompt("Department name:", d.name);
    if (name === null || !name.trim()) return;
    try {
        // keep the existing head, otherwise the PUT would clear it
        await api("/api/departments/" + d.id, {
            method: "PUT",
            body: JSON.stringify({ name: name.trim(), head_employee_id: d.head_employee_id }),
        });
        toast("Department updated.");
        loadDepartments();
    } catch (err) { toast(err.message, "error"); }
}

async function deleteDepartment(d) {
    if (!confirm("Delete department " + d.name + "?")) return;
    try {
        await api("/api/departments/" + d.id, { method: "DELETE" });
        toast("Department deleted.");
        loadDepartments();
        loadDashboard();
    } catch (err) { toast(err.message, "error"); }
}

async function loadPositions() {
    const tbody = document.querySelector("#positions-table tbody");
    const select = byId("pos-department");
    let rows, depts;
    try {
        [rows, depts] = await Promise.all([api("/api/positions"), api("/api/departments")]);
    } catch (err) {
        toast(err.message, "error");
        return;
    }
    const chosen = select.value;
    select.innerHTML = depts
        .map((d) => `<option value="${d.id}">${escapeHtml(d.name)}</option>`)
        .join("");
    if (chosen) select.value = chosen;

    tbody.innerHTML = "";
    if (!rows.length) return emptyRow(tbody, 5, "No positions yet.");
    rows.forEach((p) => {
        const tr = document.createElement("tr");
        [p.id, p.title, p.department, p.employees].forEach((v) => {
            const td = document.createElement("td");
            td.textContent = v;
            tr.appendChild(td);
        });
        tr.appendChild(actionCell(() => editPosition(p), () => deletePosition(p)));
        tbody.appendChild(tr);
    });
}

async function editPosition(p) {
    const title = prompt("Position title:", p.title);
    if (title === null || !title.trim()) return;
    try {
        await api("/api/positions/" + p.id, {
            method: "PUT",
            body: JSON.stringify({ title: title.trim(), department_id: p.department_id }),
        });
        toast("Position updated.");
        loadPositions();
    } catch (err) { toast(err.message, "error"); }
}

async function deletePosition(p) {
    if (!confirm("Delete position " + p.title + "?")) return;
    try {
        await api("/api/positions/" + p.id, { method: "DELETE" });
        toast("Position deleted.");
        loadPositions();
        loadDashboard();
    } catch (err) { toast(err.message, "error"); }
}

document.addEventListener("DOMContentLoaded", () => {
    byId("dept-form").addEventListener("submit", async (ev) => {
        ev.preventDefault();
        try {
            await api("/api/departments", {
                method: "POST",
                body: JSON.stringify({ name: byId("dept-name").value }),
            });
            byId("dept-name").value = "";
            toast("Department added.");
            loadDepartments();
            loadDashboard();
        } catch (err) { toast(err.message, "error"); }
    });

    byId("pos-form").addEventListener("submit", async (ev) => {
        ev.preventDefault();
        try {
            await api("/api/positions", {
                method: "POST",
                body: JSON.stringify({
                    title: byId("pos-title").value,
                    department_id: byId("pos-department").value,
                }),
            });
            byId("pos-title").value = "";
            toast("Position added.");
            loadPositions();
            loadDashboard();
        } catch (err) { toast(err.message, "error"); }
    });
});


// ---------------------------------------------------------------- Salaries
const peso = (n) => "\u20B1" + Number(n || 0).toLocaleString("en-PH", {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
});

async function loadSalaries() {
    const tbody = document.querySelector("#salaries-table tbody");
    let d;
    try {
        d = await api("/api/salaries");
    } catch (err) {
        toast(err.message, "error");
        return;
    }
    setText("sal-total", peso(d.summary.total_monthly));
    setText("sal-average", peso(d.summary.average));
    setText("sal-highest", peso(d.summary.highest));

    tbody.innerHTML = "";
    if (!d.items.length) return emptyRow(tbody, 7, "No employees found.");
    d.items.forEach((e) => {
        const tr = document.createElement("tr");
        [e.id, e.name, e.department || "-", e.position || "-", e.status,
         e.salary === null || e.salary === undefined ? "-" : peso(e.salary)].forEach((v) => {
            const td = document.createElement("td");
            td.textContent = v;
            tr.appendChild(td);
        });
        const td = document.createElement("td");
        td.className = "actions";
        const edit = document.createElement("button");
        edit.className = "btn btn-secondary";
        edit.textContent = "Edit";
        edit.addEventListener("click", () => editSalary(e));
        td.appendChild(edit);
        tr.appendChild(td);
        tbody.appendChild(tr);
    });
}

let salaryTarget = null;

function editSalary(e) {
    salaryTarget = e;
    byId("sal-id").value = e.id;
    byId("sal-name").textContent = e.name;
    byId("sal-dept").textContent = e.department || "-";
    byId("sal-pos").textContent = e.position || "-";
    byId("sal-current").textContent =
        e.salary === null || e.salary === undefined ? "Not set" : peso(e.salary);
    byId("sal-input").value = e.salary === null || e.salary === undefined ? "" : Number(e.salary).toFixed(2);
    byId("salary-error").hidden = true;
    updateSalaryDiff();
    byId("salary-modal").hidden = false;
    byId("sal-input").focus();
    byId("sal-input").select();
}

function closeSalaryModal() {
    byId("salary-modal").hidden = true;
    salaryTarget = null;
}

function updateSalaryDiff() {
    const out = byId("sal-diff");
    const raw = byId("sal-input").value;
    if (!salaryTarget || raw === "" || isNaN(Number(raw))) { out.textContent = ""; return; }
    const diff = Number(raw) - Number(salaryTarget.salary || 0);
    if (diff === 0) out.textContent = "No change from the current salary.";
    else out.textContent = (diff > 0 ? "Increase of " : "Decrease of ") + peso(Math.abs(diff)) + ".";
}

document.addEventListener("DOMContentLoaded", () => {
    byId("sal-input").addEventListener("input", updateSalaryDiff);
    byId("salary-close").addEventListener("click", closeSalaryModal);
    byId("salary-cancel").addEventListener("click", closeSalaryModal);
    byId("salary-modal").addEventListener("click", (ev) => {
        if (ev.target.id === "salary-modal") closeSalaryModal();
    });
    document.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape") closeSalaryModal();
    });

    byId("salary-form").addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const errBox = byId("salary-error");
        const raw = byId("sal-input").value.trim();
        const amount = Number(raw);
        if (raw === "" || isNaN(amount) || amount < 0 || amount >= 100000000) {
            errBox.textContent = "Enter a valid salary between 0 and 99,999,999.99.";
            errBox.hidden = false;
            return;
        }
        try {
            await api("/api/salaries/" + byId("sal-id").value, {
                method: "PUT",
                body: JSON.stringify({ salary: raw }),
            });
            closeSalaryModal();
            toast("Salary updated.");
            loadSalaries();
        } catch (err) {
            errBox.textContent = err.message;
            errBox.hidden = false;
        }
    });
});


// ---------------------------------------------------------------- Leaves
function fmtDate(v) {
    const d = new Date(v);
    return isNaN(d) ? String(v ?? "-") : d.toLocaleDateString("en-PH", { year: "numeric", month: "short", day: "numeric" });
}

async function loadLeaves() {
    const tbody = document.querySelector("#leaves-table tbody");
    const status = byId("leave-filter").value;
    let rows;
    try {
        rows = await api("/api/leaves" + (status ? "?status=" + encodeURIComponent(status) : ""));
    } catch (err) {
        toast(err.message, "error");
        return;
    }
    tbody.innerHTML = "";
    if (!rows.length) return emptyRow(tbody, 8, "No leave requests found.");

    rows.forEach((l) => {
        const tr = document.createElement("tr");
        const dates = l.start_date === l.end_date ? fmtDate(l.start_date) : fmtDate(l.start_date) + " – " + fmtDate(l.end_date);
        [l.id, l.employee, l.department || "-", l.leave_type, dates, l.days, l.status || "Pending"].forEach((v) => {
            const td = document.createElement("td");
            td.textContent = v;
            tr.appendChild(td);
        });

        const td = document.createElement("td");
        td.className = "actions";
        const btn = (label, cls, fn) => {
            const b = document.createElement("button");
            b.type = "button";
            b.className = "btn " + cls;
            b.textContent = label;
            b.addEventListener("click", fn);
            td.appendChild(b);
        };
        if (l.status !== "Approved") btn("Approve", "btn-primary", () => setLeaveStatus(l, "Approved"));
        if (l.status !== "Rejected") btn("Reject", "btn-secondary", () => setLeaveStatus(l, "Rejected"));
        btn("Delete", "btn-danger", () => deleteLeave(l));
        tr.appendChild(td);
        tbody.appendChild(tr);
    });
}

async function setLeaveStatus(l, status) {
    try {
        await api("/api/leaves/" + l.id + "/status", { method: "PUT", body: JSON.stringify({ status }) });
        toast("Leave " + status.toLowerCase() + ".");
        loadLeaves();
        loadDashboard();
    } catch (err) { toast(err.message, "error"); }   // e.g. "Not enough ... balance"
}

async function deleteLeave(l) {
    if (!confirm("Delete the leave request of " + l.employee + "?")) return;
    try {
        await api("/api/leaves/" + l.id, { method: "DELETE" });
        toast("Leave request deleted.");
        loadLeaves();
        loadDashboard();
    } catch (err) { toast(err.message, "error"); }
}

async function openLeaveModal() {
    let types, emps;
    try {
        [types, emps] = await Promise.all([api("/api/leave-types"), api("/api/employees?per_page=500&status=Active")]);
    } catch (err) {
        toast(err.message, "error");
        return;
    }
    byId("leave-form").reset();
    byId("leave-error").hidden = true;
    byId("lf-type").innerHTML = types.map((t) => `<option value="${escapeHtml(t)}">${escapeHtml(t)}</option>`).join("");
    byId("lf-employee").innerHTML = emps.items
        .map((e) => `<option value="${e.id}">${escapeHtml(e.name)}</option>`).join("");
    byId("leave-modal").hidden = false;
}

function closeLeaveModal() { byId("leave-modal").hidden = true; }

document.addEventListener("DOMContentLoaded", () => {
    byId("leave-filter").addEventListener("change", loadLeaves);
    byId("file-leave-btn").addEventListener("click", openLeaveModal);
    byId("leave-close").addEventListener("click", closeLeaveModal);
    byId("leave-cancel").addEventListener("click", closeLeaveModal);
    byId("leave-modal").addEventListener("click", (e) => { if (e.target.id === "leave-modal") closeLeaveModal(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeLeaveModal(); });

    byId("leave-form").addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const errBox = byId("leave-error");
        try {
            await api("/api/leaves", {
                method: "POST",
                body: JSON.stringify({
                    employee_id: byId("lf-employee").value,
                    leave_type: byId("lf-type").value,
                    start_date: byId("lf-start").value,
                    end_date: byId("lf-end").value,
                }),
            });
            closeLeaveModal();
            toast("Leave filed.");
            loadLeaves();
            loadDashboard();
        } catch (err) {
            errBox.textContent = err.message;
            errBox.hidden = false;
        }
    });
});


// ---------------------------------------------------------------- Reports
let reportData = null;

function fillReportTable(id, rows, cols, formatters = []) {
    const tbody = document.querySelector("#" + id + " tbody");
    tbody.innerHTML = "";
    if (!rows.length) return emptyRow(tbody, cols.length, "No data.");
    rows.forEach((r) => {
        const tr = document.createElement("tr");
        cols.forEach((c, i) => {
            const td = document.createElement("td");
            td.textContent = formatters[i] ? formatters[i](r[c]) : r[c];
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
}

async function loadReports() {
    try {
        reportData = await api("/api/admin/reports");
    } catch (err) {
        toast(err.message, "error");
        return;
    }
    const d = reportData;
    setText("rep-total", d.summary.total_employees);
    setText("rep-active", d.summary.active_employees);
    setText("rep-payroll", peso(d.summary.total_payroll));
    fillReportTable("rep-dept-table", d.by_department, ["department", "employees", "payroll"], [null, null, peso]);
    fillReportTable("rep-status-table", d.by_status, ["status", "total"]);
    fillReportTable("rep-role-table", d.by_role, ["role", "total"]);
}

function exportReportCsv() {
    if (!reportData) return toast("Open Reports first.", "error");
    const q = (v) => '"' + String(v ?? "").replace(/"/g, '""') + '"';
    const lines = [["Department", "Employees", "Monthly Payroll"].map(q).join(",")];
    reportData.by_department.forEach((r) =>
        lines.push([r.department, r.employees, Number(r.payroll).toFixed(2)].map(q).join(",")));
    lines.push("", ["Status", "Employees"].map(q).join(","));
    reportData.by_status.forEach((r) => lines.push([r.status, r.total].map(q).join(",")));
    lines.push("", ["Role", "Accounts"].map(q).join(","));
    reportData.by_role.forEach((r) => lines.push([r.role, r.total].map(q).join(",")));

    const blob = new Blob([lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "biri_go_report_" + new Date().toISOString().slice(0, 10) + ".csv";
    a.click();
    URL.revokeObjectURL(a.href);
}


// ---------------------------------------------------------------- Settings
async function loadSettings() {
    try {
        const p = await api("/api/settings/profile");
        setText("set-name", p.name || "-");
        setText("set-code", p.employee_code || "-");
        setText("set-email", p.email || "-");
        setText("set-role", (p.role || "-").toUpperCase());
    } catch (err) {
        toast(err.message, "error");
    }
}

document.addEventListener("DOMContentLoaded", () => {
    byId("print-report").addEventListener("click", () => window.print());
    byId("export-report").addEventListener("click", exportReportCsv);

    byId("password-form").addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const errBox = byId("password-error");
        errBox.hidden = true;

        const current = byId("pw-current").value;
        const next = byId("pw-new").value;
        if (!current) {
            errBox.textContent = "Enter your current password.";
            errBox.hidden = false;
            return;
        }
        if (next.length < 8) {
            errBox.textContent = "New password must be at least 8 characters.";
            errBox.hidden = false;
            return;
        }
        if (next !== byId("pw-confirm").value) {
            errBox.textContent = "New passwords do not match.";
            errBox.hidden = false;
            return;
        }
        try {
            await api("/api/settings/password", {
                method: "PUT",
                body: JSON.stringify({ current_password: current, new_password: next }),
            });
            byId("password-form").reset();
            toast("Password updated.");
        } catch (err) {
            errBox.textContent = err.message;
            errBox.hidden = false;
        }
    });
});