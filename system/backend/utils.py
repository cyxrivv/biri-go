import re
from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import request
from flask.json.provider import DefaultJSONProvider

import mysql.connector

from db import fetch_all, fetch_one

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
EMPLOYEE_STATUSES = ("Active", "On Leave", "Resigned", "Terminated")
LEAVE_ALLOWANCE = {
    "Vacation Leave (PTO)": 15,
    "Sick Leave": 7,
    "Emergency Leave": 3,
    "Bereavement Leave": 3,
    "Maternity Leave": 105,
    "Paternity Leave": 7,
    "Parental Leave": 7,
    "Special Leave (Mandated)": 5,
    "Unpaid Leave (LOA)": None,
}
LEAVE_SEX_ONLY = {"Maternity Leave": "Female", "Paternity Leave": "Male"}
LEAVE_TYPES = tuple(LEAVE_ALLOWANCE)   # keeps hr.py's existing import working
LEAVE_STATUSES = ("Pending", "Approved", "Rejected")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# --------------------------------------------------------------------------
# JSON provider (Decimal, dates and timedelta become JSON-friendly)
# --------------------------------------------------------------------------
def _json_default(o):
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    if isinstance(o, timedelta):
        total = int(o.total_seconds())
        return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"
    return DefaultJSONProvider.default(o)


class AppJSONProvider(DefaultJSONProvider):
    default = staticmethod(_json_default)
    sort_keys = False


# --------------------------------------------------------------------------
# Errors and validation helpers
# --------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def clean(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def to_int(value, field, required=True):
    value = clean(value)
    if value is None:
        if required:
            raise ApiError(f"{field} is required.")
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError(f"{field} must be a whole number.")


def to_money(value, field, required=False):
    value = clean(value)
    if value is None:
        if required:
            raise ApiError(f"{field} is required.")
        return None
    try:
        amount = Decimal(str(value))
    except Exception:
        raise ApiError(f"{field} must be a number.")
    if amount < 0 or amount >= Decimal("100000000"):
        raise ApiError(f"{field} is out of range.")
    return amount.quantize(Decimal("0.01"))


def to_date(value, field):
    value = clean(value)
    if value is None:
        raise ApiError(f"{field} is required.")
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        raise ApiError(f"{field} must be a date (YYYY-MM-DD).")


def arg_int(name, default, minimum=1, maximum=None):
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default
    value = max(value, minimum)
    if maximum is not None:
        value = min(value, maximum)
    return value


def json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Request body must be a JSON object.")
    return data


# --------------------------------------------------------------------------
# Employee lookup (shared by HR, owner and employee routes)
# --------------------------------------------------------------------------
EMP_SELECT = """
    SELECT e.employee_id AS id,
           e.first_name, e.last_name,
           CONCAT(e.first_name, ' ', e.last_name) AS name,
           e.email, e.phone,
           e.stat AS status,
           e.salary,
           e.department_id, d.dept_name AS department,
           e.position_id,   p.title     AS position,
           e.manager_id
    FROM employees e
    LEFT JOIN departments d ON d.department_id = e.department_id
    LEFT JOIN positions   p ON p.position_id   = e.position_id
"""


def get_employee(employee_id):
    return fetch_one(EMP_SELECT + " WHERE e.employee_id = %s", (employee_id,))


# --------------------------------------------------------------------------
# HR settings (work hours, leave entitlements) - stored in hr_settings
# --------------------------------------------------------------------------
SETTING_DEFAULTS = {"work_start": "08:00", "work_end": "17:00", "grace_minutes": 15,
                    "leave_vacation": 15, "leave_sick": 7, "leave_emergency": 3, "probation_months": 6}
LEAVE_SETTING_KEY = {"Vacation Leave (PTO)": "leave_vacation", "Sick Leave": "leave_sick",
                     "Emergency Leave": "leave_emergency"}


def get_settings():
    out = dict(SETTING_DEFAULTS)
    try:
        for r in fetch_all("SELECT skey, svalue FROM hr_settings"):
            key = r["skey"]
            if key in out:
                try:
                    out[key] = r["svalue"] if isinstance(SETTING_DEFAULTS[key], str) else int(r["svalue"])
                except (TypeError, ValueError):
                    pass
    except mysql.connector.Error:
        pass
    return out


def leave_allowances():
    """LEAVE_ALLOWANCE, with the three entitlements HR can edit in Settings applied."""
    settings = get_settings()
    allowance = dict(LEAVE_ALLOWANCE)
    for leave_type, key in LEAVE_SETTING_KEY.items():
        allowance[leave_type] = settings[key]
    return allowance


# --------------------------------------------------------------------------
# Leave rules shared by the admin, HR and employee routes
# --------------------------------------------------------------------------
def ensure_leave_balance(employee_id, leave_type, start, end, exclude_id=None, statuses=("Approved",)):
    allowance = leave_allowances().get(leave_type)
    if allowance is None:               # unpaid leave has no limit
        return
    marks = ", ".join(["%s"] * len(statuses))
    sql = ("SELECT COALESCE(SUM(DATEDIFF(end_date, start_date) + 1), 0) AS days FROM leave_requests "
           "WHERE employee_id = %s AND leave_type = %s AND YEAR(start_date) = %s "
           "AND leave_status IN (" + marks + ")")
    params = [employee_id, leave_type, start.year, *statuses]
    if exclude_id:
        sql += " AND leave_id <> %s"
        params.append(exclude_id)
    used = int(fetch_one(sql, params)["days"])
    if used + (end - start).days + 1 > allowance:
        raise ApiError(f"Not enough {leave_type} balance ({max(allowance - used, 0)} day(s) remaining).")


def validate_leave_request(employee_id, leave_type, start, end, exclude_id=None, status="Pending"):
    """Type, sex-restricted types, date order, overlaps and balance."""
    emp = fetch_one("SELECT sex FROM employees WHERE employee_id = %s", (employee_id,))
    if not emp:
        raise ApiError("Selected employee doesn't exist.")
    if leave_type not in LEAVE_ALLOWANCE:
        raise ApiError("Select a valid leave type.")
    needed = LEAVE_SEX_ONLY.get(leave_type)
    if needed and emp["sex"] != needed:
        raise ApiError(f"{leave_type} isn't available for this employee.")
    if end < start:
        raise ApiError("The end date can't be before the start date.")
    if status == "Rejected":
        return
    sql = ("SELECT 1 AS ok FROM leave_requests WHERE employee_id = %s AND leave_status <> 'Rejected' "
           "AND start_date <= %s AND end_date >= %s")
    params = [employee_id, end, start]
    if exclude_id:
        sql += " AND leave_id <> %s"
        params.append(exclude_id)
    if fetch_one(sql, params):
        raise ApiError("This employee already has a leave request on those dates.")
    counted = ("Approved",) if status == "Approved" else ("Approved", "Pending")
    ensure_leave_balance(employee_id, leave_type, start, end, exclude_id, counted)


# --------------------------------------------------------------------------
# Deleting an employee together with everything that points at them
# --------------------------------------------------------------------------
def purge_employee(cur, employee_id):
    for table in ("attendance", "leave_requests", "payroll", "hr_reviews", "hr_processes"):
        cur.execute("DELETE FROM %s WHERE employee_id = %%s" % table, (employee_id,))
    cur.execute("UPDATE departments SET head_employee_id = NULL WHERE head_employee_id = %s", (employee_id,))
    cur.execute("UPDATE employees SET manager_id = NULL WHERE manager_id = %s", (employee_id,))
    cur.execute("DELETE FROM account WHERE employee_id = %s", (employee_id,))
    cur.execute("DELETE FROM employees WHERE employee_id = %s", (employee_id,))
