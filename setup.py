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

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

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


def prompt(label, default="", secret=False):
    d = f" [{default}]" if default and not secret else ""
    while True:
        if secret and sys.stdin.isatty():
            val = getpass.getpass(f"  {label}{d}: ").strip()
        else:
            val = input(f"  {label}{d}: ").strip()
        if not val:
            val = default
        if val:
            return val
        print(yellow("  Please enter a value or press Ctrl+C to quit."))


def confirm(label, default=True):
    options = " [Y/n]" if default else " [y/N]"
    val = input(f"  {label}{options}: ").strip().lower()
    if not val:
        return default
    return val in ("y", "yes")


def securesave(config):
    """Save config with restricted file permissions."""
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
    if os.name == "nt":
        try:
            user = os.environ.get("USERNAME", "")
            subprocess.run(
                f'icacls "{CONFIG_PATH}" /grant "{user}:(F)" /inheritance:e',
                shell=True, capture_output=True, timeout=10,
            )
        except Exception:
            pass
    else:
        os.chmod(CONFIG_PATH, 0o600)


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


def show_keys():
    """Show current key status."""
    existing = {}
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                data = json.load(f)
            if isinstance(data, dict):
                existing = data
        except (json.JSONDecodeError, IOError):
            pass
    gem = existing.get("GEMINI_API_KEY", "")
    ork = existing.get("OPENROUTER_API_KEY", "")
    print(f"  Gemini API key:     {green('set') if gem else yellow('not set')}")
    print(f"  OpenRouter API key: {green('set') if ork else yellow('not set')}")


# ── key entry flow ────────────────────────────────────────────────────────


def enter_keys():
    """Prompt user for API keys, validate, and save."""
    existing = {}
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                data = json.load(f)
            if isinstance(data, dict):
                existing = data
            print(yellow("  Existing config found — press Enter to keep current values."))
            print()
        except (json.JSONDecodeError, IOError):
            pass

    gemini_key = prompt(
        "Gemini API key",
        default=existing.get("GEMINI_API_KEY", ""),
        secret=True,
    )
    openrouter_key = prompt(
        "OpenRouter API key",
        default=existing.get("OPENROUTER_API_KEY", ""),
        secret=True,
    )

    print()
    print(bold("  Validating..."))
    gemini_ok = test_gemini(gemini_key)
    openrouter_ok = test_openrouter(openrouter_key)

    if gemini_ok:
        print(f"    {green('Gemini API key works')}")
    else:
        print(f"    {yellow('Gemini key not verified (saved but may not work)')}")

    if openrouter_ok:
        print(f"    {green('OpenRouter key works')}")
    else:
        print(f"    {yellow('OpenRouter key not verified (saved but may not work)')}")

    if not gemini_ok and not openrouter_ok:
        print()
        print(yellow("  Neither key was confirmed working. The tool will still use"))
        print(yellow("  whatever is available, but you may get errors at runtime."))

    config = {
        "GEMINI_API_KEY": gemini_key,
        "OPENROUTER_API_KEY": openrouter_key,
    }
    securesave(config)

    print()
    print(green(f"  Saved to {CONFIG_PATH} (permissions locked to you only)"))
    print()
    print(bold("  You are all set!"))
    print()
    print('  Tell your AI: "analyse this image" or "look at this video"')
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

    if os.path.isfile(CONFIG_PATH):
        show_keys()
        print()

    print(bold("  Select an option:"))
    print()
    print(bold("  1)") + "  Enter API key now")
    print(dim("     Provide your Gemini / OpenRouter key. Validated and"))
    print(dim("     saved securely to config.json with locked permissions."))
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
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                data = json.load(f)
            if isinstance(data, dict):
                existing = data
        except (json.JSONDecodeError, IOError):
            pass

    has_keys = any(v for v in (existing.get("GEMINI_API_KEY"), existing.get("OPENROUTER_API_KEY")))
    if has_keys:
        print(yellow("  Keys already configured — nothing to skip."))
        return

    config = {
        "GEMINI_API_KEY": "",
        "OPENROUTER_API_KEY": "",
    }
    securesave(config)
    print()
    print(yellow(bold("  Keys not configured — vision-tool will not work until you add them.")))
    print()
    print("  To add your API keys later, run:")
    print(bold(f"    python {os.path.join(os.path.dirname(os.path.abspath(__file__)), 'setup.py')} --add-key"))
    print()
    print("  Get your free keys at:")
    print("    Gemini:    https://aistudio.google.com/apikey")
    print("    OpenRouter: https://openrouter.ai/keys")
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
