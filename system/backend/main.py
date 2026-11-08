import re
import hmac
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import mysql.connector
from flask import Flask, jsonify, render_template
from flask import session, redirect
from flask import request
import secrets
import os
import sys
import time

import config
from auth import role_required
from db import init_db, db, log_activity
from utils import ApiError, AppJSONProvider, EMAIL_RE, EMPLOYEE_STATUSES
from routes.employee import employee_bp
from routes.admin import admin_bp
from routes.hr import hr_bp, init_hr_tables
from routes.owner import owner_bp
from werkzeug.security import check_password_hash, generate_password_hash


if getattr(sys, "_MEIPASS", None):  # running as a packaged .exe
    TEMPLATE_DIR = os.path.join(sys._MEIPASS, "template")
    STATIC_DIR = os.path.join(sys._MEIPASS, "statistics")
else:
    _here = os.path.dirname(os.path.abspath(__file__))
    TEMPLATE_DIR = os.path.join(_here, "..", "template")
    STATIC_DIR = os.path.join(_here, "..", "statistics")

app = Flask(__name__, template_folder=TEMPLATE_DIR,
            static_folder=STATIC_DIR, static_url_path="/statistics")

app.json = AppJSONProvider(app)
app.secret_key = config.SECRET_KEY
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=(
        config.APP_ENV == "production"
        or os.environ.get("COOKIE_SECURE") == "1"
    ),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    SESSION_REFRESH_EACH_REQUEST=False,
)

@app.context_processor
def inject_csrf_token():
    """Make a session-bound CSRF token available to every rendered page."""
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return {"csrf_token": session["csrf_token"]}

app.register_blueprint(employee_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(hr_bp)
app.register_blueprint(owner_bp)

ROLE_HOME = {"admin": "/admin", "hr": "/hr", "owner": "/owner", "employee": "/employee"}  # match your blueprint URLs


@app.after_request
def no_cache(resp):
    if request.path in ROLE_HOME.values():
        resp.headers["Cache-Control"] = "no-store"

    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Content-Security-Policy"] = (
        "object-src 'none'; base-uri 'self'; frame-ancestors 'self'"
    )
    return resp


@app.before_request
def require_json_for_writes():
    if (
        request.method in ("POST", "PUT", "PATCH", "DELETE")
        and request.path.startswith("/api/")
        and not request.is_json
    ):
        return jsonify(error="Content-Type must be application/json."), 415

@app.before_request
def csrf_protect():
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return

    token = (
        request.headers.get("X-CSRF-Token")
        or request.form.get("csrf_token")
    )

    session_token = session.get("csrf_token")

    if not token or not session_token:
        return jsonify(error="CSRF token missing."), 403

    if not hmac.compare_digest(token, session_token):
        return jsonify(error="Invalid CSRF token."), 403

@app.errorhandler(ApiError)
def handle_api_error(e):
    return jsonify(error=e.message), e.status


@app.errorhandler(mysql.connector.Error)
def handle_db_error(e):
    errno = getattr(e, "errno", None)
    if errno == 1062:
        return jsonify(error="That value already exists (duplicate entry)."), 409
    if errno == 1451:
        return jsonify(
            error="This record is still used by other records, so it can't be deleted."
        ), 409
    if errno == 1452:
        return jsonify(error="A referenced record doesn't exist."), 400
    if errno in (1045, 1049, 2002, 2003, 2013):
        app.logger.error("Database connection problem: %s", e)
        return jsonify(
            error="Can't connect to the database. Check DB_HOST / DB_USER / "
                  "DB_PASSWORD / DB_NAME in config.py and that MySQL is running."
        ), 503
    if errno == 1146:
        app.logger.error("Missing table: %s", e)
        return jsonify(error="Database table missing: " + str(getattr(e, "msg", e))), 500
    if errno == 1054:
        app.logger.error("Missing column: %s", e)
        return jsonify(error="Database column missing: " + str(getattr(e, "msg", e))), 500
    app.logger.exception("Database error")
    return jsonify(error="Database error."), 500


@app.route("/")
def index():
    # Already signed in? Skip the login page and go to that role's home.
    role = session.get("role")
    if session.get("account_id") and role in ROLE_HOME:
        return redirect(ROLE_HOME[role])
    return render_template("login.html")


@app.route("/admin")
@role_required("admin")
def admin_page():
    return render_template("admin.html")


@app.route("/hr")
@role_required("hr")
def hr_page():
    return render_template("hr.html")


_FAILED_LOGINS = {}
MAX_FAILED_LOGINS, LOGIN_WINDOW_SECONDS = 5, 300


def _too_many_attempts(key):
    now = time.time()
    recent = [t for t in _FAILED_LOGINS.get(key, []) if now - t < LOGIN_WINDOW_SECONDS]
    _FAILED_LOGINS[key] = recent
    return len(recent) >= MAX_FAILED_LOGINS


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    code = (data.get("employee_code") or "").strip().lower()
    password = data.get("password") or ""

    throttle_key = f"{request.remote_addr}|{code}"
    if _too_many_attempts(throttle_key):
        return jsonify(success=False, message="Too many failed attempts. Try again in a few minutes."), 429

    with db() as (conn, cur):
        cur.execute(
            "SELECT account_id, account_password, account_role AS role "
            "FROM account WHERE employee_code = %s",
            (code,),
        )
        row = cur.fetchone()

    if not row or not check_password_hash(row["account_password"], password):
        _FAILED_LOGINS.setdefault(throttle_key, []).append(time.time())
        return jsonify(success=False, message="Invalid employee ID or password."), 401

    _FAILED_LOGINS.pop(throttle_key, None)
    session.clear()
    session["csrf_token"] = secrets.token_urlsafe(32)
    session.permanent = True
    session["account_id"] = row["account_id"]
    session["role"] = row["role"]
    return jsonify(success=True, redirect=ROLE_HOME.get(row["role"], "/"))

ACCOUNT_ROLES = ("admin", "hr", "owner", "employee")
SEX_VALUES = ("Male", "Female")


def _json_object():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Request body must be a JSON object.")
    return data


def _text(data, key):
    value = data.get(key)
    return value.strip() if isinstance(value, str) else ""


def parse_employee_form(data, require_job=True):
    """Validate the personal/job fields shared by Add Account and Edit Employee."""
    first, middle, last = _text(data, "first_name"), _text(data, "middle_name"), _text(data, "last_name")
    suffix, sex, phone = _text(data, "suffix"), _text(data, "sex"), _text(data, "phone")
    email = _text(data, "email").lower()

    if not first or len(first) > 50:
        raise ApiError("First name is required (max 50 characters).")
    if len(middle) > 50:
        raise ApiError("Middle name is too long (max 50 characters).")
    if not last or len(last) > 50:
        raise ApiError("Last name is required (max 50 characters).")
    if not suffix:
        raise ApiError("Suffix is required. Enter 'None' if you don't have one.")
    if len(suffix) > 20:
        raise ApiError("Suffix is too long (max 20 characters).")
    if suffix.lower() == "none":
        suffix = None
    if sex not in SEX_VALUES:
        raise ApiError("Please select a sex.")

    try:
        birthday = datetime.strptime(_text(data, "birthday"), "%Y-%m-%d").date()
    except ValueError:
        raise ApiError("Birthday must be a valid date.")
    if birthday > date.today() or birthday.year < 1900:
        raise ApiError("Birthday is out of range.")

    if not email or not EMAIL_RE.match(email) or len(email) > 100:
        raise ApiError("A valid email is required.")
    if len(phone) > 20:
        raise ApiError("Phone number is too long (max 20 characters).")

    department_id = position_id = None
    if require_job:
        try:
            department_id = int(data.get("department_id"))
            position_id = int(data.get("position_id"))
        except (TypeError, ValueError):
            raise ApiError("Please select a department and a position.")

    raw_salary = data.get("salary")
    raw_salary = str(raw_salary).strip() if raw_salary is not None else ""
    salary = None
    if raw_salary:
        try:
            salary = Decimal(raw_salary)
        except InvalidOperation:
            raise ApiError("Salary must be a number.")
        if salary < 0 or salary >= Decimal("100000000"):
            raise ApiError("Salary is out of range.")
        salary = salary.quantize(Decimal("0.01"))

    return {
        "first_name": first, "middle_name": middle or None, "last_name": last,
        "suffix": suffix, "sex": sex, "birthday": birthday, "email": email,
        "phone": phone or None, "salary": salary,
        "department_id": department_id, "position_id": position_id,
    }


def check_position(cur, department_id, position_id):
    cur.execute("SELECT department_id FROM positions WHERE position_id = %s", (position_id,))
    pos = cur.fetchone()
    if not pos:
        raise ApiError("Selected position doesn't exist.")
    if pos["department_id"] != department_id:
        raise ApiError("The selected position doesn't belong to that department.")

def generate_employee_code(cur):
    """Return a unique ID like biri-048213."""
    for _ in range(20):
        code = "biri-%06d" % secrets.randbelow(1_000_000)
        cur.execute("SELECT 1 AS ok FROM account WHERE employee_code = %s", (code,))
        if not cur.fetchone():
            return code
    raise ApiError("Could not generate a unique employee ID. Please try again.", 500)


@app.route("/api/accounts/options")
@role_required("admin")
def account_options():
    """Departments and positions used by the Add Account / Edit Employee forms."""
    with db() as (conn, cur):
        cur.execute(
            "SELECT department_id AS id, dept_name AS name "
            "FROM departments ORDER BY department_id"
        )
        departments = cur.fetchall()
        cur.execute(
            "SELECT position_id AS id, title, department_id "
            "FROM positions ORDER BY department_id, position_id"
        )
        positions = cur.fetchall()
    return jsonify(departments=departments, positions=positions)


@app.route("/api/accounts", methods=["POST"])
@role_required("admin")
def create_account():
    """Create an employee record and its login account in one transaction."""
    data = _json_object()
    role = _text(data, "role").lower()
    emp = parse_employee_form(data, require_job=(role != "admin"))
    password = data.get("password") or ""

    if role not in ACCOUNT_ROLES:
        raise ApiError("Role must be one of: " + ", ".join(ACCOUNT_ROLES) + ".")
    if len(password) < 8:
        raise ApiError("Password must be at least 8 characters.")

    with db() as (conn, cur):
        cur.execute("SELECT 1 AS ok FROM account WHERE account_email = %s", (emp["email"],))
        if cur.fetchone():
            raise ApiError("An account with that email already exists.", 409)
        cur.execute("SELECT 1 AS ok FROM employees WHERE email = %s", (emp["email"],))
        if cur.fetchone():
            raise ApiError("An employee with that email already exists.", 409)
        if emp["department_id"] is not None:
            check_position(cur, emp["department_id"], emp["position_id"])

        cur.execute(
            "INSERT INTO employees "
            "(first_name, middle_name, last_name, suffix, sex, birthday, "
            " email, phone, stat, salary, department_id, position_id, hired) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Active', %s, %s, %s, CURDATE())",
            (emp["first_name"], emp["middle_name"], emp["last_name"], emp["suffix"],
             emp["sex"], emp["birthday"], emp["email"], emp["phone"], emp["salary"],
             emp["department_id"], emp["position_id"]),
        )
        employee_id = cur.lastrowid

        hashed = generate_password_hash(password)
        employee_code = generate_employee_code(cur)
        cur.execute(
            "INSERT INTO account (employee_code, employee_id, account_email, account_password, account_role) "
            "VALUES (%s, %s, %s, %s, %s)",
            (employee_code, employee_id, emp["email"], hashed, role),
        )
        account_id = cur.lastrowid

        log_activity(cur, "Added employee %s %s with %s account"
                     % (emp["first_name"], emp["last_name"], role))

    return jsonify(id=account_id, employee_id=employee_id, employee_code=employee_code, email=emp["email"], role=role), 201


@app.route("/api/accounts/employees/<int:employee_id>", methods=["GET"])
@role_required("admin")
def get_employee_for_edit(employee_id):
    """Full employee record (including the extra personal fields) for the Edit form."""
    with db() as (conn, cur):
        cur.execute(
            "SELECT employee_id AS id, first_name, middle_name, last_name, suffix, sex, "
            "       birthday, email, phone, stat AS status, salary, department_id, position_id "
            "FROM employees WHERE employee_id = %s",
            (employee_id,),
        )
        row = cur.fetchone()
    if not row:
        raise ApiError("Employee not found.", 404)
    row["birthday"] = str(row["birthday"])[:10] if row.get("birthday") else ""
    row["salary"] = float(row["salary"]) if row.get("salary") is not None else ""
    return jsonify(row)


@app.route("/api/accounts/employees/<int:employee_id>", methods=["PUT"])
@role_required("admin")
def update_employee_profile(employee_id):
    """Save the Edit Employee form. A changed email is also applied to the login account."""
    data = _json_object()
    status = _text(data, "status") or "Active"
    if status not in EMPLOYEE_STATUSES:
        raise ApiError("Status must be one of: " + ", ".join(EMPLOYEE_STATUSES) + ".")

    with db() as (conn, cur):
        cur.execute("SELECT email FROM employees WHERE employee_id = %s", (employee_id,))
        current = cur.fetchone()
        if not current:
            raise ApiError("Employee not found.", 404)
        old_email = current["email"]

        # Admin accounts are created without a department/position (see create_account),
        # so they must be editable without one too.
        cur.execute("SELECT account_role FROM account WHERE employee_id = %s", (employee_id,))
        acct = cur.fetchone()
        emp = parse_employee_form(data, require_job=not (acct and acct["account_role"] == "admin"))

        cur.execute(
            "SELECT 1 AS ok FROM employees WHERE email = %s AND employee_id <> %s",
            (emp["email"], employee_id),
        )
        if cur.fetchone():
            raise ApiError("Another employee already uses that email.", 409)

        cur.execute(
            "SELECT 1 AS ok FROM account WHERE account_email = %s "
            "AND (employee_id IS NULL OR employee_id <> %s)",
            (emp["email"], employee_id),
        )
        if cur.fetchone():
            raise ApiError("Another account already uses that email.", 409)

        if emp["department_id"] is not None:
            check_position(cur, emp["department_id"], emp["position_id"])

        cur.execute(
            "UPDATE employees SET first_name=%s, middle_name=%s, last_name=%s, suffix=%s, "
            "sex=%s, birthday=%s, email=%s, phone=%s, stat=%s, salary=%s, "
            "department_id=%s, position_id=%s WHERE employee_id=%s",
            (emp["first_name"], emp["middle_name"], emp["last_name"], emp["suffix"],
             emp["sex"], emp["birthday"], emp["email"], emp["phone"], status, emp["salary"],
             emp["department_id"], emp["position_id"], employee_id),
        )

        if emp["email"] != old_email:
            cur.execute(
                "UPDATE account SET account_email = %s WHERE employee_id = %s",
                (emp["email"], employee_id),
            )

        log_activity(cur, "Updated employee %s %s" % (emp["first_name"], emp["last_name"]))

    return jsonify(id=employee_id, message="Employee updated.")


# ---------------------------------------------------------------- Reports page
@app.route("/api/admin/reports")
@role_required("admin")
def api_reports():
    """Numbers for the Reports page."""
    with db() as (conn, cur):
        cur.execute(
            "SELECT d.dept_name AS department, COUNT(e.employee_id) AS employees, "
            "       COALESCE(SUM(CASE WHEN e.stat = 'Active' THEN e.salary END), 0) AS payroll "
            "FROM departments d "
            "LEFT JOIN employees e ON e.department_id = d.department_id "
            "GROUP BY d.department_id, d.dept_name ORDER BY d.dept_name"
        )
        by_department = cur.fetchall()

        cur.execute(
            "SELECT stat AS status, COUNT(*) AS total "
            "FROM employees GROUP BY stat ORDER BY total DESC"
        )
        by_status = cur.fetchall()

        cur.execute(
            "SELECT account_role AS role, COUNT(*) AS total "
            "FROM account GROUP BY account_role ORDER BY total DESC"
        )
        by_role = cur.fetchall()

        cur.execute(
            "SELECT COUNT(*) AS total_employees, "
            "       COALESCE(SUM(stat = 'Active'), 0) AS active_employees, "
            "       COALESCE(SUM(CASE WHEN stat = 'Active' THEN salary END), 0) AS total_payroll "
            "FROM employees"
        )
        summary = cur.fetchone()

    return jsonify(
        summary={
            "total_employees": int(summary["total_employees"]), 
            "active_employees": int(summary["active_employees"]),
            "total_payroll": float(summary["total_payroll"]),
        },
        by_department=[
            {"department": r["department"], "employees": int(r["employees"]),
             "payroll": float(r["payroll"])}
            for r in by_department
        ],
        by_status=[{"status": r["status"], "total": int(r["total"])} for r in by_status],
        by_role=[{"role": r["role"], "total": int(r["total"])} for r in by_role],
    )


# ---------------------------------------------------------------- Settings page
@app.route("/api/settings/profile")
@role_required("admin")
def settings_profile():
    """The logged-in admin's own account details."""
    with db() as (conn, cur):
        cur.execute(
            "SELECT a.employee_code, a.account_email AS email, a.account_role AS role, "
            "       e.first_name, e.last_name "
            "FROM account a LEFT JOIN employees e ON e.employee_id = a.employee_id "
            "WHERE a.account_id = %s",
            (session.get("account_id"),),
        )
        row = cur.fetchone()
    if not row:
        raise ApiError("Account not found.", 404)

    name = " ".join(p for p in (row.get("first_name"), row.get("last_name")) if p)
    return jsonify(
        name=name, employee_code=row["employee_code"],
        email=row["email"], role=row["role"],
    )


@app.route("/api/settings/password", methods=["PUT"])
@role_required("admin")
def settings_password():
    """Let the logged-in admin change their own password."""
    data = _json_object()
    current = data.get("current_password") or ""
    new = data.get("new_password") or ""

    if len(new) < 8:
        raise ApiError("New password must be at least 8 characters.")

    with db() as (conn, cur):
        cur.execute(
            "SELECT account_password FROM account WHERE account_id = %s",
            (session.get("account_id"),),
        )
        row = cur.fetchone()
        if not row or not check_password_hash(row["account_password"], current):
            raise ApiError("Current password is incorrect.", 400)
        if check_password_hash(row["account_password"], new):
            raise ApiError("New password must be different from the current one.")

        cur.execute(
            "UPDATE account SET account_password = %s WHERE account_id = %s",
            (generate_password_hash(new), session.get("account_id")),
        )
        log_activity(cur, "Admin changed their password")

    return jsonify(message="Password updated.")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect("/")



def _ensure_first_admin():
    """Fresh database: create admin biri-000000 with a one-time password printed to the console."""
    with db() as (conn, cur):
        cur.execute("SELECT COUNT(*) AS n FROM account")
        if cur.fetchone()["n"]:
            return
        password = secrets.token_urlsafe(10)
        cur.execute(
            "INSERT INTO account (employee_code, account_email, account_password, account_role) "
            "VALUES ('biri-000000', 'admin@biringan.com', %s, 'admin')",
            (generate_password_hash(password),),
        )
    print("=" * 60)
    print(" First run: admin account created")
    print("   Employee ID: biri-000000")
    print("   Password:    " + password)
    print(" Sign in and change it right away (Settings > Change Password).")
    print("=" * 60)


def _init_db_safely():
    try:
        init_db()
        init_hr_tables()
        _ensure_first_admin()
    except mysql.connector.Error as err:
        print(f"[warning] Could not prepare the database yet: {err}")


# Runs under `python main.py`, `flask run` and WSGI servers alike.
_init_db_safely()

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")