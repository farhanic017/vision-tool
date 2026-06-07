#!/usr/bin/env python3
#  vision-tool — First-run API key setup
#  Copyright (c) 2026 Farhan Dhrubo  <farhaiee123@gmail.com>
#  License: GPL-3.0  —  https://github.com/farhanic017/vision-tool
#
#  This program is free software. You may NOT remove this notice,
#  re-distribute as your own work, or sell without attribution.
# =============================================================================

"""
setup.py — First-run API key setup for vision-tool.
Copyright (C) 2026 Farhan Dhrubo

Usage:
  python setup.py              # Interactive: choose enter now or add later
  python setup.py --add-key    # Add keys later (skips the choice prompt)
"""

import json
import os
import sys
import io
import re
import urllib.request
import urllib.error
import getpass
import subprocess

_vp_script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _vp_script_dir)
import vision_proxy as _vp
CONFIG_PATH = _vp.CONFIG_PATH
CONFIG_PATH_LOCAL = _vp.CONFIG_PATH_LOCAL

# ── helpers ──────────────────────────────────────────────────────────────


def _is_tty():
    try:
        return sys.stdout.isatty()
    except (OSError, ValueError, RuntimeError):
        return False

def bold(text):
    return f"\033[1m{text}\033[0m" if _is_tty() else text


def green(text):
    return f"\033[92m{text}\033[0m" if _is_tty() else text


def yellow(text):
    return f"\033[93m{text}\033[0m" if _is_tty() else text


def cyan(text):
    return f"\033[96m{text}\033[0m" if _is_tty() else text


def dim(text):
    return f"\033[2m{text}\033[0m" if _is_tty() else text


def prompt(label, default="", secret=False, optional=False):
    d = f" [{default}]" if default and not secret else ""
    while True:
        if secret:
            if sys.stdin.isatty():
                try:
                    val = getpass.getpass(f"  {label}{d}: ").strip()
                except Exception:
                    val = input(f"  {label}{d}: ").strip()
            else:
                try:
                    val = input(f"  {label}{d}: ").strip()
                except EOFError:
                    val = ""
        else:
            try:
                val = input(f"  {label}{d}: ").strip()
            except EOFError:
                val = ""
        if not val:
            val = default
        if val:
            return val
        if optional:
            return ""
        print(yellow("  Please enter a value or press Ctrl+C to quit."))


def confirm(label, default=True):
    options = " [Y/n]" if default else " [y/N]"
    val = input(f"  {label}{options}: ").strip().lower()
    if not val:
        return default
    return val in ("y", "yes")


def _save_to(path, config):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        pass
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w") as f:
            json.dump(config, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        with open(path, "w") as f:
            json.dump(config, f, indent=2)


def securesave(config):
    # Merge missing keys from environment variables (never overwrite explicit values)
    PROVIDER_ENV_KEYS = ["GEMINI_API_KEY", "CLOUDFLARE_API_KEY",
                         "AZUREAI_API_KEY", "AZUREAI_ENDPOINT",
                         "OPENROUTER_API_KEY", "OPENAI_API_KEY",
                         "ANTHROPIC_API_KEY", "MISTRAL_API_KEY", "GROQ_API_KEY",
                         "HF_TOKEN", "FIREWORKS_API_KEY", "ZAI_API_KEY",
                         "TOGETHER_API_KEY", "DEEPINFRA_API_KEY",
                         "COHERE_API_KEY", "XAI_API_KEY", "DEFAULT_MODEL"]
    for k in PROVIDER_ENV_KEYS:
        env_val = os.environ.get(k, "")
        if env_val and not config.get(k):
            config[k] = env_val
    _save_to(CONFIG_PATH, config)
    _save_to(CONFIG_PATH_LOCAL, config)
    target = CONFIG_PATH
    if os.name == "nt":
        try:
            user = os.environ.get("USERNAME", "")
            subprocess.run(
                f'icacls "{target}" /grant "{user}:(F)" /inheritance:e',
                shell=True, capture_output=True, timeout=10,
            )
        except Exception:
            pass
    else:
        try:
            os.chmod(target, 0o600)
        except Exception:
            pass


def test_cloudflare(key):
    if not key:
        return False
    try:
        req = urllib.request.Request(
            "https://api.cloudflare.com/client/v4/accounts/c782ccfebd6eb876a9ef860d61588da7/ai/v1/models/search?per_page=1",
            headers={"Authorization": f"Bearer {key}"},
        )
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status == 200
    except Exception:
        return False


def test_azureai(key, endpoint):
    if not key or not endpoint:
        return False
    try:
        base = endpoint.rstrip("/")
        url = f"{base}/openai/deployments?api-version=2024-10-21"
        req = urllib.request.Request(
            url,
            headers={
                "api-key": key,
                "Content-Type": "application/json",
            },
        )
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status == 200
    except Exception:
        return False


def test_groq(key):
    if not key:
        return False
    try:
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/models",
            headers={
                "Authorization": f"Bearer {key}",
                "User-Agent": "vision-tool/1.0",
            },
        )
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status == 200
    except Exception:
        return False


def test_huggingface(key):
    if not key:
        return False
    try:
        req = urllib.request.Request(
            "https://router.huggingface.co/v1/models",
            headers={"Authorization": f"Bearer {key}"},
        )
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status == 200
    except Exception:
        return False


def test_gemini(key):
    if not key:
        return False
    try:
        req = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models?key=" + key,
        )
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status == 200
    except Exception:
        return False


def test_openrouter(key):
    if not key:
        return False
    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {key}"},
        )
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status == 200
    except Exception:
        return False


TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4DwAAAQEABRjYTgAAAABJRU5ErkJggg=="
)
VISION_MODEL_HINTS = (
    "vision", "vl", "llava", "bakllava", "moondream", "minicpm-v",
    "qwen2-vl", "qwen2.5-vl", "qwen3-vl", "gemma3", "granite-vision",
    "pixtral", "mllama", "llama3.2-vision", "llama-3.2-vision",
)
PROVIDER_CONFIG_KEYS = [
    "GEMINI_API_KEY", "OPENROUTER_API_KEY", "CLOUDFLARE_API_KEY",
    "AZUREAI_API_KEY", "AZUREAI_ENDPOINT", "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY", "MISTRAL_API_KEY", "GROQ_API_KEY",
    "HF_TOKEN", "FIREWORKS_API_KEY", "ZAI_API_KEY",
    "TOGETHER_API_KEY", "DEEPINFRA_API_KEY", "COHERE_API_KEY", "XAI_API_KEY",
]
PROVIDER_KEY_ALIASES = {
    "GEMINI_API_KEY": ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY"),
    "OPENROUTER_API_KEY": ("OPENROUTER_API_KEY", "OPENROUTER_KEY"),
    "CLOUDFLARE_API_KEY": ("CLOUDFLARE_API_KEY", "CF_API_TOKEN", "CLOUDFLARE_TOKEN"),
    "AZUREAI_API_KEY": ("AZUREAI_API_KEY", "AZURE_OPENAI_API_KEY", "AZURE_API_KEY"),
    "AZUREAI_ENDPOINT": ("AZUREAI_ENDPOINT", "AZURE_OPENAI_ENDPOINT", "AZURE_ENDPOINT"),
    "OPENAI_API_KEY": ("OPENAI_API_KEY",),
    "ANTHROPIC_API_KEY": ("ANTHROPIC_API_KEY",),
    "MISTRAL_API_KEY": ("MISTRAL_API_KEY",),
    "GROQ_API_KEY": ("GROQ_API_KEY",),
    "HF_TOKEN": ("HF_TOKEN", "HUGGINGFACE_API_KEY", "HUGGINGFACE_TOKEN"),
    "FIREWORKS_API_KEY": ("FIREWORKS_API_KEY",),
    "ZAI_API_KEY": ("ZAI_API_KEY", "ZHIPUAI_API_KEY", "ZHIPU_API_KEY"),
    "TOGETHER_API_KEY": ("TOGETHER_API_KEY",),
    "DEEPINFRA_API_KEY": ("DEEPINFRA_API_KEY",),
    "COHERE_API_KEY": ("COHERE_API_KEY",),
    "XAI_API_KEY": ("XAI_API_KEY", "GROK_API_KEY"),
}
OPENROUTER_FALLBACK_VISION_MODELS = (
    "google/gemini-2.5-flash",
    "google/gemini-2.0-flash-001",
    "openai/gpt-4o-mini",
    "qwen/qwen2.5-vl-72b-instruct",
    "meta-llama/llama-3.2-11b-vision-instruct",
    "meta-llama/llama-3.2-11b-vision-instruct:free",
)
GEMINI_VISION_MODELS = (
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
)
OPENAI_COMPAT_VISION_MODELS = {
    "OPENAI_API_KEY": ("openai", "https://api.openai.com/v1", "gpt-4o-mini"),
    "TOGETHER_API_KEY": ("together", "https://api.together.xyz/v1", "moonshotai/Kimi-K2.5"),
    "DEEPINFRA_API_KEY": ("deepinfra", "https://api.deepinfra.com/v1/openai", "Qwen/Qwen2.5-VL-72B-Instruct"),
    "XAI_API_KEY": ("xai", "https://api.x.ai/v1", "grok-4.3"),
    "MISTRAL_API_KEY": ("mistral", "https://api.mistral.ai/v1", "pixtral-large-latest"),
    "GROQ_API_KEY": ("groq", "https://api.groq.com/openai/v1", "meta-llama/llama-4-scout-17b-16e-instruct"),
    "HF_TOKEN": ("hf", "https://router.huggingface.co/v1", "Qwen/Qwen3-VL-8B-Instruct"),
    "FIREWORKS_API_KEY": ("fireworks", "https://api.fireworks.ai/inference/v1", "accounts/fireworks/models/llama-v3p2-90b-vision-instruct"),
    "ZAI_API_KEY": ("zai", "https://api.z.ai/api/paas/v4", "glm-4.5-flash"),
}


def _json_request(url, payload=None, timeout=2.0, headers=None):
    data = None if payload is None else json.dumps(payload).encode()
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=data, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _local_http_base(value, default):
    base = (value or default).strip().rstrip("/")
    if "://" not in base:
        base = "http://" + base
    return base


def _looks_like_vision_model(name):
    lower = (name or "").lower()
    return any(hint in lower for hint in VISION_MODEL_HINTS)


def _sort_vision_candidates(names):
    clean = [n for n in names if isinstance(n, str) and n.strip()]
    return sorted(clean, key=lambda n: (not _looks_like_vision_model(n), n.lower()))


def _provider_api_base(env_name, default):
    return _local_http_base(os.environ.get(env_name), default)


def _extract_openai_compatible_text(data):
    if not isinstance(data, dict):
        return ""
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message", {}) if isinstance(choice, dict) else {}
    content = msg.get("content", "")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            elif item:
                parts.append(str(item))
        return " ".join(parts)
    return str(content or "")


def _test_openai_compatible_vision(base_url, key, model, extra_headers=None):
    if not key or not model:
        return False
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "Reply with one short word describing this image."},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{TINY_PNG_B64}"}},
        ]}],
        "max_tokens": 16,
    }
    headers = {"Authorization": f"Bearer {key}"}
    if extra_headers:
        headers.update(extra_headers)
    try:
        data = _json_request(base_url.rstrip("/") + "/chat/completions", payload, timeout=15.0, headers=headers)
        return bool(_extract_openai_compatible_text(data).strip())
    except Exception:
        return False


def _test_gemini_vision_model(key, model):
    if not key or not model:
        return False
    payload = {"contents": [{"parts": [
        {"text": "Reply with one short word describing this image."},
        {"inline_data": {"mime_type": "image/png", "data": TINY_PNG_B64}},
    ]}]}
    base = _provider_api_base("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/models")
    try:
        data = _json_request(f"{base}/{model}:generateContent?key={key}", payload, timeout=15.0)
        cand = (data.get("candidates") or [{}])[0] if isinstance(data, dict) else {}
        parts = cand.get("content", {}).get("parts", []) if isinstance(cand, dict) else []
        text = " ".join(str(p.get("text", "")) for p in parts if isinstance(p, dict))
        return bool(text.strip())
    except Exception:
        return False


def _extract_anthropic_text(data):
    parts = []
    for item in data.get("content", []) if isinstance(data, dict) else []:
        if isinstance(item, dict):
            parts.append(str(item.get("text") or ""))
    return " ".join(parts).strip()


def _test_anthropic_vision_model(key, model):
    if not key or not model:
        return False
    payload = {
        "model": model,
        "max_tokens": 16,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "Reply with one short word describing this image."},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": TINY_PNG_B64}},
        ]}],
    }
    base = _provider_api_base("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1")
    try:
        data = _json_request(
            base + "/messages",
            payload,
            timeout=15.0,
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
            },
        )
        return bool(_extract_anthropic_text(data))
    except Exception:
        return False


def _extract_cohere_text(data):
    if not isinstance(data, dict):
        return ""
    message = data.get("message", {})
    content = message.get("content", []) if isinstance(message, dict) else data.get("content", [])
    if isinstance(content, str):
        return content.strip()
    parts = []
    for item in content or []:
        if isinstance(item, dict):
            parts.append(str(item.get("text") or item.get("content") or ""))
        elif item:
            parts.append(str(item))
    return " ".join(parts).strip()


def _test_cohere_vision_model(key, model):
    if not key or not model:
        return False
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "Reply with one short word describing this image."},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{TINY_PNG_B64}"}},
        ]}],
    }
    base = _provider_api_base("COHERE_BASE_URL", "https://api.cohere.com/v2")
    try:
        data = _json_request(
            base + "/chat",
            payload,
            timeout=15.0,
            headers={"Authorization": f"Bearer {key}"},
        )
        return bool(_extract_cohere_text(data))
    except Exception:
        return False


def _test_ollama_vision_model(model):
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": "Reply with one short word describing this image.",
            "images": [TINY_PNG_B64],
        }],
        "stream": False,
    }
    try:
        data = _json_request(
            _local_http_base(os.environ.get("OLLAMA_HOST"), "http://127.0.0.1:11434") + "/api/chat",
            payload,
            timeout=10.0,
        )
        msg = data.get("message", {}) if isinstance(data, dict) else {}
        text = msg.get("content") or data.get("response", "")
        return bool(str(text).strip())
    except Exception:
        return False


def _test_lmstudio_vision_model(model):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "Reply with one short word describing this image."},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{TINY_PNG_B64}"}},
        ]}],
        "max_tokens": 16,
    }
    try:
        data = _json_request(
            _local_http_base(os.environ.get("LMSTUDIO_BASE_URL"), "http://127.0.0.1:1234/v1") + "/chat/completions",
            payload,
            timeout=10.0,
        )
        choice = data.get("choices", [{}])[0] if isinstance(data, dict) else {}
        text = choice.get("message", {}).get("content", "")
        return bool(str(text).strip())
    except Exception:
        return False


def _detect_ollama_vision_model():
    try:
        data = _json_request(
            _local_http_base(os.environ.get("OLLAMA_HOST"), "http://127.0.0.1:11434") + "/api/tags",
            timeout=2.0,
        )
    except Exception:
        return None
    models = data.get("models", []) if isinstance(data, dict) else []
    names = []
    for model in models:
        if isinstance(model, dict):
            names.append(model.get("name") or model.get("model"))
        elif isinstance(model, str):
            names.append(model)
    for name in _sort_vision_candidates(names):
        if _test_ollama_vision_model(name):
            return {"label": f"Ollama: {name}", "default_model": f"ollama/{name}"}
    return None


def _detect_lmstudio_vision_model():
    base = _local_http_base(os.environ.get("LMSTUDIO_BASE_URL"), "http://127.0.0.1:1234/v1")
    try:
        data = _json_request(base + "/models", timeout=2.0)
    except Exception:
        return None
    models = data.get("data", []) if isinstance(data, dict) else []
    names = []
    for model in models:
        if isinstance(model, dict):
            names.append(model.get("id") or model.get("name"))
        elif isinstance(model, str):
            names.append(model)
    for name in _sort_vision_candidates(names):
        if _test_lmstudio_vision_model(name):
            return {"label": f"LM Studio: {name}", "default_model": f"lmstudio/{name}"}
    return None


def detect_native_vision_model():
    if os.environ.get("VISION_TOOL_SKIP_NATIVE_DETECT"):
        return None
    for detector in (_detect_ollama_vision_model, _detect_lmstudio_vision_model):
        result = detector()
        if result:
            return result
    return None


def _read_existing_config_all_locations():
    existing = {}
    for cfg_path in (CONFIG_PATH_LOCAL, CONFIG_PATH):
        if not os.path.isfile(cfg_path):
            continue
        try:
            with open(cfg_path) as f:
                data = json.load(f)
            if isinstance(data, dict):
                for k, v in data.items():
                    if v and not existing.get(k):
                        existing[k] = v
        except (json.JSONDecodeError, IOError):
                pass
    return existing


def _strip_json_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(^|[^:])//.*$", r"\1", text, flags=re.M)


def _read_jsonish(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None, ""
    try:
        return json.loads(text), text
    except json.JSONDecodeError:
        try:
            return json.loads(_strip_json_comments(text)), text
        except json.JSONDecodeError:
            return None, text


def _candidate_client_config_paths():
    paths = [
        "~/.config/opencode/opencode.jsonc",
        "~/.config/opencode/opencode.json",
        "~/.continue/config.json",
        "~/.vscode/mcp.json",
        "~/.config/VSCode/User/mcp.json",
        "~/.config/VSCodium/User/mcp.json",
        "~/.config/Claude/claude_desktop_config.json",
        "~/.gemini/antigravity/mcp_config.json",
    ]
    if os.name == "nt":
        paths.extend([
            "~/AppData/Roaming/Claude/claude_desktop_config.json",
            "~/AppData/Roaming/Code/User/mcp.json",
            "~/AppData/Roaming/VSCodium/User/mcp.json",
            "~/AppData/Roaming/Antigravity/User/mcp.json",
            "~/AppData/Roaming/Cursor/User/globalStorage/rooveterinaryinc.roo-cline/settings/cline_mcp_settings.json",
        ])
    if sys.platform == "darwin":
        paths.extend([
            "~/Library/Application Support/Claude/claude_desktop_config.json",
            "~/Library/Application Support/Code/User/mcp.json",
        ])
    extra = os.environ.get("VISION_TOOL_CONFIG_SCAN_PATHS", "")
    if extra:
        paths.extend([p for p in re.split(r"[;|]", extra) if p.strip()])
    seen = set()
    result = []
    for raw in paths:
        path = os.path.expandvars(os.path.expanduser(raw.strip()))
        key = os.path.normcase(os.path.abspath(path))
        if key not in seen and os.path.isfile(path):
            seen.add(key)
            result.append(path)
    return result


def _remember_config_value(found, key, value):
    if key in PROVIDER_CONFIG_KEYS and isinstance(value, str) and value.strip() and not found.get(key):
        found[key] = value.strip()


def _canonical_key_from_alias(name):
    upper = str(name or "").upper()
    for canonical, aliases in PROVIDER_KEY_ALIASES.items():
        if upper in aliases:
            return canonical
    return None


def _provider_from_context(context):
    text = context.lower()
    if "openrouter" in text:
        return "OPENROUTER_API_KEY"
    if "gemini" in text or "google" in text:
        return "GEMINI_API_KEY"
    if "mistral" in text:
        return "MISTRAL_API_KEY"
    if "groq" in text:
        return "GROQ_API_KEY"
    if "huggingface" in text or "hugging face" in text:
        return "HF_TOKEN"
    if "fireworks" in text:
        return "FIREWORKS_API_KEY"
    if "anthropic" in text or "claude" in text:
        return "ANTHROPIC_API_KEY"
    if "openai" in text:
        return "OPENAI_API_KEY"
    if "zai" in text or "zhipu" in text:
        return "ZAI_API_KEY"
    if "azure" in text:
        return "AZUREAI_API_KEY"
    if "together" in text:
        return "TOGETHER_API_KEY"
    if "deepinfra" in text:
        return "DEEPINFRA_API_KEY"
    if "cohere" in text:
        return "COHERE_API_KEY"
    if "xai" in text or "grok" in text:
        return "XAI_API_KEY"
    return None


def _scan_config_object(obj, found, context=""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_text = str(key)
            canonical = _canonical_key_from_alias(key_text)
            if canonical and isinstance(value, str):
                _remember_config_value(found, canonical, value)
            if key_text.lower() in ("apikey", "api_key", "key", "token", "auth_token") and isinstance(value, str):
                _remember_config_value(found, _provider_from_context(context), value)
            if key_text.lower() in ("endpoint", "baseurl", "base_url", "apiurl", "api_url") and isinstance(value, str):
                if "azure" in context.lower():
                    _remember_config_value(found, "AZUREAI_ENDPOINT", value)
            _scan_config_object(value, found, context + "." + key_text)
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            _scan_config_object(value, found, f"{context}[{idx}]")


def _scan_config_text(text, found):
    if not text:
        return
    for canonical, aliases in PROVIDER_KEY_ALIASES.items():
        for alias in aliases:
            pattern = rf'["\']?{re.escape(alias)}["\']?\s*[:=]\s*["\']([^"\'\s,}}]+)'
            match = re.search(pattern, text, flags=re.I)
            if match:
                _remember_config_value(found, canonical, match.group(1))
    raw_patterns = {
        "OPENROUTER_API_KEY": r"\bsk-or-[A-Za-z0-9_.-]{12,}",
        "GEMINI_API_KEY": r"\bAIza[A-Za-z0-9_-]{20,}",
        "ANTHROPIC_API_KEY": r"\bsk-ant-[A-Za-z0-9_-]{12,}",
        "GROQ_API_KEY": r"\bgsk_[A-Za-z0-9_-]{12,}",
        "HF_TOKEN": r"\bhf_[A-Za-z0-9]{12,}",
        "FIREWORKS_API_KEY": r"\bfw_[A-Za-z0-9_-]{12,}",
    }
    for canonical, pattern in raw_patterns.items():
        match = re.search(pattern, text)
        if match:
            _remember_config_value(found, canonical, match.group(0))


def collect_existing_provider_config():
    found = _read_existing_config_all_locations()
    for canonical, aliases in PROVIDER_KEY_ALIASES.items():
        for alias in aliases:
            _remember_config_value(found, canonical, os.environ.get(alias, ""))
    for path in _candidate_client_config_paths():
        obj, text = _read_jsonish(path)
        _scan_config_object(obj, found, path)
        _scan_config_text(text, found)
    return found


def save_detected_vision_backend(default_model, provider_config=None):
    existing = _read_existing_config_all_locations()
    config = {k: existing.get(k, "") for k in PROVIDER_CONFIG_KEYS}
    for k, v in (provider_config or {}).items():
        if k in PROVIDER_CONFIG_KEYS and v:
            config[k] = v
    config["DEFAULT_MODEL"] = default_model
    _save_to(CONFIG_PATH, config)
    _save_to(CONFIG_PATH_LOCAL, config)


def save_native_vision_model(default_model):
    save_detected_vision_backend(default_model)


def auto_setup_native_vision():
    print("  Checking for local/native vision models (Ollama, LM Studio)...")
    found = detect_native_vision_model()
    if not found:
        print(yellow("  No working local vision model detected."))
        return False
    save_native_vision_model(found["default_model"])
    print(green(f"  Native vision model detected: {found['label']}"))
    print(green(f"  Saved DEFAULT_MODEL={found['default_model']}"))
    print(green("  API keys are not required for this setup."))
    return True


def _model_metadata_mentions_vision(model):
    if not isinstance(model, dict):
        return False
    metadata = json.dumps(model, default=str).lower()
    return (
        '"image"' in metadata
        or "input_modalities" in metadata and "image" in metadata
        or _looks_like_vision_model(str(model.get("id") or model.get("name") or ""))
    )


def _openrouter_headers(key):
    return {
        "Authorization": f"Bearer {key}",
        "HTTP-Referer": "https://github.com/farhanic017/vision-tool",
        "X-Title": "vision-tool",
    }


def _detect_openrouter_vision_model(config):
    key = config.get("OPENROUTER_API_KEY", "")
    if not key:
        return None
    base = _provider_api_base("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    candidates = []
    try:
        data = _json_request(base + "/models", timeout=8.0, headers=_openrouter_headers(key))
        models = data.get("data", []) if isinstance(data, dict) else []
        for model in models:
            if isinstance(model, dict):
                model_id = model.get("id") or model.get("name")
                if model_id and _model_metadata_mentions_vision(model):
                    candidates.append(model_id)
            elif isinstance(model, str) and _looks_like_vision_model(model):
                candidates.append(model)
    except Exception:
        pass
    for model in OPENROUTER_FALLBACK_VISION_MODELS:
        if model not in candidates:
            candidates.append(model)
    for model in _sort_vision_candidates(candidates):
        if _test_openai_compatible_vision(base, key, model, extra_headers={
            "HTTP-Referer": "https://github.com/farhanic017/vision-tool",
            "X-Title": "vision-tool",
        }):
            return {
                "label": f"OpenRouter: {model}",
                "default_model": f"openrouter/{model}",
                "config": {"OPENROUTER_API_KEY": key},
            }
    return None


def _detect_gemini_cloud_vision_model(config):
    key = config.get("GEMINI_API_KEY", "")
    if not key:
        return None
    for model in GEMINI_VISION_MODELS:
        if _test_gemini_vision_model(key, model):
            return {
                "label": f"Google Gemini: {model}",
                "default_model": f"gemini/{model}",
                "config": {"GEMINI_API_KEY": key},
            }
    return None


def _detect_openai_compatible_cloud_model(config, key_name):
    key = config.get(key_name, "")
    details = OPENAI_COMPAT_VISION_MODELS.get(key_name)
    if not key or not details:
        return None
    prefix, base, model = details
    env_name = f"{prefix.upper().replace('-', '_')}_BASE_URL"
    base = _provider_api_base(env_name, base)
    if _test_openai_compatible_vision(base, key, model):
        labels = {
            "openai": "OpenAI",
            "together": "Together AI",
            "deepinfra": "DeepInfra",
            "xai": "xAI",
            "mistral": "Mistral AI",
            "groq": "Groq",
            "hf": "HuggingFace",
            "fireworks": "Fireworks AI",
            "zai": "Zhipu AI",
        }
        return {
            "label": f"{labels.get(prefix, prefix)}: {model}",
            "default_model": f"{prefix}/{model}",
            "config": {key_name: key},
        }
    return None


def _detect_anthropic_cloud_vision_model(config):
    key = config.get("ANTHROPIC_API_KEY", "")
    model = "claude-sonnet-4-5"
    if _test_anthropic_vision_model(key, model):
        return {
            "label": f"Anthropic: {model}",
            "default_model": f"anthropic/{model}",
            "config": {"ANTHROPIC_API_KEY": key},
        }
    return None


def _detect_cohere_cloud_vision_model(config):
    key = config.get("COHERE_API_KEY", "")
    model = "command-a-vision-07-2025"
    if _test_cohere_vision_model(key, model):
        return {
            "label": f"Cohere: {model}",
            "default_model": f"cohere/{model}",
            "config": {"COHERE_API_KEY": key},
        }
    return None


def _detect_azure_cloud_vision_model(config):
    key = config.get("AZUREAI_API_KEY", "")
    endpoint = config.get("AZUREAI_ENDPOINT", "")
    if not key or not endpoint:
        return None
    model = "Phi-4-multimodal-instruct"
    base = endpoint.rstrip("/")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "Reply with one short word describing this image."},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{TINY_PNG_B64}"}},
        ]}],
        "max_tokens": 16,
    }
    try:
        data = _json_request(
            f"{base}/openai/deployments/{model}/chat/completions?api-version=2024-10-21",
            payload,
            timeout=15.0,
            headers={"api-key": key},
        )
        if _extract_openai_compatible_text(data).strip():
            return {
                "label": f"Azure AI Foundry: {model}",
                "default_model": f"azureai/{model}",
                "config": {"AZUREAI_API_KEY": key, "AZUREAI_ENDPOINT": endpoint},
            }
    except Exception:
        pass
    return None


def detect_existing_cloud_vision_model():
    if os.environ.get("VISION_TOOL_SKIP_NATIVE_DETECT") or os.environ.get("VISION_TOOL_SKIP_CLOUD_DETECT"):
        return None
    config = collect_existing_provider_config()
    detectors = [
        _detect_openrouter_vision_model,
        _detect_gemini_cloud_vision_model,
        lambda cfg: _detect_openai_compatible_cloud_model(cfg, "OPENAI_API_KEY"),
        _detect_anthropic_cloud_vision_model,
        lambda cfg: _detect_openai_compatible_cloud_model(cfg, "TOGETHER_API_KEY"),
        lambda cfg: _detect_openai_compatible_cloud_model(cfg, "DEEPINFRA_API_KEY"),
        _detect_cohere_cloud_vision_model,
        lambda cfg: _detect_openai_compatible_cloud_model(cfg, "XAI_API_KEY"),
        lambda cfg: _detect_openai_compatible_cloud_model(cfg, "MISTRAL_API_KEY"),
        lambda cfg: _detect_openai_compatible_cloud_model(cfg, "GROQ_API_KEY"),
        lambda cfg: _detect_openai_compatible_cloud_model(cfg, "HF_TOKEN"),
        lambda cfg: _detect_openai_compatible_cloud_model(cfg, "FIREWORKS_API_KEY"),
        lambda cfg: _detect_openai_compatible_cloud_model(cfg, "ZAI_API_KEY"),
        _detect_azure_cloud_vision_model,
    ]
    for detector in detectors:
        result = detector(config)
        if result:
            return result
    return None


def auto_setup_cloud_vision():
    print("  Checking existing CLI/MCP/cloud provider config for vision models...")
    found = detect_existing_cloud_vision_model()
    if not found:
        print(yellow("  No working cloud vision model detected from existing config."))
        return False
    save_detected_vision_backend(found["default_model"], found.get("config", {}))
    print(green(f"  Cloud vision model detected: {found['label']}"))
    print(green(f"  Saved DEFAULT_MODEL={found['default_model']}"))
    print(green("  No API prompt is needed; existing provider config was reused."))
    return True


def auto_setup_vision_backend():
    if auto_setup_native_vision():
        return True
    return auto_setup_cloud_vision()


def run_capability_profile(reason="setup"):
    """Run first-install free/paid capability profiling after config is saved."""
    if not _is_tty() and not os.environ.get("VISION_TOOL_FORCE_CAPABILITY_PROFILE"):
        print("  Capability profile will refresh automatically when vision-tool starts.")
        return False
    try:
        print("  Profiling free/paid vision access with tiny image tests...")
        refreshed = _vp.refresh_capability_profile(force=True, reason=reason)
        memory = _vp._load_backend_memory()
        profile = memory.get("capability_profile", {}) if isinstance(memory, dict) else {}
        tier = profile.get("access_tier", "unknown")
        if refreshed:
            print(green(f"  Capability profile updated: {tier}"))
            if tier == "paid_available":
                print(green("  Paid/metered vision access is available."))
            elif tier in ("free_only", "free_or_included_available", "local_only", "local_available"):
                print(yellow("  Only free/included/local vision access was confirmed so far."))
            else:
                print(yellow("  Could not confirm paid access yet; vision-tool will retry in the background."))
            return True
    except Exception as exc:
        print(yellow(f"  Capability profile skipped: {exc}"))
    return False


PROVIDER_LABELS = [
    ("GEMINI_API_KEY", "Google Gemini"),
    ("OPENROUTER_API_KEY", "OpenRouter"),
    ("CLOUDFLARE_API_KEY", "Cloudflare"),
    ("AZUREAI_API_KEY", "Azure AI Foundry"),
    ("AZUREAI_ENDPOINT", "Azure AI Foundry endpoint"),
    ("OPENAI_API_KEY", "OpenAI"),
    ("ANTHROPIC_API_KEY", "Anthropic"),
    ("TOGETHER_API_KEY", "Together AI"),
    ("DEEPINFRA_API_KEY", "DeepInfra"),
    ("COHERE_API_KEY", "Cohere"),
    ("XAI_API_KEY", "xAI"),
    ("MISTRAL_API_KEY", "Mistral AI"),
    ("GROQ_API_KEY", "Groq"),
    ("HF_TOKEN", "HuggingFace"),
    ("FIREWORKS_API_KEY", "Fireworks AI"),
    ("ZAI_API_KEY", "Zhipu AI (Z.AI)"),
]


def _safe_print(*args, **kwargs):
    try:
        print(*args, **kwargs)
    except (OSError, ValueError, RuntimeError):
        pass

def show_keys():
    existing = {}
    cfg_path = _vp._find_config()
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path) as f:
                data = json.load(f)
            if isinstance(data, dict):
                existing = data
        except (json.JSONDecodeError, IOError):
            pass
    for key, label in PROVIDER_LABELS:
        val = existing.get(key, "")
        _safe_print(f"  {label + ' API key':22s} {green('set') if val else yellow('not set')}")
    mdl = existing.get("DEFAULT_MODEL", "")
    _safe_print(f"  {'Default model':22s} {cyan(mdl) if mdl else dim('(auto-fallback chain)')}")


def enter_keys():
    existing = {}
    cfg_path = _vp._find_config()
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path) as f:
                data = json.load(f)
            if isinstance(data, dict):
                existing = data
            print(yellow("  Existing config found — press Enter to keep current values."))
            print()
        except (json.JSONDecodeError, IOError):
            pass

    print("  Enter at least one API key (press Enter to keep existing / skip).")
    print()
    gemini_key = prompt(
        "Gemini API key (from Google AI Studio)",
        default=existing.get("GEMINI_API_KEY", ""),
        secret=True, optional=True,
    )
    openrouter_key = prompt(
        "OpenRouter API key (sk-or-...)",
        default=existing.get("OPENROUTER_API_KEY", ""),
        secret=True, optional=True,
    )
    cloudflare_key = prompt(
        "Cloudflare Workers AI API key (cfut_...)",
        default=existing.get("CLOUDFLARE_API_KEY", ""),
        secret=True, optional=True,
    )
    azureai_endpoint = prompt(
        "Azure AI Foundry endpoint (https://...)",
        default=existing.get("AZUREAI_ENDPOINT", ""),
        secret=False, optional=True,
    )
    azureai_key = prompt(
        "Azure AI Foundry API key",
        default=existing.get("AZUREAI_API_KEY", ""),
        secret=True, optional=True,
    )
    openai_key = prompt(
        "OpenAI API key (sk-...)",
        default=existing.get("OPENAI_API_KEY", ""),
        secret=True, optional=True,
    )
    anthropic_key = prompt(
        "Anthropic API key (sk-ant-...)",
        default=existing.get("ANTHROPIC_API_KEY", ""),
        secret=True, optional=True,
    )
    together_key = prompt(
        "Together AI API key",
        default=existing.get("TOGETHER_API_KEY", ""),
        secret=True, optional=True,
    )
    deepinfra_key = prompt(
        "DeepInfra API key",
        default=existing.get("DEEPINFRA_API_KEY", ""),
        secret=True, optional=True,
    )
    cohere_key = prompt(
        "Cohere API key",
        default=existing.get("COHERE_API_KEY", ""),
        secret=True, optional=True,
    )
    xai_key = prompt(
        "xAI API key",
        default=existing.get("XAI_API_KEY", ""),
        secret=True, optional=True,
    )
    mistral_key = prompt(
        "Mistral AI API key",
        default=existing.get("MISTRAL_API_KEY", ""),
        secret=True, optional=True,
    )
    groq_key = prompt(
        "Groq API key (gsk_...)",
        default=existing.get("GROQ_API_KEY", ""),
        secret=True, optional=True,
    )
    hf_token = prompt(
        "HuggingFace token (hf_...)",
        default=existing.get("HF_TOKEN", ""),
        secret=True, optional=True,
    )
    fireworks_key = prompt(
        "Fireworks AI API key (fw_...)",
        default=existing.get("FIREWORKS_API_KEY", ""),
        secret=True, optional=True,
    )
    zai_key = prompt(
        "Zhipu AI (Z.AI) API key",
        default=existing.get("ZAI_API_KEY", ""),
        secret=True, optional=True,
    )

    print()
    print(bold("  Validating..."))
    gemini_ok = test_gemini(gemini_key) if gemini_key else False
    cloudflare_ok = test_cloudflare(cloudflare_key)
    azureai_ok = test_azureai(azureai_key, azureai_endpoint)
    groq_ok = test_groq(groq_key)
    hf_ok = test_huggingface(hf_token)

    for name, ok in [("Gemini", gemini_ok),
                      ("Cloudflare", cloudflare_ok), ("Azure AI Foundry", azureai_ok),
                      ("Groq", groq_ok), ("HuggingFace", hf_ok)]:
        if ok:
            print(f"    {green(f'{name} API key works')}")
        else:
            print(f"    {yellow(f'{name} key not verified (saved but may not work)')}")

    if not any([gemini_ok, cloudflare_ok, azureai_ok, groq_ok, hf_ok]):
        print()
        print(yellow("  No key was confirmed working. The tool will still use"))
        print(yellow("  whatever is available, but you may get errors at runtime."))

    print()
    default_model = prompt(
        "Default vision model (empty = auto-fallback chain)",
        default=existing.get("DEFAULT_MODEL", ""),
        optional=True,
    )

    config = {
        "GEMINI_API_KEY": gemini_key,
        "OPENROUTER_API_KEY": openrouter_key,
        "CLOUDFLARE_API_KEY": cloudflare_key,
        "AZUREAI_API_KEY": azureai_key,
        "AZUREAI_ENDPOINT": azureai_endpoint,
        "OPENAI_API_KEY": openai_key,
        "ANTHROPIC_API_KEY": anthropic_key,
        "TOGETHER_API_KEY": together_key,
        "DEEPINFRA_API_KEY": deepinfra_key,
        "COHERE_API_KEY": cohere_key,
        "XAI_API_KEY": xai_key,
        "MISTRAL_API_KEY": mistral_key,
        "GROQ_API_KEY": groq_key,
        "HF_TOKEN": hf_token,
        "FIREWORKS_API_KEY": fireworks_key,
        "ZAI_API_KEY": zai_key,
        "DEFAULT_MODEL": default_model,
    }
    securesave(config)

    verified = False
    for verify_path in (CONFIG_PATH, CONFIG_PATH_LOCAL):
        if os.path.isfile(verify_path):
            try:
                with open(verify_path) as f:
                    saved = json.load(f)
                saved_keys = [k for k in PROVIDER_CONFIG_KEYS if saved.get(k, "")]
                if len(saved_keys) > 0:
                    verified = True
                    print(f"  {green('\u2714')} Keys verified: {', '.join(saved_keys)}")
                    break
            except (json.JSONDecodeError, IOError) as e:
                print(f"  {yellow('\u26a0')} Save verification failed for {verify_path}: {e}")

    print()
    if verified:
        print(green(f"  Saved to {CONFIG_PATH} (persistent — survives reinstalls)"))
        run_capability_profile(reason="setup_keys")
        print()
        print(bold("  You are all set!"))
        print()
        print('  Tell your AI: "analyse this image" or "look at this video"')
    else:
        print(yellow(f"  Keys were written but could not be verified."))
        print(yellow("  Try running: python setup.py --add-key"))
    print()


def choose_option():
    print()
    print(bold("\u2554\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2557"))
    print(bold("\u2551      vision-tool  \u2014  API Key Setup           \u2551"))
    print(bold("\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d"))
    print()
    print("vision-tool can use a working local vision model or external API keys.")
    print("Config is stored in config.json (gitignored, locked to you only).")
    print()

    if os.path.isfile(_vp._find_config()):
        show_keys()
        print()

    print(bold("  Select an option:"))
    print()
    print(bold("  1)") + "  Enter API key now")
    print(dim("     Provide any provider key (Gemini, OpenRouter, Cloudflare, Azure, etc)."))
    print(dim("     Validated and saved securely with locked permissions."))
    print()
    print(bold("  2)") + "  Add later")
    print(dim("     Skip key setup. vision-tool won't work until you"))
    print(dim("     add keys later. You will be shown how."))
    print()

    while True:
        choice = input("  Enter your choice (1 or 2): ").strip()
        if choice == "1":
            return "now"
        if choice == "2":
            return "later"
        print(yellow("  Please enter 1 or 2."))


def setup_later():
    existing = _read_existing_config_all_locations()
    all_provider_keys = PROVIDER_CONFIG_KEYS
    has_keys = any(existing.get(k) for k in all_provider_keys)
    if has_keys:
        print(yellow("  Keys already configured — nothing to skip."))
        return

    config = {k: "" for k in all_provider_keys}
    config["DEFAULT_MODEL"] = ""
    _save_to(CONFIG_PATH, config)
    _save_to(CONFIG_PATH_LOCAL, config)
    print()
    print(yellow(bold("  Keys not configured — vision-tool will not work until you add them.")))
    print()
    print("  To add your API keys later, run:")
    print(bold(f"    python {os.path.join(_vp_script_dir, 'setup.py')} --add-key"))
    print()
    print("  Get your free keys at:")
    print("    Gemini:       https://aistudio.google.com/apikey")
    print("    OpenAI:       https://platform.openai.com/api-keys")
    print("    Anthropic:    https://console.anthropic.com/settings/keys")
    print("    Together AI:  https://api.together.ai/settings/api-keys")
    print("    DeepInfra:    https://deepinfra.com/dash/api_keys")
    print("    Cohere:       https://dashboard.cohere.com/api-keys")
    print("    xAI:          https://console.x.ai")
    print("    Cloudflare:   https://dash.cloudflare.com/profile/api-tokens  (Workers AI)")
    print("    Azure AI:     https://ai.azure.com  (AI Foundry portal)")
    print("    Mistral:      https://console.mistral.ai/api-keys")
    print("    Groq:         https://console.groq.com/keys  (free tier)")
    print("    HuggingFace:  https://huggingface.co/settings/tokens")
    print("    Fireworks AI: https://fireworks.ai/api-keys")
    print("    Zhipu AI:     https://z.ai (Z.AI API)")
    print()


def main():
    _vp._wrap_utf8()
    add_key_mode = "--add-key" in sys.argv
    if add_key_mode:
        print()
        print(bold("\u2554\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2557"))
        print(bold("\u2551      vision-tool  \u2014  Add API Key             \u2551"))
        print(bold("\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d"))
        print()
        enter_keys()
        return
    if _is_tty() and auto_setup_vision_backend():
        run_capability_profile(reason="setup_auto_detect")
        return
    choice = choose_option()
    if choice == "now":
        enter_keys()
    else:
        setup_later()


if __name__ == "__main__":
    main()
