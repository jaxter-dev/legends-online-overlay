import sys
import os
import json
import time
import re
import shutil
import threading
import ctypes
import subprocess
from difflib import SequenceMatcher
from datetime import datetime
from ctypes import windll, c_int, Structure, c_uint, create_unicode_buffer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QApplication, QFrame, QHBoxLayout, QPushButton, QSizePolicy, QScrollArea, QCheckBox
from PyQt6.QtCore import Qt, QTimer, QSize, QPoint, QRect, QPropertyAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtGui import QFont, QIcon, QCursor, QPixmap

RELEASE_DISABLE_OCR = True

try:
    from pynput import mouse as pynput_mouse
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False

try:
    import keyboard  # noqa: F401
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False

if not RELEASE_DISABLE_OCR:
    try:
        import pytesseract  # type: ignore
        from PIL import Image, ImageGrab, ImageOps, ImageEnhance, ImageFilter  # type: ignore
        HAS_OCR_DEPS = True
    except ImportError:
        HAS_OCR_DEPS = False
else:
    pytesseract = None
    Image = None
    ImageGrab = None
    ImageOps = None
    ImageEnhance = None
    ImageFilter = None
    HAS_OCR_DEPS = False

if not RELEASE_DISABLE_OCR:
    try:
        import mss  # type: ignore
        HAS_MSS = True
    except Exception:
        mss = None
        HAS_MSS = False
else:
    mss = None
    HAS_MSS = False

if not RELEASE_DISABLE_OCR:
    try:
        from ocr_engine import (
            best_name_match,
            infer_status,
            HAS_CV,
            pil_to_binary_cv,
            extract_text_row_rects,
            color_detect_table_rows,
            crop_row_columns,
            extract_rows_from_text,
            preprocess_for_ocr_pil,
        )
    except Exception:
        best_name_match = None
        infer_status = None
        HAS_CV = False
        pil_to_binary_cv = None
        extract_text_row_rects = None
        color_detect_table_rows = None
        crop_row_columns = None
        extract_rows_from_text = None
        preprocess_for_ocr_pil = None
else:
    best_name_match = None
    infer_status = None
    HAS_CV = False
    pil_to_binary_cv = None
    extract_text_row_rects = None
    color_detect_table_rows = None
    crop_row_columns = None
    extract_rows_from_text = None
    preprocess_for_ocr_pil = None

if not RELEASE_DISABLE_OCR:
    try:
        from templates_bank import init_template_bank, get_template_bank
        HAS_TEMPLATES = True
    except Exception:
        init_template_bank = None
        get_template_bank = None
        HAS_TEMPLATES = False
else:
    init_template_bank = None
    get_template_bank = None
    HAS_TEMPLATES = False

OCR_ENGINE_REV = "2026-04-11-r9-crop"


def _ocr_name_crop(pil_crop, tesseract_cmd=None):
    """OCR a single name-column crop with optimal settings.

    Upscales 3x, sharpens, thresholds → psm 8 with alpha+space whitelist.
    Returns cleaned string.
    """
    prep = _preprocess_name_crop(pil_crop)
    if prep is None:
        return ""
    try:
        cfg = "--oem 3 --psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz .[]()"
        txt = pytesseract.image_to_string(prep, config=cfg) or ""
        # Also try psm 7 on same image and take longer result
        try:
            txt7 = pytesseract.image_to_string(prep, config="--oem 3 --psm 7") or ""
            if len(txt7.strip()) > len(txt.strip()):
                txt = txt7
        except Exception:
            pass
        return txt.strip()
    except Exception:
        return ""


def _preprocess_name_crop(pil_crop):
    """Convert a raw name-column crop to a clean B&W text-only image.

    Steps: grayscale → 3x LANCZOS upscale → SHARPEN → autocontrast → binary threshold.
    Returns a binary PIL Image ('L' mode, 1-bit values 0/255), or None on error.
    Suitable both for OCR input and for saving as template.
    """
    try:
        if pil_crop is None or pil_crop.width < 8 or pil_crop.height < 4:
            return None
        g = ImageOps.grayscale(pil_crop)
        g = g.resize((g.width * 3, g.height * 3), resample=5)  # LANCZOS
        g = ImageEnhance.Contrast(g).enhance(2.0)
        g = ImageEnhance.Sharpness(g).enhance(1.5)

        # Prefer Otsu from ocr_engine when available.
        bw = pil_to_binary_cv(g) if pil_to_binary_cv is not None else None
        if bw is not None:
            try:
                g = Image.fromarray(bw)
            except Exception:
                g = g.point(lambda p: 255 if p > 145 else 0)
        else:
            g = ImageOps.autocontrast(g)
            g = g.point(lambda p: 255 if p > 145 else 0)

        g = g.filter(ImageFilter.MedianFilter(size=3))
        return g
    except Exception:
        return None


def _tight_text_crop(pil_crop):
    """Trim horizontal empty margins from a crop so OCR/template matching sees mostly text."""
    try:
        import numpy as _np
        if pil_crop is None or pil_crop.width < 10 or pil_crop.height < 6:
            return pil_crop
        g = ImageOps.autocontrast(ImageOps.grayscale(pil_crop))
        bw = g.point(lambda p: 255 if p > 140 else 0)
        arr = _np.array(bw)
        if arr.size == 0:
            return pil_crop
        h, w = arr.shape[:2]
        min_on = max(1, h // 18)
        cols = (arr > 0).sum(axis=0)

        # Drop likely frame/border columns: almost full-height bright vertical strokes.
        border_like = cols >= int(h * 0.90)
        valid = (cols >= min_on) & (~border_like)

        # Ignore left gutter where list frame lines are common.
        left_guard = max(2, int(w * 0.08))
        valid[:left_guard] = False

        xs = _np.where(valid)[0]
        if len(xs) == 0:
            return pil_crop

        # Split into contiguous runs; keep only substantial text-like runs.
        runs = []
        s = int(xs[0])
        p = s
        for x in xs[1:]:
            x = int(x)
            if x - p <= 1:
                p = x
                continue
            runs.append((s, p))
            s = p = x
        runs.append((s, p))

        min_run_w = max(8, int(w * 0.06))
        runs = [(rs, re) for (rs, re) in runs if (re - rs + 1) >= min_run_w]
        if not runs:
            return pil_crop

        best = None
        best_score = -10**9
        for rs, re in runs:
            rw = re - rs + 1
            # Name is left-most block; penalize runs that start too far right.
            score = rw - (0.35 * rs)
            if rs > int(w * 0.70):
                score -= 100
            if score > best_score:
                best_score = score
                best = (rs, re)

        if best is None:
            return pil_crop

        rs, re = best
        x0 = max(0, int(rs) - 3)
        x1 = min(pil_crop.width, int(re) + 8)
        if x1 - x0 < 10:
            return pil_crop
        return pil_crop.crop((x0, 0, x1, pil_crop.height))
    except Exception:
        return pil_crop


def _name_crop_has_text_signal(pil_crop):
    """Heuristic guard: reject crops that look like frame lines/noise instead of text."""
    try:
        import numpy as _np
        prep = _preprocess_name_crop(pil_crop)
        if prep is None:
            return False
        arr = _np.array(prep)
        if arr.ndim != 2 or arr.size == 0:
            return False

        on = arr > 0
        h, w = on.shape
        if h < 6 or w < 12:
            return False

        total_on = int(on.sum())
        if total_on < max(18, (h * w) // 80):
            return False

        row_hits = (on.sum(axis=1) > max(2, w // 22)).sum()
        col_hits = (on.sum(axis=0) > max(1, h // 7)).sum()

        # Single horizontal/vertical lines should fail these checks.
        if row_hits < max(3, h // 8):
            return False
        if col_hits < max(6, w // 12):
            return False
        return True
    except Exception:
        return True


def _match_name_strict(raw_text, known_names, context_text=""):
    """Strict fuzzy name matching to avoid false positives from frame artifacts."""
    try:
        raw = " ".join(str(raw_text or "").strip().lower().split())
        ctx = " ".join(str(context_text or "").strip().lower().split())
        if not raw:
            return None

        letters = sum(1 for ch in raw if ch.isalpha())
        if letters < 3:
            return None
        if any(tok in raw for tok in ("alive", "dead")):
            return None

        words = [w for w in raw.split() if w]
        short_or_single = (len(words) <= 1) or (len(raw) < 8)

        scored = []
        for name in (known_names or []):
            n = " ".join(str(name or "").strip().lower().split())
            if not n:
                continue
            r1 = SequenceMatcher(None, raw, n).ratio()
            r2 = SequenceMatcher(None, ctx, n).ratio() if ctx else 0.0
            scored.append((max(r1, r2), str(name)))

        if not scored:
            return None
        scored.sort(key=lambda t: t[0], reverse=True)
        best_ratio, best_name = scored[0]
        second_ratio = scored[1][0] if len(scored) > 1 else 0.0

        # Stronger thresholds than ocr_engine.best_name_match (0.50) for noisy row crops.
        if best_ratio < 0.62:
            return None
        if (best_ratio - second_ratio) < 0.04:
            return None

        # Prevent frame/noise OCR from mapping into long multi-word names too easily.
        if short_or_single:
            bw = [w for w in str(best_name).strip().split() if w]
            if len(bw) >= 2 and best_ratio < 0.74:
                return None
        return best_name
    except Exception:
        return None


def _combine_row_hints(image):
    """Merge row candidates from color-detect and text-rect detect, then de-duplicate by Y."""
    rows = []

    if color_detect_table_rows is not None:
        try:
            rows.extend(color_detect_table_rows(image) or [])
        except Exception:
            pass

    if extract_text_row_rects is not None:
        try:
            rects = extract_text_row_rects(image) or []
            for r in rects:
                rows.append({
                    "y": int(r[1] + (r[3] // 2)),
                    "row_h": int(r[3]),
                    "status": "unknown",
                })
        except Exception:
            pass

    if not rows:
        return []

    rows = [
        {
            "y": int(r.get("y", 0)),
            "row_h": max(10, int(r.get("row_h", 12))),
            "status": str(r.get("status", "unknown")).strip().lower() or "unknown",
        }
        for r in rows
    ]
    rows.sort(key=lambda r: r["y"])

    merged = []
    for r in rows:
        if not merged or abs(r["y"] - merged[-1]["y"]) > 7:
            merged.append(dict(r))
            continue
        prev = merged[-1]
        prev["y"] = int((prev["y"] + r["y"]) / 2)
        prev["row_h"] = max(prev["row_h"], r["row_h"])
        if prev.get("status") not in ("alive", "dead") and r.get("status") in ("alive", "dead"):
            prev["status"] = r["status"]

    return merged[:80]


def _detect_name_header_anchor(image):
    """Find Name header center X and header baseline Y using OCR in top half of scan image.

    Returns (center_x, header_bottom_y) in image-local pixels, or (None, None) on failure.
    """
    try:
        if image is None or not HAS_OCR_DEPS:
            return None, None

        w, h = image.size
        if w < 80 or h < 40:
            return None, None

        # Header is expected near the top section of the list region.
        top_h = max(40, int(h * 0.45))
        top = image.crop((0, 0, w, top_h))
        g = ImageOps.autocontrast(ImageOps.grayscale(top))
        g = g.resize((max(1, g.width * 2), max(1, g.height * 2)), resample=5)
        g = g.point(lambda p: 255 if p > 145 else 0)

        data = pytesseract.image_to_data(
            g,
            config="--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
            output_type=pytesseract.Output.DICT,
        )
        n = len(data.get("text", []))
        best = None
        for i in range(n):
            txt = str(data.get("text", [""])[i] or "").strip().lower()
            if not txt:
                continue
            norm = "".join(ch for ch in txt if ch.isalpha())
            # Accept common OCR variants around "name".
            if norm not in ("name", "neme", "nane", "narne"):
                continue
            conf_raw = data.get("conf", ["0"])[i]
            try:
                conf = float(conf_raw)
            except Exception:
                conf = 0.0
            x = int(data.get("left", [0])[i]) // 2
            y = int(data.get("top", [0])[i]) // 2
            ww = int(data.get("width", [0])[i]) // 2
            hh = int(data.get("height", [0])[i]) // 2
            cx = x + max(1, ww) // 2
            by = y + max(1, hh)
            cand = (conf, cx, by)
            if best is None or cand[0] > best[0]:
                best = cand

        if best is not None:
            return int(best[1]), int(best[2])

    except Exception:
        pass

    return None, None


def _crop_name_fixed_width(image, row_y, row_h, center_x, width_px=220):
    """Crop name cell using fixed width centered around Name header center X."""
    try:
        if image is None:
            return None
        img = image.convert("RGB")
        w, h = img.size
        cx = int(center_x)
        half = max(40, int(width_px) // 2)
        x0 = max(0, cx - half)
        x1 = min(w, cx + half)
        if x1 - x0 < 24:
            return None

        pad = max(4, int(row_h) // 2 + 4)
        y0 = max(0, int(row_y) - pad)
        y1 = min(h, int(row_y) + pad)
        if y1 - y0 < 8:
            return None
        return img.crop((x0, y0, x1, y1))
    except Exception:
        return None


def _extract_name_lines_from_column(image, center_x, body_start_y, width_px=220):
    """OCR the Name column as a whole and return line-wise text with Y centers.

    This avoids frame-line artifacts from per-row cropping.
    """
    try:
        if image is None or not HAS_OCR_DEPS:
            return []
        img = image.convert("RGB")
        w, h = img.size
        if w < 80 or h < 40:
            return []

        cx = int(center_x)
        half = max(40, int(width_px) // 2)
        x0 = max(0, cx - half)
        x1 = min(w, cx + half)
        y0 = max(0, int(body_start_y))
        y1 = h
        if x1 - x0 < 30 or y1 - y0 < 20:
            return []

        col = img.crop((x0, y0, x1, y1))
        g = ImageOps.autocontrast(ImageOps.grayscale(col))
        g = g.resize((max(1, g.width * 2), max(1, g.height * 2)), resample=5)
        g = g.point(lambda p: 255 if p > 145 else 0)

        data = pytesseract.image_to_data(
            g,
            config="--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz[]() -",
            output_type=pytesseract.Output.DICT,
        )

        n = len(data.get("text", []))
        groups = {}
        for i in range(n):
            txt = str(data.get("text", [""])[i] or "").strip()
            if not txt:
                continue
            conf_raw = data.get("conf", ["0"])[i]
            try:
                conf = float(conf_raw)
            except Exception:
                conf = 0.0
            if conf < 20.0:
                continue

            clean = "".join(ch for ch in txt if ch.isalnum() or ch in " []()-")
            if not clean or not any(ch.isalpha() for ch in clean):
                continue

            b = int(data.get("block_num", [0])[i])
            p = int(data.get("par_num", [0])[i])
            l = int(data.get("line_num", [0])[i])
            key = (b, p, l)

            left = int(data.get("left", [0])[i])
            top = int(data.get("top", [0])[i])
            hh = int(data.get("height", [0])[i])
            groups.setdefault(key, []).append((left, clean, top, hh))

        out = []
        for key, words in groups.items():
            words.sort(key=lambda t: t[0])
            line_text = " ".join(w[1] for w in words).strip()
            if not line_text:
                continue
            low = line_text.lower()
            if low in ("name", "status", "slayer", "last", "updated"):
                continue

            ys = [w[2] for w in words]
            hs = [w[3] for w in words]
            y_center_scaled = int(sum(y + (h2 // 2) for y, h2 in zip(ys, hs)) / max(1, len(ys)))
            row_h_scaled = max(hs) if hs else 20

            # Convert from 2x OCR image back to original image coords.
            y_center = y0 + max(0, y_center_scaled // 2)
            row_h = max(12, row_h_scaled // 2 + 6)

            out.append({"y": int(y_center), "row_h": int(row_h), "text": line_text})

        out.sort(key=lambda r: r["y"])

        # Deduplicate very close lines.
        dedup = []
        for r in out:
            if not dedup or abs(r["y"] - dedup[-1]["y"]) > 6:
                dedup.append(r)
            else:
                # Keep richer text line when they overlap.
                if len(r["text"]) > len(dedup[-1]["text"]):
                    dedup[-1] = r
        return dedup[:80]
    except Exception:
        return []

WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 513
WM_LBUTTONUP = 514

class MSLLHOOKSTRUCT(Structure):
    _fields_ = [
        ("x", c_int),
        ("y", c_int),
        ("mouseData", c_uint),
        ("flags", c_uint),
        ("time", c_int),
        ("dwExtraInfo", c_uint)
    ]

class ToastWidget(QWidget):
    """Frameless slide-in notification that appears bottom-right on the primary monitor."""

    def __init__(self, title, message, duration=5000, bottom_offset=0):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._duration = duration
        self._bottom_offset = bottom_offset
        self._slide_anim = None

        frame = QFrame(self)
        frame.setObjectName("toastFrame")
        frame.setStyleSheet(
            "#toastFrame { background-color: rgba(28,28,28,235);"
            " border: 1px solid rgba(212,197,161,100); border-radius: 8px; }"
        )
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(14, 10, 14, 10)
        fl.setSpacing(4)

        lbl_title = QLabel(title)
        lbl_title.setStyleSheet(
            "color: #d4c5a1; font-weight: bold; font-size: 11px;"
            " background: transparent; border: none;"
        )
        lbl_msg = QLabel(message)
        lbl_msg.setStyleSheet(
            "color: #c8c8c8; font-size: 10px; background: transparent; border: none;"
        )
        lbl_msg.setWordWrap(True)
        lbl_msg.setMaximumWidth(240)

        fl.addWidget(lbl_title)
        fl.addWidget(lbl_msg)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(frame)

        self.setFixedWidth(270)

        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self._slide_out)
        self._dismiss_timer.start(duration)

    def showEvent(self, event):
        super().showEvent(event)
        self.adjustSize()
        screen = QApplication.primaryScreen()
        ag = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        end_x = ag.right() - self.width() - 16
        end_y = ag.bottom() - self.height() - 48 - self._bottom_offset
        start_y = ag.bottom() + 10
        self.move(end_x, start_y)

        self._slide_anim = QPropertyAnimation(self, b"pos", self)
        self._slide_anim.setDuration(350)
        self._slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide_anim.setStartValue(QPoint(end_x, start_y))
        self._slide_anim.setEndValue(QPoint(end_x, end_y))
        self._slide_anim.start()

    def _slide_out(self):
        if self._slide_anim and self._slide_anim.state() == QPropertyAnimation.State.Running:
            self._slide_anim.stop()
        screen = QApplication.primaryScreen()
        ag = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        out_y = ag.bottom() + 10
        self._slide_anim = QPropertyAnimation(self, b"pos", self)
        self._slide_anim.setDuration(300)
        self._slide_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._slide_anim.setStartValue(self.pos())
        self._slide_anim.setEndValue(QPoint(self.x(), out_y))
        self._slide_anim.finished.connect(self.close)
        self._slide_anim.start()


class UniqueListScanHud(QWidget):
    def __init__(self, unique_names):
        super().__init__(None)
        self._names = list(unique_names)
        self._detected = set()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        panel = QFrame()
        panel.setStyleSheet(
            "QFrame { background: rgba(15,15,15,170); border: 1px solid rgba(212,197,161,120);"
            " border-radius: 8px; }"
        )
        root.addWidget(panel, alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        pl = QVBoxLayout(panel)
        pl.setContentsMargins(10, 8, 10, 8)
        pl.setSpacing(6)

        self.countdown_lbl = QLabel("OCR scan: 00s")
        self.countdown_lbl.setStyleSheet("color: #d4c5a1; font-weight: bold; font-size: 11px;")
        pl.addWidget(self.countdown_lbl)

        hint_lbl = QLabel("ESC to cancel | Scroll list during scan")
        hint_lbl.setStyleSheet("color: #b5b5b5; font-size: 9px;")
        pl.addWidget(hint_lbl)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setFixedSize(300, 280)
        content = QWidget()
        self._rows = QVBoxLayout(content)
        self._rows.setContentsMargins(0, 0, 0, 0)
        self._rows.setSpacing(2)
        self._row_labels = {}
        for name in self._names:
            lbl = QLabel(f"[ ] {name}")
            lbl.setStyleSheet("color: #9a9a9a; font-size: 9px;")
            self._rows.addWidget(lbl)
            self._row_labels[name] = lbl
        self._rows.addStretch()
        self.scroll.setWidget(content)
        pl.addWidget(self.scroll)

        self.setFixedSize(1920, 1080)

    def sync_to_screen(self):
        screen = QApplication.primaryScreen()
        ag = screen.geometry() if screen else QRect(0, 0, 1920, 1080)
        self.setGeometry(ag)

    def set_remaining(self, seconds_left):
        self.countdown_lbl.setText(f"OCR scan: {max(0, int(seconds_left))}s")

    def set_detected(self, names):
        self._detected = set(names)
        for name, lbl in self._row_labels.items():
            if name in self._detected:
                lbl.setText(f"[x] {name}")
                lbl.setStyleSheet("color: #66dd88; font-size: 9px;")
            else:
                lbl.setText(f"[ ] {name}")
                lbl.setStyleSheet("color: #9a9a9a; font-size: 9px;")


class OCRRegionPreview(QWidget):
    def __init__(self, region_rect: QRect, mode_label: str, hint_text: str, duration_ms: int = 5000, cursor=None):
        super().__init__(None)
        self._region = QRect(region_rect)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        if cursor is not None:
            self.setCursor(cursor)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        border = QFrame(self)
        border.setStyleSheet(
            "QFrame {"
            " border: 2px solid rgba(0, 255, 140, 220);"
            " background: rgba(0, 255, 140, 28);"
            " border-radius: 4px;"
            "}"
        )
        root.addWidget(border)

        info = QLabel(f"{mode_label} scan region\n{hint_text}")
        info.setParent(self)
        info.setStyleSheet(
            "background: rgba(15,15,15,220); color: #d4c5a1;"
            "border: 1px solid rgba(212,197,161,150); border-radius: 4px;"
            "padding: 6px 8px; font-size: 10px;"
        )
        info.adjustSize()
        info.move(6, 6)
        info.raise_()

        self.setGeometry(self._region)
        QTimer.singleShot(max(500, int(duration_ms)), self.close)


class FirstRunWindow(QWidget):
    def __init__(self, cursor=None, on_open_settings=None, on_dismissed=None, on_toggle_dont_show=None):
        super().__init__(None)
        self._on_open_settings_cb = on_open_settings
        self._on_dismissed_cb = on_dismissed
        self._on_toggle_dont_show_cb = on_toggle_dont_show
        self.setWindowTitle("Welcome")
        self.setWindowFlags(
            Qt.WindowType.Tool |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet("background-color: rgba(40, 40, 40, 180); color: #d4c5a1;")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 12, 12)
        outer.setSpacing(8)

        title_row = QHBoxLayout()
        title = QLabel("Welcome")
        title.setFont(QFont("Arial", 15, QFont.Weight.Bold))
        title.setStyleSheet("color: #d4c5a1; background: transparent;")
        title_row.addWidget(title)
        title_row.addStretch()
        btn_close_x = QPushButton()
        btn_close_x.setFixedSize(28, 28)
        btn_close_x.setStyleSheet(
            "QPushButton { background: transparent;} "
            "QPushButton:hover { background: rgba(255,255,255,0.08); }"
        )
        if os.path.exists("assets/icon_close.png"):
            btn_close_x.setIcon(QIcon("assets/icon_close.png"))
        btn_close_x.clicked.connect(self.close)
        title_row.addWidget(btn_close_x)
        outer.addLayout(title_row)

        root = QFrame(self)
        root.setStyleSheet(
            "QFrame { background-color: rgba(60,60,60,0.4); border: 1px solid #5a5a5a; border-radius: 6px; }"
        )
        outer.addWidget(root)

        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 12, 14, 12)
        layout.setSpacing(10)

        body = QLabel(
            "Thank you for using this overlays!\n\n"
            "To interact with the overlays use simply click on the icons\n\n"
            "Set the settings to your prefered state.\n\n"
            "For more information, feel free to discuss in Discord server."
        )
        body.setStyleSheet("color: #c8c8c8; font-size: 11px; background: transparent; padding-left: 4px;")
        body.setWordWrap(True)
        layout.addWidget(body)

        self.dont_show_cb = QCheckBox("Don't show this again")
        self.dont_show_cb.setChecked(True)
        self.dont_show_cb.setStyleSheet(
            "QCheckBox { color: #d4c5a1; background: transparent; padding-left: 4px; }"
            "QCheckBox::indicator {"
            " width: 13px; height: 13px;"
            " border: 1px solid #5a5a5a; border-radius: 2px;"
            " background: rgba(28,28,28,0.9);"
            "}"
            "QCheckBox::indicator:checked {"
            " background: #4CAF50;"
            " border: 1px solid #5a5a5a;"
            "}"
        )
        self.dont_show_cb.toggled.connect(self._on_dont_show_toggled)
        layout.addWidget(self.dont_show_cb)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_close = QPushButton("Close")
        btn_close.setFixedSize(90, 24)
        btn_close.clicked.connect(self.close)
        btn_close.setStyleSheet(
            "QPushButton { background: rgba(60,60,60,0.95); color: #d4c5a1; border: 1px solid #5a5a5a; border-radius: 4px; padding: 2px 10px; }"
            "QPushButton:hover { background: rgba(80,80,80,0.95); }"
        )

        btn_settings = QPushButton("Open Settings")
        btn_settings.setFixedSize(118, 24)
        btn_settings.clicked.connect(self._on_open_settings)
        btn_settings.setStyleSheet(
            "QPushButton { background: #4CAF50; color: #ffffff; border: none; border-radius: 4px; font-weight: bold; padding: 2px 10px; }"
            "QPushButton:hover { background: #45a049; }"
        )

        btn_row.addWidget(btn_close)
        btn_row.addSpacing(8)
        btn_row.addWidget(btn_settings)
        layout.addLayout(btn_row)

        self.setFixedSize(560, 300)

        if cursor is not None:
            self._apply_cursor(cursor)

    def _apply_cursor(self, cursor):
        try:
            self.setCursor(cursor)
            for child in self.findChildren(QWidget):
                child.setCursor(cursor)
                child.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        except Exception:
            pass

    def center_on_primary_screen(self):
        screen = QApplication.primaryScreen()
        ag = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        self.move(
            ag.x() + (ag.width() - self.width()) // 2,
            ag.y() + (ag.height() - self.height()) // 2,
        )

    def _on_open_settings(self):
        checked = bool(self.dont_show_cb.isChecked())
        try:
            if callable(self._on_toggle_dont_show_cb):
                self._on_toggle_dont_show_cb(checked)
        except Exception:
            pass
        self.close()
        try:
            if callable(self._on_open_settings_cb):
                QTimer.singleShot(0, self._on_open_settings_cb)
        except Exception:
            pass

    def _on_dont_show_toggled(self, checked):
        try:
            if callable(self._on_toggle_dont_show_cb):
                self._on_toggle_dont_show_cb(bool(checked))
        except Exception:
            pass

    def closeEvent(self, event):
        try:
            if callable(self._on_dismissed_cb):
                self._on_dismissed_cb(bool(self.dont_show_cb.isChecked()))
        except Exception:
            pass
        super().closeEvent(event)

class OverlayWindow(QWidget):
    _move_requested = pyqtSignal(int, int)
    _drag_click_requested = pyqtSignal(int, int, bool)
    _live_ocr_ready = pyqtSignal(str)
    _list_scan_ready = pyqtSignal(str)
    _startup_task_done = pyqtSignal(str)
    startup_ready_changed = pyqtSignal()
    startup_status_changed = pyqtSignal(str)

    def _build_cursor_candidates(self):
        candidates = []
        try:
            if getattr(sys, "frozen", False):
                exe_dir = os.path.dirname(os.path.abspath(sys.executable))
                candidates.append(os.path.join(exe_dir, "assets", "cursor.cur"))
                meipass = getattr(sys, "_MEIPASS", None)
                if meipass:
                    candidates.append(os.path.join(str(meipass), "assets", "cursor.cur"))
            else:
                src_dir = os.path.dirname(os.path.abspath(__file__))
                candidates.append(os.path.join(src_dir, "assets", "cursor.cur"))
            candidates.append(os.path.join(os.getcwd(), "assets", "cursor.cur"))
        except Exception:
            pass

        uniq = []
        seen = set()
        for p in candidates:
            key = str(p).lower()
            if key in seen:
                continue
            seen.add(key)
            uniq.append(p)
        return uniq

    @staticmethod
    def _enum_window_titles():
        titles = []
        def _cb(hwnd, _):
            buf = create_unicode_buffer(256)
            windll.user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value:
                titles.append(buf.value)
            return True
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        windll.user32.EnumWindows(WNDENUMPROC(_cb), 0)
        return titles

    @staticmethod
    def _process_running(process_name):
        try:
            out = subprocess.check_output(
                f'tasklist /FI "IMAGENAME eq {process_name}" /FO CSV /NH',
                shell=True, text=True, stderr=subprocess.DEVNULL,
            )
            return process_name.lower() in out.lower()
        except Exception:
            return False

    @staticmethod
    def _game_running():
        if not OverlayWindow._process_running("sro_client.exe"):
            return False
        for title in OverlayWindow._enum_window_titles():
            if "[Legends Online]" in title or "sro_client" in title.lower():
                return True
        return False

    @staticmethod
    def _game_focused():
        hwnd = windll.user32.GetForegroundWindow()
        buf = create_unicode_buffer(256)
        windll.user32.GetWindowTextW(hwnd, buf, 256)
        title = buf.value
        return "[Legends Online]" in title or "sro_client" in title.lower()

    def __init__(self):
        super().__init__()
        self._release_info = None
        self._startup_ready = False
        self._startup_status_text = "Loading core modules..."
        self._update_check_pending = True
        self._startup_wait_template = not RELEASE_DISABLE_OCR
        self._startup_wait_tesseract = not RELEASE_DISABLE_OCR
        self._startup_wait_update = True
        try:
            from logic_engine import EventLogic, UniqueLogic, TimeManager
            self.event_logic = EventLogic()
            self.unique_logic = UniqueLogic()
            self.time_manager = TimeManager
        except ImportError:
            self.event_logic = None
            self.unique_logic = None

        # Initialize template bank lazily in the background to keep startup responsive.
        self._template_bank_ready = False

        self.labels = {}
        self.is_interactable = False
        self._drag_pos = QPoint()
        self.calendar_window = None
        self.cursor_hotspot = (0, 0)
        self.mouse_listener = None
        self.alerted_spawn = set()
        self.alerted_reg = set()
        self.alerted_1min = set()
        self.alerted_start = set()
        self._tts_startup = True
        self._esc_was_down = False
        self._last_game_running_check = 0.0
        self._cached_game_running = False
        self._settings_window = None
        self.tray = None
        self._resize_anim = None
        self._prewarm_started = False
        self._active_toasts = []
        self._unique_ocr_busy = False
        self._unique_ocr_seen_names = set()
        self._unique_ocr_last_raw_text = ""
        self._unique_ocr_last_error = ""
        self._unique_ocr_last_mode = "idle"
        self._unique_ocr_last_event_count = 0
        self._unique_ocr_last_strict_event_count = 0
        self._unique_ocr_last_capture_ts = 0.0
        self._tesseract_cmd = ""
        self._unique_ocr_row_payload = []
        self._list_scan_active = False
        self._list_scan_busy = False
        self._list_scan_deadline = 0.0
        self._list_scan_hud = None
        self._list_scan_capture_times = []
        self._ocr_region_preview = None
        self._first_run_window = None
        self._first_run_check_done = False
        self._has_saved_position = False

        self.cursor_paths = self._build_cursor_candidates()
        self.cursor_path = self.cursor_paths[0] if self.cursor_paths else os.path.join("assets", "cursor.cur")
        self._drag_use_cursor_polling = True
        self._drag_pending_xy = None
        self._last_drag_xy = None
        self._overlay_locked_cache = True
        self._overlay_locked_cache_ts = 0.0
        self.load_overlay_settings()
        self.init_ui()

        self._move_requested.connect(self._do_move)
        self._drag_click_requested.connect(self._handle_drag_click_ui)
        self._live_ocr_ready.connect(self._finish_live_ocr_job)
        self._list_scan_ready.connect(self._finish_list_scan_job)
        self._startup_task_done.connect(self._on_startup_task_done)
        self.setup_mouse_listener()

        self._drag_flush_timer = QTimer(self)
        self._drag_flush_timer.timeout.connect(self._flush_drag_move)
        self._drag_flush_timer.start(16)  # ~60 FPS max window movement
        self._drag_flush_timer.stop()

        cursor = self._get_custom_cursor()
        if cursor:
            self.setCursor(cursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

        self.input_timer = QTimer(self)
        self.input_timer.timeout.connect(self.handle_global_input)
        self.input_timer.start(16)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_content)
        self.timer.start(1000)

        self.unique_ocr_timer = QTimer(self)
        self.unique_ocr_timer.timeout.connect(self._on_unique_ocr_tick)
        self.unique_ocr_timer.start(1200)
        self.reload_unique_tracking_settings()
        if not RELEASE_DISABLE_OCR:
            QTimer.singleShot(120, self._configure_tesseract_backend_async)

        self.list_scan_timer = QTimer(self)
        self.list_scan_timer.timeout.connect(self._on_list_scan_tick)

        if not RELEASE_DISABLE_OCR:
            QTimer.singleShot(80, self._init_template_bank_async)
        QTimer.singleShot(2500, self._start_deferred_prewarm)

        self._vis_timer = QTimer(self)
        self._vis_timer.timeout.connect(self._check_game_visibility)
        self._vis_timer.start(250)

    def _init_template_bank_async(self):
        if self._template_bank_ready or not HAS_TEMPLATES or not self.unique_logic or init_template_bank is None:
            self._startup_task_done.emit("template")
            return

        self._set_startup_status("Preparing name templates...")

        def _worker():
            try:
                defs = self.unique_logic.load_definitions()
                self._template_bank_ready = bool(init_template_bank(defs))
            except Exception:
                self._template_bank_ready = False
            self._startup_task_done.emit("template")

        threading.Thread(target=_worker, daemon=True).start()

    def _configure_tesseract_backend_async(self):
        self._set_startup_status("Initializing OCR backend...")

        def _worker():
            try:
                self._configure_tesseract_backend()
            finally:
                self._startup_task_done.emit("tesseract")
        threading.Thread(target=_worker, daemon=True).start()

    def _set_startup_status(self, text: str):
        msg = str(text or "").strip()
        if not msg:
            return
        self._startup_status_text = msg
        self.startup_status_changed.emit(msg)

    def get_startup_status_text(self):
        return str(self._startup_status_text or "Loading data...")

    def _on_startup_task_done(self, task_name):
        name = str(task_name or "").strip().lower()
        if name == "template":
            self._startup_wait_template = False
        elif name == "tesseract":
            self._startup_wait_tesseract = False
        elif name == "update":
            self._startup_wait_update = False
        self._refresh_startup_state()

    def _refresh_startup_state(self):
        self._startup_ready = not (self._startup_wait_template or self._startup_wait_tesseract or self._startup_wait_update)
        if hasattr(self, "loading_label") and self.loading_label is not None:
            self.loading_label.setVisible(not self._startup_ready)
            if not self._startup_ready:
                self.loading_label.setText(self.get_startup_status_text())
        if self._startup_ready:
            self._set_startup_status("Startup complete")
            self.startup_ready_changed.emit()
            if not self._first_run_check_done:
                self._first_run_check_done = True
                QTimer.singleShot(900, self._show_first_run_if_needed)
            try:
                self.update_content()
            except Exception:
                pass
        else:
            waiting = []
            if self._startup_wait_update:
                waiting.append("version check")
            if self._startup_wait_tesseract:
                waiting.append("OCR")
            if self._startup_wait_template:
                waiting.append("templates")
            if waiting:
                self._set_startup_status("Loading: " + ", ".join(waiting) + "...")

    def startup_ready(self):
        return bool(self._startup_ready)

    def set_update_check_pending(self, pending: bool):
        self._update_check_pending = bool(pending)
        self._startup_wait_update = bool(pending)
        if self._startup_wait_update:
            self._set_startup_status("Checking latest version...")
        self._refresh_startup_state()

    def set_update_check_result(self, release_info):
        self._release_info = release_info if isinstance(release_info, dict) else None
        self._update_check_pending = False
        self._startup_wait_update = False
        if self._release_info:
            self._set_startup_status("Update available. Finalizing startup...")
        else:
            self._set_startup_status("Version is up to date. Finalizing startup...")
        self._refresh_update_banner()
        self._refresh_startup_state()

    def _refresh_update_banner(self):
        if not hasattr(self, "update_banner") or self.update_banner is None:
            return
        if isinstance(self._release_info, dict):
            v = str(self._release_info.get("version", "")).strip()
            text = f"Update available ({v}) - click to install" if v else "Update available - click to install"
            self.update_banner.setText(text)
            self.update_banner.show()
        else:
            self.update_banner.hide()

    def get_available_update_info(self):
        return self._release_info if isinstance(self._release_info, dict) else None

    def _show_first_run_if_needed(self):
        try:
            with open("settings.json", "r", encoding="utf-8") as f:
                settings = json.load(f)
        except Exception:
            settings = {}

        ui_cfg = settings.get("ui", {}) if isinstance(settings.get("ui", {}), dict) else {}
        if bool(ui_cfg.get("first_run_welcome_shown", False)):
            return

        try:
            if self._first_run_window is not None and self._first_run_window.isVisible():
                return
        except Exception:
            pass

        self._first_run_window = FirstRunWindow(
            cursor=self._get_custom_cursor(),
            on_open_settings=lambda: self.open_settings(force_reload=True),
            on_dismissed=self._mark_first_run_shown,
            on_toggle_dont_show=self._mark_first_run_shown,
        )
        self._first_run_window.center_on_primary_screen()
        self._first_run_window.show()

    def _mark_first_run_shown(self, dont_show_again=True):
        try:
            with open("settings.json", "r", encoding="utf-8") as f:
                settings = json.load(f)
        except Exception:
            settings = {}

        if not isinstance(settings.get("ui", {}), dict):
            settings["ui"] = {}
        settings["ui"]["first_run_welcome_shown"] = bool(dont_show_again)

        try:
            with open("settings.json", "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=2)
                f.flush()
        except Exception:
            pass

    def start_update_install(self):
        info = self.get_available_update_info()
        if not info:
            return False
        try:
            from updater import install_release_update
            return bool(install_release_update(info, parent=self))
        except Exception:
            return False

    def _check_game_visibility(self):
        now = time.monotonic()
        if (now - self._last_game_running_check) >= 3.0:
            self._cached_game_running = self._game_running()
            self._last_game_running_check = now
        if self._cached_game_running and self._game_focused():
            if not self.isVisible():
                self.show()
        else:
            if self.isVisible():
                self.hide()

    def _start_deferred_prewarm(self):
        if self._prewarm_started:
            return
        self._prewarm_started = True
        t = threading.Thread(target=self._background_prewarm, daemon=True)
        t.start()
        QTimer.singleShot(600, self._precreate_settings_window)
        QTimer.singleShot(1500, self._precreate_calendar_window)

    def _background_prewarm(self):
        try:
            import settings_gui  # noqa: F401
            import calendar_window  # noqa: F401
            from dependency_bootstrap import ensure_runtime_dependencies_first_run
            from tts_helper import get_tts_voices, ensure_tts_runtime_first_run
            ensure_runtime_dependencies_first_run()
            ensure_tts_runtime_first_run()
            get_tts_voices()
            for p in ("settings.json", "events.json", "uniques.json", "uniques_state.json"):
                if os.path.exists(p):
                    with open(p, "r", encoding="utf-8") as f:
                        f.read()
        except Exception:
            pass

    def _precreate_settings_window(self):
        try:
            if self._settings_window is None:
                from settings_gui import SettingsWindow
                self._settings_window = SettingsWindow(self)
                self._settings_window.hide()
        except Exception:
            pass

    def _precreate_calendar_window(self):
        try:
            if self.calendar_window is None:
                from calendar_window import CalendarWindow
                self.calendar_window = CalendarWindow(self)
                self.calendar_window.hide()
        except Exception:
            pass

    def _do_move(self, x, y):
        # Only move window, don't save to disk on every move
        # Position will be saved when drag ends
        self.move(x, y)

    def _flush_drag_move(self):
        try:
            if self.dragging and self._drag_use_cursor_polling:
                cur = QCursor.pos()
                self._drag_pending_xy = (cur.x() - self._drag_pos.x(), cur.y() - self._drag_pos.y())

            xy = self._drag_pending_xy
            if not xy or xy == self._last_drag_xy:
                return
            self._last_drag_xy = xy
            self.move(int(xy[0]), int(xy[1]))
        except Exception:
            pass

    def _is_overlay_locked(self, force_refresh=False):
        now = time.monotonic()
        if (not force_refresh) and (now - self._overlay_locked_cache_ts) < 0.15:
            return self._overlay_locked_cache
        self._overlay_locked_cache_ts = now
        try:
            with open("settings.json", "r", encoding="utf-8") as _f:
                _s = json.load(_f)
            self._overlay_locked_cache = bool(_s.get("overlay", {}).get("locked", True))
        except Exception:
            self._overlay_locked_cache = True
        return self._overlay_locked_cache

    def _is_alt_pressed(self):
        try:
            # VK_MENU (0x12), VK_LMENU (0xA4), VK_RMENU (0xA5)
            return bool(
                (windll.user32.GetAsyncKeyState(0x12) & 0x8000)
                or (windll.user32.GetAsyncKeyState(0xA4) & 0x8000)
                or (windll.user32.GetAsyncKeyState(0xA5) & 0x8000)
            )
        except Exception:
            return False

    def _handle_drag_click_ui(self, x, y, pressed):
        try:
            if pressed and self._click_toolbar_button_at(x, y):
                return

            alt_pressed = self._is_alt_pressed()
            is_locked = self._is_overlay_locked()
            overlay_rect = self.frameGeometry()
            attr = Qt.WidgetAttribute.WA_TransparentForMouseEvents
            interactive_now = not self.testAttribute(attr)
            can_drag_now = not is_locked
            if pressed and can_drag_now and not is_locked and overlay_rect.contains(QPoint(x, y)):
                self.dragging = True
                self._drag_pos = QPoint(x, y) - overlay_rect.topLeft()
                self._drag_pending_xy = (overlay_rect.x(), overlay_rect.y())
                self._last_drag_xy = None
                if hasattr(self, "_drag_flush_timer") and not self._drag_flush_timer.isActive():
                    self._drag_flush_timer.start(8)
            elif (not pressed) and self.dragging:
                self.dragging = False
                self._drag_pending_xy = None
                if hasattr(self, "_drag_flush_timer"):
                    self._drag_flush_timer.stop()
                current_pos = self.frameGeometry().topLeft()
                self._save_position(current_pos.x(), current_pos.y())
        except Exception:
            pass

    def _click_toolbar_button_at(self, x, y):
        try:
            if not self.isVisible():
                return False
            pt = QPoint(int(x), int(y))
            for btn in (self.btn_calendar, self.btn_uniques, self.btn_settings):
                if btn is None or not btn.isVisible():
                    continue
                top_left = btn.mapToGlobal(QPoint(0, 0))
                rect = QRect(top_left, btn.size())
                if rect.contains(pt):
                    btn.click()
                    return True
        except Exception:
            pass
        return False

    def _save_position(self, x, y):
        try:
            with open("settings.json", "r") as f:
                settings = json.load(f)
            settings.setdefault("overlay", {})["position"] = {"x": x, "y": y}
            with open("settings.json", "w") as f:
                json.dump(settings, f, indent=2)
        except Exception:
            pass

    def load_overlay_settings(self):
        try:
            with open("settings.json", "r") as f:
                settings = json.load(f)
                hotspot = settings.get("overlay", {}).get("cursor_hotspot", {})
                self.cursor_hotspot = (
                    int(hotspot.get("x", 0)),
                    int(hotspot.get("y", 0))
                )
                pos = settings.get("overlay", {}).get("position", {})
                if pos:
                    self._has_saved_position = True
                    self.move(int(pos.get("x", 100)), int(pos.get("y", 100)))
        except Exception:
            self.cursor_hotspot = (0, 0)
            self._has_saved_position = False

    def _get_default_overlay_position(self):
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        overlay_width = self.width() if self.width() > 0 else 220
        right_margin = int(geo.width() * 0.10)
        top_margin = int(geo.height() * 0.10)
        x = geo.x() + geo.width() - overlay_width - right_margin
        y = geo.y() + top_margin
        return max(geo.x(), x), max(geo.y(), y)

    def reload_unique_tracking_settings(self):
        try:
            with open("settings.json", "r", encoding="utf-8") as f:
                settings = json.load(f)
            uniq = settings.get("uniques", {})
            interval_ms = int(uniq.get("live_ocr", {}).get("interval_ms", 1200))
            interval_ms = max(500, min(10000, interval_ms))
            self.unique_ocr_timer.setInterval(interval_ms)
        except Exception:
            self.unique_ocr_timer.setInterval(1200)

    def _load_tesseract_cmd_from_settings(self):
        try:
            with open("settings.json", "r", encoding="utf-8") as f:
                settings = json.load(f)
            ocr_cfg = settings.get("ocr", {}) if isinstance(settings.get("ocr", {}), dict) else {}
            val = str(ocr_cfg.get("tesseract_cmd", "")).strip()
            return val
        except Exception:
            return ""

    def _configure_tesseract_backend(self):
        if not HAS_OCR_DEPS:
            self._tesseract_cmd = ""
            self._unique_ocr_last_error = "OCR deps missing (pytesseract/Pillow)"
            return False

        # Keep OCR CPU usage low to avoid system stalls during scans.
        os.environ.setdefault("OMP_THREAD_LIMIT", "1")
        os.environ.setdefault("OMP_NUM_THREADS", "1")

        saved_cmd = self._load_tesseract_cmd_from_settings()
        candidates = []
        if saved_cmd:
            candidates.append(saved_cmd)

        in_path = shutil.which("tesseract")
        if in_path:
            candidates.append(in_path)

        local_app = os.environ.get("LOCALAPPDATA", "")
        candidates.extend([
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            r"C:\ProgramData\chocolatey\bin\tesseract.exe",
            os.path.join(local_app, "Programs", "Tesseract-OCR", "tesseract.exe") if local_app else "",
        ])

        seen = set()
        for raw in candidates:
            cmd = str(raw or "").strip().strip('"')
            if not cmd:
                continue
            key = cmd.lower()
            if key in seen:
                continue
            seen.add(key)
            if not os.path.exists(cmd):
                continue
            try:
                pytesseract.pytesseract.tesseract_cmd = cmd
                _ = pytesseract.get_tesseract_version()
                self._tesseract_cmd = cmd
                self._unique_ocr_last_error = ""
                return True
            except Exception:
                continue

        self._tesseract_cmd = ""
        self._unique_ocr_last_error = "Tesseract executable not found. Install Tesseract or set settings.json ocr.tesseract_cmd"
        return False

    def _capture_ocr_text(self, scan_region=None, *, lightweight=False, require_region=False):
        if RELEASE_DISABLE_OCR:
            self._unique_ocr_last_error = "OCR disabled for this release"
            self._unique_ocr_last_raw_text = ""
            self._unique_ocr_row_payload = []
            self._unique_ocr_last_capture_ts = time.time()
            return ""
        if not HAS_OCR_DEPS:
            self._unique_ocr_last_error = "OCR deps missing (pytesseract/Pillow)"
            self._unique_ocr_last_raw_text = ""
            self._unique_ocr_last_capture_ts = time.time()
            return ""
        if not self._tesseract_cmd:
            if not self._configure_tesseract_backend():
                self._unique_ocr_last_raw_text = ""
                self._unique_ocr_last_capture_ts = time.time()
                return ""
        try:
            bbox = None
            monitor = None
            if isinstance(scan_region, dict):
                x = int(scan_region.get("x", 0))
                y = int(scan_region.get("y", 0))
                w = int(scan_region.get("width", 0))
                h = int(scan_region.get("height", 0))
                if w > 0 and h > 0:
                    r = self._dpi_ratio()
                    px, py = int(x * r), int(y * r)
                    pw, ph = int(w * r), int(h * r)
                    bbox = (px, py, px + pw, py + ph)
                    monitor = {"left": px, "top": py, "width": pw, "height": ph}

            if require_region and monitor is None:
                self._unique_ocr_last_error = "OCR region missing/invalid. Select region first."
                self._unique_ocr_last_raw_text = ""
                self._unique_ocr_row_payload = []
                self._unique_ocr_last_capture_ts = time.time()
                return ""

            img = None
            if HAS_MSS and monitor is not None:
                try:
                    with mss.mss() as sct:
                        sct_img = sct.grab(monitor)
                        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                except Exception:
                    img = None
            if img is None:
                # Safer fallback on Windows than forcing all_screens=True in worker threads.
                img = ImageGrab.grab(bbox=bbox) if bbox else ImageGrab.grab()

            if lightweight:
                # Minimal-cost path for list scan to avoid UI/PC stalls.
                gray = ImageOps.grayscale(img)
                gray = ImageOps.autocontrast(gray)
                # Keep image size bounded; do not upscale aggressively.
                max_w = 1600
                if gray.width > max_w:
                    ratio = max_w / float(gray.width)
                    gray = gray.resize((max_w, max(1, int(gray.height * ratio))))
                pre_img = gray
            else:
                if preprocess_for_ocr_pil is not None:
                    pre_img = preprocess_for_ocr_pil(img)
                else:
                    pre_img = img
                gray = ImageOps.grayscale(pre_img)
                gray = ImageOps.autocontrast(gray)

            candidates = []
            row_candidates = []

            def _score_text(txt):
                s = str(txt or "")
                s_l = s.lower()
                score = 0
                score += min(len(s), 2000) / 80.0
                score += 25 if "alive" in s_l else 0
                score += 25 if "dead" in s_l else 0
                score += 20 if "last updated" in s_l else 0
                score += 10 if "name" in s_l else 0
                score += 10 if "status" in s_l else 0
                score += 10 * min(10, s_l.count("ago"))
                return score

            if lightweight:
                self._unique_ocr_row_payload = []
                quick_mode_no_fallback = True
                try:
                    with open("settings.json", "r", encoding="utf-8") as f:
                        _s = json.load(f)
                    quick_mode_no_fallback = bool(
                        _s.get("uniques", {}).get("list_ocr", {}).get("fast_no_fallback", True)
                    )
                except Exception:
                    quick_mode_no_fallback = True
                
                # Primary path: crop-OCR rows first (more reliable than templates for this UI).
                if not self._unique_ocr_row_payload and self.unique_logic:
                    try:
                        known = []
                        seen_known = set()
                        for u in self.unique_logic.load_definitions():
                            for cand in (str(u.get("name","")), str(u.get("short_name",""))):
                                cand = cand.strip()
                                if not cand:
                                    continue
                                key = cand.lower()
                                if key in seen_known:
                                    continue
                                seen_known.add(key)
                                known.append(cand)

                        name_center_x, header_bottom_y = _detect_name_header_anchor(img)
                        body_start_default = int(img.height * 0.30)
                        body_start = (header_bottom_y + 10) if header_bottom_y is not None else body_start_default
                        name_lines = _extract_name_lines_from_column(
                            img, name_center_x, body_start, width_px=220
                        ) if name_center_x is not None else []

                        rows_hint = _combine_row_hints(img)

                        # Color rows are the most trustworthy source for status labels.
                        color_rows = []
                        if color_detect_table_rows is not None:
                            try:
                                color_rows = color_detect_table_rows(
                                    img,
                                    status_col_frac=(0.44, 0.62),
                                    broad_search=False,
                                ) or []
                            except Exception:
                                color_rows = []

                        def _nearest_status(y_val):
                            best = None
                            best_d = 10**9
                            for sr in color_rows:
                                sy = int(sr.get("y", -9999))
                                st = str(sr.get("status", "")).strip().lower()
                                if st not in ("alive", "dead"):
                                    continue
                                d = abs(sy - int(y_val))
                                if d < best_d:
                                    best_d = d
                                    best = st
                            if best in ("alive", "dead") and best_d <= 20:
                                return best
                            return None

                        micro_rows = []

                        # Primary: OCR line text from Name column directly.
                        source_rows = name_lines if name_lines else rows_hint[:70]
                        for rr in source_rows:
                            y = int(rr.get("y", 0))
                            row_h = int(rr.get("row_h", 14))

                            if y <= body_start:
                                continue

                            status = str(rr.get("status", "")).strip().lower()
                            if status not in ("alive", "dead"):
                                status = _nearest_status(y) or "unknown"
                            if status not in ("alive", "dead"):
                                continue

                            upd_crop = crop_row_columns(img, y, row_h, (0.62, 0.88)) \
                                if crop_row_columns else None

                            raw_name = str(rr.get("text", "")).strip()
                            if not raw_name:
                                name_crop = None
                                if name_center_x is not None:
                                    name_crop = _crop_name_fixed_width(img, y, row_h, name_center_x, width_px=220)
                                if name_crop is None:
                                    name_crop = crop_row_columns(img, y, row_h, (0.05, 0.33)) \
                                        if crop_row_columns else None
                                if name_crop is None:
                                    continue
                                name_crop = _tight_text_crop(name_crop)
                                if not _name_crop_has_text_signal(name_crop):
                                    continue
                                raw_name = _ocr_name_crop(name_crop)

                            mapped = _match_name_strict(raw_name, known, raw_name)
                            if mapped is None and best_name_match is not None and raw_name:
                                mapped = best_name_match(raw_name, raw_name, known)

                            if not mapped:
                                continue

                            raw_upd = ""
                            if upd_crop is not None:
                                try:
                                    upd_g = upd_crop.resize(
                                        (upd_crop.width * 3, upd_crop.height * 3), resample=5)
                                    upd_g = ImageOps.autocontrast(ImageOps.grayscale(upd_g))
                                    upd_g = upd_g.point(lambda p: 255 if p > 140 else 0)
                                    raw_upd = pytesseract.image_to_string(
                                        upd_g, config="--oem 3 --psm 7") or ""
                                except Exception:
                                    raw_upd = ""

                            micro_rows.append({
                                "name":         mapped,
                                "status":        status,
                                "last_updated":  raw_upd.strip(),
                                "line":          f"{mapped} {status} {raw_upd}".strip(),
                            })

                        if micro_rows:
                            self._unique_ocr_row_payload = micro_rows
                            candidates.append((900.0, f"[{len(micro_rows)} crop-ocr rows]"))
                    except Exception:
                        pass

                # Template matching is only enabled for learned custom templates.
                enable_template_fallback = True
                if (not self._unique_ocr_row_payload) and enable_template_fallback and self._template_bank_ready and HAS_CV and get_template_bank:
                    try:
                        import numpy as np
                        # Convert PIL image to cv2 format
                        pil_arr = np.array(pre_img)
                        if len(pil_arr.shape) == 2:
                            cv_img = pil_arr
                        else:
                            cv_img = pil_arr[:,:,::-1] if pil_arr.shape[2] >= 3 else pil_arr
                        
                        bank = get_template_bank()
                        use_templates = bool(getattr(bank, "has_custom_templates", lambda: False)())
                        if use_templates:
                            name_center_x, header_bottom_y = _detect_name_header_anchor(img)
                            body_start_y = (header_bottom_y + 10) if header_bottom_y is not None else int(img.height * 0.30)
                            x0 = 0
                            x1 = img.width
                            if name_center_x is not None:
                                half = max(55, 220 // 2)
                                x0 = max(0, int(name_center_x) - half)
                                x1 = min(img.width, int(name_center_x) + half)
                            h_cv, w_cv = cv_img.shape[:2]
                            sx = float(w_cv) / float(max(1, img.width))
                            sy = float(h_cv) / float(max(1, img.height))

                            body_start_y_cv = max(0, min(h_cv - 1, int(body_start_y * sy)))
                            x0_cv = max(0, min(w_cv - 1, int(x0 * sx)))
                            x1_cv = max(x0_cv + 1, min(w_cv, int(x1 * sx)))

                            if (h_cv - body_start_y_cv) < 8 or (x1_cv - x0_cv) < 16:
                                matches = {}
                            else:
                                search_cv = cv_img[body_start_y_cv:h_cv, x0_cv:x1_cv]
                                matches = bank.match_in_image(search_cv, threshold=0.84)
                        else:
                            matches = {}
                        
                        if matches and self.unique_logic:
                            status_rows = []
                            if color_detect_table_rows is not None:
                                try:
                                    status_rows = color_detect_table_rows(
                                        img,
                                        status_col_frac=(0.44, 0.62),
                                        broad_search=False,
                                    )
                                except Exception:
                                    status_rows = []

                            def _nearest_status(y_val):
                                best = None
                                best_d = 10**9
                                for sr in status_rows:
                                    sy = int(sr.get("y", -9999))
                                    d = abs(sy - int(y_val))
                                    if d < best_d:
                                        best_d = d
                                        best = str(sr.get("status", "")).strip().lower()
                                if best in ("alive", "dead") and best_d <= 18:
                                    return best
                                return "unknown"

                            rows_from_matches = []
                            for name, locs in matches.items():
                                for loc in locs:
                                    y_guess_cv = body_start_y_cv + int(loc.get("y", 0))
                                    y_guess = int(y_guess_cv / max(sy, 1e-6))
                                    if header_bottom_y is not None and y_guess <= (header_bottom_y + 12):
                                        continue

                                    row_h_guess_cv = int(loc.get("h", 14))
                                    row_h_guess = max(10, int(row_h_guess_cv / max(sy, 1e-6)))

                                    st = "unknown"
                                    if crop_row_columns is not None:
                                        try:
                                            st_crop = crop_row_columns(img, y_guess, row_h_guess, (0.44, 0.62))
                                        except Exception:
                                            st_crop = None
                                        if st_crop is not None:
                                            try:
                                                g = ImageOps.autocontrast(ImageOps.grayscale(st_crop))
                                                g = g.resize((max(1, g.width * 3), max(1, g.height * 3)), resample=5)
                                                g = g.point(lambda p: 255 if p > 145 else 0)
                                                st_text = pytesseract.image_to_string(g, config="--oem 3 --psm 7") or ""
                                                if infer_status is not None:
                                                    st = infer_status(st_text) or "unknown"
                                            except Exception:
                                                st = "unknown"

                                    if st not in ("alive", "dead"):
                                        st = _nearest_status(y_guess)
                                    if st not in ("alive", "dead"):
                                        continue
                                    rows_from_matches.append({
                                        "name": name,
                                        "status": st,
                                        "last_updated": "",
                                        "line": name,
                                        "score": 0.9
                                    })
                            if rows_from_matches:
                                self._unique_ocr_row_payload = rows_from_matches
                                candidates.append((1000.0, f"[{len(rows_from_matches)} template matches]"))
                    except Exception:
                        pass
                
                # Optional OCR fallback (off by default for maximum smoothness).
                if (not self._unique_ocr_row_payload) and (not quick_mode_no_fallback):
                    light_img = pre_img.point(lambda p: 255 if p > 165 else 0)
                    txt11 = pytesseract.image_to_string(light_img, config="--oem 3 --psm 11") or ""
                    candidates.append((_score_text(txt11), txt11))
                    if extract_rows_from_text is not None and self.unique_logic:
                        try:
                            known = []
                            seen_known = set()
                            for u in self.unique_logic.load_definitions():
                                full = str(u.get("name", "")).strip()
                                if not full:
                                    continue
                                key = full.lower()
                                if key in seen_known:
                                    continue
                                seen_known.add(key)
                                known.append(full)

                            merged_rows = []
                            seen_rows = set()
                            for row in extract_rows_from_text(txt11, known):
                                key = (
                                    str(row.get("name", "")).strip().lower(),
                                    str(row.get("status", "")).strip().lower(),
                                    str(row.get("last_updated", "")).strip().lower(),
                                )
                                if key in seen_rows:
                                    continue
                                seen_rows.add(key)
                                merged_rows.append(row)
                            self._unique_ocr_row_payload = merged_rows
                        except Exception:
                            self._unique_ocr_row_payload = []
            else:
                # Upscale improves readability for small table fonts in Unique History.
                big = gray.resize((max(1, gray.width * 2), max(1, gray.height * 2)))
                bw_140 = big.point(lambda p: 255 if p > 140 else 0)
                bw_170 = big.point(lambda p: 255 if p > 170 else 0)
                cv_bw = None
                if HAS_CV and pil_to_binary_cv is not None:
                    try:
                        cv_arr = pil_to_binary_cv(pre_img)
                        if cv_arr is not None:
                            cv_bw = Image.fromarray(cv_arr)
                    except Exception:
                        cv_bw = None

                images_to_try = [big, bw_140, bw_170]
                if cv_bw is not None:
                    images_to_try.append(cv_bw)

                for im in images_to_try:
                    for psm in (6, 4, 11):
                        cfg = f"--oem 3 --psm {psm}"
                        txt = pytesseract.image_to_string(im, config=cfg) or ""
                        candidates.append((_score_text(txt), txt))
                        rows = self._extract_strict_ocr_rows(im, cfg)
                        row_candidates.append((len(rows), rows))

            candidates.sort(key=lambda item: item[0], reverse=True)
            selected = candidates[0][1] if candidates else ""
            if not lightweight:
                row_candidates.sort(key=lambda item: item[0], reverse=True)
                self._unique_ocr_row_payload = row_candidates[0][1] if row_candidates else []

            if not self._unique_ocr_row_payload and selected and extract_rows_from_text is not None and self.unique_logic:
                try:
                    known = []
                    seen_known = set()
                    for u in self.unique_logic.load_definitions():
                        full = str(u.get("name", "")).strip()
                        if not full:
                            continue
                        key = full.lower()
                        if key in seen_known:
                            continue
                        seen_known.add(key)
                        known.append(full)
                    self._unique_ocr_row_payload = extract_rows_from_text(selected, known)
                except Exception:
                    self._unique_ocr_row_payload = []

            self._unique_ocr_last_error = ""
            self._unique_ocr_last_raw_text = selected
            self._unique_ocr_last_capture_ts = time.time()
            return selected
        except Exception as ex:
            self._unique_ocr_last_error = f"Capture error: {ex}"
            self._unique_ocr_last_raw_text = ""
            self._unique_ocr_row_payload = []
            self._unique_ocr_last_capture_ts = time.time()
            return ""

    @staticmethod
    def _dpi_ratio():
        """Return primary screen device pixel ratio (logical→physical scale)."""
        try:
            from PyQt6.QtWidgets import QApplication as _QApp
            s = _QApp.primaryScreen()
            return float(s.devicePixelRatio()) if s else 1.0
        except Exception:
            return 1.0

    def _grab_region_image(self, scan_region=None, *, require_region=False):
        bbox = None
        monitor = None
        if isinstance(scan_region, dict):
            x = int(scan_region.get("x", 0))
            y = int(scan_region.get("y", 0))
            w = int(scan_region.get("width", 0))
            h = int(scan_region.get("height", 0))
            if w > 0 and h > 0:
                r = self._dpi_ratio()
                px, py = int(x * r), int(y * r)
                pw, ph = int(w * r), int(h * r)
                bbox = (px, py, px + pw, py + ph)
                monitor = {"left": px, "top": py, "width": pw, "height": ph}

        if require_region and monitor is None:
            raise ValueError("invalid scan region")

        img = None
        if HAS_MSS and monitor is not None:
            try:
                with mss.mss() as sct:
                    sct_img = sct.grab(monitor)
                    img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            except Exception:
                img = None
        if img is None:
            img = ImageGrab.grab(bbox=bbox) if bbox else ImageGrab.grab()
        return img

    @staticmethod
    def _slug_name(text: str) -> str:
        s = str(text or "").strip().lower()
        out = []
        prev_sep = False
        for ch in s:
            if ch.isalnum():
                out.append(ch)
                prev_sep = False
            elif not prev_sep:
                out.append("_")
                prev_sep = True
        return ("".join(out).strip("_") or "name")

    def learn_unique_templates(self):
        """Capture list region and auto-save per-name custom templates for fast matching."""
        if RELEASE_DISABLE_OCR:
            return {"ok": False, "message": "Under Development. OCR templates release in next version."}
        if not HAS_OCR_DEPS:
            return {"ok": False, "message": "Learn failed: OCR deps missing"}
        if not self.unique_logic:
            return {"ok": False, "message": "Learn failed: unique logic unavailable"}

        try:
            with open("settings.json", "r", encoding="utf-8") as f:
                settings = json.load(f)
            uniq = settings.get("uniques", {})
            scan_region = uniq.get("list_ocr", {}).get("scan_region", settings.get("ocr", {}).get("scan_region", {}))
        except Exception:
            scan_region = {}

        if not self._tesseract_cmd:
            self._configure_tesseract_backend()

        learn_passes = 10
        learn_interval_sec = 0.45
        captures = []
        for _ in range(learn_passes):
            try:
                cap = self._grab_region_image(scan_region, require_region=True)
                if cap is not None:
                    captures.append(cap)
            except Exception:
                pass
            time.sleep(learn_interval_sec)

        if not captures:
            return {"ok": False, "message": "Learn failed: capture error (no frames)"}

        # Use first frame for deterministic debug snapshots; process all for voting.
        img = captures[0]

        defs = self.unique_logic.load_definitions()
        known_names = []
        seen = set()
        for u in defs:
            full = str(u.get("name", "")).strip()
            if not full:
                continue
            key = full.lower()
            if key in seen:
                continue
            seen.add(key)
            known_names.append(full)

        rows = []
        _debug_dir = ".templates_cache"
        os.makedirs(_debug_dir, exist_ok=True)
        try:
            img.save(os.path.join(_debug_dir, "debug_capture.png"))
        except Exception:
            pass

        rows = _combine_row_hints(img)
        name_center_x, header_bottom_y = _detect_name_header_anchor(img)
        body_start = (header_bottom_y + 10) if header_bottom_y is not None else int(img.height * 0.30)
        name_lines = _extract_name_lines_from_column(
            img, name_center_x, body_start, width_px=220
        ) if name_center_x is not None else []
        if name_lines:
            rows = [{"y": int(r["y"]), "row_h": int(r.get("row_h", 14)), "text": str(r.get("text", ""))} for r in name_lines]

        # If still no rows: save status-band crop + sample color stats for diagnosis
        if not rows:
            try:
                iw, ih = img.size
                x0 = int(iw * 0.40)
                x1 = int(iw * 0.62)
                band = img.crop((x0, 0, x1, ih))
                band.save(os.path.join(_debug_dir, "debug_status_band.png"))

                # Sample max R/G/B per 10-row strip so user can see actual game colors
                import numpy as _np
                arr = _np.array(img.convert("RGB"))
                b = arr[:, x0:x1, :]
                stats_lines = []
                step = max(1, ih // 20)
                for sy in range(0, ih, step):
                    ey = min(ih, sy + step)
                    chunk = b[sy:ey]
                    mr, mg, mb = int(chunk[:,:,0].max()), int(chunk[:,:,1].max()), int(chunk[:,:,2].max())
                    stats_lines.append(f"y={sy:4d}-{ey:4d}  maxR={mr:3d} maxG={mg:3d} maxB={mb:3d}")
                with open(os.path.join(_debug_dir, "debug_color_stats.txt"), "w") as _f:
                    _f.write("\n".join(stats_lines))
            except Exception:
                pass
            return {"ok": False, "message": (
                "Learn failed: no rows detected. "
                "Saved debug_capture.png + debug_status_band.png + debug_color_stats.txt "
                f"in {_debug_dir}/ — open them to check if region/colors are correct."
            )}

        if not rows:
            return {"ok": False, "message": "Learn failed: no rows detected (check region)"}

        custom_dir = os.path.join(".templates_cache", "custom")
        os.makedirs(custom_dir, exist_ok=True)

        best_crop_by_name = {}
        unknown = 0

        for img_cap in captures:
            cap_rows = _combine_row_hints(img_cap)
            cap_name_center_x, cap_header_bottom_y = _detect_name_header_anchor(img_cap)
            cap_body_start = (cap_header_bottom_y + 10) if cap_header_bottom_y is not None else int(img_cap.height * 0.30)
            cap_name_lines = _extract_name_lines_from_column(
                img_cap, cap_name_center_x, cap_body_start, width_px=220
            ) if cap_name_center_x is not None else []
            if cap_name_lines:
                cap_rows = [{"y": int(r["y"]), "row_h": int(r.get("row_h", 14)), "text": str(r.get("text", ""))} for r in cap_name_lines]

            for row in cap_rows:
                y = int(row.get("y", 0))
                row_h = int(row.get("row_h", 14))
                if y <= cap_body_start:
                    continue

                crop = None
                if cap_name_center_x is not None:
                    crop = _crop_name_fixed_width(img_cap, y, row_h, cap_name_center_x, width_px=220)
                if crop is None and crop_row_columns is not None:
                    crop = crop_row_columns(img_cap, y, row_h, (0.05, 0.33))
                if crop is None:
                    w, h = img_cap.size
                    y0 = max(0, y - max(6, row_h // 2))
                    y1 = min(h, y + max(6, row_h // 2))
                    crop = img_cap.crop((int(w * 0.05), y0, int(w * 0.33), y1))

                if crop is None or crop.width < 20 or crop.height < 8:
                    continue

                crop = _tight_text_crop(crop)
                if not _name_crop_has_text_signal(crop):
                    unknown += 1
                    continue
                prep = _preprocess_name_crop(crop)
                text = str(row.get("text", "")).strip() or _ocr_name_crop(crop)

                match = _match_name_strict(text, known_names, text)
                if match is None and best_name_match is not None:
                    match = best_name_match(text, text, known_names)

                if not match:
                    unknown += 1
                    continue

                canonical = str(match).strip()
                if not canonical:
                    continue
                score = len(text or "")
                prev = best_crop_by_name.get(canonical)
                if prev is None or score > prev[0]:
                    best_crop_by_name[canonical] = (score, prep if prep is not None else crop)

        saved = 0
        touched = set()
        for canonical, (_, image_to_save) in best_crop_by_name.items():
            out_path = os.path.join(custom_dir, f"{self._slug_name(canonical)}.png")
            try:
                image_to_save.save(out_path)
                saved += 1
                touched.add(canonical)
            except Exception:
                pass

        if saved <= 0:
            return {"ok": False, "message": f"Learn failed: no matched names (rows={len(rows)}, unknown={unknown})"}

        # Rebuild template bank with new crops
        if init_template_bank is not None:
            try:
                self._template_bank_ready = bool(init_template_bank(defs))
            except Exception:
                pass

        return {
            "ok": True,
            "saved": saved,
            "unique_names": len(touched),
            "rows": len(rows),
            "message": f"Learn OK: saved {saved} templates for {len(touched)} uniques (captures={len(captures)}, unmatched={unknown})",
        }

    def _extract_strict_ocr_rows(self, image, config):
        try:
            data = pytesseract.image_to_data(image, config=config, output_type=pytesseract.Output.DICT)
        except Exception:
            return []

        n = len(data.get("text", []))
        words = []

        for i in range(n):
            txt = str(data["text"][i] or "").strip()
            if not txt:
                continue
            conf_raw = str(data.get("conf", ["-1"] * n)[i])
            try:
                conf = float(conf_raw)
            except Exception:
                conf = -1.0
            if conf < 20:
                continue
            left = int(data.get("left", [0] * n)[i])
            top = int(data.get("top", [0] * n)[i])
            w = int(data.get("width", [0] * n)[i])
            h = int(data.get("height", [0] * n)[i])
            words.append({
                "text": txt,
                "left": left,
                "top": top,
                "width": w,
                "height": h,
                "x_center": left + (w // 2),
                "y_center": top + (h // 2),
            })

        if not words:
            return []

        out_rows = []

        def _norm(value):
            s = str(value or "").lower().strip()
            s = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", s)
            s = re.sub(r"[^a-z0-9]+", " ", s)
            return re.sub(r"\s+", " ", s).strip()

        def _status_from_word(word):
            w = str(word or "").lower()
            if not w:
                return None
            if w in ("alive", "a1ive", "aive"):
                return "alive"
            if w in ("dead", "deod", "deac"):
                return "dead"
            if len(w) >= 3:
                from difflib import SequenceMatcher
                if SequenceMatcher(None, w, "alive").ratio() >= 0.72:
                    return "alive"
                if SequenceMatcher(None, w, "dead").ratio() >= 0.72:
                    return "dead"
            return None

        ago_re = re.compile(
            r"(?i)([0-9OQDoIlIsSB]{1,3}\s*h(?:\s*[0-9OQDoIlIsSB]{1,3}\s*m)?(?:\s*[0-9OQDoIlIsSB]{1,3}\s*s)?\s*ag[ao0]?|"
            r"[0-9OQDoIlIsSB]{1,3}\s*m(?:\s*[0-9OQDoIlIsSB]{1,3}\s*s)?\s*ag[ao0]?|"
            r"[0-9OQDoIlIsSB]{1,3}\s*s\s*ag[ao0]?)"
        )

        # Build known unique name dictionary for fuzzy matching.
        known_names = []
        try:
            if self.unique_logic:
                known_names = [
                    str(u.get("name", "")).strip()
                    for u in self.unique_logic.load_definitions()
                    if str(u.get("name", "")).strip()
                ]
        except Exception:
            known_names = []
        name_norm_map = {name: _norm(name) for name in known_names}

        img_w = max(1, int(image.width))
        # Column zones relative to selected OCR region.
        name_min_x = int(img_w * 0.08)
        name_max_x = int(img_w * 0.52)
        status_min_x = int(img_w * 0.44)
        status_max_x = int(img_w * 0.68)
        updated_min_x = int(img_w * 0.62)
        updated_max_x = int(img_w * 0.98)

        # Calibrate columns dynamically from header words when possible.
        top_words = [w for w in words if w["y_center"] <= int(image.height * 0.28)]

        def _best_header_word_center(target):
            best = (0.0, None)
            for w in top_words:
                txt = str(w.get("text", "")).lower()
                if not txt:
                    continue
                ratio = SequenceMatcher(None, txt, target).ratio()
                if ratio > best[0]:
                    best = (ratio, w)
            return best[1] if best[0] >= 0.62 else None

        w_name = _best_header_word_center("name")
        w_status = _best_header_word_center("status")
        w_last = _best_header_word_center("last")
        w_updated = _best_header_word_center("updated")

        if w_name and w_status:
            split_ns = int((w_name["x_center"] + w_status["x_center"]) / 2)
            name_min_x = max(0, int(w_name["x_center"] - img_w * 0.22))
            name_max_x = max(name_min_x + 10, split_ns)

        if w_status:
            status_center = int(w_status["x_center"])
            status_min_x = max(0, status_center - int(img_w * 0.10))
            status_max_x = min(img_w, status_center + int(img_w * 0.10))

        if w_last or w_updated:
            if w_last and w_updated:
                upd_center = int((w_last["x_center"] + w_updated["x_center"]) / 2)
            else:
                upd_center = int((w_last or w_updated)["x_center"])
            updated_min_x = max(0, upd_center - int(img_w * 0.18))
            updated_max_x = min(img_w, upd_center + int(img_w * 0.22))

        # Cluster words into horizontal bands (rows) by Y center.
        words_sorted_y = sorted(words, key=lambda w: w["y_center"])
        row_bands = []
        y_tol = 11
        for wd in words_sorted_y:
            if not row_bands or abs(wd["y_center"] - row_bands[-1]["y"]) > y_tol:
                row_bands.append({"y": wd["y_center"], "words": [wd]})
            else:
                band = row_bands[-1]
                band["words"].append(wd)
                band["y"] = int((band["y"] + wd["y_center"]) / 2)

        def _best_name_from_text(name_text):
            name_text_n = _norm(name_text)
            if not name_text_n:
                return None

            # Try direct containment first.
            for k, kn in name_norm_map.items():
                if kn and (kn in name_text_n or name_text_n in kn):
                    return k

            # Try fuzzy against full segment.
            best_name = None
            best_ratio = 0.0
            for k, kn in name_norm_map.items():
                if not kn:
                    continue
                ratio = SequenceMatcher(None, name_text_n, kn).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_name = k
            if best_name and best_ratio >= 0.62:
                return best_name

            # Try sliding windows of name tokens.
            parts = name_text_n.split()
            for start in range(len(parts)):
                for end in range(start + 1, min(len(parts), start + 5) + 1):
                    piece = " ".join(parts[start:end])
                    for k, kn in name_norm_map.items():
                        if not kn:
                            continue
                        ratio = SequenceMatcher(None, piece, kn).ratio()
                        if ratio >= 0.68:
                            return k
            return None

        row_seen = set()

        # Hybrid mode: detect likely text rows with CV, OCR each row crop separately.
        if HAS_CV and extract_text_row_rects is not None:
            try:
                rects = extract_text_row_rects(image)
                for x, y, w, h in rects:
                    if w < 80 or h < 10:
                        continue
                    crop = image.crop((x, y, x + w, y + h))
                    row_text = pytesseract.image_to_string(crop, config="--oem 3 --psm 7") or ""
                    line_text = " ".join(row_text.split())
                    line_l = line_text.lower()
                    if not line_text:
                        continue
                    if (
                        "unique history" in line_l
                        or ("name" in line_l and "status" in line_l)
                        or "list ocr scan region" in line_l
                        or "searching columns" in line_l
                    ):
                        continue

                    mapped_name_any = _best_name_from_text(line_text)
                    status_any = None
                    for tok in re.findall(r"[A-Za-z0-9]+", line_text):
                        status_any = _status_from_word(tok)
                        if status_any:
                            break
                    ago_any_m = ago_re.search(line_text)
                    last_updated_any = ago_any_m.group(1) if ago_any_m else ""
                    if not last_updated_any and "ag" in line_l:
                        last_updated_any = line_text

                    if mapped_name_any and status_any and last_updated_any:
                        key = (mapped_name_any, status_any, _norm(last_updated_any))
                        if key not in row_seen:
                            row_seen.add(key)
                            out_rows.append({
                                "name": mapped_name_any,
                                "status": status_any,
                                "last_updated": last_updated_any,
                                "line": line_text,
                            })
            except Exception:
                pass

        for band in row_bands:
            band_words = sorted(band["words"], key=lambda w: w["left"])
            line_text = " ".join(w["text"] for w in band_words)
            line_l = line_text.lower()
            if (
                "unique history" in line_l
                or ("name" in line_l and "status" in line_l)
                or "list ocr scan region" in line_l
                or "searching columns" in line_l
                or "dead alive" in line_l
            ):
                continue

            # Primary same-line parse: detect name/status/ago anywhere in the same row band.
            mapped_name_any = _best_name_from_text(line_text)
            status_any = None
            for tok in re.findall(r"[A-Za-z0-9]+", line_text):
                status_any = _status_from_word(tok)
                if status_any:
                    break
            ago_any_m = ago_re.search(line_text)
            last_updated_any = ago_any_m.group(1) if ago_any_m else ""
            if not last_updated_any and "ag" in line_l:
                last_updated_any = line_text

            if mapped_name_any and status_any and last_updated_any:
                key = (mapped_name_any, status_any, _norm(last_updated_any))
                if key not in row_seen:
                    row_seen.add(key)
                    out_rows.append({
                        "name": mapped_name_any,
                        "status": status_any,
                        "last_updated": last_updated_any,
                        "line": line_text,
                    })
                continue

            name_words = [w["text"] for w in band_words if name_min_x <= w["x_center"] <= name_max_x]
            if not name_words:
                continue
            name_text = " ".join(name_words).strip()
            mapped_name = _best_name_from_text(name_text)
            if not mapped_name:
                continue

            status_words = [w["text"] for w in band_words if status_min_x <= w["x_center"] <= status_max_x]
            status = None
            for sw in status_words:
                status = _status_from_word(sw)
                if status:
                    break
            if not status:
                continue

            updated_words = [w["text"] for w in band_words if updated_min_x <= w["x_center"] <= updated_max_x]
            updated_text = " ".join(updated_words).strip()
            ago_match = ago_re.search(updated_text)
            last_updated = ago_match.group(1) if ago_match else ""
            if not last_updated and "ag" in updated_text.lower():
                last_updated = updated_text
            if not last_updated:
                continue

            key = (mapped_name, status, _norm(last_updated))
            if key in row_seen:
                continue
            row_seen.add(key)

            out_rows.append({
                "name": mapped_name,
                "status": status,
                "last_updated": last_updated,
                "line": line_text,
            })

        if out_rows:
            return out_rows

        # Fallback: old row grouping when y-aligned columns find nothing.
        grouped = {}
        for wd in words:
            key = (wd["top"] // 8)
            grouped.setdefault(key, []).append((wd["left"], wd["text"]))

        for key in sorted(grouped.keys()):
            row_words = [w for _, w in sorted(grouped[key], key=lambda x: x[0])]
            line_text = " ".join(row_words).strip()
            if not line_text:
                continue

            line_l = line_text.lower()
            if (
                "unique history" in line_l
                or ("name" in line_l and "status" in line_l)
                or "list ocr scan region" in line_l
                or "searching columns" in line_l
            ):
                continue

            status_idx = -1
            status = None
            for idx, word in enumerate(row_words):
                st = _status_from_word(word)
                if st:
                    status_idx = idx
                    status = st
                    break

            if status_idx <= 0 or not status:
                continue

            name_text = " ".join(row_words[:status_idx]).strip()
            if len(name_text) < 3:
                continue

            tail_text = " ".join(row_words[status_idx + 1 :]).strip()
            ago_match = ago_re.search(tail_text)
            last_updated = ago_match.group(1) if ago_match else ""
            if not last_updated and "ago" in tail_text.lower():
                last_updated = tail_text
            if not last_updated:
                continue

            mapped_name = _best_name_from_text(name_text)
            if not mapped_name:
                continue

            out_rows.append({
                "name": mapped_name,
                "status": status,
                "last_updated": last_updated,
                "line": line_text,
            })

        return out_rows

    def _consume_unique_ocr_text(self, text, *, for_list_scan=False):
        self._unique_ocr_last_mode = "list_scan" if for_list_scan else "live_ocr"
        if not self.unique_logic:
            self._unique_ocr_last_error = "Unique logic unavailable"
            self._unique_ocr_last_event_count = 0
            return

        strict_row_only = True
        try:
            with open("settings.json", "r", encoding="utf-8") as f:
                settings = json.load(f)
            uniq_cfg = settings.get("uniques", {}) if isinstance(settings.get("uniques", {}), dict) else {}
            strict_row_only = bool(uniq_cfg.get("strict_row_only", True))
        except Exception:
            strict_row_only = True

        row_events = []
        try:
            row_events = self.unique_logic.process_ocr_rows(self._unique_ocr_row_payload)
        except Exception as ex:
            row_events = []
            self._unique_ocr_last_error = f"Strict row parser error: {ex}"

        if not row_events and self._unique_ocr_row_payload:
            # Overlay-level safety net: force one timer from first strict row when logic returned nothing.
            try:
                row0 = self._unique_ocr_row_payload[0]
                raw_name = str(row0.get("name", "")).strip()
                raw_status = str(row0.get("status", "")).strip().lower()
                raw_updated = str(row0.get("last_updated", "")).strip()
                row_line = str(row0.get("line", ""))

                defs = self.unique_logic.load_definitions() if self.unique_logic else []
                known = [str(u.get("name", "")).strip() for u in defs if str(u.get("name", "")).strip()]
                mapped = None
                # 1) direct case-insensitive exact
                raw_l = raw_name.lower()
                for n in known:
                    if n.lower() == raw_l:
                        mapped = n
                        break
                # 2) helper match
                if mapped is None and best_name_match is not None:
                    mapped = best_name_match(raw_name, row_line, known)
                if mapped is None:
                    mapped = _match_name_strict(raw_name, known, row_line)
                # 3) existing resolver fallback
                if mapped is None:
                    mapped = self.unique_logic._resolve_unique_name_from_ocr(raw_name or row_line, row_line, known)
                # 4) last resort: use OCR name directly.
                if mapped is None and raw_name:
                    mapped = raw_name

                if mapped:
                    when = self.unique_logic._parse_ocr_last_updated(raw_updated)
                    if when is None:
                        when = self.unique_logic._parse_ocr_last_updated(row_line)
                    if when is None:
                        when = datetime.now()

                    status = raw_status
                    if status not in ("alive", "dead"):
                        if infer_status is not None:
                            status = infer_status(raw_status + " " + row_line) or "dead"
                        else:
                            status = "alive" if "alive" in (raw_status + " " + row_line).lower() else "dead"

                    if status == "alive":
                        self.unique_logic.update_spawn(mapped, when=when, source="ocr_overlay_fallback")
                        action = "spawn"
                    else:
                        self.unique_logic.update_death(mapped, when=when, source="ocr_overlay_fallback")
                        action = "kill"

                    row_events = [{"name": mapped, "action": action, "when": when.strftime("%Y-%m-%d %H:%M:%S")}]
                else:
                    self._unique_ocr_last_error = f"Fallback map failed: name='{raw_name}'"
            except Exception:
                import traceback
                self._unique_ocr_last_error = f"Overlay fallback error: {traceback.format_exc().splitlines()[-1]}"

        # Last resort for all strict rows: if still no events, force updates from each row payload.
        if not row_events and self._unique_ocr_row_payload and self.unique_logic:
            forced_events = []
            for row in self._unique_ocr_row_payload:
                raw_name = str(row.get("name", "")).strip()
                if not raw_name:
                    continue
                raw_status = str(row.get("status", "")).strip().lower()
                raw_updated = str(row.get("last_updated", "")).strip()
                row_line = str(row.get("line", ""))

                when = self.unique_logic._parse_ocr_last_updated(raw_updated)
                if when is None:
                    when = self.unique_logic._parse_ocr_last_updated(row_line)
                if when is None:
                    when = datetime.now()

                status = raw_status
                if status not in ("alive", "dead"):
                    if infer_status is not None:
                        status = infer_status(raw_status + " " + row_line) or "dead"
                    else:
                        status = "alive" if "alive" in (raw_status + " " + row_line).lower() else "dead"

                if status == "alive":
                    self.unique_logic.update_spawn(raw_name, when=when, source="ocr_overlay_force")
                    action = "spawn"
                else:
                    self.unique_logic.update_death(raw_name, when=when, source="ocr_overlay_force")
                    action = "kill"

                forced_events.append({"name": raw_name, "action": action, "when": when.strftime("%Y-%m-%d %H:%M:%S")})

            if forced_events:
                row_events = forced_events
                self._unique_ocr_last_error = ""

        self._unique_ocr_last_strict_event_count = len(row_events)

        if strict_row_only:
            if row_events:
                events = row_events
            else:
                # Rescue path: if strict rows are empty due noisy OCR flattening,
                # still attempt text parser so timers can be populated.
                text_events = self.unique_logic.process_ocr_text(text) if text else []
                if text_events:
                    events = text_events
                else:
                    if not self._unique_ocr_last_error:
                        self._unique_ocr_last_error = "No strict row matched (Name+Status+Last Updated on same row)"
                    self._unique_ocr_last_event_count = 0
                    return
        else:
            if not text:
                if row_events:
                    events = row_events
                else:
                    self._unique_ocr_last_error = self._unique_ocr_last_error or "OCR returned empty text"
                    self._unique_ocr_last_event_count = 0
                    return
            else:
                text_events = self.unique_logic.process_ocr_text(text)
                events = row_events + text_events

        # Deduplicate merged row/text events.
        uniq_events = []
        seen = set()
        for ev in events:
            key = (ev.get("name", ""), ev.get("action", ""), ev.get("when", ""))
            if key in seen:
                continue
            seen.add(key)
            uniq_events.append(ev)
        events = uniq_events

        self._unique_ocr_last_event_count = len(events)
        if not events:
            self._unique_ocr_last_error = "No table rows matched (Name/Status/Last Updated)"
            return
        self._unique_ocr_last_error = ""
        for event in events:
            self._unique_ocr_seen_names.add(event.get("name", ""))
        if for_list_scan and self._list_scan_hud is not None:
            self._list_scan_hud.set_detected(self._unique_ocr_seen_names)

    def get_unique_ocr_debug_snapshot(self):
        tracking_mode = "unknown"
        live_enabled = False
        strict_row_only = True
        try:
            with open("settings.json", "r", encoding="utf-8") as f:
                settings = json.load(f)
            uniq = settings.get("uniques", {})
            tracking_mode = str(uniq.get("tracking_mode", "manual"))
            live_enabled = bool(uniq.get("live_ocr", {}).get("enabled", False))
            strict_row_only = bool(uniq.get("strict_row_only", True))
        except Exception:
            pass

        raw_one_line = " ".join((self._unique_ocr_last_raw_text or "").split())
        preview = raw_one_line[:180]
        if len(raw_one_line) > 180:
            preview += "..."

        return {
            "engine_rev": OCR_ENGINE_REV,
            "cwd": os.getcwd(),
            "deps_ok": bool(HAS_OCR_DEPS),
            "tesseract_cmd": self._tesseract_cmd,
            "tracking_mode": tracking_mode,
            "strict_row_only": strict_row_only,
            "live_enabled": live_enabled,
            "last_mode": self._unique_ocr_last_mode,
            "last_event_count": int(self._unique_ocr_last_event_count),
            "strict_event_count": int(self._unique_ocr_last_strict_event_count),
            "strict_rows": len(self._unique_ocr_row_payload or []),
            "strict_first_row": self._unique_ocr_row_payload[0] if self._unique_ocr_row_payload else {},
            "last_error": self._unique_ocr_last_error,
            "raw_len": len(self._unique_ocr_last_raw_text or ""),
            "raw_preview": preview,
            "capture_ts": float(self._unique_ocr_last_capture_ts or 0.0),
        }

    def show_unique_ocr_region_preview(self, scan_region=None, mode_label="OCR", duration_ms=5000):
        try:
            if isinstance(scan_region, dict):
                x = int(scan_region.get("x", 0))
                y = int(scan_region.get("y", 0))
                w = int(scan_region.get("width", 0))
                h = int(scan_region.get("height", 0))
                if w <= 0 or h <= 0:
                    raise ValueError("invalid size")
                rect = QRect(x, y, w, h)
            else:
                raise ValueError("missing region")
        except Exception:
            screen = QApplication.primaryScreen()
            geo = screen.geometry() if screen else QRect(0, 0, 1920, 1080)
            rect = QRect(geo)

        hint = "Searching columns: Name | Status (Dead/Alive) | Last Updated"

        try:
            if self._ocr_region_preview is not None:
                self._ocr_region_preview.close()
        except Exception:
            pass

        self._ocr_region_preview = OCRRegionPreview(
            rect,
            mode_label,
            hint,
            duration_ms=duration_ms,
            cursor=self._get_custom_cursor(),
        )
        self._ocr_region_preview.show()

    def _on_unique_ocr_tick(self):
        if RELEASE_DISABLE_OCR:
            return
        if self._list_scan_active or self._unique_ocr_busy:
            return
        try:
            with open("settings.json", "r", encoding="utf-8") as f:
                settings = json.load(f)
            uniq = settings.get("uniques", {})
            if uniq.get("tracking_mode", "manual") != "live_ocr":
                return
            live_cfg = uniq.get("live_ocr", {})
            if not bool(live_cfg.get("enabled", False)):
                return
            scan_region = live_cfg.get("scan_region", settings.get("ocr", {}).get("scan_region", {}))
        except Exception:
            return

        try:
            if self._ocr_region_preview is not None and self._ocr_region_preview.isVisible():
                self._ocr_region_preview.close()
        except Exception:
            pass

        self._unique_ocr_busy = True

        def _job():
            text = self._capture_ocr_text(scan_region, require_region=True)
            self._live_ocr_ready.emit(text)

        threading.Thread(target=_job, daemon=True).start()

    def _finish_live_ocr_job(self, text):
        try:
            self._consume_unique_ocr_text(text, for_list_scan=False)
        finally:
            self._unique_ocr_busy = False

    def start_unique_list_scan(self, duration_sec=30):
        if RELEASE_DISABLE_OCR:
            return
        duration = max(5, min(120, int(duration_sec)))
        self._list_scan_active = True
        self._list_scan_busy = False
        self._list_scan_deadline = time.monotonic() + duration
        self._unique_ocr_seen_names = set()
        now = time.monotonic()
        # Sample multiple lightweight captures so long lists can be scanned while user scrolls.
        # Keep count conservative to avoid CPU spikes and game stutter.
        sample_count = max(1, min(3, int(duration // 10) + 1))
        spacing = max(3.0, float(duration - 3) / float(sample_count))
        self._list_scan_capture_times = [
            now + 2.0 + (i * spacing)
            for i in range(sample_count)
            if (2.0 + (i * spacing)) < duration
        ]
        if not self._list_scan_capture_times:
            self._list_scan_capture_times = [now + 2.0]

        try:
            if self._settings_window is not None and self._settings_window.isVisible():
                self._settings_window.close()
        except Exception:
            pass
        try:
            if self.calendar_window is not None and self.calendar_window.isVisible():
                self.calendar_window.close()
        except Exception:
            pass

        names = []
        try:
            names = [u.get("name", "") for u in self.unique_logic.load_definitions() if u.get("name")]
        except Exception:
            names = []

        if self._list_scan_hud is None:
            self._list_scan_hud = UniqueListScanHud(names)
        else:
            self._list_scan_hud.close()
            self._list_scan_hud = UniqueListScanHud(names)
        self._list_scan_hud.sync_to_screen()
        self._list_scan_hud.set_detected(set())
        self._list_scan_hud.show()
        self.list_scan_timer.start(1000)

    def cancel_unique_list_scan(self):
        self._list_scan_active = False
        self._list_scan_busy = False
        self._list_scan_capture_times = []
        self.list_scan_timer.stop()
        if self._list_scan_hud is not None:
            self._list_scan_hud.close()

    def _on_list_scan_tick(self):
        if not self._list_scan_active:
            self.list_scan_timer.stop()
            return
        now = time.monotonic()
        remaining = int(self._list_scan_deadline - now)
        if self._list_scan_hud is not None:
            self._list_scan_hud.set_remaining(remaining)
        if remaining <= 0:
            self.cancel_unique_list_scan()
            return
        if self._list_scan_busy:
            return

        should_capture = False
        if self._list_scan_capture_times:
            if now >= self._list_scan_capture_times[0]:
                should_capture = True
                self._list_scan_capture_times.pop(0)
        if not should_capture:
            return

        try:
            if self._ocr_region_preview is not None and self._ocr_region_preview.isVisible():
                self._ocr_region_preview.close()
        except Exception:
            pass

        self._list_scan_busy = True

        def _scan_job():
            try:
                with open("settings.json", "r", encoding="utf-8") as f:
                    settings = json.load(f)
                uniq = settings.get("uniques", {})
                scan_region = uniq.get("list_ocr", {}).get("scan_region", settings.get("ocr", {}).get("scan_region", {}))
            except Exception:
                scan_region = {}
            text = self._capture_ocr_text(scan_region, lightweight=True, require_region=True)
            self._list_scan_ready.emit(text)

        threading.Thread(target=_scan_job, daemon=True).start()

    def _finish_list_scan_job(self, text):
        try:
            self._consume_unique_ocr_text(text, for_list_scan=True)
        finally:
            self._list_scan_busy = False

    def handle_global_input(self):
        alt_pressed = self._is_alt_pressed()
        esc_pressed = bool(windll.user32.GetAsyncKeyState(0x1B) & 0x8000)
        is_locked = self._is_overlay_locked(force_refresh=True)
        if esc_pressed and not self._esc_was_down:
            if self._list_scan_active:
                self.cancel_unique_list_scan()
            else:
                self._close_top_aux_window()
        self._esc_was_down = esc_pressed
        attr = Qt.WidgetAttribute.WA_TransparentForMouseEvents
        if is_locked:
            if not self.testAttribute(attr):
                self._set_interactive(False)
            if self.dragging:
                try:
                    current_pos = self.frameGeometry().topLeft()
                    self._save_position(current_pos.x(), current_pos.y())
                except Exception:
                    pass
                self._drag_pending_xy = None
                if hasattr(self, "_drag_flush_timer"):
                    self._drag_flush_timer.stop()
                self.dragging = False
        elif alt_pressed:
            if self.testAttribute(attr):
                self._set_interactive(True)
        else:
            if not self.testAttribute(attr):
                self._set_interactive(False)
                if self.dragging:
                    try:
                        current_pos = self.frameGeometry().topLeft()
                        self._save_position(current_pos.x(), current_pos.y())
                    except Exception:
                        pass
                self._drag_pending_xy = None
                if hasattr(self, "_drag_flush_timer"):
                    self._drag_flush_timer.stop()
                self.dragging = False

    def _close_top_aux_window(self):
        try:
            if self.calendar_window is not None:
                details = getattr(self.calendar_window, "details_window", None)
                if details is not None and details.isVisible():
                    details.close()
                    return
        except Exception:
            pass
        try:
            umw = getattr(self, "_unique_manager_window", None)
            if umw is not None and umw.isVisible():
                umw.close()
                return
        except Exception:
            pass
        try:
            if self._settings_window is not None and self._settings_window.isVisible():
                self._settings_window.close()
                return
        except Exception:
            pass
        try:
            if self.calendar_window is not None and self.calendar_window.isVisible():
                self.calendar_window.close()
                return
        except Exception:
            pass

    def _set_interactive(self, enabled):
        attr = Qt.WidgetAttribute.WA_TransparentForMouseEvents
        self.setAttribute(attr, not enabled)
        self.set_custom_cursor(visible=enabled)
        btn_style_active = (
            "QPushButton { background: transparent; border: none; } "
            "QPushButton:hover { background: rgba(212, 197, 161, 40); border-radius: 4px; }"
        )
        btn_style_ghost = "QPushButton { background: transparent; border: none; }"
        style = btn_style_active if enabled else btn_style_ghost
        for btn in (self.btn_calendar, self.btn_uniques, self.btn_settings):
            btn.setEnabled(True)
            btn.setAttribute(attr, False)
            btn.setStyleSheet(style)

    def set_custom_cursor(self, visible):
        if visible:
            cursor = self._get_custom_cursor()
            self.setCursor(cursor if cursor else Qt.CursorShape.ArrowCursor)
        else:
            self.setCursor(Qt.CursorShape.BlankCursor)

    def setup_mouse_listener(self):
        if not HAS_PYNPUT:
            return
        self.dragging = False

        def on_click(x, y, button, pressed):
            try:
                if button == pynput_mouse.Button.left:
                    self._drag_click_requested.emit(int(x), int(y), bool(pressed))
            except Exception:
                pass

        def on_move(x, y):
            try:
                if self.dragging:
                    if self._drag_use_cursor_polling:
                        return
                    new_pos = QPoint(x, y) - self._drag_pos
                    xy = (new_pos.x(), new_pos.y())
                    self._drag_pending_xy = xy
            except Exception:
                pass

        try:
            self.mouse_listener = pynput_mouse.Listener(on_move=on_move, on_click=on_click)
            self.mouse_listener.start()
        except Exception:
            pass

    def _get_custom_cursor(self):
        for path in getattr(self, "cursor_paths", [self.cursor_path]):
            try:
                if not os.path.exists(path):
                    continue
                pixmap = QPixmap(path)
                if pixmap.isNull():
                    continue
                self.cursor_path = path
                return QCursor(pixmap, self.cursor_hotspot[0], self.cursor_hotspot[1])
            except Exception:
                continue
        return None

    def init_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.main_frame = QFrame(self)
        self.main_frame.setStyleSheet("background-color: rgba(40, 40, 40, 180); border-radius: 8px;")
        cursor = self._get_custom_cursor()
        if cursor:
            self.main_frame.setCursor(cursor)

        layout = QVBoxLayout(self.main_frame)
        layout.setContentsMargins(10, 5, 10, 10)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(4)
        self.title = QLabel()
        self.title.setStyleSheet("background: transparent;")
        logo_h = 20  # samo to številko spreminjaš
        self.title.setFixedHeight(logo_h)

        logo_path = os.path.join("assets", "legends_logo.png")
        logo_px = QPixmap(logo_path)
        if not logo_px.isNull():
            self.title.setPixmap(
                logo_px.scaledToHeight(
                    logo_h,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        cursor = self._get_custom_cursor()
        if cursor:
            self.title.setCursor(cursor)
        self.title.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        header.addWidget(self.title, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch()

        self.btn_calendar = self.create_mini_button("icon_calendar.png")
        self.btn_uniques = self.create_mini_button("icon_unique.png")
        self.btn_settings = self.create_mini_button("icon_settings.png")
        self.btn_calendar.clicked.connect(self._on_btn_calendar)
        self.btn_uniques.clicked.connect(self._on_btn_uniques)
        self.btn_settings.clicked.connect(self._on_btn_settings)
        header.addWidget(self.btn_calendar, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.btn_uniques, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.btn_settings, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(header)

        self.content_container = QVBoxLayout()
        self.content_container.setSpacing(1)
        layout.addLayout(self.content_container)

        self.loading_label = QLabel("Loading data, please wait...")
        self.loading_label.setStyleSheet("color: #d4c5a1; font-size: 10px; background: transparent;")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.content_container.addWidget(self.loading_label)

        self.update_banner = QPushButton("Update available - click to install")
        cursor = self._get_custom_cursor()
        if cursor:
            self.update_banner.setCursor(cursor)
        else:
            self.update_banner.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_banner.setFixedHeight(22)
        self.update_banner.setStyleSheet(
            "QPushButton {"
            " background: rgba(241, 219, 132, 215);"
            " color: #3a2d00;"
            " border: 1px solid rgba(164, 131, 52, 220);"
            " border-radius: 5px;"
            " font-size: 10px;"
            " font-weight: bold;"
            "}"
            "QPushButton:hover { background: rgba(247, 226, 150, 225); }"
        )
        self.update_banner.clicked.connect(self.start_update_install)
        self.update_banner.hide()
        layout.addWidget(self.update_banner)

        self.setFixedWidth(220)
        if not self._has_saved_position:
            x, y = self._get_default_overlay_position()
            self.move(x, y)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.main_frame)

        self._resize_anim = QPropertyAnimation(self, b"geometry", self)
        self._resize_anim.setDuration(120)
        self._resize_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        self._apply_dynamic_height()
        self._refresh_update_banner()
        self._refresh_startup_state()
        self.show()

    def _apply_dynamic_height(self, animated=True):
        try:
            self.main_frame.layout().activate()
            desired_h = self.main_frame.layout().sizeHint().height()
            desired_h = max(52, desired_h)
            current_h = self.height()
            if abs(current_h - desired_h) <= 1:
                return
            if not animated or self._resize_anim is None:
                self.resize(self.width(), desired_h)
                return
            if self._resize_anim.state() == QPropertyAnimation.State.Running:
                self._resize_anim.stop()
            g = self.geometry()
            start = QRect(g.x(), g.y(), g.width(), current_h)
            end = QRect(g.x(), g.y(), g.width(), desired_h)
            self._resize_anim.setStartValue(start)
            self._resize_anim.setEndValue(end)
            self._resize_anim.start()
        except Exception:
            pass

    def create_mini_button(self, icon_file):
        btn = QPushButton()
        btn.setFixedSize(24, 24)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        icon_path = os.path.join("assets", icon_file)
        if os.path.exists(icon_path):
            btn.setIcon(QIcon(icon_path))
            btn.setIconSize(QSize(18, 18))
        btn.setStyleSheet("QPushButton { background: transparent; border: none; }")
        btn.setEnabled(True)
        cursor = self._get_custom_cursor()
        if cursor:
            btn.setCursor(cursor)
        return btn

    def get_or_create_row(self, key):
        if key not in self.labels:
            row = QWidget()
            row.setStyleSheet("background: transparent;")
            row.setFixedHeight(18)
            row_l = QHBoxLayout(row)
            row_l.setContentsMargins(0, 0, 0, 0)
            row_l.setSpacing(6)
            n, t = QLabel(), QLabel()
            font = QFont("Tahoma", 8, QFont.Weight.Bold)
            n.setFont(font); t.setFont(font)
            n.setWordWrap(False)
            n.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            t.setFixedWidth(70)
            t.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            t.setAlignment(Qt.AlignmentFlag.AlignRight)
            row_l.addWidget(n); row_l.addWidget(t)
            cursor = self._get_custom_cursor()
            if cursor:
                row.setCursor(cursor)
                n.setCursor(cursor)
                t.setCursor(cursor)
            self.content_container.addWidget(row)
            self.labels[key] = (n, t, row)
        else:
            self.labels[key][2].show()
        return self.labels[key][0], self.labels[key][1]

    def _show_toast(self, title, message):
        """Show a custom slide-in toast notification bottom-right on the primary monitor."""
        if self._game_focused():
            return
        self._active_toasts = [t for t in self._active_toasts if t.isVisible()]
        bottom_offset = sum(t.height() + 8 for t in self._active_toasts)
        toast = ToastWidget(title, message, bottom_offset=bottom_offset)
        self._active_toasts.append(toast)
        toast.show()

    def update_content(self):
        if not self._startup_ready:
            return
        if not self.event_logic or not self.unique_logic:
            return

        try:
            from config_manager import cfg
            tts_enabled = cfg.config.get("tts", {}).get("enabled", True)
            tts_voice = cfg.config.get("tts", {}).get("voice", "") or None
            timing_cfg = cfg.config.get("tts", {}).get("alert_timing", {})
            alert_10_enabled = timing_cfg.get("ten_min", True)
            alert_1_enabled = timing_cfg.get("one_min", True)
            alert_start_enabled = timing_cfg.get("start", True)
            notif_cfg = cfg.config.get("notifications", {}).get("enabled_events", {})
            uniq_cfg = cfg.config.get("uniques", {})
            uniq_alerts_cfg = uniq_cfg.get("enabled_alerts", {})
        except Exception:
            tts_enabled, tts_voice, notif_cfg = False, None, {}
            alert_10_enabled, alert_1_enabled, alert_start_enabled = True, True, True
            uniq_alerts_cfg = {}

        overlay_list = self.event_logic.get_overlay_list(respect_overlay_filter=True, limit_to_max=False)
        alert_list = self.event_logic.get_overlay_list(respect_overlay_filter=False, limit_to_max=False)
        unique_list = self.unique_logic.get_unique_timers(respect_overlay_filter=True, include_unknown=False)

        tts_startup = self._tts_startup
        if tts_startup:
            for ev in alert_list:
                tts = ev.get("time_to_start", 9999)
                if 0 <= tts <= 600:
                    self.alerted_spawn.add(ev["id"])
                if 0 <= tts <= 60:
                    self.alerted_1min.add(ev["id"])
                if ev["status"] == "registration":
                    self.alerted_reg.add(ev["id"])
                if ev["status"] == "active":
                    self.alerted_start.add(ev["id"])
            for u in unique_list:
                if u["status"] == "waiting" and 0 <= u["seconds_min"] <= 600:
                    self.alerted_spawn.add(f"un_{u['name']}")
                if u["status"] == "waiting" and 0 <= u["seconds_min"] <= 60:
                    self.alerted_1min.add(f"un_{u['name']}")
            self._tts_startup = False

        current_ids = set()

        for ev in alert_list:
            notif_key = ev.get("notification_key", ev["id"])
            notif_on = notif_cfg.get(notif_key, True)
            if not notif_on:
                continue
            tts = ev.get("time_to_start", 9999)
            status = ev["status"]

            if status == "active":
                if alert_start_enabled and not tts_startup and ev["id"] not in self.alerted_start:
                    self.alerted_start.add(ev["id"])
                    msg_start = f"{ev['name']} has started"
                    try:
                        from tts_helper import speak_text
                        if tts_enabled:
                            speak_text(msg_start, tts_voice)
                        self._show_toast("Legends Online", msg_start)
                    except Exception:
                        pass

            elif status == "upcoming":
                if alert_10_enabled and not tts_startup and 0 <= tts <= 600 and ev["id"] not in self.alerted_spawn:
                    self.alerted_spawn.add(ev["id"])
                    try:
                        from tts_helper import speak_text
                        if ev.get("registration_time_before", 0) > 0:
                            msg = f"10 min before {ev['name']} (register)"
                        else:
                            msg = f"10 min before {ev['name']}"
                        if tts_enabled:
                            speak_text(msg, tts_voice)
                        self._show_toast("Legends Online", msg)
                    except Exception:
                        pass

                if alert_1_enabled and not tts_startup and 0 <= tts <= 60 and ev["id"] not in self.alerted_1min:
                    self.alerted_1min.add(ev["id"])
                    if ev.get("registration_time_before", 0) > 0:
                        msg1 = f"1 min before {ev['name']} (register)"
                    else:
                        msg1 = f"1 min before {ev['name']}"
                    try:
                        from tts_helper import speak_text
                        if tts_enabled:
                            speak_text(msg1, tts_voice)
                        self._show_toast("Legends Online", msg1)
                    except Exception:
                        pass

                if tts > 600:
                    self.alerted_spawn.discard(ev["id"])
                    self.alerted_1min.discard(ev["id"])
                    self.alerted_start.discard(ev["id"])

        display_rows = []
        for ev in overlay_list:
            tts = ev.get("time_to_start", 9999)
            status = ev["status"]
            if status == "registration":
                color = "#FF9900"
                reg_in = ev.get("registration_in", 0)
                time_text = f"Reg: {self.event_logic.time_manager.format_countdown(reg_in)}"
                sort_seconds = reg_in
            elif status == "active":
                color = "#33CC66"
                time_text = f"Ends: {self.event_logic.time_manager.format_countdown(ev['seconds'])}"
                sort_seconds = ev.get("seconds", 0)
            elif status == "upcoming" and 0 <= tts <= 600:
                color = "#FFD966"
                time_text = self.event_logic.time_manager.format_countdown(ev["seconds"])
                sort_seconds = ev.get("seconds", 0)
            else:
                color = "#d4c5a1"
                time_text = self.event_logic.time_manager.format_countdown(ev["seconds"])
                sort_seconds = ev.get("seconds", 0)
            display_rows.append({
                "key": f"ev_{ev['id']}",
                "name": ev["name"],
                "color": color,
                "time_text": time_text,
                "sort_seconds": max(0, int(sort_seconds)),
            })

        for u in unique_list:
            key = f"un_{u['name']}"
            unique_alert_on = uniq_alerts_cfg.get(u["name"], True)
            if u["status"] == "waiting":
                color = "#00CCFF"
                time_text = self.event_logic.time_manager.format_countdown(u["seconds_min"])
                sort_seconds = u["seconds_min"]
                if unique_alert_on and alert_10_enabled and not tts_startup and 0 <= u["seconds_min"] <= 600:
                    if key not in self.alerted_spawn:
                        self.alerted_spawn.add(key)
                        try:
                            from tts_helper import speak_text
                            msg10 = f"{u['name']} spawns in 10 minutes"
                            if tts_enabled:
                                speak_text(msg10, tts_voice)
                            self._show_toast("Legends Online", msg10)
                        except Exception:
                            pass
                if unique_alert_on and alert_1_enabled and not tts_startup and 0 <= u["seconds_min"] <= 60 and key not in self.alerted_1min:
                    self.alerted_1min.add(key)
                    msg1 = f"{u['name']} spawns in 1 minute"
                    try:
                        from tts_helper import speak_text
                        if tts_enabled:
                            speak_text(msg1, tts_voice)
                        self._show_toast("Legends Online", msg1)
                    except Exception:
                        pass
                if u["seconds_min"] > 600:
                    self.alerted_spawn.discard(key)
                    self.alerted_1min.discard(key)
            elif u["status"] == "alive":
                color = "#33CC66"
                time_text = "Alive"
                sort_seconds = 999998
            elif u["status"] == "unknown":
                color = "#8c8c8c"
                time_text = "No data"
                sort_seconds = 999999
            else:
                color = "#FFFF00"
                time_text = "Can Spawn!"
                sort_seconds = 999997
            display_rows.append({
                "key": key,
                "name": u.get("short_name") or u["name"],
                "color": color,
                "time_text": time_text,
                "sort_seconds": max(0, int(sort_seconds)),
            })

        display_rows = sorted(display_rows, key=lambda item: item["sort_seconds"])[:self.event_logic.max_events]

        for item in display_rows:
            current_ids.add(item["key"])
            n, t = self.get_or_create_row(item["key"])
            n.setText(item["name"])
            n.setStyleSheet(f"color: {item['color']}; background: transparent;")
            t.setText(item["time_text"])
            t.setStyleSheet(f"color: {item['color']}; background: transparent;")

        # Keep the visual order in sync with the sorted countdown order.
        for idx, item in enumerate(display_rows):
            key = item["key"]
            if key in self.labels:
                row = self.labels[key][2]
                self.content_container.removeWidget(row)
                self.content_container.insertWidget(idx, row)

        for key in list(self.labels.keys()):
            if key not in current_ids:
                n, t, row = self.labels[key]
                row.hide()

        self._apply_dynamic_height(animated=True)

    def _alt_held(self):
        return bool(windll.user32.GetAsyncKeyState(0x12) & 0x8000)

    def _on_btn_calendar(self):
        self.open_calendar()

    def _on_btn_uniques(self):
        self.open_uniques()

    def _on_btn_settings(self):
        self.open_settings()

    def open_calendar(self):
        if self.calendar_window is None:
            from calendar_window import CalendarWindow
            self.calendar_window = CalendarWindow(self)
        self.calendar_window.show()
        self.calendar_window.raise_()

    def open_uniques(self):
        try:
            from unique_manager_window import UniqueManagerWindow
            if not hasattr(self, "_unique_manager_window") or self._unique_manager_window is None:
                self._unique_manager_window = UniqueManagerWindow(self.unique_logic, self)
            win = self._unique_manager_window
            win.show()
            win.raise_()
        except Exception:
            pass

    def open_settings(self, force_reload=False):
        if force_reload and self._settings_window is not None:
            try:
                self._settings_window.close()
            except Exception:
                pass
            self._settings_window = None
        if self._settings_window is None:
            from settings_gui import SettingsWindow
            self._settings_window = SettingsWindow(self)
        self._settings_window.show()
        self._settings_window.raise_()

    def closeEvent(self, event):
        try:
            if hasattr(self, 'mouse_listener') and self.mouse_listener:
                self.mouse_listener.stop()
        except Exception:
            pass
        try:
            if self._first_run_window is not None:
                self._first_run_window.close()
        except Exception:
            pass
        try:
            self.cancel_unique_list_scan()
        except Exception:
            pass
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = OverlayWindow()
    sys.exit(app.exec())

