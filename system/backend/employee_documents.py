"""Employee documents. Put in system/backend/routes/employee_documents.py

See the paste guide. Register in main.py:
       from routes.employee_documents import docs_bp
       app.register_blueprint(docs_bp)
"""
import os
import uuid

from flask import Blueprint, jsonify, request, send_from_directory, session, abort
from werkzeug.utils import secure_filename

from db import db  # same helper used elsewhere: `with db() as (conn, cur):`

docs_bp = Blueprint("employee_documents", __name__)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS employee_documents (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    employee_id   INT NOT NULL,
    title         VARCHAR(150) NOT NULL,
    category      VARCHAR(50)  NOT NULL,
    original_name VARCHAR(255) NOT NULL,
    stored_name   VARCHAR(255) NOT NULL,
    mime_type     VARCHAR(100) NOT NULL,
    size_bytes    INT NOT NULL,
    uploaded_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_docs_employee (employee_id)
);
"""


def init_documents_table():
    """Create the employee_documents table if it doesn't exist yet."""
    with db() as (conn, cur):
        cur.execute(CREATE_TABLE_SQL)
        conn.commit()

UPLOAD_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads", "employee_documents")
ALLOWED = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
}
CATEGORIES = {"Government ID", "Contract", "Certificate", "Medical", "Other"}
MAX_BYTES = 5 * 1024 * 1024


def current_employee_id():
    acc = session.get("account_id")
    if not acc:
        return None
    with db() as (_, cur):
        cur.execute("SELECT employee_id FROM account WHERE account_id = %s", (acc,))
        row = cur.fetchone()
    return row["employee_id"] if row else None


def _folder(emp_id):
    path = os.path.join(UPLOAD_ROOT, str(emp_id))
    os.makedirs(path, exist_ok=True)
    return path


def _as_dicts(cur, rows):
    return list(rows)  # db() already returns dict rows


def _get_doc(emp_id, doc_id):
    with db() as (_, cur):
        cur.execute("SELECT * FROM employee_documents WHERE id=%s AND employee_id=%s", (doc_id, emp_id))
        rows = _as_dicts(cur, cur.fetchall())
    return rows[0] if rows else None


@docs_bp.get("/api/employee/documents")
def list_documents():
    emp_id = current_employee_id()
    if not emp_id:
        return jsonify(error="Not signed in"), 401
    with db() as (_, cur):
        cur.execute(
            "SELECT id, title, category, original_name, size_bytes, uploaded_at "
            "FROM employee_documents WHERE employee_id=%s ORDER BY uploaded_at DESC, id DESC",
            (emp_id,),
        )
        rows = _as_dicts(cur, cur.fetchall())
    for r in rows:
        r["uploaded_at"] = r["uploaded_at"].strftime("%Y-%m-%d") if r["uploaded_at"] else ""
    return jsonify(documents=rows)


@docs_bp.post("/api/employee/documents")
def upload_document():
    emp_id = current_employee_id()
    if not emp_id:
        return jsonify(error="Not signed in"), 401

    title = (request.form.get("title") or "").strip()
    category = (request.form.get("category") or "").strip()
    file = request.files.get("file")

    if not title or len(title) > 150:
        return jsonify(error="Please enter a title (up to 150 characters)."), 400
    if category not in CATEGORIES:
        return jsonify(error="Invalid category."), 400
    if not file or not file.filename:
        return jsonify(error="Please choose a file."), 400

    original = secure_filename(file.filename)
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in ALLOWED:
        return jsonify(error="Only PDF, Word, JPG or PNG files are allowed."), 400

    data = file.read()
    if len(data) > MAX_BYTES:
        return jsonify(error="The file is too large (maximum 5 MB)."), 400
    if not data:
        return jsonify(error="The file is empty."), 400

    stored = f"{uuid.uuid4().hex}.{ext}"
    with open(os.path.join(_folder(emp_id), stored), "wb") as fh:
        fh.write(data)

    with db() as (conn, cur):
        cur.execute(
            "INSERT INTO employee_documents (employee_id, title, category, original_name, stored_name, mime_type, size_bytes) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (emp_id, title, category, original, stored, ALLOWED[ext], len(data)),
        )
        conn.commit()
    return jsonify(message="Document uploaded."), 201


@docs_bp.get("/employee/documents/<int:doc_id>/view")
def view_document(doc_id):
    return _send(doc_id, as_attachment=False)


@docs_bp.get("/employee/documents/<int:doc_id>/download")
def download_document(doc_id):
    return _send(doc_id, as_attachment=True)


def _send(doc_id, as_attachment):
    emp_id = current_employee_id()
    if not emp_id:
        abort(401)
    doc = _get_doc(emp_id, doc_id)  # only the owner can open a file
    if not doc:
        abort(404)
    return send_from_directory(
        _folder(emp_id),
        doc["stored_name"],
        mimetype=doc["mime_type"],
        as_attachment=as_attachment,
        download_name=doc["original_name"],
    )


@docs_bp.delete("/api/employee/documents/<int:doc_id>")
def delete_document(doc_id):
    emp_id = current_employee_id()
    if not emp_id:
        return jsonify(error="Not signed in"), 401
    doc = _get_doc(emp_id, doc_id)
    if not doc:
        return jsonify(error="Document not found."), 404
    with db() as (conn, cur):
        cur.execute("DELETE FROM employee_documents WHERE id=%s AND employee_id=%s", (doc_id, emp_id))
        conn.commit()
    try:
        os.remove(os.path.join(_folder(emp_id), doc["stored_name"]))
    except OSError:
        pass
    return jsonify(message="Document deleted.")