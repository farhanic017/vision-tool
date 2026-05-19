#!/usr/bin/env python3
"""
install.py — One-command installer for opencode-vision.
Copyright (C) 2026 Farhan Dhrubo

Usage:
  python install.py                          # Interactive install
  python install.py --auto                   # Non-interactive (skip prompts where possible)
  python install.py --repo <url>             # Clone from custom repo URL
  python install.py --target <path>          # Install to custom path

What it does:
  1. Clones the repo (if not already local)
  2. Installs pip dependencies (pillow)
  3. Runs setup.py to configure API keys
  4. Detects your AI client and auto-configures MCP server
  5. Offers to install invisible watchdog (Windows only)
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request

REPO_URL = "https://github.com/farhanic017/vision-for-opencode.git"
REPO_NAME = "vision-for-opencode"


# ── helpers ──────────────────────────────────────────────────────────────


def bold(text):
    return f"\033[1m{text}\033[0m" if sys.stdout.isatty() else text


def green(text):
    return f"\033[92m{text}\033[0m" if sys.stdout.isatty() else text


def yellow(text):
    return f"\033[93m{text}\033[0m" if sys.stdout.isatty() else text


def cyan(text):
    return f"\033[96m{text}\033[0m" if sys.stdout.isatty() else text


def run(cmd, cwd=None, check=True, capture=False):
    """Run a command and print output."""
    sys.stderr.write(f"  $ {cmd}\n")
    sys.stderr.flush()
    kwargs = {"cwd": cwd, "capture_output": capture, "text": True}
    if capture:
        result = subprocess.run(cmd, shell=True, **kwargs)
        return result.stdout.strip() if result.stdout else ""
    result = subprocess.run(cmd, shell=True, **kwargs)
    if check and result.returncode != 0:
        sys.exit(result.returncode)
    return result


def prompt(label, default=""):
    d = f" [{default}]" if default else ""
    val = input(f"  {label}{d}: ").strip()
    return val if val else default


def confirm(label, default=True):
    options = " [Y/n]" if default else " [y/N]"
    val = input(f"  {label}{options}: ").strip().lower()
    if not val:
        return default
    return val in ("y", "yes")


# ── install steps ────────────────────────────────────────────────────────


def step_clone(target_dir):
    """Clone repo if not already present."""
    if os.path.isdir(target_dir) and os.path.isfile(os.path.join(target_dir, "vision_proxy.py")):
        print(f"  {green('✔')} Already installed at {target_dir}")
        return target_dir

    parent = os.path.dirname(target_dir)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)

    print(f"  Cloning {REPO_URL}...")
    run(f"git clone {REPO_URL} \"{target_dir}\"")
    print(f"  {green('✔')} Cloned to {target_dir}")
    return target_dir


def step_deps(target_dir):
    """Install Python dependencies."""
    print(f"  Installing dependencies (pillow)...")
    run(f"\"{sys.executable}\" -m pip install pillow")
    print(f"  {green('✔')} Dependencies installed")


def step_setup(target_dir):
    """Run setup.py for API keys."""
    setup_path = os.path.join(target_dir, "setup.py")
    if os.path.isfile(setup_path):
        print(f"  Running setup wizard...")
        subprocess.run([sys.executable, setup_path], cwd=target_dir)


def detect_client():
    """Detect which AI client is being used."""
    clients = []
    # Check opencode config
    opencode_paths = [
        os.path.expanduser("~/.config/opencode/opencode.jsonc"),
        os.path.expanduser("~/.config/opencode/opencode.json"),
    ]
    if os.name == "nt":
        opencode_paths = [
            os.path.expanduser("~/.config/opencode/opencode.jsonc"),
            os.path.expanduser("~/.config/opencode/opencode.json"),
        ]

    for p in opencode_paths:
        if os.path.isfile(p):
            clients.append(("opencode", p))
            break

    # Check Claude Desktop
    if os.name == "nt":
        claude_path = os.path.expanduser("~/AppData/Roaming/Claude/claude_desktop_config.json")
    elif sys.platform == "darwin":
        claude_path = os.path.expanduser("~/Library/Application Support/Claude/claude_desktop_config.json")
    else:
        claude_path = os.path.expanduser("~/.config/Claude/claude_desktop_config.json")

    if os.path.isfile(claude_path):
        clients.append(("Claude Desktop", claude_path))

    # Check Continue.dev
    if os.name == "nt":
        continue_path = os.path.expanduser("~/.continue/config.json")
    else:
        continue_path = os.path.expanduser("~/.continue/config.json")
    if os.path.isfile(continue_path):
        clients.append(("Continue.dev", continue_path))

    # Check Cursor
    if os.name == "nt":
        cursor_path = os.path.expanduser("~/AppData/Roaming/Cursor/User/globalStorage/rooveterinaryinc.roo-cline/settings/cline_mcp_settings.json")
    else:
        cursor_path = ""
    if cursor_path and os.path.isfile(cursor_path):
        clients.append(("Cursor", cursor_path))

    return clients


def step_configure(target_dir, auto=False):
    """Auto-configure MCP server for detected clients."""
    clients = detect_client()
    if not clients:
        print(f"  {yellow('⚠')} No supported AI client config found.")
        print(f"     Manual setup: add to your MCP config:")
        print(f'     {{"mcpServers": {{"opencode-vision": {{"command": "{sys.executable}", "args": ["{os.path.join(target_dir, "vision_mcp_server.py")}"]}}}}}}')
        return

    for name, config_path in clients:
        if auto or confirm(f"  Configure {name} at {config_path}?"):
            try:
                with open(config_path, "r") as f:
                    config = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                config = {}

            # Handle different config structures
            if name == "opencode":
                mcp_key = "mcp"
                server_entry = {
                    "type": "local",
                    "command": [sys.executable, os.path.join(target_dir, "vision_mcp_server.py")],
                    "enabled": True,
                }
            else:
                mcp_key = "mcpServers"
                server_entry = {
                    "command": sys.executable,
                    "args": [os.path.join(target_dir, "vision_mcp_server.py")],
                }

            if mcp_key not in config:
                config[mcp_key] = {}
            config[mcp_key]["opencode-vision"] = server_entry

            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
            print(f"  {green('✔')} Added opencode-vision to {name}")

            # Also add as skill for opencode
            if name == "opencode":
                skills_key = "skills"
                if skills_key not in config:
                    config[skills_key] = {"paths": []}
                if "paths" not in config[skills_key]:
                    config[skills_key]["paths"] = []
                if target_dir not in config[skills_key]["paths"]:
                    config[skills_key]["paths"].append(target_dir)
                with open(config_path, "w") as f:
                    json.dump(config, f, indent=2)
                print(f"  {green('✔')} Added as opencode skill")

            if name == "opencode":
                # Also check old/instrutions if they have instructions.md
                instr_key = "instructions"
                if instr_key not in config:
                    config[instr_key] = []
                skill_instr = os.path.join(target_dir, "SKILL.md")
                if skill_instr not in config[instr_key]:
                    config[instr_key].append(skill_instr)


def step_watchdog(target_dir, auto=False):
    """Offer to install invisible watchdog (Windows only)."""
    if os.name != "nt":
        return

    print()
    print(cyan("  ── Invisible background watchdog (Windows only) ──"))
    print("  Keeps the vision server running silently when opencode is active.")
    print("  Auto-starts with Windows, auto-kills when opencode exits.")

    if auto or confirm("  Install invisible watchdog (add to startup)?"):
        vbs_path = os.path.join(target_dir, "vision_watchdog.vbs")
        if os.path.isfile(vbs_path):
            # Add to Windows startup folder
            startup_dir = os.path.expanduser("~/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup")
            if os.path.isdir(startup_dir):
                lnk_path = os.path.join(startup_dir, "opencode-vision.url")
                with open(lnk_path, "w") as f:
                    f.write("[InternetShortcut]\n")
                    f.write(f"URL=file:///{vbs_path.replace(' ', '%20')}\n")
                print(f"  {green('✔')} Added to Windows Startup")
                print(f"     ({lnk_path})")

                # Also show how to start immediately
                print(f"  Run now: wscript.exe //nologo \"{vbs_path}\"")


# ── main ─────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Install opencode-vision")
    parser.add_argument("--auto", action="store_true", help="Non-interactive mode")
    parser.add_argument("--repo", default=REPO_URL, help="Repository URL to clone")
    parser.add_argument("--target", default=None, help="Install target directory")
    args = parser.parse_args()

    # Determine target directory
    if args.target:
        target_dir = args.target
    else:
        default_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vision-for-opencode")
        if not os.path.isdir(default_dir) or not os.path.isfile(os.path.join(default_dir, "vision_proxy.py")):
            default_dir = os.path.join(os.getcwd(), "vision-for-opencode")
        target_dir = default_dir

    print()
    print(bold("╔══════════════════════════════════════════════╗"))
    print(bold("║      opencode-vision  —  Installer           ║"))
    print(bold("╚══════════════════════════════════════════════╝"))
    print()

    # ── 1. Clone ────────────────────────────────────────────────
    print(bold("  Step 1: Get the code"))
    target_dir = step_clone(target_dir)
    print()

    # ── 2. Dependencies ─────────────────────────────────────────
    print(bold("  Step 2: Install dependencies"))
    step_deps(target_dir)
    print()

    # ── 3. API keys ─────────────────────────────────────────────
    print(bold("  Step 3: Configure API keys"))
    if args.auto:
        # Check if config already exists
        config_path = os.path.join(target_dir, "config.json")
        if not os.path.isfile(config_path):
            print(f"  {yellow('⚠')} --auto mode: skipping setup. Run 'python setup.py' manually.")
    else:
        step_setup(target_dir)
    print()

    # ── 4. AI client config ─────────────────────────────────────
    print(bold("  Step 4: Configure AI client"))
    step_configure(target_dir, auto=args.auto)
    print()

    # ── 5. Watchdog (Windows) ──────────────────────────────────
    step_watchdog(target_dir, auto=args.auto)
    print()

    # ── Done ────────────────────────────────────────────────────
    print(green(bold("  ── Installation complete! ──")))
    print()
    print(f"  Installed at: {target_dir}")
    print()
    print("  Quick test:")
    print(f"    {sys.executable} \"{os.path.join(target_dir, 'vision_proxy.py')}\" <image_path>")
    print()
    print("  Tell your AI:  \"analyse this image\" or \"look at this video\"")
    print()


if __name__ == "__main__":
    main()
