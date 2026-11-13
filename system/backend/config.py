import os
import secrets

APP_ENV = os.environ.get("APP_ENV", "development").strip().lower()
SECRET_KEY = os.environ.get("SECRET_KEY")

if APP_ENV == "production" and not SECRET_KEY:
    raise RuntimeError("SECRET_KEY must be set when APP_ENV=production.")

if not SECRET_KEY:
    # Development only. Set a persistent SECRET_KEY for stable local sessions.
    SECRET_KEY = secrets.token_hex(32)
    print("[warning] SECRET_KEY is not set - using a temporary development key.")

if len(SECRET_KEY) < 32:
    raise RuntimeError("SECRET_KEY must contain at least 32 characters.")

DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "biri_go")
DB_SSL = os.environ.get(
    "DB_SSL", "1" if APP_ENV == "production" else "0"
).strip() == "1"
DB_SSL_CA = os.environ.get("DB_SSL_CA", "").strip() or None

# Development keeps the existing automatic schema setup by default.
# Production must use a pre-migrated schema and a restricted application account.
DB_AUTO_INIT = os.environ.get(
    "DB_AUTO_INIT", "0" if APP_ENV == "production" else "1"
).strip() == "1"

if not 1 <= DB_PORT <= 65535:
    raise RuntimeError("DB_PORT must be between 1 and 65535.")

if APP_ENV == "production":
    if DB_USER.strip().lower() in ("root", "admin"):
        raise RuntimeError("Use a dedicated least-privilege database account in production.")
    if DB_AUTO_INIT:
        raise RuntimeError("DB_AUTO_INIT must be disabled in production.")
    if os.environ.get("FLASK_DEBUG") == "1":
        raise RuntimeError("FLASK_DEBUG must be disabled in production.")
