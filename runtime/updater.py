import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path


def download_update(download_url: str, target_path: str) -> bool:
    try:
        request = urllib.request.Request(
            download_url,
            headers={"User-Agent": "LegendsOverlayUpdater/1.0"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()

        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return True

    except Exception as ex:
        print(f"Failed to download update: {ex}")
        return False


def apply_update_and_restart(new_exe_path: str, current_exe_path: str):
    """
    Windows-safe updater flow:
    - wait for current exe to exit
    - replace exe
    - restart new exe
    - delete temp bat
    """
    new_exe = Path(new_exe_path).resolve()
    current_exe = Path(current_exe_path).resolve()
    old_exe = current_exe.with_name(current_exe.stem + "_old.exe")

    bat_contents = f"""@echo off
setlocal

timeout /t 2 /nobreak >nul

if exist "{old_exe}" del /f /q "{old_exe}"
if exist "{current_exe}" move /y "{current_exe}" "{old_exe}"
move /y "{new_exe}" "{current_exe}"

start "" "{current_exe}"

timeout /t 2 /nobreak >nul
del /f /q "{old_exe}" 2>nul

del /f /q "%~f0"
"""

    bat_path = Path(tempfile.gettempdir()) / "legends_overlay_update.bat"
    bat_path.write_text(bat_contents, encoding="utf-8")

    subprocess.Popen(
        ["cmd", "/c", str(bat_path)],
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def get_running_exe_path() -> str:
    """
    Works both for:
    - PyInstaller exe
    - python main.py during development
    """
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve())

    # dev mode fallback
    return str(Path(sys.argv[0]).resolve())