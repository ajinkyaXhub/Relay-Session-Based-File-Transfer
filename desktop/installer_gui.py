"""
Relay Windows App Installer (Setup Wizard)
Extracts Relay files, creates Desktop & Start Menu shortcuts,
registers in Windows Add/Remove Programs, and launches Relay.
"""
import os
import sys
import zipfile
import subprocess
import tempfile
import winreg
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Resolve base directories
if getattr(sys, "frozen", False):
    BUNDLE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
else:
    BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_INSTALL_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "Programs",
    "Relay"
)

def create_windows_shortcut(target, shortcut_path, icon_path=None, description="Relay - File Transfer"):
    """Creates a Windows .lnk shortcut using built-in cscript without external dependencies."""
    try:
        os.makedirs(os.path.dirname(shortcut_path), exist_ok=True)
        vbs_lines = [
            'Set oWS = WScript.CreateObject("WScript.Shell")',
            f'Set oLink = oWS.CreateShortcut("{shortcut_path}")',
            f'oLink.TargetPath = "{target}"',
            f'oLink.WorkingDirectory = "{os.path.dirname(target)}"',
            f'oLink.Description = "{description}"'
        ]
        if icon_path and os.path.exists(icon_path):
            vbs_lines.append(f'oLink.IconLocation = "{icon_path}"')
        vbs_lines.append('oLink.Save')

        tmp_vbs = os.path.join(tempfile.gettempdir(), f"relay_sc_{os.getpid()}.vbs")
        with open(tmp_vbs, "w", encoding="utf-8") as f:
            f.write("\n".join(vbs_lines))

        subprocess.run(["cscript.exe", "//Nologo", tmp_vbs], check=True, creationflags=0x08000000)
        if os.path.exists(tmp_vbs):
            os.remove(tmp_vbs)
        return True
    except Exception as e:
        print(f"[!] Shortcut error: {e}")
        return False

def register_uninstaller(install_dir, exe_path, icon_path):
    """Registers Relay in Windows Add/Remove Programs (Settings > Apps)."""
    try:
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\Relay"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "Relay File Transfer")
            winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, "1.0.0")
            winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "Relay Team")
            winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, install_dir)
            if icon_path and os.path.exists(icon_path):
                winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, icon_path)
            
            uninstall_bat = os.path.join(install_dir, "uninstall.bat")
            winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'cmd.exe /c "{uninstall_bat}"')
            winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
    except Exception as e:
        print(f"[!] Registry registration warning: {e}")

class RelayInstallerGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Relay Setup — Windows App Installer")
        self.root.geometry("520x460")
        self.root.minsize(500, 440)
        self.root.configure(bg="#070b14")

        icon_file = os.path.join(BUNDLE_DIR, "app_icon.ico")
        if os.path.exists(icon_file):
            try:
                self.root.iconbitmap(icon_file)
            except Exception:
                pass

        self.install_dir_var = tk.StringVar(value=DEFAULT_INSTALL_DIR)
        self.desktop_sc_var = tk.BooleanVar(value=True)
        self.startmenu_sc_var = tk.BooleanVar(value=True)
        self.launch_after_var = tk.BooleanVar(value=True)

        self._build_ui()

    def _build_ui(self):
        # Header banner
        header = tk.Frame(self.root, bg="#0f172a", padx=24, pady=18, highlightbackground="#06b6d4", highlightthickness=1)
        header.pack(fill=tk.X)

        title = tk.Label(
            header,
            text="Relay for Windows",
            font=("Segoe UI", 16, "bold"),
            fg="#f8fafc",
            bg="#0f172a"
        )
        title.pack(anchor="w")

        subtitle = tk.Label(
            header,
            text="Install the desktop app for instant, isolated Wi-Fi & web transfers",
            font=("Segoe UI", 9),
            fg="#94a3b8",
            bg="#0f172a"
        )
        subtitle.pack(anchor="w", pady=(3, 0))

        # Main Body
        body = tk.Frame(self.root, bg="#070b14", padx=24, pady=18)
        body.pack(fill=tk.BOTH, expand=True)

        # Destination Folder Selector
        dest_lbl = tk.Label(
            body,
            text="Installation Folder:",
            font=("Segoe UI", 10, "bold"),
            fg="#e2e8f0",
            bg="#070b14"
        )
        dest_lbl.pack(anchor="w", pady=(0, 6))

        dest_row = tk.Frame(body, bg="#070b14")
        dest_row.pack(fill=tk.X, pady=(0, 16))

        self.dest_entry = tk.Entry(
            dest_row,
            textvariable=self.install_dir_var,
            font=("Segoe UI", 9),
            bg="#1e293b",
            fg="#f8fafc",
            insertbackground="#38bdf8",
            relief=tk.FLAT,
            highlightbackground="#334155",
            highlightthickness=1,
            padx=8
        )
        self.dest_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5)

        browse_btn = tk.Button(
            dest_row,
            text="Browse...",
            font=("Segoe UI", 9),
            bg="#334155",
            fg="#ffffff",
            activebackground="#475569",
            relief=tk.FLAT,
            padx=12,
            pady=4,
            command=self.browse_folder
        )
        browse_btn.pack(side=tk.LEFT, padx=(8, 0))

        # Options Checkboxes
        opts_lbl = tk.Label(
            body,
            text="Installation Options:",
            font=("Segoe UI", 10, "bold"),
            fg="#e2e8f0",
            bg="#070b14"
        )
        opts_lbl.pack(anchor="w", pady=(0, 6))

        cb_desktop = tk.Checkbutton(
            body,
            text="Create Desktop Shortcut",
            variable=self.desktop_sc_var,
            font=("Segoe UI", 9),
            fg="#cbd5e1",
            bg="#070b14",
            activebackground="#070b14",
            activeforeground="#38bdf8",
            selectcolor="#0f172a"
        )
        cb_desktop.pack(anchor="w")

        cb_start = tk.Checkbutton(
            body,
            text="Create Start Menu Shortcut",
            variable=self.startmenu_sc_var,
            font=("Segoe UI", 9),
            fg="#cbd5e1",
            bg="#070b14",
            activebackground="#070b14",
            activeforeground="#38bdf8",
            selectcolor="#0f172a"
        )
        cb_start.pack(anchor="w")

        cb_launch = tk.Checkbutton(
            body,
            text="Launch Relay when installation completes",
            variable=self.launch_after_var,
            font=("Segoe UI", 9),
            fg="#cbd5e1",
            bg="#070b14",
            activebackground="#070b14",
            activeforeground="#38bdf8",
            selectcolor="#0f172a"
        )
        cb_launch.pack(anchor="w", pady=(0, 16))

        # Progress bar & Status
        self.status_lbl = tk.Label(
            body,
            text="Ready to install.",
            font=("Segoe UI", 9),
            fg="#94a3b8",
            bg="#070b14"
        )
        self.status_lbl.pack(anchor="w", pady=(0, 6))

        style = ttk.Style()
        style.theme_use('default')
        style.configure(
            "Cyan.Horizontal.TProgressbar",
            troughcolor="#1e293b",
            background="#06b6d4"
        )

        self.progress = ttk.Progressbar(
            body,
            style="Cyan.Horizontal.TProgressbar",
            orient="horizontal",
            mode="determinate"
        )
        self.progress.pack(fill=tk.X, pady=(0, 16))

        # Bottom Bar Buttons
        btn_frame = tk.Frame(self.root, bg="#0f172a", padx=24, pady=14)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)

        self.cancel_btn = tk.Button(
            btn_frame,
            text="Cancel",
            font=("Segoe UI", 9),
            bg="#1e293b",
            fg="#94a3b8",
            activebackground="#334155",
            relief=tk.FLAT,
            padx=14,
            pady=6,
            command=self.root.destroy
        )
        self.cancel_btn.pack(side=tk.RIGHT, padx=(8, 0))

        self.install_btn = tk.Button(
            btn_frame,
            text="Install Relay",
            font=("Segoe UI", 10, "bold"),
            bg="#06b6d4",
            fg="#070b14",
            activebackground="#0891b2",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            padx=20,
            pady=6,
            cursor="hand2",
            command=self.start_install
        )
        self.install_btn.pack(side=tk.RIGHT)

    def browse_folder(self):
        selected = filedialog.askdirectory(initialdir=self.install_dir_var.get())
        if selected:
            self.install_dir_var.set(os.path.join(selected, "Relay"))

    def start_install(self):
        self.install_btn.config(state=tk.DISABLED)
        self.dest_entry.config(state=tk.DISABLED)
        self.status_lbl.config(text="Preparing installation directory...", fg="#38bdf8")
        self.progress["value"] = 10

        import threading
        threading.Thread(target=self._run_install_worker, daemon=True).start()

    def _run_install_worker(self):
        try:
            target_dir = self.install_dir_var.get().strip()
            os.makedirs(target_dir, exist_ok=True)

            self.root.after(0, lambda: self.status_lbl.config(text="Extracting application files..."))
            self.root.after(0, lambda: self.progress.config(value=30))

            # Look for payload.zip in bundle or current directory
            payload_zip = os.path.join(BUNDLE_DIR, "payload.zip")
            if os.path.exists(payload_zip):
                with zipfile.ZipFile(payload_zip, "r") as zf:
                    zf.extractall(target_dir)
            else:
                # Fallback: copy app files directly if running in loose mode
                import shutil
                source_exe = os.path.join(BUNDLE_DIR, "Relay.exe")
                if os.path.exists(source_exe):
                    shutil.copy2(source_exe, os.path.join(target_dir, "Relay.exe"))

            # Ensure icon exists in target dir
            target_icon = os.path.join(target_dir, "app_icon.ico")
            bundle_icon = os.path.join(BUNDLE_DIR, "app_icon.ico")
            if os.path.exists(bundle_icon) and not os.path.exists(target_icon):
                import shutil
                shutil.copy2(bundle_icon, target_icon)

            self.root.after(0, lambda: self.progress.config(value=60))
            self.root.after(0, lambda: self.status_lbl.config(text="Creating desktop & menu shortcuts..."))

            exe_path = os.path.join(target_dir, "Relay.exe")

            # Create Desktop Shortcut
            if self.desktop_sc_var.get():
                desktop_folder = os.path.join(os.environ["USERPROFILE"], "Desktop")
                desktop_sc = os.path.join(desktop_folder, "Relay.lnk")
                create_windows_shortcut(exe_path, desktop_sc, target_icon, "Relay - Fast Isolated File Transfer")

            # Create Start Menu Shortcut
            if self.startmenu_sc_var.get():
                appdata = os.environ.get("APPDATA", os.path.expanduser("~\\AppData\\Roaming"))
                start_folder = os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Relay")
                start_sc = os.path.join(start_folder, "Relay.lnk")
                create_windows_shortcut(exe_path, start_sc, target_icon, "Relay - Fast Isolated File Transfer")

            self.root.after(0, lambda: self.progress.config(value=80))
            self.root.after(0, lambda: self.status_lbl.config(text="Registering Windows uninstaller..."))

            # Write clean uninstaller script
            uninstaller_path = os.path.join(target_dir, "uninstall.bat")
            with open(uninstaller_path, "w", encoding="utf-8") as f:
                f.write(f"""@echo off
title Uninstalling Relay
echo ===================================
echo     Uninstalling Relay App
echo ===================================
echo Removing shortcuts...
del "%USERPROFILE%\\Desktop\\Relay.lnk" 2>nul
rd /s /q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Relay" 2>nul
echo Removing Windows uninstall registry...
reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Relay" /f 2>nul
echo Cleaning up application files...
cd /d "%TEMP%"
timeout /t 1 /nobreak >nul
rd /s /q "{target_dir}" 2>nul
echo.
echo Relay has been successfully removed from your computer.
echo.
pause
""")

            # Register in Windows Apps
            register_uninstaller(target_dir, exe_path, target_icon)

            self.root.after(0, lambda: self.progress.config(value=100))
            self.root.after(0, lambda: self.status_lbl.config(text="Relay installed successfully!", fg="#10b981"))
            self.root.after(0, lambda: self._on_install_complete(target_dir, exe_path))

        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Installation Error", f"Failed to install Relay:\n{e}"))
            self.root.after(0, lambda: self.install_btn.config(state=tk.NORMAL))

    def _on_install_complete(self, target_dir, exe_path):
        self.install_btn.config(
            text="Finish",
            state=tk.NORMAL,
            command=lambda: self._finish(exe_path)
        )
        self.cancel_btn.pack_forget()

    def _finish(self, exe_path):
        if self.launch_after_var.get() and os.path.exists(exe_path):
            try:
                subprocess.Popen([exe_path], cwd=os.path.dirname(exe_path))
            except Exception as e:
                print(f"[!] Launch error: {e}")
        self.root.destroy()

def main():
    installer = RelayInstallerGUI()
    installer.root.mainloop()

if __name__ == "__main__":
    main()
