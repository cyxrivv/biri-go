import base64, gzip, hashlib, hmac, json, os, re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from db import db
import config

PREFIX = "cloud-backups/"
ARCHIVE_RE = re.compile(r"^biri_go_(\d{8})_(\d{6})_(\d{6})_([0-9a-f]{64})\.bkg$")
MAGIC = b"BIRI-GO-CLOUD-BACKUP\x01"
FORMAT_VERSION = 1
RETENTION_COUNT = 5
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
BATCH_SIZE = 200


def _key():
    value = os.environ.get("CLOUD_BACKUP_ENCRYPTION_KEY", "").strip()
    if not value:
        raise RuntimeError("CLOUD_BACKUP_ENCRYPTION_KEY is not configured.")
    try:
        result = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception:
        result = b""
    if len(result) != 32:
        try:
            result = bytes.fromhex(value)
        except ValueError:
            result = value.encode()
    if len(result) != 32:
        raise RuntimeError("CLOUD_BACKUP_ENCRYPTION_KEY must represent exactly 32 bytes.")
    return result


def _encrypt(data):
    nonce = os.urandom(12)
    return MAGIC + nonce + AESGCM(_key()).encrypt(nonce, data, MAGIC)


def _decrypt(data):
    if not data.startswith(MAGIC) or len(data) <= len(MAGIC) + 12:
        raise RuntimeError("Unsupported cloud backup archive.")
    offset = len(MAGIC)
    try:
        return AESGCM(_key()).decrypt(data[offset:offset + 12], data[offset + 12:], MAGIC)
    except Exception as exc:
        raise RuntimeError("Backup authentication failed: wrong key or damaged archive.") from exc


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return {"__biri_datetime__": value.isoformat(sep=" ")}
    if isinstance(value, date):
        return {"__biri_date__": value.isoformat()}
    if isinstance(value, time):
        return {"__biri_time__": value.isoformat()}
    if isinstance(value, timedelta):
        return {"__biri_timedelta__": str(value)}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__biri_bytes__": base64.b64encode(bytes(value)).decode("ascii")}
    raise TypeError("Unsupported database value: %s" % type(value).__name__)


def _json_hook(value):
    if len(value) == 1:
        if "__biri_bytes__" in value:
            return base64.b64decode(value["__biri_bytes__"], validate=True)
        if "__biri_datetime__" in value:
            return datetime.fromisoformat(value["__biri_datetime__"])
        if "__biri_date__" in value:
            return date.fromisoformat(value["__biri_date__"])
        if "__biri_time__" in value:
            return time.fromisoformat(value["__biri_time__"])
        if "__biri_timedelta__" in value:
            return value["__biri_timedelta__"]
    return value


def _ident(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_$]+", name):
        raise RuntimeError("Invalid database identifier in archive.")
    return chr(96) + name + chr(96)


def _normalise_ddl(ddl):
    ddl = re.sub(r"\sAUTO_INCREMENT=\d+", "", ddl, flags=re.I)
    return re.sub(r"\s+", " ", ddl).strip()


def _tables(cur):
    cur.execute(
        "SELECT TABLE_NAME FROM information_schema.tables "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME"
    )
    return [r["TABLE_NAME"] for r in cur.fetchall()]


def _ddl(cur, name):
    cur.execute("SHOW CREATE TABLE %s" % _ident(name))
    row = cur.fetchone()
    if not row:
        raise RuntimeError("Could not read table schema: %s" % name)
    return list(row.values())[-1]


def _capture():
    result, total = [], 0
    with db() as (conn, cur):
        cur.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
        for name in _tables(cur):
            create_sql = _ddl(cur, name)
            cur.execute("SELECT * FROM %s" % _ident(name))
            rows = cur.fetchall()
            total += len(rows)
            result.append({"name": name, "create_sql": create_sql, "rows": rows})
    return {
        "format_version": FORMAT_VERSION,
        "database": config.DB_NAME,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tables": result,
        "table_count": len(result),
        "row_count": total,
    }


def _blob():
    try:
        from vercel.blob import sync as blob
    except ImportError as exc:
        raise RuntimeError("Install the Vercel Python SDK: vercel>=0.5.0.") from exc
    if not (os.getenv("BLOB_READ_WRITE_TOKEN") or
            (os.getenv("VERCEL_OIDC_TOKEN") and os.getenv("BLOB_STORE_ID"))):
        raise RuntimeError("Private Vercel Blob credentials are missing.")
    return blob


def _archive(snapshot):
    raw = json.dumps(snapshot, default=_json_default, separators=(",", ":"),
                     ensure_ascii=False).encode("utf-8")
    result = _encrypt(gzip.compress(raw, compresslevel=6))
    limit = int(os.getenv("CLOUD_BACKUP_MAX_BYTES", MAX_ARCHIVE_BYTES))
    if len(result) > limit:
        raise RuntimeError("Backup exceeds CLOUD_BACKUP_MAX_BYTES (%s bytes)." % limit)
    return result


def _filename(payload):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    return "biri_go_%s_%s.bkg" % (stamp, hashlib.sha256(payload).hexdigest())


def _valid_filename(name):
    if not isinstance(name, str) or not ARCHIVE_RE.fullmatch(name):
        raise RuntimeError("Invalid cloud backup filename.")
    return name


def _decode(payload, filename=None):
    if filename:
        match = ARCHIVE_RE.fullmatch(filename)
        if not match or not hmac.compare_digest(match.group(4), hashlib.sha256(payload).hexdigest()):
            raise RuntimeError("Backup checksum verification failed.")
    try:
        snapshot = json.loads(gzip.decompress(_decrypt(payload)), object_hook=_json_hook)
    except Exception as exc:
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError("Backup archive is corrupt or incomplete.") from exc
    if not isinstance(snapshot, dict) or snapshot.get("format_version") != FORMAT_VERSION:
        raise RuntimeError("Unsupported backup format.")
    if snapshot.get("database") != config.DB_NAME:
        raise RuntimeError("Backup belongs to a different database.")
    if not isinstance(snapshot.get("tables"), list) or not snapshot["tables"]:
        raise RuntimeError("Backup contains no tables.")
    return snapshot


def _objects():
    return [x for x in _blob().query_blobs(prefix=PREFIX)
            if ARCHIVE_RE.fullmatch(x.pathname.rsplit("/", 1)[-1])]


def list_cloud_backups():
    items = []
    for item in _objects():
        name = item.pathname.rsplit("/", 1)[-1]
        match = ARCHIVE_RE.fullmatch(name)
        created = datetime.strptime("_".join(match.group(1, 2, 3)),
                                    "%Y%m%d_%H%M%S_%f").replace(tzinfo=timezone.utc)
        items.append({"filename": name, "size": item.size,
                      "created_at": created.isoformat(timespec="seconds"),
                      "checksum": match.group(4), "storage": "Vercel Blob (private)"})
    return sorted(items, key=lambda x: x["created_at"], reverse=True)


def create_cloud_backup(source="manual"):
    snapshot = _capture()
    snapshot["source"] = source
    payload = _archive(snapshot)
    name = _filename(payload)
    pathname = PREFIX + name
    blob = _blob()
    uploaded = blob.put_blob(pathname, payload, access="private",
                             content_type="application/octet-stream")
    downloaded = blob.get_blob(uploaded.pathname, access="private").body
    checked = _decode(downloaded, name)
    if checked["table_count"] != snapshot["table_count"]:
        raise RuntimeError("Uploaded backup verification failed.")
    warning = None
    try:
        objects = sorted(_objects(), key=lambda x: x.uploaded_at, reverse=True)
        stale = [x.pathname for x in objects[RETENTION_COUNT:]]
        if stale:
            blob.delete_blob(stale)
    except Exception as exc:
        warning = "Backup verified, but retention cleanup failed: %s" % exc
    return {"filename": name, "size": len(payload), "created_at": snapshot["created_at"],
            "checksum": hashlib.sha256(payload).hexdigest(),
            "table_count": snapshot["table_count"], "row_count": snapshot["row_count"],
            "source": source, "retention_warning": warning}


def delete_cloud_backup(filename):
    _blob().delete_blob(PREFIX + _valid_filename(filename))


def _schema(cur):
    return {name: _normalise_ddl(_ddl(cur, name)) for name in _tables(cur)}


def _restore_data(snapshot):
    archive = {}
    for item in snapshot["tables"]:
        name = item.get("name")
        _ident(name)
        if name in archive or not isinstance(item.get("rows"), list):
            raise RuntimeError("Invalid or duplicate table in backup.")
        archive[name] = item
    with db() as (conn, cur):
        current = _schema(cur)
        archived = {n: _normalise_ddl(t.get("create_sql", "")) for n, t in archive.items()}
        if set(current) != set(archived):
            raise RuntimeError("Schema/table list differs from backup; no data was changed.")
        for name in current:
            if current[name] != archived[name]:
                raise RuntimeError("Schema for table %s differs; no data was changed." % name)
        try:
            cur.execute("SET FOREIGN_KEY_CHECKS = 0")
            conn.start_transaction()
            for name in reversed(list(archive)):
                cur.execute("DELETE FROM %s" % _ident(name))
            counts = {}
            for name, table in archive.items():
                rows = table["rows"]
                counts[name] = len(rows)
                if not rows:
                    continue
                columns = list(rows[0].keys())
                sql = "INSERT INTO %s (%s) VALUES (%s)" % (
                    _ident(name), ", ".join(_ident(c) for c in columns),
                    ", ".join(["%s"] * len(columns)))
                for offset in range(0, len(rows), BATCH_SIZE):
                    batch = rows[offset:offset + BATCH_SIZE]
                    cur.executemany(sql, [tuple(r.get(c) for c in columns) for r in batch])
            for name, expected in counts.items():
                cur.execute("SELECT COUNT(*) AS n FROM %s" % _ident(name))
                if int(cur.fetchone()["n"]) != expected:
                    raise RuntimeError("Row-count verification failed for %s." % name)
            conn.commit()
            return {"table_count": len(archive), "row_count": sum(counts.values())}
        except Exception:
            conn.rollback()
            raise
        finally:
            try:
                cur.execute("SET FOREIGN_KEY_CHECKS = 1")
            except Exception:
                pass


def restore_cloud_backup(filename):
    name = _valid_filename(filename)
    payload = _blob().get_blob(PREFIX + name, access="private").body
    snapshot = _decode(payload, name)
    return {**_restore_data(snapshot), "created_at": snapshot.get("created_at")}
