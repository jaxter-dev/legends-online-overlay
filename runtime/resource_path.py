import sys
from pathlib import Path


def resource_path(*parts: str) -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # PyInstaller temp
    else:
        base = Path(__file__).resolve().parent.parent

    return base.joinpath(*parts)