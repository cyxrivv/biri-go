import base64
import gzip
import json
import os
import re
from decimal import Decimal

from flask import Blueprint, current_app, jsonify, request, send_from_directory, session

from auth import role_required
from db import db, fetch_all, fetch_one, log_activity
from utils import (ApiError, clean, to_int, json_body, LEAVE_ALLOWANCE,
                   purge_employee, validate_leave_request)
from datetime import date, datetime, timedelta

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
# Backup & restore (pure Python, uses the app's own DB connection:
# no mysqldump / PATH setup needed). Backups are plain .sql files.
# --------------------------------------------------------------------------
BACKUP_HEADER = "-- Biri-Go SQL backup"
STMT_SEP = "\n-- @@\n"  # a SQL comment, so the file stays valid for the mysql CLI
BACKUP_NAME_RE = re.compile(r"^biri_go_\d{8}_\d{6}(_prerestore)?\.sql$")
MAX_BACKUPS = 30  # newest N are kept, older ones are removed automatically
INSERT_BATCH = 100


def backup_dir():
    path = current_app.config.get("BACKUP_DIR") or os.path.join(current_app.root_path, "backups")
    os.makedirs(path, exist_ok=True)
    return path


def valid_backup(name):
    return bool(BACKUP_NAME_RE.match(name)) and os.path.isfile(os.path.join(backup_dir(), name))


def _human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _q(name):
    return "`" + str(name).replace("`", "``") + "`"


def _lit(v):
    """Convert a Python/DB value into a MySQL SQL literal (always a single line)."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float, Decimal)):
        return str(v)
    if isinstance(v, (bytes, bytearray)):
        return "X'" + bytes(v).hex() + "'"
    if isinstance(v, datetime):
        v = v.isoformat(sep=" ")
    elif isinstance(v, date):
        v = v.isoformat()
    elif isinstance(v, timedelta):  # MySQL TIME
        secs = int(v.total_seconds())
        sign = "-" if secs < 0 else ""
        secs = abs(secs)
        v = f"{sign}{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}"
    s = (str(v).replace("\\", "\\\\").replace("'", "''")
         .replace("\0", "\\0").replace("\n", "\\n")
         .replace("\r", "\\r").replace("\x1a", "\\Z"))
    return "'" + s + "'"


def write_dump(f):
    def emit(stmt):
        f.write(stmt.rstrip().rstrip(";") + ";" + STMT_SEP)

    f.write(BACKUP_HEADER + "\n")
    f.write("-- Created: " + datetime.now().isoformat(timespec="seconds") + STMT_SEP)
    emit("SET NAMES utf8mb4")
    emit("SET FOREIGN_KEY_CHECKS = 0")

    names = [list(r.values())[0] for r in
             fetch_all("SHOW FULL TABLES WHERE Table_type = 'BASE TABLE'")]
    for t in names:
        create = list(fetch_one("SHOW CREATE TABLE " + _q(t)).values())[1]
        emit("DROP TABLE IF EXISTS " + _q(t))
        emit(create)
        rows = fetch_all("SELECT * FROM " + _q(t))
        if not rows:
            continue
        cols = list(rows[0].keys())
        head = "INSERT INTO " + _q(t) + " (" + ", ".join(_q(c) for c in cols) + ") VALUES\n"
        for i in range(0, len(rows), INSERT_BATCH):
            chunk = rows[i:i + INSERT_BATCH]
            values = ",\n".join("(" + ", ".join(_lit(r[c]) for c in cols) + ")" for r in chunk)
            emit(head + values)

    emit("SET FOREIGN_KEY_CHECKS = 1")


def create_backup(tag=""):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"biri_go_{stamp}{('_' + tag) if tag else ''}.sql"
    target = os.path.join(backup_dir(), name)
    try:
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            write_dump(f)
    except Exception:
        if os.path.exists(target):
            os.remove(target)  # never leave a broken file behind
        raise
    for old in list_backup_files()[MAX_BACKUPS:]:
        os.remove(os.path.join(backup_dir(), old["name"]))
    return name


def list_backup_files():
    items = []
    for name in os.listdir(backup_dir()):
        if BACKUP_NAME_RE.match(name):
            st = os.stat(os.path.join(backup_dir(), name))
            items.append({
                "name": name,
                "type": "Pre-restore" if "_prerestore" in name else "Manual",
                "created": datetime.fromtimestamp(st.st_mtime).strftime("%b %d, %Y %I:%M %p"),
                "size": _human_size(st.st_size),
                "_mtime": st.st_mtime,
            })
    items.sort(key=lambda x: x["_mtime"], reverse=True)
    for i in items:
        del i["_mtime"]
    return items


def restore_dump(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        text = f.read().replace("\r\n", "\n")
    if not text.startswith(BACKUP_HEADER):
        raise ApiError("This file is not a valid Biri-Go backup.")

    statements = []
    for chunk in text.split(STMT_SEP):
        chunk = chunk.strip()
        if not chunk or all(line.startswith("--") for line in chunk.splitlines()):
            continue  # header / comment-only chunk
        statements.append(chunk.rstrip(";"))

    with db() as (_, cur):
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")
        try:
            for stmt in statements:
                cur.execute(stmt)
        finally:
            cur.execute("SET FOREIGN_KEY_CHECKS = 1")

@admin_bp.get("/api/backups")
@role_required("admin")
def list_backups():
    return jsonify(list_backup_files())


@admin_bp.post("/api/backups")
@role_required("admin")
def create_backup_route():
    try:
        name = create_backup()
    except Exception as exc:
        current_app.logger.exception("Backup failed")
        raise ApiError(f"Backup failed: {exc}", 500)
    with db() as (_, cur):
        log_activity(cur, f"Created backup {name}")
    return jsonify(name=name, message="Backup created."), 201


@admin_bp.get("/api/backups/<name>/download")
@role_required("admin")
def download_backup(name):
    if not valid_backup(name):
        raise ApiError("Backup not found.", 404)
    return send_from_directory(backup_dir(), name, as_attachment=True)


@admin_bp.delete("/api/backups/<name>")
@role_required("admin")
def delete_backup(name):
    if not valid_backup(name):
        raise ApiError("Backup not found.", 404)
    os.remove(os.path.join(backup_dir(), name))
    with db() as (_, cur):
        log_activity(cur, f"Deleted backup {name}")
    return jsonify(message="Backup deleted.")


@admin_bp.post("/api/backups/<name>/restore")
@role_required("admin")
def restore_backup(name):
    if not valid_backup(name):
        raise ApiError("Backup not found.", 404)
    if clean(json_body().get("confirm")) != "RESTORE":
        raise ApiError("Type RESTORE to confirm.")
    safety = create_backup(tag="prerestore")  # safety net before overwriting anything
    try:
        restore_dump(os.path.join(backup_dir(), name))
    except ApiError:
        raise
    except Exception as exc:
        current_app.logger.exception("Restore failed")
        raise ApiError(f"Restore failed: {exc}. Your data before the restore is saved in {safety}.", 500)
    with db() as (_, cur):
        log_activity(cur, f"Restored database from {name}")
    return jsonify(message="Database restored.", safety_backup=safety)
