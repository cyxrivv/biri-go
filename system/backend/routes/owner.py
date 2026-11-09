"""Owner portal: page + API.  Replaces system/backend/routes/owner.py

!! Table / column names for attendance, leaves, payslips and announcements are GUESSED.
!! Open routes/employee.py, see what those tables are really called, and fix the
!! CONFIG block below (only place you need to change).
"""
import datetime as dt
from decimal import Decimal

from flask import Blueprint, jsonify, render_template, request, session

from auth import role_required
from db import db
from utils import ApiError

owner_bp = Blueprint("owner", __name__)

# ============================ CONFIG (edit if needed) ============================
ATT, LEAVE, PAY, NEWS = "attendance", "leaves", "payslips", "announcements"
LEAVE_PK, PAY_PK, NEWS_PK = "id", "id", "id"        # primary-key column of each table
FK = "employee_id"                                   # employee column in those tables
# ================================================================================

NAME = "TRIM(CONCAT_WS(' ', e.first_name, e.last_name))"
INACTIVE = "e.stat NOT IN ('Resigned', 'Terminated')"


def _clean(v):
    if isinstance(v, dt.timedelta):                  # TIME columns
        s = int(v.total_seconds())
        return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"
    if isinstance(v, (dt.datetime, dt.date)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, Decimal):
        return float(v)
    return v


def q(sql, args=()):
    with db() as (_, cur):
        cur.execute(sql, args)
        return [{k: _clean(v) for k, v in r.items()} for r in cur.fetchall()]


def scalar(sql, args=()):
    rows = q(sql, args)
    return next(iter(rows[0].values())) if rows else 0


def run(sql, args=()):
    with db() as (conn, cur):
        cur.execute(sql, args)
        return cur.rowcount


# ---------------------------------------------------------------- page
@owner_bp.route("/owner")
@role_required("owner")
def owner_page():
    return render_template("owner.html")


# ---------------------------------------------------------------- dashboard
ATT_SQL = f"""
    SELECT {NAME} AS name, a2.employee_code, d.dept_name AS department,
           t.time_in, t.time_out, t.status
    FROM {ATT} t
    JOIN employees e ON e.employee_id = t.{FK}
    LEFT JOIN account a2 ON a2.employee_id = e.employee_id
    LEFT JOIN departments d ON d.department_id = e.department_id
    WHERE t.work_date = %s ORDER BY t.time_in
"""


@owner_bp.route("/api/owner/summary")
@role_required("owner")
def summary():
    today = dt.date.today()
    me = q("SELECT e.first_name, e.last_name, a.account_email FROM account a "
           "LEFT JOIN employees e ON e.employee_id = a.employee_id WHERE a.account_id = %s",
           (session.get("account_id"),))
    name = "Owner"
    if me:
        name = " ".join(p for p in (me[0]["first_name"], me[0]["last_name"]) if p) or me[0]["account_email"]

    stats = {
        "employees": scalar(f"SELECT COUNT(*) FROM employees e WHERE {INACTIVE}"),
        "present_today": scalar(f"SELECT COUNT(DISTINCT {FK}) FROM {ATT} WHERE work_date = %s", (today,)),
        "on_leave": scalar(f"SELECT COUNT(DISTINCT {FK}) FROM {LEAVE} WHERE status='Approved' "
                           "AND %s BETWEEN start_date AND end_date", (today,)),
        "pending_leaves": scalar(f"SELECT COUNT(*) FROM {LEAVE} WHERE status='Pending'"),
        "payroll_month": scalar(f"SELECT COALESCE(SUM(net_pay),0) FROM {PAY} "
                                "WHERE DATE_FORMAT(pay_period,'%%Y-%%m') = %s", (today.strftime("%Y-%m"),)),
    }
    pending = q(f"""SELECT l.{LEAVE_PK} AS id, {NAME} AS name, a.employee_code, l.type, l.start_date, l.end_date
                    FROM {LEAVE} l JOIN employees e ON e.employee_id = l.{FK}
                    LEFT JOIN account a ON a.employee_id = e.employee_id
                    WHERE l.status='Pending' ORDER BY l.start_date LIMIT 5""")
    depts = q(f"""SELECT d.dept_name AS name, COUNT(e.employee_id) AS count
                  FROM departments d LEFT JOIN employees e
                    ON e.department_id = d.department_id AND {INACTIVE}
                  GROUP BY d.department_id, d.dept_name ORDER BY count DESC""")
    return jsonify(owner_name=name, stats=stats, pending_leaves=pending, departments=depts,
                   attendance_today=q(ATT_SQL, (today,)))


# ---------------------------------------------------------------- employees
@owner_bp.route("/api/owner/employees")
@role_required("owner")
def employees():
    return jsonify(employees=q(f"""
        SELECT e.employee_id AS id, a.employee_code, {NAME} AS name, e.email, e.phone,
               d.dept_name AS department, p.title AS position, e.stat AS status
        FROM employees e
        LEFT JOIN account a ON a.employee_id = e.employee_id
        LEFT JOIN departments d ON d.department_id = e.department_id
        LEFT JOIN positions p ON p.position_id = e.position_id
        ORDER BY e.last_name, e.first_name"""))


# ---------------------------------------------------------------- attendance
@owner_bp.route("/api/owner/attendance")
@role_required("owner")
def attendance():
    try:
        day = dt.date.fromisoformat(request.args.get("date", ""))
    except ValueError:
        day = dt.date.today()
    return jsonify(attendance=q(ATT_SQL, (day,)))


# ---------------------------------------------------------------- leaves
@owner_bp.route("/api/owner/leaves")
@role_required("owner")
def leaves():
    status = request.args.get("status", "")
    where, args = (("WHERE l.status = %s", (status,))
                   if status in ("Pending", "Approved", "Rejected") else ("", ()))
    return jsonify(leaves=q(f"""
        SELECT l.{LEAVE_PK} AS id, {NAME} AS name, a.employee_code, l.type, l.start_date, l.end_date, l.status
        FROM {LEAVE} l JOIN employees e ON e.employee_id = l.{FK}
        LEFT JOIN account a ON a.employee_id = e.employee_id {where}
        ORDER BY (l.status = 'Pending') DESC, l.start_date DESC""", args))


@owner_bp.route("/api/owner/leaves/<int:leave_id>/decision", methods=["POST"])
@role_required("owner")
def decide_leave(leave_id):
    status = (request.get_json(silent=True) or {}).get("status")
    if status not in ("Approved", "Rejected"):
        raise ApiError("Invalid decision.")
    if not run(f"UPDATE {LEAVE} SET status = %s WHERE {LEAVE_PK} = %s AND status = 'Pending'", (status, leave_id)):
        raise ApiError("This request was already decided or does not exist.", 404)
    return jsonify(message=f"Leave {status.lower()}.")


# ---------------------------------------------------------------- payroll
@owner_bp.route("/api/owner/payroll")
@role_required("owner")
def payroll():
    rows = q(f"""SELECT p.{PAY_PK} AS id, {NAME} AS name, a.employee_code,
                        p.pay_period, p.gross_pay, p.deductions, p.net_pay
                 FROM {PAY} p JOIN employees e ON e.employee_id = p.{FK}
                 LEFT JOIN account a ON a.employee_id = e.employee_id
                 ORDER BY p.pay_period DESC, e.last_name LIMIT 200""")
    month = dt.date.today().strftime("%Y-%m")
    total = sum(r["net_pay"] or 0 for r in rows if str(r["pay_period"])[:7] == month)
    return jsonify(payslips=rows, month_total=total)


# ---------------------------------------------------------------- announcements
@owner_bp.route("/api/owner/announcements")
@role_required("owner")
def announcements():
    return jsonify(announcements=q(
        f"SELECT {NEWS_PK} AS id, title, body, date FROM {NEWS} ORDER BY date DESC, {NEWS_PK} DESC LIMIT 50"))


@owner_bp.route("/api/owner/announcements", methods=["POST"])
@role_required("owner")
def add_announcement():
    d = request.get_json(silent=True) or {}
    title, body = (d.get("title") or "").strip(), (d.get("body") or "").strip()
    if not title or not body:
        raise ApiError("Title and message are required.")
    if len(title) > 120 or len(body) > 1000:
        raise ApiError("Title or message is too long.")
    run(f"INSERT INTO {NEWS} (title, body, date) VALUES (%s, %s, CURDATE())", (title, body))
    return jsonify(message="Announcement posted."), 201


@owner_bp.route("/api/owner/announcements/<int:ann_id>", methods=["DELETE"])
@role_required("owner")
def delete_announcement(ann_id):
    if not run(f"DELETE FROM {NEWS} WHERE {NEWS_PK} = %s", (ann_id,)):
        raise ApiError("Announcement not found.", 404)
    return jsonify(message="Announcement deleted.")