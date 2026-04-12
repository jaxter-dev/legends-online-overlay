import sys
import os
import shutil
import logging
from logging.handlers import RotatingFileHandler
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtGui import QAction, QIcon
from overlay import OverlayWindow
from updater import ReleaseCheckThread


def _app_root_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _bundle_root_dir() -> str:
    return getattr(sys, "_MEIPASS", _app_root_dir())


def _packaged_user_data_dir() -> str:
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if not local_app_data:
        return _app_root_dir()
    return os.path.join(local_app_data, "LegendsOverlay")


def _hide_dir_on_windows(path: str) -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        FILE_ATTRIBUTE_HIDDEN = 0x2
        ctypes.windll.kernel32.SetFileAttributesW(str(path), FILE_ATTRIBUTE_HIDDEN)
    except Exception:
        pass


def _runtime_data_dir() -> str:
    """Choose where runtime JSON/assets are read/written.

    In dev packaging layout (project/release/LegendsOverlay.exe), prefer project root
    so running exe and main.py share the same timers/settings data.
    """
    app_dir = _app_root_dir()
    if getattr(sys, "frozen", False):
        parent_dir = os.path.dirname(app_dir)
        parent_main = os.path.join(parent_dir, "main.py")
        parent_events = os.path.join(parent_dir, "events.json")
        if os.path.isfile(parent_main) and os.path.isfile(parent_events):
            return parent_dir
        return _packaged_user_data_dir()
    return app_dir


def _seed_runtime_files(target_dir: str) -> None:
    """Copy bundled defaults to app dir on first run so relative paths keep working."""
    app_dir = target_dir
    bundle_dir = _bundle_root_dir()
    install_dir = _app_root_dir()
    project_parent = os.path.dirname(_app_root_dir())

    os.makedirs(app_dir, exist_ok=True)
    _hide_dir_on_windows(app_dir)

    assets_src = os.path.join(bundle_dir, "assets")
    if not os.path.isdir(assets_src):
        install_assets = os.path.join(install_dir, "assets")
        if os.path.isdir(install_assets):
            assets_src = install_assets
    if not os.path.isdir(assets_src):
        fallback_assets = os.path.join(project_parent, "assets")
        if os.path.isdir(fallback_assets):
            assets_src = fallback_assets
    assets_dst = os.path.join(app_dir, "assets")
    if os.path.isdir(assets_src) and not os.path.isdir(assets_dst):
        shutil.copytree(assets_src, assets_dst)

    for name in ("icon.ico", "settings.json", "events.json", "uniques.json", "uniques_state.json"):
        src = os.path.join(bundle_dir, name)
        if not os.path.isfile(src):
            install_src = os.path.join(install_dir, name)
            if os.path.isfile(install_src):
                src = install_src
        if not os.path.isfile(src):
            fallback_src = os.path.join(project_parent, name)
            if os.path.isfile(fallback_src):
                src = fallback_src
        dst = os.path.join(app_dir, name)
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)

    # Legacy helper text may mention icon.png; keep compatibility if only .ico exists.
    icon_png_dst = os.path.join(app_dir, "icon.png")
    icon_ico_dst = os.path.join(app_dir, "icon.ico")
    if not os.path.exists(icon_png_dst) and os.path.exists(icon_ico_dst):
        try:
            shutil.copy2(icon_ico_dst, icon_png_dst)
        except Exception:
            pass


def _configure_logging(data_dir: str) -> str:
    logs_dir = os.path.join(data_dir, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    log_path = os.path.join(logs_dir, "overlay.log")

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Avoid duplicate handlers on restarts/hot reload.
    for h in list(logger.handlers):
        logger.removeHandler(h)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=4,
        encoding="utf-8",
    )
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    def _excepthook(exc_type, exc_value, exc_traceback):
        logging.exception("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    sys.excepthook = _excepthook
    logging.info("Logger initialized")
    return log_path

def main():
    data_dir = _runtime_data_dir()
    _seed_runtime_files(data_dir)
    os.chdir(data_dir)
    log_path = _configure_logging(data_dir)
    logging.info("App start: frozen=%s, data_dir=%s", bool(getattr(sys, "frozen", False)), data_dir)

    app = QApplication(sys.argv)
    # Preprečimo, da bi se aplikacija zaprla, ko zapremo zadnje okno
    app.setQuitOnLastWindowClosed(False)

    state = {"overlay": None, "tray": None, "release": None, "update_checked": False}

    checker = ReleaseCheckThread()

    def on_release_checked(release):
        state["release"] = release
        state["update_checked"] = True
        overlay = state.get("overlay")
        if overlay and hasattr(overlay, "set_update_check_result"):
            overlay.set_update_check_result(release)

    checker.finished.connect(on_release_checked)
    checker.start()

    def bootstrap_overlay():
        overlay = OverlayWindow()
        state["overlay"] = overlay

        if hasattr(overlay, "set_update_check_pending"):
            overlay.set_update_check_pending(checker.isRunning())
        if state.get("update_checked") and hasattr(overlay, "set_update_check_result"):
            overlay.set_update_check_result(state.get("release"))

        # Tu bova kasneje dodala lock_hotkey

        # --- POPRAVEK ZA IKONO ---
        tray = QSystemTrayIcon()

        # Uporabimo runtime data dir, da ikona in ostale datoteke sledijo isti logiki kot JSON.
        current_dir = _runtime_data_dir()
        icon_path = os.path.join(current_dir, "icon.ico")

        if os.path.exists(icon_path):
            # Ustvarimo QIcon objekt iz absolutne poti
            icon = QIcon(icon_path)
            tray.setIcon(icon)
            # Nastavimo ikono še za celo aplikacijo (tudi za overlay/taskbar)
            app.setWindowIcon(icon)
            print(f"Ikona naložena iz: {icon_path}")
            logging.info("Icon loaded from %s", icon_path)
        else:
            print(f"Opozorilo: Datoteka {icon_path} ni bila najdena!")
            print("Preveri, če je slika 'icon.png' v isti mapi kot 'main.py'")
            logging.warning("Icon not found at %s", icon_path)
        # -----------------------

        menu = QMenu()
        action_settings = QAction("⚙️ Settings", menu)
        action_exit = QAction("❌ Exit", menu)

        action_exit.triggered.connect(app.quit)
        action_settings.triggered.connect(overlay.open_settings)

        menu.addAction(action_settings)
        menu.addSeparator()
        menu.addAction(action_exit)

        tray.setContextMenu(menu)
        tray.show()
        state["tray"] = tray

        # Give overlay a reference to the tray for balloon/toast messages
        overlay.tray = tray
        print("Legends Overlay teče...")
        logging.info("Overlay started successfully. Log file: %s", log_path)

    QTimer.singleShot(0, bootstrap_overlay)
    sys.exit(app.exec())

if __name__ == "__main__":
    main()