# Biri-Go: Biringan Employee Management System

A role-based employee management web app for a logistics company, covering employee records, attendance, leave, payroll, HR processes, and company reports. Built with **Flask**, **MySQL**, and **vanilla JavaScript**, and it can also run as a standalone Windows desktop app.

## Features

| Portal | Role | What it does |
|---|---|---|
| **Admin** (`/admin`) | `admin` | Dashboard, accounts, employees, departments, positions, salaries, leave management, reports, database backups and restore, personal pay and settings |
| **HR** (`/hr`) | `hr` | Employees, departments, attendance, leave requests/balances/calendar, recruitment (jobs and applicant board), onboarding/offboarding, performance reviews, training, announcements, holidays, payroll, reports, settings |
| **Owner** (`/owner`) | `owner` | **View-only** access to everything HR sees, plus salaries and payroll. Every write request to `/api/owner/*` is rejected |
| **Employee** (`/employee`) | `employee` | Dashboard, check-in/check-out, attendance history, leave requests, payslips (with acknowledgement), company news, profile and profile picture |

### Highlights

- **Single source of truth.** Leave and attendance live only in `leave_requests` and `attendance`. Admin, HR, and employee views all read and write the same tables and share the same validation rules (`utils.validate_leave_request`): valid leave type, sex-restricted types, no overlapping requests, and sufficient balance.
- **Philippine-style leave types.** Vacation (PTO), Sick, Emergency, Bereavement, Maternity, Paternity, Parental, Special (Mandated), and Unpaid (LOA). Vacation, Sick, and Emergency entitlements are editable in HR Settings.
- **Payroll.** Monthly records per employee. Daily rate is salary ÷ 26, hourly rate is daily ÷ 8, and overtime is paid at 1.25×. Only recorded absences and approved unpaid leave are deducted, and an absence overlapping unpaid leave is not deducted twice. HR confirms payment, then the employee acknowledges receipt. Payslips are exported as PDFs (ReportLab).
- **Backups.** Create, verify, restore, and delete compressed database backups from the Admin portal or the command line.
- **Profile pictures.** Uploaded images are validated and re-saved as 256×256 files (JPEG, PNG, or WebP, up to 2 MB).
- **Activity log.** Key actions are recorded in an `activity_log` table.

## Tech stack

- **Backend:** Python, Flask 3, `mysql-connector-python`, ReportLab, Pillow
- **Database:** MySQL 8 (InnoDB)
- **Frontend:** HTML, CSS, and vanilla JavaScript (no build step)
- **Desktop build (optional):** `pywebview` + PyInstaller

## Project structure

```
requirements.txt
SECURITY.md
CODE_OF_CONDUCT.md
system/
├── backend/
│   ├── main.py                  app setup, login, accounts, settings, startup
│   ├── config.py                environment-based configuration
│   ├── auth.py                  role_required decorator
│   ├── db.py                    connection pool, schema upgrades, activity log
│   ├── utils.py                 constants, validation, leave rules, settings
│   ├── profile_pictures.py      profile picture upload/serve
│   ├── employee_documents.py    employee document uploads (see Known limitations)
│   ├── backup_restore.py        backup / verify / restore CLI
│   ├── desktop.py               desktop launcher (pywebview)
│   ├── desktop.spec             PyInstaller spec
│   ├── create_app_user.sql.example   least-privilege DB account
│   ├── SECURITY_OPERATIONS.md   production and backup runbook
│   └── routes/
│       ├── admin.py             admin API
│       ├── hr.py                HR API and HR tables
│       ├── owner.py             owner API (read-only)
│       ├── employee.py          employee API and payslip PDFs
│       └── my_pay.py            "my pay" for admin/HR/owner accounts
├── template/                    login, admin, hr, owner, employee_dashboard (.html)
└── statistics/                  static assets, served at /statistics
    ├── css/
    ├── js/
    └── images/
```

## Getting started

### Prerequisites

- Python 3.10+
- MySQL 8
- `mysqldump` and `mysql` on your `PATH` (only needed for backups)

### 1. Install dependencies

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
export DB_PASSWORD=your-mysql-password
```

```powershell
# Windows PowerShell
$env:SECRET_KEY = python -c "import secrets; print(secrets.token_hex(32))"
$env:DB_PASSWORD = "your-mysql-password"
```

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `development` | Set to `production` for hardened mode (see below) |
| `SECRET_KEY` | random (dev only) | Required in production; at least 32 characters |
| `DB_HOST` | `localhost` | |
| `DB_PORT` | `3306` | |
| `DB_USER` | `root` | Must not be `root`/`admin` in production |
| `DB_PASSWORD` | *(empty)* | |
| `DB_NAME` | `biri_go` | |
| `DB_AUTO_INIT` | `1` in dev, `0` in production | Automatic schema creation/upgrades |
| `COOKIE_SECURE` | off | Set to `1` when serving over HTTPS |
| `FLASK_DEBUG` | off | `1` only on your own machine; blocked in production |
| `DB_RESTORE_USER` / `DB_RESTORE_PASSWORD` | none | Admin credentials for backup verify/restore |

### 4. Run

```bash
cd system/backend
python main.py
```

Open <http://127.0.0.1:5000>.

On the first run against an empty `account` table, the console prints a one-time password for the admin account **`biri-000000`**. Sign in and change it immediately under **Settings → Change Password**.

### Employee IDs

New accounts get generated IDs in the format `biri-######` (for example `biri-048213`). Users sign in with their ID and password.

## Desktop app (optional)

The app can be wrapped in a native window with `pywebview` and packaged with PyInstaller:

```bash
pip install pywebview pyinstaller
cd system/backend
python desktop.py                 # run in a desktop window
pyinstaller desktop.spec          # build desktop.exe
```

`desktop.py` serves Flask on port 5000 and opens it in a 1280×800 window.

## Production deployment

Set `APP_ENV=production`. The app then refuses to start unless:

- `SECRET_KEY` is set (32+ characters),
- `DB_USER` is not `root` or `admin`,
- `DB_AUTO_INIT` is disabled, and
- `FLASK_DEBUG` is off.

Cookies are marked `Secure` automatically in production, so serve the app over HTTPS.

Use a restricted database account: copy `system/backend/create_app_user.sql.example`, replace the placeholder password, and run it as a MySQL administrator. The account only gets `SELECT`, `INSERT`, `UPDATE`, and `DELETE` on `biri_go.*`. Full steps are in [`system/backend/SECURITY_OPERATIONS.md`](system/backend/SECURITY_OPERATIONS.md).

## Backups

From `system/backend`:

```bash
python backup_restore.py backup                          # creates backups/*.sql.gz
python backup_restore.py verify backups/YOUR_BACKUP.sql.gz
python backup_restore.py restore backups/YOUR_BACKUP.sql.gz --confirm "RESTORE BIRI-GO DATABASE"
```

You can also manage backups from the **Backups** page in the Admin portal. Restoring is destructive: it drops and recreates the schema, so a safety backup is taken first when possible. Backups contain personal and payroll data. They are git-ignored, so keep them in protected storage.

## Roles and access

| Capability | admin | hr | owner | employee |
|---|:-:|:-:|:-:|:-:|
| Admin portal: accounts, departments, positions, leaves, reports, backups | ✔ | | | |
| HR portal (`/api/hr/*`) | | ✔ | | |
| Owner portal, view-only (`/api/owner/*`) | | | ✔ | |
| Employee dashboard (`/api/employee/*`) | | | | ✔ |

## Security

- Passwords are hashed with Werkzeug.
- Sessions are HttpOnly, SameSite=Lax, last 8 hours, and are `Secure` in production.
- **CSRF protection:** every write request needs a session-bound `X-CSRF-Token`, checked with a constant-time comparison.
- Write requests to `/api/*` must be `application/json`.
- Login is rate limited to 5 failed attempts per 5 minutes per employee ID and IP address (in memory; resets on restart).
- Responses send a strict Content-Security-Policy, `X-Content-Type-Options`, `X-Frame-Options`, and `Referrer-Policy` headers.
- Input is validated server-side (names, Philippine mobile numbers `09XXXXXXXXX`, 18+ age check, salary range, and more).
- Uploaded files are renamed to random IDs and checked by type and size.

To report a vulnerability, see [SECURITY.md](SECURITY.md).

## Known limitations

- **Employee documents are not wired up yet.** The employee dashboard has a Documents page and `employee_documents.py` exists, but its blueprint is not registered in `main.py`, so the `/api/employee/documents` calls fail.
- **Base schema file.** `Biri-Go.sql` is required for a fresh install but is currently excluded by the `*.sql` rule in `.gitignore`.
- **Login rate limiting** is in memory only and resets on restart.
- **Password reset** and an **automated test suite** are not implemented.

## Contributing

Please read the [Code of Conduct](CODE_OF_CONDUCT.md) before contributing. Pull requests are welcome.
