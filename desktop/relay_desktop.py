"""
Relay - Native Windows Desktop Companion Application
Launches local isolated file transfer server and provides a desktop control window.
"""
import os
import sys
import threading
import time
import socket
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox

# Resolve base directories
if getattr(sys, "frozen", False):
    BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
else:
    BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from werkzeug.serving import make_server
from app import app, get_local_ip, cleanup_all_sessions

class ServerThread(threading.Thread):
    def __init__(self, app_instance, host, port):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.server = make_server(host, port, app_instance, threaded=True)
        self.ctx = app_instance.app_context()
        self.ctx.push()

    def run(self):
        try:
            self.server.serve_forever()
        except Exception:
            pass

    def shutdown(self):
        try:
            self.server.shutdown()
        except Exception:
            pass

def find_available_port(preferred=5000):
    for port in range(preferred, preferred + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    return preferred

class RelayDesktopWindow:
    def __init__(self, port):
        self.port = port
        self.local_ip = get_local_ip()
        self.local_url = f"http://127.0.0.1:{self.port}"
        self.network_url = f"http://{self.local_ip}:{self.port}"

        self.root = tk.Tk()
        self.root.title("Relay — Desktop File Transfer")
        self.root.geometry("440x360")
        self.root.minsize(400, 320)
        self.root.configure(bg="#070b14")

        # Set window icon if available
        icon_path = os.path.join(BASE_DIR, "static", "app_icon.ico")
        if os.path.exists(icon_path):
            try:
                self.root.iconbitmap(icon_path)
            except Exception:
                pass

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _build_ui(self):
        container = tk.Frame(self.root, bg="#070b14", padx=24, pady=20)
        container.pack(fill=tk.BOTH, expand=True)

        # Header Title
        title_frame = tk.Frame(container, bg="#070b14")
        title_frame.pack(fill=tk.X, pady=(0, 16))

        title_lbl = tk.Label(
            title_frame,
            text="Relay File Transfer",
            font=("Segoe UI", 16, "bold"),
            fg="#f8fafc",
            bg="#070b14"
        )
        title_lbl.pack(anchor="w")

        subtitle_lbl = tk.Label(
            title_frame,
            text="Local Wi-Fi & Web Session-Isolated Transfer",
            font=("Segoe UI", 9),
            fg="#94a3b8",
            bg="#070b14"
        )
        subtitle_lbl.pack(anchor="w", pady=(2, 0))

        # Status Card
        card = tk.Frame(
            container,
            bg="#0f172a",
            highlightbackground="#06b6d4",
            highlightthickness=1,
            padx=16,
            pady=14
        )
        card.pack(fill=tk.X, pady=(0, 16))

        status_row = tk.Frame(card, bg="#0f172a")
        status_row.pack(fill=tk.X)

        dot = tk.Label(status_row, text="●", font=("Segoe UI", 12), fg="#10b981", bg="#0f172a")
        dot.pack(side=tk.LEFT, padx=(0, 6))

        status_lbl = tk.Label(
            status_row,
            text=f"Server Active on Port {self.port}",
            font=("Segoe UI", 10, "bold"),
            fg="#f8fafc",
            bg="#0f172a"
        )
        status_lbl.pack(side=tk.LEFT)

        url_lbl = tk.Label(
            card,
            text=f"LAN Access: {self.network_url}",
            font=("Segoe UI", 9),
            fg="#38bdf8",
            bg="#0f172a"
        )
        url_lbl.pack(anchor="w", pady=(8, 0))

        # Action Buttons
        btn_open = tk.Button(
            container,
            text="Open Relay in Browser",
            font=("Segoe UI", 10, "bold"),
            bg="#06b6d4",
            fg="#070b14",
            activebackground="#0891b2",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            padx=12,
            pady=8,
            cursor="hand2",
            command=self.open_browser
        )
        btn_open.pack(fill=tk.X, pady=(0, 10))

        btn_copy = tk.Button(
            container,
            text="Copy Network Address for Other Devices",
            font=("Segoe UI", 9),
            bg="#1e293b",
            fg="#e2e8f0",
            activebackground="#334155",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            padx=12,
            pady=7,
            cursor="hand2",
            command=self.copy_link
        )
        btn_copy.pack(fill=tk.X, pady=(0, 10))

        # Footer / Exit
        footer_frame = tk.Frame(container, bg="#070b14")
        footer_frame.pack(fill=tk.X, side=tk.BOTTOM)

        btn_exit = tk.Button(
            footer_frame,
            text="Exit Relay",
            font=("Segoe UI", 9),
            bg="#070b14",
            fg="#ef4444",
            activebackground="#1e293b",
            activeforeground="#f87171",
            relief=tk.FLAT,
            cursor="hand2",
            command=self.on_close
        )
        btn_exit.pack(side=tk.RIGHT)

    def open_browser(self):
        webbrowser.open(self.local_url)

    def copy_link(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.network_url)
        messagebox.showinfo("Copied", f"Network link copied to clipboard:\n{self.network_url}")

    def on_close(self):
        if messagebox.askokcancel("Quit Relay", "Do you want to stop the Relay server and exit?"):
            self.root.destroy()

def main():
    port = find_available_port(5000)
    server_thread = ServerThread(app, "0.0.0.0", port)
    server_thread.start()

    time.sleep(0.3)
    webbrowser.open(f"http://127.0.0.1:{port}")

    app_win = RelayDesktopWindow(port)
    app_win.root.mainloop()

    # Clean shutdown on window close
    cleanup_all_sessions()
    server_thread.shutdown()

if __name__ == "__main__":
    main()
