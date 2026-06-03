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

Tries free backends first, then falls back to others in parallel.
  Priority: Gemini → Azure → Groq → HuggingFace → Mistral in parallel
  Total timeout: 25s | Per-backend timeout: 12s

Custom model (auto-routes to best provider):
  --model "azureai/Phi-4-multimodal-instruct"  → Azure AI Foundry
  --model "cf/@cf/google/gemma-4-26b-a4b-it"   → Cloudflare Workers AI
  --model "groq/meta-llama/llama-4-scout-17b-16e-instruct" → Groq
  Set VISION_MODEL env var or DEFAULT_MODEL in config.json for persistence.

Supported provider keys (set via setup.py or env vars):
  GEMINI_API_KEY | OPENROUTER_API_KEY | CLOUDFLARE_API_KEY | AZUREAI_API_KEY | AZUREAI_ENDPOINT | OPENAI_API_KEY | ANTHROPIC_API_KEY | MISTRAL_API_KEY | GROQ_API_KEY | HF_TOKEN

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
import threading

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


# ── File search — fast, simple, user-dirs only ───────────────────────────
_SEARCH_CACHE = {}
_GLOBAL_SEARCH_TIMEOUT = 5  # seconds for optional recursive fallback


def _get_search_dirs():
    """Known user directories to check for files. No drive scanning."""
    key = "search_dirs"
    if key in _SEARCH_CACHE:
        return _SEARCH_CACHE[key]
    dirs = set()
    username = os.environ.get("USERNAME", "")
    for drive_letter in string.ascii_uppercase:
        drive = f"{drive_letter}:"
        if not os.path.isdir(drive):
            continue
        if username:
            for sub in ("Desktop", "Downloads", "Pictures", "Documents",
                        "Pictures\\Screenshots", "AppData\\Roaming\\Microsoft\\Windows\\Recent"):
                p = os.path.join(drive, "Users", username, sub)
                if os.path.isdir(p):
                    dirs.add(os.path.abspath(p))
    try:
        dirs.add(os.path.abspath(os.getcwd()))
    except Exception:
        pass
    home = os.path.abspath(os.path.expanduser("~"))
    if os.path.isdir(home):
        dirs.add(home)
    result = sorted(dirs)
    _SEARCH_CACHE[key] = result
    return result


def _should_skip_dir(name):
    lower = name.lower()
    if lower in {"$recycle.bin", "windows", "winnt", "program files",
                 "program files (x86)", "programdata", "boot", "recovery",
                 "perflogs", "system volume information"}:
        return True
    return name.startswith("$") or name.startswith(".")


def _scandir_walk(root_dir, filename, deadline, max_depth=3):
    """Quick recursive file search with deadline. Depth-limited."""
    if not os.path.isdir(root_dir):
        return
    root_dir = os.path.abspath(root_dir)
    file_lower = filename.lower()
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
                    elif entry.name.lower() == file_lower:
                        yield os.path.abspath(entry.path)
        except (PermissionError, OSError):
            continue


def find_file(name, max_results=5):
    """Fast file search — checks direct path, then user dirs, then shallow recursive."""
    if not name:
        return []
    name = name.strip().strip('"\'').strip()
    basename = os.path.basename(name)
    if not basename:
        return []

    abs_check = os.path.abspath(name)
    if os.path.isfile(abs_check):
        return [abs_check]

    cache_key = ("find", basename)
    if cache_key in _SEARCH_CACHE:
        return _SEARCH_CACHE[cache_key]

    dirs = _get_search_dirs()
    for d in dirs:
        candidate = os.path.join(d, basename)
        if os.path.isfile(candidate):
            result = [os.path.abspath(candidate)]
            _SEARCH_CACHE[cache_key] = result
            return result

    deadline = time.time() + _GLOBAL_SEARCH_TIMEOUT
    for d in dirs:
        if time.time() >= deadline:
            break
        for match in _scandir_walk(d, basename, deadline, max_depth=3):
            _SEARCH_CACHE[cache_key] = [match]
            return [match]

    _SEARCH_CACHE[cache_key] = []
    return []


# ── Config loader ────────────────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_APPDATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "vision-tool")
CONFIG_PATH = os.path.join(_APPDATA_DIR, "config.json")
CONFIG_PATH_LOCAL = os.path.join(_SCRIPT_DIR, "config.json")


ALL_PROVIDER_KEYS = ["CLOUDFLARE_API_KEY", "AZUREAI_API_KEY", "AZUREAI_ENDPOINT", "GROQ_API_KEY", "HF_TOKEN", "MISTRAL_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "FIREWORKS_API_KEY", "ZAI_API_KEY"]


def _find_config():
    if os.path.isfile(CONFIG_PATH_LOCAL):
        return CONFIG_PATH_LOCAL
    if os.path.isfile(CONFIG_PATH):
        return CONFIG_PATH
    return CONFIG_PATH


def _ensure_config_dir():
    try:
        os.makedirs(_APPDATA_DIR, exist_ok=True)
    except Exception:
        pass


def save_config(config):
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
    try:
        with open(CONFIG_PATH_LOCAL, "w") as f:
            json.dump(config, f)
    except Exception:
        pass


def load_config():
    keys = {
        "CLOUDFLARE_API_KEY": os.environ.get("CLOUDFLARE_API_KEY"),
        "AZUREAI_API_KEY": os.environ.get("AZUREAI_API_KEY"),
        "AZUREAI_ENDPOINT": os.environ.get("AZUREAI_ENDPOINT"),
        "GROQ_API_KEY": os.environ.get("GROQ_API_KEY"),
        "HF_TOKEN": os.environ.get("HF_TOKEN"),
        "MISTRAL_API_KEY": os.environ.get("MISTRAL_API_KEY"),
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY"),
        "OPENROUTER_API_KEY": os.environ.get("OPENROUTER_API_KEY"),
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY"),
        "FIREWORKS_API_KEY": os.environ.get("FIREWORKS_API_KEY"),
        "ZAI_API_KEY": os.environ.get("ZAI_API_KEY"),
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
            "    $env:GEMINI_API_KEY='...'            (aistudio.google.com/apikey)\n"
            "    $env:OPENROUTER_API_KEY='sk-or-...'  (openrouter.ai/keys)\n"
            "    $env:CLOUDFLARE_API_KEY='cfut_...'  (cloudflare.com, Workers AI)\n"
            "    $env:AZUREAI_API_KEY='...'           (Azure AI Foundry)\n"
            "    $env:AZUREAI_ENDPOINT='https://...'  (Azure AI Foundry endpoint)\n"
            "    $env:MISTRAL_API_KEY='...'           (console.mistral.ai/api-keys)\n"
            "    $env:GROQ_API_KEY='gsk_...'          (groq.com, free tier)\n"
            "    $env:HF_TOKEN='hf_...'               (huggingface.co/settings/tokens)\n"
            "    $env:FIREWORKS_API_KEY='fw_...'       (fireworks.ai/api-keys)\n"
            "    $env:OPENAI_API_KEY='sk-...'         (platform.openai.com/api-keys)\n"
            "    $env:ANTHROPIC_API_KEY='sk-ant-...'  (console.anthropic.com/settings/keys)\n"
            "    $env:VISION_MODEL='model-name'    (optional default model)"
        )
    return keys


CFG = None


def _has_key(name):
    if CFG is None:
        return True
    if "Cloudflare" in name or "cloudflare" in name or "CF " in name:
        return bool(CFG.get("CLOUDFLARE_API_KEY"))
    if "Azure" in name or "azure" in name or "azureai" in name:
        return bool(CFG.get("AZUREAI_API_KEY")) and bool(CFG.get("AZUREAI_ENDPOINT"))
    if "Groq" in name or "groq" in name:
        return bool(CFG.get("GROQ_API_KEY"))
    if "HF" in name or "Hugging" in name or "HuggingFace" in name:
        return bool(CFG.get("HF_TOKEN"))
    if "Mistral" in name or "mistral" in name:
        return bool(CFG.get("MISTRAL_API_KEY"))
    if "Fireworks" in name or "fireworks" in name:
        return bool(CFG.get("FIREWORKS_API_KEY"))
    if "Gemini" in name or "gemini" in name or "Google" in name:
        return bool(CFG.get("GEMINI_API_KEY"))
    if "Zai" in name or "zai" in name or "Z.AI" in name or "ZAI" in name:
        return bool(CFG.get("ZAI_API_KEY"))
    return False


def _print_available_keys():
    key_labels = [
        ("CLOUDFLARE_API_KEY", "Cloudflare"),
        ("AZUREAI_API_KEY", "Azure AI Foundry"),
        ("GROQ_API_KEY", "Groq"),
        ("HF_TOKEN", "HuggingFace"),
        ("MISTRAL_API_KEY", "Mistral AI"),
        ("FIREWORKS_API_KEY", "Fireworks AI"),
        ("ZAI_API_KEY", "Zhipu AI"),
        ("GEMINI_API_KEY", "Google Gemini"),
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
MAX_IMAGE_DIM = 2048


def resize_image(path, max_dim=None):
    if max_dim is None:
        max_dim = MAX_IMAGE_DIM
    try:
        from PIL import Image
        img = Image.open(path)
        img.load()
        w, h = img.size
        if w > max_dim or h > max_dim:
            if w > h:
                nw, nh = max_dim, int(h * max_dim / w)
            else:
                nw, nh = int(w * max_dim / h), max_dim
            img = img.resize((nw, nh), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=75)
        result = buf.getvalue()
        if len(result) > 3_000_000:
            quality = 65
            while len(result) > 3_000_000 and quality >= 15:
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=quality)
                result = buf.getvalue()
                quality -= 10
        return result, "image/jpeg"
    except Exception:
        with open(path, "rb") as f:
            return f.read(), get_mime(path)


# ── Video keyframe extraction ────────────────────────────────────────────
def extract_video_frames(path, max_frames=8):
    ext = os.path.splitext(path)[1].lower()
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
    parts = [{"text": prompt}]
    for data, mime in frames:
        parts.append({"inline_data": {"mime_type": mime, "data": b64(data)}})
    return parts


# ── Backend callers ──────────────────────────────────────────────────────

# ── Cloudflare Workers AI caller (OpenAI-compatible) ────────────
CLOUDFLARE_ACCOUNT_ID = "c782ccfebd6eb876a9ef860d61588da7"
CLOUDFLARE_ENDPOINT = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/v1/chat/completions"


def _cloudflare_headers():
    return {
        "Authorization": f"Bearer {CFG['CLOUDFLARE_API_KEY']}",
        "Content-Type": "application/json",
    }


def _cloudflare_extract(response):
    msg = response["choices"][0]["message"]
    content = msg.get("content")
    if content:
        return content
    reasoning = msg.get("reasoning") or msg.get("reasoning_content")
    if reasoning:
        return reasoning
    return str(msg)


def call_cloudflare(b64data, mime, prompt, model):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64data}"}},
        ]}],
        "max_tokens": 2048,
    }
    req = urllib.request.Request(
        CLOUDFLARE_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers=_cloudflare_headers(),
    )
    resp = urllib.request.urlopen(req, timeout=30)
    return _cloudflare_extract(json.loads(resp.read()))


def call_cloudflare_multi(frames, prompt, model):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": build_multimodal_content(frames, prompt)}],
        "max_tokens": 2048,
    }
    req = urllib.request.Request(
        CLOUDFLARE_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers=_cloudflare_headers(),
    )
    resp = urllib.request.urlopen(req, timeout=30)
    return _cloudflare_extract(json.loads(resp.read()))


# ── Azure AI Foundry caller (OpenAI-compatible) ────────────────────
AZUREAI_DEFAULT_DEPLOYMENT = "Phi-4-multimodal-instruct"
AZUREAI_API_VERSION = "2024-10-21"
AZUREAI_API_VERSION_NEW = "2025-04-01-preview"

# GPT-5.x models don't support max_tokens parameter
_AZUREAI_NO_MAX_TOKENS = {"gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.1"}
# o4-mini needs newer API version
_AZUREAI_NEW_API_VERSION = {"o4-mini"}


def _azureai_endpoint(model):
    base = (CFG.get("AZUREAI_ENDPOINT") or "").rstrip("/")
    api_ver = AZUREAI_API_VERSION
    if model in _AZUREAI_NEW_API_VERSION:
        api_ver = AZUREAI_API_VERSION_NEW
    if "/openai/deployments/" in base:
        return f"{base}/chat/completions?api-version={api_ver}"
    return f"{base}/openai/deployments/{model}/chat/completions?api-version={api_ver}"


def _azureai_headers():
    return {
        "api-key": CFG["AZUREAI_API_KEY"],
        "Content-Type": "application/json",
    }


def call_azureai(b64data, mime, prompt, model):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64data}"}},
        ]}],
    }
    if model not in _AZUREAI_NO_MAX_TOKENS:
        payload["max_tokens"] = 2048
    req = urllib.request.Request(
        _azureai_endpoint(model),
        data=json.dumps(payload).encode(),
        headers=_azureai_headers(),
    )
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())["choices"][0]["message"]["content"]


def call_azureai_multi(frames, prompt, model):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": build_multimodal_content(frames, prompt)}],
    }
    if model not in _AZUREAI_NO_MAX_TOKENS:
        payload["max_tokens"] = 2048
    req = urllib.request.Request(
        _azureai_endpoint(model),
        data=json.dumps(payload).encode(),
        headers=_azureai_headers(),
    )
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())["choices"][0]["message"]["content"]


# ── Groq caller (OpenAI-compatible) ──────────────────────────────────
GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"


def _groq_headers():
    return {
        "Authorization": f"Bearer {CFG['GROQ_API_KEY']}",
        "Content-Type": "application/json",
        "User-Agent": "vision-tool/1.0",
    }


def call_groq(b64data, mime, prompt, model="meta-llama/llama-4-scout-17b-16e-instruct"):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64data}"}},
        ]}],
    }
    req = urllib.request.Request(
        GROQ_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers=_groq_headers(),
    )
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read())["choices"][0]["message"]["content"]


def call_groq_multi(frames, prompt, model="meta-llama/llama-4-scout-17b-16e-instruct"):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": build_multimodal_content(frames, prompt)}],
    }
    req = urllib.request.Request(
        GROQ_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers=_groq_headers(),
    )
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read())["choices"][0]["message"]["content"]


# ── Hugging Face Inference Providers caller ───────────────────────────
HF_ROUTER_ENDPOINT = "https://router.huggingface.co/v1/chat/completions"


def _hf_headers():
    return {
        "Authorization": f"Bearer {CFG['HF_TOKEN']}",
        "Content-Type": "application/json",
    }


def _hf_default_model():
    return "Qwen/Qwen3-VL-8B-Instruct"


def call_hf_inference(b64data, mime, prompt, model=None):
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


# ── Mistral AI caller (OpenAI-compatible) ───────────────────────────
MISTRAL_ENDPOINT = "https://api.mistral.ai/v1/chat/completions"


def _mistral_headers():
    return {
        "Authorization": f"Bearer {CFG['MISTRAL_API_KEY']}",
        "Content-Type": "application/json",
    }


def call_mistral(b64data, mime, prompt, model="pixtral-large-latest"):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64data}"}},
        ]}],
    }
    req = urllib.request.Request(
        MISTRAL_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers=_mistral_headers(),
    )
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())["choices"][0]["message"]["content"]


def call_mistral_multi(frames, prompt, model="pixtral-large-latest"):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": build_multimodal_content(frames, prompt)}],
    }
    req = urllib.request.Request(
        MISTRAL_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers=_mistral_headers(),
    )
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())["choices"][0]["message"]["content"]


# ── Fireworks AI caller (OpenAI-compatible) ─────────────────────────
FIREWORKS_ENDPOINT = "https://api.fireworks.ai/inference/v1/chat/completions"


def _fireworks_headers():
    return {
        "Authorization": f"Bearer {CFG['FIREWORKS_API_KEY']}",
        "Content-Type": "application/json",
    }


def call_fireworks(b64data, mime, prompt, model="accounts/fireworks/models/llama-v3p2-90b-vision-instruct"):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64data}"}},
        ]}],
        "max_tokens": 2048,
    }
    req = urllib.request.Request(
        FIREWORKS_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers=_fireworks_headers(),
    )
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())["choices"][0]["message"]["content"]


def call_fireworks_multi(frames, prompt, model="accounts/fireworks/models/llama-v3p2-90b-vision-instruct"):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": build_multimodal_content(frames, prompt)}],
        "max_tokens": 2048,
    }
    req = urllib.request.Request(
        FIREWORKS_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers=_fireworks_headers(),
    )
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())["choices"][0]["message"]["content"]


# ── Google Gemini caller ────────────────────────────────────────────
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def _gemini_url(model, action="generateContent"):
    return f"{GEMINI_BASE}/{model}:{action}?key={CFG['GEMINI_API_KEY']}"


def call_gemini(b64data, mime, prompt, model="gemini-2.5-flash"):
    payload = {
        "contents": [{"parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": mime, "data": b64data}},
        ]}],
    }
    req = urllib.request.Request(
        _gemini_url(model),
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=30)
    d = json.loads(resp.read())
    return d["candidates"][0]["content"]["parts"][0]["text"]


def call_gemini_multi(frames, prompt, model="gemini-2.5-flash"):
    parts = [{"text": prompt}]
    for frame in frames:
        if isinstance(frame, dict):
            parts.append({"inline_data": {"mime_type": frame.get("mime_type", "image/jpeg"), "data": frame["data"]}})
        elif isinstance(frame, tuple):
            data, mime = frame
            b64data = b64(data) if isinstance(data, bytes) else data
            parts.append({"inline_data": {"mime_type": mime, "data": b64data}})
        else:
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": frame}})
    payload = {"contents": [{"parts": parts}]}
    req = urllib.request.Request(
        _gemini_url(model),
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=30)
    d = json.loads(resp.read())
    return d["candidates"][0]["content"]["parts"][0]["text"]


# ── ZAI (Zhipu AI) caller (OpenAI-compatible) ──────────────────────
ZAI_ENDPOINT = "https://api.z.ai/api/paas/v4/chat/completions"


def _zai_headers():
    return {
        "Authorization": f"Bearer {CFG['ZAI_API_KEY']}",
        "Content-Type": "application/json",
    }


def call_zai(b64data, mime, prompt, model="glm-4.5-flash"):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64data}"}},
        ]}],
        "max_tokens": 2048,
    }
    req = urllib.request.Request(
        ZAI_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers=_zai_headers(),
    )
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())["choices"][0]["message"]["content"]


def call_zai_multi(frames, prompt, model="glm-4.5-flash"):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": build_multimodal_content(frames, prompt)}],
        "max_tokens": 2048,
    }
    req = urllib.request.Request(
        ZAI_ENDPOINT,
        data=json.dumps(payload).encode(),
        headers=_zai_headers(),
    )
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())["choices"][0]["message"]["content"]


# ── Provider routing ───────────────────────────────────────────────────

def get_providers_for_model(model):
    ml = model.lower()
    if "/" in model:
        prefix = model.split("/", 1)[0].lower()
        stripped = model.split("/", 1)[1]
        if prefix in ("cloudflare", "cf", "@cf"):
            return _filter_providers([("cloudflare", model)])
        if prefix in ("azure", "azureai"):
            deployment = model.split("/", 1)[1]
            return _filter_providers([("azureai", deployment)])
        if prefix in ("groq",):
            return _filter_providers([("groq", stripped)])
        if prefix == "hf":
            return _filter_providers([("hf", stripped)])
        if prefix == "huggingface":
            return _filter_providers([("hf", stripped)])
        if prefix == "mistral":
            return _filter_providers([("mistral", stripped)])
        if prefix == "zai":
            return _filter_providers([("zai", stripped)])
        if prefix == "fireworks":
            return _filter_providers([("fireworks", stripped)])
    if ml in ("mistral", "pixtral-large-latest", "pixtral"):
        return _filter_providers([("mistral", ml)])
    if ml in ("zai", "glm-4.5-flash", "glm-5", "glm-5.1"):
        return _filter_providers([("zai", ml)])
    return []


def _filter_providers(candidates):
    PROVIDER_KEY_MAP = {
        "cloudflare": "CLOUDFLARE_API_KEY",
        "azureai": "AZUREAI_API_KEY",
        "groq": "GROQ_API_KEY",
        "hf": "HF_TOKEN",
        "mistral": "MISTRAL_API_KEY",
        "fireworks": "FIREWORKS_API_KEY",
        "zai": "ZAI_API_KEY",
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

def _call_with_timeout(fn, timeout_sec=12):
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(fn)
    try:
        return fut.result(timeout=timeout_sec)
    except concurrent.futures.TimeoutError:
        raise TimeoutError(f"Backend timed out after {timeout_sec}s")
    finally:
        pool.shutdown(wait=False)


# ── Strategy builder ──────────────────────────────────────────────────────

def _build_strategies(kind, *args, prompt=""):
    if kind == "vid":
        frames = args[0]
        s = [
            # Google Gemini — tried first (fastest, most reliable)
            ("\u2606 Gemini 2.5 Flash", lambda: call_gemini_multi(frames, prompt, "gemini-2.5-flash")),
            ("\u2606 Gemini 3 Flash Preview", lambda: call_gemini_multi(frames, prompt, "gemini-3-flash-preview")),
            ("\u2606 Gemini 2.0 Flash", lambda: call_gemini_multi(frames, prompt, "gemini-2.0-flash")),
            ("\u2606 Gemini 2.0 Flash Lite", lambda: call_gemini_multi(frames, prompt, "gemini-2.0-flash-lite")),
            ("\u2606 Gemini 2.5 Pro", lambda: call_gemini_multi(frames, prompt, "gemini-2.5-pro")),
            ("\u2606 Gemini 3 Pro Preview", lambda: call_gemini_multi(frames, prompt, "gemini-3-pro-preview")),
            # Azure AI Foundry
            ("\u2606 Azure DeepSeek-V4-Pro", lambda: call_azureai_multi(frames, prompt, "DeepSeek-V4-Pro")),
            ("\u2606 Azure gpt-4.1", lambda: call_azureai_multi(frames, prompt, "gpt-4.1")),
            ("\u2606 Azure gpt-4.1-mini", lambda: call_azureai_multi(frames, prompt, "gpt-4.1-mini")),
            ("\u2606 Azure gpt-4.1-nano", lambda: call_azureai_multi(frames, prompt, "gpt-4.1-nano")),
            ("\u2606 Azure gpt-4o", lambda: call_azureai_multi(frames, prompt, "gpt-4o")),
            ("\u2606 Azure gpt-4o-mini", lambda: call_azureai_multi(frames, prompt, "gpt-4o-mini")),
            ("\u2606 Azure gpt-5.1", lambda: call_azureai_multi(frames, prompt, "gpt-5.1")),
            ("\u2606 Azure gpt-5.4", lambda: call_azureai_multi(frames, prompt, "gpt-5.4")),
            ("\u2606 Azure gpt-5.4-mini", lambda: call_azureai_multi(frames, prompt, "gpt-5.4-mini")),
            ("\u2606 Azure gpt-5.4-nano", lambda: call_azureai_multi(frames, prompt, "gpt-5.4-nano")),
            ("\u2606 Azure Kimi-K2.6", lambda: call_azureai_multi(frames, prompt, "Kimi-K2.6")),
            ("\u2606 Azure Phi-4 multimodal", lambda: call_azureai_multi(frames, prompt, "Phi-4-multimodal-instruct")),
            # Groq
            ("\u2606 Groq Llama 4 Scout 17B", lambda: call_groq_multi(frames, prompt, "meta-llama/llama-4-scout-17b-16e-instruct")),
            # HuggingFace
            ("\u2606 HF Qwen3-VL-8B", lambda: call_hf_multi(frames, prompt, "Qwen/Qwen3-VL-8B-Instruct")),
            # Mistral AI
            ("\u2606 Mistral pixtral-large", lambda: call_mistral_multi(frames, prompt, "pixtral-large-latest")),
            # Fireworks AI
            ("\u2606 Fireworks Llama 3.2 90B Vision", lambda: call_fireworks_multi(frames, prompt, "accounts/fireworks/models/llama-v3p2-90b-vision-instruct")),
            # Zhipu AI
            ("\u2606 ZAI Glm-4.5-Flash", lambda: call_zai_multi(frames, prompt, "glm-4.5-flash")),
        ]
    else:
        img_b64, mime = args
        s = [
            # Google Gemini — tried first (fastest, most reliable)
            ("\u2606 Gemini 2.5 Flash", lambda: call_gemini(img_b64, mime, prompt, "gemini-2.5-flash")),
            ("\u2606 Gemini 3 Flash Preview", lambda: call_gemini(img_b64, mime, prompt, "gemini-3-flash-preview")),
            ("\u2606 Gemini 2.0 Flash", lambda: call_gemini(img_b64, mime, prompt, "gemini-2.0-flash")),
            ("\u2606 Gemini 2.0 Flash Lite", lambda: call_gemini(img_b64, mime, prompt, "gemini-2.0-flash-lite")),
            ("\u2606 Gemini 2.5 Pro", lambda: call_gemini(img_b64, mime, prompt, "gemini-2.5-pro")),
            ("\u2606 Gemini 3 Pro Preview", lambda: call_gemini(img_b64, mime, prompt, "gemini-3-pro-preview")),
            # Azure AI Foundry
            ("\u2606 Azure DeepSeek-V4-Pro", lambda: call_azureai(img_b64, mime, prompt, "DeepSeek-V4-Pro")),
            ("\u2606 Azure gpt-4.1", lambda: call_azureai(img_b64, mime, prompt, "gpt-4.1")),
            ("\u2606 Azure gpt-4.1-mini", lambda: call_azureai(img_b64, mime, prompt, "gpt-4.1-mini")),
            ("\u2606 Azure gpt-4.1-nano", lambda: call_azureai(img_b64, mime, prompt, "gpt-4.1-nano")),
            ("\u2606 Azure gpt-4o", lambda: call_azureai(img_b64, mime, prompt, "gpt-4o")),
            ("\u2606 Azure gpt-4o-mini", lambda: call_azureai(img_b64, mime, prompt, "gpt-4o-mini")),
            ("\u2606 Azure gpt-5.1", lambda: call_azureai(img_b64, mime, prompt, "gpt-5.1")),
            ("\u2606 Azure gpt-5.4", lambda: call_azureai(img_b64, mime, prompt, "gpt-5.4")),
            ("\u2606 Azure gpt-5.4-mini", lambda: call_azureai(img_b64, mime, prompt, "gpt-5.4-mini")),
            ("\u2606 Azure gpt-5.4-nano", lambda: call_azureai(img_b64, mime, prompt, "gpt-5.4-nano")),
            ("\u2606 Azure Kimi-K2.6", lambda: call_azureai(img_b64, mime, prompt, "Kimi-K2.6")),
            ("\u2606 Azure Phi-4 multimodal", lambda: call_azureai(img_b64, mime, prompt, "Phi-4-multimodal-instruct")),
            # Groq
            ("\u2606 Groq Llama 4 Scout 17B", lambda: call_groq(img_b64, mime, prompt, "meta-llama/llama-4-scout-17b-16e-instruct")),
            # HuggingFace
            ("\u2606 HF Qwen3-VL-8B", lambda: call_hf_inference(img_b64, mime, prompt, "Qwen/Qwen3-VL-8B-Instruct")),
            # Mistral AI
            ("\u2606 Mistral pixtral-large", lambda: call_mistral(img_b64, mime, prompt, "pixtral-large-latest")),
            # Fireworks AI
            ("\u2606 Fireworks Llama 3.2 90B Vision", lambda: call_fireworks(img_b64, mime, prompt, "accounts/fireworks/models/llama-v3p2-90b-vision-instruct")),
            # Zhipu AI
            ("\u2606 ZAI Glm-4.5-Flash", lambda: call_zai(img_b64, mime, prompt, "glm-4.5-flash")),
        ]
    return s


def _insert_model_strategies(strategies, model, kind, *args, prompt=""):
    dispatch = {
        "cloudflare": (call_cloudflare, call_cloudflare_multi),
        "azureai": (call_azureai, call_azureai_multi),
        "groq": (call_groq, call_groq_multi),
        "hf": (call_hf_inference, call_hf_multi),
        "mistral": (call_mistral, call_mistral_multi),
        "fireworks": (call_fireworks, call_fireworks_multi),
        "gemini": (call_gemini, call_gemini_multi),
        "zai": (call_zai, call_zai_multi),
    }
    is_vid = kind == "vid"
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


# ── Public API ──────────────────────────────────────────────────────────

def analyze(file_path, prompt="", model=None):
    if os.path.isdir(file_path):
        raise FileNotFoundError(
            f"Path is a directory, not a file: {file_path}\n"
            f"  Pass the full path to an image or video file."
        )

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

    filename = os.path.basename(file_path)
    vid = is_video(file_path)

    global CFG
    CFG = load_config()
    _print_available_keys()

    model = model or CFG.get("DEFAULT_MODEL", "") or None

    if not prompt:
        if vid:
            prompt = (
                "Describe this video naturally — what's happening, what you see changing "
                "frame to frame. Cover the layout, any visible text or UI elements, "
                "colors, and scene transitions. Be thorough but conversational."
            )
        else:
            prompt = (
                "What do you see in this image? Describe it naturally — cover the main "
                "subject, layout, any visible text, colors, and visual style. "
                "If it's a UI or design screenshot, note key elements, spacing, and how "
                "things are arranged. Be thorough but conversational."
            )

    if vid:
        frames = extract_video_frames(file_path, max_frames=8)
        strategies = _build_strategies("vid", frames, prompt=prompt)
    else:
        data, mime = resize_image(file_path, 1024)
        img_b64 = b64(data)
        strategies = _build_strategies("img", img_b64, mime, prompt=prompt)

    if model:
        _insert_model_strategies(strategies, model, "vid" if vid else "img",
                                 *(frames if vid else (img_b64, mime)), prompt=prompt)

    before = len(strategies)
    strategies = [(n, f) for n, f in strategies if _has_key(n)]
    skipped = before - len(strategies)
    if skipped:
        print(f"KEYS: Skipped {skipped}/{before} backends (missing API key)", file=sys.stderr, flush=True)
    print(f"KEYS: {len(strategies)} backends available", file=sys.stderr, flush=True)

    if not strategies:
        raise RuntimeError("No backends available — configure at least one API key (python setup.py)")

    PER_CALL_TIMEOUT = 12
    TOTAL_TIMEOUT = 25
    FAST_TIMEOUT = 8
    last_error = ""

    for name, fn in strategies[:2]:
        try:
            text = _call_with_timeout(fn, FAST_TIMEOUT)
            if text and text.strip():
                print(f"  {name}: OK", file=sys.stderr, flush=True)
                return f"[{filename}]\n{text}"
        except Exception as e:
            msg = str(e)
            if hasattr(e, "code"):
                msg = f"HTTP {e.code}"
            last_error = msg
            print(f"  {name}: FAILED ({msg})", file=sys.stderr, flush=True)

    remaining = strategies[2:]
    if not remaining:
        raise RuntimeError(f"All vision backends failed. Last error: {last_error}")

    print(f"FALLBACK: {len(remaining)} backends in parallel", file=sys.stderr, flush=True)
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(remaining))
    futs = {pool.submit(lambda f=fn, n=name: (n, _call_with_timeout(f, PER_CALL_TIMEOUT))): name for name, fn in remaining}
    try:
        for fut in concurrent.futures.as_completed(futs, timeout=TOTAL_TIMEOUT):
            name = futs[fut]
            try:
                text = fut.result()[1]
                if text and text.strip():
                    print(f"  {name}: OK", file=sys.stderr, flush=True)
                    return f"[{filename}]\n{text}"
            except Exception as e:
                msg = str(e)
                if hasattr(e, "code"):
                    msg = f"HTTP {e.code}"
                last_error = msg
                print(f"  {name}: FAILED ({msg})", file=sys.stderr, flush=True)
    except concurrent.futures.TimeoutError:
        pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    raise RuntimeError(f"All vision backends failed. Last error: {last_error}")


# ── CLI entry point ─────────────────────────────────────────────────────

def _list_models():
    global CFG
    CFG = load_config()

    models = [
        # Azure AI Foundry
        ("\u2606 Azure DeepSeek-V4-Pro",     "AZUREAI_API_KEY"),
        ("\u2606 Azure gpt-4.1",             "AZUREAI_API_KEY"),
        ("\u2606 Azure gpt-4.1-mini",        "AZUREAI_API_KEY"),
        ("\u2606 Azure gpt-4.1-nano",        "AZUREAI_API_KEY"),
        ("\u2606 Azure gpt-4o",              "AZUREAI_API_KEY"),
        ("\u2606 Azure gpt-4o-mini",         "AZUREAI_API_KEY"),
        ("\u2606 Azure gpt-5.1",             "AZUREAI_API_KEY"),
        ("\u2606 Azure gpt-5.4",             "AZUREAI_API_KEY"),
        ("\u2606 Azure gpt-5.4-mini",        "AZUREAI_API_KEY"),
        ("\u2606 Azure gpt-5.4-nano",        "AZUREAI_API_KEY"),
        ("\u2606 Azure Kimi-K2.6",           "AZUREAI_API_KEY"),
        ("\u2606 Azure Phi-4 multimodal",    "AZUREAI_API_KEY"),
        # Groq
        ("\u2606 Groq Llama 4 Scout 17B",    "GROQ_API_KEY"),
        # HuggingFace
        ("\u2606 HF Qwen3-VL-8B",            "HF_TOKEN"),
        # Mistral AI
        ("\u2606 Mistral pixtral-large",     "MISTRAL_API_KEY"),
        # Fireworks AI
        ("\u2606 Fireworks Llama 3.2 90B Vision", "FIREWORKS_API_KEY"),
        # Zhipu AI
        ("\u2606 ZAI Glm-4.5-Flash",              "ZAI_API_KEY"),
        # Google Gemini
        ("\u2606 Gemini 2.5 Flash",           "GEMINI_API_KEY"),
        ("\u2606 Gemini 3 Flash Preview",     "GEMINI_API_KEY"),
        ("\u2606 Gemini 2.0 Flash",           "GEMINI_API_KEY"),
        ("\u2606 Gemini 2.0 Flash Lite",      "GEMINI_API_KEY"),
        ("\u2606 Gemini 2.5 Pro",             "GEMINI_API_KEY"),
        ("\u2606 Gemini 3 Pro Preview",       "GEMINI_API_KEY"),
    ]

    print(f"{'Vision Backend':<45} {'Status':<12} Key")
    print("-" * 75)
    for name, key in models:
        has = bool(CFG.get(key))
        status = "AVAILABLE" if has else "NO KEY"
        status_sym = "\u2705" if has else "\u274c"
        print(f"  {name:<42} {status_sym} {status:<8} {key}")

    print()
    print("Keys configured:")
    for key in ["GEMINI_API_KEY", "OPENROUTER_API_KEY", "CLOUDFLARE_API_KEY", "AZUREAI_API_KEY", "AZUREAI_ENDPOINT", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "MISTRAL_API_KEY", "GROQ_API_KEY", "HF_TOKEN", "FIREWORKS_API_KEY", "ZAI_API_KEY"]:
        v = CFG.get(key, "")
        val = v[:20] + "..." if v and len(v) > 20 else (v or "(not set)")
        print(f"  {key:<25} {val}")


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Analyse images and videos using AI vision models.",
        epilog="First run?  python setup.py",
    )
    parser.add_argument("file", nargs="?", help="Path to image or video file")
    parser.add_argument("prompt", nargs="*", help="Optional prompt text")
    parser.add_argument("--model", "-m", help="Custom model name (auto-routes to best provider)")
    parser.add_argument("--models", "-l", action="store_true", help="List available vision backends and exit")
    args = parser.parse_args()

    if args.models:
        _list_models()
        return

    if not args.file:
        parser.print_help()
        sys.exit(1)

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
