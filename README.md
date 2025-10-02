# pylaunchWIN — Python Apps Launcher for Windows (v4)

> A zero-dependency, Tk/ttk-based GUI to **scan**, **run**, **stop**, and **maintain** multiple Python app projects from a single dashboard — with **right‑click context actions**, **smart venv management**, and **pip install orchestration**.

<p align="center">
  <sub>OS</sub> Windows 10/11 &nbsp;•&nbsp; <sub>Python</sub> 3.8+ (recommended 3.10+) &nbsp;•&nbsp; <sub>Deps</sub> Standard Library Only
</p>

---

## ✨ Highlights

- **Modern UI**: ttk with Segoe UI, 26px row height, alternating row colors.
- **Project discovery**: point at a root folder; each subdirectory becomes a project.
- **Smart entrypoint detection**: tries `app.py`, `main.py`, `run.py`, `server.py`, `wsgi.py`, otherwise first `*.py`.
- **Right‑click context menu** on rows:
  - **Start App** / **Stop App**
  - **Rebuild venv** (safe, backs up broken envs)
  - **Edit Entrypoint/Args**
  - **Open Folder**
  - **Copy Path**
  - **Clear Logs**
- **Status coloring** in the grid (Running / Preparing / Error / Idle / Stopped).
- **Search/Filter** box (instant, case‑insensitive).
- **One‑click venv bootstrap** with health checks (validates `pyvenv.cfg: home`).
- **Requirements orchestrator**: `pip install -r` with **auto‑retry** after upgrading `pip/setuptools/wheel`.
- **Idempotence marker**: `.launcher_installed.flag` skips installs unless you opt into “Always install on run”.
- **Persistent settings**: remembers last projects root + install mode in `~/.python_apps_launcher.ini`.
- **Keyboard shortcuts**: `F5` Refresh, `Ctrl+F` focus Filter, `Enter` Run.
- **No external packages**: pure stdlib (Tkinter, subprocess, threading, configparser).

---

## 📦 Repository Layout

```
pylaunchWIN/
├─ launch_apps.py            # main GUI
├─ start_launcher.bat        # convenience starter for Windows
├─ CHANGELOG.txt             # changes & quick steps
└─ (per-user) %USERPROFILE%\.python_apps_launcher.ini  # persisted settings
```

When a project installs requirements successfully, a small file is created:
```
<your-project>\.launcher_installed.flag
```

This acts as an idempotence marker to **skip re-installs** when “Always install requirements on run” is **off**.

---

## 🚀 Quick Start

1. **Install Python 3.8+** (3.10+ recommended) and ensure `python` is on PATH.
2. Unzip the release and double‑click **`start_launcher.bat`**  
   _or_ run:
   ```powershell
   python .\launch_apps.py
   ```
3. In the GUI, set **Projects folder** to your root directory that contains subfolders (each subfolder is a project).
4. Click **Set Default** to persist the root.
5. Right‑click any row to **Start App** / **Stop App**, manage venv, etc.

> **Tip:** Multi‑select is supported (use Shift/Ctrl). You can also use the toolbar buttons for bulk **Run Selected / Stop Selected / Rebuild venv**.

---

## 🖥️ UI Tour

### Top Bar
- **Projects folder**: root path; each direct child folder becomes a project row.
- **Browse**: choose a different root.
- **Refresh (F5)**: rescan projects and update the grid.
- **Set Default**: save the current root in `%USERPROFILE%\.python_apps_launcher.ini`.

### Filter Row
- **Filter**: instant search across project name, entrypoint, and full path.
- **Clear**: reset the filter.

### Projects Grid (ttk.Treeview)
Columns:
- **Project** — folder name
- **Entrypoint** — Python module to run (editable; double‑click or use context menu)
- **Status** — real‑time state string with background color tag

Status color tags:
| Tag | Meaning |
|---|---|
| Running | Process is launched (shows PID). |
| Preparing… | Bootstrapping venv and/or installing dependencies. |
| Venv rebuilt | Recreated `.venv`. |
| Error / Failed | Something went wrong (venv, install, or launch). |
| Idle / Stopped / Killed / Exited | Not running. |

### Right‑Click Context Menu
- **Start App** — Ensures venv, optionally installs requirements, then `Popen` with a **new console window** on Windows.
- **Stop App** — Attempts graceful `terminate()` then `kill()` fallback.
- **Rebuild venv** — Backs up previous venv safely (`.broken_backup[_N]`), recreates `.venv`, re‑validates python.
- **Edit Entrypoint/Args** — Set script and CLI args (stored in memory for this session).
- **Open Folder** — Opens the project in Explorer (`os.startfile`).
- **Copy Path** — Copies project path to clipboard.
- **Clear Logs** — Clears the launcher’s log pane (pip output + launcher messages).

### Toolbar
- **Always install requirements on run** — if enabled, `pip install -r` runs on every start (ignores idempotence flag).
- **Run/Stop/Rebuild venv for Selected** batch actions.
- **Clear Logs** clears the log panel.

### Keyboard Shortcuts
- `F5` — Refresh projects
- `Ctrl+F` — Focus Filter
- `Enter` — Run selected projects

---

## 🧠 How It Works (Deep Dive)

### Project Discovery
- Root is scanned; each **direct child directory** becomes a project.
- Entrypoint resolution order: `app.py`, `main.py`, `run.py`, `server.py`, `wsgi.py`, otherwise the **first** `*.py` file.

### Virtual Environment Strategy
- Prefers `.venv` in the **project root**. If missing, searches shallow subdirs for `venv`, `env` as fallback.
- When (re)creating venvs, uses:
  ```bash
  <system-python> -m venv <project>/.venv
  ```
- **Health check**: verifies `pyvenv.cfg` `home=` path exists, and `python -V` returns successfully.
- If venv appears **broken**, it is **moved** to a timestamped `*.broken_backup[_N]` before rebuild.

### Dependency Installation
- If `requirements.txt` (or `requirements-dev.txt` / `requirement.txt`) exists:
  1. Runs `python -m pip install -r requirements.txt` in the venv.
  2. On failure, **auto‑upgrades** `pip setuptools wheel` and retries once.
  3. Writes `.launcher_installed.flag` on success.
- Idempotence:
  - If the flag exists and **“Always install on run” is disabled**, install step is **skipped**.

### Process Launching
- Starts the app with:
  ```text
  <venv_python> <entrypoint> [args...]
  ```
- On Windows, uses `CREATE_NEW_CONSOLE` so your app opens in its own terminal.
- The launcher tracks process handles to update statuses and to stop apps upon request.

### Logging
- The log pane shows **launcher** output (pip logs, venv messages, actions).  
  Child app stdout/stderr appear in the **separate console** opened for the process on Windows.
- A Tk `queue.Queue` is drained periodically (every 150ms) to keep the UI responsive.

### Concurrency Model
- Long‑running actions (run/venv rebuild) execute in **background threads**.
- UI updates are scheduled on the main Tk loop; no direct cross‑thread Tk calls.

---

## ⚙️ Configuration

**User config file**: `%USERPROFILE%\.python_apps_launcher.ini`
```ini
[launcher]
root = C:\path\to\your\projects
install_always = true|false
```

**Advanced constants** (edit `launch_apps.py` if you want different defaults):
```python
APP_TITLE = "Python Apps Launcher"
DEFAULT_ROOT = r"C:\Users\anass\Desktop\Python-Project"
ENTRY_CANDIDATES = ["app.py", "main.py", "run.py", "server.py", "wsgi.py"]
VENV_NAMES = [".venv", "venv", "env"]
```

---

## 🧪 Tested Scenarios

- Projects with/without `requirements.txt`
- Broken venv (invalid `home` in `pyvenv.cfg`) → rebuilt with backup
- Spaces in paths
- No entrypoint in folder → prompts to set one
- Bulk operations (multi‑select run/stop/rebuild)

---

## 🔒 Security Notes

- Runs **user‑level** processes; no elevation is required or used.
- `pip install` executes in the project’s venv only.
- Review third‑party requirements before installing. Consider private indexes / hashes for supply‑chain hardening.

---

## 🛠️ Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| **“python not found”** when creating venv | Python not on PATH | Reinstall Python with “Add to PATH”. Verify `python -V` in a new terminal. |
| App launches but no output in log | Expected | App output is in **its own console** window; the log shows launcher/pip messages. |
| **Install failed** even after retry | Network constraints, private index, build tools missing | Add `--index-url` in `requirements.txt`, ensure Visual C++ Build Tools, or pin wheels. |
| **Venv error / broken** | Moved or corrupted interpreter | Use **Rebuild venv**; launcher will back up the old one. |
| **Permission denied** moving old venv | Locked files | Close any shells in that venv; retry. |
| **Entrypoint missing** | Wrong file name/path | Use **Edit Entrypoint/Args** to set the correct script. |

---

## 🧰 Extensibility Ideas

- System tray icon with quick actions
- Per‑project **persistent** args/entrypoints (JSON beside each project)
- Export/import projects list + per‑project settings
- Capture child process stdout/stderr in a dockable panel (cross‑platform mode)
- One‑click **PyInstaller** packaging for each project
- Task Scheduler integration (“Run this project at logon/boot”)

---

## 🔄 Changelog (v4)

- UI refresh and status coloring
- Right‑click context menu (Start/Stop/Rebuild/Edit/Open/Copy/Clear)
- Filter/search box
- Persistent settings (`.ini` in user profile)
- Improved venv validation and safe rebuild with backups
- Requirements install with robust retry path
- QoL: Clear Logs, F5 refresh, Ctrl+F filter focus, Enter to run


---

## 🙌 Credits

Built with ❤️ using the Python standard library (Tkinter, subprocess, threading, configparser) for the **pylaunchWIN** project.
