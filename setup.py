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

# Import shared config path/save from vision_proxy
_vp_config_dir = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "vision-tool")
_vp_script_dir = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_vp_config_dir, "config.json")
CONFIG_PATH_LOCAL = os.path.join(_vp_script_dir, "config.json")

# ── helpers ──────────────────────────────────────────────────────────────


def bold(text):
    return f"\033[1m{text}\033[0m" if sys.stdout.isatty() else text


def green(text):
    return f"\033[92m{text}\033[0m" if sys.stdout.isatty() else text


def yellow(text):
    return f"\033[93m{text}\033[0m" if sys.stdout.isatty() else text


def cyan(text):
    return f"\033[96m{text}\033[0m" if sys.stdout.isatty() else text


def dim(text):
    return f"\033[2m{text}\033[0m" if sys.stdout.isatty() else text


def prompt(label, default="", secret=False, optional=False):
    d = f" [{default}]" if default and not secret else ""
    while True:
        if secret:
            if sys.stdin.isatty():
                try:
                    val = getpass.getpass(f"  {label}{d}: ").strip()
                except Exception:
                    # getpass can fail on some Windows terminals
                    # fall back to input (shows chars but works)
                    val = input(f"  {label}{d}: ").strip()
            else:
                # Non-tty stdin (e.g. piped input)
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
    """Write config atomically to a single path."""
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
    """Save config to persistent AppData path + local fallback."""
    _save_to(CONFIG_PATH, config)
    _save_to(CONFIG_PATH_LOCAL, config)

    # Lock permissions (best-effort) on primary path
    target = CONFIG_PATH
    if os.name == "nt":
        try:
            user = os.environ.get("USERNAME", "")
            r = subprocess.run(
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


def test_gemini(key):
    if not key:
        return False
    try:
        req = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}",
            data=json.dumps({"contents": [{"parts": [{"text": "Say OK"}]}]}).encode(),
            headers={"Content-Type": "application/json"},
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


def test_openai(key):
    if not key:
        return False
    try:
        req = urllib.request.Request(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
        )
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status == 200
    except Exception:
        return False


def test_anthropic(key):
    if not key:
        return False
    try:
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/models",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        )
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status == 200
    except Exception:
        return False


PROVIDER_LABELS = [
    ("GEMINI_API_KEY", "Gemini"),
    ("OPENROUTER_API_KEY", "OpenRouter"),
    ("OPENAI_API_KEY", "OpenAI"),
    ("ANTHROPIC_API_KEY", "Anthropic"),
]


def _find_config():
    """Check local path first (explicit user override), then AppData (persistent)."""
    for p in (CONFIG_PATH_LOCAL, CONFIG_PATH):
        if os.path.isfile(p):
            return p
    return CONFIG_PATH


def show_keys():
    """Show current key status."""
    existing = {}
    cfg_path = _find_config()
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
        print(f"  {label + ' API key':22s} {green('set') if val else yellow('not set')}")
    mdl = existing.get("DEFAULT_MODEL", "")
    print(f"  {'Default model':22s} {cyan(mdl) if mdl else dim('(auto-fallback chain)')}")


# ── key entry flow ────────────────────────────────────────────────────────


def enter_keys():
    """Prompt user for API keys, validate, and save."""
    existing = {}
    cfg_path = _find_config()
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
        "Gemini API key",
        default=existing.get("GEMINI_API_KEY", ""),
        secret=True, optional=True,
    )
    openrouter_key = prompt(
        "OpenRouter API key",
        default=existing.get("OPENROUTER_API_KEY", ""),
        secret=True, optional=True,
    )
    openai_key = prompt(
        "OpenAI API key",
        default=existing.get("OPENAI_API_KEY", ""),
        secret=True, optional=True,
    )
    anthropic_key = prompt(
        "Anthropic API key",
        default=existing.get("ANTHROPIC_API_KEY", ""),
        secret=True, optional=True,
    )

    print()
    print(bold("  Validating..."))
    gemini_ok = test_gemini(gemini_key)
    openrouter_ok = test_openrouter(openrouter_key)
    openai_ok = test_openai(openai_key)
    anthropic_ok = test_anthropic(anthropic_key)

    for name, ok in [("Gemini", gemini_ok), ("OpenRouter", openrouter_ok),
                      ("OpenAI", openai_ok), ("Anthropic", anthropic_ok)]:
        if ok:
            print(f"    {green(f'{name} API key works')}")
        else:
            print(f"    {yellow(f'{name} key not verified (saved but may not work)')}")

    if not any([gemini_ok, openrouter_ok, openai_ok, anthropic_ok]):
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
        "OPENAI_API_KEY": openai_key,
        "ANTHROPIC_API_KEY": anthropic_key,
        "DEFAULT_MODEL": default_model,
    }
    securesave(config)

    # Verify save succeeded (check AppData path)
    verified = False
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                saved = json.load(f)
            saved_keys = [k for k in ("GEMINI_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY") if saved.get(k, "")]
            verified = len(saved_keys) > 0
            if verified:
                print(f"  {green('✔')} Keys verified: {', '.join(saved_keys)}")
        except (json.JSONDecodeError, IOError) as e:
            print(f"  {yellow('⚠')} Save verification failed: {e}")

    print()
    if verified:
        print(green(f"  Saved to {CONFIG_PATH} (persistent — survives reinstalls)"))
        print()
        print(bold("  You are all set!"))
        print()
        print('  Tell your AI: "analyse this image" or "look at this video"')
    else:
        print(yellow(f"  Wrote to {CONFIG_PATH} but verification failed."))
        print(yellow("  Try running: python setup.py --add-key"))
    print()


# ── option selector ────────────────────────────────────────────────────────


def choose_option():
    """Show 2-option selection at start of setup."""
    print()
    print(bold("╔══════════════════════════════════════════════╗"))
    print(bold("║      vision-tool  —  API Key Setup           ║"))
    print(bold("╚══════════════════════════════════════════════╝"))
    print()
    print("vision-tool needs at least one API key to analyse images & videos.")
    print("Keys are stored in config.json (gitignored, locked to you only).")
    print()

    if os.path.isfile(_find_config()):
        show_keys()
        print()

    print(bold("  Select an option:"))
    print()
    print(bold("  1)") + "  Enter API key now")
    print(dim("     Provide any provider key (Gemini, OpenRouter, OpenAI, Anthropic)."))
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
    """Create blank config with placeholders and warn user."""
    existing = {}
    cfg_path = _find_config()
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path) as f:
                data = json.load(f)
            if isinstance(data, dict):
                existing = data
        except (json.JSONDecodeError, IOError):
            pass

    all_provider_keys = ["GEMINI_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]
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
    print("    Gemini:    https://aistudio.google.com/apikey")
    print("    OpenRouter: https://openrouter.ai/keys")
    print("    OpenAI:     https://platform.openai.com/api-keys")
    print("    Anthropic:  https://console.anthropic.com/keys")
    print()


# ── main ─────────────────────────────────────────────────────────────────


def main():
    # Force UTF-8 output (handles Windows cp1252 box-drawing chars)
    if sys.stdout is not None and hasattr(sys.stdout, 'buffer') and sys.stdout.buffer is not None:
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        except (ValueError, TypeError, AttributeError):
            pass

    add_key_mode = "--add-key" in sys.argv

    if add_key_mode:
        print()
        print(bold("╔══════════════════════════════════════════════╗"))
        print(bold("║      vision-tool  —  Add API Key             ║"))
        print(bold("╚══════════════════════════════════════════════╝"))
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
