
import os
import secrets

APP_ENV = os.environ.get("APP_ENV", "development").lower()
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
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD")
DB_NAME = os.environ.get("DB_NAME", "biri_go    ")
