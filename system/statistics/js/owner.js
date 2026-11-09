/* Biri-Go owner dashboard.
 *   GET  /api/owner/summary                    dashboard numbers + today's attendance
 *   GET  /api/owner/employees
 *   GET  /api/owner/attendance?date=YYYY-MM-DD
 *   GET  /api/owner/leaves[?status=Pending]    |  POST /api/owner/leaves/<id>/decision {status}
 *   GET  /api/owner/payroll
 *   GET  /api/owner/announcements              |  POST ...  |  DELETE /api/owner/announcements/<id>
 */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const pad = (n) => String(n).padStart(2, '0');
  const peso = (n) => '\u20B1' + Number(n || 0).toLocaleString('en-PH', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const parse = (s) => new Date(`${String(s).slice(0, 10)}T00:00:00`);
  const fmtDate = (s) => (s ? parse(s).toLocaleDateString('en-PH', { month: 'short', day: 'numeric', year: 'numeric' }) : '-');
  const fmtPeriod = (s) => (s ? parse(s).toLocaleDateString('en-PH', { month: 'long', year: 'numeric' }) : '-');
  const days = (a, b) => Math.round((parse(b) - parse(a)) / 86400000) + 1;
  const localToday = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
  const BADGE = { Approved: 'b-green', Pending: 'b-orange', Rejected: 'b-red', Active: 'b-green', 'On Leave': 'b-orange', Present: 'b-green', Late: 'b-orange', Absent: 'b-red' };
  const badge = (s) => `<span class="badge ${BADGE[s] || 'b-grey'}">${esc(s || '-')}</span>`;
  const emptyRow = (cols, msg) => `<tr><td colspan="${cols}" class="empty-row">${esc(msg)}</td></tr>`;
  const range = (a, b) => (a === b ? fmtDate(a) : `${fmtDate(a)} - ${fmtDate(b)}`);
  const swatch = (i) => (i % 3 === 1 ? 'c1' : i % 3 === 2 ? 'c2' : '');
  const mobileQuery = window.matchMedia('(max-width: 900px)');
  const mobile = () => mobileQuery.matches;

  let employees = [];

  /* ---------- network ---------- */
  async function api(url, options = {}) {
    const token = document.querySelector('meta[name="csrf-token"]')?.content || '';
    const res = await fetch(url, {
      ...options,
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token, ...(options.headers || {}) },
      credentials: 'same-origin',
    });
    if (res.status === 401) { window.location.href = '/'; return new Promise(() => {}); }
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || `Request failed (${res.status})`);
    return body;
  }

  let toastTimer;
  function toast(message, isError) {
    const el = $('toast');
    el.textContent = message;
    el.className = isError ? 'toast toast-error' : 'toast toast-success';
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 3500);
  }
  function pageError(message) { const el = $('page-error'); el.textContent = message || ''; el.hidden = !message; }

  const decisionButtons = (id) =>
    `<button class="btn btn-sm btn-primary" type="button" data-decide="${id}" data-status="Approved">Approve</button>
     <button class="btn btn-sm btn-danger" type="button" data-decide="${id}" data-status="Rejected">Reject</button>`;
  const personCell = (r) => `<td class="name-cell"><strong>${esc(r.name)}</strong>${r.employee_code ? `<small>${esc(r.employee_code)}</small>` : ''}</td>`;

  /* ---------- dashboard ---------- */
  function attendanceRows(list) {
    return list.length ? list.map((a) =>
      `<tr>${personCell(a)}<td>${esc(a.department || '-')}</td><td>${esc(a.time_in || '-')}</td><td>${esc(a.time_out || '-')}</td><td>${badge(a.status)}</td></tr>`).join('')
      : emptyRow(5, 'No attendance records.');
  }

  async function loadDashboard() {
    const d = await api('/api/owner/summary');
    const s = d.stats;
    const name = d.owner_name || 'Owner';
    $('header-name').textContent = name;
    $('avatar').textContent = name.trim().slice(0, 2).toUpperCase();
    $('greeting').textContent = `Welcome back, ${name.split(' ')[0]}`;
    $('st-emp').textContent = s.employees;
    $('st-present').textContent = s.present_today;
    $('st-present-sub').textContent = s.employees ? `${Math.round((s.present_today / s.employees) * 100)}% of staff` : '\u00A0';
    $('st-leave').textContent = s.on_leave;
    $('st-pending').textContent = s.pending_leaves;
    $('st-payroll').textContent = peso(s.payroll_month);
    $('bell-dot').hidden = !s.pending_leaves;

    $('dash-leaves').innerHTML = d.pending_leaves.length ? d.pending_leaves.map((l) =>
      `<tr>${personCell(l)}<td>${esc(l.type)}</td><td>${range(l.start_date, l.end_date)}</td><td>${decisionButtons(l.id)}</td></tr>`).join('')
      : emptyRow(4, 'No pending requests.');

    const max = Math.max(1, ...d.departments.map((x) => x.count));
    $('dept-list').innerHTML = d.departments.length ? d.departments.map((x, i) =>
      `<div class="bal"><div class="bal-top"><span>${esc(x.name || 'Unassigned')}</span><span><strong>${x.count}</strong> employee${x.count === 1 ? '' : 's'}</span></div>
       <div class="bar ${swatch(i)}"><span style="width:${(x.count / max) * 100}%"></span></div></div>`).join('')
      : '<p class="muted small">No departments yet.</p>';

    $('dash-attendance').innerHTML = attendanceRows(d.attendance_today);
  }

  /* ---------- employees ---------- */
  function renderEmployees() {
    const dept = $('emp-dept').value;
    const q = $('emp-search').value.trim().toLowerCase();
    const list = employees.filter((e) => (!dept || e.department === dept)
      && (!q || [e.name, e.employee_code, e.email].some((v) => String(v || '').toLowerCase().includes(q))));
    $('emp-count').textContent = `${employees.length} employee${employees.length === 1 ? '' : 's'} on record`;
    $('emp-rows').innerHTML = list.length ? list.map((e) =>
      `<tr><td>${esc(e.employee_code)}</td><td><strong>${esc(e.name)}</strong></td><td>${esc(e.department || '-')}</td><td>${esc(e.position || '-')}</td>
       <td class="name-cell">${esc(e.email || '-')}<small>${esc(e.phone || '')}</small></td><td>${badge(e.status)}</td></tr>`).join('')
      : emptyRow(6, employees.length ? 'No employees match your search.' : 'No employees yet.');
  }

  async function loadEmployees() {
    employees = (await api('/api/owner/employees')).employees;
    const depts = [...new Set(employees.map((e) => e.department).filter(Boolean))].sort();
    const keep = $('emp-dept').value;
    $('emp-dept').innerHTML = '<option value="">All departments</option>' + depts.map((d) => `<option>${esc(d)}</option>`).join('');
    $('emp-dept').value = keep;
    renderEmployees();
  }

  /* ---------- attendance ---------- */
  async function loadAttendance() {
    const date = $('att-date').value || localToday();
    const d = await api(`/api/owner/attendance?date=${encodeURIComponent(date)}`);
    $('att-rows').innerHTML = attendanceRows(d.attendance);
  }

  /* ---------- leaves ---------- */
  async function loadLeaves() {
    const st = $('lv-filter').value;
    const d = await api(`/api/owner/leaves${st ? `?status=${encodeURIComponent(st)}` : ''}`);
    $('lv-rows').innerHTML = d.leaves.length ? d.leaves.map((l) =>
      `<tr>${personCell(l)}<td>${esc(l.type)}</td><td>${range(l.start_date, l.end_date)}</td><td>${days(l.start_date, l.end_date)}</td>
       <td>${badge(l.status)}</td><td>${l.status === 'Pending' ? decisionButtons(l.id) : '-'}</td></tr>`).join('')
      : emptyRow(6, 'No leave requests.');
  }

  async function decide(id, status) {
    if (!confirm(`${status === 'Approved' ? 'Approve' : 'Reject'} this leave request?`)) return;
    try {
      await api(`/api/owner/leaves/${id}/decision`, { method: 'POST', body: JSON.stringify({ status }) });
      toast(`Leave ${status.toLowerCase()}.`);
      await Promise.all([loadDashboard(), loadLeaves()]);
    } catch (e) { toast(e.message, true); }
  }

  /* ---------- payroll ---------- */
  async function loadPayroll() {
    const d = await api('/api/owner/payroll');
    $('pay-total').textContent = `Net pay this month: ${peso(d.month_total)}`;
    $('pay-rows').innerHTML = d.payslips.length ? d.payslips.map((p) =>
      `<tr>${personCell(p)}<td>${fmtPeriod(p.pay_period)}</td><td>${peso(p.gross_pay)}</td><td>${peso(p.deductions)}</td><td><strong>${peso(p.net_pay)}</strong></td></tr>`).join('')
      : emptyRow(5, 'No payslips yet.');
  }

  /* ---------- announcements ---------- */
  async function loadNews() {
    const d = await api('/api/owner/announcements');
    $('news-list').innerHTML = d.announcements.length ? d.announcements.map((a, i) =>
      `<li><span class="swatch ${swatch(i)}" aria-hidden="true"></span><div><strong>${esc(a.title)}</strong><p>${esc(a.body)}</p><small>${fmtDate(a.date)}</small></div>
       <button class="btn btn-danger btn-sm" type="button" data-del-news="${a.id}" aria-label="Delete ${esc(a.title)}"><i class="far fa-trash-can" aria-hidden="true"></i></button></li>`).join('')
      : '<li class="empty muted small">No announcements yet.</li>';
  }

  async function submitNews(ev) {
    ev.preventDefault();
    const err = $('news-error');
    err.hidden = true;
    $('news-submit').disabled = true;
    try {
      await api('/api/owner/announcements', { method: 'POST', body: JSON.stringify({ title: $('news-title-in').value.trim(), body: $('news-body').value.trim() }) });
      $('news-dialog').close();
      toast('Announcement posted.');
      await loadNews();
    } catch (e) { err.textContent = e.message; err.hidden = false; }
    finally { $('news-submit').disabled = false; }
  }

  async function deleteNews(id) {
    if (!confirm('Delete this announcement?')) return;
    try { await api(`/api/owner/announcements/${id}`, { method: 'DELETE' }); toast('Announcement deleted.'); await loadNews(); }
    catch (e) { toast(e.message, true); }
  }

  /* ---------- navigation ---------- */
  const LOADERS = { dashboard: loadDashboard, employees: loadEmployees, attendance: loadAttendance, leaves: loadLeaves, payroll: loadPayroll, news: loadNews };

  async function showPage(name) {
    if (!LOADERS[name]) name = 'dashboard';
    document.querySelectorAll('.page').forEach((p) => p.classList.toggle('active', p.id === `page-${name}`));
    document.querySelectorAll('#sidebar li').forEach((li) => {
      const on = li.dataset.page === name;
      li.classList.toggle('active', on);
      if (on) li.setAttribute('aria-current', 'page'); else li.removeAttribute('aria-current');
    });
    $('main').scrollTo({ top: 0 }); window.scrollTo(0, 0);
    if (location.hash !== `#${name}`) history.replaceState(null, '', `#${name}`);
    if (mobile()) setNav(false);
    try { pageError(''); await LOADERS[name](); } catch (e) { pageError(e.message); }
  }

  function setNav(open) {
    if (mobile()) document.body.classList.toggle('nav-open', open);
    else document.body.classList.toggle('nav-collapsed', !open);
    $('menu-toggle').setAttribute('aria-expanded', String(open));
  }
  const navOpen = () => (mobile() ? document.body.classList.contains('nav-open') : !document.body.classList.contains('nav-collapsed'));
  function setUserMenu(open) { $('user-menu').hidden = !open; $('user-btn').setAttribute('aria-expanded', String(open)); }

  function bind() {
    $('menu-toggle').addEventListener('click', () => setNav(!navOpen()));
    mobileQuery.addEventListener('change', () => { document.body.classList.remove('nav-open', 'nav-collapsed'); setNav(!mobile()); });
    $('main').addEventListener('click', () => { if (mobile() && navOpen()) setNav(false); });
    $('user-btn').addEventListener('click', (e) => { e.stopPropagation(); setUserMenu($('user-menu').hidden); });
    document.addEventListener('click', (e) => { if (!e.target.closest('.user-menu')) setUserMenu(false); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('user-menu').hidden) { setUserMenu(false); $('user-btn').focus(); } });

    document.querySelectorAll('#sidebar li').forEach((li) => {
      const go = () => showPage(li.dataset.page);
      li.addEventListener('click', go);
      li.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
    });
    window.addEventListener('hashchange', () => showPage(location.hash.slice(1) || 'dashboard'));
    $('bell').addEventListener('click', () => showPage('leaves'));
    document.querySelectorAll('[data-page-link]').forEach((b) => b.addEventListener('click', () => showPage(b.dataset.pageLink)));

    // Approve / reject buttons (dashboard + leaves page)
    document.addEventListener('click', (e) => {
      const b = e.target.closest('[data-decide]');
      if (b) decide(b.dataset.decide, b.dataset.status);
      const n = e.target.closest('[data-del-news]');
      if (n) deleteNews(n.dataset.delNews);
    });

    $('emp-search').addEventListener('input', renderEmployees);
    $('emp-dept').addEventListener('change', renderEmployees);
    $('att-date').value = localToday();
    $('att-date').addEventListener('change', () => loadAttendance().catch((e) => pageError(e.message)));
    $('lv-filter').addEventListener('change', () => loadLeaves().catch((e) => pageError(e.message)));

    $('open-news').addEventListener('click', () => { $('news-form').reset(); $('news-error').hidden = true; $('news-dialog').showModal(); });
    $('news-cancel').addEventListener('click', () => $('news-dialog').close());
    $('news-dialog').addEventListener('click', (e) => { if (e.target === e.currentTarget) e.currentTarget.close(); });
    $('news-form').addEventListener('submit', submitNews);

    if (mobile()) setNav(false);
  }

  document.addEventListener('DOMContentLoaded', () => {
    $('today-date').textContent = new Date().toLocaleDateString('en-PH', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
    bind();
    showPage(location.hash.slice(1) || 'dashboard');
  });
})();