#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Python Apps Launcher — v4 (UI refresh + context menu)
-----------------------------------------------------
What's new in v4 (compared to v3):
- Modernized Tk/ttk look & feel (Segoe UI, larger row height, subtle colors)
- Search/Filter box for projects (instant filtering)
- Persistent settings (remembers last root folder & "always install requirements" flag)
- Right-click context menu on project rows:
    • Start App
    • Stop App
    • Rebuild venv
    • Edit Entrypoint/Args
    • Open Folder
    • Copy Path
    • (bonus) Clear Logs
- Color-tagged status in the table (Running, Idle, Preparing, Error, etc.)
- Quality-of-life tweaks: Clear Logs button, keyboard shortcuts (F5 = Refresh, Ctrl+F = focus search)
- Safer logging and minor reliability fixes

No external dependencies. Pure standard library.
"""

import os
import sys
import threading
import subprocess
import queue
import shutil
from pathlib import Path
import configparser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

APP_TITLE = "Python Apps Launcher"
DEFAULT_ROOT = r"C:\Users\anass\Desktop\Python-Project"

ENTRY_CANDIDATES = ["app.py", "main.py", "run.py", "server.py", "wsgi.py"]
VENV_NAMES = [".venv", "venv", "env"]
IS_WINDOWS = (os.name == "nt")
CREATE_NEW_CONSOLE = 0x00000010 if IS_WINDOWS else 0

CONFIG_PATH = Path.home() / ".python_apps_launcher.ini"
CONFIG_SECTION = "launcher"

def stream_proc(cmd, cwd, log_put, env=None):
    try:
        p = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            env=env or os.environ.copy(),
        )
        for line in p.stdout:
            log_put(line.rstrip("\n"))
        p.wait()
        return p.returncode
    except FileNotFoundError as e:
        log_put(f"Command not found: {cmd[0]} ({e})")
        return 127
    except Exception as e:
        log_put(f"Error running command: {e}")
        return 1

def read_pyvenv_home(venv_dir: Path):
    """Return 'home' from pyvenv.cfg if present, else ''."""
    cfg = venv_dir / "pyvenv.cfg"
    try:
        if cfg.exists():
            for line in cfg.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.lower().startswith("home"):
                    return line.split("=", 1)[1].strip().strip('"')
    except Exception:
        pass
    return ""

def is_valid_venv_python(python_exe: Path):
    """Check venv python by attempting a trivial command and validating pyvenv.cfg home existence."""
    if not python_exe.exists():
        return False
    home = read_pyvenv_home(python_exe.parent.parent)
    if home and not Path(home).exists():
        return False
    try:
        rc = subprocess.call([str(python_exe), "-V"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return rc == 0
    except Exception:
        return False

class Project:
    def __init__(self, path: Path):
        self.path = path
        self.name = path.name
        self.entrypoint = self._detect_entrypoint()
        self.args = ""
        self.requirements = self._detect_requirements()
        self.venv_python = self._detect_venv_python()
        self.proc = None
        self.status = tk.StringVar(value="Idle")
        self.selected = tk.BooleanVar(value=False)
        self.install_on_run = tk.BooleanVar(value=True)
        self.created_venv = False

    def _detect_entrypoint(self):
        for cand in ENTRY_CANDIDATES:
            p = self.path / cand
            if p.exists():
                return cand
        py_files = [p.name for p in self.path.glob("*.py") if p.is_file() and not p.name.startswith("_")]
        return py_files[0] if py_files else ""

    def _detect_requirements(self):
        for name in ["requirements.txt", "requirement.txt", "requirements-dev.txt"]:
            p = self.path / name
            if p.exists():
                return p.name
        return ""

    def _prefer_root_venv(self):
        for vname in VENV_NAMES:
            vp = self.path / vname / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")
            if vp.exists():
                return vp
        return None

    def _find_shallow_venv(self):
        for sub in self.path.iterdir():
            if sub.is_dir() and not sub.name.startswith("."):
                for vname in VENV_NAMES:
                    vp = sub / vname / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")
                    if vp.exists():
                        return vp
        return None

    def _detect_venv_python(self):
        vp = self._prefer_root_venv()
        if vp:
            return str(vp)
        vp = self._find_shallow_venv()
        if vp:
            return str(vp)
        return ""

    def _backup_dir(self, d: Path, log):
        try:
            suffix = d.name + ".broken_backup"
            parent = d.parent
            idx = 1
            dest = parent / f"{suffix}"
            while dest.exists():
                idx += 1
                dest = parent / f"{suffix}_{idx}"
            shutil.move(str(d), str(dest))
            log.put((self.name, f"Backed up broken venv to: {dest}"))
        except Exception as e:
            log.put((self.name, f"Failed to backup broken venv ({d}): {e}"))

    def ensure_venv(self, log, force_rebuild=False):
        venv_dir = self.path / ".venv"
        venv_python = venv_dir / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")

        if force_rebuild and venv_dir.exists():
            log.put((self.name, "Force rebuilding venv..."))
            self._backup_dir(venv_dir, log)

        if venv_python.exists() and is_valid_venv_python(venv_python):
            self.venv_python = str(venv_python)
            log.put((self.name, f"Using existing venv: {self.venv_python}"))
            return True

        if self.venv_python:
            cand = Path(self.venv_python)
            if not is_valid_venv_python(cand):
                log.put((self.name, f"Detected existing venv appears broken: {cand} (home='{read_pyvenv_home(cand.parent.parent)}')."))
                self._backup_dir(cand.parent.parent, log)
                self.venv_python = ""

        log.put((self.name, "Creating fresh .venv in project root..."))
        py = sys.executable
        try:
            rc = stream_proc([py, "-m", "venv", str(venv_dir)], cwd=self.path, log_put=lambda m: log.put((self.name, m)))
            if rc != 0:
                log.put((self.name, f"Failed to create venv (exit {rc})."))
                return False
            self.venv_python = str(venv_python)
            self.created_venv = True
            log.put((self.name, f"Venv created: {self.venv_python}"))
            return True
        except Exception as e:
            log.put((self.name, f"Failed to create venv: {e}"))
            return False

    def _pip(self, args, log):
        if not self.venv_python or not Path(self.venv_python).exists():
            log.put((self.name, "Internal error: venv python missing"))
            return 1
        env = os.environ.copy()
        env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
        cmd = [self.venv_python, "-m", "pip"] + args
        log.put((self.name, f"$ {' '.join(cmd)}"))
        return stream_proc(cmd, cwd=self.path, log_put=lambda m: log.put((self.name, m)), env=env)

    def install_requirements(self, log):
        if not self.requirements:
            return True
        req_path = self.path / self.requirements
        if not req_path.exists():
            return True

        marker = self.path / ".launcher_installed.flag"
        if marker.exists() and not self.install_on_run.get():
            log.put((self.name, "Skipping requirements (already installed)."))
            return True

        if not self.venv_python or not is_valid_venv_python(Path(self.venv_python)):
            if not self.ensure_venv(log):
                return False

        log.put((self.name, f"Installing requirements from {req_path.name} ..."))
        rc = self._pip(["install", "-r", str(req_path)], log)
        if rc == 0:
            marker.write_text("ok")
            log.put((self.name, "Requirements installed."))
            return True

        log.put((self.name, f"pip install failed (exit {rc}). Retrying after upgrading pip/setuptools/wheel..."))
        up_rc = self._pip(["install", "--upgrade", "pip", "setuptools", "wheel"], log)
        if up_rc != 0:
            log.put((self.name, f"Upgrade step failed (exit {up_rc}). Giving up."))
            return False

        rc2 = self._pip(["install", "-r", str(req_path)], log)
        if rc2 == 0:
            marker.write_text("ok")
            log.put((self.name, "Requirements installed on retry."))
            return True

        log.put((self.name, f"Second attempt failed (exit {rc2}). See log above for details."))
        return False

    def run(self, log):
        if not self.entrypoint:
            log.put((self.name, "No entrypoint detected. Right-click → Edit Entrypoint/Args."))
            self.status.set("Need entrypoint")
            return

        if not self.ensure_venv(log):
            self.status.set("Venv error")
            return

        python_exec = self.venv_python if (self.venv_python and Path(self.venv_python).exists()) else sys.executable
        entry = self.path / self.entrypoint
        if not entry.exists():
            log.put((self.name, f"Entrypoint '{self.entrypoint}' not found."))
            self.status.set("Missing entrypoint")
            return

        if not self.install_requirements(log):
            self.status.set("Install failed")
            return

        try:
            cmd = [python_exec, str(entry)]
            if self.args.strip():
                cmd += self.args.strip().split()
            self.proc = subprocess.Popen(
                cmd,
                cwd=str(self.path),
                creationflags=CREATE_NEW_CONSOLE
            )
            self.status.set(f"Running (PID {self.proc.pid})")
            log.put((self.name, f"Launched with {Path(python_exec).name} {self.entrypoint}"))
        except Exception as e:
            self.status.set("Launch failed")
            log.put((self.name, f"Launch failed: {e}"))

    def stop(self, log):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=5)
                self.status.set("Stopped")
                log.put((self.name, "Stopped."))
            except Exception:
                try:
                    self.proc.kill()
                    self.status.set("Killed")
                    log.put((self.name, "Killed."))
                except Exception as e:
                    log.put((self.name, f"Failed to stop: {e}"))
        else:
            self.status.set("Idle")


class LauncherApp(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.master = master
        self.pack(fill="both", expand=True)

        self.projects = []
        self.log_queue = queue.Queue()
        self.process_threads = []
        self.all_projects = []  # for filtering
        self._menu_row_iid = None

        self._load_config()
        self._build_ui()
        self._scan(self.root_var.get() or DEFAULT_ROOT)
        self.after(100, self._drain_logs)

    # ---------- Settings ----------
    def _load_config(self):
        self.cfg = configparser.ConfigParser()
        if CONFIG_PATH.exists():
            try:
                self.cfg.read(CONFIG_PATH, encoding="utf-8")
            except Exception:
                pass
        if CONFIG_SECTION not in self.cfg:
            self.cfg[CONFIG_SECTION] = {}
        self.saved_root = self.cfg[CONFIG_SECTION].get("root", DEFAULT_ROOT)
        self.saved_install_always = self.cfg[CONFIG_SECTION].get("install_always", "false").lower() == "true"

    def _save_config(self):
        self.cfg[CONFIG_SECTION]["root"] = self.root_var.get()
        self.cfg[CONFIG_SECTION]["install_always"] = "true" if self.install_always_var.get() else "false"
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                self.cfg.write(f)
        except Exception:
            pass

    # ---------- UI ----------
    def _build_ui(self):
        self.master.title(APP_TITLE + " — v4")
        self.master.geometry("1100x720")

        # Fonts & theme
        try:
            import tkinter.font as tkfont
            for fname in ("TkDefaultFont", "TkTextFont"):
                try:
                    f = tkfont.nametofont(fname)
                    f.configure(family="Segoe UI", size=10)
                except Exception:
                    pass
            style = ttk.Style()
            themes = style.theme_names()
            if "vista" in themes:
                style.theme_use("vista")
            elif "clam" in themes:
                style.theme_use("clam")
            style.configure("Treeview", rowheight=26, borderwidth=0)
            style.configure("TButton", padding=6)
            style.configure("TCheckbutton", padding=6)
            style.configure("TLabelframe.Label", font=("Segoe UI", 10, "bold"))
        except Exception:
            pass

        # Top bar
        top = ttk.Frame(self)
        top.pack(side="top", fill="x", padx=10, pady=10)

        ttk.Label(top, text="Projects folder:").pack(side="left")
        self.root_var = tk.StringVar(value=self.saved_root or DEFAULT_ROOT)
        self.root_entry = ttk.Entry(top, textvariable=self.root_var, width=70)
        self.root_entry.pack(side="left", padx=6)

        ttk.Button(top, text="Browse", command=self._browse).pack(side="left", padx=3)
        ttk.Button(top, text="Refresh (F5)", command=self._refresh).pack(side="left", padx=3)
        ttk.Button(top, text="Set Default", command=self._set_default_root).pack(side="left", padx=3)

        # Search bar
        search = ttk.Frame(self)
        search.pack(side="top", fill="x", padx=10, pady=(0,10))
        ttk.Label(search, text="Filter:").pack(side="left")
        self.filter_var = tk.StringVar()
        self.filter_entry = ttk.Entry(search, textvariable=self.filter_var, width=40)
        self.filter_entry.pack(side="left", padx=6)
        ttk.Button(search, text="Clear", command=lambda: (self.filter_var.set(""), self._apply_filter())).pack(side="left")
        self.filter_var.trace_add("write", lambda *_: self._apply_filter())

        cols = ("name", "entry", "status")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="extended", height=18)
        self.tree.pack(side="top", fill="both", expand=True, padx=10)

        self.tree.heading("name", text="Project")
        self.tree.heading("entry", text="Entrypoint")
        self.tree.heading("status", text="Status")

        self.tree.column("name", width=300, anchor="w")
        self.tree.column("entry", width=520, anchor="w")
        self.tree.column("status", width=220, anchor="center")

        # Color tags for statuses
        self.tree.tag_configure("row-odd", background="#fafafa")
        self.tree.tag_configure("row-even", background="#f2f2f5")
        self.tree.tag_configure("status-running", background="#e6ffea")
        self.tree.tag_configure("status-prep", background="#fff7e6")
        self.tree.tag_configure("status-error", background="#ffeaea")
        self.tree.tag_configure("status-idle", background="#f5faff")
        self.tree.tag_configure("status-stopped", background="#eef2f7")

        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<Button-3>", self._on_right_click)  # right-click
        self.tree.bind("<Return>", lambda e: self._run_selected())
        self.master.bind("<F5>", lambda e: self._refresh())
        self.master.bind("<Control-f>", lambda e: (self.filter_entry.focus_set(), self.filter_entry.select_range(0, 'end')))

        # Buttons
        btns = ttk.Frame(self)
        btns.pack(side="top", fill="x", padx=10, pady=8)
        self.install_always_var = tk.BooleanVar(value=self.saved_install_always)
        ttk.Checkbutton(btns, text="Always install requirements on run", variable=self.install_always_var, command=self._on_toggle_install_mode).pack(side="left")

        ttk.Button(btns, text="Run Selected", command=self._run_selected).pack(side="left", padx=6)
        ttk.Button(btns, text="Stop Selected", command=self._stop_selected).pack(side="left", padx=6)
        ttk.Button(btns, text="Rebuild venv for Selected", command=self._rebuild_selected_venv).pack(side="left", padx=12)
        ttk.Button(btns, text="Clear Logs", command=self._clear_logs).pack(side="left", padx=6)

        # Logs
        log_frame = ttk.LabelFrame(self, text="Logs (pip output included)")
        log_frame.pack(side="top", fill="both", expand=False, padx=10, pady=10)
        self.log_text = tk.Text(log_frame, height=12, wrap="word")
        self.log_text.pack(fill="both", expand=True)

        # Footer
        footer = ttk.Frame(self)
        footer.pack(side="bottom", fill="x", padx=10, pady=6)
        ttk.Label(footer, text="Tips: Right-click a project row for actions • Double-click to edit entrypoint/args • F5 to refresh • Ctrl+F to filter").pack(side="left")

        # Context menu
        self._build_context_menu()

    def _build_context_menu(self):
        self.row_menu = tk.Menu(self, tearoff=0)
        self.row_menu.add_command(label="Start App", command=lambda: self._ctx_run_single())
        self.row_menu.add_command(label="Stop App", command=lambda: self._ctx_stop_single())
        self.row_menu.add_separator()
        self.row_menu.add_command(label="Rebuild venv", command=lambda: self._ctx_rebuild_single())
        self.row_menu.add_command(label="Edit Entrypoint/Args", command=lambda: self._ctx_edit_single())
        self.row_menu.add_separator()
        self.row_menu.add_command(label="Open Folder", command=lambda: self._ctx_open_folder())
        self.row_menu.add_command(label="Copy Path", command=lambda: self._ctx_copy_path())
        self.row_menu.add_separator()
        self.row_menu.add_command(label="Clear Logs", command=self._clear_logs)


    def _on_toggle_install_mode(self):
        """Apply 'Always install requirements on run' to all loaded projects and persist setting."""
        val = self.install_always_var.get()
        # Update both currently displayed and the full list used for filtering
        for proj in getattr(self, "projects", []):
            try:
                proj.install_on_run.set(val)
            except Exception:
                pass
        for proj in getattr(self, "all_projects", []):
            try:
                proj.install_on_run.set(val)
            except Exception:
                pass
        self._save_config()

    def _on_right_click(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            # select the row under cursor
            self.tree.selection_set(iid)
            self._menu_row_iid = iid
            try:
                self.row_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.row_menu.grab_release()

    # ---------- Helpers ----------
    def _status_tag_for(self, status_text: str):
        s = status_text.lower()
        if "running" in s:
            return "status-running"
        if "prepar" in s:
            return "status-prep"
        if "failed" in s or "error" in s or "missing" in s or "need" in s or "venv" in s:
            return "status-error"
        if "stopp" in s or "killed" in s or "exited" in s:
            return "status-stopped"
        return "status-idle"

    def _apply_row_tags(self, proj: "Project", index: int):
        base_tag = "row-even" if index % 2 == 0 else "row-odd"
        status_tag = self._status_tag_for(proj.status.get())
        self.tree.item(proj.name, tags=(base_tag, status_tag))

    def _append_log(self, proj_name, msg):
        self.log_text.insert("end", f"[{proj_name}] {msg}\n")
        self.log_text.see("end")

    def _clear_logs(self):
        self.log_text.delete("1.0", "end")

    # ---------- Persistence ----------
    def _set_default_root(self):
        self._save_config()
        messagebox.showinfo("Saved", f"Default root saved:\n{self.root_var.get()}")

    # ---------- Browse / Refresh / Scan ----------
    def _browse(self):
        path = filedialog.askdirectory(initialdir=self.root_var.get() or os.getcwd(), title="Choose root folder with your Python projects")
        if path:
            self._scan(path)

    def _refresh(self):
        self._scan(self.root_var.get())

    def _scan(self, root_path):
        root = Path(root_path).expanduser()
        if not root.exists() or not root.is_dir():
            messagebox.showerror("Invalid folder", f"Folder does not exist:\n{root}")
            return
        self.root_var.set(str(root))

        # Keep original list for filtering
        self.all_projects = []
        for sub in sorted([p for p in root.iterdir() if p.is_dir()]):
            proj = Project(sub)
            proj.install_on_run.set(self.install_always_var.get())
            self.all_projects.append(proj)

        self._rebuild_tree(self.all_projects)
        self._save_config()

    def _rebuild_tree(self, proj_list):
        # Clear current state
        self.projects = []
        for i in self.tree.get_children():
            self.tree.delete(i)

        # Insert rows
        for idx, proj in enumerate(proj_list):
            self.projects.append(proj)
            self.tree.insert("", "end", iid=proj.name, values=(proj.name, proj.entrypoint or "<right-click to edit>", proj.status.get()))
            proj.status.trace_add("write", lambda *_args, proj=proj: self._update_status(proj))
            self._apply_row_tags(proj, idx)

    def _apply_filter(self):
        term = (self.filter_var.get() or "").strip().lower()
        if not term:
            self._rebuild_tree(self.all_projects)
            return
        filtered = []
        for p in self.all_projects:
            hay = " ".join([p.name, p.entrypoint or "", str(p.path)]).lower()
            if term in hay:
                filtered.append(p)
        self._rebuild_tree(filtered)

    def _update_status(self, proj: "Project"):
        if proj.name in self.tree.get_children():
            vals = list(self.tree.item(proj.name, "values"))
            vals[2] = proj.status.get()
            self.tree.item(proj.name, values=vals)
            # update status color tag
            current_tags = self.tree.item(proj.name, "tags")
            base_row_tag = [t for t in current_tags if t.startswith("row-")]
            status_tag = self._status_tag_for(proj.status.get())
            self.tree.item(proj.name, tags=tuple(base_row_tag + [status_tag]))

    # ---------- Edit ----------
    def _on_double_click(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        proj = next((p for p in self.projects if p.name == item), None)
        if not proj:
            return
        self._edit_project(proj)

    def _edit_project(self, proj: "Project"):
        ep = simpledialog.askstring("Entrypoint", f"Set the Python file to run for '{proj.name}' (relative to project folder):",
                                    initialvalue=proj.entrypoint or "app.py")
        if ep:
            ep_path = (proj.path / ep)
            if not ep_path.exists():
                if not messagebox.askyesno("File not found", f"'{ep}' does not exist in {proj.path}.\nSave anyway?"):
                    return
            proj.entrypoint = ep
        args = simpledialog.askstring("Arguments (optional)", "Command-line arguments (space-separated):",
                                      initialvalue=proj.args or "")
        if args is not None:
            proj.args = args

        vals = list(self.tree.item(proj.name, "values"))
        vals[1] = proj.entrypoint or "<right-click to edit>"
        self.tree.item(proj.name, values=vals)

    # ---------- Selection helpers ----------
    def _get_selected_projects(self):
        items = self.tree.selection()
        if not items:
            items = self.tree.get_children()
        selected = []
        for iid in items:
            proj = next((p for p in self.projects if p.name == iid), None)
            if proj:
                selected.append(proj)
        return selected

    # ---------- Run/Stop/Rebuild actions ----------
    def _run_selected(self):
        projs = self._get_selected_projects()
        if not projs:
            messagebox.showinfo("Nothing to run", "No projects selected.")
            return
        for p in projs:
            t = threading.Thread(target=self._run_project_thread, args=(p,), daemon=True)
            t.start()
            self.process_threads.append(t)

    def _run_project_thread(self, proj: "Project"):
        proj.status.set("Preparing...")
        self.log_queue.put((proj.name, f"--- {proj.name} ---"))
        proj.run(self.log_queue)

    def _stop_selected(self):
        for proj in self._get_selected_projects():
            proj.stop(self.log_queue)

    def _rebuild_selected_venv(self):
        for proj in self._get_selected_projects():
            t = threading.Thread(target=self._rebuild_thread, args=(proj,), daemon=True)
            t.start()

    def _rebuild_thread(self, proj: "Project"):
        proj.status.set("Rebuilding venv...")
        self.log_queue.put((proj.name, f"--- {proj.name}: rebuilding venv ---"))
        ok = proj.ensure_venv(self.log_queue, force_rebuild=True)
        if ok:
            proj.status.set("Venv rebuilt")
            self.log_queue.put((proj.name, "Venv rebuilt successfully."))
        else:
            proj.status.set("Venv rebuild failed")
            self.log_queue.put((proj.name, "Failed to rebuild venv."))

    # ---------- Context menu handlers ----------
    def _ctx_get_proj(self):
        iid = self._menu_row_iid
        if not iid:
            return None
        return next((p for p in self.projects if p.name == iid), None)

    def _ctx_run_single(self):
        proj = self._ctx_get_proj()
        if proj:
            t = threading.Thread(target=self._run_project_thread, args=(proj,), daemon=True)
            t.start()

    def _ctx_stop_single(self):
        proj = self._ctx_get_proj()
        if proj:
            proj.stop(self.log_queue)

    def _ctx_rebuild_single(self):
        proj = self._ctx_get_proj()
        if proj:
            t = threading.Thread(target=self._rebuild_thread, args=(proj,), daemon=True)
            t.start()

    def _ctx_edit_single(self):
        proj = self._ctx_get_proj()
        if proj:
            self._edit_project(proj)

    def _ctx_open_folder(self):
        proj = self._ctx_get_proj()
        if not proj:
            return
        path = proj.path
        try:
            if IS_WINDOWS:
                os.startfile(str(path))
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            messagebox.showerror("Open Folder", f"Failed to open folder:\n{e}")

    def _ctx_copy_path(self):
        proj = self._ctx_get_proj()
        if proj:
            self.master.clipboard_clear()
            self.master.clipboard_append(str(proj.path))
            self.master.update()  # keep clipboard after window closes
            self._append_log(proj.name, f"Copied path to clipboard: {proj.path}")

    # ---------- Logs & polling ----------
    def _drain_logs(self):
        try:
            while True:
                name, msg = self.log_queue.get_nowait()
                self._append_log(name, msg)
        except queue.Empty:
            pass

        for p in self.projects:
            if p.proc and p.proc.poll() is not None and p.status.get().startswith("Running"):
                p.status.set("Exited")

        self.after(150, self._drain_logs)

def main():
    root = tk.Tk()
    try:
        style = ttk.Style()
        # theme already set in _build_ui
    except Exception:
        pass
    app = LauncherApp(root)
    def on_close():
        try:
            app._save_config()
        finally:
            root.destroy()
    root.protocol("WM_DELETE_WINDOW", on_close)
    app.mainloop()

if __name__ == "__main__":
    main()
