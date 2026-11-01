from flask import Blueprint, jsonify

from auth import role_required
from db import db, fetch_all, fetch_one, log_activity
from utils import ApiError, to_money, json_body, get_employee

owner_bp = Blueprint("owner", __name__)


# --------------------------------------------------------------------------
# Salaries
# --------------------------------------------------------------------------
@owner_bp.get("/api/salaries")
@role_required("admin", "owner")
def list_salaries():
    items = fetch_all(
        """
        SELECT e.employee_id AS id,
               CONCAT(e.first_name, ' ', e.last_name) AS name,
               d.dept_name AS department, p.title AS position,
               e.stat AS status, e.salary
        FROM employees e
        LEFT JOIN departments d ON d.department_id = e.department_id
        LEFT JOIN positions   p ON p.position_id   = e.position_id
        ORDER BY e.employee_id
        """
    )
    summary = fetch_one(
        """
        SELECT COALESCE(SUM(salary), 0) AS total_monthly,
               COALESCE(ROUND(AVG(salary), 2), 0) AS average,
               COALESCE(MAX(salary), 0) AS highest
        FROM employees WHERE stat = 'Active'
        """
    )
    return jsonify(items=items, summary=summary)


# NOTE: "admin" is allowed here only because the current admin page may edit
# salaries. Once the owner page exists, change this to @role_required("owner").
@owner_bp.put("/api/salaries/<int:employee_id>")
@role_required("admin", "owner")
def update_salary(employee_id):
    emp = get_employee(employee_id)
    if not emp:
        raise ApiError("Employee not found.", 404)
    salary = to_money(json_body().get("salary"), "Salary", required=True)
    with db() as (_, cur):
        cur.execute("UPDATE employees SET salary = %s WHERE employee_id = %s", (salary, employee_id))
        log_activity(cur, f"Updated salary of {emp['name']}")
    return jsonify(id=employee_id, salary=salary)


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------
@owner_bp.get("/api/reports")
@role_required("admin", "owner")
def reports():
    return jsonify(
        headcount_by_department=fetch_all(
            """
            SELECT d.dept_name AS department,
                   COUNT(e.employee_id) AS total,
                   COUNT(CASE WHEN e.stat = 'Active' THEN 1 END) AS active
            FROM departments d
            LEFT JOIN employees e ON e.department_id = d.department_id
            GROUP BY d.department_id, d.dept_name
            ORDER BY d.department_id
            """
        ),
        status_breakdown=fetch_all(
            "SELECT stat AS status, COUNT(*) AS total FROM employees GROUP BY stat ORDER BY total DESC"
        ),
        leave_summary=fetch_all(
            "SELECT leave_status AS status, COUNT(*) AS total FROM leave_requests "
            "GROUP BY leave_status ORDER BY total DESC"
        ),
        salary_by_department=fetch_all(
            """
            SELECT d.dept_name AS department,
                   COALESCE(ROUND(AVG(e.salary), 2), 0) AS average,
                   COALESCE(SUM(e.salary), 0) AS total
            FROM departments d
            LEFT JOIN employees e ON e.department_id = d.department_id AND e.stat = 'Active'
            GROUP BY d.department_id, d.dept_name
            ORDER BY d.department_id
            """
        ),
    )