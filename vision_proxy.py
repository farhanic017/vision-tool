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

Usage:
  python vision_proxy.py <image_or_video_path> [prompt text...]

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
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config():
    keys = {
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY"),
        "OPENROUTER_API_KEY": os.environ.get("OPENROUTER_API_KEY"),
    }
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                cfg = json.load(f)
        except (json.JSONDecodeError, IOError):
            cfg = None
        if isinstance(cfg, dict):
            for k in keys:
                if not keys[k]:
                    keys[k] = cfg.get(k)
    present = [k for k, v in keys.items() if v]
    if not present:
        raise RuntimeError(
            "No API keys configured.\n"
            "  Run setup.py to configure:  python setup.py\n"
            "  Or set environment variables:\n"
            "    $env:GEMINI_API_KEY='your-key'\n"
            "    $env:OPENROUTER_API_KEY='your-key'"
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
def resize_image(path, max_dim=1024):
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


# ── Public API ──────────────────────────────────────────────────────────

def analyze(file_path, prompt=""):
    """Analyse an image or video file and return the description text.

    Args:
        file_path: Absolute path to image or video file.
        prompt: Optional custom prompt. Auto-generated if empty.

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

    if not prompt:
        prompt = (
            "Describe this video in detail frame by frame — visible text, colours, layout, UI elements, actions, and scene changes. Be specific."
            if vid else
            "Describe this image in detail — visible text, colours, layout, UI elements. Be specific."
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


# ── CLI entry point ─────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(
            "Usage:  python vision_proxy.py <image_or_video_path> [prompt...]\n"
            "First run?  python setup.py\n\n"
            "Examples:\n"
            "  python vision_proxy.py screenshot.png\n"
            "  python vision_proxy.py video.mp4 \"Describe the UI flow\"\n"
            "  python vision_proxy.py diagram.jpg \"Extract all text\""
        )
        sys.exit(1)

    file_path = sys.argv[1]
    prompt = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""

    try:
        result = analyze(file_path, prompt)
        print(result)
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
