"""routes/hr.py  -  REST API behind template/hr.html + statistics/js/hr.js

    GET    /api/hr/me
    GET    /api/hr/<resource>            list
    POST   /api/hr/<resource>            create
    PUT    /api/hr/<resource>/<id>       update (only the fields sent)
    DELETE /api/hr/<resource>/<id>       delete
    GET/PUT /api/hr/settings

Resources: employees, departments, jobs, applicants, processes, attendance,
           leaves, reviews, trainings, announcements, holidays
"""
import json
import re
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import Blueprint, jsonify, request, session
from werkzeug.security import generate_password_hash

from auth import role_required
from db import add_column, db, fetch_one, log_activity
from utils import (ApiError, LEAVE_TYPES, SETTING_DEFAULTS, get_settings as read_settings,
                   purge_employee, validate_leave_request)

hr_bp = Blueprint("hr", __name__, url_prefix="/api/hr")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EMP_STATUSES = ("Active", "On Leave", "Resigned", "Terminated")
EMP_TYPES = ("Full-time", "Part-time", "Contract", "Intern")

# --------------------------------------------------------------------------
# Tables (created automatically by init_hr_tables(), called from main.py)
# --------------------------------------------------------------------------
_DDL = [
    """CREATE TABLE IF NOT EXISTS hr_jobs (
        id INT AUTO_INCREMENT PRIMARY KEY, title VARCHAR(255) NOT NULL,
        department_id INT NOT NULL, job_type VARCHAR(30), openings INT DEFAULT 1,
        posted DATE, status VARCHAR(20) DEFAULT 'Open') DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS hr_applicants (
        id INT AUTO_INCREMENT PRIMARY KEY, job_id INT NOT NULL, name VARCHAR(255) NOT NULL,
        email VARCHAR(255), phone VARCHAR(50), stage VARCHAR(20) DEFAULT 'Applied') DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS hr_processes (
        id INT AUTO_INCREMENT PRIMARY KEY, employee_id INT NOT NULL, kind VARCHAR(20),
        status VARCHAR(20), tasks TEXT) DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS hr_reviews (
        id INT AUTO_INCREMENT PRIMARY KEY, employee_id INT NOT NULL, period VARCHAR(50),
        reviewer VARCHAR(255), rating DECIMAL(3,1) DEFAULT 0, status VARCHAR(20) DEFAULT 'Draft') DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS hr_trainings (
        id INT AUTO_INCREMENT PRIMARY KEY, title VARCHAR(255) NOT NULL, trainer VARCHAR(255),
        training_date DATE, hours DECIMAL(5,1) DEFAULT 0, venue VARCHAR(255),
        enrolled INT DEFAULT 0, status VARCHAR(20) DEFAULT 'Scheduled') DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS hr_announcements (
        id INT AUTO_INCREMENT PRIMARY KEY, title VARCHAR(255) NOT NULL, body TEXT,
        posted_on DATE) DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS hr_holidays (
        id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(100) NOT NULL,
        holiday_date DATE NOT NULL) DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS hr_settings (
        skey VARCHAR(50) PRIMARY KEY, svalue VARCHAR(100)) DEFAULT CHARSET=utf8mb4""",
]


def init_hr_tables():
    """Create the HR tables and add the few extra columns the HR page needs."""
    with db() as (conn, cur):
        for ddl in _DDL:
            cur.execute(ddl)
        if add_column(cur, "employees", "hired", "DATE NULL"):
            cur.execute("UPDATE employees SET hired = CURDATE() WHERE hired IS NULL")
        add_column(cur, "employees", "emp_type", "VARCHAR(20) NOT NULL DEFAULT 'Full-time'")


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def _body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Request body must be a JSON object.")
    return data


def _s(data, key, limit=255):
    v = data.get(key)
    v = v.strip() if isinstance(v, str) else ("" if v is None else str(v).strip())
    if len(v) > limit:
        raise ApiError("%s is too long (max %d characters)." % (key.replace("_", " ").capitalize(), limit))
    return v


def _date(v, label):
    if v in (None, ""):
        return None
    try:
        return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
    except ValueError:
        raise ApiError("%s must be a valid date." % label)


def _out(v):
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, timedelta):
        s = int(v.total_seconds())
        return "%02d:%02d" % ((s // 3600) % 24, (s % 3600) // 60)
    if isinstance(v, Decimal):
        return float(v)
    return v


def _clean(row):
    return {k: _out(v) for k, v in row.items()}


# --------------------------------------------------------------------------
# Generic resources  (api name, db column, kind)
#   s=short text  x=long text  i=int  f=float  d=date  t=time  j=json list
#   n=nullable int  r=read-only (computed in SQL, never written)
# --------------------------------------------------------------------------
RESOURCES = {
    "departments": dict(table="departments", pk="department_id", order="department_id",
                        cols=[("name", "dept_name", "s"), ("head_employee_id", "head_employee_id", "n"),
                              ("head", "(SELECT CONCAT(h.first_name, ' ', h.last_name) FROM employees h "
                                       "WHERE h.employee_id = departments.head_employee_id)", "r")],
                        required=["name"]),
    "jobs": dict(table="hr_jobs", pk="id", order="id DESC",
                 cols=[("title", "title", "s"), ("department_id", "department_id", "i"), ("type", "job_type", "s"),
                       ("openings", "openings", "i"), ("posted", "posted", "d"), ("status", "status", "s")],
                 required=["title", "department_id"]),
    "applicants": dict(table="hr_applicants", pk="id", order="id",
                       cols=[("job_id", "job_id", "i"), ("name", "name", "s"), ("email", "email", "s"),
                             ("phone", "phone", "s"), ("stage", "stage", "s")], required=["name", "job_id"]),
    "processes": dict(table="hr_processes", pk="id", order="id DESC",
                      cols=[("employee_id", "employee_id", "i"), ("kind", "kind", "s"), ("status", "status", "s"),
                            ("tasks", "tasks", "j")], required=["employee_id", "kind"]),
    "attendance": dict(table="attendance", pk="attendance_id", order="work_date DESC, attendance_id DESC",
                       cols=[("employee_id", "employee_id", "i"), ("date", "work_date", "d"), ("time_in", "time_in", "t"),
                             ("time_out", "time_out", "t"), ("overtime_hours", "overtime_hours", "f"), ("status", "status", "s"), ("remarks", "remarks", "s")],
                       required=["employee_id", "date"]),
    "leaves": dict(table="leave_requests", pk="leave_id", order="start_date DESC, leave_id DESC",
                   cols=[("employee_id", "employee_id", "i"), ("type", "leave_type", "s"), ("from", "start_date", "d"),
                         ("to", "end_date", "d"), ("days", "DATEDIFF(end_date, start_date) + 1", "r"),
                         ("reason", "reason", "x"), ("status", "leave_status", "s"), ("pay_status", "pay_status", "s")],
                   required=["employee_id", "type", "from", "to"]),
    "reviews": dict(table="hr_reviews", pk="id", order="id DESC",
                    cols=[("employee_id", "employee_id", "i"), ("period", "period", "s"), ("reviewer", "reviewer", "s"),
                          ("rating", "rating", "f"), ("status", "status", "s")], required=["employee_id", "period"]),
    "trainings": dict(table="hr_trainings", pk="id", order="training_date DESC, id DESC",
                      cols=[("title", "title", "s"), ("trainer", "trainer", "s"), ("date", "training_date", "d"),
                            ("hours", "hours", "f"), ("venue", "venue", "s"), ("enrolled", "enrolled", "i"),
                            ("status", "status", "s")], required=["title"]),
    "announcements": dict(table="hr_announcements", pk="id", order="posted_on DESC, id DESC",
                          cols=[("title", "title", "s"), ("body", "body", "x"), ("date", "posted_on", "d")],
                          required=["title"]),
    "holidays": dict(table="hr_holidays", pk="id", order="holiday_date",
                     cols=[("name", "name", "s"), ("date", "holiday_date", "d")], required=["name", "date"]),
}
_CHOICES = {
    ("leaves", "status"): ("Pending", "Approved", "Rejected"),
    ("leaves", "pay_status"): ("Paid", "Unpaid"),
    ("leaves", "type"): tuple(LEAVE_TYPES),
    ("applicants", "stage"): ("Applied", "Screening", "Interview", "Offer", "Hired", "Rejected"),
    ("jobs", "status"): ("Open", "Closed"),
    ("reviews", "status"): ("Draft", "Completed"),
    ("trainings", "status"): ("Scheduled", "Completed", "Cancelled"),
    ("attendance", "status"): ("Present", "Late", "Absent", "On Leave"),
    ("processes", "kind"): ("Onboarding", "Offboarding"),
}


def _convert(res, api_name, kind, value):
    label = api_name.replace("_", " ").capitalize()
    if kind in ("s", "x"):
        v = "" if value is None else str(value).strip()
        if len(v) > (5000 if kind == "x" else 255):
            raise ApiError("%s is too long." % label)
        allowed = _CHOICES.get((res, api_name))
        if allowed and v not in allowed:
            raise ApiError("%s must be one of: %s." % (label, ", ".join(allowed)))
        return v
    if kind == "i":
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ApiError("%s must be a whole number." % label)
    if kind == "n":
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ApiError("%s must be a whole number." % label)
    if kind == "f":
        try:
            number = float(value)
            if number < 0:
                raise ValueError
            return number
        except (TypeError, ValueError):
            raise ApiError("%s must be a valid non-negative number." % label)
    if kind == "d":
        return _date(value, label)
    if kind == "t":
        if value in (None, ""):
            return None
        try:
            return datetime.strptime(str(value)[:5], "%H:%M").strftime("%H:%M:00")
        except ValueError:
            raise ApiError("%s must be a valid time." % label)
    if kind == "j":
        if not isinstance(value, list):
            raise ApiError("%s must be a list." % label)
        return json.dumps(value)
    raise ApiError("Unsupported field type.")


def _cfg(res):
    cfg = RESOURCES.get(res)
    if not cfg:
        raise ApiError("Unknown resource.", 404)
    return cfg


def _check_rules(res, vals, existing=None):
    """Cross-field rules."""
    ex = existing or {}
    if res == "leaves":
        status = vals.get("leave_status", ex.get("leave_status", "Pending"))
        validate_leave_request(
            vals.get("employee_id", ex.get("employee_id")),
            vals.get("leave_type", ex.get("leave_type")),
            vals.get("start_date", ex.get("start_date")),
            vals.get("end_date", ex.get("end_date")),
            exclude_id=ex.get("leave_id"), status=status)
    elif res == "departments" and vals.get("head_employee_id") is not None:
        if not fetch_one("SELECT 1 AS ok FROM employees WHERE employee_id = %s", (vals["head_employee_id"],)):
            raise ApiError("Selected department head doesn't exist.")


@hr_bp.route("/me")
@role_required("hr")
def me():
    with db() as (conn, cur):
        cur.execute(
            "SELECT e.first_name, e.last_name FROM account a "
            "LEFT JOIN employees e ON e.employee_id = a.employee_id WHERE a.account_id = %s",
            (session.get("account_id"),),
        )
        row = cur.fetchone() or {}
    name = ("%s %s" % (row.get("first_name") or "", row.get("last_name") or "")).strip()
    return jsonify(name=name or "HR")


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

@hr_bp.route("/settings", methods=["GET"])
@role_required("hr")
def get_settings():
    return jsonify(read_settings())


@hr_bp.route("/settings", methods=["PUT"])
@role_required("hr")
def put_settings():
    data = _body()
    rows = []
    for key, default in SETTING_DEFAULTS.items():
        if key not in data:
            continue
        if isinstance(default, str):
            v = str(data[key]).strip()
            if not re.match(r"^\d{2}:\d{2}$", v):
                raise ApiError("%s must be a time (HH:MM)." % key.replace("_", " ").capitalize())
        else:
            try:
                v = int(data[key])
            except (TypeError, ValueError):
                raise ApiError("%s must be a whole number." % key.replace("_", " ").capitalize())
            if v < 0 or v > 365:
                raise ApiError("%s is out of range." % key.replace("_", " ").capitalize())
        rows.append((key, str(v)))
    with db() as (conn, cur):
        for k, v in rows:
            cur.execute("INSERT INTO hr_settings (skey, svalue) VALUES (%s, %s) "
                        "ON DUPLICATE KEY UPDATE svalue = VALUES(svalue)", (k, v))
        log_activity(cur, "HR updated settings")
    return get_settings()


# --------------------------------------------------------------------------
# Employees  (maps the HR page's shape onto employees / positions / account)
# --------------------------------------------------------------------------
_EMP_SELECT = (
    "SELECT e.employee_id AS id, a.employee_code AS code, e.first_name, e.last_name, e.sex, "
    "       e.email, e.phone, e.birthday, e.department_id, p.title AS position, "
    "       e.emp_type AS type, COALESCE(e.hired, CURDATE()) AS hired, e.stat AS status, "
    "       e.salary "
    "FROM employees e "
    "LEFT JOIN positions p ON p.position_id = e.position_id "
    "LEFT JOIN account a ON a.employee_id = e.employee_id "
)


def _position_id(cur, dept_id, title):
    cur.execute("SELECT position_id FROM positions WHERE department_id = %s AND title = %s", (dept_id, title))
    row = cur.fetchone()
    if row:
        return row["position_id"]
    cur.execute("INSERT INTO positions (title, department_id) VALUES (%s, %s)", (title, dept_id))
    return cur.lastrowid


def _parse_employee(data):
    first, last = _s(data, "first_name", 50), _s(data, "last_name", 50)
    email, phone = _s(data, "email", 100).lower(), _s(data, "phone", 20)
    sex, position = _s(data, "sex", 10), _s(data, "position", 100)
    emp_type, status = _s(data, "type", 20) or "Full-time", _s(data, "status", 20) or "Active"
    try:
        salary = float(data.get("salary") or 0)

    except (TypeError, ValueError):
        raise ApiError("Please enter a valid salary.")
    if salary < 0:
       raise ApiError("Salary cannot be negative.")

    if not first:
        raise ApiError("First name is required.")
    if not last:
        raise ApiError("Last name is required.")
    if not email or not EMAIL_RE.match(email):
        raise ApiError("A valid email is required.")
    if sex not in ("Male", "Female"):
        raise ApiError("Please select a sex.")
    birthday = _date(data.get("birthday"), "Birthday")
    if not birthday or birthday > date.today() or birthday.year < 1900:
        raise ApiError("A valid birthday is required.")
    hired = _date(data.get("hired"), "Date hired")
    if not hired:
        raise ApiError("Date hired is required.")
    try:
        dept_id = int(data.get("department_id"))
    except (TypeError, ValueError):
        raise ApiError("Please select a department.")
    if not position:
        raise ApiError("Position is required.")
    if emp_type not in EMP_TYPES:
        raise ApiError("Type must be one of: " + ", ".join(EMP_TYPES) + ".")
    if status not in EMP_STATUSES:
        raise ApiError("Status must be one of: " + ", ".join(EMP_STATUSES) + ".")
    return dict(first=first, last=last, email=email, phone=phone or None, sex=sex, birthday=birthday,
                hired=hired, dept_id=dept_id, position=position, type=emp_type, status=status, salary=salary)


def _need_department(cur, dept_id):
    cur.execute("SELECT 1 AS ok FROM departments WHERE department_id = %s", (dept_id,))
    if not cur.fetchone():
        raise ApiError("Selected department doesn't exist.")


@hr_bp.route("/employees", methods=["GET"])
@role_required("hr")
def list_employees():
    with db() as (conn, cur):
        cur.execute(_EMP_SELECT + "ORDER BY e.employee_id")
        rows = [_clean(r) for r in cur.fetchall()]
    return jsonify(rows)


@hr_bp.route("/employees", methods=["POST"])
@role_required("hr")
def create_employee():
    e = _parse_employee(_body())
    e["salary"] = float(e.get("salary") or 0)
    with db() as (conn, cur):
        cur.execute("SELECT 1 AS ok FROM employees WHERE email = %s", (e["email"],))
        if cur.fetchone():
            raise ApiError("An employee with that email already exists.", 409)
        cur.execute("SELECT 1 AS ok FROM account WHERE account_email = %s", (e["email"],))
        if cur.fetchone():
            raise ApiError("An account with that email already exists.", 409)
        _need_department(cur, e["dept_id"])
        pos_id = _position_id(cur, e["dept_id"], e["position"])

        cur.execute(
            "INSERT INTO employees (first_name, middle_name, last_name, suffix, sex, birthday, email, phone, "
            "stat, salary, department_id, position_id, hired, emp_type) "
            "VALUES (%s, NULL, %s, NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                e["first"], e["last"], e["sex"], e["birthday"],
                e["email"], e["phone"], e["status"], e["salary"],
                e["dept_id"], pos_id, e["hired"], e["type"]
            ),
        )
        emp_id = cur.lastrowid

        code = None
        for _ in range(20):
            c = "biri-%06d" % secrets.randbelow(1_000_000)
            cur.execute("SELECT 1 AS ok FROM account WHERE employee_code = %s", (c,))
            if not cur.fetchone():
                code = c
                break
        if not code:
            raise ApiError("Could not generate a unique employee ID. Please try again.", 500)
        temp_password = secrets.token_urlsafe(8)
        cur.execute(
            "INSERT INTO account (employee_code, employee_id, account_email, account_password, account_role) "
            "VALUES (%s, %s, %s, %s, 'employee')",
            (code, emp_id, e["email"], generate_password_hash(temp_password)),
        )
        log_activity(cur, "HR added employee %s %s" % (e["first"], e["last"]))
    return jsonify(id=emp_id, code=code, temp_password=temp_password), 201


@hr_bp.route("/employees/<int:emp_id>", methods=["PUT"])
@role_required("hr")
def update_employee(emp_id):
    e = _parse_employee(_body())
    e["salary"] = float(e.get("salary") or 0)
    with db() as (conn, cur):
        cur.execute("SELECT email FROM employees WHERE employee_id = %s", (emp_id,))
        current = cur.fetchone()
        if not current:
            raise ApiError("Employee not found.", 404)
        cur.execute("SELECT 1 AS ok FROM employees WHERE email = %s AND employee_id <> %s", (e["email"], emp_id))
        if cur.fetchone():
            raise ApiError("Another employee already uses that email.", 409)
        cur.execute("SELECT 1 AS ok FROM account WHERE account_email = %s AND (employee_id IS NULL OR employee_id <> %s)",
                    (e["email"], emp_id))
        if cur.fetchone():
            raise ApiError("Another account already uses that email.", 409)
        _need_department(cur, e["dept_id"])
        pos_id = _position_id(cur, e["dept_id"], e["position"])
        cur.execute(
            "UPDATE employees SET first_name=%s, last_name=%s, sex=%s, birthday=%s, email=%s, phone=%s, stat=%s, "
            "salary=%s, department_id=%s, position_id=%s, hired=%s, emp_type=%s WHERE employee_id=%s",
            (e["first"], e["last"], e["sex"], e["birthday"], e["email"], e["phone"], e["status"],
             e["salary"], e["dept_id"], pos_id, e["hired"], e["type"], emp_id),
        )
        if e["email"] != current["email"]:
            cur.execute("UPDATE account SET account_email = %s WHERE employee_id = %s", (e["email"], emp_id))
        log_activity(cur, "HR updated employee %s %s" % (e["first"], e["last"]))
    return jsonify(id=emp_id, message="Employee updated.")


@hr_bp.route("/employees/<int:emp_id>", methods=["DELETE"])
@role_required("hr")
def delete_employee(emp_id):
    with db() as (conn, cur):
        cur.execute("SELECT first_name, last_name FROM employees WHERE employee_id = %s", (emp_id,))
        row = cur.fetchone()
        if not row:
            raise ApiError("Employee not found.", 404)
        if emp_id_is_current_user(cur, emp_id):
            raise ApiError("You can't delete your own employee record.", 400)
        purge_employee(cur, emp_id)
        log_activity(cur, "HR deleted employee %s %s" % (row["first_name"], row["last_name"]))
    return jsonify(ok=True)


def emp_id_is_current_user(cur, emp_id):
    cur.execute("SELECT 1 AS ok FROM account WHERE account_id = %s AND employee_id = %s",
                (session.get("account_id"), emp_id))
    return cur.fetchone() is not None


# --------------------------------------------------------------------------
# Generic list / create / update / delete
# --------------------------------------------------------------------------
@hr_bp.route("/<res>", methods=["GET"])
@role_required("hr")
def list_rows(res):
    cfg = _cfg(res)
    select = ", ".join(["%s AS id" % cfg["pk"]] + ["%s AS `%s`" % (c, a) for a, c, _ in cfg["cols"]])
    with db() as (conn, cur):
        cur.execute("SELECT %s FROM %s ORDER BY %s" % (select, cfg["table"], cfg["order"]))
        rows = [_clean(r) for r in cur.fetchall()]
    for r in rows:
        for a, _, kind in cfg["cols"]:
            if kind == "j":
                try:
                    r[a] = json.loads(r[a] or "[]")
                except ValueError:
                    r[a] = []
            elif kind in ("s", "x") and r[a] is None:
                r[a] = ""
    return jsonify(rows)


@hr_bp.route("/<res>", methods=["POST"])
@role_required("hr")
def create_row(res):
    cfg = _cfg(res)
    data = _body()
    for key in cfg["required"]:
        if data.get(key) in (None, ""):
            raise ApiError("%s is required." % key.replace("_", " ").capitalize())
    vals = {}
    for a, c, kind in cfg["cols"]:
        if kind == "r":
            continue
        if a in data:
            vals[c] = _convert(res, a, kind, data[a])
        elif kind == "j":
            vals[c] = "[]"
    _check_rules(res, vals)
    with db() as (conn, cur):
        if res == "departments":
            cur.execute("SELECT 1 AS ok FROM departments WHERE dept_name = %s", (vals["dept_name"],))
            if cur.fetchone():
                raise ApiError("That department already exists.", 409)
        cols = list(vals)
        cur.execute("INSERT INTO %s (%s) VALUES (%s)" % (cfg["table"], ", ".join(cols), ", ".join(["%s"] * len(cols))),
                    [vals[c] for c in cols])
        new_id = cur.lastrowid
        log_activity(cur, "HR added %s record #%s" % (res, new_id))
    return jsonify(id=new_id), 201


@hr_bp.route("/<res>/<int:rid>", methods=["PUT"])
@role_required("hr")
def update_row(res, rid):
    cfg = _cfg(res)
    data = _body()
    vals = {}
    for a, c, kind in cfg["cols"]:
        if kind != "r" and a in data:
            if a in cfg["required"] and data[a] in (None, ""):
                raise ApiError("%s is required." % a.replace("_", " ").capitalize())
            vals[c] = _convert(res, a, kind, data[a])
    if not vals:
        raise ApiError("Nothing to update.")
    with db() as (conn, cur):
        cur.execute("SELECT * FROM %s WHERE %s = %%s" % (cfg["table"], cfg["pk"]), (rid,))
        existing = cur.fetchone()
        if not existing:
            raise ApiError("Record not found.", 404)
        _check_rules(res, vals, existing)
        sets = ", ".join("%s = %%s" % c for c in vals)
        cur.execute("UPDATE %s SET %s WHERE %s = %%s" % (cfg["table"], sets, cfg["pk"]), list(vals.values()) + [rid])
        log_activity(cur, "HR updated %s record #%s" % (res, rid))
    return jsonify(id=rid, message="Saved.")


@hr_bp.route("/<res>/<int:rid>", methods=["DELETE"])
@role_required("hr")
def delete_row(res, rid):
    cfg = _cfg(res)
    with db() as (conn, cur):
        cur.execute("SELECT 1 AS ok FROM %s WHERE %s = %%s" % (cfg["table"], cfg["pk"]), (rid,))
        if not cur.fetchone():
            raise ApiError("Record not found.", 404)
        if res == "jobs":
            cur.execute("DELETE FROM hr_applicants WHERE job_id = %s", (rid,))
        cur.execute("DELETE FROM %s WHERE %s = %%s" % (cfg["table"], cfg["pk"]), (rid,))
        log_activity(cur, "HR deleted %s record #%s" % (res, rid))
    return jsonify(ok=True)

# --------------------------------------------------------------------------
# Payroll
# --------------------------------------------------------------------------

@hr_bp.route("/payroll", methods=["GET"])
@role_required("hr")
def list_payroll():
    with db() as (conn, cur):
        cur.execute(
            """
            SELECT
                p.payroll_id AS id,
                p.employee_id,
                CONCAT(e.first_name, ' ', e.last_name) AS employee_name,
                p.pay_period,
                p.monthly_salary,
                p.overtime_pay,
                p.absence_deduction,
                p.unpaid_leave_deduction,
                p.allowances,
                p.manual_deductions,
                p.gross_pay,
                p.deductions,
                p.net_pay,
                p.payment_status,
                p.created_at
            FROM payroll p
            JOIN employees e ON e.employee_id = p.employee_id
            ORDER BY p.pay_period DESC, p.payroll_id DESC
            """
        )
        rows = [_clean(row) for row in cur.fetchall()]

    return jsonify(rows)

@hr_bp.route("/payroll", methods=["POST"])
@role_required("hr")
def create_payroll():
    """Create one payroll record for an employee and month.

    Daily rate is monthly salary / 26; hourly rate is daily rate / 8.
    Overtime is paid at 1.25x. Only recorded absences and approved
    unpaid leave are deducted. An absence is not deducted twice when
    it overlaps an approved unpaid-leave day.
    """
    data = _body()

    try:
        employee_id = int(data.get("employee_id"))
    except (TypeError, ValueError):
        raise ApiError("Please select a valid employee.")

    pay_period = _date(data.get("pay_period"), "Pay period")
    if not pay_period or pay_period.day != 1:
        raise ApiError("Pay period must be the first day of the selected month.")

    month_start = pay_period
    if pay_period.month == 12:
        month_end = date(pay_period.year + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = date(pay_period.year, pay_period.month + 1, 1) - timedelta(days=1)

    with db() as (conn, cur):
        # Do not create duplicate payrolls for the same employee and month.
        cur.execute(
            "SELECT payroll_id, payment_status FROM payroll "
            "WHERE employee_id = %s AND pay_period = %s LIMIT 1",
            (employee_id, month_start),
        )
        existing = cur.fetchone()
        if existing:
            status = existing.get("payment_status") or "Unpaid"
            raise ApiError(
                "Payroll already exists for this employee and month (%s)." % status,
                409,
            )

        cur.execute(
            "SELECT employee_id, salary FROM employees "
            "WHERE employee_id = %s AND stat NOT IN ('Resigned', 'Terminated')",
            (employee_id,),
        )
        employee = cur.fetchone()
        if not employee:
            raise ApiError("Employee not found or no longer active.", 404)

        monthly_salary = Decimal(str(employee.get("salary") or 0))
        if monthly_salary < 0:
            raise ApiError("Employee salary cannot be negative.")

        daily_rate = monthly_salary / Decimal("26")
        hourly_rate = daily_rate / Decimal("8")

        # Count only explicitly recorded Absent attendance rows.
        cur.execute(
            """
            SELECT work_date, COALESCE(overtime_hours, 0) AS overtime_hours, status
            FROM attendance
            WHERE employee_id = %s AND work_date BETWEEN %s AND %s
            """,
            (employee_id, month_start, month_end),
        )
        attendance_rows = cur.fetchall()

        absent_dates = set()
        overtime_hours = Decimal("0")
        for row in attendance_rows:
            work_date = row["work_date"]
            if isinstance(work_date, datetime):
                work_date = work_date.date()
            elif isinstance(work_date, str):
                work_date = _date(work_date, "Attendance date")
            if row.get("status") == "Absent" and work_date:
                absent_dates.add(work_date)
            overtime_hours += Decimal(str(row.get("overtime_hours") or 0))

        overtime_pay = hourly_rate * Decimal("1.25") * overtime_hours
        absence_deduction = daily_rate * len(absent_dates)

        # Approved unpaid leave is counted Monday-Saturday only.
        # Avoid deducting a day twice if it is also marked Absent.
        cur.execute(
            """
            SELECT start_date, end_date
            FROM leave_requests
            WHERE employee_id = %s
              AND leave_status = 'Approved'
              AND leave_type = 'Unpaid Leave (LOA)'
              AND start_date <= %s
              AND end_date >= %s
            """,
            (employee_id, month_end, month_start),
        )
        leave_rows = cur.fetchall()

        unpaid_leave_dates = set()
        for row in leave_rows:
            start = row["start_date"]
            end = row["end_date"]
            if isinstance(start, datetime):
                start = start.date()
            elif isinstance(start, str):
                start = _date(start, "Leave start date")
            if isinstance(end, datetime):
                end = end.date()
            elif isinstance(end, str):
                end = _date(end, "Leave end date")
            current = max(start, month_start)
            last = min(end, month_end)
            while current <= last:
                if current.weekday() != 6 and current not in absent_dates:
                    unpaid_leave_dates.add(current)
                current += timedelta(days=1)

        unpaid_leave_deduction = daily_rate * len(unpaid_leave_dates)

        # These are optional inputs and default to zero.
        try:
            allowances = Decimal(str(data.get("allowances") or 0))
            manual_deductions = Decimal(str(data.get("manual_deductions") or 0))
        except Exception:
            raise ApiError("Allowances and manual deductions must be valid numbers.")
        if allowances < 0 or manual_deductions < 0:
            raise ApiError("Allowances and manual deductions cannot be negative.")

        gross_pay = monthly_salary + overtime_pay + allowances
        deductions = absence_deduction + unpaid_leave_deduction + manual_deductions
        net_pay = gross_pay - deductions

        cur.execute(
            """
            INSERT INTO payroll (
                employee_id, pay_period, monthly_salary, overtime_pay,
                absence_deduction, unpaid_leave_deduction, allowances,
                manual_deductions, gross_pay, deductions, net_pay,
                payment_status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Unpaid')
            """,
            (
                employee_id, month_start, monthly_salary, overtime_pay,
                absence_deduction, unpaid_leave_deduction, allowances,
                manual_deductions, gross_pay, deductions, net_pay,
            ),
        )
        payroll_id = cur.lastrowid
        log_activity(
            cur,
            "HR generated payroll #%s for employee #%s (%s)" %
            (payroll_id, employee_id, month_start.strftime("%Y-%m")),
        )

    return jsonify(id=payroll_id, message="Payroll generated successfully."), 201
