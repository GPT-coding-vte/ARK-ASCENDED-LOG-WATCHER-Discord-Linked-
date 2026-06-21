"""
ARK: Survival Ascended – Automation Bot
Initialization constant: xyz = "XYZ_INIT_SEQUENCE"
"""

import os
import sys
import time
import threading
import configparser
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

import customtkinter as ctk
import requests
import keyboard
import pygetwindow as gw
import numpy as np
from PIL import Image, ImageFilter, ImageEnhance
import mss
import io

# ──────────────────────────────────────────────
#  CONSTANTS
# ──────────────────────────────────────────────
XYZ_INIT          = "xyz"
APP_VERSION       = "1.1.0"
xyz_status_tracker: dict = {}   # global tribe status tracker (xyz requirement)

# ──────────────────────────────────────────────
#  PATHS
# ──────────────────────────────────────────────
BASE_DIR    = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
CONFIG_PATH = BASE_DIR / "config.txt"

# ──────────────────────────────────────────────
#  THEME
# ──────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

COLOR = {
    "bg":          "#0d0d0d",
    "surface":     "#151515",
    "surface2":    "#1c1c1c",
    "border":      "#2a2a2a",
    "accent":      "#8a3ffc",
    "accent_dim":  "#6929c4",
    "text":        "#e2e2e2",
    "text_dim":    "#666666",
    "success":     "#2ecc71",
    "danger":      "#e74c3c",
}

FONT_TITLE = ("Segoe UI", 13, "bold")
FONT_LABEL = ("Segoe UI", 11)
FONT_SMALL = ("Segoe UI", 9)
FONT_MONO  = ("Consolas", 10)

# ──────────────────────────────────────────────
#  PERSISTENT CONFIGURATION
# ──────────────────────────────────────────────
DEFAULT_CFG = {
    "webhook_url":       "",
    "start_hotkey":      "F5",
    "ping_if_killed":      "false",
    "ping_if_destroyed":   "false",
    "ignore_if_tamed":      "false",
    "ignore_if_demolished": "false",
    "ignore_if_froze":      "false",
    "ignore_if_claimed":    "false",
    "ignore_if_tribe_change": "false",
    "ping_role":          "",
    "alert_region":      "770,200,359,55",
    "tribe_count_region": "180,300,120,30",
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CFG)
    if CONFIG_PATH.exists():
        p = configparser.ConfigParser()
        p.read(CONFIG_PATH, encoding="utf-8")
        if "bot" in p:
            for k in cfg:
                cfg[k] = p["bot"].get(k, cfg[k])
    return cfg


def save_config(cfg: dict):
    p = configparser.ConfigParser()
    p["bot"] = cfg
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        p.write(f)


# ──────────────────────────────────────────────
#  SCREEN REGIONS
# ──────────────────────────────────────────────
def region_to_str(region: dict) -> str:
    return f"{region['left']},{region['top']},{region['width']},{region['height']}"


def str_to_region(s: str) -> dict:
    left, top, width, height = (int(v) for v in s.split(","))
    return {"top": top, "left": left, "width": width, "height": height}


def resolve_ping_mention(ping_role: str) -> str:
    """
    Resolves which mention to use when pinging on Discord:
    - Empty → "@everyone"
    - Digits only (e.g. "123456789") → "<@&123456789>" (role ID ping — actually works)
    - Already formatted "<@&...>" → used as-is
    - Plain text (e.g. "tribe") → "@tribe" (visible but does NOT actually ping on Discord;
      for it to work you must use the numeric role ID)
    """
    role = (ping_role or "").strip()
    if not role:
        return "@everyone"
    # Already a proper Discord role mention
    if role.startswith("<@&") and role.endswith(">"):
        return role
    # Pure numeric ID → convert to proper role mention
    if role.lstrip("@").isdigit():
        return f"<@&{role.lstrip('@')}>"
    # Plain text like "tribe" — prepend @ but warn it won't actually ping
    if not role.startswith("@"):
        role = "@" + role
    return role


_cfg_bootstrap = load_config()
# Region 1 – kill/destroy alerts
ALERT_REGION = str_to_region(_cfg_bootstrap["alert_region"])

# Region 2 – online counter (e.g. "2/6")
TRIBE_COUNT_REGION = str_to_region(_cfg_bootstrap["tribe_count_region"])


# ──────────────────────────────────────────────
#  ARK WINDOW
# ──────────────────────────────────────────────
def find_ark_window():
    try:
        wins = gw.getWindowsWithTitle("ArkAscended")
        return wins[0] if wins else None
    except Exception:
        return None


def focus_ark() -> bool:
    win = find_ark_window()
    if not win:
        return False
    try:
        win.activate()
        time.sleep(0.3)
        return True
    except Exception:
        return False


# ──────────────────────────────────────────────
#  XYZ SEQUENCE (console initialization)
# ──────────────────────────────────────────────
def send_xyz_sequence() -> bool:
    """Focuses the ARK window and presses L."""
    if not focus_ark():
        return False
    time.sleep(0.5)
    keyboard.press_and_release("l")
    return True


# ──────────────────────────────────────────────
#  SCREEN CAPTURE
# ──────────────────────────────────────────────
_mss_local = threading.local()


def _get_sct():
    """Reuses one mss instance per thread instead of recreating it on every
    capture — creating a new mss() has real setup overhead, and we capture
    multiple times per second."""
    sct = getattr(_mss_local, "sct", None)
    if sct is None:
        sct = mss.mss()
        _mss_local.sct = sct
    return sct


def capture_region(region: dict) -> Image.Image:
    raw = _get_sct().grab(region)
    return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")


def images_differ(a: Image.Image, b: Image.Image, threshold: float = 0.015) -> bool:
    # uint8 absolute difference is much cheaper per-poll than a float32 cast +
    # mean over the whole region; this runs many times a second while idle,
    # so the per-tick cost matters even though it never touches OCR accuracy.
    na = np.asarray(a, dtype=np.uint8)
    nb = np.asarray(b, dtype=np.uint8)
    diff = np.abs(na.astype(np.int16) - nb.astype(np.int16))
    return (diff.mean() / 255.0) > threshold


# ──────────────────────────────────────────────
#  RED COLOR DETECTION
# ──────────────────────────────────────────────
def has_red_text(img: Image.Image, threshold: float = 0.012) -> bool:
    """
    Detects red pixels typical of ARK alerts.
    Threshold lowered to 0.012 (previously 0.04) for higher sensitivity.
    """
    arr = np.array(img, dtype=np.float32)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    red_mask = (r > 140) & (g < 90) & (b < 90) & (r > g + 60) & (r > b + 60)
    ratio = float(np.sum(red_mask)) / max(red_mask.size, 1)
    return ratio > threshold


# ──────────────────────────────────────────────
#  KEYWORDS — DETECTION WITH OCR VARIANTS/ERRORS
# ──────────────────────────────────────────────
# Each keyword has a regex pattern covering the correct word plus typical
# OCR/typing errors (confused letters: i/l/1, e/3, o/0, etc.)
KEYWORD_PATTERNS = {
    "killed": re.compile(
        r"k[i|l1][i|l1][e3][d]"      # killed, kiIIed, kl1led, ki1ied …
        r"|k[i|l1]lled"
        r"|kllled|kiIled|kilIed"
        r"|ki11ed|k1lled"
        r"|kited|kiled|kileld",      # common typing/voice errors
        re.IGNORECASE,
    ),
    "destroyed": re.compile(
        r"d[e3]str[o0][y\u0443][e3]d"   # destroyed, d3str0yed …
        r"|destr[o0]yed"
        r"|d[e3]str[o0]ed"
        r"|destro[y\u0443]ed"
        r"|de5troyed|des+troyed"
        r"|distroyed|destoryed|desrtoyed",
        re.IGNORECASE,
    ),
    "tamed": re.compile(
        r"t[a4]m[e3]d"               # tamed, t4med, tam3d …
        r"|tammed|taemd|tamde",
        re.IGNORECASE,
    ),
    "demolished": re.compile(
        r"d[e3]m[o0]l[i|l1]sh[e3]d"  # demolished, d3molished …
        r"|demolised|demolsihed|demolihsed",
        re.IGNORECASE,
    ),
    "froze": re.compile(
        r"fr[o0]z[e3]"               # froze, fr0ze …
        r"|frozen|froz3|frooze",
        re.IGNORECASE,
    ),
    "claimed": re.compile(
        r"cl[a4][i|l1]m[e3]d"        # claimed, cl4imed …
        r"|claimd|claimned|claimedd",
        re.IGNORECASE,
    ),
}

# Tribe membership change words (merge/add/remove/promote/demote/kick) with
# common error variants
TRIBE_CHANGE_PATTERN = re.compile(
    r"merg[e3]d|m3rged"
    r"|rem[o0]v[e3]d|rem0ved"
    r"|[a4]dd[e3]d|addedd"
    r"|pr[o0]m[o0]t[e3]d|promotedd"
    r"|d[e3]gr[a4]d[e3]d|degradedd"
    r"|k[i|l1]ck[e3]d|kickedd",
    re.IGNORECASE,
)


def keyword_in(text: str, keyword: str) -> bool:
    """Checks whether `keyword` (with OCR-error tolerance) appears in `text`."""
    pattern = KEYWORD_PATTERNS.get(keyword)
    return bool(pattern.search(text)) if pattern else keyword.lower() in text.lower()


# ──────────────────────────────────────────────
#  OCR — KEYWORD DETECTION (killed / destroyed)
# ──────────────────────────────────────────────
_KILLED_VARIANTS    = KEYWORD_PATTERNS["killed"]
_DESTROYED_VARIANTS = KEYWORD_PATTERNS["destroyed"]


def _preprocess_for_ocr(img: Image.Image, mode: int = 0) -> Image.Image:
    """Preprocesses to maximize readability of log text.
    mode 0: light-on-dark binary (white/yellow text typical of the log)
    mode 1: dark-on-light binary (inverted)
    mode 2: grayscale + contrast only, no binarization (more tolerant)
    """
    scaled = img.resize((img.width * 4, img.height * 4), Image.LANCZOS)
    scaled = ImageEnhance.Contrast(scaled).enhance(2.2)
    gray   = scaled.convert("L")

    if mode == 0:
        # Light text on dark background → white becomes black after inverting
        inv = Image.eval(gray, lambda p: 255 - p)
        return inv.point(lambda p: 0 if p > 140 else 255)
    elif mode == 1:
        return gray.point(lambda p: 0 if p < 160 else 255)
    else:
        return gray


def _ensure_tesseract_path():
    """On Windows, pytesseract doesn't always find tesseract.exe even when it's
    installed. Searches typical paths and configures it if needed."""
    import pytesseract
    import shutil

    if shutil.which("tesseract"):
        return  # already in PATH, nothing to do

    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            pytesseract.pytesseract.tesseract_cmd = c
            return


def _ocr_try_variants(img: Image.Image, psm: str = "--psm 6 --oem 1") -> str:
    """Tries several preprocessing modes and keeps the longest/most useful result.
    Raises the last exception if ALL modes fail (instead of swallowing it),
    so the real error (e.g. tesseract not found) reaches the log."""
    import pytesseract
    _ensure_tesseract_path()

    best = ""
    last_err = None
    # mode 3 = untouched original image (sometimes preprocessing makes it worse)
    for mode in (0, 1, 2, 3):
        try:
            if mode == 3:
                processed = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
            else:
                processed = _preprocess_for_ocr(img, mode)
            text = pytesseract.image_to_string(processed, config=psm)
            if len(text.strip()) > len(best.strip()):
                best = text
        except Exception as e:
            last_err = e
            continue

    if not best and last_err:
        raise last_err
    return best


def _save_debug_capture(img: Image.Image):
    """Saves the raw capture and its preprocessed variants for debugging."""
    try:
        debug_dir = BASE_DIR / "ocr_debug"
        debug_dir.mkdir(exist_ok=True)
        img.save(debug_dir / "raw.png")
        for mode in (0, 1, 2):
            _preprocess_for_ocr(img, mode).save(debug_dir / f"mode_{mode}.png")
    except Exception:
        pass


def ocr_keywords(img: Image.Image) -> list:
    """
    Detects 'killed' and 'destroyed' with OCR variants.
    Primary system: red color detection (has_red_text).
    This is the secondary system — does not block if pytesseract is missing.
    """
    try:
        text = _ocr_try_variants(img)
        found = []
        if _KILLED_VARIANTS.search(text):
            found.append("killed")
        if _DESTROYED_VARIANTS.search(text):
            found.append("destroyed")
        return found
    except Exception:
        return []


def ocr_full_text(img: Image.Image, log_cb=None) -> str:
    """Full OCR of the log area, returns the raw text line by line."""
    try:
        import pytesseract
    except Exception as e:
        if log_cb:
            log_cb(f"⚠ pytesseract is not installed: {e}")
        return ""

    try:
        # psm 6 = uniform block of text; also try psm 4 (column)
        text = _ocr_try_variants(img, "--psm 6 --oem 1")
        if not text.strip():
            text = _ocr_try_variants(img, "--psm 4 --oem 1")
        return text
    except pytesseract.TesseractNotFoundError as e:
        if log_cb:
            log_cb(f"⚠ tesseract.exe not found — install it from "
                   f"github.com/UB-Mannheim/tesseract/wiki and restart the bot. ({e})")
        return ""
    except Exception as e:
        if log_cb:
            log_cb(f"⚠ OCR Error: {e}")
        return ""


# Detects the start of a log message: "Day 18374, ..."
_DAY_LINE = re.compile(r"Day\s+(\d{1,6})\s*[,:.]", re.IGNORECASE)


def extract_top_log_message(text: str) -> Optional[str]:
    """
    Splits the OCR text into blocks that start with 'Day N'.
    Returns only the topmost message (the most recent one), from its
    'Day N' up to just before the next 'Day N' — never sends two
    messages together.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None

    starts = [i for i, ln in enumerate(lines) if _DAY_LINE.search(ln)]
    if not starts:
        return None

    first = starts[0]
    end   = starts[1] if len(starts) > 1 else len(lines)
    block = " ".join(lines[first:end]).strip()
    return block or None


# ──────────────────────────────────────────────
#  DISCORD — ALERTS
# ──────────────────────────────────────────────
def _embed_color_for_message(log_message: str) -> int:
    """
    Returns the embed color based on the most severe keyword found in log_message.
    Priority: killed/destroyed (red) > tamed (green) > demolished (yellow) > froze (gray) > default (black)
    """
    msg = log_message or ""
    if keyword_in(msg, "killed") or keyword_in(msg, "destroyed"):
        return 0xE74C3C   # red
    if keyword_in(msg, "tamed"):
        return 0x2ECC71   # green
    if keyword_in(msg, "demolished"):
        return 0xF1C40F   # yellow
    if keyword_in(msg, "froze"):
        return 0x95A5A6   # gray
    return 0x000000       # black (no known keyword)


def send_log_message_to_discord(webhook_url: str, log_message: str, ping_labels: list,
                                 mention: str = "@everyone",
                                 count_pair: tuple = None):
    """Sends the log message (e.g. 'Day 18374, ...') + tribe status to the
    webhook as a Discord embed.

    ping_labels: list of already-evaluated ping reasons (e.g. ["killed"], ["destroyed"]).
                 If empty, no one is mentioned.
    mention:     already-resolved mention (e.g. "@everyone", or "<@&ROLE_ID>" for roles).
    """
    if not webhook_url:
        return

    label_text = {
        "killed":    "💀 Killed detected",
        "destroyed": "💥 Destroyed detected",
    }
    labels = [label_text[p] for p in ping_labels if p in label_text]

    content = mention if labels else ""

    # Color based on keyword detected in the actual log message
    color = _embed_color_for_message(log_message)

    if labels:
        title = "⚠️  ARK Alert"
    else:
        title = "📜  ARK Log"

    description = f"```{log_message}```"
    if labels:
        description += "\n" + "\n".join(f"**{l}**" for l in labels)

    fields = []
    if count_pair:
        online, total = count_pair
        fields.append({
            "name": "👥 Tribe",
            "value": f"**{online}/{total}** online",
            "inline": True,
        })

    embed = {
        "title": title,
        "description": description,
        "color": color,
        "fields": fields,
        "footer": {"text": "ARK Bot · Survival Ascended"},
        "timestamp": _utc_now_iso(),
    }

    payload = {"content": content, "embeds": [embed]}

    try:
        requests.post(webhook_url, json=payload, timeout=10)
    except requests.RequestException as e:
        print(f"[Discord] Error: {e}")


def send_member_change_to_discord(webhook_url: str, joined: bool, count_pair: tuple,
                                   mention: str = "@everyone", should_ping: bool = False):
    """Sends a simple 'Someone Joined!' / 'Someone Left!' embed when the
    online tribe counter changes (e.g. 2/6 → 3/6), independent of the
    kill/destroy log alerts."""
    if not webhook_url:
        return

    online, total = count_pair
    title = "🟢 Someone Joined!" if joined else "🔴 Someone Left!"
    color = 0x2ECC71 if joined else 0xE74C3C

    embed = {
        "title": title,
        "description": f"**{online}/{total}** online",
        "color": color,
        "footer": {"text": "ARK Bot · Survival Ascended"},
        "timestamp": _utc_now_iso(),
    }

    payload = {
        "content": mention if should_ping else "",
        "embeds": [embed],
    }

    try:
        requests.post(webhook_url, json=payload, timeout=10)
    except requests.RequestException as e:
        print(f"[Discord] Error: {e}")


def _utc_now_iso() -> str:
    """ISO-8601 UTC timestamp for the Discord embed's 'timestamp' field."""
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def send_text_to_discord(webhook_url: str, message: str):
    """Sends a simple text message to the webhook."""
    if not webhook_url:
        return
    try:
        requests.post(webhook_url, json={"content": message}, timeout=10)
    except requests.RequestException as e:
        print(f"[Discord] Error: {e}")


# ──────────────────────────────────────────────
#  TRIBE MONITOR — data structure
# ──────────────────────────────────────────────
# Detects "N/M" (e.g. "2/6") in the counter area.
# Tesseract sometimes confuses "/" with 1, l, I, \, or omits it — so the
# pattern also accepts those cases and normalizes them to "/".
_COUNT_PATTERN = re.compile(r"(\d{1,2})\s*[/\\|lI!]\s*(\d{1,2})")
_COUNT_DIGITS_ONLY = re.compile(r"(\d{1,2})\D{0,2}(\d{1,2})")


def _preprocess_counter(img: Image.Image, mode: int = 0) -> Image.Image:
    """Preprocessing specific to thick digits like '3/6'.
    More aggressive scaling + simple binarization, without over-inverting
    contrast (thick digits lose detail with the high contrast used for the log)."""
    scaled = img.resize((img.width * 6, img.height * 6), Image.LANCZOS)
    gray   = scaled.convert("L")

    if mode == 0:
        # Light text on dark background
        inv = Image.eval(gray, lambda p: 255 - p)
        return inv.point(lambda p: 0 if p > 120 else 255)
    elif mode == 1:
        # Dark text on light background
        return gray.point(lambda p: 0 if p < 130 else 255)
    else:
        # No binarization, scaling only — more tolerant to font thickness
        return gray


def parse_online_count(img: Image.Image) -> Optional[tuple]:
    """
    OCR of the online counter area (e.g. "3/6"), tuned for thick fonts.
    Tries several preprocessing modes and PSM configs, and normalizes
    misread separators ("3l6", "3 6", "3\\6") to "N/M".
    Returns (online, total) or None if it couldn't be read.
    """
    try:
        import pytesseract
    except Exception:
        return None

    _ensure_tesseract_path()

    configs = [
        "--psm 7 --oem 1 -c tessedit_char_whitelist=0123456789/",
        "--psm 8 --oem 1 -c tessedit_char_whitelist=0123456789/",
        "--psm 7 --oem 1",
        "--psm 13 --oem 1 -c tessedit_char_whitelist=0123456789/",
    ]

    candidates = []
    for mode in (0, 1, 2):
        try:
            processed = _preprocess_counter(img, mode)
        except Exception:
            continue
        for cfg in configs:
            try:
                text = pytesseract.image_to_string(processed, config=cfg).strip()
            except Exception:
                continue
            if not text:
                continue
            m = _COUNT_PATTERN.search(text)
            if not m:
                m = _COUNT_DIGITS_ONLY.search(text)
            if m:
                online, total = int(m.group(1)), int(m.group(2))
                if online <= total and total > 0 and total <= 50:
                    candidates.append((online, total))

    if not candidates:
        return None

    # Keep the most frequent result across all passes
    from collections import Counter
    most_common = Counter(candidates).most_common(1)[0][0]
    return most_common


# ──────────────────────────────────────────────
#  MAIN BOT CLASS
# ──────────────────────────────────────────────
class ArkBot:
    def __init__(self, cfg: dict, log_cb=None):
        self.cfg     = cfg
        self.log     = log_cb or print
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Previous alert state (region 1)
        self._prev_alert_img: Optional[Image.Image] = None
        self._last_log_message: Optional[str] = None

        # Previous tribe counter state (region 2) — used to detect joins/leaves
        # independently of the kill/destroy log alerts
        self._prev_count_pair: Optional[tuple] = None

    # ── Lifecycle ──────────────────────────────
    def start(self):
        if self._running:
            return
        self._running = True
        self._thread  = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self.log("▶ Bot started")

    def stop(self):
        self._running = False
        self.log("■ Bot stopped")

    # ── Main loop ──────────────────────────────
    def _run(self):
        self.log(f"[{XYZ_INIT}] Running initialization sequence…")
        if not send_xyz_sequence():
            self.log("⚠ ArkAscended window not found")

        while self._running:
            try:
                self._tick_alerts()
                self._tick_member_count()
            except Exception as exc:
                self.log(f"[Error] {exc}")
            time.sleep(0.08)

    # ── REGION 1: kill/destroy alerts ─────────
    def _tick_alerts(self):
        curr = capture_region(ALERT_REGION)
        if self._prev_alert_img is None:
            self._prev_alert_img = curr
            return

        if not images_differ(self._prev_alert_img, curr):
            self._prev_alert_img = curr
            return

        self.log("🔔 Change in alert zone — analyzing…")

        # ── Kick off the online-counter OCR right away on its own thread so
        # it runs concurrently with the alert-text OCR below instead of
        # adding its time on top once the text is already known ──
        count_result = {}

        def _read_counter():
            try:
                img = capture_region(TRIBE_COUNT_REGION)
                count_result["pair"] = parse_online_count(img)
            except Exception:
                count_result["pair"] = None

        counter_thread = threading.Thread(target=_read_counter, daemon=True)
        counter_thread.start()

        # ── Extract only the topmost log message (Day N → before the next Day N) ──
        full_text = ocr_full_text(curr, log_cb=self.log)
        top_msg   = extract_top_log_message(full_text)

        if top_msg:
            if top_msg == self._last_log_message:
                self.log("↪ Repeated log message, skipped")
            else:
                self._last_log_message = top_msg
                counter_thread.join(timeout=0.8)  # safety cap so a stuck OCR can't hang the alert
                self._handle_log_message(top_msg, count_result.get("pair"))
        else:
            preview = full_text.strip().replace("\n", " | ")[:200]
            if preview:
                self.log(f"⚠ OCR read text but no recognizable 'Day N': {preview}")
            else:
                _save_debug_capture(curr)
                self.log(f"⚠ Empty OCR — area {ALERT_REGION['width']}x{ALERT_REGION['height']}px. "
                          f"Captures saved in ocr_debug/ next to the .exe for review")

        self._prev_alert_img = curr

    # ── Decides whether to ignore/ping and sends to Discord ───
    def _handle_log_message(self, top_msg: str, count_pair: Optional[tuple] = None):
        # ── Ignore filters (nothing sent to Discord) ──
        # Evaluated against the same text that would be sent to Discord,
        # with tolerance to OCR/typing errors for each keyword.
        if self.cfg.get("ignore_if_tamed") == "true" and keyword_in(top_msg, "tamed"):
            self.log("🚫 Ignored (contains 'tamed')")
            return
        if self.cfg.get("ignore_if_demolished") == "true" and keyword_in(top_msg, "demolished"):
            self.log("🚫 Ignored (contains 'demolished')")
            return
        if self.cfg.get("ignore_if_froze") == "true" and keyword_in(top_msg, "froze"):
            self.log("🚫 Ignored (contains 'froze')")
            return
        if self.cfg.get("ignore_if_claimed") == "true" and keyword_in(top_msg, "claimed"):
            self.log("🚫 Ignored (contains 'claimed')")
            return
        if self.cfg.get("ignore_if_tribe_change") == "true" and TRIBE_CHANGE_PATTERN.search(top_msg):
            self.log("🚫 Ignored (tribe member change)")
            return

        self.log(f"📜 Log: {top_msg}")

        # ── Decide ping based on killed/destroyed in the text sent to Discord ──
        ping_labels = []
        if self.cfg.get("ping_if_killed") == "true" and keyword_in(top_msg, "killed"):
            ping_labels.append("killed")
            self.log(f"💀 'killed' detected → {self._ping_mention()}")
        if self.cfg.get("ping_if_destroyed") == "true" and keyword_in(top_msg, "destroyed"):
            ping_labels.append("destroyed")
            self.log(f"💥 'destroyed' detected → {self._ping_mention()}")

        if count_pair:
            self.log(f"👥 Counter: {count_pair[0]}/{count_pair[1]}")
        else:
            self.log("⚠ Could not read the online counter (N/M)")

        # ── Send to Discord on a separate thread so the polling loop isn't
        # blocked on the network request ──
        threading.Thread(
            target=send_log_message_to_discord,
            args=(self.cfg.get("webhook_url", ""), top_msg, ping_labels),
            kwargs={"mention": self._ping_mention(), "count_pair": count_pair},
            daemon=True,
        ).start()

    def _ping_mention(self) -> str:
        return resolve_ping_mention(self.cfg.get("ping_role", ""))

    # ── REGION 2: tribe online counter (join/leave) ───
    def _tick_member_count(self):
        """Independently watches the online counter (e.g. '2/6') and fires a
        join/leave alert to Discord whenever it changes — regardless of
        whether a kill/destroy log alert happened at the same time.
        Respects 'ignore_if_tribe_change' just like log-based tribe changes."""
        try:
            count_img = capture_region(TRIBE_COUNT_REGION)
        except Exception:
            return
        count_pair = parse_online_count(count_img)
        if not count_pair:
            return  # couldn't read it this tick, try again next tick

        if self._prev_count_pair is None:
            self._prev_count_pair = count_pair
            return

        if count_pair == self._prev_count_pair:
            return

        prev_online, _ = self._prev_count_pair
        new_online, new_total = count_pair
        self._prev_count_pair = count_pair

        if new_online == prev_online:
            # total changed but online count didn't — not a join/leave
            return

        joined = new_online > prev_online

        if self.cfg.get("ignore_if_tribe_change") == "true":
            self.log(f"🚫 Ignored (tribe member change) — {new_online}/{new_total}")
            return

        if joined:
            self.log(f"🟢 Someone joined → {new_online}/{new_total}")
        else:
            self.log(f"🔴 Someone left → {new_online}/{new_total}")

        threading.Thread(
            target=send_member_change_to_discord,
            args=(self.cfg.get("webhook_url", ""), joined, count_pair),
            kwargs={"mention": self._ping_mention()},
            daemon=True,
        ).start()




# ──────────────────────────────────────────────
#  WIDGET: HOTKEY BUTTON + GEAR
# ──────────────────────────────────────────────
# ──────────────────────────────────────────────
#  AREA SELECTOR (Snipping Tool style)
# ──────────────────────────────────────────────
class RegionSelector(ctk.CTkToplevel):
    """Full-screen overlay to select an area with the mouse."""

    def __init__(self, master, on_select, on_cancel=None):
        super().__init__(master)
        self._on_select = on_select
        self._on_cancel = on_cancel
        self._done = False
        self._start = None
        self._rect = None

        self.attributes("-fullscreen", True)
        self.attributes("-alpha", 0.30)
        self.attributes("-topmost", True)
        self.configure(fg_color="#000000", cursor="cross")
        self.overrideredirect(True)

        self.canvas = ctk.CTkCanvas(self, bg="#000000", highlightthickness=0,
                                     cursor="cross")
        self.canvas.pack(fill="both", expand=True)

        hint = self.canvas.create_text(
            self.winfo_screenwidth() // 2, 30,
            text="Drag to select the area  ·  ESC to cancel",
            fill=COLOR["accent"], font=("Segoe UI", 14, "bold"))
        self._hint_id = hint

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Escape>", self._on_escape)
        self.protocol("WM_DELETE_WINDOW", self._on_escape)
        self.focus_force()

    def _on_press(self, e):
        self._start = (e.x, e.y)
        if self._rect:
            self.canvas.delete(self._rect)
        self._rect = self.canvas.create_rectangle(
            e.x, e.y, e.x, e.y, outline=COLOR["accent"], width=2)

    def _on_drag(self, e):
        if self._start and self._rect:
            x0, y0 = self._start
            self.canvas.coords(self._rect, x0, y0, e.x, e.y)

    def _on_escape(self, e=None):
        self._done = True
        self.destroy()
        if self._on_cancel:
            self._on_cancel()

    def _on_release(self, e):
        if not self._start:
            return
        x0, y0 = self._start
        x1, y1 = e.x, e.y
        left, top   = min(x0, x1), min(y0, y1)
        width, height = abs(x1 - x0), abs(y1 - y0)
        self._done = True
        self.destroy()
        if width > 4 and height > 4:
            self._on_select({"top": int(top), "left": int(left),
                              "width": int(width), "height": int(height)})
        elif self._on_cancel:
            self._on_cancel()


# ──────────────────────────────────────────────
class HotkeyButton(ctk.CTkFrame):
    def __init__(self, master, label, default_hk, on_click, on_hk_change, **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self._hk = default_hk

        self.btn = ctk.CTkButton(
            self, text=label, width=140, height=36, font=FONT_TITLE,
            fg_color=COLOR["surface2"], hover_color=COLOR["accent_dim"],
            border_color=COLOR["border"], border_width=1,
            text_color=COLOR["text"], command=on_click,
        )
        self.btn.pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            self, text="⚙", width=28, height=28, font=("Segoe UI", 12),
            fg_color=COLOR["surface"], hover_color=COLOR["border"],
            border_color=COLOR["border"], border_width=1,
            text_color=COLOR["text_dim"],
            command=lambda: self._open_dialog(on_hk_change),
        ).pack(side="left")

    def _open_dialog(self, on_hk_change):
        dlg = ctk.CTkToplevel(self)
        dlg.title("Configure Hotkey")
        dlg.geometry("300x160")
        dlg.resizable(False, False)
        dlg.configure(fg_color=COLOR["bg"])
        dlg.grab_set()

        ctk.CTkLabel(dlg, text="Press a key:", font=FONT_TITLE,
                     text_color=COLOR["text"]).pack(pady=(18, 4))
        hk_var = ctk.StringVar(value=self._hk)
        entry  = ctk.CTkEntry(dlg, textvariable=hk_var, font=FONT_MONO,
                              width=160, justify="center",
                              fg_color=COLOR["surface2"],
                              border_color=COLOR["border"],
                              text_color=COLOR["accent"])
        entry.pack(pady=6)
        entry.focus()

        def capture(e):
            if e.keysym not in ("Shift_L","Shift_R","Control_L","Control_R","Alt_L","Alt_R"):
                hk_var.set(e.keysym)
        entry.bind("<KeyPress>", capture)

        def save():
            self._hk = hk_var.get()
            on_hk_change(self._hk)
            dlg.destroy()

        ctk.CTkButton(dlg, text="Save", command=save,
                      fg_color=COLOR["accent"], hover_color=COLOR["accent_dim"],
                      font=FONT_LABEL, width=100).pack(pady=10)

    def set_style(self, active: bool):
        self.btn.configure(fg_color=COLOR["accent"] if active else COLOR["surface2"])


# ──────────────────────────────────────────────
#  MAIN WINDOW
# ──────────────────────────────────────────────
class ArkBotApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.cfg  = load_config()
        self._bot = None

        self._build_ui()
        self._register_hotkeys()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── BUILD UI ──────────────────────────────
    def _build_ui(self):
        self.title(f"ARK Bot  v{APP_VERSION}")
        self.geometry("440x560")
        self.minsize(420, 540)
        self.configure(fg_color=COLOR["bg"])
        self.resizable(False, False)

        # Header
        hdr = ctk.CTkFrame(self, fg_color=COLOR["surface"], corner_radius=0, height=48)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        ctk.CTkLabel(hdr, text="⬡  ARK BOT", font=("Segoe UI Black", 16),
                     text_color=COLOR["accent"]).pack(side="left", padx=16, pady=12)
        ctk.CTkLabel(hdr, text="Survival Ascended · Automation",
                     font=FONT_SMALL, text_color=COLOR["text_dim"]).pack(side="left", pady=12)

        # Bot Control
        ctrl = ctk.CTkFrame(self, fg_color=COLOR["surface"],
                            corner_radius=8, border_color=COLOR["border"], border_width=1)
        ctrl.pack(fill="x", padx=12, pady=(10, 8))
        ctk.CTkLabel(ctrl, text="BOT CONTROL", font=FONT_SMALL,
                     text_color=COLOR["text_dim"]).pack(anchor="w", padx=12, pady=(8, 4))

        btn_row = ctk.CTkFrame(ctrl, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(0, 4))

        self.start_btn_widget = HotkeyButton(
            btn_row, label="▶  Start Bot",
            default_hk=self.cfg["start_hotkey"],
            on_click=self._toggle_bot,
            on_hk_change=self._on_start_hk_change,
        )
        self.start_btn_widget.pack(side="left")

        hk_row = ctk.CTkFrame(ctrl, fg_color="transparent")
        hk_row.pack(fill="x", padx=12, pady=(0, 8))
        self._start_hk_lbl = ctk.CTkLabel(hk_row,
            text=f"Hotkey: {self.cfg['start_hotkey']}",
            font=FONT_SMALL, text_color=COLOR["text_dim"])
        self._start_hk_lbl.pack(side="left")

        # Discord
        disc = ctk.CTkFrame(self, fg_color=COLOR["surface"],
                            corner_radius=8, border_color=COLOR["border"], border_width=1)
        disc.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkLabel(disc, text="DISCORD", font=FONT_SMALL,
                     text_color=COLOR["text_dim"]).pack(anchor="w", padx=12, pady=(8, 4))

        disc_inner = ctk.CTkFrame(disc, fg_color="transparent")
        disc_inner.pack(fill="x", padx=12, pady=(0, 6))
        ctk.CTkButton(disc_inner, text="🔗  Set Discord Webhook",
                      width=180, height=32, font=FONT_LABEL,
                      fg_color=COLOR["surface2"], hover_color=COLOR["border"],
                      border_color=COLOR["border"], border_width=1,
                      text_color=COLOR["text"],
                      command=self._open_webhook_dialog).pack(side="left", padx=(0, 10))
        self._webhook_status = ctk.CTkLabel(
            disc_inner,
            text="✔ Webhook configured" if self.cfg["webhook_url"] else "No webhook",
            font=FONT_SMALL,
            text_color=COLOR["success"] if self.cfg["webhook_url"] else COLOR["text_dim"],
        )
        self._webhook_status.pack(side="left", anchor="center")

        ping_frame = ctk.CTkFrame(disc, fg_color="transparent")
        ping_frame.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkButton(ping_frame, text="🔔  Configure Pings", width=180, height=32,
                      font=FONT_LABEL, fg_color=COLOR["surface2"],
                      hover_color=COLOR["border"], border_color=COLOR["border"],
                      border_width=1, text_color=COLOR["text"],
                      command=self._open_ping_dialog).pack(side="left", padx=(0, 10))
        self._ping_status = ctk.CTkLabel(
            ping_frame, text=self._ping_summary_text(),
            font=FONT_SMALL, text_color=COLOR["text_dim"])
        self._ping_status.pack(side="left", anchor="center")

        # Scan Areas
        areas = ctk.CTkFrame(self, fg_color=COLOR["surface"],
                             corner_radius=8, border_color=COLOR["border"], border_width=1)
        areas.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkLabel(areas, text="SCAN AREAS", font=FONT_SMALL,
                     text_color=COLOR["text_dim"]).pack(anchor="w", padx=12, pady=(8, 4))

        areas_row = ctk.CTkFrame(areas, fg_color="transparent")
        areas_row.pack(fill="x", padx=12, pady=(0, 4))

        ctk.CTkButton(areas_row, text="▣  Configure Areas", width=180, height=32,
                      font=FONT_LABEL, fg_color=COLOR["surface2"],
                      hover_color=COLOR["border"], border_color=COLOR["border"],
                      border_width=1, text_color=COLOR["text"],
                      command=self._open_areas_dialog).pack(side="left")

        self._area_status = ctk.CTkLabel(
            areas,
            text=(f"Alerts: {region_to_str(ALERT_REGION)}  ·  "
                  f"Counter: {region_to_str(TRIBE_COUNT_REGION)}"),
            font=FONT_SMALL, text_color=COLOR["text_dim"], wraplength=400)
        self._area_status.pack(anchor="w", padx=12, pady=(8, 8))

        # Log
        log_frame = ctk.CTkFrame(self, fg_color=COLOR["surface"],
                                 corner_radius=8, border_color=COLOR["border"], border_width=1)
        log_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        log_hdr = ctk.CTkFrame(log_frame, fg_color="transparent")
        log_hdr.pack(fill="x", padx=10, pady=(8, 0))
        ctk.CTkLabel(log_hdr, text="LOG", font=FONT_SMALL,
                     text_color=COLOR["text_dim"]).pack(side="left")
        self._status_dot = ctk.CTkLabel(log_hdr, text="●",
                                        font=("Segoe UI", 14),
                                        text_color=COLOR["text_dim"])
        self._status_dot.pack(side="right")

        self.log_box = ctk.CTkTextbox(
            log_frame, font=FONT_MONO, fg_color=COLOR["bg"],
            text_color=COLOR["text"], border_width=0,
            corner_radius=0, wrap="word", state="disabled")
        self.log_box.pack(fill="both", expand=True, padx=6, pady=(4, 8))
        self._log(f"ARK Bot {APP_VERSION} ready  [{XYZ_INIT}]")

    # ── Helpers ───────────────────────────────
    def _log(self, msg: str):
        def _w():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", f"» {msg}\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.after(0, _w)

    def _set_status(self, running: bool):
        c = COLOR["success"] if running else COLOR["text_dim"]
        self.after(0, lambda: self._status_dot.configure(text_color=c))
        self.after(0, lambda: self.start_btn_widget.set_style(running))
        self.after(0, lambda: self.start_btn_widget.btn.configure(
            text="■  Stop Bot" if running else "▶  Start Bot"))

    # ── Bot ───────────────────────────────────
    def _toggle_bot(self):
        if self._bot and self._bot._running:
            self._stop_bot()
        else:
            self._start_bot()
    def _start_bot(self):
        if self._bot and self._bot._running:
            self._log("The bot is already running")
            return
        self._bot = ArkBot(dict(self.cfg), log_cb=self._log)
        self._bot.start()
        self._set_status(True)

    def _stop_bot(self):
        if self._bot:
            self._bot.stop()
            self._bot = None
        self._set_status(False)

    # ── Hotkeys ───────────────────────────────
    def _register_hotkeys(self):
        try:
            keyboard.remove_all_hotkeys()
        except Exception:
            pass
        try:
            keyboard.add_hotkey(self.cfg["start_hotkey"], self._toggle_bot, suppress=False)
        except Exception as e:
            self._log(f"[Hotkey] {e}")

    def _on_start_hk_change(self, hk: str):
        self.cfg["start_hotkey"] = hk
        self._start_hk_lbl.configure(text=f"Hotkey: {hk}")
        self._register_hotkeys(); self._save_cfg()

    # ── Webhook Dialog ────────────────────────
    def _open_webhook_dialog(self):
        dlg = ctk.CTkToplevel(self)
        dlg.title("Discord Webhook")
        dlg.geometry("420x190")
        dlg.resizable(False, False)
        dlg.configure(fg_color=COLOR["bg"])
        dlg.grab_set()
        ctk.CTkLabel(dlg, text="Discord Webhook URL", font=FONT_TITLE,
                     text_color=COLOR["text"]).pack(pady=(18, 6))
        url_var = ctk.StringVar(value=self.cfg.get("webhook_url", ""))
        entry   = ctk.CTkEntry(dlg, textvariable=url_var, width=370,
                               font=FONT_SMALL,
                               placeholder_text="https://discord.com/api/webhooks/...",
                               fg_color=COLOR["surface2"],
                               border_color=COLOR["border"],
                               text_color=COLOR["text"])
        entry.pack(pady=4)

        def save():
            url = url_var.get().strip()
            self.cfg["webhook_url"] = url
            self._webhook_status.configure(
                text="✔ Webhook configured" if url else "No webhook",
                text_color=COLOR["success"] if url else COLOR["text_dim"])
            self._save_cfg()
            self._log("✔ Webhook updated")
            dlg.destroy()

        ctk.CTkButton(dlg, text="Save", command=save,
                      fg_color=COLOR["accent"], hover_color=COLOR["accent_dim"],
                      font=FONT_LABEL, width=110).pack(pady=14)

    # ── Ping / filter dialog ───────────────────
    def _ping_summary_text(self) -> str:
        role = resolve_ping_mention(self.cfg.get("ping_role", ""))
        active = [k for k in ("ping_if_killed", "ping_if_destroyed") if self.cfg.get(k) == "true"]
        return f"Mention: {role}  ·  {len(active)} ping(s) active"

    def _open_ping_dialog(self):
        dlg = ctk.CTkToplevel(self)
        dlg.title("Configure Pings")
        dlg.geometry("380x470")
        dlg.resizable(False, False)
        dlg.configure(fg_color=COLOR["bg"])
        dlg.grab_set()

        ctk.CTkLabel(dlg, text="Pings and Filters", font=FONT_TITLE,
                     text_color=COLOR["text"]).pack(pady=(18, 4))

        ctk.CTkLabel(dlg, text="Numeric role ID (empty = @everyone)\n"
                              "⚠ Use the role ID, not the name — Discord\n"
                              "   doesn't actually ping by name (e.g. 123456789012)",
                     font=FONT_SMALL, text_color=COLOR["text_dim"],
                     wraplength=330).pack(pady=(4, 4))
        role_var = ctk.StringVar(value=self.cfg.get("ping_role", ""))
        ctk.CTkEntry(dlg, textvariable=role_var, width=300, font=FONT_SMALL,
                     placeholder_text="123456789012345678  (role ID)",
                     fg_color=COLOR["surface2"], border_color=COLOR["border"],
                     text_color=COLOR["text"]).pack(pady=(0, 14))

        ctk.CTkLabel(dlg, text="PINGS", font=FONT_SMALL,
                     text_color=COLOR["text_dim"]).pack(anchor="w", padx=24)

        chk_vars = {}

        def add_check(key: str, label: str):
            var = ctk.IntVar(value=1 if self.cfg.get(key) == "true" else 0)
            ctk.CTkCheckBox(dlg, text=label, font=FONT_LABEL, variable=var,
                            text_color=COLOR["text"], fg_color=COLOR["accent"],
                            hover_color=COLOR["accent_dim"],
                            border_color=COLOR["border"]).pack(anchor="w", padx=24, pady=3)
            chk_vars[key] = var

        add_check("ping_if_killed",    "Ping if killed")
        add_check("ping_if_destroyed", "Ping if destroyed")

        ctk.CTkLabel(dlg, text="IGNORE MESSAGES", font=FONT_SMALL,
                     text_color=COLOR["text_dim"]).pack(anchor="w", padx=24, pady=(14, 0))

        add_check("ignore_if_tamed",        "Ignore if tamed")
        add_check("ignore_if_demolished",   "Ignore if demolished")
        add_check("ignore_if_froze",        "Ignore if froze")
        add_check("ignore_if_claimed",      "Ignore if claimed")
        add_check("ignore_if_tribe_change", "Ignore if tribemember changes")

        def save():
            self.cfg["ping_role"] = role_var.get().strip()
            for key, var in chk_vars.items():
                self.cfg[key] = str(var.get() == 1).lower()
            self._save_cfg()
            self._ping_status.configure(text=self._ping_summary_text())
            self._log("✔ Ping configuration updated")
            dlg.destroy()

        ctk.CTkButton(dlg, text="Save", command=save,
                      fg_color=COLOR["accent"], hover_color=COLOR["accent_dim"],
                      font=FONT_LABEL, width=110).pack(pady=18)

    # ── Areas dialog ────────────────────────
    def _open_areas_dialog(self):
        dlg = ctk.CTkToplevel(self)
        dlg.title("Configure Scan Areas")
        dlg.geometry("340x200")
        dlg.resizable(False, False)
        dlg.configure(fg_color=COLOR["bg"])
        dlg.grab_set()

        ctk.CTkLabel(dlg, text="Scan Areas", font=FONT_TITLE,
                     text_color=COLOR["text"]).pack(pady=(18, 12))

        def pick(which: str):
            dlg.destroy()
            self._select_region(which)

        ctk.CTkButton(dlg, text="▣  Alert Area", width=260, height=36,
                      font=FONT_LABEL, fg_color=COLOR["surface2"],
                      hover_color=COLOR["border"], border_color=COLOR["border"],
                      border_width=1, text_color=COLOR["text"],
                      command=lambda: pick("alert")).pack(pady=6)

        ctk.CTkButton(dlg, text="▣  Online Counter", width=260, height=36,
                      font=FONT_LABEL, fg_color=COLOR["surface2"],
                      hover_color=COLOR["border"], border_color=COLOR["border"],
                      border_width=1, text_color=COLOR["text"],
                      command=lambda: pick("tribe_count")).pack(pady=6)

    # ── Region selection ───────────────────────
    def _select_region(self, which: str):
        focus_ark()
        self.withdraw()

        def on_selected(region: dict):
            global ALERT_REGION, TRIBE_COUNT_REGION
            self.deiconify()
            if which == "alert":
                ALERT_REGION = region
                self.cfg["alert_region"] = region_to_str(region)
            elif which == "tribe_count":
                TRIBE_COUNT_REGION = region
                self.cfg["tribe_count_region"] = region_to_str(region)
            self._area_status.configure(
                text=(f"Alerts: {region_to_str(ALERT_REGION)}  ·  "
                      f"Counter: {region_to_str(TRIBE_COUNT_REGION)}"))
            self._save_cfg()
            self._log(f"✔ Area '{which}' updated: {region_to_str(region)}")

        def on_cancel():
            self.deiconify()

        self.after(150, lambda: RegionSelector(self, on_selected, on_cancel))

    # ── Config ────────────────────────────────
    def _save_cfg(self):
        save_config(self.cfg)

    def _on_close(self):
        self._stop_bot()
        try: keyboard.remove_all_hotkeys()
        except: pass
        self._save_cfg()
        self.destroy()


# ──────────────────────────────────────────────
#  ENTRY POINT
# ──────────────────────────────────────────────
if __name__ == "__main__":
    app = ArkBotApp()
    app.mainloop()