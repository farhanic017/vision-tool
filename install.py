#!/usr/bin/env python3
"""
install.py — One-command installer for vision-tool.
Copyright (C) 2026 Farhan Dhrubo

Usage:
  python install.py                          # Interactive install
  python install.py --auto                   # Non-interactive (skip prompts where possible)
  python install.py --repo <url>             # Clone from custom repo URL
  python install.py --target <path>          # Install to custom path

What it does:
  1. Clones the repo (if not already local)
  2. Installs pip dependencies (pillow)
  3. Detects your AI client and auto-configures MCP server
  4. Configures vision-tool as ALWAYS-ON (permanent system instruction,
     not just a triggered skill — the model will never say "I can't view images")
  5. Offers to install invisible watchdog (Windows only)
  6. Prompts to configure API keys (enter now or add later)
"""

import argparse
import json
import os
import io
import shutil
import subprocess
import sys
import urllib.request

REPO_URL = "https://github.com/farhanic017/vision-tool.git"
REPO_NAME = "vision-tool"


# ── helpers ──────────────────────────────────────────────────────────────


def safe(text):
    """Replace Unicode chars that may not encode on cp1252 Windows."""
    return (str(text)
        .replace('\u2714', '[OK]')
        .replace('\u2716', '[X]')
        .replace('\u26a0', '[!]')
        .replace('\u2500', '-')
        .replace('\u2550', '=')
        .replace('\u2554', '+')
        .replace('\u2557', '+')
        .replace('\u2551', '|')
        .replace('\u255a', '+')
        .replace('\u255d', '+')
        .replace('\u2014', '--')
    )


def bold(text):
    if sys.stdout.isatty():
        return f"\033[1m{text}\033[0m"
    return safe(text)


def green(text):
    if sys.stdout.isatty():
        return f"\033[92m{text}\033[0m"
    return safe(text)


def yellow(text):
    if sys.stdout.isatty():
        return f"\033[93m{text}\033[0m"
    return safe(text)


def cyan(text):
    if sys.stdout.isatty():
        return f"\033[96m{text}\033[0m"
    return safe(text)


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
    """Prompt for API keys inline (no subprocess, no new terminal)."""
    import importlib.util
    setup_path = os.path.join(target_dir, "setup.py")
    if os.path.isfile(setup_path):
        print(f"  Running setup wizard...")
        # Import setup.py in-process so it uses the SAME terminal
        # (subprocess would open a new window on Windows)
        spec = importlib.util.spec_from_file_location("_vision_tool_setup", setup_path)
        mod = importlib.util.module_from_spec(spec)
        # Add target_dir to path so setup.py can find its siblings if needed
        sys.path.insert(0, target_dir)
        spec.loader.exec_module(mod)
        sys.path.pop(0)
        mod.enter_keys()
        # Verify save worked
        config_path = os.path.join(target_dir, "config.json")
        if os.path.isfile(config_path):
            try:
                with open(config_path) as f:
                    cfg = json.load(f)
                has_keys = any(cfg.get(k, "") for k in ("GEMINI_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"))
                if has_keys:
                    print(f"  {green('✔')} API keys saved and verified")
                else:
                    print(f"  {yellow('⚠')} Config file exists but no keys found")
            except (json.JSONDecodeError, IOError) as e:
                print(f"  {yellow('⚠')} Could not verify keys: {e}")
        else:
            print(f"  {yellow('⚠')} Config file not found after setup")


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

    # Check VSCode (native MCP support) — also covers VS Studio Code
    if os.name == "nt":
        vscode_path = os.path.expanduser("~/AppData/Roaming/Code/User/mcp.json")
    elif sys.platform == "darwin":
        vscode_path = os.path.expanduser("~/Library/Application Support/Code/User/mcp.json")
    else:
        vscode_path = os.path.expanduser("~/.config/Code/User/mcp.json")
    if os.path.isfile(vscode_path):
        clients.append(("VSCode", vscode_path))
    else:
        # Also check for VSCode portable / other installs
        for alt in [os.path.expanduser("~/.vscode/mcp.json"), os.path.expanduser("~/.config/VSCode/User/mcp.json")]:
            if os.path.isfile(alt):
                clients.append(("VSCode", alt))
                break

    # Check VSCodium (open-source VS Code fork)
    if os.name == "nt":
        vscodium_path = os.path.expanduser("~/AppData/Roaming/VSCodium/User/mcp.json")
    else:
        vscodium_path = os.path.expanduser("~/.config/VSCodium/User/mcp.json")
    if os.path.isfile(vscodium_path):
        clients.append(("VSCodium", vscodium_path))

    # Check Antigravity 2.x (Google AI-first IDE, uses Gemini branding)
    if os.name == "nt":
        anti_path = os.path.expanduser("~\\.gemini\\antigravity\\mcp_config.json")
    else:
        anti_path = os.path.expanduser("~/.gemini/antigravity/mcp_config.json")
    if os.path.isfile(anti_path):
        clients.append(("Antigravity", anti_path))

    # Check Antigravity 1.x (VS Code fork, uses standard VS Code-like paths)
    if os.name == "nt":
        anti1_path = os.path.expanduser("~/AppData/Roaming/Antigravity/User/mcp.json")
    else:
        anti1_path = os.path.expanduser("~/.config/Antigravity/User/mcp.json")
    if os.path.isfile(anti1_path):
        clients.append(("Antigravity 1.x", anti1_path))

    return clients


def step_configure(target_dir, auto=False):
    """Auto-configure MCP server for detected clients."""
    clients = detect_client()
    if not clients:
        print(f"  {yellow('⚠')} No supported AI client config found.")
        print(f"     Manual setup: add to your MCP config:")
        print(f'     {{"mcpServers": {{"vision-tool": {{"command": "{sys.executable}", "args": ["{os.path.join(target_dir, "vision_mcp_server.py")}"]}}}}}}')
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
            elif name in ("VSCode", "VSCodium", "Antigravity 1.x"):
                mcp_key = "servers"
                server_entry = {
                    "type": "stdio",
                    "command": sys.executable,
                    "args": [os.path.join(target_dir, "vision_mcp_server.py")],
                }
            else:
                mcp_key = "mcpServers"
                server_entry = {
                    "command": sys.executable,
                    "args": [os.path.join(target_dir, "vision_mcp_server.py")],
                }

            if mcp_key not in config:
                config[mcp_key] = {}
            config[mcp_key]["vision-tool"] = server_entry

            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
            print(f"  {green('✔')} Added vision-tool to {name}")

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
                # ── Add ALWAYS_ON.md as permanent system instruction ──
                # This is the KEY change: the model gets told in EVERY session
                # to use vision-tool for all images, so it never says "can't view".
                instr_key = "instructions"
                if instr_key not in config:
                    config[instr_key] = []
                always_on_path = os.path.join(target_dir, "ALWAYS_ON.md")
                if always_on_path not in config[instr_key]:
                    config[instr_key].append(always_on_path)
                with open(config_path, "w") as f:
                    json.dump(config, f, indent=2)
                print(f"  {green('✔')} Added ALWAYS_ON.md as permanent system instruction")

                # ── Add SKILL.md as secondary instruction ──
                skill_instr = os.path.join(target_dir, "SKILL.md")
                if skill_instr not in config[instr_key]:
                    config[instr_key].append(skill_instr)
                with open(config_path, "w") as f:
                    json.dump(config, f, indent=2)
                print(f"  {green('✔')} Added SKILL.md to instructions")

                # ── Configure dynamic-skill-loader for always-on ──
                # If the user has dynamic-skill-loader installed, mark
                # vision-tool as always-loaded so it's never filtered by triggers.
                dsl_key = "agent-skills"
                if dsl_key in config:
                    if "alwaysOn" not in config[dsl_key]:
                        config[dsl_key]["alwaysOn"] = {}
                    config[dsl_key]["alwaysOn"]["vision-tool"] = {
                        "name": "vision-tool",
                        "path": target_dir,
                    }
                    with open(config_path, "w") as f:
                        json.dump(config, f, indent=2)
                    print(f"  {green('✔')} Configured vision-tool as always-on for dynamic-skill-loader")

            # ── Always-on for VSCode / VSCodium / Antigravity 1.x ──
            # These tools don't have an "instructions" array like opencode,
            # but the MCP tools themselves are always available.
            # For project-level always-on behavior, the user can add
            # ALWAYS_ON.md as a GitHub copilot instructions file.
            if name in ("VSCode", "VSCodium", "Antigravity 1.x"):
                print(f"  {green(safe('✔'))} vision-tool MCP tools always available in {name}")
                print(f"     ({mcp_key} -> vision-tool with analyze_image/analyze_video)")


def step_watchdog(target_dir, auto=False):
    """Offer to install invisible watchdog (Windows only)."""
    if os.name != "nt":
        return

    print()
    print(cyan("  ── Invisible background watchdog (Windows only) ──"))
    print("  Keeps the vision server running silently while ANY AI tool is active.")
    print("  Monitors all 13 supported tools (opencode, claude, cursor, windsurf,")
    print("  aider, continue, VSCode, VSCodium, Antigravity 1.x/2.x, gh-copilot).")
    print("  Auto-starts with Windows, auto-kills when all tools exit.")

    if auto or confirm("  Install invisible watchdog (add to startup + Task Scheduler)?"):
        vbs_path = os.path.join(target_dir, "vision_watchdog.vbs")
        exe_path = os.path.join(target_dir, "vision_watchdog.exe")
        cs_path = os.path.join(target_dir, "vision_watchdog.cs")
        if os.path.isfile(vbs_path):
            # ── Option A: Try to compile C# EXE (zero-flash) ──
            watchdog_exe = vbs_path
            if os.path.isfile(cs_path):
                try:
                    run(f"csc.exe /target:winexe /out:\"{exe_path}\" \"{cs_path}\"", check=False)
                    if os.path.isfile(exe_path):
                        watchdog_exe = exe_path
                        print(f"  {green('✔')} Compiled zero-flash watchdog (vision_watchdog.exe)")
                except Exception:
                    pass

            # ── Option B: Task Scheduler (works on many Windows systems) ──
            task_name = "vision-tool-watchdog"
            try:
                task_cmd = (f'schtasks /create /tn "{task_name}" '
                           f'/tr "\'{watchdog_exe}\'" '
                           f'/sc onlogon /delay 0000:30 '
                           f'/ru "{os.environ.get("USERNAME", "SYSTEM")}" '
                           f'/f')
                run(task_cmd, check=False)
                print(f"  {green('✔')} Added Task Scheduler task (runs at Windows boot)")
                print(f"     Task name: {task_name}")
            except Exception as e:
                print(f"  {yellow('⚠')} Task Scheduler not available: {e}")

            # ── Option C: Startup folder (more reliable on all systems) ──
            startup_dir = os.path.expanduser("~/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup")
            if os.path.isdir(startup_dir):
                try:
                    ps1_path = os.path.join(target_dir, "_install_startup.ps1")
                    with open(ps1_path, "w") as f:
                        f.write(f"""
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut("{startup_dir}\\vision-tool-watchdog.lnk")
$s.TargetPath = "wscript.exe"
$s.Arguments = "{vbs_path}"
$s.WorkingDirectory = "{target_dir}"
$s.Description = "vision-tool watchdog"
$s.Save()
""".strip())
                    run(f'powershell -ExecutionPolicy Bypass -File "{ps1_path}"', check=False)
                    if os.path.isfile(os.path.join(startup_dir, "vision-tool-watchdog.lnk")):
                        print(f"  {green('✔')} Added to Windows Startup folder")
                    else:
                        print(f"  {yellow('⚠')} Could not create shortcut")
                    os.remove(ps1_path)
                except Exception as e:
                    print(f"  {yellow('⚠')} Startup folder failed: {e}")

            # Show how to run now
            print(f"  Run now: wscript.exe //nologo \"{vbs_path}\"")


# ── main ─────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Install vision-tool")
    parser.add_argument("--auto", action="store_true", help="Non-interactive mode")
    parser.add_argument("--repo", default=REPO_URL, help="Repository URL to clone")
    parser.add_argument("--target", default=None, help="Install target directory")
    args = parser.parse_args()

    # Determine target directory
    if args.target:
        target_dir = args.target
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if os.path.isfile(os.path.join(script_dir, "vision_proxy.py")):
            target_dir = script_dir
        else:
            default_dir = os.path.join(script_dir, "vision-tool")
            if not os.path.isdir(default_dir) or not os.path.isfile(os.path.join(default_dir, "vision_proxy.py")):
                default_dir = os.path.join(os.getcwd(), "vision-tool")
            target_dir = default_dir

    print()
    print(bold("╔══════════════════════════════════════════════╗"))
    print(bold("║      vision-tool  —  Installer                ║"))
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

    # ── 3. AI client config ─────────────────────────────────────
    print(bold("  Step 3: Configure AI client"))
    step_configure(target_dir, auto=args.auto)
    print()

    # ── 4. Watchdog (Windows) ──────────────────────────────────
    step_watchdog(target_dir, auto=args.auto)
    print()

    # ── 5. API keys ─────────────────────────────────────────────
    print(bold("  Step 5: Configure API keys"))
    if args.auto:
        config_path = os.path.join(target_dir, "config.json")
        if not os.path.isfile(config_path):
            print(f"  {yellow('⚠')} --auto mode: skipping setup. Run 'python setup.py' or 'python setup.py --add-key' manually.")
    else:
        step_setup(target_dir)
    print()

    # ── Done ────────────────────────────────────────────────────
    print(green(bold("  ── Installation complete! ──")))
    print()
    print(f"  Installed at: {target_dir}")
    print()
    print("  vision-tool is now ALWAYS-ON — your AI will never say 'I can't view images'.")
    print()
    print("  Manual test:")
    print(f"    {sys.executable} \"{os.path.join(target_dir, 'vision_proxy.py')}\" <image_path>")
    print()
    if not args.auto:
        config_path = os.path.join(target_dir, "config.json")
        if os.path.isfile(config_path):
            try:
                with open(config_path) as f:
                    cfg = json.load(f)
                has_keys = any(v for v in (cfg.get("GEMINI_API_KEY"), cfg.get("OPENROUTER_API_KEY")))
                if not has_keys:
                    print(yellow("  Keys not configured yet. Run when ready:"))
                    print(f"    python \"{os.path.join(target_dir, 'setup.py')}\" --add-key")
                    print()
            except (json.JSONDecodeError, IOError):
                pass


if __name__ == "__main__":
    main()
