"""Self-service salary & payslips for HR, admin and owner accounts.

Same idea as the employee dashboard: the employee_id ALWAYS comes from the
logged-in session, never from the request, so nobody can read someone
else's pay through these endpoints.
"""
from functools import wraps

from flask import Blueprint, jsonify, session

from db import db, fetch_all, fetch_one
from utils import ApiError
from routes.employee import _date, _money, render_payslip

my_pay_bp = Blueprint("my_pay", __name__)

PAY_ROLES = ("hr", "admin", "owner")


def _pay_roles_only(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("account_id"):
            raise ApiError("Please sign in.", 401)
        if session.get("role") not in PAY_ROLES:
            raise ApiError("Not allowed.", 403)
        return fn(*args, **kwargs)
    return wrapper


def _linked_employee_id():
    """employee_id of the signed-in account, or None if the account has no employee record."""
    row = fetch_one(
        "SELECT a.employee_id FROM account a "
        "JOIN employees e ON e.employee_id = a.employee_id "
        "WHERE a.account_id = %s",
        (session.get("account_id"),),
    )
    return row["employee_id"] if row else None


@my_pay_bp.get("/api/me/pay")
@_pay_roles_only
def my_pay():
    emp_id = _linked_employee_id()
    if emp_id is None:
        # e.g. a bootstrap admin/owner with no employee record
        return jsonify(linked=False, salary=None, payslips=[])

    emp = fetch_one(
        "SELECT e.salary, p.title AS position, d.dept_name AS department "
        "FROM employees e "
        "LEFT JOIN positions p ON p.position_id = e.position_id "
        "LEFT JOIN departments d ON d.department_id = e.department_id "
        "WHERE e.employee_id = %s",
        (emp_id,),
    )
    payslips = fetch_all(
        "SELECT payroll_id AS id, pay_period, gross_pay, deductions, net_pay, "
        "(hr_confirmed_at IS NOT NULL) AS hr_confirmed, "
        "(employee_confirmed_at IS NOT NULL) AS employee_confirmed FROM payroll "
        "WHERE employee_id = %s ORDER BY pay_period DESC, payroll_id DESC LIMIT 24",
        (emp_id,),
    )
    for p in payslips:
        p["pay_period"] = _date(p["pay_period"])
        for key in ("gross_pay", "deductions", "net_pay"):
            p[key] = _money(p[key])

    return jsonify(
        linked=True,
        salary=_money(emp["salary"]) if emp else None,
        position=emp["position"] if emp else None,
        department=emp["department"] if emp else None,
        payslips=payslips,
    )


@my_pay_bp.post("/api/me/pay/<int:payroll_id>/confirm")
@_pay_roles_only
def confirm_my_payslip_receipt(payroll_id):
    """Allow an employee-linked admin/HR/owner account to acknowledge its own pay."""
    emp_id = _linked_employee_id()
    if emp_id is None:
        raise ApiError("No employee record is linked to this account.", 404)

    row = fetch_one(
        "SELECT hr_confirmed_at, employee_confirmed_at FROM payroll "
        "WHERE payroll_id = %s AND employee_id = %s",
        (payroll_id, emp_id),
    )
    if not row:
        raise ApiError("Payroll record not found.", 404)
    if row["hr_confirmed_at"] is None:
        raise ApiError("HR must confirm payment before you can acknowledge receipt.", 409)
    if row["employee_confirmed_at"] is not None:
        return jsonify(message="You have already confirmed receipt.")

    with db() as (_, cur):
        cur.execute(
            "UPDATE payroll SET employee_confirmed_at = CURRENT_TIMESTAMP "
            "WHERE payroll_id = %s AND employee_id = %s AND employee_confirmed_at IS NULL",
            (payroll_id, emp_id),
        )
    return jsonify(message="Receipt confirmed. Your official payslip is now available.")


@my_pay_bp.get("/me/payslips/<int:payroll_id>")
@_pay_roles_only
def my_payslip(payroll_id):
    emp_id = _linked_employee_id()
    if emp_id is None:
        raise ApiError("No employee record is linked to this account.", 404)
    return render_payslip(payroll_id, emp_id)