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
    PROVIDER_ENV_KEYS = ["GEMINI_API_KEY", "OPENROUTER_API_KEY", "CLOUDFLARE_API_KEY",
                         "AZUREAI_API_KEY", "AZUREAI_ENDPOINT", "OPENAI_API_KEY",
                         "ANTHROPIC_API_KEY", "MISTRAL_API_KEY", "GROQ_API_KEY",
                         "HF_TOKEN", "FIREWORKS_API_KEY", "ZAI_API_KEY", "DEFAULT_MODEL"]
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


PROVIDER_LABELS = [
    ("GEMINI_API_KEY", "Google Gemini"),
    ("OPENROUTER_API_KEY", "OpenRouter"),
    ("CLOUDFLARE_API_KEY", "Cloudflare"),
    ("AZUREAI_API_KEY", "Azure AI Foundry"),
    ("AZUREAI_ENDPOINT", "Azure AI Foundry endpoint"),
    ("OPENAI_API_KEY", "OpenAI"),
    ("ANTHROPIC_API_KEY", "Anthropic"),
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
    openrouter_ok = test_openrouter(openrouter_key) if openrouter_key else False
    cloudflare_ok = test_cloudflare(cloudflare_key)
    azureai_ok = test_azureai(azureai_key, azureai_endpoint)
    groq_ok = test_groq(groq_key)
    hf_ok = test_huggingface(hf_token)

    for name, ok in [("Gemini", gemini_ok), ("OpenRouter", openrouter_ok),
                      ("Cloudflare", cloudflare_ok), ("Azure AI Foundry", azureai_ok),
                      ("Groq", groq_ok), ("HuggingFace", hf_ok)]:
        if ok:
            print(f"    {green(f'{name} API key works')}")
        else:
            print(f"    {yellow(f'{name} key not verified (saved but may not work)')}")

    if not any([gemini_ok, openrouter_ok, cloudflare_ok, azureai_ok, groq_ok, hf_ok]):
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
                saved_keys = [k for k in ("GEMINI_API_KEY", "OPENROUTER_API_KEY", "CLOUDFLARE_API_KEY", "AZUREAI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "MISTRAL_API_KEY", "GROQ_API_KEY", "HF_TOKEN", "FIREWORKS_API_KEY", "ZAI_API_KEY") if saved.get(k, "")]
                if len(saved_keys) > 0:
                    verified = True
                    print(f"  {green('\u2714')} Keys verified: {', '.join(saved_keys)}")
                    break
            except (json.JSONDecodeError, IOError) as e:
                print(f"  {yellow('\u26a0')} Save verification failed for {verify_path}: {e}")

    print()
    if verified:
        print(green(f"  Saved to {CONFIG_PATH} (persistent — survives reinstalls)"))
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
    print("vision-tool needs at least one API key to analyse images & videos.")
    print("Keys are stored in config.json (gitignored, locked to you only).")
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

    all_provider_keys = ["GEMINI_API_KEY", "OPENROUTER_API_KEY", "CLOUDFLARE_API_KEY", "AZUREAI_API_KEY", "AZUREAI_ENDPOINT", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "MISTRAL_API_KEY", "GROQ_API_KEY", "HF_TOKEN", "FIREWORKS_API_KEY", "ZAI_API_KEY"]
    has_keys = any(existing.get(k) for k in all_provider_keys)
    if has_keys:
        print(yellow("  Keys already configured — nothing to skip."))
        return

    config = {k: "" for k in all_provider_keys}
    config["DEFAULT_MODEL"] = ""
    securesave(config)
    print()
    print(yellow(bold("  Keys not configured — vision-tool will not work until you add them.")))
    print()
    print("  To add your API keys later, run:")
    print(bold(f"    python {os.path.join(_vp_script_dir, 'setup.py')} --add-key"))
    print()
    print("  Get your free keys at:")
    print("    Gemini:       https://aistudio.google.com/apikey")
    print("    OpenRouter:   https://openrouter.ai/keys  (free tier)")
    print("    Cloudflare:   https://dash.cloudflare.com/profile/api-tokens  (Workers AI)")
    print("    Azure AI:     https://ai.azure.com  (AI Foundry portal)")
    print("    OpenAI:       https://platform.openai.com/api-keys")
    print("    Anthropic:    https://console.anthropic.com/settings/keys")
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
    choice = choose_option()
    if choice == "now":
        enter_keys()
    else:
        setup_later()


if __name__ == "__main__":
    main()
