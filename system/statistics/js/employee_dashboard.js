/* Biri-Go employee dashboard.
 *   GET  /api/employee/me                      profile
 *   GET  /api/employee/summary                 everything shown on the dashboard
 *   POST /api/employee/attendance/check-in     |  .../check-out
 *   POST /api/employee/leaves                  { type, start_date, end_date }
 *   GET  /employee/payslips/<id>[?download=1]  PDF payslip
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
  const hhmm = (secs) => `${pad(Math.floor(secs / 3600))}:${pad(Math.floor((secs % 3600) / 60))}`;
  const toSecs = (t) => (t ? +t.slice(0, 2) * 3600 + +t.slice(3, 5) * 60 : null);
  const localToday = () => { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };

  // Status -> badge class (these match the b-* / badge-* classes in the stylesheet)
  const BADGE = { Approved: 'b-green', Pending: 'b-orange', Rejected: 'b-red', Active: 'b-green', 'On Leave': 'b-orange', Resigned: 'b-grey', Terminated: 'b-red' };
  const badgeClass = (s) => BADGE[s] || 'b-grey';
  const badge = (s) => `<span class="badge ${badgeClass(s)}">${esc(s)}</span>`;
  const emptyRow = (cols, msg) => `<tr><td colspan="${cols}" class="empty-row">${esc(msg)}</td></tr>`;
  const swatch = (i) => (i % 3 === 1 ? 'c1' : i % 3 === 2 ? 'c2' : '');

  let me = null;
  let data = null;
  let loadedAt = 0;
  const mobileQuery = window.matchMedia('(max-width: 900px)');
  const mobile = () => mobileQuery.matches;

  /* ---------- network ---------- */
  async function api(url, options = {}) {
    const token = document.querySelector('meta[name="csrf-token"]')?.content || '';

    const isForm = options.body instanceof FormData;
    const res = await fetch(url, {
      ...options,
      headers: {
        ...(isForm ? {} : { 'Content-Type': 'application/json' }),
        'X-CSRF-Token': token,
        ...(options.headers || {})
      },
      credentials: 'same-origin'
    });

    if (res.status === 401) {
      window.location.href = '/';
      return new Promise(() => {});
    }

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
  function pageError(message) {
    const el = $('page-error');
    el.textContent = message || '';
    el.hidden = !message;
  }

  /* ---------- rendering ---------- */
  function renderProfile() {
    const full = [me.first_name, me.middle_name, me.last_name, me.suffix && me.suffix.toLowerCase() !== 'none' ? me.suffix : '']
      .filter(Boolean).join(' ');
    const initials = `${(me.first_name || '?')[0]}${(me.last_name || '')[0] || ''}`.toUpperCase();
    $('avatar').textContent = initials;
    $('profile-avatar').textContent = initials;
    $('header-name').textContent = me.first_name ? `${me.first_name} ${me.last_name}` : 'Employee';
    $('profile-name').textContent = full || '-';
    $('card-position').textContent = me.position || '-';
    $('card-department').textContent = me.department || '-';

    const status = $('card-status');
    status.textContent = me.status || '-';
    status.className = `badge ${badgeClass(me.status)}`;

    $('greeting').textContent = `Welcome back, ${me.first_name || 'there'}`;
    $('att-place-text').textContent = me.department || '-';
    const rows = [
      ['Employee ID', me.employee_code], ['Full name', full], ['Email', me.email], ['Phone', me.phone],
      ['Birthday', fmtDate(me.birthday)], ['Sex', me.sex], ['Department', me.department], ['Position', me.position], ['Status', me.status],
    ];
    $('profile-rows').innerHTML = rows.map(([k, v]) => `<tr><th scope="row">${esc(k)}</th><td>${esc(v || '-')}</td></tr>`).join('');
  }

  function renderStats() {
    const s = data.stats;
    $('st-days').textContent = s.days_present;
    $('st-days-sub').textContent = `of ${s.working_days} working days`;
    $('st-rate').textContent = s.attendance_rate == null ? '-' : `${s.attendance_rate}%`;
    $('st-rate-sub').textContent = 'This month';
    $('st-leave').textContent = data.leave_balances.reduce((n, b) => n + b.remaining, 0);
    $('st-hours').textContent = `${s.hours_month}h`;
    $('st-hours-sub').textContent = `of ${s.working_days * data.daily_target}h target`;
    $('card-pending').textContent = data.leave_counts.Pending || 0;
  }

  function serverSeconds() { return data.server_now + (Date.now() - loadedAt) / 1000; }

  function renderAttendanceCard() {
    const t = data.today;
    const target = data.daily_target * 3600;
    let worked = 0;
    let chip = 'Not checked in', chipClass = 'b-grey', btn = 'Check in', disabled = false;
    if (t && t.time_in) {
      const end = t.time_out ? toSecs(t.time_out) : serverSeconds();
      worked = Math.max(0, end - toSecs(t.time_in));
      if (t.time_out) { chip = 'Completed'; chipClass = 'b-blue'; btn = 'Done for today'; disabled = true; }
      else { chip = t.status === 'Late' ? 'Working (late)' : 'Working'; chipClass = t.status === 'Late' ? 'b-orange' : 'b-green'; btn = 'Check out'; }
    }
    $('att-chip').textContent = chip;
    $('att-chip').className = `badge ${chipClass}`;
    $('att-clock').textContent = hhmm(worked);
    $('att-in').textContent = (t && t.time_in_label) || '-';
    $('att-out').textContent = (t && t.time_out_label) || '-';
    $('att-shift').textContent = `${data.shift.start} - ${data.shift.end}`;
    $('att-bar').style.width = `${Math.min(100, (worked / target) * 100)}%`;
    $('att-btn').textContent = btn;
    $('att-btn').disabled = disabled;
  }

  function renderBalances() {
    $('balance-list').innerHTML = data.leave_balances.length ? data.leave_balances.map((b, i) => {
      const pct = b.total ? Math.min(100, (b.used / b.total) * 100) : 0;
      return `<div class="bal"><div class="bal-top"><span>${esc(b.type)}</span><span><strong>${b.remaining}</strong> of ${b.total} days left</span></div>
        <div class="bar ${swatch(i)}"><span style="width:${pct}%"></span></div></div>`;
    }).join('') : '<p class="muted small">No leave balances.</p>';
    $('balance-note').textContent = `Balances count approved leave for ${new Date().getFullYear()}.`;
  }

  function renderPay() {
    const p = data.payslips[0];
    $('pay-body').hidden = !p;
    $('pay-empty').hidden = !!p;
    if (!p) return;
    $('pay-period').textContent = fmtPeriod(p.pay_period);
    $('pay-net').textContent = peso(p.net_pay);
    const unlocked = !!p.hr_confirmed && !!p.employee_confirmed;
    $('pay-confirmation').textContent = !p.hr_confirmed
      ? 'Waiting for HR to confirm that payment has been made.'
      : !p.employee_confirmed
        ? 'HR confirmed payment. Please acknowledge receipt to unlock your official payslip.'
        : 'Payment and receipt are confirmed. Your official payslip is available.';
    $('pay-confirm').hidden = !p.hr_confirmed || !!p.employee_confirmed;
    $('pay-download').hidden = !unlocked;
    $('pay-view').hidden = !unlocked;
    $('pay-download').href = `/employee/payslips/${p.id}?download=1`;
    $('pay-view').href = `/employee/payslips/${p.id}`;
  }

  function renderTables() {
    $('leave-rows').innerHTML = data.leaves.length ? data.leaves.map((l) => {
      const n = days(l.start_date, l.end_date);
      const range = l.start_date === l.end_date ? fmtDate(l.start_date) : `${fmtDate(l.start_date)} - ${fmtDate(l.end_date)}`;
      return `<tr><td>${esc(l.type)}</td><td>${range}</td><td>${n} day${n === 1 ? '' : 's'}</td><td>${badge(l.status)}</td></tr>`;
    }).join('') : emptyRow(4, 'No leave requests yet.');

    $('attendance-rows').innerHTML = data.attendance.length ? data.attendance.map((a) =>
      `<tr><td>${fmtDate(a.work_date)}</td><td>${esc(a.time_in || '-')}</td><td>${esc(a.time_out || '-')}</td></tr>`).join('')
      : emptyRow(3, 'No attendance records yet.');

    $('payslip-rows').innerHTML = data.payslips.length ? data.payslips.map((p) => {
      const unlocked = !!p.hr_confirmed && !!p.employee_confirmed;
      const status = !p.hr_confirmed ? 'Waiting for HR' : !p.employee_confirmed ? 'Awaiting your confirmation' : 'Confirmed';
      const action = unlocked
        ? `<a href="/employee/payslips/${p.id}" target="_blank" rel="noopener">View</a> · <a href="/employee/payslips/${p.id}?download=1" download>Download</a>`
        : p.hr_confirmed
          ? `<button class="btn btn-primary btn-sm" type="button" data-confirm-payslip="${p.id}">Confirm receipt</button>`
          : '<span class="muted">Not available yet</span>';
      return `<tr><td>${fmtPeriod(p.pay_period)}</td><td>${peso(p.gross_pay)}</td><td>${peso(p.deductions)}</td><td>${peso(p.net_pay)}</td><td>${badge(status)}</td><td>${action}</td></tr>`;
    }).join('') : emptyRow(6, 'No payslips yet.');
  }

  function renderNews() {
    $('news-list').innerHTML = data.announcements.length ? data.announcements.map((a, i) =>
      `<li><span class="swatch ${swatch(i)}" aria-hidden="true"></span><div><strong>${esc(a.title)}</strong><p>${esc(a.body)}</p><small>${fmtDate(a.date)}</small></div></li>`).join('')
      : '<li class="empty muted small">No announcements.</li>';
    const weekAgo = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
    $('bell-dot').hidden = !data.announcements.some((a) => a.date >= weekAgo);
  }

  function renderActivity() {
    const items = [];
    if (data.leaves[0]) items.push(['Latest leave request', `${data.leaves[0].type} - ${data.leaves[0].status}`, fmtDate(data.leaves[0].start_date)]);
    if (data.attendance[0]) items.push(['Last attendance', `In ${data.attendance[0].time_in || '-'}, out ${data.attendance[0].time_out || '-'}`, fmtDate(data.attendance[0].work_date)]);
    if (data.payslips[0]) items.push(['Latest payslip', `Net ${peso(data.payslips[0].net_pay)}`, fmtPeriod(data.payslips[0].pay_period)]);
    $('activity-list').innerHTML = items.length ? items.map(([title, text, when], i) =>
      `<li><span class="swatch ${i === 1 ? 'c2' : i === 2 ? 'c1' : ''}" aria-hidden="true"></span><div><strong>${esc(title)}</strong><small>${esc(text)}</small><small>${esc(when)}</small></div></li>`).join('')
      : '<li class="empty muted small">Nothing yet.</li>';
  }

  function renderAll() {
    renderStats(); renderAttendanceCard(); renderBalances(); renderPay(); renderTables(); renderNews(); renderActivity();
  }

  async function loadSummary() {
    data = await api('/api/employee/summary');
    loadedAt = Date.now();
    renderAll();
  }

  /* ---------- actions ---------- */
  async function toggleAttendance() {
    const t = data.today;
    const btn = $('att-btn');
    btn.disabled = true;
    try {
      const r = await api(`/api/employee/attendance/check-${t && t.time_in ? 'out' : 'in'}`, { method: 'POST', body: '{}' });
      toast(r.message || 'Done.');
      await loadSummary();
    } catch (err) { toast(err.message, true); renderAttendanceCard(); }
  }

  function openLeave() {
    if (!data) return;
    $('lv-type').innerHTML = data.leave_types.map((t) => `<option>${esc(t)}</option>`).join('');
    const today = localToday();
    $('lv-start').value = today; $('lv-end').value = today;
    $('lv-start').min = today; $('lv-end').min = today;
    $('lv-reason').value = '';
    $('lv-error').hidden = true;
    $('leave-dialog').showModal();
  }

  async function submitLeave(ev) {
    ev.preventDefault();
    const err = $('lv-error');
    err.hidden = true;
    const body = {
      type: $('lv-type').value,
      start_date: $('lv-start').value,
      end_date: $('lv-end').value,
      reason: $('lv-reason').value.trim()
    };
    if (!body.reason) {
      err.textContent = 'Please provide a reason for your leave request.';
      err.hidden = false;
      $('lv-reason').focus();
      return;
    }
    if (body.end_date < body.start_date) { err.textContent = 'The end date cannot be before the start date.'; err.hidden = false; return; }
    $('lv-submit').disabled = true;
    try {
      await api('/api/employee/leaves', { method: 'POST', body: JSON.stringify(body) });
      $('leave-dialog').close();
      toast('Leave request sent.');
      await loadSummary();
    } catch (e) { err.textContent = e.message; err.hidden = false; }
    finally { $('lv-submit').disabled = false; }
  }

  /* ---------- documents ---------- */
  const DOC_CATEGORIES = ['Government ID', 'Contract', 'Certificate', 'Medical', 'Other'];
  const DOC_EXT = ['pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png'];
  const DOC_MAX = 5 * 1024 * 1024;
  let docs = [];
  const fmtSize = (b) => (b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);
  const docIcon = (name) => {
    const ext = String(name).split('.').pop().toLowerCase();
    return ext === 'pdf' ? 'fa-file-pdf' : ext === 'doc' || ext === 'docx' ? 'fa-file-word' : 'fa-file-image';
  };

  function renderDocuments() {
    const cat = $('doc-filter').value;
    const q = $('doc-search').value.trim().toLowerCase();
    const list = docs.filter((d) => (!cat || d.category === cat)
      && (!q || d.title.toLowerCase().includes(q) || d.original_name.toLowerCase().includes(q)));
    $('doc-count').textContent = `${docs.length} document${docs.length === 1 ? '' : 's'} on record`;
    $('doc-rows').innerHTML = list.length ? list.map((d) =>
      `<tr>
        <td><i class="far ${docIcon(d.original_name)}" aria-hidden="true"></i> <strong>${esc(d.title)}</strong><br><small class="muted">${esc(d.original_name)}</small></td>
        <td><span class="badge b-blue">${esc(d.category)}</span></td>
        <td>${fmtSize(d.size_bytes)}</td>
        <td>${fmtDate(d.uploaded_at)}</td>
        <td>
          <a class="btn btn-secondary btn-ghost btn-sm" href="/employee/documents/${d.id}/view" target="_blank" rel="noopener" aria-label="View ${esc(d.title)}"><i class="far fa-eye" aria-hidden="true"></i></a>
          <a class="btn btn-secondary btn-ghost btn-sm" href="/employee/documents/${d.id}/download" aria-label="Download ${esc(d.title)}"><i class="fas fa-download" aria-hidden="true"></i></a>
          <button class="btn btn-danger btn-sm" type="button" data-del-doc="${d.id}" aria-label="Delete ${esc(d.title)}"><i class="far fa-trash-can" aria-hidden="true"></i></button>
        </td>
      </tr>`).join('')
      : emptyRow(5, docs.length ? 'No documents match your search.' : 'No documents uploaded yet.');
  }

  async function loadDocuments() {
    try {
      docs = (await api('/api/employee/documents')).documents || [];
      renderDocuments();
    } catch (err) {
      $('doc-rows').innerHTML = emptyRow(5, err.message);
    }
  }

  function openDocDialog() {
    $('doc-form').reset();
    $('doc-error').hidden = true;
    $('doc-dialog').showModal();
  }

  async function submitDoc(ev) {
    ev.preventDefault();
    const err = $('doc-error');
    err.hidden = true;
    const file = $('doc-file').files[0];
    const fail = (m) => { err.textContent = m; err.hidden = false; };
    if (!file) return fail('Please choose a file.');
    if (!DOC_EXT.includes(file.name.split('.').pop().toLowerCase())) return fail('Only PDF, Word, JPG or PNG files are allowed.');
    if (file.size > DOC_MAX) return fail('The file is too large (maximum 5 MB).');

    const form = new FormData();
    form.append('title', $('doc-title').value.trim());
    form.append('category', $('doc-category').value);
    form.append('file', file);
    $('doc-submit').disabled = true;
    try {
      await api('/api/employee/documents', { method: 'POST', body: form });
      $('doc-dialog').close();
      toast('Document uploaded.');
      await loadDocuments();
    } catch (e) { fail(e.message); }
    finally { $('doc-submit').disabled = false; }
  }

  async function deleteDoc(id) {
    const d = docs.find((x) => String(x.id) === String(id));
    if (!d || !confirm(`Delete "${d.title}"? This cannot be undone.`)) return;
    try {
      await api(`/api/employee/documents/${id}`, { method: 'DELETE' });
      toast('Document deleted.');
      await loadDocuments();
    } catch (e) { toast(e.message, true); }
  }

  /* ---------- navigation ---------- */
  function scrollTop() {
    // On desktop the page scrolls inside .main-content; on small screens it scrolls the window.
    $('main').scrollTo({ top: 0 });
    window.scrollTo(0, 0);
  }

  function showPage(name) {
    if (!$(`page-${name}`)) name = 'dashboard';
    document.querySelectorAll('.page').forEach((p) => p.classList.toggle('active', p.id === `page-${name}`));
    document.querySelectorAll('#sidebar li').forEach((li) => {
      const on = li.dataset.page === name;
      li.classList.toggle('active', on);
      if (on) li.setAttribute('aria-current', 'page'); else li.removeAttribute('aria-current');
    });
    scrollTop();
    if (name === 'documents') loadDocuments();
    // Keep the current page on refresh / browser back
    if (location.hash !== `#${name}`) history.replaceState(null, '', `#${name}`);
    if (mobile()) setNav(false);
  }

  function setNav(open) {
    if (mobile()) document.body.classList.toggle('nav-open', open);
    else document.body.classList.toggle('nav-collapsed', !open);
    $('menu-toggle').setAttribute('aria-expanded', String(open));
  }
  const navOpen = () => (mobile() ? document.body.classList.contains('nav-open') : !document.body.classList.contains('nav-collapsed'));

  function setUserMenu(open) {
    $('user-menu').hidden = !open;
    $('user-btn').setAttribute('aria-expanded', String(open));
  }

  function bind() {
    $('menu-toggle').addEventListener('click', () => setNav(!navOpen()));

    // Reset the sidebar when crossing the mobile breakpoint
    mobileQuery.addEventListener('change', () => {
      document.body.classList.remove('nav-open', 'nav-collapsed');
      setNav(!mobile());
    });
    // Tapping the content closes the mobile drawer
    $('main').addEventListener('click', () => { if (mobile() && navOpen()) setNav(false); });

    $('user-btn').addEventListener('click', (e) => { e.stopPropagation(); setUserMenu($('user-menu').hidden); });
    document.addEventListener('click', (e) => { if (!e.target.closest('.user-menu')) setUserMenu(false); });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !$('user-menu').hidden) { setUserMenu(false); $('user-btn').focus(); }
    });
    $('user-menu').addEventListener('click', (e) => {
      const item = e.target.closest('[data-page]');
      if (item) showPage(item.dataset.page);
      setUserMenu(false);
    });

    // Sidebar: each item opens its own page
    document.querySelectorAll('#sidebar li').forEach((li) => {
      const go = () => {
        if (li.dataset.page) return showPage(li.dataset.page);
        if (li.dataset.soon) toast(`${li.dataset.soon} is coming soon.`);
      };
      li.addEventListener('click', go);
      li.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
    });

    // Browser back / forward and manual hash changes
    window.addEventListener('hashchange', () => showPage(location.hash.slice(1) || 'dashboard'));

    document.querySelectorAll('[data-action="help"]').forEach((b) =>
      b.addEventListener('click', () => toast('Need help? Contact your HR team.')));
    $('bell').addEventListener('click', () => showPage('news'));

    $('att-btn').addEventListener('click', toggleAttendance);
    document.querySelectorAll('[data-action="open-leave"]').forEach((b) => b.addEventListener('click', openLeave));
    $('lv-cancel').addEventListener('click', () => $('leave-dialog').close());
    $('leave-dialog').addEventListener('click', (e) => { if (e.target === e.currentTarget) e.currentTarget.close(); }); // backdrop click
    $('leave-form').addEventListener('submit', submitLeave);
    $('lv-start').addEventListener('change', () => { if ($('lv-end').value < $('lv-start').value) $('lv-end').value = $('lv-start').value; });

    // Documents
    const catOptions = DOC_CATEGORIES.map((c) => `<option>${esc(c)}</option>`).join('');
    $('doc-category').innerHTML = catOptions;
    $('doc-filter').innerHTML = `<option value="">All categories</option>${catOptions}`;
    $('doc-filter').addEventListener('change', renderDocuments);
    $('doc-search').addEventListener('input', renderDocuments);
    $('open-doc').addEventListener('click', openDocDialog);
    $('doc-cancel').addEventListener('click', () => $('doc-dialog').close());
    $('doc-dialog').addEventListener('click', (e) => { if (e.target === e.currentTarget) e.currentTarget.close(); });
    $('doc-form').addEventListener('submit', submitDoc);
    $('pay-confirm').addEventListener('click', async () => {
      const p = data && data.payslips[0];
      if (!p || !p.hr_confirmed || p.employee_confirmed) return;
      $('pay-confirm').disabled = true;
      try {
        const result = await api(`/api/employee/payslips/${p.id}/confirm`, { method: 'POST', body: '{}' });
        toast(result.message || 'Receipt confirmed.');
        await loadSummary();
      } catch (err) { toast(err.message, true); }
      finally { $('pay-confirm').disabled = false; }
    });

    $('payslip-rows').addEventListener('click', async (e) => {
      const button = e.target.closest('[data-confirm-payslip]');
      if (!button) return;
      button.disabled = true;
      try {
        const result = await api(`/api/employee/payslips/${button.dataset.confirmPayslip}/confirm`, { method: 'POST', body: '{}' });
        toast(result.message || 'Receipt confirmed.');
        await loadSummary();
      } catch (err) { toast(err.message, true); }
      finally { button.disabled = false; }
    });
    $('doc-rows').addEventListener('click', (e) => {
      const b = e.target.closest('[data-del-doc]');
      if (b) deleteDoc(b.dataset.delDoc);
    });

    if (mobile()) setNav(false);
    setInterval(() => { if (data && !document.hidden) renderAttendanceCard(); }, 30000);   // keeps "hours worked today" ticking
    document.addEventListener('visibilitychange', () => { if (data && !document.hidden) renderAttendanceCard(); });
  }

  document.addEventListener('DOMContentLoaded', async () => {
    $('today-date').textContent = new Date().toLocaleDateString('en-PH', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
    bind();
    // Open the page named in the URL hash (e.g. #leaves), if any
    const start = location.hash.slice(1);
    if (start && $(`page-${start}`)) showPage(start);
    try {
      me = await api('/api/employee/me');
      renderProfile();
      await loadSummary();
      loadDocuments();
    } catch (err) {
      pageError(err.message);
    }
  });
})();