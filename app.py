import os
import sys
import time
import socket
import tempfile
import shutil
import atexit
import threading
import zipfile
import io
import uuid
import secrets
import mimetypes
import argparse
import webbrowser
from datetime import datetime
from flask import Flask, render_template, request, send_file, redirect, url_for, jsonify, abort, session as flask_session
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def get_env_int(key, default):
    """Safely parse integer from environment, handling None, empty strings, and invalid values."""
    val = os.getenv(key)
    if val is None or not str(val).strip():
        return default
    try:
        return int(str(val).strip())
    except (ValueError, TypeError):
        return default

# App Configuration
app = Flask(__name__)
secret_env = os.getenv("SECRET_KEY")
app.secret_key = secret_env.strip() if secret_env and secret_env.strip() else secrets.token_hex(32)

HOST = os.getenv("HOST", "0.0.0.0")
if not HOST or not HOST.strip():
    HOST = "0.0.0.0"

PORT = get_env_int("PORT", 5000)
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
SESSION_TIMEOUT_MINUTES = get_env_int("SESSION_TIMEOUT_MINUTES", 5)
MAX_CONTENT_LENGTH_MB = get_env_int("MAX_CONTENT_LENGTH_MB", 250)
ENABLE_SESSION_PIN = (os.getenv("ENABLE_SESSION_PIN", "false") or "").strip().lower() in ("true", "1", "yes")
OPEN_BROWSER = (os.getenv("OPEN_BROWSER", "false") or "").strip().lower() in ("true", "1", "yes")

app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH_MB * 1024 * 1024

# ------------------------------------------------------------------------------
# In-Memory Session Registry
# Note: Designed for single-instance, single-process deployment (1 Gunicorn worker
# with multiple threads, e.g. `workers = 1`, `threads = 8`).
#
# IMPORTANT FOR HOSTED PLATFORMS (Render / Railway):
# Deploy this service with strictly 1 replica / 1 instance and NO horizontal autoscaling.
#
# Horizontal Scaling Path:
# If scaling across multiple instances or multiple Gunicorn processes:
# 1. Move `SESSIONS` registry to a shared in-memory store like Redis (e.g. Upstash Redis
#    available on Render / Railway).
# 2. Store files in shared S3 / Cloudflare R2 object storage or an attached shared volume
#    rather than local ephemeral temp directories.
# ------------------------------------------------------------------------------
def get_local_ip():
    """Detect LAN IP address for QR code and local network access."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

def get_session_url(session_id):
    """Constructs the full shareable URL for a session."""
    if PUBLIC_BASE_URL:
        return f"{PUBLIC_BASE_URL}/s/{session_id}"

    # Auto-detect public URL from request headers (Render, Railway, custom domains)
    try:
        if request:
            proto = (request.headers.get("X-Forwarded-Proto") or request.scheme or "http").strip()
            host = (request.headers.get("X-Forwarded-Host") or request.host or "").strip()
            if host:
                host_name = host.split(":")[0].strip().lower()
                if host_name not in ("localhost", "127.0.0.1", "0.0.0.0"):
                    return f"{proto}://{host}/s/{session_id}"
    except Exception:
        pass

    local_ip = get_local_ip()
    port_str = f":{PORT}" if PORT not in (80, 443) else ""
    return f"http://{local_ip}{port_str}/s/{session_id}"

def format_file_size(size_bytes):
    """Format bytes into human-readable size string."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}" if unit != 'B' else f"{int(size_bytes)} B"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"

def is_safe_path(base_dir, path, follow_symlinks=True):
    """Path traversal prevention check."""
    if follow_symlinks:
        matchpath = os.path.realpath(path)
        basepath = os.path.realpath(base_dir)
    else:
        matchpath = os.path.abspath(path)
        basepath = os.path.abspath(base_dir)
    return basepath == os.path.commonpath((basepath, matchpath))

# ------------------------------------------------------------------------------
# Session Manager & In-Memory Capability Registry
# ------------------------------------------------------------------------------
JOIN_CODE_CHARS = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # Omits 0, O, 1, I, L

class SessionManager:
    """Manages ephemeral transfer sessions, isolated storage folders, and join codes."""
    _sessions = {}
    _code_to_session = {}
    _lock = threading.RLock()

    @classmethod
    def _cleanup_dir(cls, folder_path):
        """Safely removes a session temporary folder from disk."""
        if not folder_path or not os.path.exists(folder_path):
            return

        def handle_remove_readonly(func, path, exc_info):
            import stat
            try:
                os.chmod(path, stat.S_IWRITE)
                func(path)
            except Exception:
                pass

        for attempt in range(3):
            try:
                if not os.path.exists(folder_path):
                    break
                shutil.rmtree(folder_path, onexc=handle_remove_readonly)
            except TypeError:
                shutil.rmtree(folder_path, onerror=handle_remove_readonly)
            except Exception:
                shutil.rmtree(folder_path, ignore_errors=True)
            if not os.path.exists(folder_path):
                break
            time.sleep(0.05)

    @classmethod
    def generate_short_code(cls):
        """Generates a collision-free 6-character short code formatted as XXX-XXX."""
        while True:
            raw = "".join(secrets.choice(JOIN_CODE_CHARS) for _ in range(6))
            if raw not in cls._code_to_session:
                formatted = f"{raw[:3]}-{raw[3:]}"
                return raw, formatted

    @classmethod
    def create_session(cls):
        """Creates a new isolated session with unique capability UUID and short code."""
        session_id = uuid.uuid4().hex
        temp_dir = tempfile.mkdtemp(prefix=f"session_{session_id[:8]}_")
        now = time.time()
        expires_at = now + (SESSION_TIMEOUT_MINUTES * 60)
        csrf_token = secrets.token_hex(16)
        pin = f"{secrets.randbelow(9000) + 1000}" if ENABLE_SESSION_PIN else None

        with cls._lock:
            code_raw, short_code = cls.generate_short_code()
            session_data = {
                "id": session_id,
                "short_code": short_code,
                "short_code_raw": code_raw,
                "folder": temp_dir,
                "created_at": now,
                "expires_at": expires_at,
                "csrf_token": csrf_token,
                "pin": pin,
                "files": {},  # file_id -> file_meta
                "verified_pins": set()  # Client IPs or tokens that passed PIN check
            }
            cls._sessions[session_id] = session_data
            cls._code_to_session[code_raw] = session_id

        return session_data

    @classmethod
    def get_session(cls, session_id):
        """Retrieves session by ID if it exists and has not expired."""
        now = time.time()
        with cls._lock:
            session_data = cls._sessions.get(session_id)
            if not session_data:
                return None

            max_remaining = SESSION_TIMEOUT_MINUTES * 60
            if not session_data.get("extended", False):
                if session_data["expires_at"] > now + max_remaining:
                    session_data["expires_at"] = now + max_remaining

            if now > session_data["expires_at"]:
                # Expired - clean up folder and registry indices
                cls._cleanup_dir(session_data["folder"])
                cls._sessions.pop(session_id, None)
                cls._code_to_session.pop(session_data.get("short_code_raw"), None)
                return None

            return session_data

    @classmethod
    def get_session_by_code(cls, code):
        """Retrieves active session by human-typable short code (case/dash insensitive)."""
        if not code:
            return None
        clean_code = "".join(c for c in str(code).upper() if c.isalnum())
        if len(clean_code) != 6:
            return None

        with cls._lock:
            session_id = cls._code_to_session.get(clean_code)
            if not session_id:
                return None
            return cls.get_session(session_id)

    @classmethod
    def terminate_session(cls, session_id):
        """Immediately ends a session, removes indices, and purges files."""
        with cls._lock:
            session_data = cls._sessions.pop(session_id, None)
            if session_data:
                cls._code_to_session.pop(session_data.get("short_code_raw"), None)
        if session_data:
            cls._cleanup_dir(session_data["folder"])
            return True
        return False

    @classmethod
    def sweep_expired(cls):
        """Sweeps expired sessions from registry and disk."""
        now = time.time()
        expired_folders = []
        with cls._lock:
            max_lifetime = SESSION_TIMEOUT_MINUTES * 60
            for sid, s in list(cls._sessions.items()):
                if not s.get("extended", False) and s["expires_at"] > now + max_lifetime:
                    s["expires_at"] = now + max_lifetime

            expired_ids = [
                sid for sid, s in cls._sessions.items()
                if now > s["expires_at"]
            ]
            for sid in expired_ids:
                s = cls._sessions.pop(sid)
                cls._code_to_session.pop(s.get("short_code_raw"), None)
                expired_folders.append(s["folder"])

        for folder in expired_folders:
            cls._cleanup_dir(folder)

    @classmethod
    def cleanup_all(cls):
        """Removes all active session directories and clears registries on shutdown."""
        with cls._lock:
            for sid, s in cls._sessions.items():
                cls._cleanup_dir(s.get("folder"))
            cls._sessions.clear()
            cls._code_to_session.clear()

    @classmethod
    def active_count(cls):
        """Returns the count of currently active sessions."""
        now = time.time()
        with cls._lock:
            return sum(1 for s in cls._sessions.values() if now <= s["expires_at"])


# Backward compatibility aliases
SESSIONS = SessionManager._sessions
CODE_TO_SESSION = SessionManager._code_to_session
sessions_lock = SessionManager._lock
create_session = SessionManager.create_session
get_session = SessionManager.get_session
terminate_session = SessionManager.terminate_session
_cleanup_session_dir = SessionManager._cleanup_dir

# ------------------------------------------------------------------------------
# Rate Limiter for /join Attempts (10 attempts / minute per IP)
# ------------------------------------------------------------------------------
JOIN_RATE_LIMIT = 10
JOIN_RATE_WINDOW = 60
JOIN_ATTEMPTS = {}
join_rate_lock = threading.Lock()

def check_join_rate_limit(client_ip):
    now = time.time()
    with join_rate_lock:
        timestamps = JOIN_ATTEMPTS.get(client_ip, [])
        timestamps = [t for t in timestamps if now - t < JOIN_RATE_WINDOW]
        if len(timestamps) >= JOIN_RATE_LIMIT:
            JOIN_ATTEMPTS[client_ip] = timestamps
            return False
        timestamps.append(now)
        JOIN_ATTEMPTS[client_ip] = timestamps
        return True

# ------------------------------------------------------------------------------
# Background Session Sweeper & Server Cleanup
# ------------------------------------------------------------------------------
def sweep_expired_sessions():
    """Background worker that periodically deletes expired session folders."""
    while True:
        try:
            time.sleep(30)
            SessionManager.sweep_expired()
        except Exception as e:
            app.logger.warning(f"Error in session sweeper thread: {e}")

def cleanup_all_sessions():
    """Executed on server shutdown to remove all active session directories."""
    SessionManager.cleanup_all()

# Register atexit cleanup BEFORE starting application execution
atexit.register(cleanup_all_sessions)

# Start daemon sweeper thread
sweeper_thread = threading.Thread(target=sweep_expired_sessions, daemon=True)
sweeper_thread.start()

# ------------------------------------------------------------------------------
# Request Verification & Helpers
# ------------------------------------------------------------------------------
def check_pin_authorization(session_data):
    """Validates if client has entered the session PIN (if enabled)."""
    if not session_data.get("pin"):
        return True
    client_token = flask_session.get(f"pin_auth_{session_data['id']}")
    return client_token == session_data["pin"]

@app.errorhandler(413)
def request_entity_too_large(error):
    if request.is_json or request.path.endswith("/upload"):
        return jsonify({
            "error": f"File exceeds maximum allowed size of {MAX_CONTENT_LENGTH_MB} MB."
        }), 413
    return f"File exceeds maximum allowed size of {MAX_CONTENT_LENGTH_MB} MB.", 413

# ------------------------------------------------------------------------------
# Routes
# ------------------------------------------------------------------------------

@app.route("/")
def index():
    """Landing page with 'Start New Transfer' and 'Join a Session' options."""
    return render_template("index.html")

@app.route("/new", methods=["GET", "POST"])
def new_transfer():
    """Explicitly spins up a fresh session with its own ID, QR code, and short code."""
    session_data = SessionManager.create_session()
    return redirect(url_for("session_view", session_id=session_data["id"]))

@app.route("/join", methods=["GET", "POST"])
def join_session():
    """Allows joining an active session via human-typable 6-character short code."""
    if request.method == "GET":
        return redirect(url_for("index"))

    client_ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "127.0.0.1").split(",")[0].strip()

    if not check_join_rate_limit(client_ip):
        rate_error = "Too many join attempts. Please wait a minute and try again."
        if request.is_json:
            return jsonify({"error": rate_error}), 429
        return render_template("index.html", error=rate_error), 429

    data = request.get_json(silent=True) or request.form
    raw_code = (data.get("code") or "").strip()

    session_data = SessionManager.get_session_by_code(raw_code)

    if session_data:
        dest_url = url_for("session_view", session_id=session_data["id"])
        if request.is_json:
            return jsonify({"success": True, "redirect": dest_url}), 200
        return redirect(dest_url, code=302)

    error_msg = "No active session with that code — check for typos, or ask the sender for a new one."
    if request.is_json:
        return jsonify({"error": error_msg}), 400
    return render_template("index.html", error=error_msg, entered_code=raw_code), 400

@app.route("/healthz")
def healthz():
    """Health check liveness probe for Render / Railway platform monitoring."""
    return jsonify({
        "status": "ok",
        "active_sessions": SessionManager.active_count()
    }), 200

@app.route("/favicon.ico")
def favicon():
    """Serves the new logo favicon."""
    return send_file(os.path.join(app.root_path, "static", "favicon.ico"), mimetype="image/x-icon")

@app.route("/s/<session_id>")
def session_view(session_id):
    """Renders the transfer interface for a specific isolated session."""
    session_data = SessionManager.get_session(session_id)
    if not session_data:
        return render_template("expired.html"), 404

    session_url = get_session_url(session_id)
    
    requires_pin = False
    if session_data.get("pin") and not check_pin_authorization(session_data):
        requires_pin = True

    remaining_seconds = max(0, int(session_data["expires_at"] - time.time()))

    return render_template(
        "session.html",
        session_id=session_id,
        short_code=session_data["short_code"],
        session_url=session_url,
        csrf_token=session_data["csrf_token"],
        pin=session_data.get("pin"),
        requires_pin=requires_pin,
        remaining_seconds=remaining_seconds,
        max_upload_mb=MAX_CONTENT_LENGTH_MB,
        files=list(session_data["files"].values())
    )

@app.route("/s/<session_id>/qr.png")
def session_qr(session_id):
    """Generates and serves QR code on the fly in memory for the full session URL."""
    session_data = get_session(session_id)
    if not session_data:
        abort(404)

    import qrcode
    session_url = get_session_url(session_id)

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(session_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

@app.route("/s/<session_id>/verify-pin", methods=["POST"])
def verify_pin(session_id):
    """Verifies PIN for PIN-protected sessions."""
    session_data = get_session(session_id)
    if not session_data:
        return jsonify({"error": "Session expired or not found."}), 404

    data = request.get_json(silent=True) or request.form
    entered_pin = (data.get("pin") or "").strip()

    if session_data.get("pin") and entered_pin == session_data["pin"]:
        flask_session[f"pin_auth_{session_id}"] = entered_pin
        return jsonify({"success": True})
    return jsonify({"error": "Incorrect PIN. Please try again."}), 403

@app.route("/s/<session_id>/files")
def session_files(session_id):
    """JSON API for real-time polling of files and session expiration countdown."""
    session_data = get_session(session_id)
    if not session_data:
        return jsonify({"error": "Session expired"}), 404

    now = time.time()
    remaining_seconds = max(0, int(session_data["expires_at"] - now))

    return jsonify({
        "session_id": session_id,
        "short_code": session_data["short_code"],
        "remaining_seconds": remaining_seconds,
        "expires_at": session_data["expires_at"],
        "files": list(session_data["files"].values())
    })

@app.route("/s/<session_id>/upload", methods=["POST"])
def upload_file(session_id):
    """Handles secure file uploads scoped exclusively to this session folder."""
    session_data = get_session(session_id)
    if not session_data:
        return jsonify({"error": "Session expired or not found."}), 404

    # CSRF Check
    submitted_csrf = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    if not submitted_csrf or submitted_csrf != session_data["csrf_token"]:
        return jsonify({"error": "Invalid or missing CSRF token."}), 403

    # PIN Check
    if session_data.get("pin") and not check_pin_authorization(session_data):
        return jsonify({"error": "PIN authorization required."}), 403

    if "file" not in request.files and "files" not in request.files and not request.files:
        return jsonify({"error": "No file part in request."}), 400

    uploaded_files = request.files.getlist("file") or request.files.getlist("files")
    saved_files = []

    for file_storage in uploaded_files:
        if not file_storage or not file_storage.filename:
            continue

        raw_name = file_storage.filename
        safe_name = secure_filename(raw_name)
        if not safe_name:
            safe_name = f"file_{secrets.token_hex(4)}"

        # Generate unique identifier and stored filename to prevent overwrites/collisions
        file_id = secrets.token_hex(8)
        stored_filename = f"{file_id}_{safe_name}"
        destination = os.path.join(session_data["folder"], stored_filename)

        # Path traversal verification
        if not is_safe_path(session_data["folder"], destination):
            return jsonify({"error": "Security error: Path traversal detected."}), 400

        file_storage.save(destination)
        file_size = os.path.getsize(destination)

        # Detect MIME and determine if image for preview
        mime_type, _ = mimetypes.guess_type(raw_name)
        is_image = bool(mime_type and mime_type.startswith("image/"))

        file_meta = {
            "id": file_id,
            "filename": stored_filename,
            "display_name": raw_name,
            "size_bytes": file_size,
            "size_formatted": format_file_size(file_size),
            "uploaded_at": datetime.now().strftime("%I:%M %p"),
            "is_image": is_image,
            "mime_type": mime_type or "application/octet-stream",
            "download_url": url_for("download_file", session_id=session_id, file_id=file_id)
        }

        session_data["files"][file_id] = file_meta
        saved_files.append(file_meta)

    return jsonify({
        "success": True,
        "message": f"Successfully uploaded {len(saved_files)} file(s).",
        "files": saved_files
    })

@app.route("/s/<session_id>/download/<file_id>")
def download_file(session_id, file_id):
    """Serves a file strictly from the session directory with original download name."""
    session_data = get_session(session_id)
    if not session_data:
        return render_template("expired.html"), 404

    # PIN Check
    if session_data.get("pin") and not check_pin_authorization(session_data):
        return redirect(url_for("session_view", session_id=session_id))

    file_meta = session_data["files"].get(file_id)
    if not file_meta:
        abort(404)

    file_path = os.path.join(session_data["folder"], file_meta["filename"])

    if not is_safe_path(session_data["folder"], file_path) or not os.path.isfile(file_path):
        abort(404)

    # If it's an inline image preview request (e.g. ?preview=1), serve inline
    as_attachment = request.args.get("preview") != "1"

    return send_file(
        file_path,
        as_attachment=as_attachment,
        download_name=file_meta["display_name"],
        mimetype=file_meta["mime_type"]
    )

@app.route("/s/<session_id>/download-all")
def download_all(session_id):
    """Creates a zip archive in memory (or outside session folder) and serves it."""
    session_data = get_session(session_id)
    if not session_data:
        return render_template("expired.html"), 404

    if session_data.get("pin") and not check_pin_authorization(session_data):
        return redirect(url_for("session_view", session_id=session_id))

    if not session_data["files"]:
        return "No files to download", 400

    # Build zip file into an in-memory buffer so session folder is never polluted
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file_id, file_meta in session_data["files"].items():
            file_path = os.path.join(session_data["folder"], file_meta["filename"])
            if os.path.isfile(file_path) and is_safe_path(session_data["folder"], file_path):
                zipf.write(file_path, arcname=file_meta["display_name"])

    zip_buffer.seek(0)
    zip_name = f"transfer_{session_id[:8]}.zip"

    return send_file(
        zip_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=zip_name
    )

@app.route("/s/<session_id>/extend", methods=["POST"])
def extend_session(session_id):
    """Extends the lifetime of a session by 5 minutes."""
    session_data = get_session(session_id)
    if not session_data:
        return jsonify({"error": "Session expired or not found."}), 404

    # CSRF Check
    submitted_csrf = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    if not submitted_csrf or submitted_csrf != session_data["csrf_token"]:
        return jsonify({"error": "Invalid CSRF token."}), 403

    # Add 5 minutes, capped at max 60 minutes from now
    additional_seconds = 5 * 60
    new_expires = min(time.time() + (60 * 60), session_data["expires_at"] + additional_seconds)
    session_data["expires_at"] = new_expires
    session_data["extended"] = True

    remaining_seconds = max(0, int(new_expires - time.time()))

    return jsonify({
        "success": True,
        "remaining_seconds": remaining_seconds,
        "expires_at": new_expires
    })

@app.route("/s/<session_id>/end", methods=["POST"])
def end_session(session_id):
    """Immediately ends session and purges files. Supports sendBeacon and AJAX."""
    session_data = get_session(session_id)
    if session_data:
        # Check CSRF if provided (sendBeacon may send empty or form-encoded)
        submitted_csrf = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
        if submitted_csrf and submitted_csrf != session_data["csrf_token"]:
            return jsonify({"error": "Invalid CSRF token."}), 403

        terminate_session(session_id)

    if request.is_json:
        return jsonify({"success": True})
    return redirect(url_for("index"))

# ------------------------------------------------------------------------------
# Optional Browser Auto-launch
# ------------------------------------------------------------------------------
def maybe_open_browser(host, port):
    """Opens browser automatically if configured via CLI flag or .env."""
    url = f"http://127.0.0.1:{port}"
    print(f"[*] Opening browser at {url}...")
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"[!] Could not launch browser: {e}")

# ------------------------------------------------------------------------------
# Entry Point
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Relay - Local File Transfer App with Session Isolation")
    parser.add_argument("--port", type=int, default=PORT, help=f"Port to bind (default: {PORT})")
    parser.add_argument("--host", type=str, default=HOST, help=f"Host to bind (default: {HOST})")
    parser.add_argument("--open", action="store_true", help="Automatically open browser on start")
    args = parser.parse_args()

    active_port = args.port
    active_host = args.host
    should_open_browser = args.open or OPEN_BROWSER

    if should_open_browser:
        threading.Timer(1.2, maybe_open_browser, args=(active_host, active_port)).start()

    local_ip = get_local_ip()
    print("=" * 60)
    print(" Relay - File Transfer App (Session Isolated) ")
    print("=" * 60)
    print(f" * Local Address:   http://127.0.0.1:{active_port}")
    if PUBLIC_BASE_URL:
        print(f" * Public Address:  {PUBLIC_BASE_URL}")
    else:
        print(f" * Network Address: http://{local_ip}:{active_port}")
    print(f" * Default Timeout: {SESSION_TIMEOUT_MINUTES} minutes")
    print(f" * Max Upload Size: {MAX_CONTENT_LENGTH_MB} MB")
    print("=" * 60)

    app.run(host=active_host, port=active_port, debug=False)
