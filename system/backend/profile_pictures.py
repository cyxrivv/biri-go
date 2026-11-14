"""Profile pictures for every account (admin, HR, owner, employee).

Desktop builds keep profile pictures on disk. Vercel deployments use private
Vercel Blob storage because the function filesystem is read-only and ephemeral.
"""
import io
import os
import sys
import uuid
from urllib.parse import quote

from flask import Blueprint, Response, abort, jsonify, request, session
from PIL import Image, ImageOps, UnidentifiedImageError

from db import db
from utils import ApiError

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
AVATAR_SIZE = 256
DEFAULT_AVATAR_URL = "/statistics/images/default-avatar.png"
BLOB_PREFIX = "profile-pictures/"
Image.MAX_IMAGE_PIXELS = 30_000_000


def _is_vercel_runtime():
    return os.environ.get("VERCEL") == "1" or bool(os.environ.get("VERCEL_ENV"))


def _upload_dir():
    # Packaged .exe: keep pictures next to the executable.
    if getattr(sys, "frozen", False):
        base = os.path.join(os.path.dirname(sys.executable), "uploads", "profile_pics")
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        base = os.path.join(here, "..", "statistics", "uploads", "profile_pics")
    base = os.path.abspath(base)
    os.makedirs(base, exist_ok=True)
    return base


# Never create directories in Vercel's read-only /var/task filesystem.
UPLOAD_DIR = None if _is_vercel_runtime() else _upload_dir()


def _blob():
    if not (os.getenv("BLOB_READ_WRITE_TOKEN") or
            (os.getenv("VERCEL_OIDC_TOKEN") and os.getenv("BLOB_STORE_ID"))):
        raise RuntimeError("Private Vercel Blob storage is not connected to this project.")
    try:
        from vercel.blob import sync as blob
    except ImportError as exc:
        raise RuntimeError("Install the Vercel Python SDK (vercel>=0.5.0).") from exc
    return blob


def _require_login():
    account_id = session.get("account_id")
    if not account_id:
        raise ApiError("Please sign in.", 401)
    return account_id


def _url_for(filename):
    if not filename:
        return DEFAULT_AVATAR_URL
    return "/profile-pictures/" + quote(str(filename), safe="/")


def _delete_file(filename):
    if not filename:
        return
    if _is_vercel_runtime():
        # Blob deletion is idempotent; ignore cleanup errors after DB changes.
        try:
            if str(filename).startswith(BLOB_PREFIX):
                _blob().delete_blob(filename)
        except Exception:
            pass
        return

    path = os.path.join(UPLOAD_DIR, os.path.basename(filename))
    try:
        os.remove(path)
    except OSError:
        pass


def _process_image(file_storage, account_id):
    """Validate and normalize an uploaded image, then persist it."""
    raw = file_storage.read(MAX_UPLOAD_BYTES + 1)
    if not raw:
        raise ApiError("No file selected.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ApiError("Image is too large (max 2 MB).")

    try:
        img = Image.open(io.BytesIO(raw))
        if img.format not in ALLOWED_FORMATS:
            raise ApiError("Only PNG, JPG or WEBP images are allowed.")
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        img = ImageOps.fit(img, (AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ApiError("That file is not a valid image.")

    output = io.BytesIO()
    img.save(output, "JPEG", quality=85)
    image_bytes = output.getvalue()
    unique_name = "%s_%s.jpg" % (account_id, uuid.uuid4().hex)

    if _is_vercel_runtime():
        pathname = BLOB_PREFIX + str(account_id) + "/" + unique_name
        uploaded = _blob().put_blob(
            pathname,
            image_bytes,
            access="private",
            content_type="image/jpeg",
            add_random_suffix=False,
        )
        return uploaded.pathname

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with open(os.path.join(UPLOAD_DIR, unique_name), "wb") as image_file:
        image_file.write(image_bytes)
    return unique_name


profile_bp = Blueprint("profile", __name__)


@profile_bp.route("/account/profile-picture", methods=["GET"])
def get_profile_picture():
    """URL of the logged-in account's picture (or the default avatar)."""
    account_id = _require_login()
    with db() as (conn, cur):
        cur.execute("SELECT profile_picture FROM account WHERE account_id = %s", (account_id,))
        row = cur.fetchone()
    if not row:
        raise ApiError("Account not found.", 404)
    return jsonify(url=_url_for(row["profile_picture"]))


@profile_bp.route("/account/profile-picture", methods=["POST"])
def upload_profile_picture():
    account_id = _require_login()
    file = request.files.get("picture")
    if not file or not file.filename:
        raise ApiError("No file selected.")

    new_name = _process_image(file, account_id)
    try:
        with db() as (conn, cur):
            cur.execute("SELECT profile_picture FROM account WHERE account_id = %s", (account_id,))
            row = cur.fetchone()
            if not row:
                raise ApiError("Account not found.", 404)
            old_name = row["profile_picture"]
            cur.execute(
                "UPDATE account SET profile_picture = %s WHERE account_id = %s",
                (new_name, account_id),
            )
    except Exception:
        _delete_file(new_name)
        raise

    _delete_file(old_name)
    return jsonify(url=_url_for(new_name), message="Profile picture updated.")


@profile_bp.route("/account/profile-picture", methods=["DELETE"])
def remove_profile_picture():
    account_id = _require_login()
    with db() as (conn, cur):
        cur.execute("SELECT profile_picture FROM account WHERE account_id = %s", (account_id,))
        row = cur.fetchone()
        if not row:
            raise ApiError("Account not found.", 404)
        cur.execute("UPDATE account SET profile_picture = NULL WHERE account_id = %s", (account_id,))
    _delete_file(row["profile_picture"])
    return jsonify(url=DEFAULT_AVATAR_URL, message="Profile picture removed.")


@profile_bp.route("/profile-pictures/<path:filename>")
def serve_profile_picture(filename):
    """Serve private cloud pictures only to authenticated accounts."""
    if not session.get("account_id"):
        abort(403)

    if _is_vercel_runtime():
        # Restrict reads to the avatar namespace; never expose backup objects.
        parts = filename.split("/")
        if (not filename.startswith(BLOB_PREFIX) or
                any(part in ("", ".", "..") for part in parts)):
            abort(404)
        result = _blob().get_blob(filename, access="private")
        if result is None or result.metadata.status_code != 200:
            abort(404)
        response = Response(result.body, mimetype=result.metadata.content_type or "image/jpeg")
    else:
        from flask import send_from_directory
        response = send_from_directory(UPLOAD_DIR, filename)

    response.headers["Cache-Control"] = "private, max-age=300"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
