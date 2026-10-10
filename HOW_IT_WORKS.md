# How Relay Works — Architecture, Technologies & Code Walkthrough

This document explains in detail how Relay operates under the hood, breaking down every core feature, the exact technologies powering it, how file transferring is performed from end-to-end, and how security is enforced at every layer with code examples.

---

## 1. High-Level Architecture Overview

Relay is built on an **ephemeral, session-isolated client-server architecture**:

```
 [ Device A: Sender / Creator ]
         │
         │  1. GET /new  (Creates isolated session)
         ▼
 ┌────────────────────────────────────────────────────────┐
 │                      Relay Server                      │
 │                                                        │
 │  • SessionManager: in-memory state & lock              │
 │  • Ephemeral folder: /tmp/session_xxxxxxxx/            │
 │  • Dynamic QR Generator: In-memory qrcode              │
 │  • Background Sweeper: 30s expiry garbage collection   │
 └────────────────────────────────────────────────────────┘
         ▲                                ▲
         │ 2. Scans QR or                 │ 4. Downloads files
         │    enters code (XXX-XXX)       │    or streams .zip
         │                                │
 [ Device B: Receiver / Joiner ] ─────────┘
         │
         │ 3. Uploads files via drag-and-drop
         ▼
```

### The Core Philosophy: Zero Shared Storage
Unlike traditional file servers where all files land in a global `/uploads` directory, Relay dynamically spins up a **dedicated temporary folder per transfer session**. When the session ends or expires after 5 minutes, that folder is completely erased from disk.

---

## 2. Feature-by-Feature Deep Dive & Code Breakdown

---

### Feature 1: Isolated Sessions & Lifecycle Management

#### What it does:
Each transfer session is completely isolated. When a user starts a transfer, the server creates a unique cryptographic UUID, assigns a temporary folder, sets a 5-minute expiration clock, and starts an automatic cleanup countdown.

#### Technologies Used:
- **Python `uuid.uuid4()`**: Generates high-entropy capability IDs for URLs.
- **Python `tempfile.mkdtemp()`**: Creates secure, unique filesystem folders.
- **Python `threading.RLock()`**: Thread-safe access to session registries across concurrent requests.
- **Python `threading.Thread` & `atexit`**: Background sweeper thread and server shutdown cleanup hooks.

#### The Code Part (`app.py`):
```python
class SessionManager:
    _sessions = {}
    _code_to_session = {}
    _lock = threading.RLock()

    @classmethod
    def create_session(cls):
        # 1. Generate unique 32-character hexadecimal ID
        session_id = uuid.uuid4().hex

        # 2. Create isolated OS temporary directory
        temp_dir = tempfile.mkdtemp(prefix=f"session_{session_id[:8]}_")

        # 3. Establish 5-minute lifespan and security tokens
        now = time.time()
        expires_at = now + (SESSION_TIMEOUT_MINUTES * 60)
        csrf_token = secrets.token_hex(16)
        code_raw, short_code = cls.generate_short_code()

        with cls._lock:
            session_data = {
                "id": session_id,
                "short_code": short_code,
                "folder": temp_dir,
                "created_at": now,
                "expires_at": expires_at,
                "csrf_token": csrf_token,
                "files": {},
            }
            cls._sessions[session_id] = session_data
            cls._code_to_session[code_raw] = session_id

        return session_data
```

#### Automatic Expiration Sweeper (`app.py`):
A daemon background thread runs every 30 seconds to clean up expired sessions from memory and disk:
```python
def sweep_expired_sessions():
    while True:
        time.sleep(30)
        SessionManager.sweep_expired()

# Launched automatically at server startup
threading.Thread(target=sweep_expired_sessions, daemon=True).start()
```

---

### Feature 2: Dual-Device Pairing (Dynamic QR Codes & Short Join Codes)

#### What it does:
Connecting two devices must be frictionless:
1. **Phones/Tablets** can scan the on-screen QR code.
2. **Laptops/Desktops** (which lack cameras) can type a 6-character code like `4K9-2PZ`.

#### Technologies Used:
- **Python `qrcode`**: In-memory barcode generation.
- **Python `io.BytesIO`**: Prevents writing static image files to disk.
- **Sliding-Window IP Rate Limiter**: Prevents brute-forcing short join codes.

#### How QR Codes are Generated Dynamically (`app.py`):
Instead of saving `.png` files that clutter storage, Relay generates the QR image in RAM and streams it directly to the browser:
```python
@app.route("/s/<session_id>/qr.png")
def session_qr(session_id):
    session_data = get_session(session_id)
    if not session_data:
        abort(404)

    target_url = get_session_url(session_id)
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(target_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")
```

#### How Short Join Codes Work (`app.py`):
To prevent misreading, visually ambiguous characters (`0`, `O`, `1`, `I`, `L`) are eliminated:
```python
JOIN_CODE_CHARS = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"

def generate_short_code(cls):
    while True:
        raw = "".join(secrets.choice(JOIN_CODE_CHARS) for _ in range(6))
        if raw not in cls._code_to_session:
            formatted = f"{raw[:3]}-{raw[3:]}"  # Formats as XXX-XXX
            return raw, formatted
```

---

### Feature 3: In-App Camera QR Scanner

#### What it does:
Allows any device with a camera to scan another device's screen directly inside Relay, without relying on native camera apps.

#### Technologies Used:
- **HTML5 MediaDevices API (`navigator.mediaDevices.getUserMedia`)**: Accesses the device's rear or front video camera.
- **HTML5 `<video>` & `<canvas>`**: Captures real-time video frames.
- **`jsQR` Library**: Decodes QR code matrices from raw pixel arrays in the browser.
- **Web Audio API (`AudioContext`) & Vibration API (`navigator.vibrate`)**: Provides instant auditory and tactile feedback upon detection.

#### The Code Part (`static/js/app.js`):
```javascript
// 1. Request rear camera stream
const stream = await navigator.mediaDevices.getUserMedia({
  video: { facingMode: { ideal: 'environment' } }
});
videoElement.srcObject = stream;

// 2. Continuously capture frames into canvas and analyze via jsQR
function scanFrame() {
  if (videoElement.readyState === videoElement.HAVE_ENOUGH_DATA) {
    canvas.width = videoElement.videoWidth;
    canvas.height = videoElement.videoHeight;
    ctx.drawImage(videoElement, 0, 0, canvas.width, canvas.height);

    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    // Real-time computer vision QR decoding
    const code = jsQR(imageData.data, imageData.width, imageData.height);

    if (code && code.data) {
      playSuccessSound();      // Web Audio API beep
      triggerHapticFeedback(); // Phone vibration
      window.location.href = code.data; // Navigate immediately to session
      return;
    }
  }
  requestAnimationFrame(scanFrame);
}
```

---

### Feature 4: How File Transferring is Done (End-to-End)

File transfer consists of three coordinated stages: **Upload**, **Live Sync**, and **Download**.

```
Client A (Sender)                     Relay Server                     Client B (Receiver)
       │                                   │                                    │
       │─── 1. POST /upload (FormData) ───>│                                    │
       │    [Tracks progress bar via XHR]  │                                    │
       │                                   │─── Saves file in isolated folder ─>│
       │                                   │                                    │
       │                                   │<── 2. GET /files (polling 2.5s) ───│
       │                                   │─── Returns updated files list ────>│
       │                                   │                                    │
       │                                   │<── 3. GET /download/file_id ───────│
       │                                   │─── Streams file / ZIP to disk ────>│
```

#### Step 1: Uploading (Client-Side)
Files are uploaded asynchronously using `XMLHttpRequest` with real-time percentage tracking:
```javascript
// static/js/app.js
const formData = new FormData();
formData.append('file', file);
formData.append('csrf_token', csrfToken);

const xhr = new XMLHttpRequest();
xhr.open('POST', `/s/${sessionId}/upload`, true);
xhr.setRequestHeader('X-CSRF-Token', csrfToken);

// Real-time progress bar calculation
xhr.upload.onprogress = (e) => {
  if (e.lengthComputable) {
    const percent = Math.round((e.loaded / e.total) * 100);
    progressBar.style.width = `${percent}%`;
    statusText.textContent = `${percent}%`;
  }
};
xhr.send(formData);
```

#### Step 2: Receiving & Saving on Backend (`app.py`)
The server receives the file, checks security boundaries, and stores it in the session sandbox:
```python
@app.route("/s/<session_id>/upload", methods=["POST"])
def upload_file(session_id):
    session_data = get_session(session_id)
    
    # 1. CSRF Verification
    submitted_csrf = request.headers.get("X-CSRF-Token")
    if submitted_csrf != session_data["csrf_token"]:
        return jsonify({"error": "Invalid CSRF token"}), 403

    uploaded_files = request.files.getlist("file")
    for file_storage in uploaded_files:
        safe_name = secure_filename(file_storage.filename)
        file_id = secrets.token_hex(8)
        stored_filename = f"{file_id}_{safe_name}"
        destination = os.path.join(session_data["folder"], stored_filename)

        # 2. Path Traversal check
        if not is_safe_path(session_data["folder"], destination):
            return jsonify({"error": "Path traversal detected"}), 400

        # 3. Write file into isolated session directory
        file_storage.save(destination)

        # 4. Save metadata to in-memory session registry
        session_data["files"][file_id] = {
            "id": file_id,
            "filename": stored_filename,
            "display_name": file_storage.filename,
            "size_bytes": os.path.getsize(destination),
            "download_url": url_for("download_file", session_id=session_id, file_id=file_id)
        }

    return jsonify({"success": True})
```

#### Step 3: Real-Time Synchronization Across Devices
All connected devices poll the `/s/<session_id>/files` endpoint every 2.5 seconds to receive immediate updates when new files are added:
```javascript
// static/js/app.js
async function fetchSessionFiles() {
  const res = await fetch(`/s/${sessionId}/files`);
  const data = await res.json();
  renderFileList(data.files);
  updateCountdown(data.remaining_seconds);
}
setInterval(fetchSessionFiles, 2500);
```

#### Step 4: Single File & In-Memory Batch ZIP Downloads
- **Individual Download**: Uses Flask's `send_file` with the original filename preserved via `download_name`.
- **Download All (.zip)**: Instead of creating a physical `.zip` file on disk, Relay streams an archive generated completely in-memory using `io.BytesIO`:

```python
# app.py
@app.route("/s/<session_id>/download-all")
def download_all(session_id):
    session_data = get_session(session_id)
    
    # Pack files in RAM - Never pollutes the session folder!
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for file_id, file_meta in session_data["files"].items():
            file_path = os.path.join(session_data["folder"], file_meta["filename"])
            if is_safe_path(session_data["folder"], file_path):
                zipf.write(file_path, arcname=file_meta["display_name"])

    zip_buffer.seek(0)
    return send_file(
        zip_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"transfer_{session_id[:8]}.zip"
    )
```

---

### Feature 5: Security Architecture & Protections

Relay incorporates layered defense mechanisms against common web vulnerabilities:

| Vulnerability Threat | Defense Mechanism | Where It Is Enforced |
| :--- | :--- | :--- |
| **Cross-Session Leakage** | Isolated `tempfile.mkdtemp` folder + UUID4 token per transfer | `SessionManager.create_session()` |
| **Path Traversal (`../../`)** | `is_safe_path()` using `os.path.commonpath` | Upload & Download handlers |
| **Malicious Filenames** | `werkzeug.utils.secure_filename` + random hex prefix | `upload_file()` |
| **Denial of Service (OOM)** | Flask `MAX_CONTENT_LENGTH_MB` (250MB limit) | `app.py` configuration |
| **CSRF Exploitation** | Per-session 16-byte cryptographic token | `X-CSRF-Token` headers |
| **Brute-Force Code Guessing** | Sliding-window IP rate limiter (max 10 tries/min) | `check_join_rate_limit()` |
| **Data Lingering on Server** | Automatic 5-minute wipe + Immediate "End Session" deletion | `_cleanup_dir()` with `shutil.rmtree` |
| **Unauthorized LAN Interception** | Optional 4-digit PIN authentication | `verify_pin()` with session cookie |

#### Path Traversal Protection Code (`app.py`):
```python
def is_safe_path(base_dir, path, follow_symlinks=True):
    """Guarantees path remains strictly inside base_dir."""
    if follow_symlinks:
        matchpath = os.path.realpath(path)
        basepath = os.path.realpath(base_dir)
    else:
        matchpath = os.path.abspath(path)
        basepath = os.path.abspath(base_dir)
    return basepath == os.path.commonpath((basepath, matchpath))
```

#### Brute-Force Rate Limiting Code (`app.py`):
```python
JOIN_RATE_LIMIT = 10     # Max 10 attempts
JOIN_RATE_WINDOW = 60    # Per 60 seconds

def check_join_rate_limit(client_ip):
    now = time.time()
    with join_rate_lock:
        timestamps = JOIN_ATTEMPTS.get(client_ip, [])
        timestamps = [t for t in timestamps if now - t < JOIN_RATE_WINDOW]
        if len(timestamps) >= JOIN_RATE_LIMIT:
            return False
        timestamps.append(now)
        JOIN_ATTEMPTS[client_ip] = timestamps
        return True
```

---

### Feature 6: Progressive Web App (PWA) & Offline Capabilities

#### What it does:
Users on Windows, Android, or iOS can install Relay as a native-like desktop or mobile app directly from the browser without compiling `.exe` or downloading an `.apk`. Once installed, the "Install App" button automatically vanishes.

#### Technologies Used:
- **`manifest.json`**: Defines display mode (`"display": "standalone"`), application icons, theme colors, and orientation.
- **`service-worker.js`**: Intercepts network requests and caches static assets for instant load and offline resilience.
- **`install.js`**: Manages the `beforeinstallprompt` browser event, tracks installation state in `localStorage`, and hides install prompts permanently.
- **CSS Media Queries**: `@media all and (display-mode: standalone)` cleanly hides install UI elements inside the installed app window.

#### How the "Install App" Option Disappears After Installation (`install.js` & `style.css`):
```javascript
// static/js/install.js
function isAppInstalled() {
  return (
    window.matchMedia('(display-mode: standalone)').matches ||
    window.navigator.standalone === true ||
    localStorage.getItem('relay_app_installed') === '1'
  );
}

function markAppInstalled() {
  localStorage.setItem('relay_app_installed', '1');
  document.documentElement.classList.add('app-installed');
  document.getElementById('navInstallBtn').style.display = 'none';
  document.getElementById('pwaInstallModal').style.display = 'none';
}

// Automatically fires when user clicks "Install" in browser prompt
window.addEventListener('appinstalled', markAppInstalled);
```

```css
/* static/css/style.css */
html.app-installed .nav-install-btn,
html.app-installed #pwaInstallModal,
@media all and (display-mode: standalone) {
  .nav-install-btn,
  #pwaInstallModal {
    display: none !important;
  }
}
```

---

## 3. Technology Stack Summary

| Layer | Technology | Primary Role in Relay |
| :--- | :--- | :--- |
| **Backend Framework** | Python 3 + Flask | Request routing, streaming file responses, API endpoints |
| **Web Server** | Gunicorn (1 worker, 8 threads) | Concurrent request handling without cross-process isolation bugs |
| **Temporary Filesystem** | `tempfile` + `shutil` | Creating and safely wiping ephemeral session folders |
| **QR Code Encoding** | `qrcode` + `io.BytesIO` | In-memory dynamic QR code generation |
| **QR Code Decoding** | `jsQR` (client-side JS) | Camera-based real-time barcode recognition |
| **Archiving** | Python `zipfile` | In-memory `.zip` compression for multi-file downloads |
| **Frontend Styling** | Vanilla CSS3 (Custom Glassmorphism) | Fast load time, fluid dark mode, zero bulky CSS frameworks |
| **Offline & PWA** | Service Worker + Web Manifest | Standalone window execution and static caching |
| **Audio Feedback** | Web Audio API (`AudioContext`) | Synthetic scan chime without loading audio files |

---

## 4. End-to-End User Flow Walkthrough

1. **User A opens Relay (`GET /`)**:
   - Clicks **"Start a Transfer"** (`GET /new`).
   - Server initializes an isolated session directory (`/tmp/session_abcd1234/`).
   - Browser displays dynamic QR code and 6-character code `7M2-9KX`.
2. **User B joins the session**:
   - Option 1: Scans QR code using phone camera or Relay in-app scanner.
   - Option 2: Types `7M2-9KX` on landing page and clicks "Join".
   - Server redirects User B to `/s/abcd1234`.
3. **Transferring Files**:
   - User A or User B drops files into the dropzone.
   - `XMLHttpRequest` streams files with real-time percentage indicators.
   - Files are saved inside `/tmp/session_abcd1234/` with sanitized names.
   - Both devices poll `/s/abcd1234/files` every 2.5s and immediately display the new files.
4. **Completion or Cleanup**:
   - Users click "Download All (.zip)" to download an in-memory zip archive.
   - Users click "End Session", or the 5-minute timer expires.
   - Server executes `shutil.rmtree('/tmp/session_abcd1234/')` — all files are permanently wiped.
