"""Profile pictures for every account (admin, hr, owner, employee).

Put this file in: system/backend/profile_pictures.py
"""
import io
import os
import sys
import uuid

from flask import Blueprint, abort, jsonify, request, send_from_directory, session
from PIL import Image, ImageOps, UnidentifiedImageError

from db import db
from utils import ApiError

MAX_UPLOAD_BYTES = 2 * 1024 * 1024          # 2 MB
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
AVATAR_SIZE = 256                            # saved as 256x256
DEFAULT_AVATAR_URL = "/statistics/images/default-avatar.png"
Image.MAX_IMAGE_PIXELS = 30_000_000          # refuse absurdly large images


def _upload_dir():
    # Packaged .exe: the bundle is temporary, so store pictures next to the .exe.
    if getattr(sys, "frozen", False):
        base = os.path.join(os.path.dirname(sys.executable), "uploads", "profile_pics")
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        base = os.path.join(here, "..", "statistics", "uploads", "profile_pics")
    base = os.path.abspath(base)
    os.makedirs(base, exist_ok=True)
    return base


UPLOAD_DIR = _upload_dir()

profile_bp = Blueprint("profile", __name__)


def _require_login():
    account_id = session.get("account_id")
    if not account_id:
        raise ApiError("Please sign in.", 401)
    return account_id


def _url_for(filename):
    return "/profile-pictures/" + filename if filename else DEFAULT_AVATAR_URL


def _delete_file(filename):
    if not filename:
        return
    path = os.path.join(UPLOAD_DIR, os.path.basename(filename))
    try:
        os.remove(path)
    except OSError:
        pass


def _process_image(file_storage, account_id):
    """Validate the upload, crop it to a square, and save it. Returns the new filename."""
    raw = file_storage.read(MAX_UPLOAD_BYTES + 1)
    if not raw:
        raise ApiError("No file selected.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ApiError("Image is too large (max 2 MB).")

    try:
        img = Image.open(io.BytesIO(raw))
        if img.format not in ALLOWED_FORMATS:
            raise ApiError("Only PNG, JPG or WEBP images are allowed.")
        img = ImageOps.exif_transpose(img)           # fix phone-photo rotation
        img = img.convert("RGB")                     # drops transparency / metadata
        img = ImageOps.fit(img, (AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)  # center-crop + resize
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ApiError("That file is not a valid image.")

    filename = "%s_%s.jpg" % (account_id, uuid.uuid4().hex)
    img.save(os.path.join(UPLOAD_DIR, filename), "JPEG", quality=85)
    return filename


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
        _delete_file(new_name)      # don't leave an orphan file if the DB step failed
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
    """Serve saved pictures to signed-in users only."""
    if not session.get("account_id"):
        abort(403)
    resp = send_from_directory(UPLOAD_DIR, filename)   # blocks ../ path tricks
    resp.headers["Cache-Control"] = "private, max-age=86400"  # filenames are unique per upload
    return resp