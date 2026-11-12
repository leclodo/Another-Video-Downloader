#!/usr/bin/env python3
"""Another Video Downloader - GUI for yt-dlp / interface graphique pour yt-dlp.

Requirements / Prérequis :
    pip install -U "yt-dlp[default]" pillow
    ffmpeg in PATH (MP3, trimming, video + audio merge)  ->  winget install ffmpeg
"""

import gc
import io
import json
import math
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
import tkinter as tk
import tkinter.font as tkfont
import traceback
import webbrowser
from tkinter import filedialog, messagebox, ttk
from concurrent.futures import ThreadPoolExecutor, wait as futures_wait, FIRST_COMPLETED
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.error import HTTPError
from urllib.request import Request, urlopen

# Windowed builds (.pyw / PyInstaller --windowed) have no stdout/stderr: give libraries a sink.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")


def app_data_dir():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    new = os.path.join(base, "Another Video Downloader")
    old = os.path.join(base, "Just a YouTube Downloader")       # previous name: settings + queue are carried over
    if not os.path.exists(new) and os.path.isdir(old):
        try:
            shutil.copytree(old, new)
        except OSError:
            pass
    return new


def updates_dir():
    """Where the .exe stores yt-dlp / ffmpeg updates (it cannot modify itself)."""
    return os.path.join(app_data_dir(), "updates")


def _exe_stamp():
    try:
        st = os.stat(sys.executable)
        return f"{st.st_size}-{int(st.st_mtime)}"
    except OSError:
        return ""


def _write_stamp():
    """Ties the stored updates to this exact .exe: a rebuilt .exe discards older updates."""
    os.makedirs(updates_dir(), exist_ok=True)
    with open(os.path.join(updates_dir(), "exe.stamp"), "w") as f:
        f.write(_exe_stamp())


YT_OVERRIDE = os.path.join(updates_dir(), "ytdlp")


def _setup_ffmpeg_path():
    """Lets ffmpeg sit next to the script / .exe, or inside the .exe (PyInstaller's temp folder).

    In the .exe, updates downloaded from the Infos window (ffmpeg, yt-dlp) take priority."""
    frozen = getattr(sys, "frozen", False)
    dirs = [os.path.dirname(os.path.abspath(sys.executable if frozen else __file__))]
    if frozen and getattr(sys, "_MEIPASS", None):
        dirs.append(sys._MEIPASS)
    if frozen:
        root = updates_dir()
        try:
            if os.path.isdir(root):
                with open(os.path.join(root, "exe.stamp")) as f:
                    if f.read().strip() != _exe_stamp():
                        raise OSError("exe changed")
        except OSError:
            shutil.rmtree(root, ignore_errors=True)
        if os.path.isdir(os.path.join(root, "ffmpeg")):
            dirs.insert(0, os.path.join(root, "ffmpeg"))
        if os.path.isdir(YT_OVERRIDE):
            sys.path.insert(0, YT_OVERRIDE)
    os.environ["PATH"] = os.pathsep.join(dirs + [os.environ.get("PATH", "")])


def _hide_console():
    """Hides the console window when it was opened just for this script (double-click).

    A console that belongs to someone else (script started from cmd / a terminal) is left alone.
    For no console at all, even briefly, rename the file to .pyw.
    """
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        hwnd = k32.GetConsoleWindow()
        pids = (ctypes.c_uint * 4)()
        if hwnd and k32.GetConsoleProcessList(pids, 4) <= 1:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


_setup_ffmpeg_path()

# yt-dlp is heavy to import (~1-2 s): it loads in a background thread while the window is built.
# The names below wait for it when first used, so the rest of the code does not change.
_YT = {}
_YT_READY = threading.Event()


def _load_ytdlp():
    try:
        try:
            import yt_dlp as mod
            from yt_dlp.utils import download_range_func as rng, sanitize_filename as san
        except Exception:
            if not os.path.isdir(YT_OVERRIDE):
                raise
            # A broken downloaded update: drop it and fall back to the version packed in the .exe.
            for _m in [m for m in sys.modules if m.split(".")[0] in ("yt_dlp", "yt_dlp_ejs")]:
                del sys.modules[_m]
            sys.path[:] = [p for p in sys.path if p != YT_OVERRIDE]
            shutil.rmtree(YT_OVERRIDE, ignore_errors=True)
            import yt_dlp as mod
            from yt_dlp.utils import download_range_func as rng, sanitize_filename as san
        _YT.update(mod=mod, range=rng, san=san)
    except BaseException as e:
        _YT["error"] = e
    finally:
        _YT_READY.set()


def _yt(key):
    _YT_READY.wait()
    if "error" in _YT:
        raise _YT["error"]
    return _YT[key]


class _LazyYt:
    def __getattr__(self, name):
        return getattr(_yt("mod"), name)


yt_dlp = _LazyYt()


def download_range_func(*a, **k):
    return _yt("range")(*a, **k)


def sanitize_filename(*a, **k):
    return _yt("san")(*a, **k)


from PIL import Image, ImageDraw, ImageTk  # noqa: E402
try:                                  # optional: notification-area icon ("close to tray")
    import pystray  # noqa: E402
except Exception:
    pystray = None

# ------------------------------------------------------------------ constants
YTDLP_URL = "https://github.com/yt-dlp/yt-dlp"
SITES_URL = "https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md"
FFMPEG_URL = "https://ffmpeg.org/download.html"

ACCENT = "#4f7cff"
PALETTES = {
    "dark": {
        "BG": "#0b0d12", "CARD": "#12151c", "CARD2": "#1a1e29", "BORDER": "#232838",
        "FG": "#e8ecf4", "MUTED": "#8a93a6", "DIM": "#555d70", "ACCENT_HI": "#6b92ff",
        "GREEN": "#3ddc84", "RED": "#ff5c6c", "ORANGE": "#ffb020",
        "BTN2": "#222839", "BTN2_HI": "#2d3550", "DANGER_BG": "#2a1a20", "DANGER_HI": "#3d2029",
        "BTN_OFF": "#161a24", "TIP_BG": "#1f2433", "INPUT_OFF": "#0f1219", "INVALID_BG": "#4a1d24",
        "SB": "#2a3043", "SB_HI": "#3a4260", "ACCENT": "#4f7cff",
    },
    "light": {  # no value may be pure white: "#ffffff" is kept for text on coloured buttons
        "BG": "#eef1f7", "CARD": "#fdfdfe", "CARD2": "#e9edf5", "BORDER": "#d5dbe7",
        "FG": "#1b2030", "MUTED": "#5f6980", "DIM": "#a3abbc", "ACCENT_HI": "#3d68e8",
        "GREEN": "#16a34a", "RED": "#dc2f45", "ORANGE": "#c77700",
        "BTN2": "#e1e6f0", "BTN2_HI": "#d3daea", "DANGER_BG": "#fde8ec", "DANGER_HI": "#f9d3da",
        "BTN_OFF": "#eceff5", "TIP_BG": "#fbfcfe", "INPUT_OFF": "#e3e7ef", "INVALID_BG": "#fbd5db",
        "SB": "#c9d0df", "SB_HI": "#aab3c8", "ACCENT": "#4f7cff",
    },
    "sakura": {  # soft pink, light
        "BG": "#fbeef3", "CARD": "#fff7fa", "CARD2": "#f7e0e9", "BORDER": "#efc8d7",
        "FG": "#3b2430", "MUTED": "#8a5f72", "DIM": "#c9a3b3", "ACCENT_HI": "#cf3f77",
        "GREEN": "#2f9e6a", "RED": "#d6334f", "ORANGE": "#c9731a",
        "BTN2": "#f3d5e1", "BTN2_HI": "#ebc2d4", "DANGER_BG": "#fde1e8", "DANGER_HI": "#f9ccd7",
        "BTN_OFF": "#f6e4eb", "TIP_BG": "#fffbfc", "INPUT_OFF": "#f3dfe7", "INVALID_BG": "#f9c9d3",
        "SB": "#e9bfce", "SB_HI": "#dba1b6", "ACCENT": "#e0558a",
    },
    "cyberpunk": {  # night violet + magenta (toned down)
        "BG": "#0d0a18", "CARD": "#151022", "CARD2": "#1e172f", "BORDER": "#33284f",
        "FG": "#e9e4f5", "MUTED": "#9a90b8", "DIM": "#5a5078", "ACCENT_HI": "#d9479a",
        "GREEN": "#2fcf9b", "RED": "#e5485f", "ORANGE": "#e8b923",
        "BTN2": "#271d3d", "BTN2_HI": "#352851", "DANGER_BG": "#32132a", "DANGER_HI": "#451a37",
        "BTN_OFF": "#171126", "TIP_BG": "#221a36", "INPUT_OFF": "#0f0b1b", "INVALID_BG": "#4a1832",
        "SB": "#35294f", "SB_HI": "#4e3d74", "ACCENT": "#c13584",
    },
    "hacker": {  # terminal green on black
        "BG": "#050805", "CARD": "#0a110a", "CARD2": "#101a10", "BORDER": "#17301a",
        "FG": "#b8f5b8", "MUTED": "#5fae6a", "DIM": "#2f5a36", "ACCENT_HI": "#22c95a",
        "GREEN": "#39ff7a", "RED": "#ff4d4d", "ORANGE": "#e6b800",
        "BTN2": "#122312", "BTN2_HI": "#1a331b", "DANGER_BG": "#2a1212", "DANGER_HI": "#3a1818",
        "BTN_OFF": "#0b130b", "TIP_BG": "#0f1c0f", "INPUT_OFF": "#070d07", "INVALID_BG": "#3d1414",
        "SB": "#1a3a1d", "SB_HI": "#26552b", "ACCENT": "#12a844",
    },
}
THEME_DARK = {"dark": True, "light": False, "sakura": False, "cyberpunk": True, "hacker": True}
LIGHT_THEMES = {k for k, dark in THEME_DARK.items() if not dark}


def heavy(name=None):
    """Font weight for titles: light themes (clear, sakura) look better without bold."""
    return "normal" if (name or THEME) in LIGHT_THEMES else "bold"


THEME = "dark"
globals().update(PALETTES[THEME])


def load_font():
    """Sora (fonts/ folder next to the script, or packed in the .exe) loaded for this process only;
    falls back to Segoe UI when the files or Windows are not there."""
    if not sys.platform.startswith("win"):
        return "Segoe UI"
    try:
        import ctypes
        bases = [os.path.dirname(os.path.abspath(__file__))]
        if getattr(sys, "_MEIPASS", None):
            bases.insert(0, sys._MEIPASS)
        loaded = 0
        for base in bases:
            for f in ("Sora-Regular.ttf", "Sora-Bold.ttf"):
                path = os.path.join(base, "fonts", f)
                if os.path.exists(path):  # FR_PRIVATE = 0x10: not installed on the PC
                    loaded += ctypes.windll.gdi32.AddFontResourceExW(path, 0x10, 0)
            if loaded:
                return "Sora"
    except Exception:
        pass
    return "Segoe UI"


FONT = load_font()


def system_theme():
    """'dark' or 'light' according to the PC's setting (Windows); dark elsewhere."""
    if sys.platform.startswith("win"):
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
                return "light" if winreg.QueryValueEx(k, "AppsUseLightTheme")[0] else "dark"
        except OSError:
            pass
    return "dark"


def set_theme(name):
    """Switches the colour constants; returns {old colour: new colour} to repaint existing widgets."""
    global THEME
    old = dict(PALETTES[THEME])
    THEME = name
    globals().update(PALETTES[name])
    return {old[k].lower(): PALETTES[name][k] for k in old if old[k].lower() != PALETTES[name][k].lower()}


_COLOR_OPTS = ("bg", "fg", "activebackground", "activeforeground", "highlightbackground",
               "highlightcolor", "insertbackground", "selectcolor", "disabledforeground",
               "disabledbackground", "readonlybackground")


def recolor_tree(widget, mapping):
    """Repaints a widget and all its children with `mapping` (old colour -> new colour)."""
    try:
        keys = widget.keys()
        for opt in _COLOR_OPTS:
            if opt in keys:
                new = mapping.get(str(widget.cget(opt)).lower())
                if new:
                    tk.Misc.configure(widget, **{opt: new})
        base = getattr(widget, "base_fg", None)
        if base and base.lower() in mapping:
            widget.base_fg = mapping[base.lower()]
        if isinstance(widget, tk.Canvas) and not isinstance(widget, RoundButton):
            for item in widget.find_all():
                for opt in ("fill", "outline"):
                    try:
                        new = mapping.get(str(widget.itemcget(item, opt)).lower())
                        if new:
                            widget.itemconfig(item, **{opt: new})
                    except tk.TclError:
                        pass
        if isinstance(widget, RoundButton):
            widget._redraw()
        if isinstance(widget, ttk.Combobox):  # its drop-down list is a separate widget
            widget.tk.call("ttk::combobox::PopdownWindow", str(widget))
            widget.tk.call(f"{widget}.popdown.f.l", "configure", "-background", CARD2,
                           "-foreground", FG, "-selectbackground", ACCENT)
    except tk.TclError:
        pass
    for child in widget.winfo_children():
        recolor_tree(child, mapping)

WIDTH = 1080     # also the minimum window width (fits a 1080 px wide, rotated screen)
MAX_VISIBLE = 5  # rows visible in the queue before a scrollbar appears
QUEUE_SPACE = 410  # extra window height reserved for a full queue (MAX_VISIBLE lines)
NAME_PX = 200   # max pixel width of a file name in the queue

# (column, min width) - shared by the header and the queue rows.
COLS = [(0, 94), (1, 170), (2, 84), (3, 92), (4, 84), (5, 110), (6, 190), (7, 76)]

ANSI = re.compile(r"\x1b\[[0-9;]*m")

# ----------------------------------------------------------------------- i18n
LANG = "fr"

T = {
    "fr": {
        "title": "Another Video Downloader",
        "link": "Lien",
        "load": "Charger",
        "thumb": "miniature",
        "thumb_save": "Enregistrer l'image sous…", "thumb_title": "Miniatures",
        "video_title": "Titre de la vidéo",
        "length_ph": "Durée",
        "date_ph": "Date de mise en ligne",
        "length": "Durée : {v}",
        "date": "Mise en ligne : {v}",
        "quality": "Qualité",
        "trim": "Découpe",
        "start": "début",
        "end": "fin",
        "start_w": "début",
        "end_w": "fin",
        "trim_suffix": " (extrait)",
        "folder": "Dossier…",
        "add": "Ajouter à la file",
        "download": "Télécharger",
        "queue": "File d'attente",
        "col_added": "#",
        "col_title": "Titre",
        "col_length": "Durée",
        "col_date": "Date",
        "col_quality": "Qualité",
        "col_trim": "Découpe",
        "col_progress": "Progression",
        "dl_queue": "Télécharger la file",
        "stop_queue": "Arrêter la file",
        "clear_queue": "Effacer la file",
        "no_ffmpeg": "⚠ ffmpeg introuvable : découpe désactivée — le MP3 et la HD risquent d'échouer",
        "tip_trim_off": "Découpe indisponible : ffmpeg est introuvable (voir Infos).",
        "info_ytdlp_bundled": "yt-dlp est déjà inclus dans cette application, rien à installer.",
        "info_ffmpeg_bundled": "ffmpeg est déjà inclus dans cette application, rien à installer.",
        "lang_btn": "EN",
        "tip_settings": "Paramètres",
        "settings_title": "Paramètres",
        "set_lang": "Langue",
        "set_theme": "Thème",
        "theme_dark": "☾  Sombre",
        "theme_light": "☀  Clair",
        "theme_sakura": "Sakura", "theme_cyberpunk": "Cyberpunk", "theme_hacker": "Hacker",
        "set_date": "Format de la date",
        "date_eu": "JJ/MM/AAAA",
        "date_us": "MM/JJ/AAAA",
        "date_iso": "AAAA-MM-JJ",
        "est_size": "Taille estimée : {v}",
        "est_time": "Temps estimé : {v}",
        "est_unknown": "inconnue",
        "est_nolimit": "selon ta connexion",
        "unit_mb": "Mo",
        "unit_gb": "Go",
        "set_speed": "Limite de vitesse de téléchargement",
        "speed_unit": "Mo/s",
        "speed_or": "ou",
        "pl_count": "Playlist : {n} vidéos",
        "trim_edit_title": "Modifier la découpe", "trim_cancel": "Annuler",
        "tip_trim_edit": "Cliquer pour modifier la découpe",
        "set_close": "Bouton de fermeture (✕)",
        "set_compat": "Compatibilité montage",
        "compat_edit": "Compatible Premiere (H.264 + AAC)", "compat_best": "Qualité maximale (VP9/AV1 + Opus)",
        "compat_hint": "Premiere et d'autres logiciels de montage ne lisent pas VP9/AV1/Opus. Le mode compatible choisit H.264 + AAC "
                       "quand YouTube le propose ; sinon (1440p, 4K…) la vidéo est ré-encodée automatiquement après le téléchargement (plus long).",
        "set_live": "Directs en cours (lives)",
        "live_now": "À partir de maintenant", "live_start": "Depuis le début",
        "set_trimmode": "Découpe (trim)", "trim_exact": "Précise", "trim_fast": "Rapide",
        "trimmode_hint": "Précise : la partie choisie est réencodée, découpe à l'image près mais plus lent. "
                         "Rapide : coupe à l'image clé la plus proche sans réencoder (quelques secondes de décalage possibles).",
        "live_hint": "« Depuis le début » récupère le direct depuis son commencement quand YouTube le permet "
                     "(expérimental, plus lourd au démarrage).",
        "live_tag": "● DIRECT",
        "live_cb": "Depuis le début du direct",
        "live_set": "Direct : début de l'enregistrement",
        "live_short_start": "Du début", "live_short_now": "Maintenant",
        "stopping_live": "Arrêt du direct…", "finalizing": "Création du MP4…",
        "tip_stop_live": "Arrêter et garder ce qui est enregistré",
        "live_fail": "Impossible de finaliser le fichier du direct",
        "close_quit": "Quitter", "close_tray": "Réduire dans la zone de notification",
        "close_need": "Nécessite le module pystray (pip install pystray).",
        "tray_open": "Ouvrir", "tray_quit": "Quitter",
        "ctx_cut": "Couper", "ctx_copy": "Copier", "ctx_paste": "Coller", "ctx_all": "Tout sélectionner",
        "tip_clear": "Effacer le lien",
        "speed_unlimited": "Illimitée",
        "set_name": "Nom des fichiers",
        "name_vars": "Variables :",
        "name_example": "Exemple : {v}",
        "name_default": "Remettre le nom par défaut",
        "settings_save": "Enregistrer",
        "views_word": "vues",
        "sample_title": "Ma vidéo",
        "sample_channel": "Ma chaîne",
        "best": "Meilleure",
        "waiting": "En attente",
        "starting": "Connexion…",
        "rec": "Enregistrement", "merging": "Fusion audio + vidéo…", "audio_conv": "Conversion en MP3…",
        "tip_logs": "Journal", "logs_title": "Journal", "log_copy": "Copier", "log_clear": "Effacer",
        "log_copied": "Copié", "log_empty": "(vide)",
        "converting": "Conversion…",
        "done": "Terminé ✓",
        "error": "Erreur ✗ (clic)",
        "cancelled": "Arrêté",
        "stopping": "Arrêt…",
        "load_err": "Impossible de charger la vidéo",
        "playlist": "Playlist non gérée : colle le lien d'une vidéo.",
        "trim_title": "Découpe",
        "trim_bad": "Le début doit être avant la fin (et dans la vidéo).",
        "queue_title": "File d'attente",
        "queue_empty": "Rien à télécharger dans la file.",
        "dl_err": "Erreur de téléchargement",
        "yes": "Oui", "no": "Non", "toast_done": "Téléchargement terminé", "toast_play": "Lire",
        "vol": "Volume des notifications",
        "notif_style": "Style de la bulle", "style_1": "Carte", "style_2": "Bandeau", "style_3": "Vertical",
        "notif_test_err": "Tester le son d'erreur",
        "notif_tone": "Mélodie", "tone_1": "Carillon", "tone_2": "Snap", "tone_3": "Arpège", "tone_4": "Tri-ton",
        "notif_test": "Tester les notifications",
        "notif_sound": "Son de fin de téléchargement", "notif_toast": "Bulle de notification",
        "notif_on": "Activé", "notif_off": "Désactivé", "canceled": "Annulé",
        "tab_general": "Général", "tab_dl": "Téléchargement", "tab_notif": "Notifications", "tab_adv": "Avancé",
        "set_codec": "Codec vidéo", "codec_h264": "H.264 (Premiere)", "codec_best": "Max", "codec_vp9": "VP9", "codec_av1": "AV1",
        "codec_hint": "H.264 : compatible Premiere et la plupart des logiciels de montage (ré-encodé automatiquement si YouTube n'a que du VP9/AV1/Opus). "
                      "Max : le meilleur flux disponible, sans conversion. VP9 / AV1 : préfère ce codec quand il existe.",
        "dup_queue_title": "Déjà dans la file", "dup_queue_msg": "« {name} » est déjà dans la file.\n\nL'ajouter quand même ?",
        "dup_hist_msg": "« {name} » a déjà été téléchargée le {date}.\n\nLa télécharger à nouveau ?",
        "dup_tag_queue": "déjà dans la file", "dup_tag_hist": "déjà téléchargée",
        "dup_pl_msg": "{n} vidéo(s) de la playlist sont déjà dans la file ou déjà téléchargées.\n\nLes ignorer ?",
        "hist_search": "Rechercher", "hist_sort_new": "Récents", "hist_sort_old": "Anciens", "hist_sort_name": "A–Z",
        "hist_none": "Aucun résultat",
        "set_retry": "Relance automatique", "retry_off": "Non",
        "retry_hint": "Nombre d'essais en cas d'erreur réseau.",
        "set_cookies": "Cookies du navigateur", "cookies_none": "Aucun",
        "cookies_why": "Certaines vidéos (privées, +18, réservées aux membres) ne s'ouvrent que si tu es connecté. "
                       "Connecte-toi au site de la vidéo dans Firefox et choisis-le ici : l'appli utilise ta session, "
                       "uniquement pour ces vidéos. Inutile pour les vidéos publiques.",
        "cookies_import_hint": "Chrome, Edge, Brave : exporte tes cookies avec une extension (« Get cookies.txt LOCALLY »), "
                               "puis importe le fichier. Tes cookies restent sur ton PC : ils ne sont ni partagés, "
                               "ni envoyés à autre chose qu'au site de la vidéo.",
        "ck_sync_hint": "Cette vidéo demande d'être connecté (privée, +18, membres…).\n"
                        "Ajoute tes cookies dans Paramètres › Avancé.",
        "ck_import": "Importer un cookies.txt", "ck_remove": "Retirer",
        "ck_file_ok": "✔ Fichier importé ({n} cookies)", "ck_file_bad": "✖ Fichier invalide (format cookies.txt attendu)",
        "priv_title": "Confidentialité",
        "priv_body": "Aucune donnée n'est collectée, prélevée, partagée ni vendue. Tout (réglages, file d'attente, historique) reste sur ton PC. "
                     "L'application ne contacte que les sites des vidéos, et GitHub / PyPI pour vérifier les mises à jour.",
        "retry": "Nouvelle tentative…",
        "ck_test": "Vérifier les cookies", "ck_js_hint": "Avec les cookies, YouTube (et certains sites) demande Node.js ou Deno installé sur le PC (winget install DenoLand.Deno), puis redémarre l'appli. Sinon, choisis « Aucun » pour les cookies.", "ck_testing": "Test en cours…",
        "ck_ok": "{n} cookies trouvés", "ck_more": "Cliquez ici pour plus d'infos",
        "ck_dpapi": "Ce navigateur bloque la lecture de ses cookies (chiffrement). Utilise Firefox.",
        "ck_noyt": "Aucun cookie trouvé : connecte-toi à un site dans ce navigateur",
        "ck_fail": "Échec : {e}",
        "hist_btn": "Historique", "hist_title": "Historique des téléchargements",
        "hist_empty": "Aucun téléchargement pour l'instant.", "hist_open": "Ouvrir", "hist_folder": "Dossier",
        "hist_clear": "Vider l'historique", "hist_confirm": "Vider tout l'historique ?\n\nLes fichiers téléchargés ne sont pas supprimés.",
        "hist_missing": "fichier introuvable",
        "q_opts": "Options de la file", "q_sched": "Démarrer la file à", "q_after": "Quand la file est terminée",
        "q_after_none": "Ne rien faire", "q_after_sleep": "Mettre en veille", "q_after_shutdown": "Éteindre le PC",
        "q_save": "Enregistrer", "q_cancel": "Annuler", "q_sched_at": "Démarrage à {t}",
        "q_label_sleep": "Veille à la fin", "q_label_shutdown": "Extinction à la fin",
        "q_count_sleep": "Mise en veille du PC dans {n} s…", "q_count_shutdown": "Extinction du PC dans {n} s…",
        "q_count_title": "File terminée",
        "pl_pick_title": "Choisir les vidéos", "pl_ok": "Valider ({n})", "pick_btn": "Choisir les vidéos de la playlist", "pick_btn_n": "Vidéos choisies : {n}/{t}", "pl_pick_msg": "Playlist : {title}",
        "pl_all": "Tout cocher", "pl_none": "Tout décocher", "pl_add": "Ajouter ({n})", "pl_cancel": "Annuler",
        "dup_title": "Déjà téléchargé", "dup_msg": "« {name} » existe déjà dans ce dossier.\n\nLe télécharger à nouveau ?",
        "rename_title": "Renommer le fichier",
        "rename_prompt": "Nom du fichier (sans extension) :",
        "tip_rename": "Renommer le fichier",
        "tip_folder": "Dossier d'enregistrement :",
        "tip_link": "Copier le lien de la vidéo\n(Ctrl + clic : l'ouvrir dans le navigateur)",
        "tip_play": "Télécharger cette vidéo seulement",
        "tip_delete": "Retirer de la file",
        "tip_stop": "Mettre ce téléchargement en pause",
        "tip_open": "Ouvrir l'emplacement du fichier",
        "tip_trim": "Avec une découpe, le téléchargement peut prendre beaucoup plus de temps : "
                    "la partie choisie est recoupée et réencodée par ffmpeg.",
        "info_btn": "Infos",
        "tip_res": "Ressources utilisées par l'appli (et ffmpeg / deno qu'elle lance)",
        "info_title": "Infos",
        "info_ytdlp_body": "Cette interface est un habillage de yt-dlp : yt-dlp doit être "
                           "installé pour qu'elle fonctionne.",
        "info_ffmpeg_body": "ffmpeg est nécessaire pour le MP3, la découpe et les vidéos HD. "
                            "Relance l'appli après l'avoir installé.",
        "info_install": "Installer / mettre à jour :",
        "info_outdated": "mise à jour disponible ({v})",
        "info_uptodate": "à jour",
        "info_ffmpeg_site": "Site officiel de ffmpeg (ffmpeg.org)",
        "info_github": "GitHub de yt-dlp",
        "info_sites": "Liste des sites compatibles",
        "info_close": "Fermer",
        "tip_sites": "Cliquer pour voir les sites compatibles",
        "sites_title": "Sites compatibles",
        "sites_count": "{n} sites",
        "tip_theme_light": "Passer au thème clair",
        "tip_theme_dark": "Passer au thème sombre",
        "info_check": "Vérifier les mises à jour",
        "info_checking": "Vérification…",
        "info_update": "Mettre à jour",
        "app_body": "Cette application. La mise à jour télécharge le nouvel installeur depuis GitHub, l'installe et relance l'app.",
        "app_busy": "Des téléchargements sont en cours : attends qu'ils se terminent avant de mettre à jour.",
        "app_manual": "Mise à jour automatique disponible seulement avec la version installée. Télécharge la nouvelle version sur GitHub.",
        "app_github": "Page des versions (GitHub)",
        "upd_title": "Mise à jour disponible",
        "upd_msg": "La version {v} est disponible (tu as la {cur}). Veux-tu mettre à jour maintenant ?",
        "upd_notes": "Notes de mise à jour (GitHub)",
        "upd_now": "Mettre à jour", "upd_ignore": "Ignorer",
        "upd_ignore_tip": "Tu peux faire la mise à jour manuellement dans le menu Infos.",
        "info_updating": "Mise à jour… (patiente)",
        "info_updated_restart": "mis à jour — relance l'appli pour l'appliquer",
        "info_updated": "mis à jour",
        "info_upd_fail": "échec de la mise à jour",
        "info_ok": "installé",
        "info_missing": "introuvable",
        "bad_url": "✗ Lien non compatible avec yt-dlp (voir le « ? »)",
    },
    "en": {
        "title": "Another Video Downloader",
        "link": "Link",
        "load": "Load",
        "thumb": "thumbnail",
        "thumb_save": "Save image as…", "thumb_title": "Thumbnails",
        "video_title": "Video title",
        "length_ph": "Length",
        "date_ph": "Upload date",
        "length": "Length: {v}",
        "date": "Uploaded: {v}",
        "quality": "Quality",
        "trim": "Trim",
        "start": "start",
        "end": "end",
        "start_w": "start",
        "end_w": "end",
        "trim_suffix": " (trimmed)",
        "folder": "Folder…",
        "add": "Add to queue",
        "download": "Download",
        "queue": "Queue",
        "col_added": "#",
        "col_title": "Title",
        "col_length": "Length",
        "col_date": "Uploaded",
        "col_quality": "Quality",
        "col_trim": "Trim",
        "col_progress": "Progress",
        "dl_queue": "Download queue",
        "stop_queue": "Stop queue",
        "clear_queue": "Clear queue",
        "no_ffmpeg": "⚠ ffmpeg not found: trimming disabled — MP3 and HD may fail",
        "tip_trim_off": "Trimming unavailable: ffmpeg was not found (see Info).",
        "info_ytdlp_bundled": "yt-dlp is already included in this application, nothing to install.",
        "info_ffmpeg_bundled": "ffmpeg is already included in this application, nothing to install.",
        "lang_btn": "FR",
        "tip_settings": "Settings",
        "settings_title": "Settings",
        "set_lang": "Language",
        "set_theme": "Theme",
        "theme_dark": "☾  Dark",
        "theme_light": "☀  Light",
        "theme_sakura": "Sakura", "theme_cyberpunk": "Cyberpunk", "theme_hacker": "Hacker",
        "set_date": "Date format",
        "date_eu": "DD/MM/YYYY",
        "date_us": "MM/DD/YYYY",
        "date_iso": "YYYY-MM-DD",
        "est_size": "Estimated size: {v}",
        "est_time": "Estimated time: {v}",
        "est_unknown": "unknown",
        "est_nolimit": "depends on your connection",
        "unit_mb": "MB",
        "unit_gb": "GB",
        "set_speed": "Download speed limit",
        "speed_unit": "MB/s",
        "speed_or": "or",
        "pl_count": "Playlist: {n} videos",
        "trim_edit_title": "Edit trim", "trim_cancel": "Cancel",
        "tip_trim_edit": "Click to edit the trim",
        "set_close": "Close button (✕)",
        "set_compat": "Editing compatibility",
        "compat_edit": "Premiere-compatible (H.264 + AAC)", "compat_best": "Maximum quality (VP9/AV1 + Opus)",
        "compat_hint": "Premiere and other editors can't read VP9/AV1/Opus. Compatible mode picks H.264 + AAC "
                       "when YouTube offers it; otherwise (1440p, 4K…) the video is re-encoded automatically after the download (slower).",
        "set_live": "Live streams",
        "live_now": "From now on", "live_start": "From the start",
        "set_trimmode": "Trim", "trim_exact": "Exact", "trim_fast": "Fast",
        "trimmode_hint": "Exact: the chosen part is re-encoded, frame-accurate but slower. "
                         "Fast: cuts at the nearest keyframe without re-encoding (a few seconds of offset possible).",
        "live_hint": "\"From the start\" fetches the stream from its beginning when YouTube allows it "
                     "(experimental, heavier at startup).",
        "live_tag": "● LIVE",
        "live_cb": "From the start of the stream",
        "live_set": "Live: where recording starts",
        "live_short_start": "From start", "live_short_now": "From now",
        "stopping_live": "Stopping the live…", "finalizing": "Creating the MP4…",
        "tip_stop_live": "Stop and keep what is recorded",
        "live_fail": "Could not finalize the live recording",
        "close_quit": "Quit", "close_tray": "Minimize to the notification area",
        "close_need": "Needs the pystray module (pip install pystray).",
        "tray_open": "Open", "tray_quit": "Quit",
        "ctx_cut": "Cut", "ctx_copy": "Copy", "ctx_paste": "Paste", "ctx_all": "Select all",
        "tip_clear": "Clear the link",
        "speed_unlimited": "Unlimited",
        "set_name": "File names",
        "name_vars": "Variables:",
        "name_example": "Example: {v}",
        "name_default": "Reset file name to default",
        "settings_save": "Save",
        "views_word": "views",
        "sample_title": "My video",
        "sample_channel": "My channel",
        "best": "Best",
        "waiting": "Waiting",
        "starting": "Connecting…",
        "rec": "Recording", "merging": "Merging audio + video…", "audio_conv": "Converting to MP3…",
        "tip_logs": "Logs", "logs_title": "Logs", "log_copy": "Copy", "log_clear": "Clear",
        "log_copied": "Copied", "log_empty": "(empty)",
        "converting": "Converting…",
        "done": "Done ✓",
        "error": "Error ✗ (click)",
        "cancelled": "Stopped",
        "stopping": "Stopping…",
        "load_err": "Could not load the video",
        "playlist": "Playlists are not supported: paste a single video link.",
        "trim_title": "Trim",
        "trim_bad": "Start must be before end (and within the video).",
        "queue_title": "Queue",
        "queue_empty": "Nothing to download in the queue.",
        "dl_err": "Download error",
        "yes": "Yes", "no": "No", "toast_done": "Download complete", "toast_play": "Play",
        "vol": "Notification volume",
        "notif_style": "Popup style", "style_1": "Card", "style_2": "Strip", "style_3": "Vertical",
        "notif_test_err": "Test error sound",
        "notif_tone": "Sound", "tone_1": "Chime", "tone_2": "Snap", "tone_3": "Arpeggio", "tone_4": "Tri-tone",
        "notif_test": "Test notifications",
        "notif_sound": "Download finished sound", "notif_toast": "Popup notification",
        "notif_on": "On", "notif_off": "Off", "canceled": "Canceled",
        "tab_general": "General", "tab_dl": "Download", "tab_notif": "Notifications", "tab_adv": "Advanced",
        "set_codec": "Video codec", "codec_h264": "H.264 (Premiere)", "codec_best": "Max", "codec_vp9": "VP9", "codec_av1": "AV1",
        "codec_hint": "H.264: works in Premiere and most editors (re-encoded automatically if YouTube only has VP9/AV1/Opus). "
                      "Max: the best stream available, no conversion. VP9 / AV1: prefers that codec when it exists.",
        "dup_queue_title": "Already in the queue", "dup_queue_msg": "\"{name}\" is already in the queue.\n\nAdd it anyway?",
        "dup_hist_msg": "\"{name}\" was already downloaded on {date}.\n\nDownload it again?",
        "dup_tag_queue": "already in the queue", "dup_tag_hist": "already downloaded",
        "dup_pl_msg": "{n} video(s) of the playlist are already in the queue or already downloaded.\n\nSkip them?",
        "hist_search": "Search", "hist_sort_new": "Newest", "hist_sort_old": "Oldest", "hist_sort_name": "A–Z",
        "hist_none": "No result",
        "set_retry": "Automatic retry", "retry_off": "Off",
        "retry_hint": "Number of attempts after a network error.",
        "set_cookies": "Browser cookies", "cookies_none": "None",
        "cookies_why": "Some videos (private, 18+, members-only) only open when you are signed in. "
                       "Sign in to the video's site in Firefox and pick it here: the app uses your session, "
                       "only for those videos. Not needed for public videos.",
        "cookies_import_hint": "Chrome, Edge, Brave: export your cookies with an extension (“Get cookies.txt LOCALLY”), "
                               "then import the file. Your cookies stay on your PC: they are not shared, "
                               "and only sent to the video's own site.",
        "ck_sync_hint": "This video needs a sign-in (private, 18+, members…).\n"
                        "Add your cookies in Settings › Advanced.",
        "ck_import": "Import a cookies.txt", "ck_remove": "Remove",
        "ck_file_ok": "✔ File imported ({n} cookies)", "ck_file_bad": "✖ Invalid file (cookies.txt format expected)",
        "priv_title": "Privacy",
        "priv_body": "No data is collected, harvested, shared or sold. Everything (settings, queue, history) stays on your PC. "
                     "The app only contacts the video sites, and GitHub / PyPI to check for updates.",
        "retry": "Retrying…",
        "ck_test": "Check cookies", "ck_js_hint": "With cookies, YouTube (and some sites) needs Node.js or Deno installed on the PC (winget install DenoLand.Deno), then restart the app. Otherwise set cookies to None.", "ck_testing": "Testing…",
        "ck_ok": "{n} cookies found", "ck_more": "Click here for more info",
        "ck_dpapi": "This browser blocks reading its cookies (encryption). Use Firefox.",
        "ck_noyt": "No cookie found: sign in to a site in that browser",
        "ck_fail": "Failed: {e}",
        "hist_btn": "History", "hist_title": "Download history",
        "hist_empty": "No downloads yet.", "hist_open": "Open", "hist_folder": "Folder",
        "hist_clear": "Clear history", "hist_confirm": "Clear the whole history?\n\nDownloaded files are not deleted.",
        "hist_missing": "file not found",
        "q_opts": "Queue options", "q_sched": "Start the queue at", "q_after": "When the queue is finished",
        "q_after_none": "Do nothing", "q_after_sleep": "Sleep", "q_after_shutdown": "Shut down the PC",
        "q_save": "Save", "q_cancel": "Cancel", "q_sched_at": "Starts at {t}",
        "q_label_sleep": "Sleep when done", "q_label_shutdown": "Shut down when done",
        "q_count_sleep": "The PC goes to sleep in {n} s…", "q_count_shutdown": "The PC shuts down in {n} s…",
        "q_count_title": "Queue finished",
        "pl_pick_title": "Choose videos", "pl_ok": "Confirm ({n})", "pick_btn": "Choose playlist videos", "pick_btn_n": "Selected videos: {n}/{t}", "pl_pick_msg": "Playlist: {title}",
        "pl_all": "Select all", "pl_none": "Select none", "pl_add": "Add ({n})", "pl_cancel": "Cancel",
        "dup_title": "Already downloaded", "dup_msg": "\"{name}\" already exists in this folder.\n\nDownload it again?",
        "rename_title": "Rename file",
        "rename_prompt": "File name (without extension):",
        "tip_rename": "Rename file",
        "tip_folder": "Save folder:",
        "tip_link": "Copy the video link\n(Ctrl + click: open it in the browser)",
        "tip_play": "Download this video only",
        "tip_delete": "Remove from queue",
        "tip_stop": "Pause this download",
        "tip_open": "Show file location",
        "tip_trim": "Trimming can make the download take much longer: "
                    "the selected part is cut and re-encoded by ffmpeg.",
        "info_btn": "Info",
        "tip_res": "Resources used by the app (and the ffmpeg / deno it starts)",
        "info_title": "Info",
        "info_ytdlp_body": "This interface is a front-end for yt-dlp: yt-dlp must be "
                           "installed for it to work.",
        "info_ffmpeg_body": "ffmpeg is required for MP3, trimming and HD videos. "
                            "Restart the app after installing it.",
        "info_install": "Install / update:",
        "info_outdated": "update available ({v})",
        "info_uptodate": "up to date",
        "info_ffmpeg_site": "Official ffmpeg website (ffmpeg.org)",
        "info_github": "yt-dlp on GitHub",
        "info_sites": "List of supported sites",
        "info_close": "Close",
        "tip_sites": "Click to see the compatible sites",
        "sites_title": "Compatible sites",
        "sites_count": "{n} sites",
        "tip_theme_light": "Switch to light theme",
        "tip_theme_dark": "Switch to dark theme",
        "info_check": "Check for updates",
        "info_checking": "Checking…",
        "info_update": "Update",
        "app_body": "This application. Updating downloads the new installer from GitHub, installs it and restarts the app.",
        "app_busy": "Downloads are running: wait for them to finish before updating.",
        "app_manual": "Automatic update is only available with the installed version. Download the new version from GitHub.",
        "app_github": "Releases page (GitHub)",
        "upd_title": "Update available",
        "upd_msg": "Version {v} is available (you have {cur}). Update now?",
        "upd_notes": "Release notes (GitHub)",
        "upd_now": "Update now", "upd_ignore": "Ignore",
        "upd_ignore_tip": "You can update manually from the Info menu.",
        "info_updating": "Updating… (please wait)",
        "info_updated_restart": "updated — restart the app to apply",
        "info_updated": "updated",
        "info_upd_fail": "update failed",
        "info_ok": "installed",
        "info_missing": "not found",
        "bad_url": "✗ Link not supported by yt-dlp (see the “?”)",
    },
}


def tr(key, **kw):
    s = T[LANG][key]
    return s.format(**kw) if kw else s


# -------------------------------------------------------------------- helpers
MEDIA_EXT = {".mp4", ".mkv", ".webm", ".mp3", ".m4a", ".opus", ".mov", ".flv", ".avi", ".ogg", ".wav", ".aac"}


def existing_media(outdir, base):
    """Path of a finished file called `base` (any media extension) in outdir, else None."""
    try:
        for f in os.listdir(outdir):
            stem, ext = os.path.splitext(f)
            if stem == base and ext.lower() in MEDIA_EXT:
                return os.path.join(outdir, f)
    except OSError:
        pass
    return None


def free_name(outdir, base):
    """'name' -> 'name - 2', 'name - 3'... the first one not downloaded yet."""
    n = 2
    while existing_media(outdir, f"{base} - {n}"):
        n += 1
    return f"{base} - {n}"


class Declined(Exception):
    """The file already exists and the user does not want a second copy."""


class Cancelled(Exception):
    """Raised from yt-dlp hooks to abort a download."""


class SlowRestart(Exception):
    """Raised from the progress hook when YouTube throttles the connection: reconnect and resume."""


class NotAVideo(Exception):
    pass


def fmt_duration(sec):
    sec = int(sec or 0)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_hms(sec):
    """5991 -> '1h 39m 51s' (hours / minutes shown only when needed)."""
    sec = int(sec or 0)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}h {m:02d}m {s:02d}s" if h else (f"{m}m {s:02d}s" if m else f"{s}s")


DATE_FMT = "eu"                      # "eu" DD/MM/YYYY, "us" MM/DD/YYYY, "iso" YYYY-MM-DD
NAME_TPL = "{title} - {channel}"     # default file name; {title} {channel} {length} {date}
DEFAULT_TPL = NAME_TPL
SPEED_LIMIT = 0.0                    # speed limit really applied, MB/s (0 = unlimited)
SPEED_VALUE = 0.0                    # limit typed in the settings (kept even when "unlimited" is chosen)
SPEED_UNLIM = False                  # "unlimited" chosen: the typed limit is kept but not applied
VIDEO_CODEC = "h264"                 # h264 (editing-friendly) / best / vp9 / av1
AUTO_RETRY = 2                       # attempts after a network error
COOKIES_BROWSER = ""                 # browser whose cookies yt-dlp uses ("" = none)
COMPAT_EDIT = True                   # prefer H.264 + AAC (opens in Premiere & co)
FAST_TRIM = True                     # trim: cut at keyframes without re-encoding (fast) instead of frame-accurate
LIVE_FROM_START = False              # live streams: record from the very start (yt-dlp --live-from-start)
NOTIFY_SOUND = True                  # sound when a download is finished
NOTIFY_VOL = 80                      # volume (0-100) of the "finished" sound
NOTIFY_STYLE = 1                     # look of the popup (1 card, 2 strip, 3 solid)
NOTIFY_TONE = 1                      # which of the 3 sounds
NOTIFY_TOAST = True                  # popup (bottom right) when a download is finished
TRAY = False                         # the window's cross hides the app in the tray instead of quitting


RECENT_DL = []          # (MB/s, MB) of the last downloaded files, for the diagnostic log
_LAST_LIMIT = [None]


def apply_speed():
    global SPEED_LIMIT
    SPEED_LIMIT = 0.0 if (SPEED_UNLIM or SPEED_VALUE <= 0) else SPEED_VALUE
    if _LAST_LIMIT[0] is not None and _LAST_LIMIT[0] != SPEED_LIMIT:
        old, new = _LAST_LIMIT[0], SPEED_LIMIT
        log(f"speed limit changed: {'unlimited' if old <= 0 else f'{old:g} MB/s'} -> "
            f"{'unlimited' if new <= 0 else f'{new:g} MB/s'} (typed value={SPEED_VALUE:g}, unlimited button={SPEED_UNLIM})")
    _LAST_LIMIT[0] = SPEED_LIMIT


def recent_avg(n=5):
    """Average speed of the last n files (MB/s), '' when nothing yet."""
    last = RECENT_DL[-n:]
    if not last:
        return ""
    return f"average of last {len(last)} download(s): {sum(v for v, _ in last) / len(last):.2f} MB/s " \
           f"(" + ", ".join(f"{v:.1f}" for v, _ in last) + ")"


def fmt_date(d, sep=None):
    """'20261103' -> '03/11/2026' (or per the chosen format); `sep` forces the separator."""
    if d and len(d) == 8 and d.isdigit():
        y, m, day = d[:4], d[4:6], d[6:]
        parts = {"eu": (day, m, y), "us": (m, day, y), "iso": (y, m, day)}.get(DATE_FMT, (day, m, y))
        return (sep or ("-" if DATE_FMT == "iso" else "/")).join(parts)
    return d or "?"


def clean_name(s):
    """Removes emojis and characters that cause trouble in file names (Windows-forbidden ones, symbols)."""
    import unicodedata
    out = []
    for ch in s or "":
        cat = unicodedata.category(ch)
        if ch in "<>\"*?\x00" or cat in ("So", "Sk", "Cs", "Co", "Cn", "Cc", "Cf") or ch in "︎️":
            continue
        out.append(" - " if ch in ":/\\|" else ch)
    s = "".join(out)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"(\s*-\s*){2,}", " - ", s)      # no doubled separators left by removed characters
    return s.strip(" .-")


def estimate_sizes(info, keys):
    """Estimated download size in bytes for each quality key ('1080p', 'best', 'mp3')."""
    dur = info.get("duration") or 0
    fmts = info.get("formats") or []

    def size(f):
        s = f.get("filesize") or f.get("filesize_approx")
        if not s and f.get("tbr") and dur:
            s = f["tbr"] * 1000 / 8 * dur           # tbr is in kbit/s
        return s or 0

    def has(f, kind):
        return f.get(kind) not in (None, "none")

    audio = [f for f in fmts if has(f, "acodec") and not has(f, "vcodec")]
    best_audio = max(audio, key=lambda f: f.get("abr") or f.get("tbr") or 0, default=None)
    a_size = size(best_audio) if best_audio else 0
    videos = [f for f in fmts if has(f, "vcodec") and f.get("height")]
    out = {}
    for k in keys:
        if k == "mp3":
            out[k] = dur * 192 * 1000 / 8           # re-encoded at 192 kbit/s
            continue
        pool = videos if k == "best" else [f for f in videos if f["height"] <= int(k[:-1])]
        if not pool:
            out[k] = 0
            continue
        top = max(f["height"] for f in pool)
        cand = sorted((f for f in pool if f["height"] == top), key=lambda f: f.get("tbr") or 0)
        v = cand[len(cand) // 2]                    # middle one: codecs differ a lot in size
        out[k] = size(v) + (0 if has(v, "acodec") else a_size)
    return out


def fmt_size(b):
    mb = b / 1048576
    if mb >= 1024:
        return f"~{mb / 1024:.1f} {tr('unit_gb')}"
    return f"~{mb:.0f} {tr('unit_mb')}" if mb >= 10 else f"~{mb:.1f} {tr('unit_mb')}"


def fmt_eta(sec):
    sec = int(round(sec))
    if sec < 1:
        return "< 1 s"
    if sec < 60:
        return f"~{sec} s"
    if sec < 3600:
        return f"~{sec // 60} min {sec % 60:02d} s"
    return f"~{sec // 3600} h {sec % 3600 // 60:02d} min"


def fmt_left(sec):
    """Compact remaining time for the queue rows: '45 s', '3:05', '1:02:10'."""
    sec = max(0, int(round(sec)))
    if sec < 60:
        return f"{sec} s"
    if sec < 3600:
        return f"{sec // 60}:{sec % 60:02d}"
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def fmt_views(n):
    """12345 -> '12.3K' (from 10 000), 1234567 -> '1.2M' (from 1 million), below: the plain number."""
    if n is None:
        return ""
    n = int(n)
    if n >= 1_000_000:
        return f"{n // 100_000 / 10:g}M"
    if n >= 10_000:
        return f"{n // 100 / 10:g}K"
    return str(n)


def make_name(info, tpl=None):
    """File name from the template ({title} {channel} {length} {date}), cleaned for the file system."""
    tpl = NAME_TPL if tpl is None else tpl
    secs = info.get("duration") or 0
    h, r = divmod(int(secs), 3600)
    m, s = divmod(r, 60)
    vals = {
        "title": info.get("title") or "",
        "channel": info.get("channel") or "",
        "length": (f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s") if secs else "",
        "date": fmt_date(info.get("date_raw"), sep="-") if info.get("date_raw") else "",
        "views": (fmt_views(info["view_count"]) + " "
                  + (tr("views_word")[:-1] if info["view_count"] == 1 else tr("views_word")))
                 if info.get("view_count") is not None else "",
    }
    name = re.sub(r"\{(\w+)\}", lambda mo: vals.get(mo.group(1), mo.group(0)), tpl or DEFAULT_TPL)
    return clean_name(name) or clean_name(vals["title"]) or "video"


def _quality_rank(q):
    if q.endswith("p") and q[:-1].isdigit():
        return int(q[:-1])
    return 10**6 if q == "best" else 0  # mp3 lowest, "best" highest


# queue column -> sort key (title, length, date, quality)
_ADDED = [0]


def next_added():
    """Order of addition (the '#' column sorts on it; the number itself is never shown)."""
    _ADDED[0] += 1
    return _ADDED[0]


SORT_KEYS = {
    0: lambda it: it.get("added", 0),
    1: lambda it: it["name"].casefold(),
    2: lambda it: it["duration"] or 0,
    3: lambda it: it.get("date_raw", ""),
    4: lambda it: _quality_rank(it["quality"]),
}


def trim_text(start, end):
    if start is None and end is None:
        return "—"
    a = fmt_duration(start) if start is not None else tr("start_w")
    b = fmt_duration(end) if end is not None else tr("end_w")
    return f"{a} → {b}"


def qlabel(key):
    """Display text of a quality key ('1080p', 'best', 'mp3')."""
    return {"mp3": "MP3 (audio)", "best": tr("best")}.get(key, key)


def qshort(key):
    """Short quality text for the queue rows."""
    return {"mp3": "MP3", "best": tr("best")}.get(key, key)


def fit_text(text, font, px):
    """Truncate `text` with an ellipsis so it is at most `px` pixels wide."""
    if font.measure(text) <= px:
        return text
    lo, hi = 0, len(text)                      # largest n such that text[:n] + "…" still fits (binary search)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.measure(text[:mid] + "…") <= px:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + "…"


def clean(msg):
    return ANSI.sub("", msg).strip()


# Windows: Chromium browsers (Chrome, Edge, Brave, Opera, Vivaldi) lock their cookies, only Firefox can be read
COOKIE_BROWSERS = (("firefox", "Firefox"),) if sys.platform.startswith("win") else (
    ("chrome", "Chrome"), ("edge", "Edge"), ("firefox", "Firefox"), ("brave", "Brave"), ("opera", "Opera"),
    ("vivaldi", "Vivaldi"))


def js_runtime_opts():
    """With cookies YouTube needs a JavaScript runtime (Deno / Node.js ...) to unlock the formats.
    yt-dlp only looks for Deno by default, so every runtime found on the PC is handed to it."""
    found = {}
    for name in ("deno", "node", "bun"):
        path = shutil.which(name)
        if path:
            found[name] = {"path": path}
    return {"js_runtimes": found} if found else {}


_COOKIES = {}                       # browser -> cookies read once (reading + decrypting them takes seconds)
_COOKIES_LOCK = threading.Lock()


def cached_cookies(browser, force=False):
    """The browser's cookies, read once and kept: loading a video no longer re-reads the whole cookie store."""
    with _COOKIES_LOCK:
        if force or browser not in _COOKIES:
            from yt_dlp.cookies import extract_cookies_from_browser
            _COOKIES[browser] = list(extract_cookies_from_browser(browser))
        return _COOKIES[browser]


def cookies_file_path():
    """Copy of the cookies.txt the user imported (kept in the app's own folder, never sent anywhere)."""
    return os.path.join(app_data_dir(), "cookies.txt")


def count_cookies_file(path):
    """Number of cookies in a Netscape-format cookies.txt (0 = not a valid file)."""
    n = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#HttpOnly_"):
                    line = line[len("#HttpOnly_"):]
                if line and not line.startswith("#") and len(line.split("\t")) >= 7:
                    n += 1
    except OSError:
        return 0
    return n


def cookies_available():
    return bool(COOKIES_BROWSER) or os.path.exists(cookies_file_path())


def apply_cookies(ydl):
    if os.path.exists(cookies_file_path()):            # an imported file comes first
        try:
            ydl.cookiejar.load(cookies_file_path(), ignore_discard=True, ignore_expires=True)
        except Exception as ce:
            raise RuntimeError(tr("ck_sync_hint")) from ce
        return
    if COOKIES_BROWSER:
        try:
            cookies = cached_cookies(COOKIES_BROWSER, force=True)     # re-read: you may have signed in since
        except Exception as ce:                  # browser open / not installed / not readable
            log("cookies unreadable: " + clean(str(ce)), "warning")
            raise RuntimeError(tr("ck_sync_hint")) from ce
        for c in cookies:
            ydl.cookiejar.set_cookie(c)


LOGIN_WORDS = ("sign in", "log in", "login", "private", "members", "age-restricted", "confirm your age",
               "not a bot", "cookies", "join this channel", "premium", "requires payment")


def needs_login(msg):
    """True when the error means the video needs the signed-in session (so cookies are worth their cost)."""
    m = str(msg).lower()
    return any(w in m for w in LOGIN_WORDS)


LOGIN_AVAIL = ("needs_auth", "subscriber_only", "premium_only", "private")


def cookie_hint(msg):
    """Adds the explanation of what to do when a video needs a signed-in session or cookies are missing."""
    if tr("ck_sync_hint") in msg:
        return msg
    if needs_login(msg):
        log("login needed: " + msg, "info")
        return tr("ck_sync_hint")                      # short and clear instead of the raw yt-dlp text
    if COOKIES_BROWSER and "format is not available" in msg:
        return msg + "\n\n" + tr("ck_js_hint")
    return msg


LOG = []                      # (time, level, text) - shown by the Logs window
LOG_LOCK = threading.Lock()


LOG_FILE_ON = [False]         # the log file is used once the session has started (see init_log_file)
LOG_KEEP = 3000


def log_file_path():
    return os.path.join(app_data_dir(), "logs.txt")


def log(msg, level="info"):
    """Adds a line to the in-app log (thread-safe, capped) and to the log file (kept between sessions)."""
    with LOG_LOCK:
        out = []
        for line in str(msg).splitlines() or [""]:
            line = line[:800]
            LOG.append((time.strftime("%H:%M:%S"), level, line))
            out.append(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{level}\t{line}\n")
        del LOG[:-LOG_KEEP]
        if LOG_FILE_ON[0]:
            try:
                with open(log_file_path(), "a", encoding="utf-8") as f:
                    f.writelines(out)
            except OSError:
                pass


def init_log_file():
    """Loads the previous sessions' logs into the Logs window, notes whether the last session ended cleanly
    (no 'closed' line = crash / kill), brings back what Python's crash handler wrote, and starts the session."""
    path = log_file_path()
    lines, today = [], time.strftime("%Y-%m-%d")
    try:
        os.makedirs(app_data_dir(), exist_ok=True)
        if os.path.exists(path):
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            if len(lines) > 20000:                         # the file stays small: last 20000 lines
                lines = lines[-20000:]
                with open(path, "w", encoding="utf-8") as f:
                    f.writelines(lines)
    except OSError:
        lines = []
    with LOG_LOCK:
        for ln in lines[-LOG_KEEP:]:
            parts = ln.rstrip("\n").split("\t", 2)
            if len(parts) == 3:
                day, _, hms = parts[0].partition(" ")
                ts = hms if day == today else f"{day[8:10]}/{day[5:7]} {hms}"
                LOG.append((ts, parts[1], parts[2]))
    LOG_FILE_ON[0] = True
    last = next((ln for ln in reversed(lines) if "===== app " in ln), "")      # last open / close marker
    crashed = bool(last) and "===== app closed" not in last
    if crashed:
        last = next((ln for ln in reversed(lines) if ln.strip()), "")
    log(f"===== app opened (v{APP_VERSION}, pid {os.getpid()}) =====")
    if crashed:
        log("previous session did not end cleanly (crash, kill or power cut): last line was -> "
            + last.rstrip("\n").replace("\t", " ")[:300], "warning")
    crash = os.path.join(app_data_dir(), "crash.txt")      # written by faulthandler when Python itself dies
    try:
        if os.path.exists(crash) and os.path.getsize(crash) > 0:
            with open(crash, encoding="utf-8", errors="replace") as f:
                log("crash report of the previous session:\n" + f.read(), "error")
        import faulthandler
        _fh = open(crash, "w", encoding="utf-8")
        faulthandler.enable(_fh, all_threads=True)
        globals()["_FAULT_FILE"] = _fh
    except Exception:
        pass

    def _hook(et, ev, tb):
        log("uncaught error: " + "".join(traceback.format_exception(et, ev, tb)), "error")
    sys.excepthook = _hook
    try:
        threading.excepthook = lambda a: log("uncaught error in thread " + str(getattr(a.thread, "name", "?")) + ": "
                                             + "".join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback)), "error")
    except Exception:
        pass


class QuietLogger:
    """Nothing is printed (no console in the windowed build): yt-dlp's output goes to the Logs window."""
    _progress = re.compile(r"^\[download\]\s+[\d.]+%|^\[download\]\s+(Got|Destination)?\s*$")

    def __init__(self, on_line=None):
        self.on_line = on_line

    _ansi = re.compile(r"\x1b\[[0-9;]*m")

    def debug(self, msg):
        if self.on_line:
            self.on_line(msg)
        clean_msg = self._ansi.sub("", msg).strip()                     # colour codes hid the progress lines
        if not self._progress.match(clean_msg) and "File locking is not supported" not in clean_msg:
            log(msg, "debug")

    def info(self, msg):
        self.debug(msg)

    def warning(self, msg):
        log(msg, "warning")

    def error(self, msg):
        log(msg, "error")


PROCS = []                   # (thread id, Popen) of the programs yt-dlp launches (ffmpeg downloads)


def track_processes():
    """Remembers yt-dlp's child processes so a stopped live can end its ffmpeg cleanly."""
    try:
        orig = yt_dlp.utils.Popen.__init__

        def init(self, *a, **k):
            orig(self, *a, **k)
            with LOG_LOCK:
                PROCS[:] = [x for x in PROCS if x[1].poll() is None] + [(threading.get_ident(), self)]
        yt_dlp.utils.Popen.__init__ = init
    except Exception as e:
        log(f"cannot track processes: {e}", "warning")


def stop_processes(tid, hard=False):
    """Asks the ffmpeg of this download thread to stop ('q' = clean end of file); hard = kill."""
    with LOG_LOCK:
        procs = [pr for t, pr in PROCS if t == tid and pr.poll() is None]
    for pr in procs:
        try:
            if hard:
                pr.kill()
            else:
                pr.stdin.write(b"q")
                pr.stdin.flush()
            log(f"{'kill' if hard else 'quit signal sent to'} process {pr.pid}")
        except Exception as e:
            log(f"stop process {pr.pid}: {e}", "warning")
            try:
                pr.kill()
            except Exception:
                pass


TEMP_DIRNAME = ".avd-temp"


def video_key(url):
    """Short id of a video, used in the name of its work folder (two downloads never share one)."""
    m = re.search(r"(?:[?&]v=|youtu\.be/|/shorts/|/live/|/embed/)([\w-]{6,})", url or "")
    if m:
        return m.group(1)
    import hashlib
    return hashlib.md5(norm_url(url or "").encode("utf-8", "ignore")).hexdigest()[:10]


def tmp_dir(outdir, key=None):
    """Hidden sub-folder where yt-dlp keeps its work files (.part, fragments, .temp. conversions) until a
    download is finished: the chosen folder stays clean meanwhile. One folder per video."""
    return os.path.join(outdir, TEMP_DIRNAME + ("-" + key if key else ""))


def make_tmp_dir(outdir, key=None):
    path = tmp_dir(outdir, key)
    try:
        os.makedirs(path, exist_ok=True)
        if sys.platform.startswith("win"):
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(path, 0x2)      # hidden
    except Exception:
        pass
    return path


def all_tmp_dirs(outdir):
    try:
        return [os.path.join(outdir, n) for n in os.listdir(outdir)
                if n.startswith(TEMP_DIRNAME) and os.path.isdir(os.path.join(outdir, n))]
    except OSError:
        return []


def drop_tmp_dir(outdir, key=None):
    """Removes the work folder(s) once empty (a paused download keeps its files there)."""
    for d in ([tmp_dir(outdir, key)] if key else all_tmp_dirs(outdir)):
        try:
            os.rmdir(d)
        except OSError:
            pass


def work_dirs(outdir):
    return [d for d in [outdir] + all_tmp_dirs(outdir) if d and os.path.isdir(d)]


def watch_conversion(app, it, outdir, name, key, info, stop):
    """yt-dlp reports nothing while ffmpeg converts: follow the growth of the temporary output file."""
    stop.clear()

    def size(p):
        try:
            return os.path.getsize(p)
        except OSError:
            return 0
    if name == "Merger":
        expected = sum(size(f.get("filepath") or "") for f in info.get("requested_formats") or [])
    elif name == "FFmpegExtractAudio":
        expected = (info.get("duration") or 0) * 192000 / 8          # 192 kb/s MP3
    else:
        expected = size(info.get("filepath") or info.get("_filename") or "")
    if expected <= 0 and it.get("final_base"):       # e.g. FixupM3u8: the file being repaired sits in the work folder
        base = os.path.basename(it["final_base"]) + "."
        try:
            expected = max([size(os.path.join(d, f)) for d in work_dirs(outdir) for f in os.listdir(d)
                            if f.startswith(base) and ".temp." not in f and not f.endswith((".part", ".ytdl"))] or [0])
        except (OSError, ValueError):
            expected = 0
    if expected <= 0:
        return                                    # unknown total: the bar keeps its text only
    t0 = time.time() - 2

    def run():
        while not stop.is_set() and it["status"] == "running":
            try:
                cands = [os.path.join(d, f) for d in work_dirs(outdir) for f in os.listdir(d) if ".temp." in f]
                cands = [c for c in cands if os.path.getmtime(c) >= t0]
            except (OSError, ValueError):
                cands = []
            try:
                if cands:
                    pct = min(99.0, max(size(c) for c in cands) / expected * 100)
                    app.events.put(("conv", it, key, pct))
            except Exception:
                pass                              # file vanished (conversion finished)
            stop.wait(0.4)
    threading.Thread(target=run, daemon=True).start()


_CHIME = {}
BELL = [(1, 1.0), (2.76, 0.45), (5.4, 0.2)]          # partials of a bell (not harmonic)
SOFT = [(1, 1.0), (2, 0.3)]
GLASS = [(1, 1.0), (4, 0.14), (6.3, 0.06)]
TONES = {                                            # (frequency, seconds, partials, decay)
    1: [(988.0, 0.11, SOFT, 4.5), (1318.5, 0.42, SOFT, 4.5)],                       # chime: two notes
    2: [(392.0, 0.11, SOFT, 6.0), (523.3, 0.34, SOFT, 5.5)],                        # "Snap": lower, soft two-note pop
    3: [(784.0, 0.09, SOFT, 3.0), (988.0, 0.09, SOFT, 3.0), (1175.0, 0.09, SOFT, 3.0),
        (1568.0, 0.40, SOFT, 4.5)],                                                 # quick rising arpeggio
    4: [(1319.0, 0.10, GLASS, 5.0), (1568.0, 0.10, GLASS, 5.0), (1976.0, 0.50, GLASS, 4.0)],   # glassy "tri-tone" plinks
}


BUZZ = [(1, 1.0), (3, 0.33), (5, 0.2)]
ERROR_NOTES = [(311.0, 0.13, BUZZ, 4.0), (233.0, 0.36, BUZZ, 4.0)]     # one low descending buzz for every error


def _play(key, notes, vol):
    """Plays a generated sound at a volume 0-100 (Windows; the WAV is written once per sound + volume)."""
    if not sys.platform.startswith("win") or vol <= 0:
        return
    try:
        import winsound
        path = os.path.join(tempfile.gettempdir(), f"justayt_{key}_{int(vol)}.wav")   # SND_MEMORY can't be async
        if not os.path.exists(path):
            import struct
            import wave
            gain = (vol / 100) ** 1.5 * 0.55
            rate, out = 44100, bytearray()
            for freq, dur, parts, decay in notes:
                n = int(rate * dur)
                norm = sum(a for _, a in parts)
                for i in range(n):
                    env = min(1.0, i / 300) * math.exp(-decay * i / n)
                    v = sum(a * math.sin(2 * math.pi * freq * r * i / rate) for r, a in parts) / norm * env
                    out += struct.pack("<h", int(max(-1, min(1, v * gain)) * 32767))
            with wave.open(path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(bytes(out))
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
    except Exception:
        log("sound failed: " + traceback.format_exc(), "warning")


def play_chime(tone=None, vol=None):
    """Download finished."""
    tone = tone or NOTIFY_TONE
    _play(f"tone{tone}", TONES.get(tone, TONES[1]), NOTIFY_VOL if vol is None else vol)


def play_error(vol=None):
    """Same sound for every error."""
    _play("error", ERROR_NOTES, NOTIFY_VOL if vol is None else vol)


class ThemeChip(tk.Canvas):
    """Theme button painted with that theme's own colours (a small preview); outlined when it is the active one."""

    def __init__(self, master, text, name, selected, command):
        pal = PALETTES[name]
        f = tkfont.Font(family=FONT, size=10, weight=heavy(name))
        w, h = f.measure(text) + 46, 32
        super().__init__(master, width=w, height=h, bg=master.cget("bg"), highlightthickness=0, cursor="hand2")
        r = 10
        pts = [r, 0, w - r, 0, w, 0, w, r, w, h - r, w, h, w - r, h, r, h, 0, h, 0, h - r, 0, r, 0, 0]
        self.create_polygon(pts, smooth=True, fill=pal["CARD2"], outline=pal["ACCENT"] if selected else pal["BORDER"],
                            width=2)
        self.create_oval(12, h / 2 - 5, 22, h / 2 + 5, fill=pal["ACCENT"], outline=pal["ACCENT"])
        self.create_text(30, h / 2, text=text, anchor="w", fill=pal["FG"], font=(FONT, 10, heavy(name)))
        self.bind("<ButtonRelease-1>", lambda e: command())


class Slider(tk.Canvas):
    """Flat horizontal slider 0-100 in the app's colours: on_change(v) while dragging, on_release(v) at the end."""

    def __init__(self, master, value, on_change, on_release, width=240):
        super().__init__(master, width=width, height=26, bg=master.cget("bg"), highlightthickness=0, cursor="hand2")
        self.w, self.value, self.on_change, self.on_release = width, int(value), on_change, on_release
        self.bind("<Button-1>", self._set)
        self.bind("<B1-Motion>", self._set)
        self.bind("<ButtonRelease-1>", lambda e: self.on_release(self.value))
        self._draw()

    def _set(self, e):
        v = int(round(min(max((e.x - 10) / (self.w - 20), 0), 1) * 100))
        if v != self.value:
            self.value = v
            self._draw()
            self.on_change(v)

    def _draw(self):
        self.delete("all")
        x = 10 + (self.w - 20) * self.value / 100
        self.create_line(10, 13, self.w - 10, 13, fill=CARD2, width=6, capstyle="round")
        if self.value > 0:
            self.create_line(10, 13, x, 13, fill=ACCENT, width=6, capstyle="round")
        self.create_oval(x - 8, 5, x + 8, 21, fill="#ffffff", outline=ACCENT, width=2)


def mix_color(c1, c2, t):
    """Blend of two #rrggbb colors (t = 0 -> c1, 1 -> c2)."""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


class ForceStop(BaseException):
    """Injected in a download thread that ignores the stop request (not an Exception: yt-dlp can't swallow it)."""


def url_start_seconds(url):
    """Start time carried by a link (?t=90, &t=1m30s, &start=90, #t=1h2m3s), else None."""
    try:
        u = urlparse(url)
        q = parse_qs(u.query)
        q.update(parse_qs(u.fragment))
        raw = (q.get("t") or q.get("start") or [""])[0].strip().lower()
    except Exception:
        return None
    if re.fullmatch(r"\d+s?", raw):
        return int(raw.rstrip("s"))
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", raw)
    if m and any(m.groups()):
        h, mi, sec = (int(g or 0) for g in m.groups())
        return h * 3600 + mi * 60 + sec
    return None


def normalize_url(url):
    u = url.strip()
    if re.match(r"^[a-z][a-z0-9+.-]*://", u, re.I):
        return u
    if u and " " not in u and "." in u:
        return "https://" + u
    return u


_EXTRACTORS = None


def is_supported(url):
    """True if a dedicated yt-dlp extractor (a site of supportedsites.md) accepts the URL."""
    global _EXTRACTORS
    if not re.match(r"^https?://[^\s/]+", url, re.I):
        return False
    try:
        if _EXTRACTORS is None:
            from yt_dlp.extractor import gen_extractor_classes
            _EXTRACTORS = [ie for ie in gen_extractor_classes() if ie.ie_key() != "Generic"]
        return any(ie.suitable(url) for ie in _EXTRACTORS)
    except Exception:
        return True  # never block the user because of an internal problem


_SITES = None


def supported_sites():
    """Sorted names of the sites yt-dlp has a dedicated extractor for (like supportedsites.md)."""
    global _SITES
    if _SITES is None:
        names = set()
        try:
            from yt_dlp.extractor import gen_extractor_classes
            for ie in gen_extractor_classes():
                if ie.ie_key() == "Generic" or getattr(ie, "IE_DESC", None) is False:
                    continue
                names.add(ie.IE_NAME.split(":")[0])  # "youtube:tab" -> "youtube"
        except Exception:
            pass
        _SITES = sorted((n for n in names if n), key=str.casefold)
    return _SITES


def has_ffmpeg():
    return shutil.which("ffmpeg") is not None


def bundled_ffmpeg():
    """True in the .exe build when ffmpeg was packed inside it."""
    base = getattr(sys, "_MEIPASS", None)
    return bool(base) and os.path.exists(os.path.join(base, "ffmpeg.exe"))


def settings_path():
    return os.path.join(app_data_dir(), "settings.json")


def load_settings():
    try:
        with open(settings_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(**kw):
    """Keeps small preferences (like the download folder) between two launches."""
    data = load_settings()
    data.update(kw)
    try:
        path = settings_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


QUEUE_KEYS = ("url", "title", "channel", "view_count", "duration", "upload_date", "date_raw", "name", "custom",
              "trimmed", "start", "end", "quality", "qualities", "outdir", "is_live", "live_from_start", "no_trim",
              "pl_color", "playlist", "thumb_url", "sizes", "started", "final_base", "filepath", "added")


def queue_path():
    return os.path.join(app_data_dir(), "queue.json")


def history_path():
    return os.path.join(app_data_dir(), "history.json")


def load_history():
    try:
        with open(history_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_history(data):
    try:
        path = history_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data[:300], f, ensure_ascii=False)
    except Exception:
        pass


def norm_url(u):
    """Same video = same key (YouTube: the video id, whatever the link looks like)."""
    u = (u or "").strip()
    try:
        from urllib.parse import urlparse, parse_qs
        p_ = urlparse(u)
        host = p_.netloc.lower()
        if "youtu.be" in host:
            return "yt:" + p_.path.strip("/")
        if "youtube" in host:
            v = parse_qs(p_.query).get("v")
            if v:
                return "yt:" + v[0]
            if p_.path.startswith(("/shorts/", "/live/", "/embed/")):
                return "yt:" + p_.path.split("/")[2]
    except Exception:
        pass
    return u.split("#")[0].rstrip("/")


def add_history(item):
    """Newest first, 300 entries at most (history.json next to the settings)."""
    path = item.get("filepath")
    if not path:
        return
    data = [e for e in load_history() if e.get("path") != path]
    data.insert(0, {"title": item.get("name") or os.path.basename(path), "path": path, "url": item.get("url") or "",
                    "date": time.strftime("%Y-%m-%d %H:%M"), "quality": item.get("quality") or ""})
    save_history(data)


def item_to_json(it):
    d = {k: it[k] for k in QUEUE_KEYS if k in it}
    st = it["status"]
    d["status"] = {"running": "cancelled", "error": "waiting"}.get(st, st)   # a run cut by quitting = paused
    if st == "running":
        d["started"] = True
    d["made"] = sorted(it.get("made") or ())
    part = it.get("partial")
    if part:
        d["partial"] = [part[0], sorted(part[1]), sorted(part[2])]
    row = it.get("row")
    d["last_pct"] = getattr(row, "last_pct", 0.0) if row is not None else 0.0
    if it.get("thumb") is not None:
        if "_thumb_b64" not in it:
            import base64
            buf = io.BytesIO()
            it["thumb"].convert("RGB").resize((128, 72), Image.Resampling.LANCZOS).save(buf, "JPEG", quality=82)
            it["_thumb_b64"] = base64.b64encode(buf.getvalue()).decode()
        d["thumb"] = it["_thumb_b64"]
    return d


def item_from_json(d):
    it = {k: v for k, v in d.items() if k not in ("thumb", "made", "partial", "last_pct")}
    if d.get("thumb"):
        try:
            import base64
            it["thumb"] = Image.open(io.BytesIO(base64.b64decode(d["thumb"]))).convert("RGB")
            it["_thumb_b64"] = d["thumb"]
        except Exception:
            it["thumb"] = None
    if d.get("made"):
        it["made"] = set(d["made"])
    if d.get("partial"):
        it["partial"] = (d["partial"][0], set(d["partial"][1]), set(d["partial"][2]))
    it["cancel"] = False
    return it


def vtuple(v):
    """'2025.10.22' / '8.0-full_build…' -> (2025, 10, 22) / (8, 0); None if it is not numeric."""
    m = re.match(r"\d+(?:\.\d+)*", v or "")
    return tuple(int(x) for x in m.group(0).split(".")) if m else None


def newer(latest, installed):
    """True if `latest` is strictly newer than `installed` (False when either is unknown)."""
    a, b = vtuple(latest), vtuple(installed)
    if not a or not b:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def _http_json(url):
    req = Request(url, headers={"User-Agent": "yt-dlp-gui", "Accept": "application/json"})
    with urlopen(req, timeout=6) as r:
        return json.load(r)


def latest_ytdlp():
    """Latest yt-dlp release on PyPI, or None if it cannot be fetched."""
    try:
        return _http_json("https://pypi.org/pypi/yt-dlp/json")["info"]["version"]
    except Exception:
        return None


def latest_ffmpeg():
    """Latest stable FFmpeg release (tags 'nX.Y[.Z]' of the FFmpeg repo), or None."""
    try:
        tags = _http_json("https://api.github.com/repos/FFmpeg/FFmpeg/tags?per_page=100")
        found = [m.group(1) for t in tags
                 if (m := re.fullmatch(r"n(\d+(?:\.\d+){1,2})", t.get("name", "")))]
        return max(found, key=lambda s: vtuple(s) + (0,) * (3 - len(vtuple(s)))) if found else None
    except Exception:
        return None


FFMPEG_ZIP = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


APP_VERSION = "1.3.2"
APP_REPO = "leclodo/Another-Video-Downloader"
APP_RELEASES_URL = f"https://github.com/{APP_REPO}/releases"


def latest_app():
    """(version, installer url) of the latest GitHub release of the app, or (None, None)."""
    try:
        d = _http_json(f"https://api.github.com/repos/{APP_REPO}/releases/latest")
        ver = str(d.get("tag_name", "")).lstrip("vV")
        url = next((a["browser_download_url"] for a in d.get("assets", [])
                    if a.get("name", "").lower().endswith("installer.exe")), None)
        return ver or None, url
    except Exception:
        return None, None


APP_UPDATE = {"url": None, "version": None}      # filled by the check (installer asset of the newer release)


def update_app():
    """Downloads the installer of the latest release and runs it silently (it restarts the app)."""
    ver, url = latest_app()
    if not url or not newer(ver, APP_VERSION):
        raise RuntimeError("no installer found")
    dest = os.path.join(tempfile.gettempdir(), "Another-Video-Downloader-Installer.exe")
    _download(url, dest)
    flags = 0x00000008 | 0x00000200 if sys.platform.startswith("win") else 0   # detached: survives our exit
    subprocess.Popen([dest, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     creationflags=flags, close_fds=True)


def can_update(key):
    """Whether the app knows how to update this component by itself."""
    if key == "app":
        return sys.platform.startswith("win") and bool(getattr(sys, "frozen", False))
    if key == "yt-dlp":
        return True
    win = sys.platform.startswith("win")
    return win and (bool(getattr(sys, "frozen", False)) or bool(shutil.which("winget")))


def _download(url, dest):
    req = Request(url, headers={"User-Agent": "yt-dlp-gui"})
    with urlopen(req, timeout=30) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)


def _pypi_release(name, version=None):
    """(metadata, url of the pure-python wheel) of a PyPI project (latest release by default)."""
    path = f"{name}/{version}/json" if version else f"{name}/json"
    data = _http_json("https://pypi.org/pypi/" + path)
    wheel = next((u["url"] for u in data["urls"]
                  if u.get("packagetype") == "bdist_wheel" and u["filename"].endswith("-none-any.whl")), None)
    return data, wheel


def _extract_wheel(url, tmp, dest):
    whl = os.path.join(tmp, "pkg.whl")
    _download(url, whl)
    with zipfile.ZipFile(whl) as z:
        z.extractall(dest)


def _run_hidden(cmd, timeout=900):
    flags = 0x08000000 if sys.platform.startswith("win") else 0  # no console flash
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=flags)


def update_ytdlp():
    """Updates yt-dlp. Python: pip. .exe: downloads the new package next to the settings."""
    if not getattr(sys, "frozen", False):
        out = _run_hidden([sys.executable, "-m", "pip", "install", "-U", "yt-dlp[default]"])
        if out.returncode != 0:
            raise RuntimeError((out.stderr or out.stdout or "pip failed").strip().splitlines()[-1])
        return
    root = updates_dir()
    new = os.path.join(root, "ytdlp.new")
    shutil.rmtree(new, ignore_errors=True)
    os.makedirs(new)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            data, wheel = _pypi_release("yt-dlp")
            if not wheel:
                raise RuntimeError("no wheel")
            _extract_wheel(wheel, tmp, new)
            # yt-dlp[default] pins a matching yt-dlp-ejs (YouTube challenge solver): fetch it too.
            ejs = next((m.group(1) for r in data["info"].get("requires_dist") or []
                        if "default" in r and (m := re.match(r"yt-dlp-ejs\s*==\s*([\w.]+)", r))), None)
            if ejs:
                try:
                    _, ejs_wheel = _pypi_release("yt-dlp-ejs", ejs)
                    if ejs_wheel:
                        _extract_wheel(ejs_wheel, tmp, new)
                except Exception:
                    pass
        shutil.rmtree(YT_OVERRIDE, ignore_errors=True)
        os.replace(new, YT_OVERRIDE)
        _write_stamp()
    finally:
        shutil.rmtree(new, ignore_errors=True)


def update_ffmpeg():
    """Updates ffmpeg. .exe: downloads the official-build zip. Python (Windows): winget."""
    if not getattr(sys, "frozen", False):
        out = _run_hidden(["winget", "upgrade", "ffmpeg", "--accept-source-agreements",
                           "--accept-package-agreements"])
        if out.returncode != 0:
            raise RuntimeError("winget: " + ((out.stdout or out.stderr or "").strip().splitlines() or ["?"])[-1])
        return
    root = updates_dir()
    final = os.path.join(root, "ffmpeg")
    new = final + ".new"
    shutil.rmtree(new, ignore_errors=True)
    os.makedirs(new)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            zpath = os.path.join(tmp, "ffmpeg.zip")
            _download(FFMPEG_ZIP, zpath)
            with zipfile.ZipFile(zpath) as z:
                for name in z.namelist():
                    base = os.path.basename(name).lower()
                    if base in ("ffmpeg.exe", "ffprobe.exe") and "/bin/" in name:
                        with z.open(name) as src, open(os.path.join(new, base), "wb") as dst:
                            shutil.copyfileobj(src, dst)
        if not all(os.path.exists(os.path.join(new, n)) for n in ("ffmpeg.exe", "ffprobe.exe")):
            raise RuntimeError("ffmpeg.exe not found in archive")
        shutil.rmtree(final, ignore_errors=True)
        os.replace(new, final)
        _write_stamp()
        os.environ["PATH"] = final + os.pathsep + os.environ.get("PATH", "")  # used right away
    finally:
        shutil.rmtree(new, ignore_errors=True)


def apply_titlebar_theme(win):
    """Windows 10/11: makes the title bar (X, minimize, maximize) follow the PC's dark / light mode."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        dark = THEME_DARK.get(THEME, True)  # follows the app's theme (which starts from the PC's setting)
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        val = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (19 on older Windows 10 builds)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val),
                                                          ctypes.sizeof(val)) == 0:
                break
    except Exception:
        pass


def trim_memory():
    """Gives back what Python no longer uses (garbage + Windows working set): lowers the RAM shown."""
    try:
        gc.collect()
        if sys.platform.startswith("win"):
            import ctypes
            ctypes.windll.kernel32.SetProcessWorkingSetSize(ctypes.windll.kernel32.GetCurrentProcess(),
                                                            ctypes.c_size_t(-1), ctypes.c_size_t(-1))
    except Exception:
        pass


def fetch_image(url):
    try:
        with urlopen(url, timeout=10) as r:
            img = Image.open(io.BytesIO(r.read()))
            img.draft("RGB", (640, 360))                  # JPEG: decoded already reduced
            img = img.convert("RGB")
            img.thumbnail((640, 360), Image.Resampling.BILINEAR)   # never keep a full 1280x720 bitmap per video
            return img
    except Exception:
        return None


def small_thumb_url(e):
    """Smallest thumbnail of a playlist entry that is still sharp enough for a 64-96 px preview."""
    ts = [t for t in (e.get("thumbnails") or []) if (t.get("url") or "").startswith("http")]
    ts = [t for t in ts if ".mhtml" not in t["url"] and not t.get("fragments")]
    if ts:
        big = sorted((t for t in ts if (t.get("width") or 0) >= 96), key=lambda t: t["width"])
        return (big[0] if big else ts[-1])["url"]
    return e.get("thumbnail") or ""


def fetch_small(url):
    """A tiny preview (max 96x54) of a thumbnail, or None."""
    if not url:
        return None
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=10) as r:
            img = Image.open(io.BytesIO(r.read()))
            img.draft("RGB", (192, 108))
            img = img.convert("RGB")
            img.thumbnail((96, 54), Image.Resampling.BILINEAR)
            return img
    except Exception:
        return None


def load_small_thumbs(jobs, deliver, workers=4):
    """jobs = [(key, url)]; deliver(key, img) is called from worker threads for each success."""
    q = queue.Queue()
    for j in jobs:
        q.put(j)

    def work():
        while True:
            try:
                key, url = q.get_nowait()
            except queue.Empty:
                return
            img = fetch_small(url)
            if img is not None:
                try:
                    deliver(key, img)
                except Exception:
                    return
    for _ in range(min(workers, len(jobs))):
        threading.Thread(target=work, daemon=True).start()


THUMB_CACHE = {}      # url -> original bytes


def fetch_bytes(url):
    if url not in THUMB_CACHE:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=15) as r:
            THUMB_CACHE[url] = r.read()
    return THUMB_CACHE[url]


def thumb_candidates(info):
    """The video's biggest thumbnail: [{'url', 'w', 'h'}] (the extractor exposes no A/B-test variants)."""
    found = []
    for i, t in enumerate(info.get("thumbnails") or []):
        url = t.get("url") or ""
        if not url.startswith("http") or t.get("fragments") or ".mhtml" in url or str(t.get("format", "")).startswith("sb"):
            continue
        w, h = t.get("width") or 0, t.get("height") or 0
        found.append((w * h, i, {"url": url, "w": w, "h": h}))
    if info.get("thumbnail") and all(f[2]["url"] != info["thumbnail"] for f in found):
        found.append((10 ** 9, 10 ** 6, {"url": info["thumbnail"], "w": 0, "h": 0}))
    found.sort(key=lambda f: (f[0], f[1]), reverse=True)     # biggest first
    if not found:
        return []
    best = found[0][2]
    for _, _, t in found:                       # same size as the best one: prefer jpg over webp
        if t["w"] * t["h"] == best["w"] * best["h"] and ".webp" in best["url"] and ".webp" not in t["url"]:
            best = t
    return [best]


def setup_cols(frame):
    for i, w in COLS:
        frame.columnconfigure(i, minsize=w, weight=1 if i == 1 else 0)


class ResMonitor:
    """RAM / CPU used by the app and the programs it started (ffmpeg, deno). Windows only, no extra package."""

    def __init__(self):
        self.ok = sys.platform.startswith("win")
        self.last = None                              # (wall time, cpu seconds)
        self.ncpu = os.cpu_count() or 1
        if self.ok:
            try:
                import ctypes
                from ctypes import wintypes as wt
                self.ct, self.wt = ctypes, wt
                k = ctypes.WinDLL("kernel32", use_last_error=True)
                k.OpenProcess.restype = wt.HANDLE
                k.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
                k.CloseHandle.argtypes = [wt.HANDLE]
                k.CreateToolhelp32Snapshot.restype = wt.HANDLE
                k.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
                k.GetProcessTimes.argtypes = [wt.HANDLE] + [ctypes.c_void_p] * 4
                k.Process32FirstW.argtypes = k.Process32NextW.argtypes = [wt.HANDLE, ctypes.c_void_p]
                self.k = k
                ps = ctypes.WinDLL("psapi", use_last_error=True)
                ps.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD]

                class PE(ctypes.Structure):
                    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("pid", wt.DWORD),
                                ("heap", ctypes.c_size_t), ("mod", wt.DWORD), ("thr", wt.DWORD),
                                ("ppid", wt.DWORD), ("pri", wt.LONG), ("flags", wt.DWORD), ("exe", wt.WCHAR * 260)]

                class PMC(ctypes.Structure):
                    _fields_ = [("cb", wt.DWORD), ("pf", wt.DWORD), ("peak", ctypes.c_size_t), ("ws", ctypes.c_size_t),
                                ("a", ctypes.c_size_t), ("b", ctypes.c_size_t), ("c", ctypes.c_size_t),
                                ("d", ctypes.c_size_t), ("priv", ctypes.c_size_t), ("e", ctypes.c_size_t)]
                self.PE, self.PMC, self.ps = PE, PMC, ps
            except Exception:
                self.ok = False

    def _tree(self):
        ct = self.ct
        snap = self.k.CreateToolhelp32Snapshot(0x2, 0)
        kids, pids = {}, {os.getpid()}
        try:
            e = self.PE()
            e.dwSize = ct.sizeof(e)
            ok = self.k.Process32FirstW(snap, ct.byref(e))
            while ok:
                kids.setdefault(e.ppid, []).append(e.pid)
                ok = self.k.Process32NextW(snap, ct.byref(e))
        finally:
            self.k.CloseHandle(snap)
        todo = [os.getpid()]
        while todo:
            for c in kids.get(todo.pop(), []):
                if c not in pids:
                    pids.add(c)
                    todo.append(c)
        return pids

    def sample(self):
        """-> (ram bytes, cpu %), or None when unavailable."""
        if not self.ok:
            return None
        ct = self.ct
        pids = self._tree()
        ram, cpu = 0, 0.0
        for pid in pids:
            h = self.k.OpenProcess(0x1000, False, pid)             # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                continue
            try:
                pm = self.PMC()
                pm.cb = ct.sizeof(pm)
                if self.ps.GetProcessMemoryInfo(h, ct.byref(pm), pm.cb):
                    ram += pm.priv
                t = [ct.c_ulonglong() for _ in range(4)]
                if self.k.GetProcessTimes(h, *[ct.byref(x) for x in t]):
                    cpu += (t[2].value + t[3].value) / 1e7
            finally:
                self.k.CloseHandle(h)
        now = time.monotonic()
        pct = 0.0
        if self.last and now > self.last[0]:
            pct = max(0.0, (cpu - self.last[1]) / (now - self.last[0]) / self.ncpu * 100)
        self.last = (now, cpu)
        return ram, min(pct, 100.0)


def mp4_http_range(url, a, b, hdrs):
    """Opens bytes a..b of a YouTube media URL (Range header first, then the `range=` parameter as a fallback)."""
    try:
        return urlopen(Request(url, headers={**hdrs, "Range": f"bytes={a}-{b}"}), timeout=30)
    except HTTPError as e:
        if e.code not in (403, 416):
            raise
    sep = "&" if "?" in url else "?"
    return urlopen(Request(f"{url}{sep}range={a}-{b}", headers=hdrs), timeout=30)


def parse_sidx(box):
    """Parses a whole 'sidx' box -> (first_offset, [(t0, t1, offset, size, starts_with_sap)]) or None."""
    p = 16 if int.from_bytes(box[0:4], "big") == 1 else 8
    ver = box[p]
    p += 8                                                   # version/flags + reference_ID
    timescale = int.from_bytes(box[p:p + 4], "big")
    p += 4
    if ver == 0:
        ept, first = int.from_bytes(box[p:p + 4], "big"), int.from_bytes(box[p + 4:p + 8], "big")
        p += 8
    else:
        ept, first = int.from_bytes(box[p:p + 8], "big"), int.from_bytes(box[p + 8:p + 16], "big")
        p += 16
    cnt = int.from_bytes(box[p + 2:p + 4], "big")
    p += 4
    if not timescale or not cnt:
        return None
    refs, off, t = [], 0, ept
    for _ in range(cnt):
        w = int.from_bytes(box[p:p + 4], "big")
        dur = int.from_bytes(box[p + 4:p + 8], "big")
        sap = int.from_bytes(box[p + 8:p + 12], "big") >> 31
        p += 12
        if w >> 31:                                          # hierarchical index: not handled
            return None
        refs.append((t / timescale, (t + dur) / timescale, off, w & 0x7FFFFFFF, bool(sap)))
        off += w & 0x7FFFFFFF
        t += dur
    return first, refs


def read_mp4_index(url, hdrs, size_hint=0):
    """Reads the start of a fragmented MP4 (DASH) file: returns (init bytes, [(t0, t1, abs_offset, size, sap)])."""
    data = b""

    def ensure(n):
        nonlocal data
        if n > 32 * 1048576:
            raise ValueError("index too far")
        while len(data) < n:
            a = len(data)
            with mp4_http_range(url, a, max(n, a + 262144) - 1, hdrs) as r:
                chunk = r.read()
            if not chunk:
                raise ValueError("file too short")
            data += chunk
    ensure(65536)
    pos = 0
    while True:
        ensure(pos + 16)
        size = int.from_bytes(data[pos:pos + 4], "big")
        typ = data[pos + 4:pos + 8]
        if size == 1:
            size = int.from_bytes(data[pos + 8:pos + 16], "big")
        if size < 8 or typ in (b"moof", b"mdat"):
            raise ValueError("no sidx before the media data")
        if typ == b"sidx":
            ensure(pos + size)
            parsed = parse_sidx(data[pos:pos + size])
            if not parsed:
                raise ValueError("unsupported sidx")
            first, refs = parsed
            base = pos + size + first
            return data[:pos], [(t0, t1, base + o, sz, sap) for t0, t1, o, sz, sap in refs]
        pos += size


def lbl(parent, text="", size=11, color=None, bold=False, **kw):
    """Label that inherits its parent's background."""
    font = (FONT, size, heavy()) if bold else (FONT, size)
    w = tk.Label(parent, text=text, bg=parent.cget("bg"), fg=color or FG, font=font, **kw)
    if bold:
        w._bold_size = size                   # restyle_bold() re-applies the weight when the theme changes
    return w


def restyle_bold(widget):
    """After a theme switch: titles lose / regain their bold depending on the theme."""
    size = getattr(widget, "_bold_size", None)
    if size:
        try:
            widget.config(font=(FONT, size, heavy()))
        except tk.TclError:
            pass
    for ch in widget.winfo_children():
        restyle_bold(ch)


def card(parent, **kw):
    return tk.Frame(parent, bg=CARD, highlightbackground=BORDER,
                    highlightcolor=BORDER, highlightthickness=1, **kw)


def round_rect(c, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


def icon_button(parent, text, command, size=12, hover="ACCENT_HI"):
    """Flat icon button; `hover` is the name of the colour constant used while the mouse is over it."""
    b = tk.Button(
        parent, text=text, command=command, width=2, bg=parent.cget("bg"), fg=MUTED,
        activebackground=parent.cget("bg"), activeforeground=globals()[hover],
        relief="flat", bd=0, highlightthickness=0, font=(FONT, size),
        cursor="hand2", disabledforeground=DIM,
    )
    b.base_fg = MUTED
    b.bind("<Enter>", lambda e: b.cget("state") == "normal" and b.config(fg=globals()[hover]))
    b.bind("<Leave>", lambda e: b.config(fg=b.base_fg))
    return b


class RoundButton(tk.Canvas):
    """Flat rounded button with hover effect. Supports config(text=, state=, command=)."""

    @staticmethod
    def styles():  # style: (normal, hover, text) - read at draw time so the theme can change
        return {
            "primary": (ACCENT, ACCENT_HI, "#ffffff"),
            "secondary": (BTN2, BTN2_HI, FG),
            "danger": (DANGER_BG, DANGER_HI, RED),
            "history": (mix_color(BTN2, GREEN, 0.22), mix_color(BTN2_HI, GREEN, 0.32), GREEN),
            "ck_ok": (mix_color(BTN2, GREEN, 0.22), mix_color(BTN2_HI, GREEN, 0.32), GREEN),
            "ck_bad": (mix_color(BTN2, RED, 0.22), mix_color(BTN2_HI, RED, 0.32), RED),
        }

    def __init__(self, parent, text, command, small=False, style="primary", state="normal"):
        self._o = {"text": text, "command": command, "style": style, "state": state, "hover": False,
                   "busy": False}
        self._angle, self._job = 0, None
        self._font = tkfont.Font(family=FONT, size=10 if small else 11, weight="normal" if small else heavy())
        self._small = small
        self._pad = (14, 5) if small else (22, 9)
        super().__init__(parent, bg=parent.cget("bg"), highlightthickness=0, bd=0, cursor="hand2")
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._release)
        self._redraw()

    def configure(self, cnf=None, **kw):
        if cnf:
            kw.update(cnf)
        changed = False
        for key in ("text", "state", "command", "style", "busy"):
            if key in kw:
                self._o[key] = kw.pop(key)
                changed = True
        if kw:
            tk.Canvas.configure(self, **kw)
        if changed:
            self._redraw()
            if self._o["busy"] and self._job is None:
                self._tick()

    config = configure

    def _tick(self):
        """Loading animation: a small arc turning where the label would be."""
        self._job = None
        if not self._o["busy"]:
            return
        try:
            self._angle = (self._angle - 30) % 360
            self._redraw()
            self._job = self.after(50, self._tick)
        except tk.TclError:                  # widget destroyed
            pass

    def _set_hover(self, on):
        self._o["hover"] = on
        self._redraw()

    def _release(self, e):
        inside = 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height()
        if self._o["state"] == "normal" and inside and self._o["command"] and not self._o["busy"]:
            self._o["command"]()

    def _redraw(self):
        o = self._o
        self.delete("all")
        if not self._small:
            self._font.configure(weight=heavy())
        w = self._font.measure(o["text"]) + 2 * self._pad[0]
        h = self._font.metrics("linespace") + 2 * self._pad[1]
        tk.Canvas.configure(self, width=w, height=h)
        base, hover, fg = self.styles()[o["style"]]
        if o["state"] != "normal":
            fill, fg, cursor = BTN_OFF, DIM, "arrow"
        else:
            fill, cursor = (hover if o["hover"] else base), "hand2"
        round_rect(self, 1, 1, w - 1, h - 1, min(10, h // 2), fill=fill, outline="")
        if o["busy"]:                        # same size as with the label, spinner instead of text
            r = h * 0.2
            self.create_arc(w / 2 - r, h / 2 - r, w / 2 + r, h / 2 + r, start=self._angle, extent=270,
                            style="arc", outline=fg, width=2)
        else:
            self.create_text(w / 2, h / 2, text=o["text"], fill=fg, font=self._font)
        tk.Canvas.configure(self, cursor=cursor)


class Tooltip:
    """Small hover tooltip. `text_fn` returns the text (empty = no tooltip)."""

    def __init__(self, widget, text_fn):
        self.widget, self.text_fn = widget, text_fn
        self.tip = None
        self.after_id = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._hide()
        self.after_id = self.widget.after(400, self._show)

    def _show(self):
        self.after_id = None
        try:
            text = self.text_fn()
            if not text:
                return
            x, y = self.widget.winfo_pointerx() + 14, self.widget.winfo_pointery() + 18
            self.tip = tk.Toplevel(self.widget)
            self.tip.wm_overrideredirect(True)
            self.tip.wm_geometry(f"+{x}+{y}")
            tk.Label(self.tip, text=text, bg=TIP_BG, fg=FG, bd=0, highlightthickness=1,
                     highlightbackground=BORDER, font=(FONT, 10), padx=8, pady=5,
                     justify="left", wraplength=520).pack()
        except tk.TclError:
            self.tip = None

    def _hide(self, _event=None):
        try:
            if self.after_id:
                self.widget.after_cancel(self.after_id)
            if self.tip:
                self.tip.destroy()
        except tk.TclError:
            pass
        self.after_id = None
        self.tip = None


# ---------------------------------------------------------------- custom widgets
def help_bubble(parent, text_fn, on_click=None):
    """Small round '?' that shows `text_fn()` in a tooltip on hover (and acts on click)."""
    c = tk.Canvas(parent, width=18, height=18, bg=parent.cget("bg"), highlightthickness=0,
                  cursor="hand2" if on_click else "")  # hand only when it can be clicked
    if on_click:
        c.bind("<ButtonRelease-1>", lambda e: on_click())
    oval = c.create_oval(1, 1, 17, 17, fill=CARD2, outline=BORDER)
    mark = c.create_text(9, 9, text="?", fill=MUTED, font=(FONT, 9, heavy()))

    def paint(on):
        c.itemconfig(oval, fill=ACCENT if on else CARD2, outline=ACCENT if on else BORDER)
        c.itemconfig(mark, fill="#ffffff" if on else MUTED)

    c.bind("<Enter>", lambda e: paint(True), add="+")
    c.bind("<Leave>", lambda e: paint(False), add="+")
    Tooltip(c, text_fn)
    return c


class TimeInput(tk.Frame):
    """__ h __ m __ s input. Mouse wheel = +/- 1, never above `max` seconds."""

    def __init__(self, master):
        super().__init__(master, bg=CARD)
        self.max = 0
        self.on_change = None   # called whenever a value changes
        self.invalid = False
        self.vars = [tk.StringVar(value="0") for _ in range(3)]
        self.entries = []
        for i, (var, unit) in enumerate(zip(self.vars, ("h", "m", "s"))):
            var.trace_add("write", lambda *a: self.on_change and self.on_change())
            e = tk.Entry(
                self, textvariable=var, width=3, justify="center", relief="flat",
                bg=CARD2, fg=FG, insertbackground=FG, highlightthickness=1,
                highlightbackground=BORDER, highlightcolor=ACCENT,
                disabledbackground=INPUT_OFF, disabledforeground=DIM, font=(FONT, 11),
            )
            e.pack(side="left", ipady=3)
            e.bind("<MouseWheel>", lambda ev, i=i: self._wheel(ev, i))
            e.bind("<FocusOut>", lambda ev: self.normalize())
            e.bind("<Return>", lambda ev: self.normalize())
            lbl(self, unit, 10, MUTED).pack(side="left", padx=(4, 12))
            self.entries.append(e)
        self.set_enabled(False)

    def set_enabled(self, on):
        for e in self.entries:
            e.config(state="normal" if on else "disabled")

    def _vals(self):
        out = []
        for v in self.vars:
            try:
                out.append(max(0, int(v.get() or 0)))
            except ValueError:
                out.append(0)
        return out

    def set(self, total):
        total = max(0, int(total))
        h, r = divmod(total, 3600)
        m, s = divmod(r, 60)
        for var, val in zip(self.vars, (h, m, s)):
            var.set(str(val))

    def set_max(self, sec):
        self.max = int(sec)
        self.normalize()

    def total(self):
        """Current value in seconds, as typed (not clamped, no side effects)."""
        h, m, s = self._vals()
        return h * 3600 + m * 60 + s

    def set_invalid(self, bad):
        """Red background when the value makes the trim impossible."""
        self.invalid = bad
        for e in self.entries:
            e.config(bg=INVALID_BG if bad else CARD2,
                     highlightbackground=RED if bad else BORDER,
                     highlightcolor=RED if bad else ACCENT)

    def normalize(self):
        h, m, s = self._vals()
        total = min(h * 3600 + m * 60 + s, self.max)
        self.set(total)
        return total

    def seconds(self):
        return self.normalize()

    def _wheel(self, event, idx):
        if str(event.widget.cget("state")) != "normal":
            return None
        vals = self._vals()
        vals[idx] += 1 if event.delta > 0 else -1
        total = vals[0] * 3600 + vals[1] * 60 + vals[2]
        valid = vals[idx] >= 0 and (idx == 0 or vals[idx] <= 59) and total <= self.max
        if valid:
            self.set(total)
        return "break"  # keep the wheel from scrolling the queue


# ------------------------------------------------ single instance
PORT = 47653                                   # local only (127.0.0.1): a 2nd launch hands its link over


def url_from_argv(argv):
    """Link given at launch (plain http(s) link)."""
    for a in argv[1:]:
        if a.startswith(("http://", "https://")):
            return a
    return None


def send_to_running(url):
    """Hands the link to an already running instance; False when none is listening."""
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.6) as c:
            c.sendall(("JAYTDL " + url).encode("utf-8"))
            c.settimeout(3)
            return c.recv(8) == b"OK"       # only a window that really answers counts (not a frozen process)
    except OSError:
        return False


def start_listener(events):
    """Listens (local machine only) for links sent by a second launch."""
    try:
        srv = socket.socket()
        srv.bind(("127.0.0.1", PORT))
        srv.listen(5)
    except OSError:
        return

    def loop():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                continue
            try:
                conn.settimeout(2)
                data = conn.recv(4096)
                u = data[7:].decode("utf-8", "ignore").strip() if data.startswith(b"JAYTDL ") else None
                ack = threading.Event()
                if u == "show":                  # plain relaunch: just bring the window back
                    events.put(("external", "", ack))
                elif u and len(u) < 4000 and u.startswith(("http://", "https://")):
                    events.put(("external", u, ack))
                else:
                    ack = None
                if ack is not None and ack.wait(2.5):    # the window itself handled it
                    conn.sendall(b"OK")
            except (OSError, ValueError):
                pass
            finally:
                conn.close()
    threading.Thread(target=loop, daemon=True).start()


def tray_image(n=64):
    """The app's logo (blue rounded square + download arrow) for the notification area."""
    k = 4
    S = n * k
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, S - 1, S - 1), radius=int(S * .3), fill=ACCENT)
    w, c = max(int(S * .09), 2), "#f5f7ff"
    d.line((S * .5, S * .22, S * .5, S * .56), fill=c, width=w)
    d.line((S * .33, S * .42, S * .5, S * .6, S * .67, S * .42), fill=c, width=w, joint="curve")
    d.line((S * .28, S * .74, S * .72, S * .74), fill=c, width=w)
    for x, y in ((S * .5, S * .22), (S * .28, S * .74), (S * .72, S * .74)):
        d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=c)
    return im.resize((n, n), Image.LANCZOS)


PL_COLORS = ["#4f7cff", "#e0527a", "#f0a020", "#2fb67c", "#a05ae0", "#20b5d0", "#e0702f", "#8bc34a"]


def playlist_icon(w, h, color):
    """'Playlist' icon (lines + play triangle) on a transparent background, in the playlist's colour."""
    k = 4
    W, H = w * k, h * k
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    t = max(int(min(w, h * 1.7) * 0.055 * k), 2)          # line thickness
    for y, x2 in ((.30, .80), (.48, .80), (.66, .50)):
        d.rounded_rectangle((W * .20, H * y - t / 2, W * x2, H * y + t / 2), radius=t // 2, fill=color)
    d.polygon([(W * .60, H * .58), (W * .60, H * .82), (W * .80, H * .70)], fill=color)
    return im.resize((w, h), Image.LANCZOS)


def pause_icon(color, w=26, h=20, stop=False):
    """Two vertical bars ('pause'), or a square ('stop'), as a transparent image of the given colour."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    bar, gap = 4, 3
    x0 = (w - (2 * bar + gap)) // 2
    y0, y1 = 6, h - 2                  # lines up with the ▶ glyph next to it
    rgb = tuple(int(color[k:k + 2], 16) for k in (1, 3, 5)) + (255,)
    cols = list(range(x0, x0 + bar)) + list(range(x0 + bar + gap, x0 + 2 * bar + gap))
    if stop:
        cols, y0, y1 = list(range(w // 2 - 5, w // 2 + 5)), y0 + 1, y1 - 1
    for x in cols:
        for y in range(y0, y1):
            px[x, y] = rgb
    return ImageTk.PhotoImage(img)


class QueueRow(tk.Frame):
    """One queue line: name (+ rename / folder buttons), info, progress bar, play / stop / delete."""

    STATUS_COLORS = {"done": GREEN, "error": RED, "cancelled": ORANGE}
    BAR_STYLES = {"done": "Green", "error": "Red", "cancelled": "Orange"}
    EDITABLE = ("waiting", "error", "cancelled")

    @staticmethod
    def can_edit(item):
        """Name, quality and folder are frozen once the download has started (even when paused)."""
        return item["status"] in QueueRow.EDITABLE and not item.get("started")

    def set_thumb(self, img):
        """A playlist line gets its real thumbnail once downloaded."""
        try:
            self.photo = ImageTk.PhotoImage(img.resize((64, 36), Image.Resampling.LANCZOS))
            self.thumb_cell.config(image=self.photo)
        except tk.TclError:
            pass

    def __init__(self, master, item, app):
        super().__init__(master, bg=CARD)
        if "added" not in item:
            item["added"] = next_added()
        setup_cols(self)
        self.item, self.app = item, app
        self.state = ("", None)
        self.err = ""
        self.is_running = False
        self.stopping = False
        self.truncated = False
        self.last_w = 0
        self.editing = False
        self.name_entry = None
        self.font = tkfont.Font(family=FONT, size=11)

        # thumbnail
        self.photo = None
        if item.get("thumb"):
            self.photo = ImageTk.PhotoImage(item["thumb"].resize((64, 36), Image.Resampling.LANCZOS))
        elif item.get("pl_color"):   # playlist line: icon in the playlist's colour instead of a thumbnail
            self.photo = ImageTk.PhotoImage(playlist_icon(64, 36, item["pl_color"]))
        if item.get("pl_color"):     # coloured line at the start: links the videos of one playlist together
            tk.Frame(self, bg=item["pl_color"], width=4).place(x=0, y=0, relheight=1)
        cell0 = tk.Frame(self, bg=CARD)
        cell0.grid(row=0, column=0, padx=(10, 4), pady=8)
        # drag handle: grab it and move the line to change the download order
        self.handle = lbl(cell0, "≡", 15, MUTED, cursor="fleur")
        self.handle.pack(side="left", padx=(0, 6))
        self.handle.bind("<ButtonPress-1>", lambda e: self.handle.config(fg=ACCENT_HI))
        self.handle.bind("<B1-Motion>", lambda e: app.drag_move(item, e.y_root))
        self.handle.bind("<ButtonRelease-1>", lambda e: self.handle.config(fg=MUTED))
        thumb_cell = self.thumb_cell = tk.Label(cell0, image=self.photo, bg=CARD2, bd=0)
        thumb_cell.pack(side="left")
        if item.get("playlist"):
            Tooltip(thumb_cell, lambda: item["playlist"])

        # name + rename + folder buttons
        tcell = self.tcell = tk.Frame(self, bg=CARD)
        tcell.grid(row=0, column=1, sticky="w", padx=4)
        self.name_lbl = lbl(tcell, "", 11, FG, anchor="w")
        self.name_lbl.pack(side="left")
        self.btn_edit = icon_button(tcell, "📝", lambda: app.rename_item(item), size=11)
        self.btn_edit.pack(side="left", padx=(6, 0))
        self.btn_dir = icon_button(tcell, "📁", lambda: app.choose_item_dir(item), size=10)
        self.btn_dir.pack(side="left")
        self.btn_link = icon_button(tcell, "🔗", self._copy_link, size=10)    # copy the link; Ctrl+click opens it
        self.btn_link.pack(side="left")
        self.btn_link.bind("<Control-Button-1>", self._open_link)

        def cell(col, color=MUTED):
            w = lbl(self, "", 11, color)
            w.grid(row=0, column=col)
            return w

        cell(2).config(text=tr("live_tag") if item.get("is_live") else fmt_duration(item["duration"]))
        self.date_cell = cell(3)
        self.date_cell.config(text=item["upload_date"])
        self.q_cb = ttk.Combobox(self, state="readonly", width=6, font=(FONT, 10),
                                 style="Row.TCombobox")
        self.q_cb.grid(row=0, column=4)
        self.q_cb.bind("<<ComboboxSelected>>", self._quality_changed)
        # the wheel scrolls the queue instead of silently changing the quality
        self.q_cb.bind("<MouseWheel>", lambda e: (app._on_wheel(e), "break")[1])
        self.trim_lbl = cell(5)
        self.trim_lbl.bind("<Button-1>", lambda e: app.edit_trim(item))  # click = edit the trim
        Tooltip(self.trim_lbl, lambda: tr("tip_trim_edit") if self._trim_editable() else "")

        # progress
        prog = tk.Frame(self, bg=CARD)
        prog.grid(row=0, column=6, padx=6)
        self.BAR_W, self.BAR_H = 176, 22
        self.pb = tk.Canvas(prog, width=self.BAR_W, height=self.BAR_H, bg=CARD,
                            highlightthickness=0, bd=0)
        self.pb.pack(side="left")
        self.pb.bind("<Button-1>", self._click)
        self.t_start = None
        self.speed = None
        self.last_pct = 0.0

        # play + stop/delete
        act = tk.Frame(self, bg=CARD)
        act.grid(row=0, column=7)
        self.btn_play = icon_button(act, "▶", self._play_click, size=11, hover="GREEN")
        self.btn_play.pack(side="left")
        self.btn = icon_button(act, "✕", self._btn_click, hover="RED")
        self.btn.pack(side="left")

        tk.Frame(self, bg=BORDER, height=1).grid(row=1, column=0, columnspan=len(COLS), sticky="ew")

        # tooltips
        Tooltip(self.name_lbl, lambda: item["name"] if self.truncated else "")
        self.name_lbl.bind("<Double-Button-1>", lambda e: app.rename_item(item))  # double click = rename
        Tooltip(self.btn_edit, lambda: tr("tip_rename"))
        Tooltip(self.btn_dir, lambda: f"{tr('tip_folder')}\n{item['outdir'] or app.outdir.get()}")
        Tooltip(self.btn_link, lambda: tr("tip_link"))
        Tooltip(self.btn_play, lambda: tr("tip_open") if item["status"] == "done" else (
            (tr("tip_stop_live") if item.get("is_live") else tr("tip_stop"))
            if item["status"] == "running" else tr("tip_play")))
        Tooltip(self.btn, lambda: tr("tip_delete"))

        self._rz_t0, self._rz_n, self._rz_job = 0.0, 0, None
        self.bind("<Configure>", self._on_resize)
        self.refresh()

    def _on_resize(self, event):
        """Name re-fitted once the layout settles (debounced). Never inside the event itself: a width that keeps
        flipping would loop forever (it froze the start-up with a restored queue)."""
        if event.widget is self and event.width != self.last_w:
            self.last_w = event.width
            now = time.monotonic()
            if now - self._rz_t0 > 1.0:
                self._rz_t0, self._rz_n = now, 0
            self._rz_n += 1
            if self._rz_n > 8 or self._rz_job is not None:     # layout feedback loop: stop refreshing
                return
            self._rz_job = self.after(30, self._do_resize)

    def _do_resize(self):
        self._rz_job = None
        try:
            if self.winfo_exists():
                self.refresh_name()
        except tk.TclError:
            pass

    def _name_px(self):
        """Pixels available for the file name: whatever the other columns leave free."""
        w = self.winfo_width()
        if w <= 1:
            return NAME_PX
        try:
            others = sum(self.grid_bbox(c, 0)[2] for c, _ in COLS if c != 1)
        except tk.TclError:
            return NAME_PX
        icons = self.btn_edit.winfo_reqwidth() + self.btn_dir.winfo_reqwidth() + self.btn_link.winfo_reqwidth() + 6
        return max(80, w - others - 8 - icons - 6)

    def _copy_link(self):
        try:
            self.app.clipboard_clear()
            self.app.clipboard_append(self.item["url"])
            self.btn_link.config(text="✓", fg=GREEN)          # short confirmation
            self.btn_link.base_fg = GREEN
            self.after(1200, self._link_reset)
        except tk.TclError:
            pass

    def _link_reset(self):
        try:
            self.btn_link.base_fg = MUTED
            self.btn_link.config(text="🔗", fg=MUTED)
        except tk.TclError:
            pass

    def _open_link(self, _event=None):
        webbrowser.open(self.item["url"])
        return "break"

    def refresh_name(self):
        name = self.item["name"]
        shown = fit_text(name, self.font, self._name_px())
        self.truncated = shown != name
        self.name_lbl.config(text=shown)

    # --- inline rename: the name turns into an entry (Enter / click away = save, Esc = cancel)
    def toggle_rename(self):
        if self.editing:
            self._finish_rename(True)
            return
        self.editing = True
        self.name_lbl.pack_forget()
        e = self.name_entry = tk.Entry(
            self.tcell, font=(FONT, 11), bg=CARD2, fg=FG, insertbackground=FG, relief="flat",
            highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT,
            width=max(12, self._name_px() // 8),
        )
        e.insert(0, self.item["name"])
        e.pack(side="left", before=self.btn_edit, ipady=2)
        e.bind("<Return>", lambda ev: self._finish_rename(True))
        e.bind("<Escape>", lambda ev: self._finish_rename(False))
        e.bind("<FocusOut>", lambda ev: self._finish_rename(True))
        self.btn_edit.config(text="✓", fg=GREEN)
        self.btn_edit.base_fg = GREEN
        e.focus_set()
        e.select_range(0, "end")
        e.icursor("end")

    def _finish_rename(self, save):
        if not self.editing:
            return
        self.editing = False
        new = self.name_entry.get().strip()
        self.name_entry.destroy()
        self.name_entry = None
        self.name_lbl.pack(side="left", before=self.btn_edit)
        self.btn_edit.base_fg = MUTED
        self.btn_edit.config(text="📝", fg=MUTED)
        new = clean_name(new)  # no emojis / forbidden characters in file names
        if save and new and new != self.item["name"]:
            self.item["name"] = new
            self.item["custom"] = True  # renamed by hand: the file-name template no longer touches it
        self.refresh_name()

    # --- texts (language / rename dependent)
    def refresh(self):
        name = self.item["name"]
        shown = fit_text(name, self.font, self._name_px())
        self.truncated = shown != name
        self.name_lbl.config(text=shown)
        keys = self.item["qualities"]
        self.q_cb.config(values=[qshort(k) for k in keys])
        if self.item["quality"] in keys:
            self.q_cb.current(keys.index(self.item["quality"]))
        if self.item.get("is_live"):          # a live has no trim: the cell tells where the recording starts
            self.trim_lbl.config(text=tr("live_short_start" if self.item.get("live_from_start")
                                         else "live_short_now"))
        else:
            self.trim_lbl.config(text=trim_text(self.item["start"], self.item["end"]))
        self.date_cell.config(text=self.item["upload_date"])
        self._render()
        self.update_buttons()

    def _render(self):
        key, arg = self.state
        w, h = self.BAR_W, self.BAR_H
        frac = 0.0
        dot = False
        if key == "pct":
            self.last_pct = arg
            self.was_rec = False
            frac, text, color = arg / 100, self._pct_text(arg), FG
        elif key == "conv":               # conversion / merge: progress guessed from the output file size
            self.last_pct = arg[1]
            self.was_rec = False
            frac, text, color = arg[1] / 100, f"{tr(arg[0])}  {arg[1]:.0f}%", FG
        elif key in ("rec", "live_rec"):  # live / unknown size: no percentage, elapsed time + size + speed
            self.was_rec = True
            el = time.monotonic() - self.t_start if self.t_start else 0
            parts = [tr("rec"), fmt_left(el)]
            if arg:
                parts.append(f"{arg / 1048576:.0f} MB")
            if self.speed:
                parts.append(f"{self.speed / 1048576:.1f} MB/s")
            frac, text, color = 0.0, "  ·  ".join(parts), FG
            dot = True
        elif key == "done":
            self.last_pct = 0.0
            frac, text, color = 1.0, tr(key), FG
        elif key == "cancelled":          # paused: orange bar up to the percentage reached
            frac, text, color = self.last_pct / 100, f"{self.last_pct:.0f}%", FG
        elif key in ("stopping", "stopping_live", "finalizing"):
            frac, text, color = (1.0 if getattr(self, "was_rec", False) else self.last_pct / 100), tr(key), FG
        elif key == "error":
            text, color = tr(key), RED
        elif key:
            text, color = tr(key), MUTED
        else:
            text, color = "", FG
        fill = {"done": GREEN, "error": RED, "cancelled": ORANGE, "stopping": ORANGE,
                "stopping_live": ORANGE, "finalizing": ORANGE}.get(key, ACCENT)
        c = self.pb
        c.delete("all")
        c.create_rectangle(0, 0, w, h, fill=CARD2, outline=CARD2)
        if frac > 0:
            c.create_rectangle(0, 0, max(1, int(w * frac)), h, fill=fill, outline=fill)
        if key == "error":  # nothing to show as progress: tint the bar's border
            c.create_rectangle(0, 0, w - 1, h - 1, fill="", outline=fill)
        if text:
            font = (FONT, 9, heavy())
            off = 7 if dot else 0                          # room for the recording dot on the left
            if not dot:
                c.create_text(w // 2 + 1, h // 2 + 1, text=text, fill=BG, font=font)  # shadow
            tid = c.create_text(w // 2 + off, h // 2, text=text, fill=color, font=font)
            if dot:
                x0 = c.bbox(tid)[0] - 12
                k = (1 + math.sin(time.monotonic() * 2 * math.pi / 2.4)) / 2   # 0..1, one cycle = 2.4 s
                col = mix_color(CARD2, "#ff2d2d", 0.15 + 0.85 * k)
                c.create_oval(x0 - 5, h // 2 - 5, x0 + 5, h // 2 + 5, fill=col, outline=col)
        c.config(cursor="hand2" if key == "error" else "")

    def set_state(self, key, arg=None, speed=None):
        now = time.monotonic()
        if key in ("pct", "rec", "live_rec"):
            if self.t_start is None:             # first measure of this run (a resume starts above 0 %)
                self.t_start, self.p0 = now, arg
            self.speed = speed
        else:
            self.t_start = None
            self.speed = None
        prev = self.state[0]
        self.state = (key, arg)
        self._render()
        if key in ("conv", "merging", "audio_conv", "converting") or prev in ("conv", "merging", "audio_conv", "converting"):
            self._sync_play()
        if key in ("rec", "live_rec") and not getattr(self, "_blinking", False):
            self._blinking = True
            self._blink()

    def _blink(self):
        """Redraws ~12x/s while recording: the red dot fades in and out slowly."""
        if self.state[0] in ("rec", "live_rec") and self.pb.winfo_exists():
            self._render()
            self.pb.after(80, self._blink)
        else:
            self._blinking = False

    def _pct_text(self, pct):
        """'45% · 1:05 · 3.2 MB/s' : percent, download speed, estimated time left."""
        parts = [f"{pct:.0f}%"]
        if self.t_start is not None and pct - self.p0 >= 1:
            rate = (pct - self.p0) / max(time.monotonic() - self.t_start, 0.001)
            parts.append(fmt_left((100 - pct) / rate))
        if self.speed:
            parts.append(f"{self.speed / 1048576:.1f} MB/s")
        return "  ·  ".join(parts)

    def set_error(self, msg):
        self.err = msg
        self.set_state("error")

    def _click(self, _event):
        if self.state[0] == "error":
            self.app.alert(tr("dl_err"), self.err, sound=False)   # the sound already played when it failed

    # --- buttons
    def _trim_editable(self):
        if self.item.get("is_live"):
            return self.can_edit(self.item)
        return self.can_edit(self.item) and not self.item.get("no_trim") and has_ffmpeg()

    def update_buttons(self):
        status = self.item["status"]
        editable = self.can_edit(self.item)
        self.trim_lbl.config(cursor="hand2" if self._trim_editable() else "")
        for b in (self.btn_edit, self.btn_dir):
            b.config(state="normal" if editable else "disabled")
        self.q_cb.config(state="readonly" if editable else "disabled")
        self._sync_play()

    def _quality_changed(self, _event=None):
        idx = self.q_cb.current()
        if idx >= 0:
            self.item["quality"] = self.item["qualities"][idx]
        self.q_cb.selection_clear()

    def _play_click(self):
        """One button for three jobs: play (idle / paused), pause (running), open folder (done)."""
        status = self.item["status"]
        if status == "done":
            self.app.open_location(self.item)
        elif status == "running":
            self.app.stop_item(self.item)
        else:
            self.app.play_item(self.item)

    def _sync_play(self):
        status = self.item["status"]
        if status == "running" and self.item.get("phase") == "pp" and not self.item.get("is_live"):
            # conversion in progress: it cannot be paused, so the button disappears
            self.btn_play.config(image="", text="", width=2, state="disabled")
        elif status == "running":  # pause icon drawn as an image (two plain bars): no font / emoji issues
            self._pause_img = pause_icon(RED, stop=bool(self.item.get("is_live")))  # live: stop + keep
            self.btn_play.config(image=self._pause_img, text="", width=0,
                                 state="disabled" if self.stopping else "normal")
        else:
            self.btn_play.config(image="", text="📂" if status == "done" else "▶", width=2,
                                 font=(FONT, 11),
                                 state="normal" if (status in self.EDITABLE or status == "done") else "disabled")

    def set_running(self, running):
        self.is_running = running
        if not running:
            self.stopping = False
        self._sync_play()

    def lock_button(self):
        """Pause requested: the button waits for the download to really stop."""
        self.stopping = True
        self._sync_play()

    def _btn_click(self):
        self.app.delete_item(self.item)  # the cross always removes the line (stops it first if needed)


# ------------------------------------------------------------------ application
class App(tk.Tk):
    def __init__(self, initial_url=None):
        super().__init__()
        self.withdraw()                  # hidden until size + position are set (no flash at the corner)
        saved_theme = load_settings().get("theme")  # first launch: the PC's own theme
        set_theme(saved_theme if saved_theme in PALETTES else system_theme())
        self.configure(bg=BG)
        if getattr(sys, "frozen", False):  # .exe: icon packed by build_exe.bat
            ico = os.path.join(getattr(sys, "_MEIPASS", ""), "icon.ico")
            if os.path.exists(ico):
                try:
                    self.iconbitmap(default=ico)
                except tk.TclError:
                    pass

        self.events = queue.Queue()      # worker -> interface
        self.lock = threading.Lock()
        self.items = []                  # queue items
        self._auto_h = None
        self._sized = False              # window sized once at launch, then left to the user
        self.sort_col, self.sort_desc = None, False
        self.sort_heads = {}             # column -> (header label, i18n key)
        self.current = None              # loaded video info
        self.pl_count = 0                # playlists added so far (each one gets its own colour)
        self.running = False             # queue worker running
        self.active = 0                  # downloads currently running (queue or single)
        self.stop_requested = False
        self.restart_requested = False
        self.queue_visible = False
        self.sb_visible = False
        self.thumb_photo = None
        self.quality_keys = []
        self.info_win = None
        self.sites_win = None
        self.settings_win = None
        self.logs_win = None
        self.hist_win = None
        self._tpl_save_id = None
        self.url_err_on = False
        self.trim_cbs = []
        self.ffmpeg_warn = None
        self.i18n = []                   # (widget, key, upper) re-translated on language switch
        global LANG, DATE_FMT, NAME_TPL, SPEED_VALUE, SPEED_UNLIM, TRAY, LIVE_FROM_START, FAST_TRIM, COMPAT_EDIT, VIDEO_CODEC, AUTO_RETRY, COOKIES_BROWSER
        saved = load_settings()
        TRAY = bool(saved.get("tray"))
        global NOTIFY_SOUND, NOTIFY_TOAST, NOTIFY_TONE, NOTIFY_VOL, NOTIFY_STYLE
        NOTIFY_VOL = int(saved.get("notify_vol", 80))
        NOTIFY_STYLE = saved.get("notify_style") if saved.get("notify_style") in (1, 2, 3) else 1
        NOTIFY_TONE = saved.get("notify_tone") if saved.get("notify_tone") in (1, 2, 3, 4) else 1
        NOTIFY_SOUND = saved.get("notify_sound", saved.get("notify", True)) is not False
        NOTIFY_TOAST = saved.get("notify_toast", saved.get("notify", True)) is not False
        LIVE_FROM_START = bool(saved.get("live_start"))
        FAST_TRIM = bool(saved.get("fast_trim", True))
        VIDEO_CODEC = saved.get("codec") or ("h264" if saved.get("compat_edit", True) is not False else "best")
        if VIDEO_CODEC not in ("h264", "best", "vp9", "av1"):
            VIDEO_CODEC = "h264"
        COMPAT_EDIT = VIDEO_CODEC == "h264"
        AUTO_RETRY = int(saved.get("retry", 2)) if str(saved.get("retry", 2)).isdigit() else 2
        COOKIES_BROWSER = saved.get("cookies_browser") or ""
        if COOKIES_BROWSER not in dict(COOKIE_BROWSERS):
            COOKIES_BROWSER = ""          # a browser that can no longer be read (saved by an older version)
        self._tray = None
        try:
            SPEED_VALUE = max(float(saved.get("speed_limit") or 0), 0.0)
        except (TypeError, ValueError):
            SPEED_VALUE = 0.0
        SPEED_UNLIM = bool(saved.get("speed_unlimited"))
        apply_speed()
        if saved.get("lang") in T:
            LANG = saved["lang"]
        if saved.get("date_fmt") in ("eu", "us", "iso"):
            DATE_FMT = saved["date_fmt"]
        if isinstance(saved.get("name_tpl"), str) and saved["name_tpl"].strip():
            NAME_TPL = saved["name_tpl"]
        saved_dir = saved.get("outdir")
        self.outdir = tk.StringVar(
            value=saved_dir if saved_dir and os.path.isdir(saved_dir)
            else os.path.join(os.path.expanduser("~"), "Downloads"))

        self._style()
        self._build()
        self._apply_lang()
        self._fit_window()
        self._restore_position()
        self._restore_queue()
        apply_titlebar_theme(self)
        self.update_idletasks()
        self.deiconify()                 # shown straight at its final place
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind_all("<Button-1>", self._defocus_click, add="+")
        self.after(100, self._poll)
        start_listener(self.events)      # links sent by a second launch
        self.after(4000, trim_memory)
        if can_update("app"):
            self.after(6000, lambda: threading.Thread(target=self._bg_app_check, daemon=True).start())    # startup done: drop what was only needed to start
        if COOKIES_BROWSER:              # read the cookies in the background: the first load is then as fast as without
            def _warm():
                try:
                    cached_cookies(COOKIES_BROWSER)
                except Exception:
                    log("cookies warm-up failed: " + traceback.format_exc(), "warning")
            self.after(2500, lambda: threading.Thread(target=_warm, daemon=True).start())
        if initial_url:                  # launched with a link
            self.after(300, lambda: self._open_external(initial_url))

    def _open_external(self, url):
        """Link received from a second launch: brings the window up, fills the field and loads the video."""
        try:
            if self._tray is not None or self.state() == "withdrawn":
                self._from_tray()
            else:
                if self.state() == "iconic":
                    self.deiconify()
                self.lift()
                self.attributes("-topmost", True)
                self.after(250, lambda: self.attributes("-topmost", False))
                self.focus_force()
        except tk.TclError:
            pass
        if url:
            self.url_var.set(url)
            self.load()

    # ---------------------------------------------------------- window position
    def _restore_position(self):
        """Puts the window back where it was last closed (if that spot is still on a screen)."""
        st = load_settings()
        try:
            x, y = int(st["pos"][0]), int(st["pos"][1])
        except (KeyError, TypeError, ValueError, IndexError):
            return
        vx, vy = self.winfo_vrootx(), self.winfo_vrooty()
        vw, vh = self.winfo_vrootwidth(), self.winfo_vrootheight()
        if not (vx - 200 < x < vx + vw - 150 and vy - 10 < y < vy + vh - 100):
            return
        size = ""
        try:
            min_w, min_h = self.minsize()
            w = min(max(int(st["size"][0]), min_w), vw)
            h = min_h                       # always opens at the smallest height (the queue grows it)
            size = f"{w}x{h}"
        except (KeyError, TypeError, ValueError, IndexError):
            pass
        self.geometry(f"{size}+{x}+{y}")
        if size:
            self._auto_h = h
        if st.get("zoomed"):
            self.state("zoomed")

    def _on_close(self):
        if TRAY and pystray is not None and self._tray is None:
            self._save_geometry()
            self._to_tray()                  # the app keeps running (downloads continue) in the tray
            return
        self._quit()

    def _to_tray(self):
        ev = self.events                     # tray callbacks run in another thread: go through the queue
        menu = pystray.Menu(
            pystray.MenuItem(tr("tray_open"), lambda *a: ev.put(("tray_show",)), default=True),
            pystray.MenuItem(tr("tray_quit"), lambda *a: ev.put(("tray_quit",))))
        self._tray = pystray.Icon("justayt", tray_image(), tr("title"), menu)
        self._tray.run_detached()
        self.withdraw()
        self.after(1500, trim_memory)

    def _from_tray(self):
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:
                pass
            self._tray = None
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after(250, lambda: self.attributes("-topmost", False))
        self.focus_force()

    def _save_geometry(self):
        try:
            if self.state() == "zoomed":  # keep the normal size, remember the maximized state
                save_settings(zoomed=True)
            else:
                save_settings(pos=[self.winfo_x(), self.winfo_y()],
                              size=[self.winfo_width(), self.winfo_height()], zoomed=False)
        except Exception:
            pass

    def save_queue(self):
        """The queue is kept between two launches (queue.json next to the settings)."""
        try:
            with self.lock:
                data = [item_to_json(it) for it in self.items if not it.get("removed")]
            path = queue_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            log("queue save failed: " + traceback.format_exc(), "warning")

    def _restore_queue(self):
        try:
            with open(queue_path(), encoding="utf-8") as f:
                saved = json.load(f)
        except Exception:
            return
        colors = set()
        for d in saved:
            try:
                item = item_from_json(d)
                if not item.get("url"):
                    continue
                row = QueueRow(self.list_frame, item, self)
                row.pack(fill="x")
                item["row"] = row
                row.last_pct = d.get("last_pct") or 0.0
                with self.lock:
                    self.items.append(item)
                if item["status"] == "done":
                    row.set_state("done")
                elif item["status"] == "cancelled":
                    row.set_state("cancelled")
                row.update_buttons()
                if item.get("pl_color"):
                    colors.add(item["pl_color"])
            except Exception:
                log("queue restore failed for one line: " + traceback.format_exc(), "warning")
        self.pl_count = max(self.pl_count, len(colors))
        self._load_row_thumbs([it for it in self.items if it.get("pl_color")])
        _ADDED[0] = max([_ADDED[0]] + [it.get("added", 0) for it in self.items])
        if self.items:
            self._refresh_queue()                 # the queue is shown only when it has lines
            self.canvas.yview_moveto(0)
        log(f"queue restored: {len(self.items)} line(s)")

    def _quit(self):
        log("===== app closed =====")
        self.save_queue()
        if self._tray is not None:
            try:
                self._tray.stop()
            except Exception:
                pass
        if self.state() != "withdrawn":
            self._save_geometry()
        self.destroy()

    # ------------------------------------------------------------------- UI
    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        for name, color in (("Accent", ACCENT), ("Green", GREEN), ("Red", RED), ("Orange", ORANGE)):
            s.configure(f"{name}.Horizontal.TProgressbar", troughcolor=CARD2, background=color,
                        bordercolor=CARD2, lightcolor=color, darkcolor=color, thickness=6)
        s.configure("TCombobox", fieldbackground=CARD2, background=CARD2, foreground=FG,
                    arrowcolor=MUTED, bordercolor=BORDER, lightcolor=CARD2, darkcolor=CARD2,
                    padding=6)
        s.configure("Row.TCombobox", padding=3)
        s.map("TCombobox", fieldbackground=[("disabled", CARD), ("readonly", CARD2)],
              foreground=[("disabled", DIM), ("readonly", FG)],
              selectbackground=[("readonly", CARD2)], selectforeground=[("readonly", FG)],
              arrowcolor=[("active", FG)], bordercolor=[("focus", ACCENT)])
        s.configure("Vertical.TScrollbar", background=SB, troughcolor=CARD,
                    bordercolor=CARD, lightcolor=SB, darkcolor=SB,
                    arrowcolor=MUTED, gripcount=0)
        s.layout("Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])   # no arrows, no grip icon
        s.configure("Vertical.TScrollbar", arrowsize=8, borderwidth=0, relief="flat")   # slimmer (default 14)
        s.map("Vertical.TScrollbar", background=[("active", SB_HI)])
        self.option_add("*TCombobox*Listbox.background", CARD2)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        self.option_add("*TCombobox*Listbox.font", (FONT, 11))

    def _t(self, widget, key, upper=False):
        """Register a widget whose text is translated."""
        self.i18n.append((widget, key, upper))
        return widget

    def _entry(self, parent, **kw):
        e = tk.Entry(parent, font=(FONT, 12), bg=CARD2, fg=FG, insertbackground=FG,
                     relief="flat", highlightthickness=1, highlightbackground=BORDER,
                     highlightcolor=ACCENT, **kw)
        e.bind("<Button-3>", lambda ev, w=e: self._entry_menu(w, ev))  # right click: cut / copy / paste
        return e

    def _ctx_close(self):
        top = getattr(self, "_ctx", None)
        self._ctx = None
        if top is not None:
            try:
                top.destroy()
            except tk.TclError:
                pass

    def _entry_menu(self, entry, event):
        """Right-click menu (cut / copy / paste / select all): small flat popup in the app's theme."""
        self._ctx_close()
        entry.focus_set()
        if not getattr(self, "_ctx_bound", False):      # a click anywhere else closes the menu
            self._ctx_bound = True
            self.bind_all("<Button-1>", self._ctx_outside, add="+")
            self.bind_all("<Escape>", lambda e: self._ctx_close(), add="+")
        top = self._ctx = tk.Toplevel(self)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(bg=BORDER)                        # 1 px outline
        inner = tk.Frame(top, bg=CARD2)
        inner.pack(padx=1, pady=1)
        has_sel = entry.selection_present()

        def run(action):
            self._ctx_close()
            entry.focus_set()
            action()

        def item(label, enabled, action):
            row = tk.Label(inner, text=label, anchor="w", bg=CARD2, fg=FG if enabled else DIM,
                           font=(FONT, 10), padx=16, pady=6, width=18)
            row.pack(fill="x", padx=4, pady=(4 if label == tr("ctx_cut") else 0, 0))
            if enabled:
                row.config(cursor="hand2")
                row.bind("<Enter>", lambda e: row.config(bg=BTN2_HI))
                row.bind("<Leave>", lambda e: row.config(bg=CARD2))
                row.bind("<ButtonRelease-1>", lambda e: run(action))

        item(tr("ctx_cut"), has_sel, lambda: entry.event_generate("<<Cut>>"))
        item(tr("ctx_copy"), has_sel, lambda: entry.event_generate("<<Copy>>"))
        item(tr("ctx_paste"), True, lambda: entry.event_generate("<<Paste>>"))
        tk.Frame(inner, bg=BORDER, height=1).pack(fill="x", padx=12, pady=4)
        item(tr("ctx_all"), True, lambda: entry.select_range(0, "end"))
        tk.Frame(inner, bg=CARD2, height=4).pack()
        top.update_idletasks()
        x = min(event.x_root, self.winfo_screenwidth() - top.winfo_reqwidth() - 4)
        y = min(event.y_root, self.winfo_screenheight() - top.winfo_reqheight() - 4)
        top.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def _ctx_outside(self, event):
        top = getattr(self, "_ctx", None)
        if top is not None and str(event.widget).split(".")[1:2] != str(top).split(".")[1:2]:
            self._ctx_close()

    def _res_start(self):
        self._res_val = None
        self._res_mon = ResMonitor()
        if not self._res_mon.ok:
            return

        def work():
            while True:
                try:
                    self._res_val = self._res_mon.sample()
                except Exception:
                    self._res_val = None
                time.sleep(2)
        threading.Thread(target=work, daemon=True).start()
        self._res_show()

    def _res_show(self):
        v = self._res_val
        if v:
            ram, cpu = v
            mb = ram / 1048576
            unit = "Mo" if LANG == "fr" else "MB"
            r = f"{mb / 1024:.1f} G{unit[-1]}" if mb >= 1024 else f"{mb:.0f} {unit}"
            txt = f"RAM {r} · CPU {cpu:.0f} %"
            if self.res_lbl.cget("text") != txt:
                self.res_lbl.config(text=txt)
        self.after(2000, self._res_show)

    def _build(self):
        # --- header: logo + title (centered), language switch (right)
        header = tk.Frame(self, bg=BG, height=48)
        header.pack(fill="x", padx=24, pady=(16, 6))
        header.pack_propagate(False)
        self.settings_btn = RoundButton(header, "⚙", self.show_settings, small=True, style="secondary")
        self.settings_btn.pack(side="right")  # language, theme, date format, file names
        Tooltip(self.settings_btn, lambda: tr("tip_settings"))
        self.logs_btn = RoundButton(header, "Logs", self.show_logs, small=True, style="secondary")
        self.logs_btn.pack(side="right", padx=(0, 8))
        Tooltip(self.logs_btn, lambda: tr("tip_logs"))
        self.info_btn = RoundButton(header, "", self.show_info, small=True, style="secondary")
        self._t(self.info_btn, "info_btn")
        self.info_btn.pack(side="left")
        self.res_lbl = lbl(header, "", 8, MUTED)                 # RAM / CPU used by the tool
        self.res_lbl.pack(side="left", padx=(8, 0))
        Tooltip(self.res_lbl, lambda: tr("tip_res"))
        self._res_start()
        group = tk.Frame(header, bg=BG)
        group.place(relx=0.5, rely=0.5, anchor="center")
        logo = tk.Canvas(group, width=36, height=36, bg=BG, highlightthickness=0)
        round_rect(logo, 0, 0, 36, 36, 11, fill=ACCENT, outline="")
        logo.create_line(18, 9, 18, 24, fill="#ffffff", width=3, capstyle="round")
        logo.create_line(11, 18, 18, 25, 25, 18, fill="#ffffff", width=3,
                         capstyle="round", joinstyle="round")
        logo.create_line(11, 28, 25, 28, fill="#ffffff", width=3, capstyle="round")
        logo.pack(side="left")
        self._t(lbl(group, "", 21, FG, bold=True), "title").pack(side="left", padx=(12, 0))

        # --- link card
        link_card = self.link_card = tk.Frame(self, bg=BG)  # no frame around this part
        link_card.pack(fill="x", padx=24, pady=(8, 12))
        top = tk.Frame(link_card, bg=BG)
        top.pack(padx=16, pady=(6, 8))  # centered
        self._t(lbl(top, "", 11, MUTED, bold=True), "link").pack(side="left")
        help_bubble(top, lambda: tr("tip_sites"), on_click=self.show_sites).pack(side="left", padx=(6, 0))
        self.url_var = tk.StringVar()
        # one rounded field: the link entry and the Load button live inside the same outline
        self.pill = tk.Canvas(top, bg=BG, highlightthickness=0, bd=0)
        self.pill.pack(side="left", padx=(12, 0))
        entry = self._entry(self.pill, textvariable=self.url_var, exportselection=False)
        entry.config(highlightthickness=0, bd=0, bg=CARD2)
        self.pill_entry_w = tkfont.Font(family=FONT, size=12).measure("0") * 52
        entry.bind("<FocusIn>", lambda e: self._pill_focus(True), add="+")
        entry.bind("<FocusOut>", lambda e: self._pill_focus(False), add="+")
        entry.bind("<Return>", lambda e: self.load())
        entry.bind("<<Paste>>", lambda e: self.after(80, self._check_pasted))
        self.url_var.trace_add("write", lambda *a: self._set_url_error(False))
        # error message: shown over the link field itself (no layout shift); a click dismisses it
        self.url_entry = entry
        self.url_err = lbl(top, "", 10, RED, cursor="hand2")
        self.url_err.config(bg=CARD2)
        self.url_err.bind("<Button-1>", self._url_err_click)
        entry.bind("<Button-1>", self._url_click)
        self.load_btn = RoundButton(self.pill, "", self.load)  # same size as the other main buttons
        self.load_btn.config(bg=CARD2)  # its corners blend into the field
        self._t(self.load_btn, "load")
        # small cross at the right end of the text area: clears the link (only shown when there is text)
        self.url_clear_btn = icon_button(self.pill, "✕", self._clear_url, size=11, hover="RED")
        self.url_clear_btn.config(bg=CARD2, activebackground=CARD2)
        Tooltip(self.url_clear_btn, lambda: tr("tip_clear"))
        self.url_var.trace_add("write", lambda *a: self._show_clear())
        self._layout_pill()

        # --- video card: thumbnail, info, options
        vcard = card(self)
        vcard.pack(fill="x", padx=24, pady=(0, 20))  # same 20 px gap as link -> video card
        mid = tk.Frame(vcard, bg=CARD)
        mid.pack(fill="x", padx=16, pady=18)

        self.placeholder = tk.PhotoImage(width=210, height=118)
        self.placeholder.put(CARD2, to=(0, 0, 210, 118))
        self.thumb_label = tk.Label(mid, image=self.placeholder, compound="center", bg=CARD2,
                                    fg=DIM, font=(FONT, 13), bd=0)
        self.thumb_label.grid(row=0, column=0, sticky="n")
        self.thumb_label.bind("<Button-1>", lambda e: self.current and self.show_thumbs(
            self.current.get("thumbs"), self.current.get("title")))
        for _b in ("<Button-3>", "<Button-2>") if sys.platform == "darwin" else ("<Button-3>",):
            self.thumb_label.bind(_b, lambda e: self.current and self.current.get("thumbs") and self.thumb_menu(
                e, self.current["thumbs"][0], self.current.get("title")))

        # grid: the middle column (title + facts) takes the free width and may shrink, so the
        # options on the right are never pushed out of the card
        mid.columnconfigure(1, weight=1, minsize=0)
        meta = tk.Frame(mid, bg=CARD)
        meta.grid(row=0, column=1, sticky="nw", padx=(18, 24))
        self.title_lbl = lbl(meta, "", 14, FG, bold=True, wraplength=290, justify="left", anchor="w")
        self.title_lbl.pack(anchor="w")

        def fit_title(_e=None):
            """The title wraps at the width the card really gives it."""
            if not hasattr(self, "opts_frame"):
                return
            free = (mid.winfo_width() - self.thumb_label.winfo_reqwidth()
                    - self.opts_frame.winfo_reqwidth() - 18 - 24)      # paddings around the title
            self.title_lbl.config(wraplength=max(160, free))
            self._set_title(self._full_title)

        def set_title(text):
            """At most 2 lines: the rest is cut with an ellipsis (a long title never grows the card)."""
            self._full_title = text
            try:
                f = tkfont.Font(font=self.title_lbl.cget("font"))
                room = max(160, int(self.title_lbl.cget("wraplength"))) - 4
                lines, cur = [], ""
                for w in text.split():
                    t = (cur + " " + w).strip()
                    if f.measure(t) <= room or not cur:
                        cur = t
                    else:
                        lines.append(cur)
                        cur = w
                lines.append(cur)
                if len(lines) > 2:
                    lines = [lines[0], " ".join(lines[1:])]
                lines = [fit_text(l, f, room) for l in lines]
                text = "\n".join(lines)
            except Exception:
                pass
            self.title_lbl.config(text=text)
        self._full_title = ""
        self._set_title = set_title
        Tooltip(self.title_lbl, lambda: self._full_title
                if " ".join(self.title_lbl.cget("text").split()) != " ".join(self._full_title.split()) else "")
        mid.bind("<Configure>", fit_title)
        facts = tk.Frame(meta, bg=CARD)  # one line: upload date | duration | estimated size
        facts.pack(anchor="w", pady=(10, 0))
        self.date_lbl = lbl(facts, "", 11, MUTED, anchor="w")
        self.date_lbl.grid(row=0, column=0, sticky="w")
        self.len_lbl = lbl(facts, "", 11, MUTED, anchor="w")
        self.len_lbl.grid(row=0, column=1, sticky="w", padx=(22, 0))
        # estimated size of the chosen quality + trim
        self.est_size_lbl = lbl(facts, "", 11, MUTED, anchor="w")
        self.est_size_lbl.grid(row=0, column=2, sticky="w", padx=(22, 0))

        opts = tk.Frame(mid, bg=CARD)
        opts.grid(row=0, column=2, sticky="ne")
        self.opts_frame = opts
        opts.bind("<Configure>", fit_title, add="+")
        self._t(lbl(opts, "", 11, MUTED, bold=True), "quality").grid(row=0, column=0, sticky="e", pady=5)
        self.quality = ttk.Combobox(opts, state="readonly", width=8, font=(FONT, 11),
                                    style="Row.TCombobox")  # narrower and less tall
        self.quality.grid(row=0, column=1, columnspan=2, sticky="w", padx=12)
        self.quality.bind("<<ComboboxSelected>>", lambda e: self._refresh_estimate(), add="+")

        trim_head = tk.Frame(opts, bg=CARD)
        trim_head.grid(row=1, column=0, sticky="e", pady=5)
        self._t(lbl(trim_head, "", 11, MUTED, bold=True), "trim").pack(side="left")
        help_bubble(trim_head, lambda: tr("tip_trim") if has_ffmpeg() else tr("tip_trim_off")
                    ).pack(side="left", padx=(6, 0))
        self.trim_widgets = [trim_head]      # hidden while a live stream is loaded
        self.use_start, self.use_end = tk.BooleanVar(), tk.BooleanVar()
        self.start_in, self.end_in = TimeInput(opts), TimeInput(opts)
        for row, (key, var, tin) in enumerate(
                (("start", self.use_start, self.start_in), ("end", self.use_end, self.end_in)), start=1):
            cb = tk.Checkbutton(opts, variable=var, command=self._toggle_trim, bg=CARD, fg=FG,
                                selectcolor=CARD2, activebackground=CARD, activeforeground=FG,
                                disabledforeground=DIM, highlightthickness=0, bd=0,
                                font=(FONT, 11), anchor="w", width=7)
            self._t(cb, key)
            self.trim_cbs.append(cb)
            self.trim_widgets += [cb, tin]
            Tooltip(cb, lambda: "" if has_ffmpeg() else tr("tip_trim_off"))
            cb.grid(row=row, column=1, sticky="w", padx=(8, 0), pady=3)
            tin.grid(row=row, column=2, sticky="w")
            tin.on_change = self._refresh_trim
            for ent in tin.entries:
                Tooltip(ent, lambda t=tin: tr("trim_bad") if t.invalid else "")

        # live stream detected: record from its start (checked) or from now on (unchecked)
        self.live_var = tk.BooleanVar(value=LIVE_FROM_START)
        self.live_cb = tk.Checkbutton(opts, variable=self.live_var, bg=CARD, fg=FG, selectcolor=CARD2,
                                      activebackground=CARD, activeforeground=FG, highlightthickness=0,
                                      bd=0, font=(FONT, 11), anchor="w")
        self._t(self.live_cb, "live_cb")
        self.live_cb.grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.live_cb.grid_remove()

        # --- one line: folder + path (left), add / download (right); extra space below while the
        # queue is hidden
        self.btns = tk.Frame(self, bg=BG)
        self.btns.pack(fill="x", padx=24, pady=(0, 28))
        right = tk.Frame(self.btns, bg=BG)  # packed first: the buttons are never pushed out
        right.pack(side="right")
        self.hist_btn = RoundButton(right, "", self.show_history, style="history")
        self._t(self.hist_btn, "hist_btn")
        self.hist_btn.pack(side="left", padx=(0, 10))
        self.pick_btn = RoundButton(right, "", self.pick_videos, style="secondary")   # only shown for a playlist
        self._t(self.pick_btn, "pick_btn")
        self.add_btn = RoundButton(right, "", self.add_to_queue, style="secondary", state="disabled")
        self._t(self.add_btn, "add")
        self.add_btn.pack(side="left", padx=(0, 10))
        self.dl_btn = RoundButton(right, "", self.download_now, state="disabled")
        self._t(self.dl_btn, "download")
        self.dl_btn.pack(side="left")
        self._pick_shown = False
        left = tk.Frame(self.btns, bg=BG)
        left.pack(side="left", fill="x", expand=True)
        folder_btn = RoundButton(left, "", self.choose_dir, style="secondary")  # same size as the others
        self._t(folder_btn, "folder")
        folder_btn.pack(side="left")
        lbl(left, "", 10, MUTED, textvariable=self.outdir, anchor="w").pack(side="left", padx=12)

        # --- ffmpeg warning (packed before the queue so it always keeps its place)
        if not has_ffmpeg():
            self.ffmpeg_warn = lbl(self, "", 10, ORANGE)
            self._t(self.ffmpeg_warn, "no_ffmpeg")
            self.ffmpeg_warn.pack(side="bottom", pady=(0, 8))

        # --- queue (hidden while empty)
        self.queue_box = tk.Frame(self, bg=BG)

        wrap = card(self.queue_box)
        wrap.pack(fill="both", expand=True, padx=24, pady=(8, 20))  # 20 px like link -> video card

        self.head = tk.Frame(wrap, bg=CARD)
        self.head.pack(fill="x")
        setup_cols(self.head)
        keys = ("col_added", "col_title", "col_length", "col_date", "col_quality", "col_trim", "col_progress", "")
        for i, key in enumerate(keys):
            h = lbl(self.head, "", 9, MUTED, bold=True)
            h.grid(row=0, column=i, pady=9, sticky="w" if i == 1 else "", padx=4 if i == 1 else 0)
            if key:
                self._t(h, key, upper=True)
            if i in SORT_KEYS:  # click = sort the queue by this column
                h.config(cursor="hand2")
                h.bind("<Button-1>", lambda e, c=i: self.sort_queue(c))
                self.sort_heads[i] = (h, key)
        tk.Frame(wrap, bg=BORDER, height=1).pack(fill="x")

        body = tk.Frame(wrap, bg=CARD)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, bg=CARD, highlightthickness=0, height=1)
        self.sb = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.list_frame = tk.Frame(self.canvas, bg=CARD)
        self.list_frame.bind("<Configure>", lambda e: (
            self.canvas.configure(scrollregion=self.canvas.bbox("all")), self._update_scrollbar()))
        win = self.canvas.create_window((0, 0), window=self.list_frame, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: (
            self.canvas.itemconfig(win, width=e.width), self._update_scrollbar()))
        self.canvas.configure(yscrollcommand=self.sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)  # scrollbar is packed on demand
        self.bind_all("<MouseWheel>", self._on_wheel)

        bar = tk.Frame(self.queue_box, bg=BG)
        bar.pack(side="bottom", fill="x", padx=24, pady=(0, 16), before=wrap)  # always visible
        self.dlq_btn = RoundButton(bar, "", self.start_queue)   # becomes "Stop queue" while downloading
        self.dlq_btn.pack(side="right")
        self._update_stop_btn()
        self.clear_btn = RoundButton(bar, "", self.clear_queue, style="danger")
        self._t(self.clear_btn, "clear_queue")
        self.clear_btn.pack(side="right", padx=(0, 10))
        self.sched_at = None                     # (hour, minute) the queue starts at; not kept between launches
        self.after_action = "none"               # none / sleep / shutdown when the queue ends (one-shot)
        self._sched_target = None
        self.qopts_btn = RoundButton(bar, "", self.queue_options, style="secondary")
        self._t(self.qopts_btn, "q_opts")
        self.qopts_btn.pack(side="left")
        self.qopts_lbl = lbl(bar, "", 10, MUTED)
        self.qopts_lbl.pack(side="left", padx=(12, 0))

        self._update_trim_availability()

    # ------------------------------------------------------------ compatible sites
    def show_sites(self):
        """Small window listing the sites yt-dlp supports, with a search field."""
        if self.sites_win is not None and self.sites_win.winfo_exists():
            self.sites_win.lift()
            self.sites_win.focus_force()
            return
        win = self.sites_win = tk.Toplevel(self)
        win.title(tr("sites_title"))
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self)
        win.bind("<Escape>", lambda e: win.destroy())
        box = card(win)
        box.pack(padx=20, pady=20)
        inner = tk.Frame(box, bg=CARD)
        inner.pack(padx=24, pady=20)

        sites = supported_sites()
        count = lbl(inner, "", 10, MUTED)
        count.pack(anchor="w", pady=(0, 10))
        var = tk.StringVar()
        search = self._entry(inner, textvariable=var, width=34)
        search.pack(fill="x", ipady=5)

        frame = tk.Frame(inner, bg=CARD)
        frame.pack(pady=(10, 0))
        sb = ttk.Scrollbar(frame, orient="vertical")
        lb = tk.Listbox(frame, width=36, height=14, bg=CARD2, fg=FG, font=(FONT, 11), relief="flat",
                        highlightthickness=1, highlightbackground=BORDER, highlightcolor=BORDER,
                        selectbackground=ACCENT, selectforeground="#ffffff", activestyle="none",
                        yscrollcommand=sb.set, exportselection=False)
        sb.config(command=lb.yview)
        lb.pack(side="left")
        sb.pack(side="left", fill="y")

        def fill(*_):
            q = var.get().strip().casefold()
            shown = [s for s in sites if q in s.casefold()]
            lb.delete(0, "end")
            lb.insert("end", *shown)
            count.config(text=tr("sites_count", n=len(shown)))

        var.trace_add("write", fill)
        fill()
        link = tk.Label(inner, text="↗ " + tr("info_sites"), bg=CARD, fg=ACCENT_HI, cursor="hand2",
                        font=(FONT, 11, "underline"))
        link.pack(anchor="w", pady=(12, 0))
        link.bind("<Button-1>", lambda e: webbrowser.open(SITES_URL))
        btn_row = tk.Frame(inner, bg=CARD)
        btn_row.pack(fill="x", pady=(14, 0))
        RoundButton(btn_row, tr("info_close"), win.destroy, small=True, style="secondary").pack(side="right")

        win.update_idletasks()
        self._center(win)
        apply_titlebar_theme(win)
        search.focus_set()

    # ------------------------------------------------------------ settings
    def show_settings(self, geometry=None, replace=None):
        """Settings window: language, theme, date format, file-name template."""
        if self.settings_win is not None and self.settings_win.winfo_exists():
            self.settings_win.lift()
            self.settings_win.focus_force()
            return
        win = self.settings_win = tk.Toplevel(self)
        win.withdraw()                       # shown once fully built (no flicker)
        start_tab = getattr(self, "_settings_tab", "general")
        win.title(tr("settings_title"))
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self)
        win.bind("<Escape>", lambda e: win.destroy())
        # sidebar on the left (full height), one page of settings rows on the right
        body = tk.Frame(win, bg=CARD)
        body.pack(fill="both", expand=True)
        tabbar = tk.Frame(body, bg=BG, width=176)
        tabbar.pack(side="left", fill="y")
        tabbar.pack_propagate(False)
        tk.Frame(tabbar, bg=BG, height=12).pack()
        side = tk.Frame(body, bg=CARD)
        side.pack(side="left", fill="both", expand=True)
        content = tk.Frame(side, bg=CARD)
        content.pack(padx=28, pady=(24, 0), anchor="w")
        footer = tk.Frame(side, bg=CARD)
        footer.pack(fill="x", padx=28, pady=(14, 18))
        pages = {k: tk.Frame(content, bg=CARD) for k in ("general", "dl", "notif", "adv")}
        tab_ui = {}

        def show_tab(k):
            self._settings_tab = k
            for page in pages.values():
                page.pack_forget()
            pages[k].pack(fill="x", anchor="nw")
            for kk, (f_, bar_, l_) in tab_ui.items():
                on = kk == k
                bg_ = CARD if on else BG
                for w_ in (f_, l_):
                    w_.config(bg=bg_)
                bar_.config(bg=ACCENT if on else BG)
                l_.config(fg=FG if on else MUTED, font=(FONT, 11, "bold" if on else "normal"))

        for k in pages:
            f_ = tk.Frame(tabbar, bg=BG, cursor="hand2")
            bar_ = tk.Frame(f_, bg=BG, width=3)
            bar_.pack(side="left", fill="y")
            l_ = tk.Label(f_, text=tr("tab_" + k), bg=BG, fg=MUTED, font=(FONT, 11), anchor="w",
                          padx=16, pady=11, cursor="hand2")
            l_.pack(side="left", fill="x", expand=True)
            f_.pack(fill="x")
            tab_ui[k] = (f_, bar_, l_)
            for w_ in (f_, bar_, l_):
                w_.bind("<Button-1>", lambda e, k=k: show_tab(k))
            l_.bind("<Enter>", lambda e, k=k: self._settings_tab != k and tab_ui[k][2].config(fg=FG))
            l_.bind("<Leave>", lambda e, k=k: self._settings_tab != k and tab_ui[k][2].config(fg=MUTED))
        rows_n = {}

        def setting(page, title, hint=None, wide=True):
            """One settings row: the title takes the whole line (small accent bar before it), then the grey
            explanation, then the control underneath."""
            row = tk.Frame(page, bg=CARD)
            row.pack(fill="x", pady=(0 if not rows_n.get(page) else 22, 0))
            rows_n[page] = rows_n.get(page, 0) + 1
            head = tk.Frame(row, bg=CARD)
            head.pack(fill="x")
            lbl(head, title, 11, FG, bold=True, anchor="w").pack(side="left")
            if hint:
                lbl(row, hint, 10, MUTED, justify="left", wraplength=470, anchor="w").pack(anchor="w", pady=(4, 0))
            ctrl = tk.Frame(row, bg=CARD)
            ctrl.pack(anchor="w", pady=(10, 0))
            return ctrl

        def segmented(parent, options, current, on_pick, per_row=None, style_for=None):
            """Row(s) of buttons, the chosen one highlighted."""
            btns = {}
            rows = []
            for i in range(0, len(options), per_row or len(options)):
                r_ = tk.Frame(parent, bg=CARD)
                r_.pack(anchor="w", pady=(0 if i == 0 else 8, 0))
                rows.append(r_)

            def pick(value):
                on_pick(value)
                for v, b in btns.items():
                    if b.winfo_exists():
                        b.config(style=style_for(v, value) if style_for else ("primary" if v == value else "secondary"))

            for n_, (value, label) in enumerate(options):
                row = rows[n_ // (per_row or len(options))]
                b = RoundButton(row, label, lambda v=value: pick(v), small=True,
                                style=style_for(value, current) if style_for else ("primary" if value == current else "secondary"))
                b.pack(side="left", padx=(0, 8))
                btns[value] = b
            return rows, btns

        segmented(setting(pages["general"], tr("set_lang")), (("fr", "Français"), ("en", "English")), LANG, self.set_lang)
        trow_ = setting(pages["general"], tr("set_theme"), wide=True)
        for k_ in ("dark", "light", "sakura", "cyberpunk", "hacker"):   # each chip is drawn in its own theme
            ThemeChip(trow_, tr("theme_" + k_), k_, k_ == THEME, lambda k=k_: self.set_theme_choice(k)
                      ).pack(side="left", padx=(0, 8))
        segmented(setting(pages["general"], tr("set_date")),
                  tuple((k, tr("date_" + k)) for k in ("eu", "us", "iso")), DATE_FMT, self.set_date_fmt)

        srow = setting(pages["dl"], tr("set_speed"), wide=True)
        speed_var = tk.StringVar(value=f"{SPEED_VALUE:g}" if SPEED_VALUE > 0 else "")
        # "unlimited" box, same look as the field; the blue outline marks the active one
        inf_btn = tk.Frame(srow, bg=CARD2, highlightthickness=1, cursor="hand2")
        inf_lbl = tk.Label(inf_btn, text="∞  " + tr("speed_unlimited"), bg=CARD2, fg=FG,
                           font=(FONT, 12), cursor="hand2")
        inf_lbl.pack(padx=14, pady=5)
        inf_btn.pack(side="left")
        lbl(srow, tr("speed_or"), 11, MUTED).pack(side="left", padx=12)  # one of the two applies
        speed_ent = self._entry(srow, textvariable=speed_var, width=7, justify="center")
        speed_ent.pack(side="left", ipady=5)
        lbl(srow, tr("speed_unit"), 11, MUTED).pack(side="left", padx=(8, 0))

        def speed_look():
            limited = SPEED_LIMIT > 0        # the blue outline marks what is applied
            inf_btn.config(highlightbackground=BORDER if limited else ACCENT,
                           highlightcolor=BORDER if limited else ACCENT)
            ring = ACCENT if limited else BORDER
            speed_ent.config(highlightbackground=ring, highlightcolor=ring)

        def refresh_speed():
            apply_speed()
            speed_look()
            self._schedule_save()
            self._refresh_estimate()

        def set_unlimited(_e=None):
            global SPEED_UNLIM
            SPEED_UNLIM = True               # the typed limit stays in the field, just not applied
            refresh_speed()
            win.focus_set()

        def pick_limit(_e=None):
            global SPEED_UNLIM
            if SPEED_UNLIM and SPEED_VALUE > 0:  # click in the field: the saved limit applies again
                SPEED_UNLIM = False
                refresh_speed()

        for w_ in (inf_btn, inf_lbl):
            w_.bind("<Button-1>", set_unlimited)
        speed_ent.bind("<FocusIn>", pick_limit)
        speed_look()

        def on_speed(*_):
            global SPEED_VALUE, SPEED_UNLIM
            txt = speed_var.get().strip().replace(",", ".")
            try:
                val = float(txt) if txt else 0.0
            except ValueError:
                return  # not a number (yet): keep the previous limit
            SPEED_VALUE = max(val, 0.0)
            if SPEED_VALUE > 0:
                SPEED_UNLIM = False          # typing a limit = choosing it
            refresh_speed()

        speed_var.trace_add("write", on_speed)

        def speed_wheel(e):
            """Mouse wheel over the field: +1 / -1 MB/s (never below 0)."""
            try:
                cur = float(speed_var.get().strip().replace(",", ".") or 0)
            except ValueError:
                cur = 0.0
            speed_var.set(f"{max(cur + (1 if e.delta > 0 else -1), 0):g}")
            return "break"

        speed_ent.bind("<MouseWheel>", speed_wheel)


        def set_codec(v):
            global VIDEO_CODEC, COMPAT_EDIT
            VIDEO_CODEC, COMPAT_EDIT = v, v == "h264"
            save_settings(codec=v, compat_edit=COMPAT_EDIT)
        segmented(setting(pages["adv"], tr("set_codec"), tr("codec_hint"), wide=True),
                  (("h264", tr("codec_h264")), ("best", tr("codec_best")), ("vp9", tr("codec_vp9")), ("av1", tr("codec_av1"))),
                  VIDEO_CODEC, set_codec)

        def set_retry(v):
            global AUTO_RETRY
            AUTO_RETRY = int(v)
            save_settings(retry=AUTO_RETRY)
        segmented(setting(pages["adv"], tr("set_retry"), tr("retry_hint")),
                  (("0", tr("retry_off")), ("1", "1"), ("2", "2"), ("3", "3"), ("5", "5")), str(AUTO_RETRY), set_retry)

        ck_box = setting(pages["adv"], tr("set_cookies"), tr("cookies_why"), wide=True)

        def set_cookies(v):
            global COOKIES_BROWSER
            COOKIES_BROWSER = v
            save_settings(cookies_browser=v)
            self._test_cookies()
        self._ck_status = {}      # browser -> True (cookies found) / False (none), set by "Check cookies"

        def ck_style(v, chosen):
            if v == chosen:
                return "primary"
            st = self._ck_status.get(v)
            return "secondary" if st is None or not v else ("ck_ok" if st else "ck_bad")
        _, self._ck_btns = segmented(ck_box, (("", tr("cookies_none")),) + COOKIE_BROWSERS, COOKIES_BROWSER, set_cookies,
                                     style_for=ck_style)
        self._ck_style = ck_style
        ck_row = tk.Frame(ck_box, bg=CARD)
        ck_row.pack(anchor="w", pady=(10, 0))
        # result to the right of the button; room for 3 lines is kept so it never covers the text below
        ck_res = tk.Frame(ck_row, bg=CARD, width=470, height=36)
        ck_res.pack(side="left")
        ck_res.pack_propagate(False)
        self._ck_lbl = lbl(ck_res, "", 10, MUTED, justify="left", wraplength=470, anchor="w")
        self._ck_lbl.pack(anchor="w")
        self._ck_url = ""
        self._ck_link = tk.Label(ck_res, text="", bg=CARD, fg=ACCENT_HI, cursor="hand2", font=(FONT, 10, "underline"))
        self._ck_link.bind("<Button-1>", lambda e: self._ck_url and webbrowser.open(self._ck_url))
        self._test_cookies()

        # manual import: a cookies.txt exported from any browser
        imp_row = tk.Frame(ck_box, bg=CARD)
        imp_row.pack(anchor="w", pady=(2, 0))
        imp_lbl = lbl(imp_row, "", 10, MUTED, anchor="w")
        rm_btn = RoundButton(imp_row, tr("ck_remove"), lambda: None, small=True, style="secondary")

        def file_status():
            path = cookies_file_path()
            if os.path.exists(path):
                imp_lbl.config(text=tr("ck_file_ok", n=count_cookies_file(path)), fg=GREEN)
                rm_btn.pack(side="left", padx=(10, 0))
            else:
                imp_lbl.config(text="")
                rm_btn.pack_forget()

        def import_cookies():
            src = filedialog.askopenfilename(parent=win, title=tr("ck_import"),
                                             filetypes=[("cookies.txt", "*.txt"), ("*", "*.*")])
            if not src:
                return
            if count_cookies_file(src) == 0:
                imp_lbl.config(text=tr("ck_file_bad"), fg=RED)
                rm_btn.pack_forget()
                return
            try:
                shutil.copyfile(src, cookies_file_path())
            except OSError as ex:
                imp_lbl.config(text="✖ " + str(ex)[:80], fg=RED)
                return
            file_status()

        def remove_cookies():
            try:
                os.remove(cookies_file_path())
            except OSError:
                pass
            file_status()

        rm_btn.config(command=remove_cookies)
        imp_btn = RoundButton(imp_row, tr("ck_import"), import_cookies, small=True, style="secondary")
        imp_btn.pack(side="left")
        imp_lbl.pack(side="left", padx=(10, 0))
        lbl(ck_box, tr("cookies_import_hint"), 10, MUTED, justify="left", wraplength=470,
            anchor="w").pack(anchor="w", pady=(6, 0))
        file_status()


        def set_live(v):
            global LIVE_FROM_START
            LIVE_FROM_START = v == "start"
            save_settings(live_start=LIVE_FROM_START)
        segmented(setting(pages["dl"], tr("set_live"), tr("live_hint")),
                  (("now", tr("live_now")), ("start", tr("live_start"))), "start" if LIVE_FROM_START else "now", set_live)

        def set_trimmode(v):
            global FAST_TRIM
            FAST_TRIM = v == "fast"
            save_settings(fast_trim=FAST_TRIM)
        segmented(setting(pages["dl"], tr("set_trimmode"), tr("trimmode_hint")),
                  (("exact", tr("trim_exact")), ("fast", tr("trim_fast"))), "fast" if FAST_TRIM else "exact", set_trimmode)

        def set_toast(v):
            global NOTIFY_TOAST
            NOTIFY_TOAST = v == "on"
            save_settings(notify_toast=NOTIFY_TOAST)
        segmented(setting(pages["notif"], tr("notif_toast")), (("on", tr("notif_on")), ("off", tr("notif_off"))),
                  "on" if NOTIFY_TOAST else "off", set_toast)

        def set_sound(v):
            global NOTIFY_SOUND
            NOTIFY_SOUND = v == "on"
            save_settings(notify_sound=NOTIFY_SOUND)
        segmented(setting(pages["notif"], tr("notif_sound")), (("on", tr("notif_on")), ("off", tr("notif_off"))),
                  "on" if NOTIFY_SOUND else "off", set_sound)

        def set_tone(v):
            global NOTIFY_TONE
            NOTIFY_TONE = int(v)
            save_settings(notify_tone=NOTIFY_TONE)
            play_chime()                             # preview
        segmented(setting(pages["notif"], tr("notif_tone"), wide=True),
                  tuple((str(k), tr(f"tone_{k}")) for k in (1, 2, 3, 4)), str(NOTIFY_TONE), set_tone)

        vrow_ = setting(pages["notif"], tr("vol"))
        pct = lbl(vrow_, f"{NOTIFY_VOL}%", 10, MUTED, width=5, anchor="e")

        def vol_changed(v):
            global NOTIFY_VOL
            NOTIFY_VOL = v
            pct.config(text=f"{v}%")

        def vol_released(v):
            save_settings(notify_vol=NOTIFY_VOL)
            play_chime()                                  # preview
        Slider(vrow_, NOTIFY_VOL, vol_changed, vol_released).pack(side="left")
        pct.pack(side="left", padx=(8, 0))

        def set_style(v):
            global NOTIFY_STYLE
            NOTIFY_STYLE = int(v)
            save_settings(notify_style=NOTIFY_STYLE)
            self.show_toast(tr("toast_done"), (self.current or {}).get("title") or tr("sample_title"),
                            lambda: None, (self.current or {}).get("thumb"), lambda: None)      # preview
        segmented(setting(pages["notif"], tr("notif_style"), wide=True),
                  tuple((str(k), tr(f"style_{k}")) for k in (1, 2, 3)), str(NOTIFY_STYLE), set_style)
        trow = tk.Frame(pages["notif"], bg=CARD)
        trow.pack(anchor="w", pady=(18, 0))
        RoundButton(trow, tr("notif_test"), lambda: (play_chime(), self.show_toast(
            tr("toast_done"), (self.current or {}).get("title") or tr("sample_title"), lambda: None,
            (self.current or {}).get("thumb"), lambda: None)), small=True, style="secondary").pack(side="left")

        if pystray is None:
            setting(pages["general"], tr("set_close"), tr("close_need"))
        else:
            def set_close(v):
                global TRAY
                TRAY = v == "tray"
                save_settings(tray=TRAY)
            segmented(setting(pages["general"], tr("set_close")), (("quit", tr("close_quit")), ("tray", tr("close_tray"))),
                      "tray" if TRAY else "quit", set_close)

        inner = setting(pages["dl"], tr("set_name"), wide=True)
        var = tk.StringVar(value=NAME_TPL)
        ent = self._entry(inner, textvariable=var, width=42)
        ent.pack(fill="x", ipady=5)
        vrow = tk.Frame(inner, bg=CARD)
        vrow.pack(anchor="w", pady=(8, 0))
        lbl(vrow, tr("name_vars"), 10, MUTED).pack(side="left", padx=(0, 6))
        for v in ("title", "channel", "length", "date", "views"):
            RoundButton(vrow, "{" + v + "}", lambda v=v: (ent.insert("insert", "{" + v + "}"), ent.focus_set()),
                        small=True, style="secondary").pack(side="left", padx=(0, 6))
        example = lbl(inner, "", 10, MUTED, justify="left", wraplength=420)
        example.pack(anchor="w", pady=(10, 0))
        actions = tk.Frame(inner, bg=CARD)
        actions.pack(fill="x", pady=(14, 0))
        RoundButton(actions, tr("name_default"), lambda: var.set(DEFAULT_TPL), small=True,
                    style="secondary").pack(side="left")
        RoundButton(footer, tr("settings_save"),
                    lambda: (self._persist_settings(), win.destroy()), small=True
                    ).pack(side="right")

        def sample():
            c = self.current or {"title": tr("sample_title"), "channel": tr("sample_channel"),
                                 "duration": 754, "date_raw": "20261103", "view_count": 12345}
            return c

        def refresh_example():
            if example.winfo_exists():
                example.config(text=tr("name_example", v=make_name(sample(), var.get()) + ".mp4"))

        self._settings_example = refresh_example  # also called when the date format changes

        def on_tpl(*_):
            global NAME_TPL
            tpl = var.get()
            refresh_example()
            if tpl.strip():
                NAME_TPL = tpl
                self.apply_name_template()
                self._schedule_save()

        var.trace_add("write", on_tpl)
        on_tpl()

        def closed(e):
            if e.widget is win and self._tpl_save_id:
                self._persist_settings()

        win.bind("<Destroy>", closed, add="+")
        for k in pages:                       # the window keeps one size whatever the tab
            show_tab(k)
            win.update_idletasks()
        content.config(width=max(p.winfo_reqwidth() for p in pages.values()),
                       height=max(p.winfo_reqheight() for p in pages.values()))
        content.pack_propagate(False)
        show_tab(start_tab)
        win.update_idletasks()
        apply_titlebar_theme(win)
        try:
            win.attributes("-alpha", 0.0)    # shown invisible first: centred on its real size, no jump
        except tk.TclError:
            pass
        win.deiconify()
        win.update()
        if geometry:                         # rebuilt window (language / theme): same centre as the old one
            ox, oy, ow, oh = geometry
            nx = max(ox + (ow - win.winfo_width()) // 2, 0)
            ny = max(oy + (oh - win.winfo_height()) // 2, 0)
            win.geometry(f"+{nx}+{ny}")
        else:
            self._center(win)
        win.update_idletasks()
        try:
            win.attributes("-alpha", 1.0)
        except tk.TclError:
            pass
        if replace is not None:              # the old window goes only once the new one is on screen
            try:
                replace.destroy()
            except tk.TclError:
                pass

    def _ck_show(self, text, fg, url=""):
        """Cookie test result; with a link "click here for more info" when the error carries one."""
        self._ck_lbl.config(text=text, fg=fg)
        self._ck_url = url
        if url:
            self._ck_link.config(text=tr("ck_more"))
            self._ck_link.pack(anchor="w")
        else:
            self._ck_link.pack_forget()

    def _test_cookies(self):
        """Reads the chosen browser's cookies in the background and shows a tick / cross with the result."""
        lbl_ = getattr(self, "_ck_lbl", None)
        try:
            if lbl_ is None or not lbl_.winfo_exists():
                return
            if not COOKIES_BROWSER:
                self._ck_show("", MUTED)
                return
            self._ck_show(tr("ck_testing"), MUTED)
        except tk.TclError:
            return
        threading.Thread(target=self._cookie_worker, args=(COOKIES_BROWSER,), daemon=True).start()

    def _cookie_worker(self, browser):
        try:
            cookies = cached_cookies(browser, force=True)
            yt = sum(1 for c in cookies if "youtube.com" in (c.domain or "") or "google.com" in (c.domain or ""))
            log(f"cookies test ({browser}): {len(cookies)} cookies, {yt} youtube/google")
            self.events.put(("cookie_test", browser, True, len(cookies), yt, ""))
        except Exception as e:
            log(f"cookies test ({browser}) failed: {clean(str(e))}", "warning")
            self.events.put(("cookie_test", browser, False, 0, 0, clean(str(e))[:160]))

    def show_history(self):
        """Finished downloads (newest first): open the file or its folder."""
        if self.hist_win is not None and self.hist_win.winfo_exists():
            self.hist_win.lift()
            self.hist_win.focus_force()
            return
        win = self.hist_win = tk.Toplevel(self)
        win.title(tr("hist_title"))
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self)
        win.bind("<Escape>", lambda e: win.destroy())
        box = card(win)
        box.pack(padx=20, pady=20)
        inner = tk.Frame(box, bg=CARD)
        inner.pack(padx=22, pady=18)
        lbl(inner, tr("hist_title"), 14, FG, bold=True).pack(anchor="w", pady=(0, 10))
        data = load_history()
        f11 = tkfont.Font(family=FONT, size=11)
        if not data:
            lbl(inner, tr("hist_empty"), 11, MUTED).pack(anchor="w", pady=20)
        else:
            state = {"sort": "new"}
            ctl = tk.Frame(inner, bg=CARD)               # search + sort
            ctl.pack(fill="x", pady=(0, 10))
            qvar = tk.StringVar()
            lbl(ctl, tr("hist_search"), 10, MUTED).pack(side="left", padx=(0, 8))
            qent = self._entry(ctl, textvariable=qvar, width=26)
            qent.pack(side="left", ipady=4)
            sort_btns = {}
            for key_, label_ in (("name", tr("hist_sort_name")), ("old", tr("hist_sort_old")), ("new", tr("hist_sort_new"))):
                sort_btns[key_] = RoundButton(ctl, label_, lambda k=key_: set_sort(k), small=True,
                                              style="primary" if key_ == "new" else "secondary")
                sort_btns[key_].pack(side="right", padx=(6, 0))
            listbox = tk.Frame(inner, bg=CARD2, highlightthickness=1, highlightbackground=BORDER)
            listbox.pack(fill="both")
            canvas = tk.Canvas(listbox, bg=CARD2, highlightthickness=0, width=640, height=360)
            sb = ttk.Scrollbar(listbox, orient="vertical", command=canvas.yview)
            canvas.configure(yscrollcommand=sb.set)
            canvas.pack(side="left", fill="both")
            frame = tk.Frame(canvas, bg=CARD2)
            canvas.create_window((0, 0), window=frame, anchor="nw")

            def wheel(e):
                canvas.yview_scroll(int(-e.delta / 120), "units")
                return "break"

            def populate(*_):
                for w_ in frame.winfo_children():
                    w_.destroy()
                q = qvar.get().strip().casefold()
                rows = [e for e in data if q in (e.get("title") or "").casefold()]
                if state["sort"] == "name":
                    rows.sort(key=lambda e: (e.get("title") or "").casefold())
                else:
                    rows.sort(key=lambda e: e.get("date") or "", reverse=state["sort"] == "new")
                if not rows:
                    tk.Label(frame, text=tr("hist_none"), bg=CARD2, fg=MUTED, font=(FONT, 11)).pack(padx=16, pady=20)
                for e in rows:
                    path = e.get("path") or ""
                    exists = os.path.exists(path)
                    row = tk.Frame(frame, bg=CARD2)
                    row.pack(fill="x", padx=8, pady=4)
                    info = tk.Frame(row, bg=CARD2, width=400, height=40)
                    info.pack(side="left")
                    info.pack_propagate(False)
                    tk.Label(info, text=fit_text(e.get("title") or "", f11, 390), bg=CARD2, fg=FG if exists else DIM,
                             font=(FONT, 11), anchor="w").pack(fill="x")
                    sub = (e.get("date") or "") + (f"  ·  {e['quality']}" if e.get("quality") else "")
                    if not exists:
                        sub += "  ·  " + tr("hist_missing")
                    tk.Label(info, text=sub, bg=CARD2, fg=MUTED, font=(FONT, 9), anchor="w").pack(fill="x")
                    fb = RoundButton(row, tr("hist_folder"), lambda p=path: self.open_location(
                        {"filepath": p, "outdir": os.path.dirname(p)}), small=True, style="secondary",
                        state="normal" if exists else "disabled")
                    fb.pack(side="right")
                    ob = RoundButton(row, tr("hist_open"), lambda p=path: self.play_file({"filepath": p}), small=True,
                                     style="primary", state="normal" if exists else "disabled")
                    ob.pack(side="right", padx=(0, 8))
                    for w_ in (row, info, *info.winfo_children()):
                        w_.bind("<MouseWheel>", wheel)
                frame.update_idletasks()
                canvas.configure(scrollregion=(0, 0, 640, frame.winfo_reqheight()))
                canvas.yview_moveto(0)
                if frame.winfo_reqheight() <= 360:
                    sb.pack_forget()
                else:
                    sb.pack(side="right", fill="y", before=canvas)

            def set_sort(k):
                state["sort"] = k
                for kk, b_ in sort_btns.items():
                    b_.config(style="primary" if kk == k else "secondary")
                populate()
            canvas.bind("<MouseWheel>", wheel)
            frame.bind("<MouseWheel>", wheel)
            qvar.trace_add("write", populate)
            populate()

        def clear():
            if self.ask_yes_no(tr("hist_title"), tr("hist_confirm")):
                save_history([])
                win.destroy()
                self.show_history()
        brow = tk.Frame(inner, bg=CARD)
        brow.pack(fill="x", pady=(14, 0))
        RoundButton(brow, tr("info_close"), win.destroy, small=True, style="secondary").pack(side="right")
        if data:
            RoundButton(brow, tr("hist_clear"), clear, small=True, style="danger").pack(side="left")
        win.update_idletasks()
        self._center(win)
        apply_titlebar_theme(win)

    def show_logs(self):
        """Log window: what the app and yt-dlp do, errors in red (for debugging)."""
        if self.logs_win is not None and self.logs_win.winfo_exists():
            self.logs_win.lift()
            self.logs_win.focus_force()
            return
        win = self.logs_win = tk.Toplevel(self)
        win.title(tr("logs_title"))
        win.configure(bg=BG)
        win.geometry("860x520")
        win.minsize(480, 280)
        win.bind("<Escape>", lambda e: win.destroy())
        bar = tk.Frame(win, bg=BG)
        bar.pack(side="bottom", fill="x", padx=14, pady=(0, 12))
        body = tk.Frame(win, bg=CARD)
        body.pack(side="top", fill="both", expand=True, padx=14, pady=(14, 10))
        sb = tk.Scrollbar(body)
        sb.pack(side="right", fill="y")
        txt = tk.Text(body, bg=CARD, fg=FG, bd=0, highlightthickness=0, wrap="word", font=("Consolas", 9),
                      padx=10, pady=8, yscrollcommand=sb.set, insertbackground=FG)
        txt.pack(side="left", fill="both", expand=True)
        sb.config(command=txt.yview)
        txt.tag_config("ts", foreground=MUTED)
        txt.tag_config("debug", foreground=MUTED)
        txt.tag_config("info", foreground=FG)
        txt.tag_config("warning", foreground=ORANGE)
        txt.tag_config("error", foreground=RED)
        shown = [0]

        def refresh():
            if not win.winfo_exists():
                return
            with LOG_LOCK:
                if shown[0] > len(LOG):                # cleared
                    shown[0] = 0
                new = LOG[shown[0]:]
                shown[0] = len(LOG)
            if new:
                at_end = txt.yview()[1] >= 0.999
                for ts, level, msg in new:
                    txt.insert("end", ts + "  ", "ts")
                    txt.insert("end", msg + "\n", level)
                if at_end:
                    txt.see("end")
                    txt.after_idle(lambda: txt.winfo_exists() and txt.yview_moveto(1.0))
            win.after(500, refresh)

        def copy():
            self.clipboard_clear()
            self.clipboard_append("\n".join(f"{t} [{lv}] {m}" for t, lv, m in list(LOG)))
            copy_btn.config(text=tr("log_copied"))
            win.after(1200, lambda: copy_btn.winfo_exists() and copy_btn.config(text=tr("log_copy")))

        def clear():
            with LOG_LOCK:
                LOG.clear()
                try:
                    open(log_file_path(), "w", encoding="utf-8").close()     # the saved history goes too
                except OSError:
                    pass
            shown[0] = 0
            txt.delete("1.0", "end")

        copy_btn = RoundButton(bar, tr("log_copy"), copy, small=True, style="secondary")
        copy_btn.pack(side="right")                                   # copy: bottom right, clear: bottom left
        RoundButton(bar, tr("log_clear"), clear, small=True, style="secondary").pack(side="left")
        refresh()
        self._center(win)
        apply_titlebar_theme(win)
        win.update_idletasks()
        txt.yview_moveto(1.0)                                         # opens on the latest lines
        win.after(150, lambda: win.winfo_exists() and txt.yview_moveto(1.0))

    def _schedule_save(self):
        """Saves the typed settings (file-name template, speed limit) shortly after the last keystroke."""
        if self._tpl_save_id:
            self.after_cancel(self._tpl_save_id)
        self._tpl_save_id = self.after(500, self._persist_settings)

    def _persist_settings(self):
        if self._tpl_save_id:
            self.after_cancel(self._tpl_save_id)
            self._tpl_save_id = None
        save_settings(name_tpl=NAME_TPL, speed_limit=SPEED_VALUE, speed_unlimited=SPEED_UNLIM)

    def _reopen_settings(self):
        """Rebuilds the settings window in place (new language / theme colours)."""
        old = self.settings_win
        if old is not None and old.winfo_exists():
            geo = (old.winfo_x(), old.winfo_y(), old.winfo_width(), old.winfo_height())   # keeps the same centre
            self.settings_win = None
            self.show_settings(geo, replace=old)
        else:
            self.show_settings()

    def apply_name_template(self):
        """Renames the queue lines that were not renamed by hand, following the template."""
        for it in self.items:
            if not it.get("custom") and QueueRow.can_edit(it):
                it["name"] = make_name(it) + (tr("trim_suffix") if it.get("trimmed") else "")
                it["row"].refresh_name()

    def set_date_fmt(self, fmt):
        global DATE_FMT
        DATE_FMT = fmt
        save_settings(date_fmt=fmt)
        for obj in [self.current] + self.items:
            if obj:
                obj["upload_date"] = fmt_date(obj.get("date_raw"))
        for it in self.items:
            it["row"].date_cell.config(text=it["upload_date"])
        self._refresh_info()
        self.apply_name_template()  # {date} may be part of the template
        if self.settings_win is not None and self.settings_win.winfo_exists():
            self._settings_example()  # the example in the settings shows the new date format

    def set_theme_choice(self, name):
        if name == THEME:
            return
        mapping = set_theme(name)
        save_settings(theme=THEME)
        for w in (self.info_win, self.sites_win):
            if w is not None and w.winfo_exists():
                w.destroy()  # reopened with the new colours
        self._style()                # ttk widgets (combobox, progress bars, scrollbar)
        self.placeholder.put(CARD2, to=(0, 0, 210, 118))
        recolor_tree(self, mapping)
        restyle_bold(self)
        apply_titlebar_theme(self)
        self._reopen_settings()

    def set_lang(self, lang):
        global LANG
        if lang == LANG:
            return
        LANG = lang
        save_settings(lang=LANG)
        for w in (self.info_win, self.sites_win):
            if w is not None and w.winfo_exists():
                w.destroy()
        self._apply_lang()
        self._update_stop_btn()
        self._fit_window()
        self.apply_name_template()  # "vues" / "views" in {views}
        self._reopen_settings()

    def _center(self, win):
        """Centers a popup on the main window, horizontally and vertically (kept on the screen)."""
        win.update_idletasks()
        ww = win.winfo_width() if win.winfo_width() > 1 else win.winfo_reqwidth()
        wh = win.winfo_height() if win.winfo_height() > 1 else win.winfo_reqheight()
        x = self.winfo_x() + (self.winfo_width() - ww) // 2
        y = self.winfo_y() + (self.winfo_height() - wh) // 2
        x = min(max(x, 0), max(self.winfo_screenwidth() - ww, 0))
        y = min(max(y, 0), max(self.winfo_screenheight() - wh - 40, 0))
        win.geometry(f"+{x}+{y}")

    def _layout_pill(self):
        """Draws the rounded link field and places the entry + Load button inside it."""
        p = self.pill
        p.update_idletasks()
        pad = 3                                   # button inset inside the field
        bw, bh = self.load_btn.winfo_reqwidth(), self.load_btn.winfo_reqheight()
        h = bh + 2 * pad
        left, gap = 20, 12                        # text padding: left edge / before the button
        w = left + self.pill_entry_w + gap + bw + 2 * pad
        p.delete("all")
        p.config(width=w, height=h)
        focused = False
        try:
            focused = self.focus_get() is self.url_entry
        except KeyError:
            pass
        self.pill_shape = round_rect(p, 1, 1, w - 1, h - 1, 13, fill=CARD2,
                                     outline=ACCENT if focused else BORDER)
        cw = self.url_clear_btn.winfo_reqwidth()
        p.create_window(left, h / 2, window=self.url_entry, anchor="w",
                        width=self.pill_entry_w - cw, height=h - 12)
        self.clear_win = p.create_window(left + self.pill_entry_w, h / 2, window=self.url_clear_btn, anchor="e")
        p.create_window(w - pad - 1, h / 2, window=self.load_btn, anchor="e")
        self._show_clear()

    def _show_clear(self):
        if hasattr(self, "clear_win"):
            self.pill.itemconfigure(self.clear_win, state="normal" if self.url_var.get() else "hidden")

    def _clear_url(self):
        self.url_var.set("")
        self.url_entry.focus_set()

    def _pill_focus(self, on):
        self.pill.itemconfig(self.pill_shape, outline=ACCENT if on else BORDER)

    def _apply_lang(self):
        self.title(tr("title"))
        for widget, key, upper in self.i18n:
            text = tr(key)
            widget.config(text=text.upper() if upper else text)
        self._layout_pill()  # the Load button's width depends on the language
        if self.url_err_on:
            self.url_err.config(text=tr("bad_url"))
        self._refresh_info()
        if self.quality_keys:
            idx = self.quality.current()
            self.quality.config(values=[qlabel(k) for k in self.quality_keys])
            self.quality.current(max(idx, 0))
        for it in self.items:
            it["row"].refresh()

    def _refresh_info(self):
        c = self.current
        if c and c.get("playlist"):
            self._set_title(c["title"])
            self.len_lbl.config(text=tr("pl_count", n=len(c["entries"])))
            self.date_lbl.config(text=c["channel"])
        elif c:
            self._set_title(c["title"])
            self.len_lbl.config(text=tr("live_tag") if c.get("is_live") else fmt_hms(c["duration"]))
            self.date_lbl.config(text=c["upload_date"])
        else:
            self._set_title(tr("video_title"))
            self.len_lbl.config(text="")
            self.date_lbl.config(text="")
        if self.thumb_photo is None:
            self.thumb_label.config(text=tr("thumb"))
        self._update_sort_arrows()
        self._refresh_estimate()  # texts follow the language

    # ------------------------------------------------------------------ sorting
    def _update_sort_arrows(self):
        for col, (h, key) in self.sort_heads.items():
            arrow = (" ▼" if self.sort_desc else " ▲") if col == self.sort_col else ""
            h.config(text=tr(key).upper() + arrow)

    def drag_move(self, item, y_root):
        """Moves a line while its handle is dragged (the queue order = the download order)."""
        with self.lock:
            items = list(self.items)
        if item not in items:
            return
        target = len(items) - 1
        for i, it in enumerate(items):
            r = it["row"]
            if y_root < r.winfo_rooty() + r.winfo_height() / 2:
                target = i
                break
        cur = items.index(item)
        if target != cur:
            ref = items[target]["row"]
            if target < cur:
                item["row"].pack_configure(before=ref)
            else:
                item["row"].pack_configure(after=ref)
            with self.lock:
                self.items.remove(item)
                self.items.insert(target, item)
            self.sort_col = None  # manual order: no column is sorted any more
            self._update_sort_arrows()
        top = self.canvas.winfo_rooty()
        if y_root < top:  # near the edges: scroll the list while dragging
            self.canvas.yview_scroll(-1, "units")
        elif y_root > top + self.canvas.winfo_height():
            self.canvas.yview_scroll(1, "units")

    def sort_queue(self, col):
        """Sorts the queue by a column; clicking the same column again reverses the order."""
        if self.sort_col == col:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_col, self.sort_desc = col, False
        keyf = SORT_KEYS[col]
        with self.lock:
            self.items.sort(key=keyf, reverse=self.sort_desc)
            order = list(self.items)
        for it in order:
            it["row"].pack_forget()
        for it in order:
            it["row"].pack(fill="x")
        self._update_sort_arrows()

    # --------------------------------------------------------------- layout
    def _fit_window(self):
        """Sizes the window once, at launch, with room for a full queue (MAX_VISIBLE lines).

        Afterwards the size is left to the user: language switch, adding to the queue, etc.
        never resize the window."""
        self.update_idletasks()
        if self._sized:
            return
        self._sized = True
        self._base_h = base_h = self.winfo_reqheight()
        self.minsize(WIDTH, base_h)  # never smaller than the interface needs without the queue
        self.geometry(f"{WIDTH}x{base_h}")
        self._auto_h = base_h               # height set by the app itself (None once the user resized)

    def _ensure_fits(self, vis=1, row_h=0):
        """The window grows with the queue (up to MAX_VISIBLE lines, then the list scrolls) and shrinks
        back when lines are removed - unless the user resized it by hand. Minimum: 1 line + the buttons."""
        self.update_idletasks()
        need = min(self.winfo_reqheight(), self.winfo_screenheight() - 100)
        self.minsize(WIDTH, max(self._base_h, need - (vis - 1) * row_h))
        if self.state() == "zoomed":
            return
        cur = self.winfo_height()
        if need > cur or (self._auto_h is not None and cur == self._auto_h and need < cur):
            self.geometry(f"{self.winfo_width()}x{need}")
            self._auto_h = need

    def _update_scrollbar(self):
        """Debounced: while a line is added the layout is momentarily out of date (the list is already
        taller, the window not yet), which made the scrollbar flash. It is decided once things settle."""
        job = getattr(self, "_sb_job", None)
        if job:
            self.after_cancel(job)
        self._sb_job = self.after(60, self._do_scrollbar)

    def _do_scrollbar(self):
        """Scrollbar only when the lines don't fit in the space the queue box has."""
        self._sb_job = None
        if not self.queue_visible:
            return
        scroll = self.list_frame.winfo_reqheight() > self.canvas.winfo_height() > 1
        if scroll and not self.sb_visible:
            self.sb.pack(side="right", fill="y", before=self.canvas)
            self.sb_visible = True
        elif not scroll and self.sb_visible:
            self.sb.pack_forget()
            self.sb_visible = False
        self.head.pack_configure(padx=(0, 8 if self.sb_visible else 0))

    def _refresh_queue(self):
        n = len(self.items)
        self.after_idle(self.save_queue)
        self.btns.pack_configure(pady=(0, 12 if n else 28))
        if n == 0:
            if self.queue_visible:
                self.queue_box.pack_forget()
                self.queue_visible = False
                self.minsize(WIDTH, self._base_h)
                if self._auto_h is not None and self.state() != "zoomed" and self.winfo_height() == self._auto_h:
                    self.geometry(f"{self.winfo_width()}x{self._base_h}")
                    self._auto_h = self._base_h
        else:
            if not self.queue_visible:
                self.queue_box.pack(fill="both", expand=True)
                self.queue_visible = True
            self.update_idletasks()
            # the queue box takes all the free space; it needs at least 1 line
            row_h = self.items[0]["row"].winfo_reqheight()
            vis = min(n, MAX_VISIBLE)
            self.canvas.config(height=vis * row_h)
            self.update_idletasks()
            self._update_scrollbar()
            self._ensure_fits(vis, row_h)

    def _on_wheel(self, e):
        if self.list_frame.winfo_reqheight() > self.canvas.winfo_height():
            self.canvas.yview_scroll(int(-e.delta / 120), "units")

    def _toggle_trim(self):
        self.start_in.set_enabled(self.use_start.get())
        self.end_in.set_enabled(self.use_end.get())
        c = self.current
        if self.use_end.get() and c and c["duration"] and self.end_in.seconds() == 0:
            self.end_in.set(c["duration"])
        self._refresh_trim()

    def _update_trim_availability(self):
        """Without ffmpeg the trim option is switched off (it cannot work)."""
        ok = has_ffmpeg()
        for cb in self.trim_cbs:
            cb.config(state="normal" if ok else "disabled")
        if not ok:
            self.use_start.set(False)
            self.use_end.set(False)
        self._toggle_trim()
        if ok and self.ffmpeg_warn is not None:
            self.i18n = [x for x in self.i18n if x[0] is not self.ffmpeg_warn]
            self.ffmpeg_warn.destroy()
            self.ffmpeg_warn = None
            self._fit_window()

    def _refresh_estimate(self):
        """Estimated size (quality + trim) of the loaded video."""
        c = self.current
        if not c or c.get("playlist"):
            self.est_size_lbl.config(text="")
            return
        idx = self.quality.current()
        key = self.quality_keys[idx] if 0 <= idx < len(self.quality_keys) else None
        size = (c.get("sizes") or {}).get(key, 0)
        dur = c["duration"]
        if dur and size:
            s = self.start_in.total() if self.use_start.get() else 0
            e = min(self.end_in.total() if self.use_end.get() else dur, dur)
            if e > s:
                size *= (e - s) / dur  # a trimmed download only fetches that part
        if not size:
            size_txt = tr("est_unknown")
        else:
            size_txt = fmt_size(size)
        self.est_size_lbl.config(text=size_txt)

    def _refresh_trim(self):
        """Marks impossible trims in red and (de)activates the add / download buttons."""
        self._refresh_estimate()
        c = self.current
        dur = c["duration"] if c else 0
        s = self.start_in.total() if self.use_start.get() else None
        e = self.end_in.total() if self.use_end.get() else None
        end_bad = e is not None and e <= (s or 0)
        start_bad = (s is not None and e is not None and s >= e) or \
                    (s is not None and bool(dur) and s >= dur)
        self.start_in.set_invalid(start_bad)
        self.end_in.set_invalid(end_bad)
        ok = not (start_bad or end_bad)
        state = "normal" if (c and ok) else "disabled"
        self.add_btn.config(state=state)
        self.dl_btn.config(state=state)
        return ok

    def choose_dir(self):
        d = filedialog.askdirectory(initialdir=self.outdir.get())
        if d:
            self.outdir.set(os.path.normpath(d))
            save_settings(outdir=self.outdir.get())  # remembered for the next launch

    # ------------------------------------------------------- loading video info
    def _set_url_error(self, on):
        if on == self.url_err_on:
            return
        self.url_err_on = on
        if on:
            self.url_err.config(text=tr("bad_url"))
            self.url_err.place(in_=self.url_entry, x=0, y=0, relwidth=1, relheight=1)
            self.url_err.lift()
        else:
            self.url_err.place_forget()

    def _url_err_click(self, _event=None):
        """Click on the error: it disappears and the (wrong) link is selected, ready to be replaced."""
        self._set_url_error(False)
        self.url_entry.focus_set()
        self.url_entry.select_range(0, "end")
        self.url_entry.icursor("end")

    def _url_click(self, event):
        """First click in the link field selects everything (paste straight over the old link);
        further clicks place the cursor as usual."""
        self._set_url_error(False)
        w = event.widget
        try:
            focused = self.focus_get() is w
        except KeyError:
            focused = False
        if not focused:
            w.focus_set()
            w.select_range(0, "end")
            w.icursor("end")
            return "break"
        return None

    def _defocus_click(self, event):
        """Clicking anywhere that is not a text field takes the typing cursor out of the fields
        (buttons and frames never take the focus by themselves)."""
        w = event.widget
        if not isinstance(w, tk.Misc):
            return
        if isinstance(w, (tk.Entry, ttk.Entry, ttk.Combobox, tk.Text, tk.Listbox)):
            return
        try:
            w.winfo_toplevel().focus_set()
        except tk.TclError:
            pass

    def _check_pasted(self):
        url = normalize_url(self.url_var.get())
        if url:
            threading.Thread(target=lambda: self.events.put(("url_check", url, is_supported(url))),
                             daemon=True).start()

    def load(self):
        url = normalize_url(self.url_var.get())
        if not url or self.load_btn._o["busy"]:
            return
        self.url_var.set(url)
        self.focus_set()  # take the typing cursor out of the link field
        self.load_btn.config(busy=True, text=tr("load"))
        threading.Thread(target=self._fetch, args=(url,), daemon=True).start()

    def _fetch(self, url):
        try:
            if not is_supported(url):
                self.events.put(("bad_url",))
                return
            # extract_flat: a playlist is listed quickly (no full analysis of every video)
            opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "logger": QuietLogger(),
                    "extract_flat": "in_playlist"}
            opts["ignore_no_formats_error"] = True        # the info is enough here: formats are picked at download time
            try:                                          # cookies cost seconds: only used when the video needs them
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                if info.get("_type") != "playlist" and info.get("availability") in LOGIN_AVAIL:
                    raise RuntimeError("Sign in required (" + str(info.get("availability")) + ")")
            except Exception as ex:
                if not (cookies_available() and needs_login(ex)):
                    raise
                log("login needed: retrying with the browser cookies", "info")
                opts.update(js_runtime_opts())
                with yt_dlp.YoutubeDL(opts) as ydl:
                    apply_cookies(ydl)
                    info = ydl.extract_info(url, download=False)
            if info.get("_type") == "playlist":
                entries = []
                for e in info.get("entries") or []:
                    if not e:
                        continue
                    u = e.get("webpage_url") or e.get("url") or ""
                    if not u.startswith("http"):
                        if e.get("id") and (e.get("ie_key") or "").lower() == "youtube":
                            u = f"https://www.youtube.com/watch?v={e['id']}"
                        else:
                            continue
                    entries.append({
                        "url": u, "title": e.get("title") or u,
                        "channel": e.get("channel") or e.get("uploader") or info.get("uploader") or "",
                        "duration": e.get("duration") or 0, "view_count": e.get("view_count"),
                        "date_raw": e.get("upload_date") or "",
                        "upload_date": fmt_date(e["upload_date"]) if e.get("upload_date") else "",
                        "thumb": None, "thumb_url": small_thumb_url(e), "sizes": {}})
                if not entries:
                    raise NotAVideo()
                th = (info.get("thumbnails") or (info["entries"][0] or {}).get("thumbnails") or [{}])[-1].get("url")
                thumb = fetch_image(th) if th else None
                self.events.put(("playlist", {"title": info.get("title") or "Playlist",
                                              "channel": info.get("channel") or info.get("uploader") or "",
                                              "entries": entries}, thumb, url))
                return
            thumb = fetch_image(info["thumbnail"]) if info.get("thumbnail") else None
            self.events.put(("info", info, thumb, url))
        except NotAVideo:
            self.events.put(("fetch_error", None))
        except Exception as e:
            self.events.put(("fetch_error", cookie_hint(clean(str(e)))))

    def show_info(self):
        if self.info_win is not None and self.info_win.winfo_exists():
            self.info_win.lift()
            self.info_win.focus_force()
            return
        win = self.info_win = tk.Toplevel(self)
        win.title(tr("info_title"))
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self)
        win.bind("<Escape>", lambda e: win.destroy())
        box = card(win)
        box.pack(padx=20, pady=20, fill="both", expand=True)
        inner = tk.Frame(box, bg=CARD)
        inner.pack(padx=24, pady=20, fill="both", expand=True)

        self.chk = {}  # section title -> status label (filled by the install check)
        self.upd = {}  # section title -> "Update" button (shown only when an update exists)

        def section(title, body, command, links):
            head = tk.Frame(inner, bg=CARD)
            head.pack(anchor="w")
            lbl(head, tr("title") if title == "app" else title, 14, FG, bold=True).pack(side="left")
            if title == "app":
                lbl(head, f"v{APP_VERSION}", 12, MUTED).pack(side="left", padx=(8, 0))
            self.chk[title] = lbl(head, "", 11, MUTED, bold=True)
            self.chk[title].pack(side="left", padx=(12, 0))
            self.upd[title] = RoundButton(head, tr("info_update"),
                                          lambda t=title: self._run_update(t), small=True)
            lbl(inner, body, 11, MUTED, justify="left", wraplength=600).pack(anchor="w", pady=(6, 12))
            if command:
                lbl(inner, tr("info_install"), 10, MUTED, bold=True).pack(anchor="w")
                cmd = tk.Entry(inner, font=("Consolas", 11), bg=CARD2, fg=FG, readonlybackground=CARD2,
                               relief="flat", highlightthickness=1, highlightbackground=BORDER, width=38)
                cmd.insert(0, command)
                cmd.config(state="readonly")
                cmd.pack(anchor="w", pady=(4, 12), ipady=5)
            for text, url in links:
                link = tk.Label(inner, text="↗ " + text, bg=CARD, fg=ACCENT_HI, cursor="hand2",
                                font=(FONT, 11, "underline"))
                link.pack(anchor="w", pady=2)
                link.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))

        section("app", tr("app_body") if can_update("app") else tr("app_manual"), None,
                [(tr("app_github"), APP_RELEASES_URL)])
        tk.Frame(inner, bg=BORDER, height=1).pack(fill="x", pady=16)
        bundled = getattr(sys, "frozen", False)  # the .exe already contains yt-dlp
        section("yt-dlp", tr("info_ytdlp_bundled" if bundled else "info_ytdlp_body"),
                None if bundled else 'pip install -U "yt-dlp[default]"',
                [(tr("info_github"), YTDLP_URL), (tr("info_sites"), SITES_URL)])
        tk.Frame(inner, bg=BORDER, height=1).pack(fill="x", pady=16)
        ff_bundled = bundled_ffmpeg()  # the .exe may already contain ffmpeg
        section("ffmpeg", tr("info_ffmpeg_bundled" if ff_bundled else "info_ffmpeg_body"),
                None if ff_bundled else "winget install ffmpeg",
                [(tr("info_ffmpeg_site"), FFMPEG_URL)])
        tk.Frame(inner, bg=BORDER, height=1).pack(fill="x", pady=16)
        lbl(inner, tr("priv_title"), 14, FG, bold=True).pack(anchor="w")
        lbl(inner, tr("priv_body"), 11, MUTED, justify="left", wraplength=600).pack(anchor="w", pady=(6, 0))
        btn_row = tk.Frame(inner, bg=CARD)
        btn_row.pack(fill="x", pady=(18, 0))
        self.chk_btn = RoundButton(btn_row, tr("info_check"), self._run_check, small=True)
        self.chk_btn.pack(side="left")
        RoundButton(btn_row, tr("info_close"), win.destroy, small=True,
                    style="secondary").pack(side="right")
        win.update_idletasks()
        win.geometry(f"{win.winfo_reqwidth() + 140}x{win.winfo_reqheight()}")   # fixed size: statuses never resize it
        self._center(win)
        apply_titlebar_theme(win)

    def _update_prompt(self, ver):
        """Themed popup at launch: update now or ignore (the Info menu keeps the manual update)."""
        win = tk.Toplevel(self)
        win.title(tr("upd_title"))
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self)
        box = card(win)
        box.pack(padx=20, pady=20)
        inner = tk.Frame(box, bg=CARD)
        inner.pack(padx=26, pady=22)
        lbl(inner, tr("upd_msg", v=ver, cur=APP_VERSION), 11, FG, justify="left", wraplength=380).pack(anchor="w")
        link = tk.Label(inner, text="↗ " + tr("upd_notes"), bg=CARD, fg=ACCENT_HI, cursor="hand2",
                        font=(FONT, 11, "underline"))
        link.pack(anchor="w", pady=(12, 0))
        link.bind("<Button-1>", lambda e: webbrowser.open(APP_RELEASES_URL))
        row = tk.Frame(inner, bg=CARD)
        row.pack(fill="x", pady=(20, 0))

        def go():
            win.destroy()
            self._start_app_update()
        RoundButton(row, tr("upd_now"), go, small=True, style="primary").pack(side="right", padx=(8, 0))
        ign = RoundButton(row, tr("upd_ignore"), win.destroy, small=True, style="secondary")
        ign.pack(side="right")
        Tooltip(ign, lambda: tr("upd_ignore_tip"))
        win.bind("<Escape>", lambda e: win.destroy())
        win.update_idletasks()
        self._center(win)
        apply_titlebar_theme(win)
        win.focus_force()

    def _start_app_update(self):
        if self.running or self.active > 0:
            self.alert(tr("info_title"), tr("app_busy"))
            return
        threading.Thread(target=self._do_update, args=("app",), daemon=True).start()

    def _bg_app_check(self):
        ver, url = latest_app()
        if url and newer(ver, APP_VERSION):
            APP_UPDATE.update(url=url, version=ver)
            self.events.put(("app_update", ver))

    def _run_check(self):
        self.chk_btn.config(state="disabled", text=tr("info_checking"))
        threading.Thread(target=self._check_install, daemon=True).start()

    def _check_install(self):
        """Checks yt-dlp and ffmpeg (installed? up to date?) without freezing the window.

        Each result is (installed, installed_version, latest_version or None if unknown)."""
        try:
            from yt_dlp.version import __version__ as yt_ver
            yt = (True, yt_ver, latest_ytdlp())
        except Exception:
            yt = (False, "", None)
        ff = (False, "", None)
        path = shutil.which("ffmpeg")
        if path:
            try:
                flags = 0x08000000 if sys.platform.startswith("win") else 0  # no console flash
                out = subprocess.run([path, "-version"], capture_output=True, text=True,
                                     timeout=10, creationflags=flags)
                m = re.search(r"version\s+(\S+)", out.stdout.splitlines()[0]) if out.stdout else None
                ff = (out.returncode == 0, m.group(1) if m else "", None)
            except Exception:
                ff = (False, "", None)
            if ff[0]:
                ff = (ff[0], ff[1], latest_ffmpeg())
        app_ver, app_url = latest_app()
        APP_UPDATE.update(url=app_url, version=app_ver)
        self.events.put(("install_check", yt, ff, (True, APP_VERSION, app_ver)))

    def _show_install(self, yt, ff, app=None):
        if self.info_win is None or not self.info_win.winfo_exists():
            return
        checks = (("yt-dlp", yt), ("ffmpeg", ff)) + ((("app", app),) if app else ())
        for key, (ok, ver, latest) in checks:
            w = self.chk[key]
            ver = (ver or "").split("-")[0]                  # "9.0.2-essentials_build-…" -> "9.0.2"
            installed = "✔ " + tr("info_ok") + (f" ({ver})" if ver else "")
            self.upd[key].pack_forget()
            if not ok:
                w.config(text="✖ " + tr("info_missing"), fg=RED)
            elif newer(latest, ver):
                if can_update(key) and (key != "app" or APP_UPDATE.get("url")):
                    self.upd[key].config(state="normal", text=tr("info_update"))
                    self.upd[key].pack(side="left", padx=(12, 0))     # on the title line: the window keeps its height
                w.config(text="⚠ " + tr("info_outdated", v=latest), fg=ORANGE)
            elif latest and vtuple(ver):
                w.config(text="✔ " + tr("info_uptodate") + (f" ({ver})" if ver else ""), fg=GREEN)
            else:
                w.config(text=installed, fg=GREEN)  # up-to-date status unknown (offline, git build…)
        self.chk_btn.config(state="normal", text=tr("info_check"))
        self._update_trim_availability()

    def _run_update(self, key):
        if key == "app" and (self.running or self.active > 0):
            self.alert(tr("info_title"), tr("app_busy"))
            return
        self.upd[key].config(state="disabled", text=tr("info_updating"))
        self.chk_btn.config(state="disabled")
        threading.Thread(target=self._do_update, args=(key,), daemon=True).start()

    def _do_update(self, key):
        try:
            {"yt-dlp": update_ytdlp, "ffmpeg": update_ffmpeg, "app": update_app}[key]()
            self.events.put(("update_done", key, True, ""))
        except Exception as e:
            self.events.put(("update_done", key, False, str(e).strip()[:120]))

    def _show_update(self, key, ok, msg):
        if not ok and key == "app" and (self.info_win is None or not self.info_win.winfo_exists()):
            self.alert(tr("info_title"), tr("info_upd_fail") + (f" : {msg}" if msg else ""))
            return
        if ok and key == "app":                 # the installer is running: leave so it can replace the files
            log("app update: installer started, quitting")
            self._quit()
            return
        if self.info_win is not None and self.info_win.winfo_exists():
            if ok:
                self.upd[key].pack_forget()
                done = "info_updated_restart" if key == "yt-dlp" else "info_updated"
                self.chk[key].config(text="✔ " + tr(done), fg=GREEN)
            else:
                self.upd[key].config(state="normal", text=tr("info_update"))
                self.chk[key].config(text="✖ " + tr("info_upd_fail") + (f" : {msg}" if msg else ""), fg=RED)
            self.chk_btn.config(state="normal")
        if ok and key == "ffmpeg":
            self._update_trim_availability()

    def play_file(self, item):
        """Opens the downloaded file with the default player."""
        path = item.get("filepath")
        log(f"play: {path} (exists={bool(path) and os.path.exists(path)})")
        try:
            if path and os.path.exists(path):
                if sys.platform.startswith("win"):
                    os.startfile(path)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", path])
                else:
                    subprocess.Popen(["xdg-open", path])
        except Exception:
            log("play failed: " + traceback.format_exc(), "warning")

    def open_location(self, item):
        """Opens the folder of a finished download (file selected on Windows/macOS)."""
        path = item.get("filepath")
        try:
            if path and os.path.exists(path):
                target = os.path.normpath(path)
                if sys.platform.startswith("win"):
                    subprocess.Popen(f'explorer /select,"{target}"')
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", "-R", target])
                else:
                    subprocess.Popen(["xdg-open", os.path.dirname(target)])
                return
            folder = os.path.dirname(path) if path else (item["outdir"] or self.outdir.get())
            if sys.platform.startswith("win"):
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception:
            traceback.print_exc()

    # ------------------------------------------------------------ dialog + popup
    def _dialog(self, title, message, buttons, default, cancel):
        """Themed modal box centered on the tool. buttons = [(label, value)] shown right to left reversed."""
        win = tk.Toplevel(self)
        win.withdraw()                      # hidden until centered: no flash in the corner
        win.title(title)
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self)
        box = card(win)
        box.pack(padx=20, pady=20)
        inner = tk.Frame(box, bg=CARD)
        inner.pack(padx=26, pady=22)
        lbl(inner, message, 11, FG, justify="left", wraplength=380).pack(anchor="w")
        row = tk.Frame(inner, bg=CARD)
        row.pack(fill="x", pady=(20, 0))
        res = [cancel]

        def close(v):
            res[0] = v
            win.destroy()
        for label, value in reversed(buttons):
            RoundButton(row, label, lambda v=value: close(v), small=True,
                        style="primary" if value == default else "secondary").pack(side="right", padx=(8, 0))
        win.protocol("WM_DELETE_WINDOW", lambda: close(cancel))
        win.bind("<Escape>", lambda e: close(cancel))
        win.bind("<Return>", lambda e: close(default))
        win.update_idletasks()
        self._center(win)
        apply_titlebar_theme(win)
        win.deiconify()
        win.grab_set()
        win.focus_force()
        self.wait_window(win)
        return res[0]

    def ask_yes_no(self, title, message):
        """Yes / No question in the app's theme, centered on the tool."""
        return self._dialog(title, message, [(tr("yes"), True), (tr("no"), False)], True, False)

    def alert(self, title, message, sound=True):
        """Message / error box in the app's theme, with the error sound the moment it opens."""
        if sound and NOTIFY_SOUND:
            play_error()
        self._dialog(title, message, [("OK", True)], True, True)

    def _work_area(self):
        """(left, top, right, bottom) of the usable area of the screen the tool is on."""
        left, top, right, bottom = 0, 0, self.winfo_screenwidth(), self.winfo_screenheight()
        if sys.platform.startswith("win"):
            try:
                import ctypes
                from ctypes import wintypes

                class MONITORINFO(ctypes.Structure):
                    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]
                pt = wintypes.POINT(self.winfo_x() + self.winfo_width() // 2, self.winfo_y() + self.winfo_height() // 2)
                user32 = ctypes.windll.user32
                user32.MonitorFromPoint.restype = wintypes.HANDLE
                mon = user32.MonitorFromPoint(pt, 2)       # the monitor nearest to the tool
                info = MONITORINFO()
                info.cbSize = ctypes.sizeof(MONITORINFO)
                if user32.GetMonitorInfoW(mon, ctypes.byref(info)):
                    r = info.rcWork
                    left, top, right, bottom = r.left, r.top, r.right, r.bottom
            except Exception:
                log("work area failed: " + traceback.format_exc(), "warning")
        return left, top, right, bottom

    def show_toast(self, title, text, on_folder=None, thumb=None, on_play=None):
        """Popup at the bottom right of the screen: rises from below, fades out after 7 s."""
        st = NOTIFY_STYLE                                 # 1 card, 2 strip, 3 vertical (picture on top)
        W, H, M = (316, 282, 16) if st == 3 else (510, 84, 16)
        if not hasattr(self, "_toasts"):
            self._toasts = []
        left, top, right, bottom = self._work_area()
        win = tk.Toplevel(self)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        outline = {1: ACCENT, 2: BORDER, 3: ACCENT}[st]
        bgc = {1: CARD, 2: CARD2, 3: CARD}[st]
        win.configure(bg=outline)
        body = tk.Frame(win, bg=bgc)
        body.pack(fill="both", expand=True, padx=1, pady=1)
        f10 = tkfont.Font(family=FONT, size=10)

        def fit(text_, room_):                            # one line: cut and add "…"
            short_ = text_
            while short_ and f10.measure(short_) > room_:
                short_ = short_[:-1].rstrip()
            return short_ + "…" if short_ != text_ else short_

        def disc(parent, size, **pk):                     # no picture: accent disc with a check mark
            c = tk.Canvas(parent, width=size, height=size, bg=bgc, highlightthickness=0)
            c.create_oval(2, 2, size - 2, size - 2, fill=ACCENT, outline=ACCENT)
            k = size / 48
            c.create_line(14 * k, 25 * k, 21 * k, 32 * k, 34 * k, 17 * k, fill="#ffffff", width=4,
                          capstyle="round", joinstyle="round")
            c.pack(**pk)
            return c

        def make_buttons(parent, side):
            """Folder icon + Play button (same look as the app's secondary / primary buttons)."""
            pb = fb = None
            order = []
            if on_folder:
                n_col, h_col, t_col = RoundButton.styles()["secondary"]
                fb = tk.Canvas(parent, width=40, height=32, bg=bgc, highlightthickness=0, cursor="hand2")
                r, w_, h_ = 9, 40, 32
                shape = fb.create_polygon(r, 0, w_ - r, 0, w_, 0, w_, r, w_, h_ - r, w_, h_, w_ - r, h_, r, h_,
                                          0, h_, 0, h_ - r, 0, r, 0, 0, smooth=True, fill=n_col, outline=n_col)
                fb.create_polygon(11, 10, 18, 10, 20, 13, 29, 13, 29, 23, 11, 23, fill=t_col, outline=t_col)
                fb.bind("<Enter>", lambda e: fb.itemconfig(shape, fill=h_col, outline=h_col))
                fb.bind("<Leave>", lambda e: fb.itemconfig(shape, fill=n_col, outline=n_col))
                fb.bind("<ButtonRelease-1>", lambda e: (kill(), on_folder()))
                order.append((fb, 8))
            if on_play:
                pb = RoundButton(parent, "▶  " + tr("toast_play"), lambda: (kill(), on_play()), small=True)
                order.append((pb, 16 if side == "right" else 0))
            if side == "right":                           # packed from the right edge: play first
                order.reverse()
            for w_, pad in order:
                w_.pack(side=side, padx=(0, pad) if side == "right" else (0, 8))
            return pb, fb

        if st == 3:                                       # picture on top, title below, then the 2 buttons
            if thumb is not None:
                self._toast_img = ImageTk.PhotoImage(thumb.resize((292, 164), Image.Resampling.LANCZOS))
                ic = tk.Label(body, image=self._toast_img, bg=bgc, bd=0)
                ic.image = self._toast_img
                ic.pack(padx=11, pady=(11, 8))
            else:
                disc(body, 80, pady=(24, 18))
            lbl(body, tr("toast_done"), 9, ACCENT, bold=True, anchor="w").pack(fill="x", padx=14)
            lbl(body, fit(text, W - 2 - 28), 10, FG, anchor="w").pack(fill="x", padx=14, pady=(2, 0))
            row = tk.Frame(body, bg=bgc)
            row.pack(fill="x", padx=14, pady=(10, 12))
            play_btn, folder_btn = make_buttons(row, "left")
        else:
            if st == 2:                                   # thick accent strip on the left
                tk.Frame(body, bg=ACCENT, width=6).pack(side="left", fill="y")
            if thumb is not None:
                self._toast_img = ImageTk.PhotoImage(thumb.resize((100, 56), Image.Resampling.LANCZOS))
                ic = tk.Label(body, image=self._toast_img, bg=bgc, bd=0)
                ic.image = self._toast_img
                ic.pack(side="left", padx=(13, 14), pady=13)
            else:
                disc(body, 48, side="left", padx=(16, 14), pady=17)
            play_btn, folder_btn = make_buttons(body, "right")
            col = tk.Frame(body, bg=bgc)
            col.pack(side="left", fill="both", expand=True, pady=10, padx=(0, 12))
            lbl(col, title, 11, FG, bold=True, anchor="w").pack(fill="x")
            room = W - 2 - (127 if thumb is not None else 78) - 16 - (110 if on_play else 0) \
                - (48 if on_folder else 0) - 14
            lbl(col, fit(text, room), 10, MUTED, anchor="w").pack(fill="x", pady=(3, 0))
        toast = {"win": win, "dead": False}
        self._toasts.append(toast)

        def y_for():
            return bottom - M - H - self._toasts.index(toast) * (H + 10)
        x = right - W - M
        win.geometry(f"{W}x{H}+{x}+{bottom}")
        win.attributes("-alpha", 0.0)

        def kill(_e=None):
            if toast["dead"]:
                return
            toast["dead"] = True
            self._toasts.remove(toast)
            try:
                win.destroy()
            except tk.TclError:
                pass
            for t in self._toasts:           # the ones above slide down
                try:
                    t["win"].geometry(f"+{x}+{bottom - M - H - self._toasts.index(t) * (H + 10)}")
                except tk.TclError:
                    pass

        def clicked(e=None):
            # the toplevel's bindings also reach its children: a press on a button must not close the
            # popup before the button gets its release (that is why the buttons did nothing)
            if e is not None and e.widget in (play_btn, folder_btn):
                return
            kill()                                    # a click anywhere else just closes it

        def bind_all_children(w):
            if w is play_btn or w is folder_btn:      # the buttons keep their own click
                return
            w.bind("<Button-1>", clicked)
            w.config(cursor="hand2")
            for c in w.winfo_children():
                bind_all_children(c)
        bind_all_children(win)
        def rise(t0):
            """Time-based easing (not frame-count based): same smooth motion whatever the PC load."""
            if toast["dead"]:
                return
            k = min(1.0, (time.perf_counter() - t0) / 0.55)
            e = 1 - (1 - k) ** 4                          # ease-out
            y0 = bottom                                   # starts below the screen's work area
            win.geometry(f"+{x}+{int(y0 + (y_for() - y0) * e)}")
            win.attributes("-alpha", 0.97 * min(1.0, k * 2.2))
            if k < 1.0:
                win.after(8, lambda: rise(t0))
            else:
                win.after(7000, lambda: fade(time.perf_counter()))

        def fade(t0):
            if toast["dead"]:
                return
            k = (time.perf_counter() - t0) / 0.6
            if k >= 1.0:
                kill()
                return
            win.attributes("-alpha", 0.97 * (1 - k * k))
            win.after(8, lambda: fade(t0))
        rise(time.perf_counter())

    # ------------------------------------------------------------ thumbnails
    def save_thumb(self, t, title):
        """Saves the original file of a thumbnail (highest quality = untouched download)."""
        ext = ".png"                                  # PNG by default (YouTube serves jpg / webp: converted on save)
        name = sanitize_filename(clean_name(title or "thumbnail")) or "thumbnail"
        path = filedialog.asksaveasfilename(parent=self, initialfile=name + ext, defaultextension=ext,
                                            initialdir=self.outdir.get() if hasattr(self, "outdir") else None,
                                            filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg"), ("WEBP", "*.webp")])
        if not path:
            return

        def work():
            err = None
            try:
                data = fetch_bytes(t["url"])
                want = os.path.splitext(path)[1].lower()
                img = Image.open(io.BytesIO(data))
                fmt = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}.get(want)
                if fmt and img.format != fmt:       # another extension chosen: convert
                    img.convert("RGB").save(path, fmt, **({"quality": 100} if fmt != "PNG" else {}))
                else:
                    with open(path, "wb") as f:
                        f.write(data)
                log(f"thumbnail saved: {path} ({img.width}x{img.height})")
            except Exception as e:
                err = str(e)
                log("thumbnail save failed: " + traceback.format_exc(), "error")
            self.events.put(("thumb_saved", err))
        threading.Thread(target=work, daemon=True).start()

    def thumb_menu(self, event, t, title):
        self._ctx_popup(event, [(tr("thumb_save"), True, lambda: self.save_thumb(t, title))])

    def _ctx_popup(self, event, items):
        """Same flat popup as the text-field menu: items = [(label, enabled, action)]."""
        self._ctx_close()
        if not getattr(self, "_ctx_bound", False):
            self._ctx_bound = True
            self.bind_all("<Button-1>", self._ctx_outside, add="+")
            self.bind_all("<Escape>", lambda e: self._ctx_close(), add="+")
        top = self._ctx = tk.Toplevel(self)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.configure(bg=BORDER)
        inner = tk.Frame(top, bg=CARD2)
        inner.pack(padx=1, pady=1)
        tk.Frame(inner, bg=CARD2, height=4).pack()
        for label, enabled, action in items:
            row = tk.Label(inner, text=label, anchor="w", bg=CARD2, fg=FG if enabled else DIM,
                           font=(FONT, 10), padx=16, pady=6, width=22)
            row.pack(fill="x", padx=4)
            if enabled:
                row.config(cursor="hand2")
                row.bind("<Enter>", lambda e, r=row: r.config(bg=BTN2_HI))
                row.bind("<Leave>", lambda e, r=row: r.config(bg=CARD2))
                row.bind("<ButtonRelease-1>", lambda e, a=action: (self._ctx_close(), a()))
        tk.Frame(inner, bg=CARD2, height=4).pack()
        top.update_idletasks()
        x = min(event.x_root, self.winfo_screenwidth() - top.winfo_reqwidth() - 4)
        y = min(event.y_root, self.winfo_screenheight() - top.winfo_reqheight() - 4)
        top.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    def show_thumbs(self, thumbs, title):
        """Big view of the thumbnails: arrows, small strip at the bottom, right click = save."""
        if not thumbs:
            return
        if getattr(self, "thumb_win", None) is not None and self.thumb_win.winfo_exists():
            self.thumb_win.destroy()
        win = self.thumb_win = tk.Toplevel(self)
        win.title(tr("thumb_title"))
        win.configure(bg=BG)
        win.transient(self)
        win.bind("<Escape>", lambda e: win.destroy())
        self.update_idletasks()
        multi = len(thumbs) > 1
        extra_w, extra_h = 32 + (110 if multi else 0), 32 + 30 + (80 if multi else 0)
        MW, MH = 1280, 720
        win.resizable(False, False)
        win.withdraw()                      # shown once the real picture size is known

        def fit_window(iw, ih):
            """Window = size of the (biggest) picture, set once, never changed afterwards."""
            nonlocal MW, MH
            ww = min(iw + extra_w, self.winfo_screenwidth() - 40)
            wh = min(ih + extra_h, self.winfo_screenheight() - 100)
            MW, MH = ww - extra_w, wh - extra_h
            x = max(0, self.winfo_x() + (self.winfo_width() - ww) // 2)
            y = max(0, self.winfo_y() + (self.winfo_height() - wh) // 2)
            win.geometry(f"{ww}x{wh}+{x}+{y}")
            win.deiconify()
            apply_titlebar_theme(win)
            sized[0] = True
        win.pack_propagate(False)
        imgs = [None] * len(thumbs)
        sized = [False]
        view = {"z": 1.0, "x0": 0.0, "y0": 0.0, "sc": 1.0, "k": 1.0}
        photos = {}
        cur = [0]
        top = tk.Frame(win, bg=BG)
        top.pack(padx=16, pady=(16, 8))
        main = tk.Label(top, bg=CARD2, fg=MUTED, font=(FONT, 12), bd=0)
        main.config(compound="center")
        prev_b = RoundButton(top, "‹", lambda: go(-1), small=True, style="secondary")
        next_b = RoundButton(top, "›", lambda: go(1), small=True, style="secondary")
        prev_b.grid(row=0, column=0, padx=(0, 10))
        main.grid(row=0, column=1)
        next_b.grid(row=0, column=2, padx=(10, 0))
        blank = tk.PhotoImage(width=320, height=180)
        blank.put(CARD2, to=(0, 0, 320, 180))
        main.config(image=blank)
        main.image = blank
        info = lbl(win, "", 10, MUTED)
        info.pack()
        strip = tk.Frame(win, bg=BG)
        if multi:
            strip.pack(pady=(8, 16), padx=16)
        cells = []
        for i, t in enumerate(thumbs):
            c = tk.Label(strip, bg=CARD2, bd=0, highlightthickness=2, highlightbackground=BG, cursor="hand2")
            ph = tk.PhotoImage(width=96, height=54)
            ph.put(CARD2, to=(0, 0, 96, 54))
            c.config(image=ph)
            c.image = ph
            c.grid(row=0, column=i, padx=3)
            c.bind("<Button-1>", lambda e, i=i: select(i))
            for b in ("<Button-3>", "<Button-2>") if sys.platform == "darwin" else ("<Button-3>",):
                c.bind(b, lambda e, i=i: self.thumb_menu(e, thumbs[i], title))
            cells.append(c)
        for b in ("<Button-3>", "<Button-2>") if sys.platform == "darwin" else ("<Button-3>",):
            main.bind(b, lambda e: self.thumb_menu(e, thumbs[cur[0]], title))

        def draw():
            i = cur[0]
            for j, c in enumerate(cells):
                c.config(highlightbackground=ACCENT if j == i else BG)
            t = thumbs[i]
            img = imgs[i]
            if img is None:
                main.config(image=blank, text="…")
                info.config(text=f"{i + 1} / {len(thumbs)}")
                return
            k = min(MW / img.width, MH / img.height, 1)     # never above its real size at zoom 1
            z = view["z"]
            sc = k * z
            vw, vh = min(img.width, MW / sc), min(img.height, MH / sc)    # part of the picture on screen
            x0 = min(max(view["x0"], 0), img.width - vw) if z > 1 else 0
            y0 = min(max(view["y0"], 0), img.height - vh) if z > 1 else 0
            view.update(x0=x0, y0=y0, sc=sc, k=k)
            crop = img.crop((int(x0), int(y0), int(x0 + vw + 0.999), int(y0 + vh + 0.999)))
            size = (max(1, int(vw * sc)), max(1, int(vh * sc)))
            photos["main"] = ImageTk.PhotoImage(crop.resize(
                size, Image.Resampling.LANCZOS if z == 1 else Image.Resampling.BILINEAR))
            main.config(image=photos["main"], text="")
            info.config(text=f"{i + 1} / {len(thumbs)}   ·   {img.width} × {img.height}")

        def select(i):
            cur[0] = i % len(thumbs)
            view.update(z=1, x0=0, y0=0)
            draw()

        def wheel(e):
            if imgs[cur[0]] is None:
                return
            up = e.num == 4 or getattr(e, "delta", 0) > 0
            z = min(8.0, max(1.0, view["z"] * (1.25 if up else 0.8)))
            if z == view["z"]:
                return
            ix, iy = view["x0"] + e.x / view["sc"], view["y0"] + e.y / view["sc"]   # point under the cursor
            sc = view["k"] * z
            view.update(z=z, x0=ix - e.x / sc, y0=iy - e.y / sc)
            draw()

        def press(e):
            view["drag"] = (e.x, e.y, view["x0"], view["y0"])

        def drag(e):
            if view["z"] > 1 and view.get("drag"):
                px, py, x0, y0 = view["drag"]
                view.update(x0=x0 - (e.x - px) / view["sc"], y0=y0 - (e.y - py) / view["sc"])
                draw()

        def reset(_e=None):
            view.update(z=1, x0=0, y0=0)
            draw()

        main.bind("<MouseWheel>", wheel)
        main.bind("<Button-4>", wheel)
        main.bind("<Button-5>", wheel)
        main.bind("<ButtonPress-1>", press)
        main.bind("<B1-Motion>", drag)
        main.bind("<Double-Button-1>", reset)

        def go(d):
            select(cur[0] + d)

        win.bind("<Left>", lambda e: go(-1))
        win.bind("<Right>", lambda e: go(1))
        if len(thumbs) < 2:
            prev_b.grid_remove()
            next_b.grid_remove()

        def loaded(i, img):
            if not win.winfo_exists():
                return
            imgs[i] = img
            if not sized[0]:
                fit_window(img.width, img.height)
            ph = ImageTk.PhotoImage(img.resize((96, 54), Image.Resampling.LANCZOS))
            photos[i] = ph
            cells[i].config(image=ph)
            cells[i].image = ph
            if i == cur[0]:
                draw()
        win.on_loaded = loaded

        def load_all():
            for i, t in enumerate(thumbs):
                try:
                    img = Image.open(io.BytesIO(fetch_bytes(t["url"]))).convert("RGB")
                    self.events.put(("thumb_img", win, i, img))
                except Exception:
                    log(f"thumbnail load failed: {t['url']}", "warning")
        threading.Thread(target=load_all, daemon=True).start()
        draw()
        win.after(4000, lambda: win.winfo_exists() and not sized[0] and fit_window(1280, 720))   # load too slow

    def _show_info(self, info, thumb, url):
        self._set_url_error(False)
        self._set_pick_visible(False)
        self.load_btn.config(busy=False, state="normal", text=tr("load"))
        self.current = {
            "url": info.get("webpage_url") or url,
            "title": info.get("title") or "?",
            "channel": info.get("channel") or info.get("uploader") or "",
            "view_count": info.get("view_count"),
            "duration": info.get("duration") or 0,
            "upload_date": fmt_date(info.get("upload_date")),
            "date_raw": info.get("upload_date") or "",  # YYYYMMDD, sortable
            "thumb": thumb,
            "thumbs": thumb_candidates(info),
            "is_live": bool(info.get("is_live")),
        }
        self.thumb_label.config(cursor="hand2" if self.current["thumbs"] else "")
        if thumb:
            self.thumb_photo = ImageTk.PhotoImage(thumb.resize((210, 118), Image.Resampling.LANCZOS))
            self.thumb_label.config(image=self.thumb_photo, text="")
        else:
            self.thumb_photo = None
            self.thumb_label.config(image=self.placeholder)

        # trim can never go beyond the video length
        limit = self.current["duration"] or 359999
        for tin in (self.start_in, self.end_in):
            tin.set(0)
            tin.set_max(limit)
        if self.current["duration"]:
            self.end_in.set(self.current["duration"])  # end pre-filled with the video length
        ts = url_start_seconds(url)
        if ts and not self.current["is_live"] and ts < (self.current["duration"] or 0):
            self.start_in.set(ts)                      # link with a timestamp: start pre-filled, not ticked
            self.use_start.set(False)

        heights = sorted(
            {f["height"] for f in info.get("formats", [])
             if f.get("height") and f.get("vcodec") not in (None, "none")},
            reverse=True,
        )
        self.quality_keys = [f"{h}p" for h in heights] or ["best"]
        self.quality_keys.append("mp3")
        default = next((i for i, k in enumerate(self.quality_keys)
                        if k.endswith("p") and int(k[:-1]) <= 1080), 0)
        self.quality.config(values=[qlabel(k) for k in self.quality_keys])
        self.quality.current(default)
        self.current["sizes"] = estimate_sizes(info, self.quality_keys)

        if self.current["is_live"]:           # live: no trim, only "from the start" / "from now"
            self.live_var.set(LIVE_FROM_START)  # (the setting is its default)
            for w_ in self.trim_widgets:
                w_.grid_remove()
            self.use_start.set(False)
            self.use_end.set(False)
            self.live_cb.grid()
        else:
            for w_ in self.trim_widgets:
                w_.grid()
            self.live_cb.grid_remove()
        self._update_trim_availability()  # (a playlist had switched the trim off)
        self._refresh_trim()
        self._refresh_info()

    def _playlist_preview(self):
        """No usable thumbnail: the card shows the playlist icon, in the colour the lines will get."""
        color = PL_COLORS[self.pl_count % len(PL_COLORS)]
        self.thumb_photo = ImageTk.PhotoImage(playlist_icon(210, 118, color))
        self.thumb_label.config(image=self.thumb_photo, text="")

    def _show_playlist(self, pl, thumb, url):
        """Playlist loaded: everything is added at once, no trim, only the quality can be chosen."""
        self._set_url_error(False)
        self.load_btn.config(busy=False, state="normal", text=tr("load"))
        entries = pl["entries"]
        self.current = {"playlist": True, "entries": entries, "url": url, "title": pl["title"],
                        "channel": pl["channel"], "view_count": None,
                        "duration": sum(e["duration"] for e in entries),
                        "upload_date": "", "date_raw": "", "thumb": thumb, "sizes": {}}
        self.pick_btn.config(text=tr("pick_btn"))
        self._set_pick_visible(len(entries) > 1)
        if thumb:
            self.thumb_photo = ImageTk.PhotoImage(thumb.resize((210, 118), Image.Resampling.LANCZOS))
            self.thumb_label.config(image=self.thumb_photo, text="")
        else:
            self._playlist_preview()
        self.live_cb.grid_remove()
        for w_ in self.trim_widgets:          # (a live had hidden them)
            w_.grid()
        self.use_start.set(False)
        self.use_end.set(False)
        for cb in self.trim_cbs:
            cb.config(state="disabled")
        self._toggle_trim()
        self.quality_keys = ["best", "2160p", "1440p", "1080p", "720p", "480p", "360p", "mp3"]
        self.quality.config(values=[qlabel(k) for k in self.quality_keys])
        self.quality.current(self.quality_keys.index("1080p"))
        self._refresh_trim()
        self._refresh_info()

    def _load_row_thumbs(self, items):
        jobs = [(id(it), it["thumb_url"]) for it in items if it.get("thumb_url") and not it.get("thumb")]
        if not jobs:
            return
        by_id = {id(it): it for it in items}
        load_small_thumbs(jobs, lambda k, img: self.events.put(("row_thumb", by_id[k], img)))

    def _set_pick_visible(self, on):
        if on and not self._pick_shown:
            self.pick_btn.pack(side="left", padx=(0, 10), before=self.add_btn)
            self._pick_shown = True
        elif not on and self._pick_shown:
            self.pick_btn.pack_forget()
            self._pick_shown = False

    def pick_videos(self):
        c = self.current
        if not c or not c.get("playlist"):
            return
        try:
            preset = c.get("chosen") or [e for e in c["entries"] if not self._dup_info(e.get("url"))] or None
            chosen = self._pick_playlist(c["title"], c["entries"], preset, "pl_ok")
        except Exception:
            log("pick videos failed: " + traceback.format_exc(), "error")
            return
        if chosen:
            c["chosen"] = chosen
            self.pick_btn.config(text=tr("pick_btn_n", n=len(chosen), t=len(c["entries"])))

    def _pick_playlist(self, title, entries, preset=None, ok_key="pl_add"):
        """Themed window with a check box per video. Returns the chosen entries, or None if cancelled."""
        win = tk.Toplevel(self)
        win.withdraw()                      # hidden until centered: no flash in the corner
        win.title(tr("pl_pick_title"))
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self)
        box = card(win)
        box.pack(padx=20, pady=20)
        inner = tk.Frame(box, bg=CARD)
        inner.pack(padx=22, pady=18)
        f11 = tkfont.Font(family=FONT, size=11)
        lbl(inner, fit_text(tr("pl_pick_msg", title=title), f11, 560), 11, FG, bold=True).pack(anchor="w")
        top = tk.Frame(inner, bg=CARD)
        top.pack(fill="x", pady=(10, 8))
        listbox = tk.Frame(inner, bg=CARD2, highlightthickness=1, highlightbackground=BORDER)
        listbox.pack(fill="both")
        canvas = tk.Canvas(listbox, bg=CARD2, highlightthickness=0, width=560, height=340)
        sb = ttk.Scrollbar(listbox, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both")
        frame = tk.Frame(canvas, bg=CARD2)
        canvas.create_window((0, 0), window=frame, anchor="nw")
        vars_ = []
        add_btn = [None]
        thumb_lbls, thumb_imgs, got = {}, {}, queue.Queue()
        blank = tk.PhotoImage(width=1, height=1)

        def refresh_count(*_):
            n = sum(v.get() for v in vars_)
            if add_btn[0] is not None:
                add_btn[0].config(text=tr(ok_key, n=n), state="normal" if n else "disabled")

        def wheel(e):
            canvas.yview_scroll(int(-e.delta / 120), "units")
            return "break"
        for e in entries:
            v = tk.BooleanVar(value=preset is None or any(e is x for x in preset))
            v.trace_add("write", refresh_count)
            vars_.append(v)
            dur = fmt_hms(e["duration"]) if e.get("duration") else ""
            dup = self._dup_info(e.get("url"))
            tag = f"   ·   {tr('dup_tag_queue' if dup[0] == 'queue' else 'dup_tag_hist')}" if dup else ""
            text = fit_text(e["title"], f11, 400 - (6 * len(tag) if tag else 0)) + (f"   ·   {dur}" if dur else "") + tag
            line = tk.Frame(frame, bg=CARD2)
            line.pack(fill="x", padx=6, pady=1)
            tl = tk.Label(line, image=blank, bg=CARD, bd=0, width=96, height=54)
            tl.pack(side="left")
            thumb_lbls[id(e)] = tl
            cb = tk.Checkbutton(line, text=text, variable=v, bg=CARD2, fg=FG, selectcolor=CARD,
                                activebackground=CARD2, activeforeground=FG, highlightthickness=0, bd=0,
                                font=(FONT, 11), anchor="w", width=54)
            cb.pack(side="left", fill="x", padx=(6, 0))
            for w_ in (line, tl, cb):
                w_.bind("<MouseWheel>", wheel)
            tl.bind("<Button-1>", lambda ev, v=v: v.set(not v.get()))
        frame.update_idletasks()
        canvas.configure(scrollregion=(0, 0, 560, frame.winfo_reqheight()))

        def show_thumbs():             # thumbnails arrive from worker threads: shown from the UI thread
            try:
                while True:
                    key, img = got.get_nowait()
                    lb = thumb_lbls.get(key)
                    if lb is not None and lb.winfo_exists():
                        thumb_imgs[key] = ImageTk.PhotoImage(img)
                        lb.config(image=thumb_imgs[key], width=img.width, height=img.height)
                        for e_ in entries:
                            if id(e_) == key and not e_.get("thumb"):
                                e_["thumb"] = img
            except queue.Empty:
                pass
            except tk.TclError:
                return
            if win.winfo_exists():
                win.after(120, show_thumbs)
        jobs = [(id(e_), e_.get("thumb_url")) for e_ in entries if e_.get("thumb_url") and not e_.get("thumb")]
        for e_ in entries:
            if e_.get("thumb"):
                got.put((id(e_), e_["thumb"]))
        load_small_thumbs(jobs, lambda k, img: got.put((k, img)))
        show_thumbs()
        canvas.bind("<MouseWheel>", wheel)
        frame.bind("<MouseWheel>", wheel)
        if frame.winfo_reqheight() <= 340:
            sb.pack_forget()

        def set_all(val):
            for v in vars_:
                v.set(val)
        RoundButton(top, tr("pl_all"), lambda: set_all(True), small=True, style="secondary").pack(side="left")
        RoundButton(top, tr("pl_none"), lambda: set_all(False), small=True, style="secondary").pack(side="left", padx=(8, 0))
        res = [None]

        def ok():
            res[0] = [e for e, v in zip(entries, vars_) if v.get()]
            win.destroy()
        row = tk.Frame(inner, bg=CARD)
        row.pack(fill="x", pady=(14, 0))
        add_btn[0] = RoundButton(row, "", ok, small=True, style="primary")
        add_btn[0].pack(side="right")
        RoundButton(row, tr("pl_cancel"), win.destroy, small=True, style="secondary").pack(side="right", padx=(0, 8))
        refresh_count()
        win.bind("<Escape>", lambda e: win.destroy())
        win.update_idletasks()
        self._center(win)
        apply_titlebar_theme(win)
        win.deiconify()
        win.grab_set()
        win.focus_force()
        self.wait_window(win)
        return res[0]

    # ------------------------------------------------------------------ queue
    def add_to_queue(self):
        c = self.current
        if c and c.get("playlist"):
            try:
                return self._add_playlist(c)
            except Exception as ex:
                log("add playlist failed: " + traceback.format_exc(), "error")
                self.alert(tr("queue_title"), f"{type(ex).__name__}: {ex}")
                return False
        return self._add_single(c)

    def report_callback_exception(self, exc, val, tb):
        """An error inside a button / event: written to the Logs window instead of vanishing in the console."""
        log("UI error: " + "".join(traceback.format_exception(exc, val, tb)), "error")

    def _dup_info(self, url):
        """None, ("queue", None) or ("hist", date) when this video is already in the queue / downloaded."""
        key = norm_url(url)
        if not key:
            return None
        with self.lock:
            if any(norm_url(it.get("url")) == key and it.get("status") != "done" for it in self.items):
                return ("queue", None)
        for e in load_history():
            if e.get("url") and norm_url(e["url"]) == key and os.path.exists(e.get("path") or ""):
                return ("hist", e.get("date") or "")
        return None

    def _add_playlist(self, c):
        if True:
            q = self.quality_keys[self.quality.current()]
            chosen = c.get("chosen")                     # selection made with the "choose videos" button
            if not chosen:
                chosen = c["entries"]
                dups = [e for e in chosen if self._dup_info(e.get("url"))]
                if dups and self.ask_yes_no(tr("dup_queue_title"), tr("dup_pl_msg", n=len(dups))):
                    chosen = [e for e in chosen if e not in dups]
                    if not chosen:
                        return False
            color = PL_COLORS[self.pl_count % len(PL_COLORS)]   # one colour per playlist added
            self.pl_count += 1
            for e in chosen:
                item = {**e, "pl_color": color, "playlist": c["title"], "name": make_name(e), "trimmed": False, "custom": False, "outdir": None,
                        "quality": q, "qualities": list(self.quality_keys), "start": None, "end": None,
                        "no_trim": True, "status": "waiting", "cancel": False}
                row = QueueRow(self.list_frame, item, self)
                row.pack(fill="x")
                item["row"] = row
                with self.lock:
                    self.items.append(item)
            if not c.get("thumb"):
                self._playlist_preview()      # next playlist = next colour
            self._refresh_queue()
            self.update_idletasks()
            self.canvas.yview_moveto(1.0)
            self._load_row_thumbs([it for it in self.items if it.get("playlist") == c["title"] and not it.get("thumb")])
            return True

    def _add_single(self, c):
        if not c:
            return False
        if not self._refresh_trim():  # impossible trim: the fields are shown in red
            return False
        start = self.start_in.seconds() if self.use_start.get() else None
        end = self.end_in.seconds() if self.use_end.get() else None

        dup = self._dup_info(c.get("url"))
        if dup:                                       # same video already in the queue / downloaded
            msg = (tr("dup_queue_msg", name=c.get("title") or "?") if dup[0] == "queue"
                   else tr("dup_hist_msg", name=c.get("title") or "?", date=dup[1]))
            if not self.ask_yes_no(tr("dup_queue_title") if dup[0] == "queue" else tr("dup_title"), msg):
                return False
        trimmed = start is not None or end is not None
        item = {**c,
                # default file name from the template in the settings (e.g. "{title} - {channel}")
                "name": make_name(c) + (tr("trim_suffix") if trimmed else ""),
                "trimmed": trimmed, "custom": False,
                "outdir": None,  # None = follow the global folder
                "quality": self.quality_keys[self.quality.current()],
                "qualities": list(self.quality_keys),
                "start": start, "end": end, "status": "waiting", "cancel": False}
        if c.get("is_live"):
            item["live_from_start"] = bool(self.live_var.get())
        row = QueueRow(self.list_frame, item, self)
        row.pack(fill="x")
        item["row"] = row
        with self.lock:
            self.items.append(item)
        self._refresh_queue()
        self.update_idletasks()
        self.canvas.yview_moveto(1.0)
        return True

    @staticmethod
    def _discard_partial(item):
        """Line removed before the end: deletes the partial files left by a stopped download."""
        if item["status"] == "done":
            return
        made = set(item.get("made") or ())
        outdir, prefixes, before = item.get("partial") or (None, set(), set())
        if not made and not outdir:
            return

        def work():
            for _ in range(8):               # files can stay locked for a moment on Windows
                left = False
                targets = {p for p in made if os.path.exists(p)}
                for d in (work_dirs(outdir) if outdir else []):
                    try:
                        names = os.listdir(d)
                    except OSError:
                        names = []
                    for f in names:
                        if (d != outdir or f not in before) and any(f.startswith(px) for px in prefixes):
                            targets.add(os.path.join(d, f))
                for p in targets:
                    try:
                        os.remove(p)
                    except OSError:
                        left = True
                if not left:
                    if outdir:
                        drop_tmp_dir(outdir)
                    return
                time.sleep(0.5)
        threading.Thread(target=work, daemon=True).start()

    def delete_item(self, item):
        with self.lock:
            running = item["status"] == "running"
            if running:                      # stop it; its files are removed once it has really stopped
                item["removed"] = True
                item["cancel"] = True
            self.items.remove(item)
        if not running:
            self._discard_partial(item)
        item["row"].destroy()
        self._refresh_queue()

    def clear_queue(self):
        with self.lock:
            removable = [it for it in self.items if it["status"] != "running"]
            for it in removable:
                self.items.remove(it)
        for it in removable:
            self._discard_partial(it)
            it["row"].destroy()
        self._refresh_queue()

    def edit_trim(self, item):
        """Small window to change the trim of a line still waiting in the queue."""
        live = bool(item.get("is_live"))
        if not QueueRow.can_edit(item) or item.get("no_trim") or (not live and not has_ffmpeg()):
            return
        win = tk.Toplevel(self)
        win.title(tr("live_set") if live else tr("trim_edit_title"))
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self)
        win.bind("<Escape>", lambda e: win.destroy())
        box = card(win)
        box.pack(padx=20, pady=20)
        inner = tk.Frame(box, bg=CARD)
        inner.pack(padx=24, pady=20)
        if live:                              # live: only "from the start / from now" can be chosen
            var = tk.BooleanVar(value=bool(item.get("live_from_start")))
            tk.Checkbutton(inner, text=tr("live_cb"), variable=var, bg=CARD, fg=FG, selectcolor=CARD2,
                           activebackground=CARD, activeforeground=FG, highlightthickness=0, bd=0,
                           font=(FONT, 11), anchor="w").pack(anchor="w")
            lbtns = tk.Frame(inner, bg=CARD)
            lbtns.pack(fill="x", pady=(16, 0))
            RoundButton(lbtns, tr("trim_cancel"), win.destroy, small=True, style="secondary").pack(side="left")

            def save_live():
                item["live_from_start"] = bool(var.get())
                item["row"].refresh()
                win.destroy()
            RoundButton(lbtns, tr("settings_save"), save_live, small=True).pack(side="right")
            self._center(win)
            apply_titlebar_theme(win)
            return
        dur = item.get("duration") or 359999
        ctl = {}

        def refresh(*_):
            s = ctl["start"][1].total() if ctl["start"][0].get() else None
            e = ctl["end"][1].total() if ctl["end"][0].get() else None
            for key in ("start", "end"):
                ctl[key][1].set_enabled(ctl[key][0].get())
            end_bad = e is not None and e <= (s or 0)
            start_bad = (s is not None and e is not None and s >= e) or (s is not None and s >= dur)
            ctl["start"][1].set_invalid(start_bad)
            ctl["end"][1].set_invalid(end_bad)
            save.config(state="disabled" if (start_bad or end_bad) else "normal")

        for r, (key, value) in enumerate((("start", item["start"]), ("end", item["end"]))):
            var = tk.BooleanVar(value=value is not None)
            tin = TimeInput(inner)
            tin.set_max(dur)
            tin.set(value if value is not None else (dur if key == "end" and item.get("duration") else 0))
            cb = tk.Checkbutton(inner, text=tr(key), variable=var, command=refresh, bg=CARD, fg=FG,
                                selectcolor=CARD2, activebackground=CARD, activeforeground=FG,
                                highlightthickness=0, bd=0, font=(FONT, 11), anchor="w", width=7)
            cb.grid(row=r, column=0, sticky="w", pady=6)
            tin.grid(row=r, column=1, padx=(12, 0))
            tin.on_change = refresh
            ctl[key] = (var, tin)

        btns = tk.Frame(inner, bg=CARD)
        btns.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        RoundButton(btns, tr("trim_cancel"), win.destroy, small=True, style="secondary").pack(side="left")

        def do_save():
            s = ctl["start"][1].seconds() if ctl["start"][0].get() else None
            e = ctl["end"][1].seconds() if ctl["end"][0].get() else None
            item["start"], item["end"] = s, e
            item["trimmed"] = s is not None or e is not None
            if not item.get("custom"):
                item["name"] = make_name(item) + (tr("trim_suffix") if item["trimmed"] else "")
            item["row"].refresh()
            win.destroy()

        save = RoundButton(btns, tr("settings_save"), do_save, small=True)
        save.pack(side="right")
        refresh()
        self._center(win)
        apply_titlebar_theme(win)

    def rename_item(self, item):
        if not QueueRow.can_edit(item):
            return
        item["row"].toggle_rename()

    def choose_item_dir(self, item):
        if not QueueRow.can_edit(item):
            return
        d = filedialog.askdirectory(initialdir=item["outdir"] or self.outdir.get())
        if d:
            item["outdir"] = os.path.normpath(d)

    def stop_item(self, item):
        if item["status"] != "running":
            return
        if item.get("phase") == "pp" and not item.get("is_live"):
            log(f"stop ignored: conversion in progress, it ends in a few seconds ({item.get('name')})")
            return
        item["cancel"] = True
        if item.get("is_live"):               # a live is never resumed: what is recorded becomes the file
            item["finish"] = True
        item["row"].set_state("stopping_live" if item.get("finish") else "stopping")
        item["row"].lock_button()
        log(f"stop requested: {item.get('name')} (live={bool(item.get('is_live'))})")
        if item.get("is_live") and item.get("thread"):      # ffmpeg ends its file cleanly
            stop_processes(item["thread"])
        item["stop_id"] = item.get("stop_id", 0) + 1
        sid = item["stop_id"]
        self.after(2500, lambda: self._force_stop(item, 0, sid, item.get("thread")))

    def _force_stop(self, it, tries, sid=None, tid=None):
        """yt-dlp sometimes never calls our hooks (live fragments): interrupt its thread by force."""
        # stale watchdog (the download was paused then resumed meanwhile): never touch the new run
        if sid is not None and (it.get("stop_id") != sid or not it.get("cancel") or it.get("thread") != tid):
            return
        if it["status"] != "running" or not it.get("in_dl"):
            return
        if it.get("phase") == "pp" and not it.get("is_live"):     # never cut a conversion
            return
        if tries < 3:
            stop_processes(it["thread"], hard=tries > 0)
            log(f"download still running after stop -> forcing interruption (try {tries + 1})", "warning")
            try:
                import ctypes
                n = ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(it["thread"]), ctypes.py_object(ForceStop))
                log(f"async exception sent ({n} thread)", "debug")
            except Exception:
                log("force-stop failed: " + traceback.format_exc(), "error")
            self.after(2500, lambda: self._force_stop(it, tries + 1, sid, tid))
        elif it.get("finish"):
            log("download thread does not react: finalizing what is recorded anyway", "warning")
            it["detached"] = True
            threading.Thread(target=self._detached_finish, args=(it,), daemon=True).start()

    def _detached_finish(self, it):
        stop_processes(it["thread"], hard=True)
        time.sleep(1)
        self._conclude(it, Cancelled())

    def stop_queue(self):
        if not self.running and self.active == 0:
            return
        self.stop_requested = True
        self.restart_requested = False
        for it in list(self.items):
            if it["status"] == "running":
                self.stop_item(it)

    def _update_stop_btn(self):
        """One button: 'Download queue' when idle, 'Stop queue' while something is downloading."""
        if self.running or self.active > 0:
            self.dlq_btn.config(text=tr("stop_queue"), command=self.stop_queue, style="secondary")
        else:
            self.dlq_btn.config(text=tr("dl_queue"), command=self.start_queue, style="primary")

    # ------------------------------------------------- queue options: start time / action when finished
    def _qopts_refresh(self):
        parts = []
        if self.sched_at:
            parts.append(tr("q_sched_at", t=f"{self.sched_at[0]:02d}:{self.sched_at[1]:02d}"))
        if self.after_action != "none":
            parts.append(tr("q_label_" + self.after_action))
        self.qopts_lbl.config(text="  ·  ".join(parts))

    def queue_options(self):
        win = tk.Toplevel(self)
        win.withdraw()                      # hidden until centered: no flash in the corner
        win.title(tr("q_opts"))
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self)
        box = card(win)
        box.pack(padx=20, pady=20)
        inner = tk.Frame(box, bg=CARD)
        inner.pack(padx=26, pady=22)
        use = tk.BooleanVar(value=bool(self.sched_at))
        hh = tk.StringVar(value=f"{(self.sched_at or (3, 0))[0]:02d}")
        mm = tk.StringVar(value=f"{(self.sched_at or (3, 0))[1]:02d}")
        row = tk.Frame(inner, bg=CARD)
        row.pack(anchor="w")
        cb = tk.Checkbutton(row, text=tr("q_sched"), variable=use, bg=CARD, fg=FG, selectcolor=CARD2,
                            activebackground=CARD, activeforeground=FG, highlightthickness=0, bd=0, font=(FONT, 11))
        cb.pack(side="left")
        for var, rng in ((hh, range(24)), (mm, range(0, 60, 5))):
            if var is mm:
                lbl(row, ":", 11, FG).pack(side="left", padx=4)
            c_ = ttk.Combobox(row, textvariable=var, values=[f"{v:02d}" for v in rng], width=3, state="readonly",
                              font=(FONT, 11))
            c_.pack(side="left", padx=(8 if var is hh else 0, 0))
        action = tk.StringVar(value=self.after_action)
        if sys.platform.startswith("win"):
            lbl(inner, tr("q_after"), 11, MUTED, bold=True).pack(anchor="w", pady=(20, 8))
            arow = tk.Frame(inner, bg=CARD)
            arow.pack(anchor="w")
            btns = {}

            def pick(v):
                action.set(v)
                for k, b in btns.items():
                    b.config(style="primary" if k == v else "secondary")
            for k in ("none", "sleep", "shutdown"):
                btns[k] = RoundButton(arow, tr("q_after_" + k), lambda k=k: pick(k), small=True,
                                      style="primary" if k == self.after_action else "secondary")
                btns[k].pack(side="left", padx=(0, 8))

        def save():
            self.sched_at = (int(hh.get()), int(mm.get())) if use.get() else None
            self.after_action = action.get() if sys.platform.startswith("win") else "none"
            self._set_schedule()
            win.destroy()
        brow = tk.Frame(inner, bg=CARD)
        brow.pack(fill="x", pady=(22, 0))
        RoundButton(brow, tr("q_save"), save, small=True, style="primary").pack(side="right")
        RoundButton(brow, tr("q_cancel"), win.destroy, small=True, style="secondary").pack(side="right", padx=(0, 8))
        win.bind("<Escape>", lambda e: win.destroy())
        win.update_idletasks()
        self._center(win)
        apply_titlebar_theme(win)
        win.deiconify()
        win.grab_set()
        win.focus_force()

    def _set_schedule(self):
        """Next occurrence of the chosen time (today if still ahead, else tomorrow); checked every 20 s."""
        import datetime as dt
        if self.sched_at:
            now = dt.datetime.now()
            t = now.replace(hour=self.sched_at[0], minute=self.sched_at[1], second=0, microsecond=0)
            if t <= now:
                t += dt.timedelta(days=1)
            first = self._sched_target is None
            self._sched_target = t
            log(f"queue scheduled for {t:%Y-%m-%d %H:%M}")
            if first:
                self.after(20000, self._sched_tick)
        else:
            self._sched_target = None
        self._qopts_refresh()

    def _sched_tick(self):
        import datetime as dt
        if self._sched_target is None:
            return
        if dt.datetime.now() >= self._sched_target:
            self._sched_target = None
            self.sched_at = None
            self._qopts_refresh()
            with self.lock:
                waiting = any(it["status"] in ("waiting", "error", "cancelled") for it in self.items)
            log("scheduled start reached")
            if waiting and not self.running:
                self.start_queue()
            return
        self.after(20000, self._sched_tick)

    def _power_countdown(self, action):
        """60 s warning before sleep / shutdown, cancellable."""
        win = tk.Toplevel(self)
        win.title(tr("q_count_title"))
        win.configure(bg=BG)
        win.resizable(False, False)
        win.transient(self)
        box = card(win)
        box.pack(padx=20, pady=20)
        inner = tk.Frame(box, bg=CARD)
        inner.pack(padx=26, pady=22)
        msg = lbl(inner, "", 12, FG, justify="left")
        msg.pack(anchor="w")
        left = [60]
        state = {"job": None}

        def cancel():
            if state["job"]:
                win.after_cancel(state["job"])
            self.after_action = "none"
            self._qopts_refresh()
            win.destroy()

        def tick():
            msg.config(text=tr("q_count_" + action, n=left[0]))
            if left[0] <= 0:
                self.after_action = "none"
                self._qopts_refresh()
                win.destroy()
                self.save_queue()
                flags = 0x08000000
                try:
                    if action == "shutdown":
                        subprocess.Popen(["shutdown", "/s", "/t", "5"], creationflags=flags)
                    else:
                        subprocess.Popen(["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"], creationflags=flags)
                except Exception:
                    log("power action failed: " + traceback.format_exc(), "error")
                return
            left[0] -= 1
            state["job"] = win.after(1000, tick)
        RoundButton(inner, tr("q_cancel"), cancel, small=True, style="primary").pack(anchor="e", pady=(18, 0))
        win.protocol("WM_DELETE_WINDOW", cancel)
        win.bind("<Escape>", lambda e: cancel())
        win.update_idletasks()
        self._center(win)
        apply_titlebar_theme(win)
        win.lift()
        tick()
        if NOTIFY_SOUND:
            play_chime()

    def download_now(self):
        if self.add_to_queue():
            self.start_queue()

    def play_item(self, item):
        """Download only this line, independently of the queue."""
        with self.lock:
            if item["status"] not in QueueRow.EDITABLE:
                return
            item["status"] = "running"
            item["cancel"] = False
        threading.Thread(target=self._run_item, args=(item, self.outdir.get()), daemon=True).start()

    def start_queue(self):
        with self.lock:
            for it in self.items:
                if it["status"] in ("error", "cancelled"):  # lets the user retry
                    it["status"] = "waiting"
                    it["cancel"] = False
            waiting = [it for it in self.items if it["status"] == "waiting"]
        if not waiting:
            self.alert(tr("queue_title"), tr("queue_empty"))
            return
        for it in waiting:
            it["row"].set_state("waiting")
            it["row"].update_buttons()
        if self.running:
            self.restart_requested = True
            return
        self.stop_requested = False
        self.running = True
        self._update_stop_btn()
        threading.Thread(target=self._worker, args=(self.outdir.get(),), daemon=True).start()

    # ----------------------------------------------------------------- worker
    def _next_waiting(self):
        with self.lock:
            for it in self.items:
                if it["status"] == "waiting":
                    it["status"] = "running"
                    return it
        return None

    def _worker(self, default_dir):
        while not self.stop_requested:
            it = self._next_waiting()
            if it is None:
                break
            if self.stop_requested:          # stop pressed just as we picked it
                with self.lock:
                    it["status"] = "waiting"
                break
            self._run_item(it, default_dir)
        self.events.put(("idle",))

    def _run_item(self, it, default_dir):
        """Runs one download (status is already 'running') and reports the outcome."""
        self.events.put(("start", it))
        it["thread"] = threading.get_ident()
        attempt = 0
        while True:
            try:
                it["filepath"] = self._download(it, it["outdir"] or default_dir)
                break
            except (Exception, ForceStop) as e:
                attempt += 1
                if not self._should_retry(it, e, attempt):
                    if it.get("detached"):               # the stop watchdog already finished this line
                        log("download thread ended after force-stop (ignored)", "debug")
                        return
                    self._conclude(it, e)
                    return
                log(f"network error, new attempt {attempt}/{AUTO_RETRY} in {5 * attempt} s: {clean(str(e))[:200]}", "warning")
                self.events.put(("status", it, "retry"))
                for _ in range(5 * attempt):             # wait, but a stop is still taken into account
                    if it["cancel"] or self.stop_requested:
                        break
                    time.sleep(1)
                if it["cancel"] or self.stop_requested:
                    self._conclude(it, Cancelled())
                    return
        try:
            if it.get("detached"):
                return
            if COMPAT_EDIT and it["quality"] != "mp3" and not it.get("is_live") and it["filepath"]:
                it["filepath"] = self._ensure_compat(it, it["filepath"])
            log(f"download finished: {it['filepath']}")
            it.pop("dup_name", None)
            it["status"] = "done"
            self.events.put(("done", it))
        except (Exception, ForceStop) as e:
            if it.get("detached"):               # the stop watchdog already finished this line
                log("download thread ended after force-stop (ignored)", "debug")
                return
            self._conclude(it, e)

    NET_WORDS = ("timed out", "timeout", "connection", "temporary failure", "getaddrinfo", "network", "http error 5",
                 "incompleteread", "ssl", "reset by peer", "remote end closed", "eof occurred")

    def _should_retry(self, it, e, attempt):
        """Network errors only (never a stop, a declined duplicate or a bad link), up to AUTO_RETRY times."""
        if attempt > AUTO_RETRY or it.get("is_live") or it["cancel"] or self.stop_requested or it.get("detached"):
            return False
        if isinstance(e, (Cancelled, ForceStop, Declined)):
            return False
        msg = clean(str(e)).lower()
        return any(w in msg for w in self.NET_WORDS)

    def _conclude(self, it, e):
        """Outcome of a download that raised (stop / pause / error)."""
        if isinstance(e, Declined):
            it["status"] = "cancelled"
            self.events.put(("declined", it))
            return
        if True:
            if not isinstance(e, (Cancelled, ForceStop)):
                log("download error: " + "".join(traceback.format_exception(type(e), e, e.__traceback__)), "error")
            else:
                log(f"download interrupted ({type(e).__name__})")
            if it["cancel"] and it.get("finish") and not it.get("removed"):
                try:
                    it["filepath"] = self._finalize_live(it)
                    it["status"] = "done"
                    self.events.put(("done", it))
                    return
                except Exception as ex:   # files stay as they are: the line can still be removed
                    log("finalize failed: " + "".join(traceback.format_exception(type(ex), ex, ex.__traceback__)), "error")
                    it["status"] = "error"
                    self.events.put(("error", it, tr("live_fail") + " : " + clean(str(ex))))
                    return
            if it["cancel"] or isinstance(e, (Cancelled, ForceStop)):
                it["status"] = "cancelled"
                self.events.put(("cancelled", it))
            else:
                it["status"] = "error"
                self.events.put(("error", it, clean(str(e)) or f"{type(e).__name__} (see Logs)"))

    def _finalize_live(self, it):
        """Stopped live: the recorded .part files are joined into a playable file (ffmpeg, no re-encoding)."""
        self.events.put(("status", it, "finalizing"))      # the progress bar tells what is going on
        ff = shutil.which("ffmpeg")
        found = {p for p in (it.get("made") or ()) if p.endswith(".part")}
        outdir, prefixes, before = it.get("partial") or (None, set(), set())
        for d in (work_dirs(outdir) if outdir else []):     # also look for what yt-dlp left in the folders
            for f in os.listdir(d):
                if f.endswith(".part") and (d != outdir or f not in before) and any(f.startswith(px) for px in prefixes):
                    found.add(os.path.join(d, f))
        parts = sorted(p for p in found if os.path.exists(p) and os.path.getsize(p) > 0)
        log(f"finalize live: ffmpeg={ff}, parts={parts}")
        if not ff or not parts:
            raise RuntimeError("ffmpeg" if not ff else "no data")
        flags = 0x08000000 if sys.platform.startswith("win") else 0   # no console flash
        base = it["final_base"]

        def free(ext):
            out, n = base + ext, 1
            while os.path.exists(out):
                out, n = f"{base} ({n}){ext}", n + 1
            return out

        inputs = [x for p in parts for x in ("-i", p)]
        maps = [x for i in range(len(parts)) for x in ("-map", str(i))]
        if it["quality"] == "mp3":
            attempts = [(".mp3", ["-vn", "-c:a", "libmp3lame", "-b:a", "192k"], ["-map", "0:a?"])]
        else:
            attempts = [(".mp4", ["-c", "copy"], maps), (".mkv", ["-c", "copy"], maps)]  # mkv takes any codec
        err = ""
        for ext, codec, mp in attempts:
            out = free(ext)
            run = subprocess.run([ff, "-y", "-v", "error", "-err_detect", "ignore_err", *inputs, *mp, *codec, out],
                                 capture_output=True, text=True, creationflags=flags)
            if run.returncode == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
                for p in parts:                        # the pieces are now inside the final file
                    folder, stem = os.path.dirname(p), os.path.basename(p)
                    for f in os.listdir(folder):       # .part + leftover fragments / resume info
                        if f.startswith(stem):
                            try:
                                os.remove(os.path.join(folder, f))
                            except OSError:
                                pass
                if outdir:
                    drop_tmp_dir(outdir)
                return out
            log(f"ffmpeg -> {out}: code {run.returncode}\n{run.stderr or ''}", "info" if run.returncode == 0 else "error")
            err = (run.stderr or "").strip().splitlines()[-1] if run.stderr else "ffmpeg"
            try:
                os.remove(out)
            except OSError:
                pass
        raise RuntimeError(err)

    def _slow_watch(self, d, fn, st, now):
        """YouTube lets a connection run fast for a while, then throttles it (a few hundred KB/s) while a new
        connection is fast again. When the speed over the last 6 s collapses, the download is cut and resumed
        on a fresh connection (the .part file is kept). With a speed limit it only acts when the limiter itself was not the one slowing the download."""
        if self.stop_requested or st["no_more"] or d.get("_live"):
            return
        att = st["att"]
        done = d.get("downloaded_bytes") or 0
        total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
        if not total:                                   # unknown size (live, streams): never cut
            return
        inf = d.get("info_dict") or {}
        if inf.get("protocol") not in ("https", "http") or d.get("fragment_count") \
                or "youtube" not in str(inf.get("extractor_key") or inf.get("extractor") or "").lower():
            return                                      # only plain YouTube downloads (not Twitch / HLS / DASH)
        if att["fn"] != fn:
            att.update(fn=fn, win=[], best=0.0)
        win = att["win"]
        win.append((now, done, st["slept"]))
        while len(win) > 1 and now - win[1][0] >= 6:
            win.pop(0)
        span = now - win[0][0]
        if span < 6 or now - att["t0"] < 7:
            return
        if st["slept"] - win[0][2] > 0.1 * span:        # our own speed limiter was holding the download back
            return
        if st["restarts"] and now - st["last_restart"] < 25:    # leave a fresh connection time to settle
            return
        cur = (done - win[0][1]) / span / 1048576
        att["best"] = max(att["best"], cur)
        best = att["best"]
        slow = cur < 1.0 if best < 8 else cur < min(0.15 * best, 5.0)
        if not slow or (total and total - done < 3 * 1048576):
            return
        if st["prev_best"] is not None and st["prev_best"] < 3:
            st["noimp"] += 1                      # the last reconnection did not help either
        else:
            st["noimp"] = 0
        if st["noimp"] >= 2 or st["restarts"] >= 40:
            st["no_more"] = True
            log(f"slow connection persists after {st['restarts']} reconnection(s): keeping the current one", "warning")
            return
        st["restarts"] += 1
        st["last_restart"] = now
        st["prev_best"] = best
        log(f"speed dropped to {cur:.2f} MB/s (best {best:.1f} MB/s) at {done / 1048576:.0f}/{total / 1048576:.0f} MB: "
            f"reconnecting and resuming (#{st['restarts']})", "warning")
        raise SlowRestart()

    def _download(self, it, outdir):
        files = []
        lim = {"fn": None, "t0": 0.0, "b0": 0}
        st = {"t_start": time.monotonic(), "slept": 0.0, "seen": set(), "pp": {}, "pp_total": 0.0,
              "bytes": 0, "dl_time": 0.0, "last_limit": SPEED_LIMIT, "peak": 0.0,
              "att": {"t0": time.monotonic(), "win": [], "best": 0.0, "fn": None},
              "restarts": 0, "noimp": 0, "no_more": False, "prev_best": None, "n403": 0, "last_restart": 0.0}

        def throttle(d):
            """Own speed limit: yt-dlp's built-in one undershoots badly with YouTube's chunked downloads
            (20 MB/s asked, 2-3 obtained). The average speed of each file is kept at the limit by pausing here."""
            if it.get("is_live"):                         # a live recording must keep up with real time
                return
            limit = SPEED_LIMIT * 1048576                 # read live: a change in the settings applies at once
            done = d.get("downloaded_bytes") or 0
            now = time.monotonic()
            if d.get("filename") != lim["fn"]:            # new file (video, then audio): new reference
                lim.update(fn=d.get("filename"), t0=now, b0=done, lm=limit)
            if lim.get("lm") != limit:                    # limit changed: the average restarts from this moment
                lim.update(t0=now, b0=done, lm=limit)     # (else a lower limit froze the download to "catch up")
            if limit <= 0:
                lim.update(t0=now, b0=done)               # unlimited: nothing to catch up on later
                return
            need = (done - lim["b0"]) / limit             # seconds this amount of data should take
            elapsed = now - lim["t0"]
            if elapsed > need + 1:                        # slower than the limit for a while: no big burst afterwards
                lim["t0"] = now - need - 1
                return
            end = now + max(need - elapsed, 0)
            t_sl = time.monotonic()
            while time.monotonic() < end and not it["cancel"] and SPEED_LIMIT * 1048576 == limit:   # a new limit ends the wait
                time.sleep(min(0.2, max(end - time.monotonic(), 0)))
            st["slept"] += time.monotonic() - t_sl

        sp = {"fn": None, "w": []}

        def shown_speed(d):
            """Speed shown in the queue: average over the last 5 s of what really arrived (yt-dlp's own value
            jumps between the pauses of the speed limiter and could show more than the limit)."""
            done = d.get("downloaded_bytes")
            if done is None:
                return d.get("speed")
            now = time.monotonic()
            if d.get("filename") != sp["fn"]:
                sp["fn"], sp["w"] = d.get("filename"), []
            w = sp["w"]
            w.append((now, done))
            while len(w) > 2 and now - w[1][0] >= 5:
                w.pop(0)
            span = now - w[0][0]
            if span < 1.0:
                return d.get("speed")
            return max(done - w[0][1], 0) / span

        def hook(d):
            # remember every file yt-dlp writes (+ its .part / .ytdl) so a removed line can clean up
            it["started"] = True            # from now on: no more changing name / quality / folder
            made = it.setdefault("made", set())
            for key in ("filename", "tmpfilename"):
                p = d.get(key)
                if p:
                    made.update((p, p + ".part", p + ".ytdl"))
            if it["cancel"] and not (it.get("finish") and d["status"] == "finished"):
                raise Cancelled()
            fn_ = d.get("filename")
            if d["status"] == "finished":
                size = d.get("total_bytes") or d.get("downloaded_bytes") or 0
                el = d.get("elapsed") or 0
                mb = size / 1048576
                avg = mb / el if el > 0 else 0.0
                st["bytes"] += size
                st["dl_time"] += el
                if el > 0.5 and mb > 1:
                    RECENT_DL.append((avg, mb))
                    del RECENT_DL[:-20]
                log(f"file done: {os.path.basename(fn_ or '')} | {mb:.1f} MB in {el:.1f} s = {avg:.2f} MB/s average "
                    f"(peak {st['peak']:.2f} MB/s, paused by the limiter {st['slept']:.1f} s, limit now {SPEED_LIMIT:g} MB/s)")
                ra = recent_avg()
                if ra:
                    log(ra)
            if d["status"] == "downloading":
                if fn_ not in st["seen"]:
                    st["seen"].add(fn_)
                    inf = d.get("info_dict") or {}
                    log(f"file start: {os.path.basename(fn_ or '')} | format_id={inf.get('format_id')} "
                        f"vcodec={inf.get('vcodec')} acodec={inf.get('acodec')} ext={inf.get('ext')} "
                        f"proto={inf.get('protocol')} res={inf.get('resolution') or inf.get('height')} "
                        f"tbr={inf.get('tbr')} total={((d.get('total_bytes') or d.get('total_bytes_estimate') or 0) / 1048576):.1f} MB "
                        f"fragments={d.get('fragment_count')} | limit={SPEED_LIMIT:g} MB/s")
                if d.get("speed"):
                    st["peak"] = max(st["peak"], d["speed"] / 1048576)
                now_ = time.monotonic()
                if now_ - st.get("sample_t", 0) >= 5:         # speed profile of the download, one line / 5 s
                    st["sample_t"] = now_
                    log(f"speed sample: {os.path.basename(fn_ or '')[-18:]} {(d.get('downloaded_bytes') or 0) / 1048576:.1f}"
                        f"/{((d.get('total_bytes') or d.get('total_bytes_estimate') or 0) / 1048576):.1f} MB, "
                        f"{(d.get('speed') or 0) / 1048576:.2f} MB/s now, limit {SPEED_LIMIT:g}")
                if not it.get("is_live"):
                    self._slow_watch(d, fn_, st, now_)
                if SPEED_LIMIT != st["last_limit"]:
                    log(f"speed limit seen by the running download: {st['last_limit']:g} -> {SPEED_LIMIT:g} MB/s "
                        f"(at {(d.get('downloaded_bytes') or 0) / 1048576:.1f} MB, current speed "
                        f"{(d.get('speed') or 0) / 1048576:.2f} MB/s)")
                    st["last_limit"] = SPEED_LIMIT
                throttle(d)
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                if it.get("is_live") or not total:
                    self.events.put(("rec", it, d.get("downloaded_bytes") or 0, shown_speed(d)))
                    return
                frac = d.get("downloaded_bytes", 0) / total if total else 0
            elif d["status"] == "finished":
                frac = 1
            else:
                return
            fn = d.get("filename")
            if fn not in files:
                files.append(fn)
            reqs = (d.get("info_dict") or {}).get("requested_formats") or [1]
            n = len(reqs)
            sizes = [(f.get("filesize") or f.get("filesize_approx") or 0) if isinstance(f, dict) else 0 for f in reqs]
            idx = files.index(fn)
            if all(sizes) and idx < n:        # video + audio: each file weighs what it really weighs
                pct = min(100.0, (sum(sizes[:idx]) + frac * sizes[idx]) / sum(sizes) * 100)
            else:
                pct = min(100.0, (idx + frac) / n * 100)
            self.events.put(("progress", it, pct, shown_speed(d) if d["status"] == "downloading" else d.get("speed")))

        conv_stop = threading.Event()

        def pp_hook(d):
            if d["status"] == "started":
                # A stop requested before the conversion starts cancels cleanly. Once ffmpeg is merging /
                # converting it is NOT interrupted (a few seconds): cutting it left half-written files and
                # made the resume fail with an empty error.
                if it.get("phase") != "pp":
                    if it["cancel"] and not it.get("finish"):
                        raise Cancelled()
                    it["phase"] = "pp"
                name = d.get("postprocessor") or ""
                st["pp"][name] = time.monotonic()
                log(f"post-processing: {name} started (+{time.monotonic() - st['t_start']:.1f} s since start)")
                key = {"Merger": "merging", "FFmpegExtractAudio": "audio_conv"}.get(name, "converting")
                self.events.put(("status", it, key))
                watch_conversion(self, it, outdir, name, key, d.get("info_dict") or {}, conv_stop)
            elif d["status"] == "finished":
                nm = d.get("postprocessor") or ""
                t0_ = st["pp"].pop(nm, None)
                if t0_ is not None:
                    dt = time.monotonic() - t0_
                    st["pp_total"] += dt
                    log(f"post-processing: {nm} finished in {dt:.1f} s")
                conv_stop.set()

        os.makedirs(outdir, exist_ok=True)
        name = sanitize_filename(clean_name(it["name"])).replace("%", "%%") or "video"
        if it.get("dup_name"):                       # already decided on an earlier run (pause / resume)
            name = it["dup_name"]
        else:
            plain = name.replace("%%", "%")
            found = existing_media(outdir, plain)
            if found:
                holder = {"event": threading.Event(), "yes": False}
                self.events.put(("ask_dup", it, plain, holder))
                holder["event"].wait()
                if not holder["yes"]:                # keep the existing file: the line is simply finished
                    log(f"already downloaded, kept: {found}")
                    raise Declined()
                name = free_name(outdir, plain).replace("%", "%%")
                log(f"already downloaded, new copy: {name}")
            it["dup_name"] = name
        opts = {
            "outtmpl": name + ".%(ext)s",
            "paths": {"home": outdir, "temp": make_tmp_dir(outdir, video_key(it["url"]))},   # work files go to a hidden sub-folder
            "noplaylist": True,
            "quiet": True,
            "verbose": True,
            "logger": QuietLogger(lambda m: it.get("is_live") and m.startswith("[download] Destination:")
                                  and self.events.put(("rec_live", it))),
            "concurrent_fragment_downloads": 4,
            "ratelimit": None,                                # the limit is applied in the progress hook (throttle)  # bytes / second, None = unlimited
            "progress_hooks": [hook],
            "postprocessor_hooks": [pp_hook],
        }

        if it.get("is_live"):                 # live in progress: from the start, or from now on
            opts["live_from_start"] = it.get("live_from_start", LIVE_FROM_START)
        q = it["quality"]
        if q == "mp3":
            opts["format"] = "bestaudio/best"
            opts["postprocessors"] = [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
            ]
        else:
            if q == "best":
                opts["format"] = "bv*+ba/b"
            else:
                h = int(q[:-1])
                opts["format"] = f"bv*[height<={h}]+ba/b[height<={h}]"
            opts["merge_output_format"] = "mp4"
            if VIDEO_CODEC == "h264":         # same resolution, but H.264 / AAC first when it exists
                opts["format_sort"] = ["res", "vcodec:h264", "acodec:aac"]
            elif VIDEO_CODEC in ("vp9", "av1"):
                opts["format_sort"] = ["res", f"vcodec:{VIDEO_CODEC}"]

        if it["start"] is not None or it["end"] is not None:
            end = it["end"] if it["end"] is not None else float("inf")
            opts["download_ranges"] = download_range_func(None, [(it["start"] or 0, end)])
            opts["force_keyframes_in_cuts"] = not FAST_TRIM
            log(f"trim {it['start']}-{it['end']} s, mode={'fast (keyframes, no re-encode)' if FAST_TRIM else 'exact (re-encode)'}")

        if it["cancel"]:
            raise Cancelled()
        # files already there before we start (never touched by the clean-up below)
        # Remembered for the whole life of the line (a stop is a pause: the partial files are
        # kept so yt-dlp resumes them; they are only deleted when the line is removed).
        prefix = name.replace("%%", "%") + "."
        it["final_base"] = os.path.join(outdir, name.replace("%%", "%"))
        cur = it.get("partial")
        if not cur or cur[0] != outdir:
            it["partial"] = (outdir, {prefix}, {f for f in os.listdir(outdir) if f.startswith(prefix)})
        elif prefix not in cur[1]:           # renamed between two runs: also watch the new name
            cur[1].add(prefix)
            cur[2].update(f for f in os.listdir(outdir) if f.startswith(prefix))
        opts["continuedl"] = True
        if it.get("is_live") and not it.get("live_from_start"):
            # ffmpeg's HLS default starts ~3 segments (~10 s) in the past: start at the newest one
            opts["external_downloader_args"] = {"ffmpeg_i": ["-live_start_index", "-1"]}
        log(f"download start: {it['url']} (quality={it['quality']}, live={bool(it.get('is_live'))}, "
            f"from_start={bool(it.get('live_from_start'))}, limit={SPEED_LIMIT:g} MB/s) -> {it['final_base']}")
        it["in_dl"] = True
        it["phase"] = "dl"
        if (it["start"] is not None or it["end"] is not None) and not it.get("is_live") and q != "mp3":
            try:
                fast = self._twitch_fast(it, outdir, opts, name)
                if not fast:
                    fast = self._youtube_fast(it, outdir, opts, name)
            except (Cancelled, Declined):
                it["in_dl"] = False
                raise
            except Exception:
                log("fast trim path failed, falling back on yt-dlp: " + traceback.format_exc(), "warning")
                fast = None
            if fast:
                it["in_dl"] = False
                drop_tmp_dir(outdir, video_key(it["url"]))
                return fast
            it["phase"] = "dl"
        def run_once():
            try:                                  # cookies cost seconds: only used when the video needs them
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(it["url"], download=True)
            except Exception as ex:
                if it["cancel"] or not needs_login(ex):
                    raise
                if not cookies_available():
                    raise RuntimeError(cookie_hint(clean(str(ex)))) from ex
                log("login needed: retrying with the browser cookies", "info")
                opts.update(js_runtime_opts())
                with yt_dlp.YoutubeDL(opts) as ydl:
                    apply_cookies(ydl)
                    try:
                        info = ydl.extract_info(it["url"], download=True)
                    except Exception as ex2:
                        if needs_login(ex2) and not it["cancel"]:
                            raise RuntimeError(cookie_hint(clean(str(ex2)))) from ex2
                        raise
            return info
        try:
            while True:                           # a throttled connection is dropped and the file resumed
                st["att"] = {"t0": time.monotonic(), "win": [], "best": 0.0, "fn": None}
                try:
                    info = run_once()
                    break
                except SlowRestart:
                    if it["cancel"]:
                        raise Cancelled()
                    continue
                except yt_dlp.utils.DownloadError as ex:
                    # YouTube sometimes answers 403 when a resumed connection comes right after another one:
                    # wait a little, then retry with fresh links (the .part file is kept).
                    if "HTTP Error 403" not in str(ex) or st["n403"] >= 4 or it["cancel"] or self.stop_requested:
                        raise
                    st["n403"] += 1
                    wait_s = 5 * st["n403"]
                    log(f"HTTP 403 while resuming: waiting {wait_s} s then retrying ({st['n403']}/4)", "warning")
                    for _ in range(wait_s * 4):
                        if it["cancel"] or self.stop_requested:
                            raise Cancelled()
                        time.sleep(0.25)
                    continue
        finally:
            it["in_dl"] = False
            drop_tmp_dir(outdir, video_key(it["url"]))   # only removed when empty: a paused download keeps its files
        total_t = time.monotonic() - st["t_start"]
        try:
            ver = yt_dlp.version.__version__
        except Exception:
            ver = "?"
        log(f"download summary: total {total_t:.1f} s | network {st['dl_time']:.1f} s for {st['bytes'] / 1048576:.1f} MB "
            f"({(st['bytes'] / 1048576 / st['dl_time']) if st['dl_time'] > 0 else 0:.2f} MB/s) | "
            f"post-processing {st['pp_total']:.1f} s | limiter pauses {st['slept']:.1f} s | "
            f"other (extraction, waiting, cleanup) {max(total_t - st['dl_time'] - st['pp_total'], 0):.1f} s | "
            f"limit={SPEED_LIMIT:g} MB/s | fragments in parallel={opts['concurrent_fragment_downloads']} | "
            f"temp dir={opts['paths']['temp']} | yt-dlp {ver} | python {sys.version.split()[0]} | "
            f"ffmpeg={'yes' if shutil.which('ffmpeg') else 'no'}")
        reqs = (info or {}).get("requested_downloads") or []
        return reqs[0].get("filepath") if reqs else None

    def _youtube_fast(self, it, outdir, opts, name):
        """YouTube + trim: reads the index (sidx) of the video and audio files, downloads ONLY the fragments covering
        the range, in parallel and with a real progress, then cuts / muxes them with ffmpeg. Returns the final path,
        or None when it does not apply or fails (the caller then falls back on yt-dlp's own ffmpeg download)."""
        ff = shutil.which("ffmpeg")
        if not ff or not re.search(r"youtu(\.be|be\.com)", it["url"]):
            return None
        flags = 0x08000000 if sys.platform.startswith("win") else 0
        t_all = time.monotonic()
        skip = ("progress_hooks", "postprocessor_hooks", "download_ranges", "force_keyframes_in_cuts", "postprocessors")
        o2 = {k: v for k, v in opts.items() if k not in skip}
        with yt_dlp.YoutubeDL(o2) as ydl:
            info = ydl.extract_info(it["url"], download=False)
        if not info or info.get("is_live") or info.get("extractor_key") != "Youtube":
            return None
        fmts = info.get("requested_formats") or [info]
        if len(fmts) > 2:
            return None
        for f in fmts:
            if f.get("protocol") not in ("https", "http") or f.get("ext") not in ("mp4", "m4a") or not f.get("url") \
                    or f.get("fragments"):
                log(f"youtube fast path: format {f.get('format_id')} ({f.get('ext')}/{f.get('protocol')}) not supported, using yt-dlp")
                return None
        vf = fmts[0]
        af = fmts[1] if len(fmts) > 1 else None
        if af is not None and vf.get("vcodec") in (None, "none"):
            vf, af = af, vf
        # indexes
        v_init, v_refs = read_mp4_index(vf["url"], dict(vf.get("http_headers") or {}))
        a_init = a_refs = None
        if af is not None:
            a_init, a_refs = read_mp4_index(af["url"], dict(af.get("http_headers") or {}))
        total_dur = v_refs[-1][1]
        start = max(float(it["start"] or 0), 0.0)
        end = min(float(it["end"]) if it["end"] is not None else total_dur, total_dur)
        if end - start < 0.5:
            return None
        v_sel = [r for r in v_refs if r[1] > start and r[0] < end]
        if not v_sel or not v_sel[0][4]:                       # must begin on a keyframe
            return None
        v_first = v_sel[0][0]
        a_sel = []
        if a_refs is not None:
            a_sel = [r for r in a_refs if r[1] > v_first and r[0] < end]
            if not a_sel:
                return None
        a_off = (v_first - a_sel[0][0]) if a_sel else 0.0
        length = end - v_first if FAST_TRIM else end - start
        tmpd = os.path.abspath(opts["paths"]["temp"])
        plain = name.replace("%%", "%")
        made = it.setdefault("made", set())

        def chunks(sel, tag):
            out, a, b = [], sel[0][2], sel[0][2]
            for r in sel:
                if r[2] + r[3] - a > 8 * 1048576 and r[2] > a:      # chunks of ~8 MB, like yt-dlp's own
                    out.append((a, b - 1))
                    a = r[2]
                b = r[2] + r[3]
            out.append((a, b - 1))
            return [(tag, i, x, y) for i, (x, y) in enumerate(out)]
        tasks = chunks(v_sel, "v") + (chunks(a_sel, "a") if a_sel else [])
        total_b = sum(y - x + 1 for _, _, x, y in tasks)
        log(f"youtube fast path: {len(v_sel)} video + {len(a_sel)} audio fragments, {total_b / 1048576:.0f} MB "
            f"for {start:.0f}-{end:.0f} s (starts at the keyframe {v_first:.1f} s), "
            f"mode={'fast (copy)' if FAST_TRIM else 'exact (re-encode)'}")
        urls = {"v": (vf["url"], dict(vf.get("http_headers") or {})), "a": ((af or {}).get("url"), dict((af or {}).get("http_headers") or {}))}
        lock = threading.Lock()
        stat = {"bytes": 0, "win": [], "ref_t": time.monotonic(), "ref_b": 0, "ref_lim": SPEED_LIMIT}

        def account(nb):
            now = time.monotonic()
            with lock:
                stat["bytes"] += nb
                stat["win"].append((now, stat["bytes"]))
                while len(stat["win"]) > 1 and now - stat["win"][0][0] > 5:
                    stat["win"].pop(0)
                if SPEED_LIMIT != stat["ref_lim"]:
                    stat["ref_lim"], stat["ref_t"], stat["ref_b"] = SPEED_LIMIT, now, stat["bytes"]
                if SPEED_LIMIT <= 0:
                    return 0.0
                due = (stat["bytes"] - stat["ref_b"]) / (SPEED_LIMIT * 1048576)
                return max(0.0, min(due - (now - stat["ref_t"]), 1.0))

        def cpath(tag, i):
            return os.path.join(tmpd, f"{plain}.{tag}{i:05d}.chunk")

        def fetch(task):
            tag, i, a, b = task
            path, want = cpath(tag, i), b - a + 1
            if os.path.exists(path) and os.path.getsize(path) == want:
                account(want)
                return
            url, hdrs = urls[tag]
            last = None
            for att in range(5):
                if it["cancel"]:
                    raise Cancelled()
                got = 0
                try:
                    made.add(path + ".part")
                    with mp4_http_range(url, a, b, hdrs) as r, open(path + ".part", "wb") as f:
                        while True:
                            if it["cancel"]:
                                raise Cancelled()
                            chunk = r.read(65536)
                            if not chunk:
                                break
                            f.write(chunk)
                            got += len(chunk)
                            pause = account(len(chunk))
                            if pause > 0:
                                time.sleep(pause)
                    if got != want:
                        raise IOError(f"incomplete chunk {tag}{i}: {got}/{want}")
                    os.replace(path + ".part", path)
                    made.discard(path + ".part")
                    return
                except Cancelled:
                    raise
                except Exception as ex:
                    last = ex
                    with lock:
                        stat["bytes"] -= got
                    time.sleep(1 + att)
            raise last

        it["phase"] = "dl"
        t_dl = time.monotonic()
        ex = ThreadPoolExecutor(max_workers=8)
        pending = set()
        try:
            pending = {ex.submit(fetch, t) for t in tasks}
            while pending:
                if it["cancel"]:
                    raise Cancelled()
                dn, pending = futures_wait(pending, timeout=0.3, return_when=FIRST_COMPLETED)
                for f in dn:
                    f.result()
                with lock:
                    w = stat["win"]
                    spd = ((w[-1][1] - w[0][1]) / (w[-1][0] - w[0][0])) if len(w) > 1 and w[-1][0] > w[0][0] else 0.0
                    got_b = stat["bytes"]
                self.events.put(("progress", it, min(got_b / total_b * 85.0, 85.0), spd))
        except BaseException:
            for f in list(pending):
                f.cancel()
            raise
        finally:
            ex.shutdown(wait=True)
        dl_time = max(time.monotonic() - t_dl, 0.001)
        mb = total_b / 1048576
        log(f"youtube fast path: {mb:.1f} MB downloaded in {dl_time:.1f} s ({mb / dl_time:.2f} MB/s)")
        if it["cancel"]:
            raise Cancelled()

        it["phase"] = "pp"
        self.events.put(("status", it, "merging" if FAST_TRIM else "converting"))

        def build(tag, init, count):
            outp = os.path.join(tmpd, f"{plain}.{tag}.mp4")
            made.add(outp)
            with open(outp, "wb") as o:
                o.write(init)
                for i in range(count):
                    pth = cpath(tag, i)
                    with open(pth, "rb") as sf:
                        shutil.copyfileobj(sf, o, 4 * 1024 * 1024)
                    os.remove(pth)
            return outp
        nv = sum(1 for t in tasks if t[0] == "v")
        vfile = build("v", v_init, nv)
        afile = build("a", a_init, len(tasks) - nv) if a_sel else None
        self.events.put(("conv", it, "merging" if FAST_TRIM else "converting", 88.0))
        out_tmp = os.path.join(tmpd, f"{plain}.yt.mp4")
        cmd = [ff, "-y", "-v", "error", "-nostdin", "-i", vfile]
        if afile:
            cmd += ["-ss", f"{a_off:.3f}", "-i", afile, "-map", "0:v:0", "-map", "1:a:0"]
        if FAST_TRIM:
            cmd += ["-t", f"{length:.3f}", "-c", "copy", "-avoid_negative_ts", "make_zero"]
        else:
            cmd += ["-ss", f"{start - v_first:.3f}", "-t", f"{length:.3f}", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"]
        cmd += ["-progress", "pipe:1", "-movflags", "+faststart", out_tmp]
        log("youtube fast path: " + " ".join(cmd))
        t_ff = time.monotonic()
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=flags)
        tail = []
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    pct = min(99.0, 88 + float(line.split("=")[1]) / 1e6 / max(length, 1) * 11)
                    self.events.put(("conv", it, "merging" if FAST_TRIM else "converting", pct))
                except ValueError:
                    pass
            elif "=" not in line and line:
                tail.append(line)
        proc.wait()
        if proc.returncode != 0 or not os.path.exists(out_tmp) or os.path.getsize(out_tmp) == 0:
            raise RuntimeError("ffmpeg failed: " + " | ".join(tail[-5:]))
        final = it["final_base"] + ".mp4"
        os.replace(out_tmp, final)
        for pth in [vfile, afile]:
            try:
                if pth:
                    os.remove(pth)
            except OSError:
                pass
        it["made"] = {m for m in made if not m.startswith(tmpd)}
        RECENT_DL.append((mb / dl_time, mb))
        del RECENT_DL[:-20]
        log(f"youtube fast path done: {time.monotonic() - t_all:.1f} s total | network {dl_time:.1f} s | "
            f"ffmpeg {time.monotonic() - t_ff:.1f} s | {os.path.getsize(final) / 1048576:.1f} MB -> {final}")
        return final

    def _twitch_fast(self, it, outdir, opts, name):
        """Twitch VOD + trim, TwitchDownloader style: reads the HLS playlist, downloads ONLY the segments covering
        the range (8 in parallel), then cuts / assembles them with ffmpeg. Returns the final file path, or None
        when this path does not apply or fails (the caller then falls back on yt-dlp)."""
        ff = shutil.which("ffmpeg")
        if not ff or "twitch.tv" not in it["url"]:
            return None
        flags = 0x08000000 if sys.platform.startswith("win") else 0
        t_all = time.monotonic()
        skip = ("progress_hooks", "postprocessor_hooks", "download_ranges", "force_keyframes_in_cuts", "postprocessors")
        o2 = {k: v for k, v in opts.items() if k not in skip}
        with yt_dlp.YoutubeDL(o2) as ydl:
            info = ydl.extract_info(it["url"], download=False)
        if not info or info.get("extractor_key") != "TwitchVod" or info.get("is_live") or info.get("requested_formats"):
            return None
        pl_url = info.get("url") or ""
        if "m3u8" not in (info.get("protocol") or "") or not pl_url:
            return None
        hdrs = dict(info.get("http_headers") or {})
        req = Request(pl_url, headers=hdrs)
        with urlopen(req, timeout=30) as r:
            text = r.read().decode("utf-8", "replace")
        if "#EXT-X-STREAM-INF" in text or "#EXT-X-KEY" in text or "#EXT-X-MAP" in text or "#EXT-X-BYTERANGE" in text:
            log("twitch fast path: playlist not supported, using yt-dlp", "info")
            return None
        segs, d = [], None
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("#EXTINF:"):
                try:
                    d = float(line[8:].split(",")[0])
                except ValueError:
                    d = None
            elif line and not line.startswith("#") and d is not None:
                segs.append((urljoin(pl_url, line), d))
                d = None
        if not segs:
            return None
        total = sum(x[1] for x in segs)
        start = max(float(it["start"] or 0), 0.0)
        end = min(float(it["end"]) if it["end"] is not None else total, total)
        if end - start < 0.5:
            return None
        sel, t, first_t = [], 0.0, None
        for url_, dur_ in segs:
            if t + dur_ > start and t < end:
                if first_t is None:
                    first_t = t
                sel.append(url_)
            t += dur_
        offset, length = start - first_t, end - start
        n = len(sel)
        tmpd = os.path.abspath(opts["paths"]["temp"])
        plain = name.replace("%%", "%")
        paths = [os.path.join(tmpd, f"{plain}.seg{i:05d}.ts") for i in range(n)]
        joined = os.path.join(tmpd, f"{plain}.joined.ts")
        out_tmp = os.path.join(tmpd, f"{plain}.fast.mp4")
        log(f"twitch fast path: {n}/{len(segs)} segments for {start:.0f}-{end:.0f} s (cut at +{offset:.1f} s, "
            f"{length:.1f} s), mode={'fast (copy)' if FAST_TRIM else 'exact (re-encode)'}")
        made = it.setdefault("made", set())
        lock = threading.Lock()
        stat = {"bytes": 0, "done": 0, "win": [], "ref_t": time.monotonic(), "ref_b": 0, "ref_lim": SPEED_LIMIT}

        def account(nb):
            """Counts the bytes and returns how long to pause to respect the shared speed limit."""
            now = time.monotonic()
            with lock:
                stat["bytes"] += nb
                stat["win"].append((now, stat["bytes"]))
                while len(stat["win"]) > 1 and now - stat["win"][0][0] > 5:
                    stat["win"].pop(0)
                if SPEED_LIMIT != stat["ref_lim"]:           # new limit: measure again from now
                    stat["ref_lim"], stat["ref_t"], stat["ref_b"] = SPEED_LIMIT, now, stat["bytes"]
                if SPEED_LIMIT <= 0:
                    return 0.0
                due = (stat["bytes"] - stat["ref_b"]) / (SPEED_LIMIT * 1048576)
                return max(0.0, min(due - (now - stat["ref_t"]), 1.0))

        def fetch(i):
            path = paths[i]
            if os.path.exists(path) and os.path.getsize(path) > 0:    # kept from an earlier (paused) run
                return os.path.getsize(path)
            last = None
            for att in range(5):
                if it["cancel"]:
                    raise Cancelled()
                got = 0
                try:
                    made.add(path + ".part")
                    with urlopen(Request(sel[i], headers=hdrs), timeout=30) as r, open(path + ".part", "wb") as f:
                        expected = int(r.headers.get("Content-Length") or 0)
                        while True:
                            if it["cancel"]:
                                raise Cancelled()
                            chunk = r.read(65536)
                            if not chunk:
                                break
                            f.write(chunk)
                            got += len(chunk)
                            pause = account(len(chunk))
                            if pause > 0:
                                time.sleep(pause)
                    if expected and got != expected:
                        raise IOError(f"incomplete segment {i}: {got}/{expected}")
                    if got == 0:
                        raise IOError(f"empty segment {i}")
                    os.replace(path + ".part", path)
                    made.discard(path + ".part")
                    return got
                except Cancelled:
                    raise
                except Exception as ex:
                    last = ex
                    with lock:
                        stat["bytes"] -= got                        # this attempt does not count
                    time.sleep(1 + att)
            raise last

        it["phase"] = "dl"
        t_dl = time.monotonic()
        ex = ThreadPoolExecutor(max_workers=8)
        try:
            pending = {ex.submit(fetch, i) for i in range(n)}
            done_n = 0
            while pending:
                if it["cancel"]:
                    raise Cancelled()
                dn, pending = futures_wait(pending, timeout=0.3, return_when=FIRST_COMPLETED)
                for f in dn:
                    f.result()                                      # re-raises a failure
                    done_n += 1
                with lock:
                    w = stat["win"]
                    spd = ((w[-1][1] - w[0][1]) / (w[-1][0] - w[0][0])) if len(w) > 1 and w[-1][0] > w[0][0] else 0.0
                self.events.put(("progress", it, min(done_n / n * 95.0, 95.0), spd))
        except BaseException:
            for f in list(pending):
                f.cancel()
            raise
        finally:
            ex.shutdown(wait=True)
        dl_time = max(time.monotonic() - t_dl, 0.001)
        mb = stat["bytes"] / 1048576
        log(f"twitch fast path: {n} segments downloaded, {mb:.1f} MB in {dl_time:.1f} s ({mb / dl_time:.2f} MB/s)")
        if it["cancel"]:
            raise Cancelled()

        # assembly (not interruptible, like a merge)
        it["phase"] = "pp"
        self.events.put(("status", it, "merging" if FAST_TRIM else "converting"))
        # The segments are joined byte for byte (like a plain HLS download): ffmpeg's concat demuxer rewrites the
        # timestamps segment by segment, which made the audio drift away from the video over long ranges.
        made.add(joined)
        with open(joined, "wb") as out_f:
            for i, pth in enumerate(paths):
                with open(pth, "rb") as sf:
                    shutil.copyfileobj(sf, out_f, 4 * 1024 * 1024)
                os.remove(pth)                                      # frees the disk as we go
                if i % 10 == 0:
                    self.events.put(("conv", it, "merging" if FAST_TRIM else "converting", (i + 1) / n * 20))
        if FAST_TRIM:
            # Stream copy: start exactly on a video keyframe. Cutting between two keyframes leaves the video starting
            # before the audio (edit list), which Premiere ignores -> audio out of sync there.
            try:
                fp = shutil.which("ffprobe")
                if fp:
                    out = subprocess.run(
                        [fp, "-v", "error", "-i", joined, "-select_streams", "v:0",
                         "-show_entries", "packet=dts_time,flags", "-of", "csv=p=0",
                         "-read_intervals", f"%+{offset + 30:.3f}"],
                        capture_output=True, text=True, timeout=120, creationflags=flags).stdout
                    st_out = subprocess.run([fp, "-v", "error", "-i", joined, "-show_entries", "stream=start_time",
                                             "-of", "csv=p=0"], capture_output=True, text=True, timeout=60,
                                            creationflags=flags).stdout
                    starts = []
                    for ln in st_out.split():
                        try:
                            starts.append(float(ln.strip(",")))
                        except ValueError:
                            pass
                    base_t, kf = (min(starts) if starts else 0.0), None      # ffmpeg's time 0 = earliest stream start
                    for ln in out.splitlines():
                        parts = ln.strip().split(",")
                        if len(parts) >= 2 and "K" in parts[1] and kf is None:      # dts_time,flags
                            try:
                                t_ = float(parts[0]) - base_t
                            except ValueError:
                                continue
                            if t_ >= offset - 0.001:
                                kf = t_
                    if kf is not None and kf - offset < 30:
                        log(f"twitch fast path: cut moved to the keyframe at +{kf:.3f} s (asked +{offset:.3f} s)")
                        length = max(length - (kf - offset), 0.5)
                        offset = math.floor(kf * 1000) / 1000
            except Exception:
                log("twitch fast path: keyframe lookup failed, cutting at the asked time", "warning")
        cmd = [ff, "-y", "-v", "error", "-nostdin", "-i", joined,
               "-ss", f"{offset:.3f}", "-t", f"{length:.3f}"]
        if FAST_TRIM:
            cmd += ["-c", "copy", "-avoid_negative_ts", "make_zero", "-progress", "pipe:1"]
        else:
            cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-progress", "pipe:1"]
        cmd += ["-movflags", "+faststart", out_tmp]
        log("twitch fast path: " + " ".join(cmd))
        t_ff = time.monotonic()
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=flags)
        tail = []
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    pct = min(99.0, 20 + float(line.split("=")[1]) / 1e6 / length * 80)
                    self.events.put(("conv", it, "merging" if FAST_TRIM else "converting", pct))
                except ValueError:
                    pass
            elif "=" not in line and line:
                tail.append(line)
        proc.wait()
        if proc.returncode != 0 or not os.path.exists(out_tmp) or os.path.getsize(out_tmp) == 0:
            raise RuntimeError("ffmpeg failed: " + " | ".join(tail[-5:]))
        final = it["final_base"] + ".mp4"
        os.replace(out_tmp, final)
        for pth in [joined]:
            try:
                os.remove(pth)
            except OSError:
                pass
        it["made"] = {m for m in made if not m.startswith(tmpd)}
        total_t = time.monotonic() - t_all
        RECENT_DL.append((mb / dl_time, mb))
        del RECENT_DL[:-20]
        log(f"twitch fast path done: {total_t:.1f} s total | network {dl_time:.1f} s | ffmpeg {time.monotonic() - t_ff:.1f} s | "
            f"{os.path.getsize(final) / 1048576:.1f} MB -> {final}")
        return final

    def _ensure_compat(self, it, path):
        """Premiere-compatible file: re-encodes to H.264 / AAC when the download is VP9 / AV1 / Opus."""
        ff, fp = shutil.which("ffmpeg"), shutil.which("ffprobe")
        if not (ff and fp and os.path.exists(path)):
            return path
        flags = 0x08000000 if sys.platform.startswith("win") else 0
        try:
            def probe(sel, entry):
                r = subprocess.run([fp, "-v", "error", "-select_streams", sel, "-show_entries", f"stream={entry}",
                                    "-of", "default=nw=1:nk=1", path], capture_output=True, text=True,
                                   creationflags=flags, timeout=60)
                return r.stdout.strip().split("\n")[0] if r.stdout.strip() else ""
            t_probe = time.monotonic()
            vc, ac = probe("v:0", "codec_name"), probe("a:0", "codec_name")
            dur = subprocess.run([fp, "-v", "error", "-show_entries", "format=duration", "-of",
                                  "default=nw=1:nk=1", path], capture_output=True, text=True,
                                 creationflags=flags, timeout=60).stdout.strip()
            dur = float(dur) if dur else 0.0
        except Exception:
            log("compat probe failed: " + traceback.format_exc(), "warning")
            return path
        log(f"compat check: video={vc}, audio={ac} (probe {time.monotonic() - t_probe:.1f} s, "
            f"COMPAT_EDIT={COMPAT_EDIT}, file {os.path.getsize(path) / 1048576:.1f} MB)")
        need_v, need_a = vc not in ("h264", ""), ac not in ("aac", "")
        if not (need_v or need_a):
            return path
        it["phase"] = "pp"                      # not interruptible (same rule as a merge)
        self.events.put(("status", it, "converting"))
        out = os.path.splitext(path)[0] + ".compat.mp4"
        cmd = [ff, "-y", "-v", "error", "-nostdin", "-progress", "pipe:1", "-i", path, "-map", "0:v:0?", "-map", "0:a:0?"]
        cmd += (["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p"] if need_v else ["-c:v", "copy"])
        cmd += (["-c:a", "aac", "-b:a", "192k"] if need_a else ["-c:a", "copy"])
        cmd += ["-movflags", "+faststart", out]
        log("re-encode: " + " ".join(cmd))
        t_enc = time.monotonic()
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=flags)
        try:
            for line in proc.stdout:
                if line.startswith("out_time_us=") and dur > 0:
                    try:
                        pct = min(99.0, int(line.split("=")[1]) / 1e6 / dur * 100)
                        self.events.put(("conv", it, "converting", pct))
                    except ValueError:
                        pass
            proc.wait()
            err = proc.stderr.read()
        except Exception:
            proc.kill()
            raise
        log(f"re-encode took {time.monotonic() - t_enc:.1f} s (exit {proc.returncode})")
        if proc.returncode != 0 or not os.path.exists(out):
            log("re-encode failed: " + err[-600:], "error")
            if os.path.exists(out):
                os.remove(out)
            return path                         # the original file stays
        os.replace(out, path)
        log("re-encode done")
        return path

    # ----------------------------------------------- worker -> interface events
    def _poll(self):
        while True:
            try:
                ev = self.events.get_nowait()
            except queue.Empty:
                break
            try:
                self._handle(ev)
            except Exception:
                log("UI event error " + repr(ev[:1]) + ":\n" + traceback.format_exc(), "error")
        self.after(100, self._poll)

    def _finish(self, it):
        self.after_idle(self.save_queue)
        self.active -= 1
        it["row"].set_running(False)
        it["row"].update_buttons()
        self._update_stop_btn()

    def _handle(self, ev):
        kind = ev[0]
        if kind == "external":
            log(f"link received: {ev[1] or '(show window)'}")
            self._open_external(ev[1])
            if len(ev) > 2:
                ev[2].set()
            return
        if kind == "tray_show":
            self._from_tray()
            return
        if kind == "tray_quit":
            self._quit()
            return
        if kind in ("start", "progress", "rec", "rec_live", "conv", "status", "done", "error", "cancelled", "declined") and ev[1].get("removed"):
            # line deleted while downloading: no row any more, only the bookkeeping + file clean-up
            if kind == "start":
                self.active += 1
            elif kind in ("done", "error", "cancelled", "declined"):
                self.active -= 1
                if kind != "done":
                    self._discard_partial(ev[1])
                self._update_stop_btn()
            return
        if kind == "thumb_img":
            ev[1].on_loaded(ev[2], ev[3]) if ev[1].winfo_exists() else None
        elif kind == "thumb_saved":
            if ev[1]:
                self.alert(tr("thumb_title"), ev[1])
        elif kind == "info":
            self._show_info(ev[1], ev[2], ev[3])
        elif kind == "cookie_test":
            try:
                self._ck_status[ev[1]] = bool(ev[2] and ev[3] > 0)
                for v_, b_ in self._ck_btns.items():
                    if b_.winfo_exists():
                        b_.config(style=self._ck_style(v_, COOKIES_BROWSER))
            except (tk.TclError, AttributeError):
                pass
            if ev[1] == COOKIES_BROWSER:
                try:
                    if ev[2] and ev[3] > 0:
                        self._ck_show("✔ " + tr("ck_ok", n=ev[3], y=ev[4]), GREEN)
                    elif ev[2]:
                        self._ck_show("⚠ " + tr("ck_noyt", n=ev[3]), ORANGE)
                    else:
                        err = ev[5]
                        if "DPAPI" in err:       # Chromium browsers lock their cookies: nothing the app can change
                            self._ck_show("✖ " + tr("ck_dpapi"), RED)
                        else:
                            m_ = re.search(r"https?://[^\s)]+", err)
                            err = re.sub(r"\s*See\s+https?://\S+\s+for more info\.?", "", err)
                            err = re.sub(r"https?://\S+", "", err).strip(" .")
                            self._ck_show("✖ " + tr("ck_fail", e=err), RED, m_.group(0) if m_ else "")
                except (tk.TclError, AttributeError):
                    pass
        elif kind == "app_update":
            log(f"app update available: {ev[1]}")
            self.info_btn.config(style="primary")        # the Info button lights up
            if self.state() != "withdrawn" and not getattr(self, "_upd_prompted", False):
                self._upd_prompted = True                # asked once per launch
                self._update_prompt(ev[1])
        elif kind == "install_check":
            self._show_install(ev[1], ev[2], ev[3] if len(ev) > 3 else None)
        elif kind == "update_done":
            self._show_update(ev[1], ev[2], ev[3])
        elif kind == "bad_url":
            if NOTIFY_SOUND:
                play_error()
            self.load_btn.config(busy=False, state="normal", text=tr("load"))
            self._set_url_error(True)
        elif kind == "url_check":
            if ev[1] == normalize_url(self.url_var.get()):
                if not ev[2] and not self.url_err_on and NOTIFY_SOUND:
                    play_error()                      # the red message just appeared (paste / typing)
                self._set_url_error(not ev[2])
        elif kind == "row_thumb":
            row = ev[1].get("row")
            if row is not None and any(x is ev[1] for x in self.items):
                ev[1]["thumb"] = ev[2]
                row.set_thumb(ev[2])
        elif kind == "playlist":
            self._show_playlist(ev[1], ev[2], ev[3])
        elif kind == "fetch_error":
            self.load_btn.config(busy=False, state="normal", text=tr("load"))
            self.alert(tr("load_err"), tr("playlist") if ev[1] is None else ev[1])
        elif kind == "start":
            self.active += 1
            ev[1]["row"].set_running(True)
            ev[1]["row"].set_state("starting")
            ev[1]["row"].update_buttons()
            self._update_stop_btn()
        elif kind == "progress":
            ev[1]["row"].set_state("pct", ev[2], ev[3])
        elif kind == "ask_dup":
            if NOTIFY_SOUND:
                play_error()                          # at the very moment the box opens
            try:
                ev[3]["yes"] = self.ask_yes_no(tr("dup_title"), tr("dup_msg", name=ev[2]))
            finally:
                ev[3]["event"].set()
        elif kind == "declined":
            self._finish(ev[1])
            ev[1]["row"].set_state("canceled")
        elif kind == "conv":
            if not ev[1].get("cancel"):
                ev[1]["row"].set_state("conv", (ev[2], ev[3]))
        elif kind == "rec_live":
            if not ev[1].get("cancel"):
                ev[1]["row"].set_state("live_rec")
        elif kind == "rec":
            if not ev[1].get("cancel"):
                ev[1]["row"].set_state("rec", ev[2], ev[3])
        elif kind == "status":
            log(f"status: {ev[2]} ({ev[1].get('name')})", "debug")
            ev[1]["row"].set_state(ev[2])
        elif kind == "done":
            log(f"done: {ev[1].get('name')}")
            try:
                add_history(ev[1])
            except Exception:
                log("history save failed: " + traceback.format_exc(), "warning")
            if NOTIFY_SOUND:
                play_chime()
            if NOTIFY_TOAST:
                self.show_toast(tr("toast_done"), ev[1].get("name") or "", lambda it=ev[1]: self.open_location(it),
                                ev[1].get("thumb"), (lambda it=ev[1]: self.play_file(it)) if ev[1].get("filepath") else None)
            self._finish(ev[1])
            ev[1]["row"].set_state("done")
        elif kind == "error":
            log(f"error: {ev[1].get('name')}: {ev[2]}", "error")
            if NOTIFY_SOUND:
                play_error()
            self._finish(ev[1])
            ev[1]["row"].set_error(ev[2])
        elif kind == "cancelled":
            self._finish(ev[1])
            ev[1]["row"].set_state("cancelled")
        elif kind == "idle":
            self.after(1500, trim_memory)
            self.running = False
            was_stopped = self.stop_requested
            self.stop_requested = False
            with self.lock:
                still = any(it["status"] in ("waiting", "running") for it in self.items)
            if self.after_action != "none" and not was_stopped and not still and not self.restart_requested:
                self._power_countdown(self.after_action)
            self._update_stop_btn()
            if self.restart_requested:
                self.restart_requested = False
                self.start_queue()


if __name__ == "__main__":
    _link = url_from_argv(sys.argv)
    if send_to_running(_link or "show"):                         # already open: bring it back (+ hand the link over)
        sys.exit(0)
    _hide_console()
    init_log_file()

    def _warm_up():                                  # yt-dlp loads while the window appears
        _load_ytdlp()
        try:
            track_processes()
            log(f"start: python {sys.version.split()[0]}, yt-dlp {yt_dlp.version.__version__}, "
                f"ffmpeg {shutil.which('ffmpeg')}, font {FONT}")
            is_supported("https://example.com/")     # builds the extractor list now, not at the first paste
        except Exception:
            pass
    threading.Thread(target=_warm_up, daemon=True).start()
    App(initial_url=_link).mainloop()
