"""
Auto-updater for Legends Online Overlay.

Flow:
  1. GitHub Releases API is queried in the background.
  2. A newer release is resolved from release assets, preferring a .exe asset.
  3. The user can install the update directly from the overlay/settings UI.
  4. For packaged .exe builds, the updater downloads the new executable,
      swaps it in after the current process exits, and restarts automatically.
  5. For development/source runs, zip fallback remains available.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QFont, QCursor, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from version import GITHUB_REPO, __version__

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# These files hold user data and must never be overwritten by an update.
_PRESERVE: set[str] = {
    "settings.json",
    "events.json",
    "uniques.json",
    "uniques_state.json",
    "icon.ico",
}

_STYLE = """
QDialog {
    background: #1a1a2e;
    color: #e0c97f;
}
QLabel {
    color: #e0c97f;
}
QTextEdit {
    background: #0f0f1e;
    color: #c8c8c8;
    border: 1px solid #3a3a5e;
    border-radius: 4px;
    padding: 6px;
    font-size: 12px;
}
QPushButton {
    background: #2a2a4e;
    color: #e0c97f;
    border: 1px solid #4a4a7e;
    border-radius: 4px;
    padding: 8px 20px;
    font-size: 13px;
    min-width: 110px;
}
QPushButton:hover  { background: #3a3a6e; }
QPushButton:disabled { color: #555555; }
QPushButton#btn_update {
    background: #1a4a1a;
    border-color: #4a8a4a;
    color: #90ee90;
}
QPushButton#btn_update:hover { background: #2a6a2a; }
QProgressBar {
    background: #0f0f1e;
    border: 1px solid #3a3a5e;
    border-radius: 4px;
    text-align: center;
    color: #e0c97f;
    height: 16px;
}
QProgressBar::chunk {
    background: #4a8a4a;
    border-radius: 3px;
}
"""


# ---------------------------------------------------------------------------
# Version helpers
# ---------------------------------------------------------------------------

def _parse_version(tag: str) -> tuple[int, ...]:
    """Convert 'v1.2.3' or '1.2.3' to (1, 2, 3). Invalid parts become 0."""
    cleaned = tag.lstrip("v").strip()
    parts = cleaned.split(".")
    result = []
    for p in parts[:3]:
        try:
            result.append(int(p))
        except ValueError:
            result.append(0)
    return tuple(result)


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------

def check_latest_release() -> dict | None:
    """
    Query the GitHub Releases API.

    Returns a dict with keys like ``version``, ``changelog``, ``asset_url``,
    ``asset_name``, ``install_kind`` when a newer release exists.
    when a newer release exists, or None otherwise (up-to-date / error).
    """
    try:
        req = urllib.request.Request(
            _API_URL,
            headers={"User-Agent": "LegendsOnlineOverlay-Updater/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data: dict = json.loads(resp.read().decode())

        tag: str = data.get("tag_name", "")
        changelog: str = data.get("body", "") or "No update description available."
        assets = data.get("assets", []) if isinstance(data.get("assets", []), list) else []

        if not tag:
            return None

        exe_asset = None
        zip_asset = None
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name", "")).strip()
            url = str(asset.get("browser_download_url", "")).strip()
            if not name or not url:
                continue
            low = name.lower()
            if low.endswith(".exe") and exe_asset is None:
                exe_asset = {"name": name, "url": url}
            elif low.endswith(".zip") and zip_asset is None:
                zip_asset = {"name": name, "url": url}

        if _parse_version(tag) > _parse_version(__version__):
            preferred = exe_asset or zip_asset
            if preferred is None:
                zip_url = str(data.get("zipball_url", "")).strip()
                if not zip_url:
                    return None
                preferred = {"name": f"{tag.lstrip('v')}.zip", "url": zip_url}
            return {
                "version": tag.lstrip("v"),
                "changelog": changelog,
                "asset_url": preferred["url"],
                "asset_name": preferred["name"],
                "install_kind": "exe" if preferred["name"].lower().endswith(".exe") else "zip",
            }
        return None

    except Exception:
        return None


# ---------------------------------------------------------------------------
# Background download thread
# ---------------------------------------------------------------------------

class _DownloadThread(QThread):
    finished = pyqtSignal(str)   # emits local file path on success
    error = pyqtSignal(str)      # emits error message on failure

    def __init__(self, url: str, filename_hint: str = "") -> None:
        super().__init__()
        self._url = url
        self._filename_hint = str(filename_hint or "").strip()

    def run(self) -> None:
        try:
            suffix = Path(self._filename_hint).suffix or Path(self._url).suffix or ".bin"
            tmp_path = tempfile.mktemp(suffix=suffix, prefix="lo_update_")
            req = urllib.request.Request(
                self._url,
                headers={"User-Agent": "LegendsOnlineOverlay-Updater/1.0"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                with open(tmp_path, "wb") as f:
                    f.write(resp.read())
            self.finished.emit(tmp_path)
        except Exception as exc:
            self.error.emit(str(exc))


class ReleaseCheckThread(QThread):
    """Background GitHub release check that never blocks the UI thread."""

    finished = pyqtSignal(object)

    def run(self) -> None:
        try:
            self.finished.emit(check_latest_release())
        except Exception:
            self.finished.emit(None)


# ---------------------------------------------------------------------------
# Update application logic
# ---------------------------------------------------------------------------

def _apply_update(zip_path: str) -> None:
    """
    Extract the downloaded zip and copy new .py / asset files into the
    application directory.  User-data files listed in _PRESERVE are skipped.
    """
    app_dir = Path(__file__).parent

    with tempfile.TemporaryDirectory() as tmp_dir:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmp_dir)

        # GitHub zips always have one root folder: {repo}-{tag}/
        extracted = Path(tmp_dir)
        subdirs = [d for d in extracted.iterdir() if d.is_dir()]
        src_root = subdirs[0] if subdirs else extracted

        # Copy .py files
        for src_file in src_root.rglob("*.py"):
            rel = src_file.relative_to(src_root)
            if rel.name in _PRESERVE:
                continue
            dest = app_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dest)

        # Copy assets folder (new/updated files only, never delete)
        src_assets = src_root / "assets"
        if src_assets.exists():
            for asset in src_assets.rglob("*"):
                if asset.is_file():
                    rel_a = asset.relative_to(src_root)
                    dest_a = app_dir / rel_a
                    dest_a.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(asset, dest_a)

    # Delete the downloaded zip (with retries for Windows file locking issues)
    for _ in range(3):
        try:
            if os.path.exists(zip_path):
                os.remove(zip_path)
            break
        except (OSError, PermissionError):
            import time
            time.sleep(0.1)
            continue


def _is_frozen_executable() -> bool:
    return bool(getattr(sys, "frozen", False)) and str(sys.executable or "").lower().endswith(".exe")


def _looks_like_valid_exe(path: str) -> bool:
    try:
        p = Path(path)
        if not p.exists() or not p.is_file():
            return False
        if p.stat().st_size < 1024 * 1024:
            return False
        with open(p, "rb") as f:
            return f.read(2) == b"MZ"
    except Exception:
        return False


def _current_app_dir() -> Path:
    if _is_frozen_executable():
        return Path(sys.executable).resolve().parent
    return Path(__file__).parent


def _schedule_exe_swap(new_exe_path: str) -> None:
    if not _is_frozen_executable():
        raise RuntimeError("EXE updates are only supported in packaged builds.")

    current_exe = Path(sys.executable).resolve()
    staged_exe = current_exe.with_suffix(".new.exe")
    backup_exe = current_exe.with_suffix(".old.exe")

    if staged_exe.exists():
        try:
            staged_exe.unlink()
        except OSError:
            pass

    if not _looks_like_valid_exe(new_exe_path):
        raise RuntimeError("Downloaded update file is invalid or incomplete.")

    shutil.move(new_exe_path, staged_exe)

    if not _looks_like_valid_exe(str(staged_exe)):
        raise RuntimeError("Staged update executable is invalid.")

    script_path = Path(tempfile.gettempdir()) / f"lo_update_swap_{os.getpid()}.cmd"
    script = f'''@echo off
setlocal
set "APP_PID={os.getpid()}"
set "APP_EXE={current_exe}"
set "APP_NEW={staged_exe}"
set "APP_OLD={backup_exe}"

:waitloop
tasklist /FI "PID eq %APP_PID%" 2>NUL | find /I "%APP_PID%" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >NUL
    goto waitloop
)

if not exist "%APP_NEW%" goto rollback

if exist "%APP_OLD%" del /f /q "%APP_OLD%" >NUL 2>&1
if exist "%APP_EXE%" move /Y "%APP_EXE%" "%APP_OLD%" >NUL 2>&1
move /Y "%APP_NEW%" "%APP_EXE%" >NUL 2>&1
if not exist "%APP_EXE%" goto rollback

for /L %%i in (1,1,20) do (
    if exist "%APP_EXE%" (
        for %%A in ("%APP_EXE%") do if %%~zA GTR 1048576 goto launch_new
    )
    timeout /t 1 /nobreak >NUL
)

:launch_new
start "" "%APP_EXE%"
if errorlevel 1 goto rollback
timeout /t 2 /nobreak >NUL
if exist "%APP_OLD%" del /f /q "%APP_OLD%" >NUL 2>&1
del /f /q "%~f0" >NUL 2>&1
goto :eof

:rollback
if exist "%APP_OLD%" (
    if not exist "%APP_EXE%" move /Y "%APP_OLD%" "%APP_EXE%" >NUL 2>&1
)
if exist "%APP_EXE%" start "" "%APP_EXE%"
del /f /q "%~f0" >NUL 2>&1
'''
    script_path.write_text(script, encoding="utf-8")
    subprocess.Popen(
        ["cmd.exe", "/d", "/c", str(script_path)],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _apply_release_file(download_path: str, install_kind: str) -> str:
    kind = str(install_kind or "").strip().lower()
    if kind == "exe":
        _schedule_exe_swap(download_path)
        return "external-swap"
    _apply_update(download_path)
    return "in-process-restart"


def _restart_app() -> None:
    """Launch a fresh instance of the app and exit the current one."""
    if _is_frozen_executable():
        subprocess.Popen([sys.executable], cwd=str(_current_app_dir()))
    else:
        subprocess.Popen([sys.executable, str(Path(__file__).parent / "main.py")], cwd=str(_current_app_dir()))
    sys.exit(0)


# ---------------------------------------------------------------------------
# Qt dialog
# ---------------------------------------------------------------------------

class UpdateDialog(QDialog):
    def __init__(self, release_info: dict, parent=None, auto_start: bool = False) -> None:
        super().__init__(parent)
        self._info = release_info
        self._auto_start = bool(auto_start)
        self._started = False
        self.update_applied = False
        self.restart_mode = ""
        self._thread: _DownloadThread | None = None
        self._build_ui()
        if self._auto_start:
            self._btn_later.setText("Cancel")
            QTimer.singleShot(0, self._start_update)

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.setWindowTitle("Update Available")
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setMinimumWidth(520)
        self.setStyleSheet(_STYLE)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 20, 24, 20)

        # Title
        title = QLabel(f"New Version: {self._info['version']}")
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        title.setFont(font)
        layout.addWidget(title)

        # Current version
        cur = QLabel(f"Current Version: {__version__}")
        cur.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(cur)

        # Changelog
        lbl = QLabel("Changes:")
        layout.addWidget(lbl)

        changelog = QTextEdit()
        changelog.setReadOnly(True)
        changelog.setPlainText(self._info["changelog"])
        changelog.setFixedHeight(180)
        layout.addWidget(changelog)

        # Progress bar (hidden until download starts)
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # Status label
        self._status = QLabel("")
        self._status.setStyleSheet("color: #aaaaaa; font-size: 11px;")
        self._status.setVisible(False)
        layout.addWidget(self._status)

        # Buttons
        btn_row = QHBoxLayout()
        self._btn_later = QPushButton("Later")
        self._btn_update = QPushButton("Update Now")
        self._btn_update.setObjectName("btn_update")

        self._btn_later.clicked.connect(self.reject)
        self._btn_update.clicked.connect(self._start_update)

        btn_row.addWidget(self._btn_later)
        btn_row.addStretch()
        btn_row.addWidget(self._btn_update)
        layout.addLayout(btn_row)
        self._apply_custom_cursor()

    def _apply_custom_cursor(self) -> None:
        try:
            cursor_path = Path(__file__).parent / "assets" / "cursor.cur"
            if not cursor_path.exists():
                return
            pix = QPixmap(str(cursor_path))
            if pix.isNull():
                return
            cursor = QCursor(pix, 0, 0)
            self.setCursor(cursor)
            for child in self.findChildren(QPushButton):
                child.setCursor(cursor)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _start_update(self) -> None:
        if self._started:
            return
        self._started = True
        self._btn_update.setEnabled(False)
        self._btn_later.setEnabled(False)
        self._progress.setRange(0, 0)   # indeterminate spinner
        self._progress.setVisible(True)
        self._status.setText("Downloading update...")
        self._status.setVisible(True)

        asset_url = str(self._info.get("asset_url", self._info.get("zip_url", ""))).strip()
        asset_name = str(self._info.get("asset_name", "update.bin")).strip()
        self._thread = _DownloadThread(asset_url, asset_name)
        self._thread.finished.connect(self._on_downloaded)
        self._thread.error.connect(self._on_error)
        self._thread.start()

    def _on_downloaded(self, downloaded_path: str) -> None:
        self._status.setText("Installing files...")
        try:
            self.restart_mode = _apply_release_file(downloaded_path, str(self._info.get("install_kind", "zip")))
        except Exception as exc:
            self._on_error(str(exc))
            return

        self._progress.setRange(0, 1)
        self._progress.setValue(1)
        self._status.setText("Update successful! Restarting application...")
        self.update_applied = True
        QTimer.singleShot(1500, self.accept)

    def _on_error(self, message: str) -> None:
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._started = False
        self._status.setText(f"Error: {message}")
        self._btn_later.setEnabled(True)
        self._btn_later.setText("Close")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_update_check() -> None:
    """
    Check for updates and show the dialog if one is available.
    Call this after ``QApplication`` is created but before the main window
    is shown.  Silently does nothing when there is no internet or when the
    app is already up to date.
    """
    release = check_latest_release()
    if release is None:
        return

    dialog = UpdateDialog(release)
    dialog.exec()

    if dialog.update_applied:
        _restart_app()


def install_release_update(release_info: dict | None, parent=None) -> bool:
    """Install a known release (if provided) and restart app on success."""
    if not isinstance(release_info, dict):
        return False
    if not str(release_info.get("asset_url", release_info.get("zip_url", ""))).strip():
        return False

    dialog = UpdateDialog(release_info, parent=parent, auto_start=True)
    dialog.exec()
    if dialog.update_applied:
        if dialog.restart_mode == "external-swap":
            app = QApplication.instance()
            if app is not None:
                app.quit()
            return True
        _restart_app()
        return True
    return False
