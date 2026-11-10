"""Self-service salary & payslips for HR, admin and owner accounts.

Same idea as the employee dashboard: the employee_id ALWAYS comes from the
logged-in session, never from the request, so nobody can read someone
else's pay through these endpoints.
"""
from functools import wraps

from flask import Blueprint, jsonify, session

from db import fetch_all, fetch_one
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
        "SELECT employee_id FROM account WHERE account_id = %s",
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
        "SELECT payroll_id AS id, pay_period, gross_pay, deductions, net_pay FROM payroll "
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


@my_pay_bp.get("/me/payslips/<int:payroll_id>")
@_pay_roles_only
def my_payslip(payroll_id):
    emp_id = _linked_employee_id()
    if emp_id is None:
        raise ApiError("No employee record is linked to this account.", 404)
    return render_payslip(payroll_id, emp_id)