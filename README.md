<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo.png">
    <img src="assets/logo-dark.png" alt="Biringan Go Logistics" width="250" style="display: block; margin: 0;"/>
  </picture>
</div>

<h1 align="center" style="font-size: 40px;">Biri-Go</h1>

<p align="center">
  <img src="https://img.shields.io/badge/Python-111111?style=flat-square&logo=python&logoColor=3776AB" alt="Python">
  <img src="https://img.shields.io/badge/Flask-111111?style=flat-square&logo=flask&logoColor=FFFFFF" alt="Flask">
  <img src="https://img.shields.io/badge/MySQL_Connector%2FPython-111111?style=flat-square&logo=mysql&logoColor=4479A1" alt="MySQL Connector/Python">
  <br>
  <img src="https://img.shields.io/badge/JavaScript-111111?style=flat-square&logo=javascript&logoColor=F7DF1E" alt="JavaScript">
  <img src="https://img.shields.io/badge/HTML5-111111?style=flat-square&logo=html5&logoColor=E34F26" alt="HTML5">
  <img src="https://img.shields.io/badge/CSS3-111111?style=flat-square&logo=css3&logoColor=1572B6" alt="CSS3">
  <img src="https://img.shields.io/badge/Git-111111?style=flat-square&logo=git&logoColor=F05032" alt="Git">
  <img src="https://img.shields.io/badge/GitHub-111111?style=flat-square&logo=github&logoColor=FFFFFF" alt="GitHub">
</p>

<br>

Biri-Go (Biringan Employee Management System) is a web-based employee management system for a logistics company. Staff sign in to a role-based browser portal (admin, HR, owner, or employee) that covers employee records, attendance, leave, payroll, and company reports. A Flask backend serves every portal, and all records live in one shared MySQL database. It can also run as a standalone Windows desktop app.

### Quick start

```bash
pip install -r requirements.txt
```

### 2. Set up the database

Create the `biri_go` database and load the base schema (`Biri-Go.sql`):

```bash
mysql -u root -p < Biri-Go.sql
```

> The core tables (`account`, `employees`, `departments`, `positions`, `leave_requests`, `attendance`) come from `Biri-Go.sql`. The app creates and upgrades the remaining tables (payroll, activity log, HR tables) on startup when `DB_AUTO_INIT=1`, which is the default in development.

### 3. Configure environment variables

Never commit these values.

```bash
# macOS / Linux
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
export DB_PASSWORD=your-mysql-password      # optional: DB_HOST, DB_USER, DB_NAME

cd system/backend
python main.py                              # http://127.0.0.1:5000
```

On the first run against an empty database, the console prints a one-time password for the admin account `biri-000000`. Sign in and change it right away under **Settings → Change Password**. On Windows PowerShell, set variables with `$env:SECRET_KEY = "..."` instead of `export`.

### Features

- **Four role-based portals:** Admin, HR, Owner, and Employee each get their own page and API. Roles are enforced on the server, so one role cannot reach another's data.
- **Employee records and accounts:** Add, edit, and remove employees with server-side validation (names, Philippine mobile numbers, 18+ age check, salary range). Each account gets a generated ID such as `biri-048213`.
- **Departments and positions:** Admin and HR manage departments and department heads, and every position belongs to a department.
- **Attendance:** Employees check in and check out from their dashboard. Status (Present, Late, Absent, On Leave) follows the work hours and grace period set in HR Settings, and HR can record overtime and remarks.
- **Leave management:** Vacation, Sick, Emergency, Bereavement, Maternity, Paternity, Parental, Special, and Unpaid leave. Requests are checked for overlaps, remaining balance, and sex-restricted types, and are approved or rejected by admin or HR with a leave calendar and balances view. Vacation, Sick, and Emergency entitlements are editable.
- **Payroll and payslips:** HR generates monthly payroll with overtime pay (1.25×), absence and unpaid-leave deductions, allowances, and manual deductions. HR confirms payment, the employee acknowledges receipt, and payslips download as PDFs.
- **HR tools:** Recruitment (job postings and an applicant board), onboarding and offboarding checklists, performance reviews, training sessions, announcements, and company holidays.
- **Owner portal (view-only):** The owner sees everything HR sees, plus salaries and payroll. Every write request to the owner API is rejected.
- **Reports and activity log:** Company reports for admin, HR, and the owner, and an activity log of key actions.
- **Backup and restore:** Create, verify, restore, and delete compressed database backups from the Admin portal or the command line. Restoring takes a safety backup first when possible.
- **Profiles:** Every user can view their profile, upload a profile picture (validated and resized to 256×256), and change their password.
- **Security by default:** Hashed passwords, CSRF tokens on every write request, JSON-only write endpoints, login rate limiting, a strict Content-Security-Policy, and a production mode that refuses to start with unsafe settings.
- **Desktop app:** Wrap the app in a native window with `pywebview` and package it into an `.exe` with PyInstaller.

### Roles

| Capability | Admin | HR | Owner | Employee |
|---|:-:|:-:|:-:|:-:|
| Accounts, positions, backups, admin reports | ✔ | | | |
| Employees, departments, leaves, salaries | ✔ | | | |
| Attendance, payroll, recruitment, onboarding, reviews, training, announcements, holidays | | ✔ | | |
| View-only access to HR data, salaries, and payroll | | | ✔ | |
| Check-in/out, own leave requests, payslips, profile | | | | ✔ |

### Project structure

```
system/
├── backend/        Flask app: main.py, config.py, auth.py, db.py, utils.py,
│                   backup_restore.py, profile_pictures.py, desktop.py
│   └── routes/     admin.py, hr.py, owner.py, employee.py, my_pay.py
├── template/       login, admin, hr, owner, employee_dashboard (.html)
└── statistics/     static CSS, JS, and images, served at /statistics
```

### Production

Set `APP_ENV=production` and the app will refuse to start unless `SECRET_KEY` is set (32+ characters), the database user is not `root` or `admin`, automatic schema setup is off, and debug mode is off. Use a least-privilege database account (`system/backend/create_app_user.sql.example`) and serve over HTTPS. The full runbook, including backup, verify, and restore commands, is in [system/backend/SECURITY_OPERATIONS.md](system/backend/SECURITY_OPERATIONS.md). To report a vulnerability, see [SECURITY.md](SECURITY.md).

### Developers

**[Arca, Howard Lance A.]**  
**[Armia, Ron Cedrick G.]**  
**[Suministrado, Brian James F.]**  


---

## Coursework Project

**[Laguna State Polytechnic University]** | **[College of Computer Studies]**  
**[CMSC 203 - Object Oriented Programming], [CITEC 104 – Data Structures and Algorithm], [ITEC 105 – Information Management]**  
**Instructors:** [Ms. Roxanne Garbo, Sir Rolan C. Sotomayor, Sir Jencel P. Sofer]  
**Academic Year:** [2026–2027]

Biri-Go is developed as the final project for [course names]. It demonstrates [what your project shows, for example: object-oriented design, database integration, and software engineering practices].

| Course | Where it shows up in the project |
|---|---|
| **[CMSC 203 (OOP)]** | [Example: Flask blueprints per role, a shared `ApiError` exception family, validation helpers] |
| **[ITEC 104 (Data Structures and Algorithms)]** | [Example: the in-memory login rate limiter, leave overlap detection, payroll rate calculations] |
| **[ITEC 105 (Information Management)]** | [Example: a MySQL schema with keys and constraints, parameterized queries, transactions, reports, activity log, backup and restore] |

---

*Last Updated: November 2026*
