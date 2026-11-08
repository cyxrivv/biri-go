import re
from datetime import date, datetime
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, session

from backup_restore import BACKUP_DIR, CONFIRM_TEXT, create_backup, restore_backup, verify_backup

from auth import role_required
from db import db, fetch_all, fetch_one, log_activity
from utils import (ApiError, clean, to_int, json_body, LEAVE_ALLOWANCE,
                   purge_employee, validate_leave_request)
admin_bp = Blueprint("admin", __name__)


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
@admin_bp.get("/api/dashboard")
@role_required("admin")
def dashboard():
    stats = fetch_one(
        """
        SELECT
          (SELECT COUNT(*) FROM employees)                           AS total_employees,
          (SELECT COUNT(*) FROM employees WHERE stat = 'Active')     AS active_employees,
          (SELECT COUNT(*) FROM departments)                         AS total_departments,
          (SELECT COUNT(*) FROM positions)                           AS total_positions,
          (SELECT COUNT(*) FROM leave_requests
             WHERE leave_status = 'Pending')                         AS pending_leaves
        """
    )
    stats["recent_activity"] = fetch_all(
        "SELECT message, created_at FROM activity_log ORDER BY activity_id DESC LIMIT 10"
    )
    return jsonify(stats)


# --------------------------------------------------------------------------
# Departments
# --------------------------------------------------------------------------
@admin_bp.get("/api/departments")
@role_required("admin", "hr")
def list_departments():
    rows = fetch_all(
        """
        SELECT d.department_id AS id, d.dept_name AS name,
               d.head_employee_id,
               CONCAT(h.first_name, ' ', h.last_name) AS head,
               (SELECT COUNT(*) FROM employees e WHERE e.department_id = d.department_id) AS employees,
               (SELECT COUNT(*) FROM positions p WHERE p.department_id = d.department_id) AS positions
        FROM departments d
        LEFT JOIN employees h ON h.employee_id = d.head_employee_id
        ORDER BY d.department_id
        """
    )
    return jsonify(rows)


def build_department(data):
    name = clean(data.get("dept_name") or data.get("name"))
    if not name:
        raise ApiError("Department name is required.")
    head = to_int(data.get("head_employee_id"), "Head", required=False)
    if head is not None and not fetch_one(
        "SELECT 1 AS ok FROM employees WHERE employee_id = %s", (head,)
    ):
        raise ApiError("Selected department head doesn't exist.")
    return name, head


@admin_bp.post("/api/departments")
@role_required("admin")
def create_department():
    name, head = build_department(json_body())
    with db() as (_, cur):
        cur.execute(
            "INSERT INTO departments (dept_name, head_employee_id) VALUES (%s, %s)", (name, head)
        )
        new_id = cur.lastrowid
        log_activity(cur, f"Added department {name}")
    return jsonify(id=new_id, name=name, head_employee_id=head), 201


@admin_bp.put("/api/departments/<int:department_id>")
@role_required("admin")
def update_department(department_id):
    if not fetch_one("SELECT 1 AS ok FROM departments WHERE department_id = %s", (department_id,)):
        raise ApiError("Department not found.", 404)
    name, head = build_department(json_body())
    with db() as (_, cur):
        cur.execute(
            "UPDATE departments SET dept_name = %s, head_employee_id = %s WHERE department_id = %s",
            (name, head, department_id),
        )
        log_activity(cur, f"Updated department {name}")
    return jsonify(id=department_id, name=name, head_employee_id=head)


@admin_bp.delete("/api/departments/<int:department_id>")
@role_required("admin")
def delete_department(department_id):
    dept = fetch_one("SELECT dept_name FROM departments WHERE department_id = %s", (department_id,))
    if not dept:
        raise ApiError("Department not found.", 404)
    with db() as (_, cur):
        cur.execute("DELETE FROM departments WHERE department_id = %s", (department_id,))
        log_activity(cur, f"Deleted department {dept['dept_name']}")
    return jsonify(message="Department deleted.")


# --------------------------------------------------------------------------
# Positions
# --------------------------------------------------------------------------
@admin_bp.get("/api/positions")
@role_required("admin", "hr")
def list_positions():
    sql = """
        SELECT p.position_id AS id, p.title, p.department_id,
               d.dept_name AS department,
               (SELECT COUNT(*) FROM employees e WHERE e.position_id = p.position_id) AS employees
        FROM positions p
        JOIN departments d ON d.department_id = p.department_id
    """
    params = []
    dept = clean(request.args.get("department_id"))
    if dept:
        sql += " WHERE p.department_id = %s"
        params.append(to_int(dept, "department_id"))
    sql += " ORDER BY p.department_id, p.position_id"
    return jsonify(fetch_all(sql, params))


def build_position(data):
    title = clean(data.get("title"))
    if not title:
        raise ApiError("Position title is required.")
    department_id = to_int(data.get("department_id"), "Department")
    if not fetch_one("SELECT 1 AS ok FROM departments WHERE department_id = %s", (department_id,)):
        raise ApiError("Selected department doesn't exist.")
    return title, department_id


@admin_bp.post("/api/positions")
@role_required("admin")
def create_position():
    title, department_id = build_position(json_body())
    with db() as (_, cur):
        cur.execute(
            "INSERT INTO positions (title, department_id) VALUES (%s, %s)", (title, department_id)
        )
        new_id = cur.lastrowid
        log_activity(cur, f"Added position {title}")
    return jsonify(id=new_id, title=title, department_id=department_id), 201


@admin_bp.put("/api/positions/<int:position_id>")
@role_required("admin")
def update_position(position_id):
    if not fetch_one("SELECT 1 AS ok FROM positions WHERE position_id = %s", (position_id,)):
        raise ApiError("Position not found.", 404)
    title, department_id = build_position(json_body())
    with db() as (_, cur):
        cur.execute(
            "UPDATE positions SET title = %s, department_id = %s WHERE position_id = %s",
            (title, department_id, position_id),
        )
        log_activity(cur, f"Updated position {title}")
    return jsonify(id=position_id, title=title, department_id=department_id)


@admin_bp.delete("/api/positions/<int:position_id>")
@role_required("admin")
def delete_position(position_id):
    pos = fetch_one("SELECT title FROM positions WHERE position_id = %s", (position_id,))
    if not pos:
        raise ApiError("Position not found.", 404)
    with db() as (_, cur):
        cur.execute("DELETE FROM positions WHERE position_id = %s", (position_id,))
        log_activity(cur, f"Deleted position {pos['title']}")
    return jsonify(message="Position deleted.")

# --------------------------------------------------------------------------
# Employees (admin list / search / delete)
# --------------------------------------------------------------------------
@admin_bp.get("/api/employees")
@role_required("admin", "hr")
def list_employees():
    page = max(to_int(request.args.get("page", 1), "page", required=False) or 1, 1)
    per_page = min(max(to_int(request.args.get("per_page", 10), "per_page", required=False) or 10, 1), 500)
    search = clean(request.args.get("search"))
    status = clean(request.args.get("status"))

    where = []
    params = []
    if search:
        where.append(
            "(CONCAT_WS(' ', e.first_name, e.middle_name, e.last_name) LIKE %s "
            "OR e.email LIKE %s OR a.employee_code LIKE %s)"
        )
        like = f"%{search}%"
        params += [like, like, like]
    if status:
        where.append("e.stat = %s")
        params.append(status)
    clause = (" WHERE " + " AND ".join(where)) if where else ""

    total = fetch_one(
        "SELECT COUNT(*) AS total FROM employees e "
        "LEFT JOIN account a ON a.employee_id = e.employee_id" + clause,
        params,
    )["total"]
    pages = max((total + per_page - 1) // per_page, 1)
    page = min(page, pages)
    offset = (page - 1) * per_page

    rows = fetch_all(
        """
        SELECT e.employee_id AS id, a.employee_code,
               CONCAT_WS(' ', e.first_name, e.middle_name, e.last_name) AS name,
               d.dept_name AS department, p.title AS position,
               e.email, e.phone, e.stat AS status
        FROM employees e
        LEFT JOIN account a ON a.employee_id = e.employee_id
        LEFT JOIN departments d ON d.department_id = e.department_id
        LEFT JOIN positions p ON p.position_id = e.position_id
        """ + clause + """
        ORDER BY e.employee_id
        LIMIT %s OFFSET %s
        """,
        params + [per_page, offset],
    )

    return jsonify(items=rows, page=page, pages=pages, total=total)


@admin_bp.delete("/api/employees/<int:employee_id>")
@role_required("admin")
def delete_employee(employee_id):
    emp = fetch_one(
        "SELECT CONCAT_WS(' ', first_name, last_name) AS name FROM employees WHERE employee_id = %s",
        (employee_id,),
    )
    if not emp:
        raise ApiError("Employee not found.", 404)
    own = fetch_one("SELECT 1 AS ok FROM account WHERE account_id = %s AND employee_id = %s",
                    (session.get("account_id"), employee_id))
    if own:
        raise ApiError("You can't delete your own employee record.")
    with db() as (_, cur):
        purge_employee(cur, employee_id)
        log_activity(cur, f"Deleted employee {emp['name']}")
    return jsonify(message="Employee deleted.")


# --------------------------------------------------------------------------
# Leaves
# --------------------------------------------------------------------------
@admin_bp.get("/api/leave-types")
@role_required("admin", "hr")
def leave_types():
    return jsonify(list(LEAVE_ALLOWANCE.keys()))


@admin_bp.get("/api/leaves")
@role_required("admin", "hr")
def list_leaves():
    status = clean(request.args.get("status"))
    where, params = "", []
    if status:
        where = " WHERE l.leave_status = %s"
        params.append(status)

    rows = fetch_all(
        """
        SELECT l.leave_id AS id,
               CONCAT_WS(' ', e.first_name, e.last_name) AS employee,
               d.dept_name AS department,
               l.leave_type, l.start_date, l.end_date,
               DATEDIFF(l.end_date, l.start_date) + 1 AS days,
               l.leave_status AS status
        FROM leave_requests l
        JOIN employees e ON e.employee_id = l.employee_id
        LEFT JOIN departments d ON d.department_id = e.department_id
        """ + where + """
        ORDER BY l.start_date DESC, l.leave_id DESC
        """,
        params,
    )
    for r in rows:
        r["start_date"] = str(r["start_date"])[:10]
        r["end_date"] = str(r["end_date"])[:10]
    return jsonify(rows)


@admin_bp.post("/api/leaves")
@role_required("admin", "hr")
def create_leave():
    data = json_body()
    employee_id = to_int(data.get("employee_id"), "Employee")
    leave_type = clean(data.get("leave_type"))
    try:
        start = date.fromisoformat(clean(data.get("start_date")))
        end = date.fromisoformat(clean(data.get("end_date")))
    except (TypeError, ValueError):
        raise ApiError("Enter valid start and end dates.")
    validate_leave_request(employee_id, leave_type, start, end)

    with db() as (_, cur):
        cur.execute(
            "INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, leave_status) "
            "VALUES (%s, %s, %s, %s, 'Pending')",
            (employee_id, leave_type, start, end),
        )
        new_id = cur.lastrowid
        log_activity(cur, f"Filed {leave_type} leave for employee #{employee_id}")
    return jsonify(id=new_id, message="Leave filed."), 201


@admin_bp.put("/api/leaves/<int:leave_id>/status")
@role_required("admin", "hr")
def update_leave_status(leave_id):
    leave = fetch_one(
        "SELECT employee_id, leave_type, start_date, end_date, leave_status "
        "FROM leave_requests WHERE leave_id = %s",
        (leave_id,),
    )
    if not leave:
        raise ApiError("Leave request not found.", 404)

    status = clean(json_body().get("status"))
    if status not in ("Pending", "Approved", "Rejected"):
        raise ApiError("Status must be Pending, Approved or Rejected.")

    if status == "Approved":
        validate_leave_request(leave["employee_id"], leave["leave_type"], leave["start_date"],
                               leave["end_date"], exclude_id=leave_id, status="Approved")

    with db() as (_, cur):
        cur.execute(
            "UPDATE leave_requests SET leave_status = %s WHERE leave_id = %s", (status, leave_id)
        )
        log_activity(cur, f"Leave #{leave_id} marked {status}")
    return jsonify(id=leave_id, status=status)


@admin_bp.delete("/api/leaves/<int:leave_id>")
@role_required("admin", "hr")
def delete_leave(leave_id):
    if not fetch_one("SELECT 1 AS ok FROM leave_requests WHERE leave_id = %s", (leave_id,)):
        raise ApiError("Leave request not found.", 404)
    with db() as (_, cur):
        cur.execute("DELETE FROM leave_requests WHERE leave_id = %s", (leave_id,))
        log_activity(cur, f"Deleted leave request #{leave_id}")
    return jsonify(message="Leave request deleted.")

# --------------------------------------------------------------------------
# Database backups (administrator only)
# --------------------------------------------------------------------------
_BACKUP_NAME_RE = re.compile(r"^biri_go_\d{8}_\d{6}_\d{6}\.sql\.gz$")


def _backup_file(filename):
    if not isinstance(filename, str) or not _BACKUP_NAME_RE.fullmatch(filename):
        raise ApiError("Invalid backup filename.", 400)
    root = BACKUP_DIR.resolve()
    path = (root / filename).resolve()
    if path.parent != root or not path.is_file():
        raise ApiError("Backup file not found.", 404)
    return path


@admin_bp.get("/api/admin/backups")
@role_required("admin")
def list_backups():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    items = []
    for path in BACKUP_DIR.iterdir():
        if not path.is_file() or not _BACKUP_NAME_RE.fullmatch(path.name):
            continue
        stat = path.stat()
        items.append({
            "filename": path.name,
            "size": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        })
    items.sort(key=lambda item: item["created_at"], reverse=True)
    return jsonify(items=items)


@admin_bp.post("/api/admin/backups")
@role_required("admin")
def create_admin_backup():
    try:
        path = create_backup()
    except Exception:
        current_app.logger.exception("Admin database backup failed")
        raise ApiError(
            "Could not create a database backup. Check the MySQL client tools and database permissions.",
            500,
        )
    return jsonify(
        message="Backup created successfully.",
        backup={"filename": path.name, "size": path.stat().st_size},
    ), 201


@admin_bp.delete("/api/admin/backups/<filename>")
@role_required("admin")
def delete_admin_backup(filename):
    path = _backup_file(filename)
    try:
        path.unlink()
    except OSError:
        current_app.logger.exception("Admin could not delete backup %s", filename)
        raise ApiError("Could not delete the selected backup.", 500)
    return jsonify(message="Backup deleted.")


@admin_bp.post("/api/admin/backups/<filename>/restore")
@role_required("admin")
def restore_admin_backup(filename):
    path = _backup_file(filename)
    try:
        # Prove the archive can be imported before touching the live database.
        verify_backup(path)
        # Keep a safety copy of the current live database before the restore.
        safety_backup = create_backup()
        restore_backup(path, CONFIRM_TEXT)
    except Exception:
        current_app.logger.exception("Admin database restore failed for %s", filename)
        raise ApiError(
            "Restore did not complete. A safety backup may have been created; "
            "inspect the database and server logs before retrying.",
            500,
        )
    return jsonify(
        message="Database restored successfully.",
        safety_backup=safety_backup.name,
    )
