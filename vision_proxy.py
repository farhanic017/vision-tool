#!/usr/bin/env python3
#  Vision Tool — Image & video analysis for AI coding assistants
#  Copyright (c) 2026 Farhan Dhrubo  <farhaiee123@gmail.com>
#  License: GPL-3.0  —  https://github.com/farhanic017/vision-tool
#
#  This program is free software. You may NOT remove this notice,
#  re-distribute as your own work, or sell without attribution.
# =============================================================================

"""
vision_proxy.py — Image & video analysis for AI models without native vision.
Copyright (C) 2026 Farhan Dhrubo

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Handles:
  - Images  (png, jpg, webp, bmp, gif)
  - Videos  (mp4, webm, mov, avi, mkv, flv, wmv, m4v) via ffmpeg keyframe extraction

Chains through free backends first, then paid fallbacks:
  Free:   Free.ai InternVL 3 8B → Free.ai Molmo 7B → Moondream →
          Gemma 4 26B → NVIDIA Nemotron VL → Gemini 2.5 Flash →
          Gemini 2.0 Flash → Kimi K2.6 → Gemma 4 31B →
          NVIDIA Nemotron Omni → OpenRouter free
  Paid:   GPT-4o → GPT-4o-mini → Claude 3.5 Sonnet → Claude 3 Haiku →
          Llama 3.2 90B Vision → Qwen VL 8B

Custom model (auto-routes to best provider):
  --model "gpt-4o"         → tries native OpenAI first, then OpenRouter
  --model "claude-sonnet-4" → tries native Anthropic first, then OpenRouter
  --model "gemini-2.5-flash" → tries native Gemini first, then OpenRouter
  --model "openrouter/free"  → OpenRouter only
  Set VISION_MODEL env var or DEFAULT_MODEL in config.json for persistence.

Supported provider keys (set via setup.py or env vars):
  GEMINI_API_KEY | OPENROUTER_API_KEY | FREEAI_API_KEY | MOONDREAM_API_KEY |
  OPENAI_API_KEY | ANTHROPIC_API_KEY

Usage:
  python vision_proxy.py <image_or_video_path> [prompt text...] [--model NAME]

First run? Run setup.py to configure your API keys:
  python setup.py
"""


import base64
import json
import os
import sys
import io
import mimetypes
import urllib.request
import urllib.error
import subprocess
import tempfile
import shutil
import string
import time
import concurrent.futures

# ── UTF-8 stdout wrapper (Windows cp1252 fix) — module level ──────────

if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
    try:
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )
    except (AttributeError, TypeError, ValueError):
        pass


def _wrap_utf8():
    """Idempotent no-op — wrapping is done at module level."""
    pass


# ── Cross-drive file search — finds files on ANY drive, no restrictions ─
_SEARCH_CACHE = {}
_GLOBAL_SEARCH_TIMEOUT = 15  # hard limit for entire search (seconds)

def _get_all_drives():
    """Detect all available drives (A:-Z: on Windows, / on Unix)."""
    key = "_all_drives"
    if key in _SEARCH_CACHE:
        return _SEARCH_CACHE[key]
    drives = []
    if sys.platform == "win32":
        for letter in string.ascii_uppercase:
            path = f"{letter}:\\"
            try:
                if os.path.exists(path):
                    drives.append(path)
            except Exception:
                continue
    else:
        drives.append("/")
    _SEARCH_CACHE[key] = drives
    return drives


def _get_search_dirs():
    """Every directory we check directly — drive roots + common user dirs on ALL drives.
    
    Returns two lists: (phase1_dirs, phase3_dirs).
    - phase1_dirs: all dirs for instant direct checks (includes large containers like Users)
    - phase3_dirs: ONLY small end-user dirs safe for recursive scandir (Desktop, Downloads, etc.)
    """
    key = "dirs"
    if key in _SEARCH_CACHE:
        return _SEARCH_CACHE[key]
    all_dirs = set()
    shallow_dirs = set()
    username = os.environ.get("USERNAME", "")

    for drive in _get_all_drives():
        root = drive.rstrip("\\/")
        all_dirs.add(root)

        users = os.path.join(drive, "Users")
        if os.path.isdir(users):
            all_dirs.add(users)
            if username:
                for sub in ("Desktop", "Downloads", "Pictures", "Documents",
                            "Music", "Videos", "OneDrive"):
                    p = os.path.join(users, username, sub)
                    if os.path.isdir(p):
                        all_dirs.add(p)
                        shallow_dirs.add(p)
                ss = os.path.join(users, username, "Pictures", "Screenshots")
                if os.path.isdir(ss):
                    all_dirs.add(ss)
                    shallow_dirs.add(ss)
            pub = os.path.join(users, "Public")
            if os.path.isdir(pub):
                all_dirs.add(pub)

        for common in ("Temp", "Data", "Projects", "Workspace", "Shared", "Backup", "Home"):
            p = os.path.join(drive, common)
            if os.path.isdir(p):
                all_dirs.add(p)
                shallow_dirs.add(p)

    home = os.path.abspath(os.path.expanduser("~"))
    all_dirs.add(home)
    try:
        cwd = os.path.abspath(os.getcwd())
        all_dirs.add(cwd)
        shallow_dirs.add(cwd)
    except Exception:
        pass

    result = (sorted(all_dirs), sorted(shallow_dirs))
    _SEARCH_CACHE[key] = result
    return result


_SKIP_DIR_NAMES = {
    "$recycle.bin", "$sysreset", "system volume information",
    "windows", "winnt", "winxs", "program files", "program files (x86)",
    "programdata", "config.msi", "boot", "recovery", "perflogs",
    "recycler", "python314", "python313", "python312", "python311",
    "msocache", "cache", "amd64", "i386",
}

_SKIP_PREFIXES = {"$", "."}

def _should_skip_dir(name):
    """Check if a directory should be skipped during search."""
    lower = name.lower()
    if lower in _SKIP_DIR_NAMES:
        return True
    if name.startswith("$") or name.startswith("."):
        return True
    return False


def _scandir_walk(root_dir, filename, deadline, max_depth=5,
                  partial=False, stop_early=True, seen=None):
    """Fast file search using os.scandir with strict deadline at every level.
    
    Yields absolute paths to matching files. Checks `time.time() >= deadline`
    before every directory entry — never blocks longer than remaining time.
    Skips system directories ($Recycle.Bin, Windows, Program Files, etc.).
    """
    if seen is None:
        seen = set()
    if not os.path.isdir(root_dir):
        return

    root_dir = os.path.abspath(root_dir)
    file_lower = filename.lower()
    file_stem, file_ext = os.path.splitext(filename)
    stem_lower = file_stem.lower() if file_stem else ""
    ext_lower = file_ext.lower() if file_ext else ""

    # BFS with depth tracking — most matches are near the root
    queue = [(root_dir, 0)]
    while queue and time.time() < deadline:
        dirpath, depth = queue.pop(0)
        if depth > max_depth:
            continue
        try:
            with os.scandir(dirpath) as entries:
                for entry in entries:
                    if time.time() >= deadline:
                        return
                    try:
                        is_dir = entry.is_dir(follow_symlinks=False)
                    except OSError:
                        continue
                    if is_dir:
                        if depth < max_depth and not _should_skip_dir(entry.name):
                            queue.append((entry.path, depth + 1))
                    else:
                        name = entry.name
                        if partial:
                            if stem_lower and (stem_lower in name.lower()):
                                if ext_lower:
                                    if not name.lower().endswith(ext_lower):
                                        continue
                                abspath = entry.path
                                if abspath not in seen:
                                    seen.add(abspath)
                                    yield abspath
                                    if stop_early:
                                        return
                        else:
                            if name.lower() == file_lower:
                                abspath = entry.path
                                if abspath not in seen:
                                    seen.add(abspath)
                                    yield abspath
                                    if stop_early:
                                        return
        except (PermissionError, OSError):
            continue


def find_file(name, max_results=5):
    """Find a file anywhere on the system — ALL drives, no restrictions.
    
    Strategy (fast → slow) with a global timeout:
      1. Direct check against every search dir (instant)
      2. BFS scandir on drive roots (strict deadline, depth 5)
      3. BFS scandir on shallow dirs  (strict deadline, depth 5)
      4. Partial-match fallback (stem + ext)
    
    If the global timeout is hit, returns whatever was found so far.
    Results are cached so repeated lookups for the same file are instant.
    """
    if not name:
        return []
    name = name.strip().strip('"\'').strip()
    basename = os.path.basename(name)
    if not basename:
        return []

    abs_check = os.path.abspath(name)
    if os.path.isfile(abs_check):
        return [abs_check]

    all_dirs, shallow_dirs = _get_search_dirs()
    cache_key = (basename, tuple(all_dirs), tuple(shallow_dirs), tuple(_get_all_drives()))
    if cache_key in _SEARCH_CACHE:
        return _SEARCH_CACHE[cache_key]

    deadline = time.time() + _GLOBAL_SEARCH_TIMEOUT
    results = []
    seen = set()
    all_drives = _get_all_drives()
    drive_roots = {d.rstrip("\\/") for d in all_drives}

    # ── Phase 1: Direct check (instant) — all dirs ───────────────────
    for d in all_dirs:
        if time.time() >= deadline:
            break
        candidate = os.path.join(d, basename)
        if os.path.isfile(candidate):
            abspath = os.path.abspath(candidate)
            if abspath not in seen:
                seen.add(abspath)
                results.append(abspath)
                if len(results) >= max_results:
                    _SEARCH_CACHE[cache_key] = results
                    return results

    # ── Phase 2: Drive root search — ALL drives in PARALLEL ──────────
    if time.time() < deadline and len(results) < max_results:
        drives_to_search = [d for d in all_drives if os.path.isdir(d)]
        print(f"SEARCH: Scanning {len(drives_to_search)} drive(s) in parallel...", file=sys.stderr, flush=True)
        for match in _parallel_search(drives_to_search, basename, deadline,
                                       max_depth=5, partial=False):
            if len(results) >= max_results:
                break
            if match not in seen:
                seen.add(match)
                results.append(match)
                if len(results) >= max_results:
                    _SEARCH_CACHE[cache_key] = results
                    return results

    # ── Phase 3: Shallow dir search — ALL dirs in PARALLEL ───────────
    if time.time() < deadline and len(results) < max_results:
        shallow_to_search = [d for d in shallow_dirs
                             if os.path.isdir(d) and d.rstrip("\\/") not in drive_roots]
        for match in _parallel_search(shallow_to_search, basename, deadline,
                                       max_depth=5, partial=False):
            if len(results) >= max_results:
                break
            if match not in seen:
                seen.add(match)
                results.append(match)
                if len(results) >= max_results:
                    _SEARCH_CACHE[cache_key] = results
                    return results

    # ── Phase 4: Partial match fallback — ALL in PARALLEL ────────────
    stem, ext = os.path.splitext(basename)
    if stem and time.time() < deadline and len(results) < max_results:
        partial_to_search = []
        partial_to_search.extend(d for d in all_drives if os.path.isdir(d))
        partial_to_search.extend(d for d in shallow_dirs
                                 if os.path.isdir(d) and d.rstrip("\\/") not in drive_roots)
        for match in _parallel_search(partial_to_search, basename, deadline,
                                       max_depth=5, partial=True):
            if len(results) >= max_results:
                break
            if match not in seen:
                seen.add(match)
                results.append(match)
                if len(results) >= max_results:
                    _SEARCH_CACHE[cache_key] = results
                    return results

    _SEARCH_CACHE[cache_key] = results
    return results


def _parallel_search(search_items, basename, deadline, partial=False, max_depth=5, max_workers=8):
    """Run _scandir_walk on multiple roots in parallel. Yields results as they come."""
    seen_par = set()
    found = []
    lock = None  # not needed since we collect per-thread and merge

    def _search_one(root):
        local_results = []
        for match in _scandir_walk(root, basename, deadline,
                                    max_depth=max_depth, partial=partial,
                                    stop_early=False, seen=set()):
            local_results.append(match)
        return local_results

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_search_one, item): item for item in search_items}
        for future in concurrent.futures.as_completed(futures, timeout=deadline - time.time()):
            if time.time() >= deadline:
                break
            try:
                for match in future.result():
                    if match not in seen_par:
                        seen_par.add(match)
                        found.append(match)
                        yield match
            except Exception:
                continue

    for m in found:
        yield m


# ── Config loader ────────────────────────────────────────────────────────
# Primary: %APPDATA%/vision-tool/config.json (persists across reinstalls)
# Fallback: script_dir/config.json (legacy, backward compat)
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_APPDATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "vision-tool")
CONFIG_PATH = os.path.join(_APPDATA_DIR, "config.json")
CONFIG_PATH_LOCAL = os.path.join(_SCRIPT_DIR, "config.json")


ALL_PROVIDER_KEYS = ["GEMINI_API_KEY", "OPENROUTER_API_KEY", "FREEAI_API_KEY", "MOONDREAM_API_KEY", "HF_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]


def _find_config():
    """Return first config path that exists: local (explicit) > AppData (persistent) > default AppData."""
    if os.path.isfile(CONFIG_PATH_LOCAL):
        return CONFIG_PATH_LOCAL
    if os.path.isfile(CONFIG_PATH):
        return CONFIG_PATH
    return CONFIG_PATH


def _ensure_config_dir():
    """Make sure the AppData config directory exists."""
    try:
        os.makedirs(_APPDATA_DIR, exist_ok=True)
    except Exception:
        pass


def save_config(config):
    """Save config to the persistent AppData location."""
    _ensure_config_dir()
    tmp = CONFIG_PATH + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(config, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, CONFIG_PATH)
    except Exception:
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f)
    # Also sync to local for backward compat
    try:
        with open(CONFIG_PATH_LOCAL, "w") as f:
            json.dump(config, f)
    except Exception:
        pass


def load_config():
    keys = {
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY"),
        "OPENROUTER_API_KEY": os.environ.get("OPENROUTER_API_KEY"),
        "FREEAI_API_KEY": os.environ.get("FREEAI_API_KEY"),
        "MOONDREAM_API_KEY": os.environ.get("MOONDREAM_API_KEY"),
        "HF_TOKEN": os.environ.get("HF_TOKEN"),
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY"),
        "DEFAULT_MODEL": os.environ.get("VISION_MODEL"),
    }
    cfg_path = _find_config()
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, "r") as f:
                cfg = json.load(f)
        except (json.JSONDecodeError, IOError):
            cfg = None
        if isinstance(cfg, dict):
            for k in list(keys):
                if not keys[k]:
                    keys[k] = cfg.get(k)
    present = [k for k in ALL_PROVIDER_KEYS if keys.get(k)]
    if not present:
        raise RuntimeError(
            "No API keys configured.\n"
            "  Run setup.py to configure:  python setup.py\n"
            "  Or set environment variables (any one is enough):\n"
            "    $env:GEMINI_API_KEY='your-key'\n"
            "    $env:OPENROUTER_API_KEY='your-key'\n"
            "    $env:FREEAI_API_KEY='sk-free-...'    (free.ai, 30K tokens/day)\n"
            "    $env:MOONDREAM_API_KEY='your-key'    (moondream.ai, 5000/day)\n"
            "    $env:HF_TOKEN='hf_...'               (huggingface.co/settings/tokens)\n"
            "    $env:OPENAI_API_KEY='your-key'\n"
            "    $env:ANTHROPIC_API_KEY='your-key'\n"
            "    $env:VISION_MODEL='model-name'    (optional default model)"
        )
    return keys


CFG = None


def _has_key(name):
    """Check if a backend's required API key is set in CFG."""
    if CFG is None:
        return True  # can't check, assume present
    if "Gemini" in name:
        return bool(CFG.get("GEMINI_API_KEY"))
    if "Freeai" in name or "Free.ai" in name:
        return bool(CFG.get("FREEAI_API_KEY"))
    if "Moondream" in name:
        return bool(CFG.get("MOONDREAM_API_KEY"))
    if "HF" in name or "Hugging" in name:
        return bool(CFG.get("HF_TOKEN"))
    return bool(CFG.get("OPENROUTER_API_KEY"))


def _print_available_keys():
    """Print which API keys are configured."""
    key_labels = [
        ("GEMINI_API_KEY", "Gemini"),
        ("OPENROUTER_API_KEY", "OpenRouter"),
        ("FREEAI_API_KEY", "Free.ai"),
        ("MOONDREAM_API_KEY", "Moondream"),
        ("HF_TOKEN", "HuggingFace"),
        ("OPENAI_API_KEY", "OpenAI"),
        ("ANTHROPIC_API_KEY", "Anthropic"),
    ]
    parts = []
    for env_key, label in key_labels:
        if CFG and CFG.get(env_key):
            parts.append(f"{label} \u2713")
        else:
            parts.append(f"{label} \u2717")
    print(f"KEYS: {'  '.join(parts)}", file=sys.stderr, flush=True)


# ── File-type helpers ────────────────────────────────────────────────────
VIDEO_EXT = {".mp4", ".webm", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".m4v"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def get_mime(path):
    m, _ = mimetypes.guess_type(path)
    if m:
        return m
    ext = os.path.splitext(path)[1].lower()
    img = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
           ".webp": "image/webp", ".bmp": "image/bmp"}
    vid = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
           ".avi": "video/x-msvideo", ".mkv": "video/x-matroska",
           ".flv": "video/x-flv", ".wmv": "video/x-ms-wmv", ".m4v": "video/mp4"}
    return img.get(ext) or vid.get(ext) or "image/png"


def is_video(path):
    return os.path.splitext(path)[1].lower() in VIDEO_EXT


def is_image(path):
    return os.path.splitext(path)[1].lower() in IMAGE_EXT


# ── Image resize ─────────────────────────────────────────────────────────
MAX_IMAGE_DIM = 2048  # higher = more detail for complex designs


def resize_image(path, max_dim=None):
    if max_dim is None:
        max_dim = MAX_IMAGE_DIM
    try:
        from PIL import Image
        from PIL import UnidentifiedImageError

        img = Image.open(path)
        w, h = img.size
        if w <= max_dim and h <= max_dim:
            with open(path, "rb") as f:
                return f.read(), get_mime(path)
        if w > h:
            nw, nh = max_dim, int(h * max_dim / w)
        else:
            nw, nh = int(w * max_dim / h), max_dim
        img = img.resize((nw, nh), Image.LANCZOS)
        buf = io.BytesIO()
        fmt = {".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP",
               ".bmp": "BMP"}.get(os.path.splitext(path)[1].lower(), "PNG")
        img.save(buf, format=fmt)
        return buf.getvalue(), get_mime(path)
    except ImportError:
        with open(path, "rb") as f:
            return f.read(), get_mime(path)
    except (UnidentifiedImageError,):
        with open(path, "rb") as f:
            return f.read(), get_mime(path)


# ── Video keyframe extraction ────────────────────────────────────────────
def extract_video_frames(path, max_frames=8):
    """Extract evenly-spaced keyframes via ffmpeg.  Falls back to raw bytes."""
    ext = os.path.splitext(path)[1].lower()

    # ── Animated GIF ─────────────────────────────────────────────────
    if ext == ".gif":
        try:
            from PIL import Image

            img = Image.open(path)
            frames = []
            try:
                while True:
                    frames.append(img.copy().convert("RGB"))
                    img.seek(img.tell() + 1)
            except EOFError:
                pass
            if not frames:
                with open(path, "rb") as f:
                    return [(f.read(), "image/gif")]
            step = max(len(frames) // max_frames, 1)
            selected = frames[::step][:max_frames]
            result = []
            for f in selected:
                buf = io.BytesIO()
                f.save(buf, format="JPEG", quality=85)
                result.append((buf.getvalue(), "image/jpeg"))
            return result
        except ImportError:
            with open(path, "rb") as f:
                return [(f.read(), "image/gif")]
        except Exception:
            with open(path, "rb") as f:
                return [(f.read(), "image/gif")]

    # ── Regular video ────────────────────────────────────────────────
    try:
        dur = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=30,
        )
        duration = float(dur.stdout.strip())
    except Exception:
        duration = 10

    if duration <= 0:
        duration = 10

    num = min(max_frames, max(2, int(duration)))
    interval = duration / num
    tmpdir = tempfile.mkdtemp()
    frames = []

    try:
        for i in range(num):
            ts = i * interval
            out = os.path.join(tmpdir, f"f_{i:03d}.jpg")
            subprocess.run(
                ["ffmpeg", "-ss", str(ts), "-i", path,
                 "-vframes", "1", "-q:v", "2", "-vf", "scale=1024:-1",
                 "-y", out],
                capture_output=True, timeout=30,
            )
            if os.path.isfile(out) and os.path.getsize(out) > 0:
                with open(out, "rb") as f:
                    frames.append((f.read(), "image/jpeg"))
                os.remove(out)
    except Exception:
        pass
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    if not frames:
        with open(path, "rb") as f:
            return [(f.read(), get_mime(path))]
    return frames


# ── API helpers ──────────────────────────────────────────────────────────
def b64(data):
    return base64.b64encode(data).decode("utf-8")


def build_multimodal_content(frames, prompt):
    parts = [{"type": "text", "text": prompt}]
    for data, mime in frames:
        parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64(data)}"}})
    return parts


def build_gemini_parts(frames, prompt):
    parts = [{"text": f"{prompt}\n[Video split into {len(frames)} frames — analyse them in sequence]"}]
    for data, mime in frames:
        parts.append({"inline_data": {"mime_type": mime, "data": b64(data)}})
    return parts


# ── Backend callers ──────────────────────────────────────────────────────
def call_openrouter(b64data, mime, prompt, model):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64data}"}},
        ]}],
    }
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {CFG['OPENROUTER_API_KEY']}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/farhanic017/vision-tool",
        },
    )
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read())["choices"][0]["message"]["content"]


def call_openrouter_multi(frames, prompt, model):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": build_multimodal_content(frames, prompt)}],
    }
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {CFG['OPENROUTER_API_KEY']}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/farhanic017/vision-tool",
        },
    )
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read())["choices"][0]["message"]["content"]


def call_gemini(b64data, mime, prompt, model="gemini-2.5-flash"):
    payload = {
        "contents": [{"parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": mime, "data": b64data}},
        ]}],
    }
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={CFG['GEMINI_API_KEY']}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=15)
    result = json.loads(resp.read())
    return result["candidates"][0]["content"]["parts"][0]["text"]


def call_gemini_multi(frames, prompt, model="gemini-2.5-flash"):
    payload = {"contents": [{"parts": build_gemini_parts(frames, prompt)}]}
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={CFG['GEMINI_API_KEY']}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=15)
    result = json.loads(resp.read())
    return result["candidates"][0]["content"]["parts"][0]["text"]


def call_openai(b64data, mime, prompt, model):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64data}"}},
        ]}],
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {CFG['OPENAI_API_KEY']}",
            "Content-Type": "application/json",
        },
    )
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read())["choices"][0]["message"]["content"]


def call_openai_multi(frames, prompt, model):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": build_multimodal_content(frames, prompt)}],
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {CFG['OPENAI_API_KEY']}",
            "Content-Type": "application/json",
        },
    )
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read())["choices"][0]["message"]["content"]


def call_anthropic(b64data, mime, prompt, model):
    payload = {
        "model": model,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64data}},
        ]}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode(),
        headers={
            "x-api-key": CFG["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
    )
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read())["content"][0]["text"]


def call_anthropic_multi(frames, prompt, model):
    content = [{"type": "text", "text": prompt}]
    for data, mime in frames:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": mime, "data": b64(data)},
        })
    payload = {
        "model": model,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": content}],
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode(),
        headers={
            "x-api-key": CFG["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
    )
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read())["content"][0]["text"]


# ── Free.ai caller (OpenAI-compatible, endpoint /v1/chat/) ─────────────
# Free.ai offers 30,000 tokens/day free. Vision models: internvl-3-8b, molmo-7b.
# Docs: https://free.ai/api/  |  Sign up: https://free.ai/signup/

FREEAI_ENDPOINT = "https://api.free.ai/v1/chat/"


def call_freeai(b64data, mime, prompt, model="internvl-3-8b"):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64data}"}},
        ]}],
    }
    req = urllib.request.Request(
        FREEAI_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {CFG['FREEAI_API_KEY']}",
            "Content-Type": "application/json",
        },
    )
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read())["choices"][0]["message"]["content"]


def call_freeai_multi(frames, prompt, model="internvl-3-8b"):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": build_multimodal_content(frames, prompt)}],
    }
    req = urllib.request.Request(
        FREEAI_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {CFG['FREEAI_API_KEY']}",
            "Content-Type": "application/json",
        },
    )
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read())["choices"][0]["message"]["content"]


# ── Moondream caller (native API — /v1/caption, /v1/query) ─────────────
# Moondream offers 5,000 requests/day free tier.
# Docs: https://docs.moondream.ai  |  Console: https://console.moondream.ai
# Uses /v1/query for detailed prompts, /v1/caption as fallback.

MOONDREAM_BASE = "https://api.moondream.ai/v1"


def _moondream_headers():
    return {
        "X-Moondream-Auth": CFG["MOONDREAM_API_KEY"],
        "Content-Type": "application/json",
    }


def call_moondream(b64data, mime, prompt, model=None):
    """Analyse a single image via Moondream."""
    url = f"{MOONDREAM_BASE}/query"
    payload = {
        "image_url": f"data:{mime};base64,{b64data}",
        "question": prompt,
    }
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=_moondream_headers(),
    )
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())["answer"]


def call_moondream_multi(frames, prompt, model=None):
    """Analyse video frames via Moondream — queries each frame, returns combined."""
    answers = []
    for i, (data, mime) in enumerate(frames[:4]):  # max 4 frames
        b = b64(data)
        url = f"{MOONDREAM_BASE}/query"
        payload = {
            "image_url": f"data:{mime};base64,{b}",
            "question": f"Frame {i+1}: {prompt[:500]}",
        }
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), headers=_moondream_headers(),
        )
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        answers.append(f"--- Frame {i+1} ---\n{result['answer']}")
    return "\n\n".join(answers)


# ── Hugging Face Inference Providers caller ───────────────────────────
# Uses Hugging Face Inference Providers API (router.huggingface.co) with
# vision models. Free tier available with a HF token.
# Docs: https://huggingface.co/docs/api-inference/en/index

HF_ROUTER_ENDPOINT = "https://router.huggingface.co/v1/chat/completions"


def _hf_headers():
    return {
        "Authorization": f"Bearer {CFG['HF_TOKEN']}",
        "Content-Type": "application/json",
    }


def _hf_default_model():
    """Return a known-good small vision model."""
    return "Qwen/Qwen3-VL-8B-Instruct"


def call_hf_inference(b64data, mime, prompt, model=None):
    """Analyse a single image via Hugging Face Inference Providers."""
    model = model or _hf_default_model()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64data}"}},
            {"type": "text", "text": prompt},
        ]}],
        "max_tokens": 1024,
    }
    req = urllib.request.Request(
        HF_ROUTER_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers=_hf_headers(),
    )
    resp = urllib.request.urlopen(req, timeout=60)
    return json.loads(resp.read())["choices"][0]["message"]["content"]


def call_hf_multi(frames, prompt, model=None):
    """Analyse video frames via Hugging Face Inference Providers."""
    model = model or _hf_default_model()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": build_multimodal_content(frames, prompt)}],
        "max_tokens": 1024,
    }
    req = urllib.request.Request(
        HF_ROUTER_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers=_hf_headers(),
    )
    resp = urllib.request.urlopen(req, timeout=60)
    return json.loads(resp.read())["choices"][0]["message"]["content"]


# ── Provider routing ───────────────────────────────────────────────────

def get_providers_for_model(model):
    """Return ordered list of (provider_name, native_model_name) tuples.

    Tries native APIs first for recognised model patterns, then falls back
    to OpenRouter (the universal gateway).  Each provider is only returned
    once and only if its API key is already loaded in CFG.
    """
    ml = model.lower()
    stripped = model
    # Strip OpenRouter-style provider prefix
    if '/' in model:
        prefix = model.split('/', 1)[0].lower()
        stripped = model.split('/', 1)[1]
        if prefix in ("google",):
            return _filter_providers([("gemini", stripped), ("openrouter", model)])
        if prefix == "openai":
            return _filter_providers([("openai", stripped), ("openrouter", model)])
        if prefix == "anthropic":
            return _filter_providers([("anthropic", stripped), ("openrouter", model)])
        # Unknown prefix — OpenRouter only
        return _filter_providers([("openrouter", model)])

    # No prefix — detect from model name patterns
    candidates = []
    if ml.startswith("gemini"):
        candidates.append(("gemini", stripped))
    if ml.startswith(("gpt", "o1", "o3")) or ml.startswith("chatgpt"):
        candidates.append(("openai", stripped))
    if ml.startswith("claude"):
        candidates.append(("anthropic", stripped))
    candidates.append(("openrouter", model))
    return _filter_providers(candidates)


def _filter_providers(candidates):
    """Remove duplicate providers and skip those without a configured key."""
    PROVIDER_KEY_MAP = {
        "gemini": "GEMINI_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "hf": "HF_TOKEN",
        "openrouter": "OPENROUTER_API_KEY",
    }
    seen = set()
    result = []
    for prov, m in candidates:
        if prov in seen:
            continue
        seen.add(prov)
        key_name = PROVIDER_KEY_MAP.get(prov)
        if key_name and CFG and CFG.get(key_name):
            result.append((prov, m))
    return result


# ── Total-timeout wrapper ──────────────────────────────────────────────
# urllib's `timeout=15` is a *socket idle* timeout only.
# If the API sends chunked streaming data, data arrives periodically
# and the socket never times out. This wrapper enforces a TOTAL
# wall-clock timeout using a thread.

def _call_with_timeout(fn, timeout_sec=15):
    """Execute fn() with a total wall-clock timeout.
    
    If fn() doesn't complete within timeout_sec, the thread is orphaned
    (keeps running in background, GC collects when done) and TimeoutError
    is raised. Prevents chunked/streaming API responses from hanging
    forever despite socket-level timeouts.
    """
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(fn)
    try:
        return fut.result(timeout=timeout_sec)
    except concurrent.futures.TimeoutError:
        raise TimeoutError(f"Backend timed out after {timeout_sec}s")
    finally:
        pool.shutdown(wait=False)


# ── Public API ──────────────────────────────────────────────────────────

def analyze(file_path, prompt="", model=None):
    """Analyse an image or video file and return the description text.

    Args:
        file_path: Absolute path to image or video file.
        prompt: Optional custom prompt. Auto-generated if empty.
        model: Optional model name. Auto-routes to the best provider
               (native API if recognised, then OpenRouter).  Set via
               VISION_MODEL env var or DEFAULT_MODEL in config.json.

    Returns:
        Description string from the first successful backend.

    Raises:
        FileNotFoundError: If file does not exist.
        RuntimeError: If all backends fail.
    """
    if not os.path.isfile(file_path):
        print("SEARCH: Locating file...", file=sys.stderr, flush=True)
        found = find_file(file_path, max_results=1)
        if found:
            file_path = found[0]
            print(f"SEARCH: Found -> {file_path}", file=sys.stderr, flush=True)
        else:
            print("SEARCH: Not found", file=sys.stderr, flush=True)
            raise FileNotFoundError(
                f"File not found: {file_path}\n"
                f"  Tried: Desktop, Downloads, Pictures, Documents, CWD, and user profile.\n"
                f"  Pass the full absolute path or make sure the file is on Desktop/Downloads/Pictures."
            )
    else:
        print(f"SEARCH: File exists at {file_path}", file=sys.stderr, flush=True)

    vid = is_video(file_path)

    global CFG
    CFG = load_config()
    _print_available_keys()

    # Resolve model: explicit arg > config default > fallback chain
    model = model or CFG.get("DEFAULT_MODEL", "") or None

    if not prompt:
        if vid:
            prompt = (
                "EXHAUSTIVE VIDEO ANALYSIS — Extract EVERY detail frame by frame:\n"
                "1) ALL visible text — read every word, label, button, menu item, heading, paragraph\n"
                "2) Exact layout — positions, dimensions, spacing, alignment, grid structure\n"
                "3) Colors — hex codes where identifiable, palette, gradients, opacity\n"
                "4) UI elements — buttons, inputs, cards, modals, navigation, icons (describe each)\n"
                "5) Typography — font families, sizes, weights, line heights, letter spacing\n"
                "6) Actions and interactions — transitions, animations, hover states, scroll behavior\n"
                "7) Scene changes — what changed between frames, timing, transitions\n"
                "8) Visual design tokens — shadows, borders, border-radius, backgrounds, overlays\n"
                "9) Images and media — describe all visible imagery, icons, illustrations\n"
                "10) Spacing and proportions — padding, margins, gaps, percentages, ratios\n\n"
                "Be exhaustive. Describe every pixel column by column, section by section. "
                "This is for following a COMPLEX DESIGN faithfully — missing details will break the output."
            )
        else:
            prompt = (
                "EXHAUSTIVE IMAGE ANALYSIS — Extract EVERY detail visible:\n"
                "1) ALL visible text — read every word, label, button, menu item, heading, paragraph verbatim\n"
                "2) Exact layout — positions, dimensions, spacing, alignment, grid/column structure\n"
                "3) Colors — hex codes where identifiable, palette, gradients, opacity, shadows\n"
                "4) UI elements — buttons, inputs, cards, modals, navigation, tabs, sliders, icons (describe shape, size, color, state)\n"
                "5) Typography — font families, sizes, weights, line heights, letter spacing, alignment\n"
                "6) Visual style — border-radius, box-shadows, borders, backgrounds, overlays, glass effects\n"
                "7) Images and media — describe all visible imagery, icons, illustrations, their positions and sizes\n"
                "8) Spacing — padding, margins, gaps between elements, section proportions\n"
                "9) States — hover, active, disabled, selected, focused (if identifiable)\n"
                "10) Responsive behavior — any indications of how layout changes at different sizes\n\n"
                "Be exhaustive. This is for following a COMPLEX DESIGN faithfully — "
                "missing any detail will break the output. Describe section by section from top to bottom."
            )

    if vid:
        frames = extract_video_frames(file_path, max_frames=8)

        strategies = [
            ("\u2606 HF Qwen3-VL-8B", lambda: call_hf_multi(frames, prompt, "Qwen/Qwen3-VL-8B-Instruct")),
            ("\u2606 Free.ai InternVL 3 8B", lambda: call_freeai_multi(frames, prompt, "internvl-3-8b")),
            ("\u2606 Free.ai Molmo 7B", lambda: call_freeai_multi(frames, prompt, "molmo-7b")),
            ("\u2606 Moondream", lambda: call_moondream_multi(frames, prompt, "moondream3")),
            ("\u2606 Gemma 4 26B", lambda: call_openrouter_multi(frames, prompt, "google/gemma-4-26b-a4b-it:free")),
            ("\u2606 NVIDIA Nemotron VL", lambda: call_openrouter_multi(frames, prompt, "nvidia/nemotron-nano-12b-v2-vl:free")),
            ("\u2606 Gemini 2.5 Flash", lambda: call_gemini_multi(frames, prompt, "gemini-2.5-flash")),
            ("\u2606 Gemini 2.0 Flash", lambda: call_gemini_multi(frames, prompt, "gemini-2.0-flash")),
            ("\u2606 Kimi K2.6", lambda: call_openrouter_multi(frames, prompt, "moonshotai/kimi-k2.6:free")),
            ("\u2606 Gemma 4 31B", lambda: call_openrouter_multi(frames, prompt, "google/gemma-4-31b-it:free")),
            ("\u2606 NVIDIA Nemotron Omni", lambda: call_openrouter_multi(frames, prompt, "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free")),
            ("\u2606 OpenRouter free", lambda: call_openrouter_multi(frames, prompt, "openrouter/free")),
            ("\u2605 GPT-4o", lambda: call_openrouter_multi(frames, prompt, "openai/gpt-4o")),
            ("\u2605 GPT-4o-mini", lambda: call_openrouter_multi(frames, prompt, "openai/gpt-4o-mini")),
            ("\u2605 Claude 3.5 Sonnet", lambda: call_openrouter_multi(frames, prompt, "anthropic/claude-3.5-sonnet")),
            ("\u2605 Claude 3 Haiku", lambda: call_openrouter_multi(frames, prompt, "anthropic/claude-3-haiku")),
            ("\u2605 Llama 3.2 90B Vision", lambda: call_openrouter_multi(frames, prompt, "meta-llama/llama-3.2-90b-vision-instruct")),
            ("\u2605 Qwen VL 8B", lambda: call_openrouter_multi(frames, prompt, "qwen/qwen3-vl-8b-instruct")),
        ]
        # Insert custom model strategies (provider-aware)
        if model:
            _insert_model_strategies(strategies, model, "vid", frames, prompt)
    else:
        data, mime = resize_image(file_path, 1024)
        img_b64 = b64(data)

        strategies = [
            ("\u2606 HF Qwen3-VL-8B", lambda: call_hf_inference(img_b64, mime, prompt, "Qwen/Qwen3-VL-8B-Instruct")),
            ("\u2606 Free.ai InternVL 3 8B", lambda: call_freeai(img_b64, mime, prompt, "internvl-3-8b")),
            ("\u2606 Free.ai Molmo 7B", lambda: call_freeai(img_b64, mime, prompt, "molmo-7b")),
            ("\u2606 Moondream", lambda: call_moondream(img_b64, mime, prompt, "moondream3")),
            ("\u2606 Gemma 4 26B", lambda: call_openrouter(img_b64, mime, prompt, "google/gemma-4-26b-a4b-it:free")),
            ("\u2606 NVIDIA Nemotron VL", lambda: call_openrouter(img_b64, mime, prompt, "nvidia/nemotron-nano-12b-v2-vl:free")),
            ("\u2606 Gemini 2.5 Flash", lambda: call_gemini(img_b64, mime, prompt, "gemini-2.5-flash")),
            ("\u2606 Gemini 2.0 Flash", lambda: call_gemini(img_b64, mime, prompt, "gemini-2.0-flash")),
            ("\u2606 Kimi K2.6", lambda: call_openrouter(img_b64, mime, prompt, "moonshotai/kimi-k2.6:free")),
            ("\u2606 Gemma 4 31B", lambda: call_openrouter(img_b64, mime, prompt, "google/gemma-4-31b-it:free")),
            ("\u2606 NVIDIA Nemotron Omni", lambda: call_openrouter(img_b64, mime, prompt, "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free")),
            ("\u2606 OpenRouter free", lambda: call_openrouter(img_b64, mime, prompt, "openrouter/free")),
            ("\u2605 GPT-4o", lambda: call_openrouter(img_b64, mime, prompt, "openai/gpt-4o")),
            ("\u2605 GPT-4o-mini", lambda: call_openrouter(img_b64, mime, prompt, "openai/gpt-4o-mini")),
            ("\u2605 Claude 3.5 Sonnet", lambda: call_openrouter(img_b64, mime, prompt, "anthropic/claude-3.5-sonnet")),
            ("\u2605 Claude 3 Haiku", lambda: call_openrouter(img_b64, mime, prompt, "anthropic/claude-3-haiku")),
            ("\u2605 Llama 3.2 90B Vision", lambda: call_openrouter(img_b64, mime, prompt, "meta-llama/llama-3.2-90b-vision-instruct")),
            ("\u2605 Qwen VL 8B", lambda: call_openrouter(img_b64, mime, prompt, "qwen/qwen3-vl-8b-instruct")),
        ]
        if model:
            _insert_model_strategies(strategies, model, "img", img_b64, mime, prompt)

    # Skip backends whose required API key is not configured
    before = len(strategies)
    strategies = [(n, f) for n, f in strategies if _has_key(n)]
    skipped = before - len(strategies)
    if skipped:
        print(f"KEYS: Skipped {skipped}/{before} backends (missing API key)", file=sys.stderr, flush=True)
    print(f"KEYS: Trying {len(strategies)} backends", file=sys.stderr, flush=True)

    # Try backends in parallel batches (3 at a time) — fastest result wins
    BATCH_SIZE = 3
    BATCH_TIMEOUT = 35  # seconds per batch
    last_error = ""
    for batch_start in range(0, len(strategies), BATCH_SIZE):
        batch = strategies[batch_start:batch_start + BATCH_SIZE]
        names = [n for n, _ in batch]
        print(f"BATCH {batch_start//BATCH_SIZE + 1}/{len(strategies)//BATCH_SIZE + 1}: {' / '.join(names)}", file=sys.stderr, flush=True)

        pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(batch))
        try:
            # Each backend gets a 15s total wall-clock timeout via _call_with_timeout
            futs = {pool.submit(lambda f=fn: _call_with_timeout(f, 30)): n for n, fn in batch}
            pending = set(futs)
            try:
                for fut in concurrent.futures.as_completed(futs, timeout=BATCH_TIMEOUT):
                    name = futs[fut]
                    pending.discard(fut)
                    try:
                        text = fut.result()
                        if text and text.strip():
                            print(f"  {name}: OK", file=sys.stderr, flush=True)
                            return text
                        print(f"  {name}: empty response", file=sys.stderr, flush=True)
                    except Exception as e:
                        msg = str(e)
                        if hasattr(e, "code"):
                            msg = f"HTTP {e.code}"
                        last_error = msg
                        print(f"  {name}: FAILED ({msg})", file=sys.stderr, flush=True)
                # All finished without success
                for p in pending:
                    n = futs[p]
                    try:
                        p.result()
                        print(f"  {n}: empty response", file=sys.stderr, flush=True)
                    except Exception as e:
                        msg = str(e)
                        if hasattr(e, "code"):
                            msg = f"HTTP {e.code}"
                        print(f"  {n}: FAILED ({msg})", file=sys.stderr, flush=True)
            except concurrent.futures.TimeoutError:
                print(f"  (batch timed out after {BATCH_TIMEOUT}s)", file=sys.stderr, flush=True)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    raise RuntimeError(f"All vision backends failed. Last error: {last_error}")


def _insert_model_strategies(strategies, model, kind, *args):
    """Insert provider-aware strategies for a custom model at the front.

    Each provider (gemini, openai, anthropic, openrouter) is tried with
    its native API first, then OpenRouter as the universal fallback.
    Only providers with a configured key are included.
    """
    dispatch = {
        "gemini": (call_gemini, call_gemini_multi),
        "openai": (call_openai, call_openai_multi),
        "anthropic": (call_anthropic, call_anthropic_multi),
        "hf": (call_hf_inference, call_hf_multi),
        "freeai": (call_freeai, call_freeai_multi),
        "moondream": (call_moondream, call_moondream_multi),
        "openrouter": (call_openrouter, call_openrouter_multi),
    }
    is_vid = kind == "vid"
    # Reverse so the first matching provider ends up first in strategies
    for prov, native_model in reversed(get_providers_for_model(model)):
        pair = dispatch.get(prov)
        if not pair:
            continue
        fn_img, fn_vid = pair
        fn = fn_vid if is_vid else fn_img
        if is_vid:
            strategies.insert(0, (
                f"\u2605 {prov.title()}: {model}",
                lambda m=native_model, f=fn: f(args[0], prompt, m),
            ))
        else:
            strategies.insert(0, (
                f"\u2605 {prov.title()}: {model}",
                lambda m=native_model, f=fn: f(args[0], args[1], prompt, m),
            ))



# ── CLI entry point ─────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Analyse images and videos using AI vision models.",
        epilog="First run?  python setup.py",
    )
    parser.add_argument("file", help="Path to image or video file")
    parser.add_argument("prompt", nargs="*", help="Optional prompt text")
    parser.add_argument("--model", "-m", help="Custom model name (auto-routes to best provider)")
    args = parser.parse_args()

    file_path = args.file
    prompt = " ".join(args.prompt) if args.prompt else ""
    model = args.model

    try:
        result = analyze(file_path, prompt, model)
        print(result)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
