# Cloud database backups (Vercel + TiDB)

Cloud backups are enabled automatically when APP_ENV=production, or locally
when CLOUD_BACKUPS_ENABLED=1. The original backup_restore.py remains the
desktop/local backup implementation.

## Required Vercel environment variables

Set these in Vercel Project Settings -> Environment Variables. Never commit
their values to Git.

- APP_ENV=production
- SECRET_KEY: at least 32 random characters.
- DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME: TiDB Cloud connection.
- DB_AUTO_INIT=0
- DB_SSL=1 (required for the TiDB Cloud Starter public endpoint).
- DB_SSL_CA is optional; the app uses the certifi CA bundle if it is omitted.
- Use the TiDB-provided prefixed username (for example, the cluster prefix plus
  .root) rather than an unprefixed username.
- CLOUD_BACKUP_ENCRYPTION_KEY: base64-encoded 32-byte random key (AES-256-GCM).
- CRON_SECRET: long random secret used to authenticate the monthly cron route.
- Connect a Private Vercel Blob store to the project. Prefer Vercel OIDC
  (BLOB_STORE_ID + platform-issued VERCEL_OIDC_TOKEN); otherwise configure
  BLOB_READ_WRITE_TOKEN.

Generate an encryption key locally:
python -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"

Keep an offline copy of CLOUD_BACKUP_ENCRYPTION_KEY. If it is lost, encrypted
backups cannot be decrypted.

## Behavior

- Manual backups and the monthly cron create AES-256-GCM encrypted,
  gzip-compressed archives in private Vercel Blob storage.
- Each upload is downloaded again and checked before it is counted as
  successful.
- The service retains the newest five verified cloud archives.
- Monthly schedule: 0 0 1 * * (00:00 UTC on the first day of each month).
- Cron endpoint: /api/cron/monthly-backup; requires Authorization: Bearer
  followed by CRON_SECRET.
- Restore first creates a safety backup, verifies checksum/authentication and
  archive format, then compares every base table's CREATE TABLE definition
  with the archive. If any table/schema differs, restore stops without
  changing live data.
- If schema matches, table rows are replaced in one DML transaction. A failed
  transaction is rolled back. The restore path never drops/recreates the TiDB
  database and never executes archived DDL.
- A TiDB advisory lock is held from pre-restore validation through the safety
  backup and restore. Normal application write requests acquire the same lock,
  so they wait briefly or receive HTTP 503 while restore is in progress.
- CLOUD_BACKUP_MAX_BYTES defaults to 64 MiB. Keep archives within the Vercel
  Function memory and execution-time limits.

## TiDB transaction limit

TiDB has a maximum transaction size. If a full restore exceeds the configured
transaction limit, TiDB rejects it and the transaction rolls back. Test using
a recent production-sized snapshot before relying on this feature.

## Deployment checklist

1. Create/connect a Private Blob store in Vercel.
2. Add the environment variables above.
3. Ensure the TiDB application user can SELECT, DELETE, INSERT, and read
   information_schema/SHOW CREATE TABLE for the configured database.
4. Deploy this branch to a Vercel Preview deployment first.
5. Test manual backup, readback verification, retention, and restore against
   a non-production TiDB database with matching schema.
6. Only then merge to main and deploy production.
