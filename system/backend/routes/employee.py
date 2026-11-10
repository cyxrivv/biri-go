from datetime import date, datetime, time, timedelta
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

import mysql.connector
from flask import Blueprint, jsonify, render_template, request, session, send_file
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

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
        "SELECT payroll_id AS id, pay_period, gross_pay, deductions, net_pay, "
        "payment_status, (hr_confirmed_at IS NOT NULL) AS hr_confirmed, "
        "(employee_confirmed_at IS NOT NULL) AS employee_confirmed FROM payroll "
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



@employee_bp.post("/api/employee/payslips/<int:payroll_id>/confirm")
@role_required("employee")
def confirm_payslip_receipt(payroll_id):
    """Let an employee acknowledge receipt after HR has confirmed payment."""
    employee_id = _current_employee_id()
    with db() as (conn, cur):
        cur.execute(
            "SELECT hr_confirmed_at, employee_confirmed_at FROM payroll "
            "WHERE payroll_id = %s AND employee_id = %s",
            (payroll_id, employee_id),
        )
        row = cur.fetchone()
        if not row:
            raise ApiError("Payroll record not found.", 404)
        if row.get("hr_confirmed_at") is None:
            raise ApiError("HR must confirm payment before you can acknowledge receipt.", 409)
        if row.get("employee_confirmed_at") is not None:
            return jsonify(message="You have already confirmed receipt.")

        cur.execute(
            "UPDATE payroll SET employee_confirmed_at = CURRENT_TIMESTAMP "
            "WHERE payroll_id = %s AND employee_id = %s AND employee_confirmed_at IS NULL",
            (payroll_id, employee_id),
        )
        log_activity(cur, "Employee #%s confirmed receipt of payroll #%s" % (employee_id, payroll_id))

    return jsonify(message="Receipt confirmed. Your official payslip is now available.")

def render_payslip(payroll_id, employee_id):
    """Create a PDF payslip for the logged-in employee's own confirmed payroll row."""
    row = fetch_one(
        """
        SELECT p.pay_period, p.monthly_salary, p.overtime_pay, p.absence_deduction,
               p.unpaid_leave_deduction, p.allowances, p.manual_deductions,
               p.gross_pay, p.deductions, p.net_pay,
               p.hr_confirmed_at, p.employee_confirmed_at,
               a.employee_code, e.first_name, e.middle_name, e.last_name, e.suffix,
               d.dept_name AS department, pos.title AS position
        FROM payroll p
        JOIN employees e ON e.employee_id = p.employee_id
        LEFT JOIN account a ON a.employee_id = e.employee_id
        LEFT JOIN departments d ON d.department_id = e.department_id
        LEFT JOIN positions pos ON pos.position_id = e.position_id
        WHERE p.payroll_id = %s AND p.employee_id = %s
        LIMIT 1
        """,
        (payroll_id, employee_id),
    )
    if not row:
        raise ApiError("Payslip not found.", 404)
    if row.get("hr_confirmed_at") is None or row.get("employee_confirmed_at") is None:
        raise ApiError(
            "The official payslip is available after HR confirms payment and you acknowledge receipt.",
            403,
        )

    def money(value):
        return "PHP " + format(float(value or 0), ",.2f")

    def date_label(value):
        if not value:
            return "-"
        return value.strftime("%b %d, %Y %I:%M %p") if hasattr(value, "strftime") else str(value)

    period_value = row["pay_period"]
    period = period_value.strftime("%B %Y") if hasattr(period_value, "strftime") else str(period_value)
    period_code = period_value.strftime("%Y-%m") if hasattr(period_value, "strftime") else str(period_value)[:7]
    employee_name = " ".join(
        part for part in (
            row.get("first_name"), row.get("middle_name"), row.get("last_name"), row.get("suffix")
        ) if part and str(part).lower() != "none"
    )
    employee_code = "".join(
        char for char in str(row.get("employee_code") or employee_id)
        if char.isalnum() or char in "-_"
    )
    filename = "payslip-%s-%s.pdf" % (employee_code or employee_id, period_code)

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="PayslipBrand", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=19, leading=23, textColor=colors.HexColor("#17365D"),
        alignment=TA_CENTER, spaceAfter=3,
    ))
    styles.add(ParagraphStyle(
        name="PayslipSub", parent=styles["Normal"], fontSize=10,
        textColor=colors.HexColor("#586579"), alignment=TA_CENTER, spaceAfter=14,
    ))
    styles.add(ParagraphStyle(
        name="PayslipSection", parent=styles["Heading2"], fontSize=11,
        leading=14, textColor=colors.HexColor("#17365D"), spaceBefore=12, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="PayslipSmall", parent=styles["Normal"], fontSize=8,
        leading=11, textColor=colors.HexColor("#586579"),
    ))

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer, pagesize=A4, rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=17 * mm, bottomMargin=17 * mm,
        title="Payslip - %s - %s" % (employee_name or employee_code, period),
        author="Biri-Go Employee Management System",
    )
    story = [
        Paragraph("BIRI-GO", styles["PayslipBrand"]),
        Paragraph("EMPLOYEE PAYSLIP", styles["PayslipSub"]),
        Paragraph(escape(period), styles["Heading1"]),
        Spacer(1, 5),
    ]

    employee_details = [
        [Paragraph("<b>Employee name</b>", styles["Normal"]),
         Paragraph(escape(employee_name or "-"), styles["Normal"])],
        [Paragraph("<b>Employee ID</b>", styles["Normal"]),
         Paragraph(escape(str(row.get("employee_code") or employee_id)), styles["Normal"])],
        [Paragraph("<b>Department</b>", styles["Normal"]),
         Paragraph(escape(str(row.get("department") or "-")), styles["Normal"])],
        [Paragraph("<b>Position</b>", styles["Normal"]),
         Paragraph(escape(str(row.get("position") or "-")), styles["Normal"])],
    ]
    story.append(Table(employee_details, colWidths=[42 * mm, 125 * mm], style=TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F1F5F9")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8E0EA")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D8E0EA")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ])))

    def amount_table(items):
        rows = [[Paragraph("<b>Description</b>", styles["Normal"]),
                 Paragraph("<b>Amount</b>", styles["Normal"])]]
        rows.extend([
            [Paragraph(escape(label), styles["Normal"]),
             Paragraph(escape(money(row[key])), styles["Normal"])]
            for label, key in items
        ])
        return Table(rows, colWidths=[125 * mm, 42 * mm], style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF0F7")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#17365D")),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#AAB8C8")),
            ("LINEBELOW", (0, 1), (-1, -1), 0.35, colors.HexColor("#E1E7EF")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))

    story.append(Paragraph("Earnings", styles["PayslipSection"]))
    story.append(amount_table([
        ("Basic monthly salary", "monthly_salary"),
        ("Overtime pay", "overtime_pay"),
        ("Allowances", "allowances"),
        ("Gross pay", "gross_pay"),
    ]))
    story.append(Paragraph("Deductions", styles["PayslipSection"]))
    story.append(amount_table([
        ("Absence deduction", "absence_deduction"),
        ("Unpaid leave deduction", "unpaid_leave_deduction"),
        ("Other deductions", "manual_deductions"),
        ("Total deductions", "deductions"),
    ]))

    net_table = Table(
        [[Paragraph("<b>NET PAY</b>", styles["Normal"]),
          Paragraph("<b>%s</b>" % escape(money(row["net_pay"])), styles["Normal"])]],
        colWidths=[125 * mm, 42 * mm],
        style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#E8F3EC")),
            ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#17643A")),
            ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#A7CFB4")),
            ("ALIGN", (1, 0), (1, 0), "RIGHT"),
            ("LEFTPADDING", (0, 0), (-1, -1), 9),
            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]),
    )
    story.extend([Spacer(1, 12), net_table, Paragraph("Payment confirmation", styles["PayslipSection"])])
    confirmation_rows = [
        ["HR confirmed payment", date_label(row.get("hr_confirmed_at"))],
        ["Employee confirmed receipt", date_label(row.get("employee_confirmed_at"))],
    ]
    story.append(Table(confirmation_rows, colWidths=[75 * mm, 92 * mm], style=TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F1F5F9")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D8E0EA")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D8E0EA")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ])))
    story.extend([
        Spacer(1, 12),
        Paragraph(
            "This document was generated by Biri-Go. Please contact HR if you have questions about this payslip.",
            styles["PayslipSmall"],
        ),
    ])
    document.build(story)
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=request.args.get("download") == "1",
        download_name=filename,
        conditional=False,
    )


@employee_bp.get("/employee/payslips/<int:payroll_id>")
@role_required("employee")
def payslip(payroll_id):
    return render_payslip(payroll_id, _current_employee_id())