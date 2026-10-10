# Relay — Session-Based File Transfer

Relay is a fast, secure, and privacy-focused file sharing web application built for instant cross-device transfers. Whether transferring between phones, laptops, tablets, or desktops, Relay works directly in your browser with zero sign-ups, zero cables, and complete session isolation.

---

## What Relay is Used For

Relay allows two or more devices to exchange photos, videos, documents, and large files seamlessly over your local Wi-Fi network or the web. 

It eliminates the friction of email size limits, messaging app compression, USB flash drives, or installing third-party desktop software. Simply open Relay, start a transfer session, connect your second device via a QR code or short join code, and share files instantly.

---

## Key Features

- **Instant Dual-Device Pairing**:
  - **Dynamic QR Code**: Scan the session QR code using your phone camera or the built-in scanner to join in one second.
  - **6-Character Join Code**: Easily join from laptops or desktops by typing a short, human-friendly code (e.g. `ABC-XYZ`) without needing a camera.
- **Total Session Isolation**:
  - Every transfer operates inside a unique, temporary cryptographic sandbox (`UUID4`).
  - No global shared folder: files in your session are completely invisible and inaccessible to any other user.
- **Web App (PWA) for Windows & Android**:
  - Install Relay directly from your browser to your Windows desktop or Android home screen with a single click.
  - Launches in a dedicated, distraction-free app window.
  - The "Install App" button automatically disappears once installed.
- **In-App Camera QR Scanner**:
  - Scan another device's Relay screen directly within the app using live camera preview, automatic alignment, and torch/camera flip controls.
- **Multi-File Drag & Drop Uploads**:
  - Queue multiple files simultaneously with individual real-time progress bars, transfer speeds, and file size indicators.
- **Single & Batch Downloads**:
  - Download files individually with preserved filenames, or download all files together as a single `.zip` archive with one click.
- **Ephemeral & Auto-Cleaning Storage**:
  - Sessions automatically expire and self-destruct after 5 minutes (extendable with "+5 Mins").
  - An "End Session" button allows either party to immediately wipe all uploaded files from disk on demand.
- **Optional PIN Protection**:
  - Secure sensitive transfers with an optional 4-digit session access PIN.

---

## Technologies Used for Transferring

Relay combines modern web platform APIs and lightweight backend architecture to perform fast, secure transfers:

1. **Progressive Web App (PWA) Standards**:
   - **Web App Manifest (`manifest.json`) & Service Worker (`service-worker.js`)**: Powers standalone window execution on Windows, Android, and iOS with asset caching and instant app launching, removing the need for traditional executable setup files.
2. **Local Network & HTTP Streaming Transfer**:
   - **LAN / Local Wi-Fi Auto-Discovery**: Detects local network IP addresses to transfer files at maximum Wi-Fi speeds without routing data across external servers when on the same network.
   - **Chunked HTTP Multi-Part Streams**: Python Flask backend handles multi-file streams with strict file sanitization (`secure_filename`) and size enforcement.
3. **Computer Vision & In-Memory QR Code Generation**:
   - **jsQR Engine & HTML5 MediaDevices (`getUserMedia`)**: Performs client-side, zero-latency barcode scanning directly from live camera video frames.
   - **In-Memory QR Rendering**: Dynamic QR codes are generated directly in memory via Python's `qrcode` library on demand without writing static image files to disk.
4. **Real-Time Client-Server State Synchronization**:
   - Uses non-blocking asynchronous requests (`XMLHttpRequest` with `upload.onprogress`) and live JSON polling to display incoming files on all connected devices in real time without refreshing the page.
5. **Sandboxed Filesystem & In-Memory Compression**:
   - **Ephemeral Directory Sandboxing**: Temporary directories (`tempfile.mkdtemp`) created per session and monitored by an automatic background sweeper thread.
   - **In-Memory ZIP Streaming**: Multi-file batch archives are packed in-memory via Python's `zipfile` and `io.BytesIO` without writing temporary archives to storage.
