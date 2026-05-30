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
  Free:   Gemini 2.5 Flash → Gemini 2.0 Flash → NVIDIA Nemotron Omni →
          Gemma 4 26B → NVIDIA Nemotron VL → OpenRouter free
  Paid:   GPT-4o → GPT-4o-mini → Claude 3.5 Sonnet → Claude 3 Haiku →
          Llama 3.2 90B Vision → Qwen VL 8B

Custom model (auto-routes to best provider):
  --model "gpt-4o"         → tries native OpenAI first, then OpenRouter
  --model "claude-sonnet-4" → tries native Anthropic first, then OpenRouter
  --model "gemini-2.5-flash" → tries native Gemini first, then OpenRouter
  --model "openrouter/free"  → OpenRouter only
  Set VISION_MODEL env var or DEFAULT_MODEL in config.json for persistence.

Supported provider keys (set via setup.py or env vars):
  GEMINI_API_KEY | OPENROUTER_API_KEY | OPENAI_API_KEY | ANTHROPIC_API_KEY

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

# ── Output: force UTF-8 (safe wrap, handles piped/closed streams) ──────
_OLD_STDOUT_WRAPPER = None
_OLD_STDERR_WRAPPER = None
if sys.stdout is not None and hasattr(sys.stdout, 'buffer') and sys.stdout.buffer is not None:
    try:
        _OLD_STDOUT_WRAPPER = sys.stdout
        _BASE_BUF = _OLD_STDOUT_WRAPPER.detach()  # detach so GC won't close buffer
        sys.stdout = io.TextIOWrapper(_BASE_BUF, encoding="utf-8", errors="replace")
    except (ValueError, TypeError, AttributeError):
        pass
if sys.stderr is not None and hasattr(sys.stderr, 'buffer') and sys.stderr.buffer is not None:
    try:
        _OLD_STDERR_WRAPPER = sys.stderr
        _BASE_BUF_ERR = _OLD_STDERR_WRAPPER.detach()
        sys.stderr = io.TextIOWrapper(_BASE_BUF_ERR, encoding="utf-8", errors="replace")
    except (ValueError, TypeError, AttributeError):
        pass

# ── Config loader ────────────────────────────────────────────────────────
# Primary: %APPDATA%/vision-tool/config.json (persists across reinstalls)
# Fallback: script_dir/config.json (legacy, backward compat)
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_APPDATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "vision-tool")
CONFIG_PATH = os.path.join(_APPDATA_DIR, "config.json")
CONFIG_PATH_LOCAL = os.path.join(_SCRIPT_DIR, "config.json")


ALL_PROVIDER_KEYS = ["GEMINI_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]


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
            "    $env:OPENAI_API_KEY='your-key'\n"
            "    $env:ANTHROPIC_API_KEY='your-key'\n"
            "    $env:VISION_MODEL='model-name'    (optional default model)"
        )
    return keys


CFG = None

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
    resp = urllib.request.urlopen(req, timeout=120)
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
    resp = urllib.request.urlopen(req, timeout=120)
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
    resp = urllib.request.urlopen(req, timeout=120)
    result = json.loads(resp.read())
    return result["candidates"][0]["content"]["parts"][0]["text"]


def call_gemini_multi(frames, prompt, model="gemini-2.5-flash"):
    payload = {"contents": [{"parts": build_gemini_parts(frames, prompt)}]}
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={CFG['GEMINI_API_KEY']}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=120)
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
    resp = urllib.request.urlopen(req, timeout=120)
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
    resp = urllib.request.urlopen(req, timeout=120)
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
    resp = urllib.request.urlopen(req, timeout=120)
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
    resp = urllib.request.urlopen(req, timeout=120)
    return json.loads(resp.read())["content"][0]["text"]


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
        raise FileNotFoundError(f"File not found: {file_path}")

    vid = is_video(file_path)

    global CFG
    CFG = load_config()

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
            ("\u2606 Gemini 2.5 Flash", lambda: call_gemini_multi(frames, prompt, "gemini-2.5-flash")),
            ("\u2606 Gemini 2.0 Flash", lambda: call_gemini_multi(frames, prompt, "gemini-2.0-flash")),
            ("\u2606 NVIDIA Nemotron Omni", lambda: call_openrouter_multi(frames, prompt, "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free")),
            ("\u2606 Gemma 4 26B", lambda: call_openrouter_multi(frames, prompt, "google/gemma-4-26b-a4b-it:free")),
            ("\u2606 NVIDIA Nemotron VL", lambda: call_openrouter_multi(frames, prompt, "nvidia/nemotron-nano-12b-v2-vl:free")),
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
            ("\u2606 Gemini 2.5 Flash", lambda: call_gemini(img_b64, mime, prompt, "gemini-2.5-flash")),
            ("\u2606 Gemini 2.0 Flash", lambda: call_gemini(img_b64, mime, prompt, "gemini-2.0-flash")),
            ("\u2606 NVIDIA Nemotron Omni", lambda: call_openrouter(img_b64, mime, prompt, "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free")),
            ("\u2606 NVIDIA Nemotron VL", lambda: call_openrouter(img_b64, mime, prompt, "nvidia/nemotron-nano-12b-v2-vl:free")),
            ("\u2606 Gemma 4 26B", lambda: call_openrouter(img_b64, mime, prompt, "google/gemma-4-26b-a4b-it:free")),
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

    last_error = ""
    for name, fn in strategies:
        try:
            text = fn()
            if text and text.strip():
                return text
        except Exception as e:
            msg = str(e)
            if hasattr(e, "code"):
                msg = f"HTTP {e.code}"
            last_error = msg

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
