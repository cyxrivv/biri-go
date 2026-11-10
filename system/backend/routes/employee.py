from datetime import date, datetime, time, timedelta
from decimal import Decimal

from html import escape

import mysql.connector
from flask import Blueprint, Response, jsonify, render_template, request, session

from auth import role_required
from db import db, fetch_all, fetch_one, log_activity
from utils import (ApiError, json_body, LEAVE_ALLOWANCE, LEAVE_SEX_ONLY, get_settings,
                   leave_allowances, validate_leave_request)

employee_bp = Blueprint("employee", __name__)

# Leave types and allowances live in utils.py (LEAVE_ALLOWANCE, LEAVE_SEX_ONLY).
DAILY_TARGET_HOURS = 8


def _current_sex(emp_id):
    row = fetch_one("SELECT sex FROM employees WHERE employee_id = %s", (emp_id,))
    return row["sex"] if row else None


def _allowed_types(sex):
    """Leave types this employee may request (sex-restricted ones are filtered)."""
    return [t for t in LEAVE_ALLOWANCE if LEAVE_SEX_ONLY.get(t) in (None, sex)]


# ---------- helpers ----------

def _date(value):
    """date/datetime -> 'YYYY-MM-DD' (the dashboard JS expects this format)."""
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def _clock(value):
    """TIME -> '08:30 AM'. MySQL TIME columns come back as timedelta."""
    if value is None:
        return None
    if isinstance(value, timedelta):
        seconds = int(value.total_seconds())
        value = time((seconds // 3600) % 24, (seconds % 3600) // 60)
    if isinstance(value, (time, datetime)):
        return value.strftime("%I:%M %p")
    return str(value)


def _money(value):
    return float(value) if isinstance(value, Decimal) else value


def _current_employee_id():
    """The employee_id always comes from the session, never from the request."""
    row = fetch_one(
        "SELECT employee_id FROM account WHERE account_id = %s",
        (session.get("account_id"),),
    )
    if not row or row["employee_id"] is None:
        raise ApiError("No employee record is linked to this account.", 404)
    return row["employee_id"]


# ---------- page ----------

@employee_bp.get("/employee")
@role_required("employee")
def employee_page():
    return render_template("employee_dashboard.html")


# ---------- API ----------

@employee_bp.get("/api/employee/me")
@role_required("employee")
def employee_me():
    row = fetch_one(
        """
        SELECT a.employee_code, a.account_email,
               e.first_name, e.middle_name, e.last_name, e.suffix, e.sex,
               e.birthday, e.email, e.phone, e.stat AS status,
               d.dept_name AS department, p.title AS position
        FROM account a
        JOIN employees e ON e.employee_id = a.employee_id
        LEFT JOIN departments d ON d.department_id = e.department_id
        LEFT JOIN positions   p ON p.position_id   = e.position_id
        WHERE a.account_id = %s
        """,
        (session.get("account_id"),),
    )
    if not row:
        raise ApiError("Employee profile not found.", 404)

    row["birthday"] = _date(row["birthday"])
    return jsonify(row)


@employee_bp.get("/api/employee/summary")
@role_required("employee")
def employee_summary():
    emp_id = _current_employee_id()
    allowed = _allowed_types(_current_sex(emp_id))

    leaves = fetch_all(
        "SELECT leave_type AS type, start_date, end_date, leave_status AS status "
        "FROM leave_requests WHERE employee_id = %s "
        "ORDER BY start_date DESC, leave_id DESC LIMIT 10",
        (emp_id,),
    )
    leave_counts = {
        r["status"]: r["total"]
        for r in fetch_all(
            "SELECT leave_status AS status, COUNT(*) AS total "
            "FROM leave_requests WHERE employee_id = %s GROUP BY leave_status",
            (emp_id,),
        )
    }
    attendance = fetch_all(
        "SELECT work_date, time_in, time_out FROM attendance "
        "WHERE employee_id = %s ORDER BY work_date DESC LIMIT 10",
        (emp_id,),
    )
    payslips = fetch_all(
        "SELECT payroll_id AS id, pay_period, gross_pay, deductions, net_pay FROM payroll "
        "WHERE employee_id = %s ORDER BY pay_period DESC, payroll_id DESC LIMIT 6",
        (emp_id,),
    )

    settings = get_settings()
    now = datetime.now()
    today_row = fetch_one(
        "SELECT time_in, time_out, status FROM attendance WHERE employee_id = %s AND work_date = %s",
        (emp_id, now.date()),
    )
    try:
        announcements = fetch_all(
            "SELECT title, body, posted_on AS date FROM hr_announcements ORDER BY posted_on DESC, id DESC LIMIT 5"
        )
    except mysql.connector.Error:
        announcements = []
    for a in announcements:
        a["date"] = _date(a["date"])

    for l in leaves:
        l["start_date"] = _date(l["start_date"])
        l["end_date"] = _date(l["end_date"])
    for a in attendance:
        a["work_date"] = _date(a["work_date"])
        a["time_in"] = _clock(a["time_in"])
        a["time_out"] = _clock(a["time_out"])
    for p in payslips:
        p["pay_period"] = _date(p["pay_period"])
        for key in ("gross_pay", "deductions", "net_pay"):
            p[key] = _money(p[key])

    return jsonify(
        leaves=leaves,
        leave_counts=leave_counts,
        attendance=attendance,
        payslips=payslips,
        stats=_month_stats(emp_id),
        leave_balances=_leave_balances(emp_id, allowed),
        leave_types=allowed,
        announcements=announcements,
        daily_target=DAILY_TARGET_HOURS,
        shift={"start": settings["work_start"], "end": settings["work_end"]},
        today=_today_payload(today_row),
        server_now=now.hour * 3600 + now.minute * 60 + now.second,
    )


def _hm(value):
    """TIME (timedelta) -> 'HH:MM' for the browser to calculate with."""
    if value is None:
        return None
    seconds = int(value.total_seconds())
    return "%02d:%02d" % ((seconds // 3600) % 24, (seconds % 3600) // 60)


def _today_payload(row):
    if not row:
        return None
    return {"time_in": _hm(row["time_in"]), "time_out": _hm(row["time_out"]),
            "time_in_label": _clock(row["time_in"]), "time_out_label": _clock(row["time_out"]),
            "status": row["status"]}


# ---------- dashboard numbers ----------

def _month_stats(emp_id):
    today = date.today()
    first = today.replace(day=1)
    row = fetch_one(
        "SELECT COUNT(*) AS days, COALESCE(SUM(CASE WHEN time_out IS NOT NULL "
        "THEN TIME_TO_SEC(time_out) - TIME_TO_SEC(time_in) END), 0) AS secs "
        "FROM attendance WHERE employee_id = %s AND time_in IS NOT NULL "
        "AND work_date BETWEEN %s AND %s",
        (emp_id, first, today),
    )
    working = sum(1 for i in range(today.day) if (first + timedelta(days=i)).weekday() < 5)
    days = int(row["days"])
    return {
        "days_present": days,
        "working_days": working,
        "attendance_rate": round(days / working * 100, 1) if working else None,
        "hours_month": round(float(row["secs"]) / 3600, 1),
    }


def _leave_balances(emp_id, allowed):
    used = {
        r["type"]: int(r["days"])
        for r in fetch_all(
            "SELECT leave_type AS type, SUM(DATEDIFF(end_date, start_date) + 1) AS days "
            "FROM leave_requests WHERE employee_id = %s AND leave_status = 'Approved' "
            "AND YEAR(start_date) = %s GROUP BY leave_type",
            (emp_id, date.today().year),
        )
    }
    return [
        {"type": t, "total": total, "used": used.get(t, 0), "remaining": max(total - used.get(t, 0), 0)}
        for t, total in leave_allowances().items()
        if total is not None and t in allowed
    ]


# ---------- actions ----------

@employee_bp.post("/api/employee/attendance/check-in")
@role_required("employee")
def check_in():
    emp_id, today = _current_employee_id(), date.today()
    if fetch_one("SELECT 1 AS ok FROM attendance WHERE employee_id = %s AND work_date = %s", (emp_id, today)):
        raise ApiError("You have already checked in today.")
    now = datetime.now().replace(microsecond=0)
    settings = get_settings()
    start = datetime.strptime(settings["work_start"], "%H:%M")
    limit = (start + timedelta(minutes=settings["grace_minutes"])).time()
    status = "Late" if now.time() > limit else "Present"
    with db() as (_, cur):
        cur.execute(
            "INSERT INTO attendance (employee_id, work_date, time_in, status) VALUES (%s, %s, %s, %s)",
            (emp_id, today, now.time(), status),
        )
        log_activity(cur, f"Employee #{emp_id} checked in")
    return jsonify(message="Checked in."), 201


@employee_bp.post("/api/employee/attendance/check-out")
@role_required("employee")
def check_out():
    emp_id, today = _current_employee_id(), date.today()
    row = fetch_one(
        "SELECT time_in, time_out FROM attendance WHERE employee_id = %s AND work_date = %s", (emp_id, today)
    )
    if not row or row["time_in"] is None:
        raise ApiError("Check in first.")
    if row["time_out"] is not None:
        raise ApiError("You have already checked out today.")
    with db() as (_, cur):
        cur.execute(
            "UPDATE attendance SET time_out = %s WHERE employee_id = %s AND work_date = %s",
            (datetime.now().time().replace(microsecond=0), emp_id, today),
        )
        log_activity(cur, f"Employee #{emp_id} checked out")
    return jsonify(message="Checked out.")


@employee_bp.post("/api/employee/leaves")
@role_required("employee")
def request_leave():
    emp_id, data = _current_employee_id(), json_body()
    leave_type = (data.get("type") or "").strip()
    try:
        start, end = date.fromisoformat(data.get("start_date")), date.fromisoformat(data.get("end_date"))
    except (TypeError, ValueError):
        raise ApiError("Enter valid start and end dates.")
    validate_leave_request(emp_id, leave_type, start, end)
    reason = (data.get("reason") or "").strip()[:1000] or None
    with db() as (_, cur):
        cur.execute(
            "INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, reason, leave_status) "
            "VALUES (%s, %s, %s, %s, %s, 'Pending')",
            (emp_id, leave_type, start, end, reason),
        )
        log_activity(cur, f"Employee #{emp_id} requested {leave_type}")
    return jsonify(message="Leave request sent."), 201


def render_payslip(payroll_id, employee_id):
    """Printable payslip for ONE employee's own payroll row. ?download=1 saves it as a file."""
    row = fetch_one(
        "SELECT pay_period, gross_pay, deductions, net_pay FROM payroll "
        "WHERE payroll_id = %s AND employee_id = %s",
        (payroll_id, employee_id),
    )
    if not row:
        raise ApiError("Payslip not found.", 404)
    lines = "".join(
        f"<tr><th>{label}</th><td>&#8369;{float(row[key]):,.2f}</td></tr>"
        for label, key in (("Gross pay", "gross_pay"), ("Deductions", "deductions"), ("Net pay", "net_pay"))
    )
    period = escape(row["pay_period"].strftime("%B %Y") if hasattr(row["pay_period"], "strftime") else str(row["pay_period"]))
    page = (
        "<!doctype html><meta charset=utf-8><title>Payslip " + period + "</title>"
        "<style>body{font:16px system-ui;max-width:460px;margin:3rem auto}table{width:100%;border-collapse:collapse}"
        "th,td{padding:.6rem 0;border-bottom:1px solid #ddd;text-align:left}td{text-align:right}</style>"
        "<h2>Payslip &ndash; " + period + "</h2><table>" + lines + "</table>"
        "<p><button onclick=print()>Print</button></p>"
    )
    resp = Response(page, mimetype="text/html")
    if request.args.get("download"):
        resp.headers["Content-Disposition"] = f"attachment; filename=payslip-{payroll_id}.html"
    return resp


@employee_bp.get("/employee/payslips/<int:payroll_id>")
@role_required("employee")
def payslip(payroll_id):
    return render_payslip(payroll_id, _current_employee_id())