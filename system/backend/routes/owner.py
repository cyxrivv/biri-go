"""routes/owner.py  -  OWNER portal (VIEW-ONLY).  Replaces system/backend/routes/owner.py

    GET /owner                      the page (template/owner.html)
    GET /api/owner/me               owner's name
    GET /api/owner/settings         HR settings (read only)
    GET /api/owner/employees        employees incl. salary
    GET /api/owner/payroll          payroll records (gross / deductions / net)
    GET /api/owner/<resource>       departments, jobs, applicants, processes, attendance,
                                    leaves, reviews, trainings, announcements, holidays

The owner can look at everything HR sees, but cannot change anything.
Two layers enforce that:
  1. Only GET routes exist here.
  2. before_request rejects any POST / PUT / PATCH / DELETE sent to /api/owner/*.
"""
import json

from flask import Blueprint, jsonify, render_template, request, session

from auth import role_required
from db import db
from utils import ApiError, get_settings as read_settings

# Reuse the HR resource definitions so the owner always sees the same data as HR.
try:
    from routes.hr import RESOURCES, _EMP_SELECT, _clean
except ImportError:                       # if routes/ is not imported as a package
    from hr import RESOURCES, _EMP_SELECT, _clean

owner_bp = Blueprint("owner", __name__)


@owner_bp.before_request
def block_writes():
    if request.path.startswith("/api/owner") and request.method not in ("GET", "HEAD", "OPTIONS"):
        return jsonify(error="The owner portal is view-only."), 405


# ---------------------------------------------------------------- page
@owner_bp.route("/owner")
@role_required("owner")
def owner_page():
    return render_template("owner.html")


# ---------------------------------------------------------------- who am I
@owner_bp.route("/api/owner/me")
@role_required("owner")
def me():
    with db() as (conn, cur):
        cur.execute(
            "SELECT e.first_name, e.last_name FROM account a "
            "LEFT JOIN employees e ON e.employee_id = a.employee_id WHERE a.account_id = %s",
            (session.get("account_id"),),
        )
        row = cur.fetchone() or {}
    name = ("%s %s" % (row.get("first_name") or "", row.get("last_name") or "")).strip()
    return jsonify(name=name or "Owner")


# ---------------------------------------------------------------- settings (read only)
@owner_bp.route("/api/owner/settings")
@role_required("owner")
def settings():
    return jsonify(read_settings())


# ---------------------------------------------------------------- employees (includes salary)
@owner_bp.route("/api/owner/employees")
@role_required("owner")
def employees():
    with db() as (conn, cur):
        cur.execute(_EMP_SELECT + "ORDER BY e.employee_id")
        rows = [_clean(r) for r in cur.fetchall()]
    return jsonify(rows)


# ---------------------------------------------------------------- payroll (net pay)
@owner_bp.route("/api/owner/payroll")
@role_required("owner")
def payroll():
    with db() as (conn, cur):
        cur.execute(
            """
            SELECT p.payroll_id AS id, p.employee_id,
                   CONCAT(e.first_name, ' ', e.last_name) AS employee_name,
                   p.pay_period, p.monthly_salary, p.overtime_pay,
                   p.absence_deduction, p.unpaid_leave_deduction,
                   p.allowances, p.manual_deductions,
                   p.gross_pay, p.deductions, p.net_pay,
                   p.payment_status, p.created_at
            FROM payroll p
            JOIN employees e ON e.employee_id = p.employee_id
            ORDER BY p.pay_period DESC, p.payroll_id DESC
            """
        )
        rows = [_clean(r) for r in cur.fetchall()]
    return jsonify(rows)


# ---------------------------------------------------------------- everything else HR has (read only)
@owner_bp.route("/api/owner/<res>", methods=["GET"])
@role_required("owner")
def list_rows(res):
    cfg = RESOURCES.get(res)
    if not cfg:
        raise ApiError("Unknown resource.", 404)
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