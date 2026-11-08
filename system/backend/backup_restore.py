"""Create, verify, and restore compressed MySQL backups for Biri-Go.

Run from this directory:
    python backup_restore.py backup
    python backup_restore.py verify backups/<file>.sql.gz
    python backup_restore.py restore backups/<file>.sql.gz --confirm "RESTORE BIRI-GO DATABASE"

Backups contain sensitive employee and payroll data. Keep them outside source control.
"""
import argparse
import gzip
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import config

HERE = Path(__file__).resolve().parent
BACKUP_DIR = HERE / "backups"
CONFIRM_TEXT = "RESTORE BIRI-GO DATABASE"


def _find_client(name):
    executable = shutil.which(name) or shutil.which(name + ".exe")
    if not executable:
        raise RuntimeError(
            "%s was not found. Install MySQL command-line tools and add them to PATH."
            % name
        )
    return executable


def _password_env(password):
    env = os.environ.copy()
    if password:
        env["MYSQL_PWD"] = password
    else:
        env.pop("MYSQL_PWD", None)
    return env


def _common_args(executable, user):
    return [
        executable,
        "--host=%s" % config.DB_HOST,
        "--port=%s" % config.DB_PORT,
        "--user=%s" % user,
        "--default-character-set=utf8mb4",
    ]


def create_backup(output_path=None):
    dump = _find_client("mysqldump")
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if output_path is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        output_path = BACKUP_DIR / ("biri_go_%s.sql.gz" % stamp)
    else:
        output_path = Path(output_path).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

    command = _common_args(dump, config.DB_USER) + [
        "--single-transaction",
        "--quick",
        "--skip-lock-tables",
        "--no-tablespaces",
        "--skip-triggers",
        "--set-gtid-purged=OFF",
        config.DB_NAME,
    ]

    try:
        with gzip.open(output_path, "wb", compresslevel=9) as compressed:
            result = subprocess.run(
                command,
                stdout=compressed,
                stderr=subprocess.PIPE,
                env=_password_env(config.DB_PASSWORD),
                check=False,
            )
        if result.returncode != 0:
            raise RuntimeError(
                "mysqldump failed (exit %s): %s"
                % (result.returncode, result.stderr.decode("utf-8", "replace").strip())
            )
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError("The backup file is empty.")
    except Exception:
        if output_path.exists():
            output_path.unlink()
        raise

    print("Backup created: %s" % output_path)
    print("Compressed size: %s bytes" % output_path.stat().st_size)
    return output_path


def _restore_credentials():
    user = os.environ.get("DB_RESTORE_USER", "").strip()
    password = os.environ.get("DB_RESTORE_PASSWORD", "")
    if not user:
        raise RuntimeError(
            "Set DB_RESTORE_USER and DB_RESTORE_PASSWORD to a database administrator "
            "account before verifying or restoring a backup."
        )
    return user, password


def _mysql_import_args(database=None):
    mysql = _find_client("mysql")
    user, password = _restore_credentials()
    args = _common_args(mysql, user) + ["--binary-mode=1"]
    if database:
        args.append("--database=%s" % database)
    return args, _password_env(password)


def _database_name():
    """Return a safely quoted configured database identifier."""
    name = str(config.DB_NAME)
    if not name or not name.replace("_", "").replace("$", "").isalnum():
        raise RuntimeError("DB_NAME contains unsupported characters.")
    return "`%s`" % name


def database_exists():
    """Check the target schema using the dedicated restore administrator."""
    args, env = _mysql_import_args()
    query = (
        "SELECT COUNT(*) FROM information_schema.schemata "
        "WHERE schema_name = %s" % ("'%s'" % config.DB_NAME.replace("'", "''"))
    )
    result = subprocess.run(
        args + ["--batch", "--skip-column-names", "--execute=%s" % query],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Could not check whether the target database exists: %s"
            % result.stderr.decode("utf-8", "replace").strip()
        )
    return result.stdout.decode("utf-8", "replace").strip() == "1"


def _recreate_target_database():
    """Recreate the configured schema so the restored snapshot is exact."""
    args, env = _mysql_import_args()
    database = _database_name()
    statements = (
        "DROP DATABASE IF EXISTS %s; "
        "CREATE DATABASE %s CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        % (database, database)
    )
    result = subprocess.run(
        args + ["--execute=%s" % statements],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Could not recreate the target database: %s"
            % result.stderr.decode("utf-8", "replace").strip()
        )


def _import_dump(backup_path, database):
    args, env = _mysql_import_args(database)
    with gzip.open(backup_path, "rb") as source:
        result = subprocess.run(
            args,
            stdin=source,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )
    if result.returncode != 0:
        details = result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(
            "MySQL import failed (exit %s): %s" % (result.returncode, details)
        )


def verify_backup(backup_path):
    """Import the dump into a temporary database, then remove that database."""
    backup_path = Path(backup_path).expanduser().resolve()
    if not backup_path.is_file():
        raise RuntimeError("Backup file not found: %s" % backup_path)

    stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    scratch = "biri_go_verify_%s_%s" % (stamp, os.getpid())
    args, env = _mysql_import_args()
    create_sql = (
        "CREATE DATABASE %s CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci" % scratch
    )
    drop_sql = "DROP DATABASE IF EXISTS %s" % scratch

    created = False
    try:
        result = subprocess.run(
            args + ["--execute=%s" % create_sql],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "Could not create a temporary verification database: %s"
                % result.stderr.decode("utf-8", "replace").strip()
            )
        created = True

        _import_dump(backup_path, scratch)

        result = subprocess.run(
            args + [
                "--batch",
                "--skip-column-names",
                "--execute=SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = '%s'" % scratch,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "Could not inspect the restored test database: %s"
                % result.stderr.decode("utf-8", "replace").strip()
            )
        table_count = int(result.stdout.decode("utf-8", "replace").strip() or "0")
        if table_count == 0:
            raise RuntimeError("The backup imported, but no tables were restored.")
        print(
            "Backup verification passed: imported %s table(s) into a temporary database."
            % table_count
        )
        return table_count
    finally:
        if created:
            cleanup = subprocess.run(
                args + ["--execute=%s" % drop_sql],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                check=False,
            )
            if cleanup.returncode != 0:
                print(
                    "WARNING: temporary verification database %s could not be removed."
                    % scratch,
                    file=sys.stderr,
                )


def restore_backup(backup_path, confirmation):
    if confirmation != CONFIRM_TEXT:
        raise RuntimeError(
            'Restore cancelled. Pass --confirm "%s" to confirm the destructive restore.'
            % CONFIRM_TEXT
        )
    backup_path = Path(backup_path).expanduser().resolve()
    if not backup_path.is_file():
        raise RuntimeError("Backup file not found: %s" % backup_path)

    print("Restoring %s into database %s..." % (backup_path, config.DB_NAME))
    _recreate_target_database()
    _import_dump(backup_path, config.DB_NAME)
    print("Restore command completed. Review the application and database after restoration.")


def main():
    parser = argparse.ArgumentParser(description="Biri-Go MySQL backup and restore utility")
    sub = parser.add_subparsers(dest="command", required=True)

    backup_parser = sub.add_parser("backup", help="Create a compressed SQL backup")
    backup_parser.add_argument("--output", help="Optional output .sql.gz path")

    verify_parser = sub.add_parser(
        "verify", help="Test-import a backup into a temporary database"
    )
    verify_parser.add_argument("backup_file")

    restore_parser = sub.add_parser(
        "restore", help="Restore a backup into the configured database"
    )
    restore_parser.add_argument("backup_file")
    restore_parser.add_argument("--confirm", required=True)

    args = parser.parse_args()
    try:
        if args.command == "backup":
            create_backup(args.output)
        elif args.command == "verify":
            verify_backup(args.backup_file)
        elif args.command == "restore":
            restore_backup(args.backup_file, args.confirm)
    except Exception as exc:
        print("Backup operation failed: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
