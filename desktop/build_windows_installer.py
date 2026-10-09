"""
Build script to compile Relay Windows Application and Windows Setup Installer.
Generates:
1. Relay.exe (standalone desktop application)
2. static/downloads/Relay-Setup.exe (official Windows Setup Installer)
"""
import os
import sys
import shutil
import zipfile
import subprocess

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DESKTOP_DIR = os.path.join(PROJECT_ROOT, "desktop")
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")
BUILD_DIR = os.path.join(PROJECT_ROOT, "build")
STATIC_DOWNLOADS = os.path.join(PROJECT_ROOT, "static", "downloads")

def run():
    os.chdir(PROJECT_ROOT)
    os.makedirs(STATIC_DOWNLOADS, exist_ok=True)
    icon_path = os.path.join(PROJECT_ROOT, "static", "app_icon.ico")

    EXCLUDES = [
        "scipy", "numpy", "pandas", "matplotlib", "IPython", "ipykernel", "jupyter",
        "tornado", "zmq", "pyzmq", "sqlalchemy", "tensorflow", "torch", "jax",
        "mediapipe", "cv2", "sklearn", "xgboost", "sounddevice", "fpdf2",
        "pygments", "cryptography", "grpc", "google"
    ]

    print("[1/4] Building Relay.exe desktop binary...")
    relay_py_cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name", "Relay",
        "--icon", icon_path,
        "--add-data", f"{os.path.join(PROJECT_ROOT, 'templates')};templates",
        "--add-data", f"{os.path.join(PROJECT_ROOT, 'static')};static",
    ]
    for mod in EXCLUDES:
        relay_py_cmd.extend(["--exclude-module", mod])
    relay_py_cmd.append(os.path.join(DESKTOP_DIR, "relay_desktop.py"))
    subprocess.run(relay_py_cmd, check=True)

    built_relay_exe = os.path.join(DIST_DIR, "Relay.exe")
    if not os.path.exists(built_relay_exe):
        raise FileNotFoundError(f"Failed to find built {built_relay_exe}")

    print("[2/4] Packaging Relay payload...")
    payload_zip = os.path.join(DESKTOP_DIR, "payload.zip")
    with zipfile.ZipFile(payload_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(built_relay_exe, arcname="Relay.exe")
        zf.write(icon_path, arcname="app_icon.ico")

    print("[3/4] Building Relay-Setup.exe Windows Installer...")
    installer_cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name", "Relay-Setup",
        "--icon", icon_path,
        "--add-data", f"{payload_zip};.",
        "--add-data", f"{icon_path};.",
        os.path.join(DESKTOP_DIR, "installer_gui.py")
    ]
    subprocess.run(installer_cmd, check=True)

    built_setup_exe = os.path.join(DIST_DIR, "Relay-Setup.exe")
    if not os.path.exists(built_setup_exe):
        raise FileNotFoundError(f"Failed to find built {built_setup_exe}")

    print("[4/4] Publishing Relay-Setup.exe to static/downloads...")
    target_installer = os.path.join(STATIC_DOWNLOADS, "Relay-Setup.exe")
    shutil.copy2(built_setup_exe, target_installer)

    # Clean up temporary payload zip
    if os.path.exists(payload_zip):
        os.remove(payload_zip)

    file_size_mb = os.path.getsize(target_installer) / (1024 * 1024)
    print(f"[OK] Windows Installer built successfully!")
    print(f"    Location: {target_installer}")
    print(f"    Size: {file_size_mb:.2f} MB")

if __name__ == "__main__":
    run()
