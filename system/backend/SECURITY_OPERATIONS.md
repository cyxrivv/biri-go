# Biri-Go security operations

This guide covers the application database account and the backup/restore utility.

## 1. Least-privilege database account

The application currently performs schema creation and upgrades in development. A production application account should not have schema-administration permissions.

1. Back up the database before changing database accounts.
2. Apply any required schema updates using a separate administrator/migration account.
3. Open system/backend/create_app_user.sql.example, replace the example password, and run its SQL as a MySQL administrator.
4. Configure the application to use the new account:

   - APP_ENV=production
   - SECRET_KEY set to a persistent random value of at least 32 characters
   - DB_USER=biri_app
   - DB_PASSWORD set to the password used in the SQL script
   - DB_NAME=biri_go
   - DB_AUTO_INIT=0

5. Restart the application and test login, employee CRUD, attendance, leave requests, HR resources, payroll, and reports.

The application account receives only SELECT, INSERT, UPDATE, and DELETE on biri_go.*. It cannot create, alter, or drop tables. Keep administrator credentials out of the application environment.

For a fresh local development database, the existing automatic setup remains enabled by default. If you need to run schema setup manually, use a development-only administrator account with DB_AUTO_INIT=1. Do not enable automatic schema initialization in production.

## 2. Create a backup

Install the MySQL command-line client tools (mysqldump and mysql) and ensure they are available on PATH.

From system/backend:

    python backup_restore.py backup

The command creates a compressed .sql.gz file in system/backend/backups. You can choose another location with --output.

The dump uses a single transaction and skips table locks. The database tables should use InnoDB for a consistent live backup. Triggers are skipped; the current Biri-Go schema does not rely on application triggers.

Backups contain employee personal information, account hashes, attendance, leave, and payroll data. Store them in a restricted folder, copy them to protected storage, and never commit them to Git.

You can also manage backups from the Admin portal: open **Backups** in the sidebar, then use **Create Backup**, **Restore**, or **Delete**. The dashboard lists each backup's filename, creation time, and size. The restore action verifies the archive in a temporary database and creates a safety backup of the live database before importing it.

For the dashboard's restore action, set DB_RESTORE_USER and DB_RESTORE_PASSWORD in the environment used to start the Flask application. Those credentials must be able to create/drop a temporary verification database and restore the dump into biri_go. Do not use the restricted biri_app account for restoration.

## 3. Verify a backup without touching the live database

Set temporary restore-administrator credentials in the shell. The account must be able to create and drop a temporary database and import the dump:

PowerShell:

    $env:DB_RESTORE_USER = "your_mysql_admin"
    $env:DB_RESTORE_PASSWORD = "your_mysql_admin_password"
    python backup_restore.py verify backups\YOUR_BACKUP.sql.gz

The verification command imports the backup into a uniquely named temporary database, confirms that tables were restored, and drops the temporary database afterward. It does not import into or modify biri_go.

Verification requires MySQL administrator permissions for temporary database creation and deletion. Always check the command's success message.

## 4. Restore a backup

Restoring is destructive: the SQL dump can drop and recreate tables in the configured database. First create a fresh backup of the current database and confirm that the selected backup is the one you intend to restore.

Set DB_RESTORE_USER and DB_RESTORE_PASSWORD to a database administrator account, then run:

    python backup_restore.py restore backups\YOUR_BACKUP.sql.gz --confirm "RESTORE BIRI-GO DATABASE"

The exact confirmation phrase is required. Do not run this against a production database unless the restore has been approved and a current pre-restore backup exists.

After restoration, restart Biri-Go and verify sign-in, employee records, attendance, leave, payroll, and reports.

## 5. Operational checklist

- Schedule backups outside Git and copy them to a separate protected location.
- Periodically run verify against a recent backup.
- Perform a full restore rehearsal in a separate test environment before relying on backups for disaster recovery.
- Keep the application account separate from migration and restore administrator accounts.
- Keep DB_AUTO_INIT=0 in production.
