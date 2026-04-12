import threading
import json
import os
import platform
import subprocess

try:
    import pyttsx3
    HAS_TTS = True
except ImportError:
    HAS_TTS = False


def get_tts_info():
    """Return a lightweight TTS status payload for UI diagnostics."""
    info = {
        "has_pyttsx3": HAS_TTS,
        "voices": [],
        "error": "",
    }
    if not HAS_TTS:
        info["error"] = "pyttsx3 module is missing"
        return info

    try:
        engine = pyttsx3.init()
        voices = engine.getProperty('voices')
        info["voices"] = [v.name for v in voices if getattr(v, 'name', None)]
        try:
            engine.stop()
        except Exception:
            pass
    except Exception as exc:
        info["error"] = str(exc)
    return info


def _read_settings():
    try:
        with open("settings.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _write_settings(data):
    try:
        with open("settings.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False


def _get_missing_tts_capabilities():
    """Return missing Windows TTS capability names, e.g. Language.TextToSpeech.*"""
    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "Get-WindowsCapability -Online | "
        "Where-Object { $_.Name -like 'Language.TextToSpeech*' -and $_.State -ne 'Installed' } | "
        "Select-Object -ExpandProperty Name",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if res.returncode != 0:
            return []
        names = [line.strip() for line in (res.stdout or "").splitlines() if line.strip()]
        return names
    except Exception:
        return []


def _install_tts_capability(cap_name):
    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        f"Add-WindowsCapability -Online -Name '{cap_name}'",
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        return res.returncode == 0
    except Exception:
        return False


def ensure_tts_runtime_first_run():
    """
    First-run bootstrap for TTS on Windows.

    - Runs only once (stored in settings.json under tts.auto_setup_attempted).
    - If no voices are available, tries to install missing Windows TextToSpeech capability.
    - Safe no-op on non-Windows or when voices are already available.
    """
    if platform.system().lower() != "windows":
        return False
    if not os.path.exists("settings.json"):
        return False

    settings = _read_settings()
    tts_cfg = settings.setdefault("tts", {})
    if bool(tts_cfg.get("auto_setup_attempted", False)):
        return False

    tts_cfg["auto_setup_attempted"] = True
    _write_settings(settings)

    info = get_tts_info()
    if info.get("voices"):
        tts_cfg["auto_setup_ok"] = True
        _write_settings(settings)
        return True

    caps = _get_missing_tts_capabilities()
    if not caps:
        tts_cfg["auto_setup_ok"] = False
        _write_settings(settings)
        return False

    installed_any = False
    for cap in caps:
        if _install_tts_capability(cap):
            installed_any = True

    info_after = get_tts_info()
    tts_cfg["auto_setup_ok"] = bool(info_after.get("voices")) and installed_any
    _write_settings(settings)
    return bool(tts_cfg["auto_setup_ok"])


def get_tts_voices():
    """Return list of available TTS voice names (all SAPI voices on Windows)."""
    return get_tts_info().get("voices", [])


def _read_saved_volume() -> float:
    """Read TTS volume from settings.json and return a normalized value 0.0-1.0."""
    try:
        with open("settings.json", "r", encoding="utf-8") as f:
            cfg = json.load(f)
        vol = cfg.get("tts", {}).get("volume", 100)
        vol = float(vol)
    except Exception:
        vol = 100.0
    vol = max(0.0, min(100.0, vol))
    return vol / 100.0


def speak_text(text, voice_name=None, volume=None):
    """Speak text asynchronously. Runs in a daemon thread so it never blocks the UI."""
    if not HAS_TTS:
        return

    def _speak():
        try:
            engine = pyttsx3.init()
            if voice_name:
                voices = engine.getProperty('voices')
                for v in voices:
                    if v.name == voice_name:
                        engine.setProperty('voice', v.id)
                        break
            if volume is None:
                volume_value = _read_saved_volume()
            else:
                # Accept either 0-1 float or 0-100 percent
                vol = float(volume)
                if vol > 1.0:
                    vol = vol / 100.0
                volume_value = max(0.0, min(1.0, vol))
            engine.setProperty('volume', volume_value)
            engine.setProperty('rate', 145)
            engine.say(text)
            engine.runAndWait()
            try:
                engine.stop()
            except Exception:
                pass
        except Exception:
            pass

    threading.Thread(target=_speak, daemon=True).start()
