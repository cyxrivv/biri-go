# Biri-Go - Biringan Employee Management System

Role-based employee management app (Flask + MySQL + vanilla JS) for a logistics company.
Roles: `admin`, `hr`, `owner`, `employee`.

**Status:** admin, HR and employee portals work. The **owner portal page (`/owner`) is not built yet**;
the owner API (`/api/salaries`, `/api/reports`) is ready for it.

## Layout
```
Biri-Go.sql                 fresh-install schema
backend/                    main.py, auth.py, config.py, db.py, utils.py
backend/routes/             admin.py, hr.py, owner.py, employee.py
template/                   login, admin, hr, employee_dashboard (.html)
statistics/css|js/          static files, served at /statistics
```

## Run
```bash
pip install -r requirements.txt
mysql -u root -p < Biri-Go.sql

# set these in your shell (never commit them)
export SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
export DB_PASSWORD=your-mysql-password      # optional: DB_HOST, DB_USER, DB_NAME
cd backend && python main.py
```
On the first run with an empty database the console prints the password for admin `biri-000000`.
Change it in Settings straight away. Set `COOKIE_SECURE=1` when serving over HTTPS and
`FLASK_DEBUG=1` only on your own machine.

Existing databases are upgraded automatically on start (leave names, `reason`, attendance `status`).

## One source of truth
Leave and attendance live only in `leave_requests` and `attendance`. Admin, HR and the employee
dashboard all read and write them, and share the same rules (`utils.validate_leave_request`):
valid type, sex-restricted types, no overlaps, balance. Vacation/Sick/Emergency entitlements come from HR Settings.

## Roles
| Capability | admin | hr | owner | employee |
|---|:-:|:-:|:-:|:-:|
| Admin portal (accounts, departments, positions, leaves, reports) | yes | | | |
| HR portal (`/api/hr/*`) | | yes | | |
| Salaries and company reports (`/api/salaries`, `/api/reports`) | yes | | yes | |
| Employee dashboard (`/api/employee/*`) | | | | yes |

## Security notes
Passwords are hashed (Werkzeug). Sessions are HttpOnly + SameSite=Lax, and write requests must be
`application/json` (blocks cross-site form posts). Login is limited to 5 failures per 5 minutes per ID and IP
(in memory, resets on restart). Still to do: CSRF tokens, password reset, tests.
