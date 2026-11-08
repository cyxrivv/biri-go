from contextlib import contextmanager

from mysql.connector import pooling

import config

DB_CONFIG = {
    "host": config.DB_HOST,
    "port": config.DB_PORT,
    "user": config.DB_USER,
    "password": config.DB_PASSWORD,
    "database": config.DB_NAME,
}

_pool = None


def get_pool():
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="biri_pool", pool_size=15, pool_reset_session=True, **DB_CONFIG
        )
    return _pool


@contextmanager
def db():
    """Yield (connection, dict-cursor). Commits on success, rolls back on error."""
    conn = get_pool().get_connection()
    cur = conn.cursor(dictionary=True)
    try:
        yield conn, cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def fetch_all(sql, params=None):
    with db() as (_, cur):
        cur.execute(sql, params or ())
        return cur.fetchall()


def fetch_one(sql, params=None):
    with db() as (_, cur):
        cur.execute(sql, params or ())
        return cur.fetchone()


def add_column(cur, table, column, ddl):
    """ALTER TABLE ... ADD COLUMN only when it is missing. Returns True if added."""
    cur.execute(
        "SELECT 1 AS ok FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
        (table, column),
    )
    if cur.fetchone():
        return False
    cur.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, column, ddl))
    return True


# Old leave names -> the names in utils.LEAVE_ALLOWANCE
_LEAVE_RENAMES = {
    "Vacation Leave (PTO)": ("Vacation", "Annual", "Casual"),
    "Sick Leave": ("Sick",),
    "Emergency Leave": ("Emergency", "Force Leave"),
    "Unpaid Leave (LOA)": ("Other",),
}


def init_db():
    """Create/upgrade the shared tables. Safe to run on every start."""
    with db() as (_, cur):
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS activity_log (
                activity_id INT AUTO_INCREMENT PRIMARY KEY,
                message     VARCHAR(255) NOT NULL,
                created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        # Leave requests: one table for admin, HR and employees
        cur.execute("ALTER TABLE leave_requests MODIFY leave_type VARCHAR(50) NOT NULL")
        add_column(cur, "leave_requests", "reason", "TEXT NULL")
        add_column(cur, "leave_requests", "pay_status", "VARCHAR(10) NOT NULL DEFAULT 'Paid'")
        for new, olds in _LEAVE_RENAMES.items():
            marks = ", ".join(["%s"] * len(olds))
            cur.execute("UPDATE leave_requests SET leave_type = %%s WHERE leave_type IN (%s)" % marks, (new, *olds))
        # Attendance: one table for HR and employees
        add_column(cur, "attendance", "status", "VARCHAR(20) NULL")
        add_column(cur, "attendance", "remarks", "VARCHAR(255) NULL")
        add_column(cur, "attendance", "overtime_hours", "DECIMAL(5,2) NOT NULL DEFAULT 0")
        cur.execute(
            "UPDATE attendance SET status = IF(time_in IS NULL, 'Absent', "
            "IF(time_in > '08:15:00', 'Late', 'Present')) WHERE status IS NULL"
        )
                # Payroll: stores monthly employee salary records
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS payroll (
                payroll_id INT AUTO_INCREMENT PRIMARY KEY,
                employee_id INT NOT NULL,
                pay_period DATE NOT NULL,
                gross_pay DECIMAL(10,2) NOT NULL DEFAULT 0,
                deductions DECIMAL(10,2) NOT NULL DEFAULT 0,
                net_pay DECIMAL(10,2) NOT NULL DEFAULT 0,
                payment_status VARCHAR(20) NOT NULL DEFAULT 'Pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (employee_id) REFERENCES employees(employee_id),
                UNIQUE (employee_id, pay_period)
            )
            """
        )
        add_column(cur, "payroll", "payment_status", "VARCHAR(20) NOT NULL DEFAULT 'Pending'")
        add_column(cur, "payroll", "created_at", "TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP")
        add_column(cur, "payroll", "monthly_salary", "DECIMAL(10,2) NOT NULL DEFAULT 0")
        add_column(cur, "payroll", "overtime_pay", "DECIMAL(10,2) NOT NULL DEFAULT 0")
        add_column(cur, "payroll", "absence_deduction", "DECIMAL(10,2) NOT NULL DEFAULT 0")
        add_column(cur, "payroll", "unpaid_leave_deduction", "DECIMAL(10,2) NOT NULL DEFAULT 0")
        add_column(cur, "payroll", "allowances", "DECIMAL(10,2) NOT NULL DEFAULT 0")
        add_column(cur, "payroll", "manual_deductions", "DECIMAL(10,2) NOT NULL DEFAULT 0")

def log_activity(cur, message):
    cur.execute("INSERT INTO activity_log (message) VALUES (%s)", (message[:255],))