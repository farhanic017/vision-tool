# vision-tool

![license GPLv3](https://img.shields.io/badge/license-GPLv3-8A2BE2)
![platform Python 3.8+](https://img.shields.io/badge/platform-Python%203.8%2B-22C55E)
![author Farhan Dhrubo](https://img.shields.io/badge/author-Farhan%20Dhrubo-F97316)
![version v8](https://img.shields.io/badge/version-v8-2563EB)
![tests 591 passed](https://img.shields.io/badge/tests-591%20passed-16A34A)
![MCP server](https://img.shields.io/badge/MCP-server-06B6D4)
![AI agents](https://img.shields.io/badge/AI-agents-22C55E)
![local LLMs](https://img.shields.io/badge/local-LLMs-F59E0B)
![vision models](https://img.shields.io/badge/vision-models-A855F7)

> Created by [Farhan Dhrubo](https://github.com/farhanic017) — [Submit an issue](https://github.com/farhanic017/vision-tool/issues)

**MCP vision server for AI agents, coding assistants, local LLMs, and text-only models.**

vision-tool gives **Claude Desktop, Claude Code, Cursor, OpenCode, VS Code,
Continue.dev, Windsurf, Ollama, LM Studio, llama.cpp, OpenRouter, Gemini,
OpenAI, Anthropic, and local AI agents** the ability to understand screenshots,
diagrams, UI clips, images, and videos.

It works as a **Model Context Protocol (MCP) server**, CLI tool, OpenCode skill,
or Python library. Text-only models and local LLMs can call `analyze_image` or
`analyze_video`, then receive a normal text description they can reason over.

If this saves you from "I can't view images" responses, star the repo so more
AI agent builders can find it.

## Why developers star it

- **Adds vision to text-only agents** - Claude, Cursor, OpenCode, Continue,
  VS Code agents, local LLMs, and terminal coding assistants can inspect images.
- **Works with MCP** - exposes `analyze_image` and `analyze_video` as standard
  MCP tools for any MCP-compatible client.
- **Supports images and videos** - screenshots, diagrams, UI mockups, web pages,
  app flows, screen recordings, MP4 clips, and animated GIFs.
- **Auto-detects working vision backends** - checks local VLMs, cloud keys,
  OpenRouter, Gemini, Ollama, LM Studio, and MCP/CLI configs before asking for
  new API keys.
- **Saves quota with memory** - remembers rate-limit, token-limit, and quota
  failures for 24 hours, then retries them after cooldown.
- **Keeps itself fresh** - refreshes free/paid capability status every 2 days
  in the background when the agent starts.
- **Routes across 23 vision backends** - Gemini first, then provider fallback
  through Azure, Groq, HuggingFace, Mistral, Fireworks, ZAI, and more.

## Popular use cases

- Add an **MCP vision server** to Claude Desktop, Claude Code, Cursor, VS Code,
  OpenCode, Continue.dev, Windsurf, or any MCP-compatible AI coding assistant.
- Give **local LLMs** such as Ollama, LM Studio, and llama.cpp image analysis
  without switching away from local text models.
- Route **OpenRouter vision models**, Gemini vision, OpenAI vision, Anthropic
  Claude vision, and free vision APIs through one fallback chain.
- Convert screenshots, UI mockups, architecture diagrams, and web pages into
  plain text an AI agent can understand.
- Summarize MP4 screen recordings, app demos, UI clips, and videos into
  keyframe-based descriptions for agent reasoning.

## Demo Video

![vision-tool animated demo](docs/demo/vision_tool_how_it_works.gif)

The preview above is embedded directly in the README from `docs/demo/vision_tool_how_it_works.gif`.

## Features

- **Images** — PNG, JPG, WebP, BMP, animated GIF
- **Videos** — MP4, WebM, MOV, AVI, MKV, FLV, WMV, M4V (via ffmpeg keyframe extraction)
- **23 fallback backends** — Gemini first, then Azure, Groq, HF, Mistral, Fireworks, ZAI all in parallel
- **Full parallel fire** — ALL backends run simultaneously, first success wins, rest cancelled
- **Fast — typical analysis in 2-5s**, worst case ~19s (no backends available)
- **Smart file search** — checks direct path → known user dirs → shallow recursive scan
- **Natural language prompts** — default prompts are conversational, not robotic checklists
- **Auto JPEG compression** — progressive quality down to 15 for large images
- **Zero hardcoded secrets** — API keys in `config.json` (gitignored) or env vars
- **Works everywhere** — CLI, MCP server, opencode skill, or direct Python import


## 🔄 Always-on mode

vision-tool is designed to be **always-on** — not a triggered skill that
only activates on certain keywords. Once installed:

1. **`ALWAYS_ON.md`** is added to your AI client's permanent system
   instructions. The model is told in every session: "You MUST use
   vision-tool for ALL images and videos. Never say you can't view images."

2. **The MCP server** (`vision_mcp_server.py`) exposes `analyze_image` and
   `analyze_video` as first-class tools available at all times.

3. **The invisible watchdog** (`vision_watchdog.vbs` / `vision_watchdog.exe`)
   monitors for ALL 13 supported AI tool process names (opencode, Claude,
   Cursor, Windsurf, Aider, Continue, VSCode, VSCodium, Antigravity 1.x/2.x,
   GitHub Copilot CLI, and more) and starts/stops the vision server
   automatically — no manual steps.

4. **The dynamic-skill-loader** integration marks vision-tool as
   `alwaysOn`, so it's never filtered by keyword triggers.

### What this means for users

- Your AI will **never say** "I can't view images" or "please describe
  what you see" — it will just analyze the file.
- No need to remember trigger keywords — just provide the file path.
- Works across all major AI coding assistants.

## Quick start

### Drop-in install (tell your AI)

Just send this URL to your AI assistant:

```
https://github.com/farhanic017/vision-tool
```

Your AI will clone, install deps, set up API keys, and configure everything
automatically as **always-on** — the model will never say "I can't view
images" again. The `SKILL.md` and `ALWAYS_ON.md` files contain the
step-by-step instructions any AI agent reads and follows.

### Manual install

```bash
# 1. Clone
git clone https://github.com/farhanic017/vision-tool.git
cd vision-tool

# 2. Install deps
pip install pillow

# 3. Run setup (choose: enter keys now or add later)
python setup.py

# 4. Analyse anything
python vision_proxy.py screenshot.png
python vision_proxy.py demo.mp4 "Describe the UI flow"
```

### Auto-installer

```bash
# Interactive (asks questions)
python install.py

# Non-interactive (best for automation)
python install.py --auto
```

## Vision backends

Google Gemini models are tried **first** (2 fast attempts at 8s each). All remaining backends fire **simultaneously** (12s per backend) — the first successful response wins, the rest are cancelled. Typical analysis completes in **2-5 seconds**.

| # | Model | Provider | Cost |
|---|-------|----------|------|
| 1 | Gemini 2.5 Flash | Google Gemini | Free tier |
| 2 | Gemini 3 Flash Preview | Google Gemini | Free tier |
| 3 | Gemini 2.0 Flash | Google Gemini | Free tier |
| 4 | Gemini 2.0 Flash Lite | Google Gemini | Free tier |
| 5 | Gemini 2.5 Pro | Google Gemini | Free tier |
| 6 | Gemini 3 Pro Preview | Google Gemini | Free tier |
| 7 | Azure DeepSeek-V4-Pro | Azure AI Foundry | Free (Azure credits) |
| 8 | Azure gpt-4.1 | Azure AI Foundry | Free (Azure credits) |
| 9 | Azure gpt-4.1-mini | Azure AI Foundry | Free (Azure credits) |
| 10 | Azure gpt-4.1-nano | Azure AI Foundry | Free (Azure credits) |
| 11 | Azure gpt-4o | Azure AI Foundry | Free (Azure credits) |
| 12 | Azure gpt-4o-mini | Azure AI Foundry | Free (Azure credits) |
| 13 | Azure gpt-5.1 | Azure AI Foundry | Free (Azure credits) |
| 14 | Azure gpt-5.4 | Azure AI Foundry | Free (Azure credits) |
| 15 | Azure gpt-5.4-mini | Azure AI Foundry | Free (Azure credits) |
| 16 | Azure gpt-5.4-nano | Azure AI Foundry | Free (Azure credits) |
| 17 | Azure Kimi-K2.6 | Azure AI Foundry | Free (Azure credits) |
| 18 | Azure Phi-4 multimodal | Azure AI Foundry | Free (Azure credits) |
| 19 | Groq Llama 4 Scout 17B | Groq | Free |
| 20 | HF Qwen3-VL-8B | HuggingFace Inference Providers | Free tier |
| 21 | Mistral pixtral-large | Mistral AI | Free tier |
| 22 | Fireworks Llama 3.2 90B Vision | Fireworks AI | Free tier |
| 23 | ZAI Glm-4.5-Flash | Zhipu AI (Z.AI) | Free tier |

> First 2 backends tried sequentially (8s timeout each), then rest fire in parallel (12s timeout each) — first success cancels all remaining. Total operation timeout: 25s.
> Only backends with configured API keys are launched. Missing keys are skipped instantly.
> Gemini, Azure, Groq, HuggingFace, and Mistral all offer free tiers.

## Capabilities & Limitations

**Images** — Describes visible content, layout, colors, text, and UI elements. The image is downscaled to **max 1024px**, so tiny details/fine text may blur.

**Videos** — Extracts **up to 8 evenly-spaced keyframes** via ffmpeg, analyzes them for UI flow, actions, scene changes, layout, text.

**What determines quality** — Gemini models are tried first (2 fast sequential attempts, 8s each). All remaining backends fire in parallel (12s each). The first backend to respond wins (typically 2-5s). Gemini 2.5 Pro and Flash give the best balance of speed and quality.

**Caveats:**
- Image capped at 1024px → small UI text/icons may be unreadable
- Video limited to 8 frames → fast transitions get missed
- First successful backend wins — not necessarily the most detailed

**Getting better results** — Speak naturally. The default prompts are conversational, but you can be more specific:

```bash
python vision_proxy.py screenshot.png "What's the main layout here? Describe the colors and buttons."
python vision_proxy.py screenshot.png "Read all the text on this page and describe the UI structure."
```

## Getting API keys

You need at least **one** of these:

| Key | Get it | Powers |
|-----|--------|--------|
| **Gemini API key** ⭐ | https://aistudio.google.com/apikey | Gemini 2.5 Flash / 3 Pro / 2.0 Flash (free tier, tried first) |
| **Azure AI key** | https://ai.azure.com | Azure AI Foundry (12 models, free credits) |
| **Groq API key** | https://console.groq.com/keys | Groq Llama 4 Scout (free tier) |
| **Mistral AI API key** | https://console.mistral.ai/api-keys | Mistral pixtral-large (free tier) |
| **HuggingFace token** | https://huggingface.co/settings/tokens | HF Qwen3-VL (free tier) |
| **Fireworks AI API key** | https://fireworks.ai/api-keys | Fireworks Llama 3.2 90B Vision (free tier) |
| **Zhipu AI (Z.AI) key** | https://z.ai | ZAI Glm-4.5-Flash (free tier) |
| **Cloudflare API key** | https://dash.cloudflare.com/profile/api-tokens | Cloudflare Workers AI (free tier, for --model flag) |
| **OpenRouter API key** | https://openrouter.ai/keys | Multi-model access (free + paid) |

Run `python setup.py` — choose to enter keys now or add later.
Add keys later anytime with: `python setup.py --add-key`

## Integration guides

### 1. CLI (any terminal)

Works with any AI coding assistant that can run shell commands.

```bash
python /path/to/vision_proxy.py image.png
python /path/to/vision_proxy.py video.mp4 "Describe the gameplay"
```

Your AI just needs to call this as a bash/terminal command.

### 2. MCP server (OpenCode, Claude Desktop, Cursor, Windsurf, Continue.dev, VSCode, VSCodium, Antigravity 1.x/2.x)

Add the MCP server to your client's config. This exposes `analyze_image` and
`analyze_video` as first-class MCP tools that any agent can call directly.

#### OpenCode (`opencode.jsonc`)

```jsonc
{
  "mcp": {
    "vision-tool": {
      "type": "local",
      "command": ["python", "path/to/vision_mcp_server.py"],
      "enabled": true
    }
  },
  "instructions": [
    "path/to/ALWAYS_ON.md"   // <-- ensures model never says "can't view"
  ]
}
```

For **always-on behavior**, add `ALWAYS_ON.md` to your `instructions` array.
This injects the mandatory vision-tool usage rules into every session so
the model automatically analyzes any image or video without being asked to.

#### Claude Desktop (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "vision-tool": {
      "command": "python",
      "args": ["path/to/vision_mcp_server.py"]
    }
  }
}
```

#### VSCode (`mcp.json`)

VSCode uses the `"servers"` key (not `"mcpServers"`). Add to your user or workspace `mcp.json`:

```json
{
  "servers": {
    "vision-tool": {
      "type": "stdio",
      "command": "python",
      "args": ["path/to/vision_mcp_server.py"]
    }
  }
}
```

**Locations:**
- User (global): `%APPDATA%\Code\User\mcp.json` (Windows), `~/Library/Application Support/Code/User/mcp.json` (macOS), `~/.config/Code/User/mcp.json` (Linux)
- Workspace: `.vscode/mcp.json` in your project root

Open via Command Palette: `MCP: Open User Configuration` or `MCP: Open Workspace Folder MCP Configuration`.

#### VSCodium (open-source VS Code fork)

VSCodium uses the same `mcp.json` format as VSCode:

```json
{
  "servers": {
    "vision-tool": {
      "type": "stdio",
      "command": "python",
      "args": ["path/to/vision_mcp_server.py"]
    }
  }
}
```

**Config path:** `%APPDATA%\VSCodium\User\mcp.json` (Windows) or `~/.config/VSCodium/User/mcp.json` (macOS/Linux).

#### Antigravity 1.x (VS Code fork)

Antigravity 1.x (the older VS Code fork with full extension support) uses
the same native MCP format as VSCode:

```json
{
  "servers": {
    "vision-tool": {
      "type": "stdio",
      "command": "python",
      "args": ["path/to/vision_mcp_server.py"]
    }
  }
}
```

**Config path:** `%APPDATA%\Antigravity\User\mcp.json` (Windows) or `~/.config/Antigravity/User/mcp.json` (macOS/Linux).

#### Antigravity 2.x (Google AI-first IDE)

Antigravity 2.x uses standard `mcpServers` format. Add to `mcp_config.json`:

```json
{
  "mcpServers": {
    "vision-tool": {
      "command": "python",
      "args": ["path/to/vision_mcp_server.py"]
    }
  }
}
```

**Config path:** `%USERPROFILE%\.gemini\antigravity\mcp_config.json` (Windows) or `~/.gemini/antigravity/mcp_config.json` (macOS/Linux).

Open via Agent Panel → `...` → Manage MCP Servers → View raw config.

#### Cursor

In Cursor's MCP server settings:

```
Name: vision-tool
Type: command
Command: python path/to/vision_mcp_server.py
```

Once added, your AI can call `analyze_image` or `analyze_video` with any
file path — no shell commands needed.

### 3. OpenCode skill (always-on)

Add to your `opencode.jsonc`:

```jsonc
{
  "instructions": [
    "path/to/ALWAYS_ON.md"    // permanent system instruction
  ],
  "skills": {
    "paths": [
      "path/to/vision-tool"
    ]
  }
}
```

The `ALWAYS_ON.md` file tells the model in every session: use vision-tool
for all images, never say you can't view them. This is what makes it
**always-on** rather than trigger-dependent.

For **dynamic-skill-loader** users, vision-tool is also configured as
`alwaysOn` so it loads on every session regardless of trigger keywords.

### 4. Local models (Ollama, LM Studio, llama.cpp)

Local models don't have vision hardware. **This tool is designed for exactly
this case.** The AI runs locally, but calling `vision_proxy.py` sends the
image/video to cloud vision APIs for analysis and returns a text description
that your local model can read.

Works identically with any local model in any MCP client:

```jsonc
{
  "model": "ollama/llama3.2",
  "mcp": {
    "vision-tool": {
      "type": "local",
      "command": ["python", "path/to/vision_mcp_server.py"],
      "enabled": true
    }
  }
}
```

### 5. Invisible background watchdog (Windows)

For a zero-setup experience, the watchdog auto-starts the vision MCP server
whenever **any** supported AI coding tool runs and kills it when all tools
exit — all hidden, no windows, no taskbar icons.

**Monitored tools (13 process names):** opencode.exe, claude.exe, cursor.exe,
windsurf.exe, aider.exe, continue.exe, code.exe (VSCode), vscode.exe,
codium.exe (VSCodium), studio.exe, antigravity.exe (Antigravity 1.x/2.x),
claudecode.exe, ghcopilot.exe (GitHub Copilot CLI)

**How it starts with Windows:**

- **Startup folder** (recommended): A `.lnk` shortcut is added to `shell:startup`
  pointing to `wscript.exe "path\to\vision_watchdog.vbs"` — reliable on all
  Windows systems, no admin needed
- **Task Scheduler** (secondary): The watchdog can run at user login via
  `schtasks /create /tn "vision-tool-watchdog" /tr "..." /sc onlogon /delay 0000:30`
- **Zero-flash EXE**: The C# version (`vision_watchdog.exe`) has no console,
  no window, no taskbar icon — compiled with `csc.exe /target:winexe`

**How it works:**

```
Windows starts
  │
  ▼
vision_watchdog.vbs launches (invisible via wscript.exe)
  │
  ▼
Every 10s polls WMI: "Is any AI coding tool running?"
  │
  ├── Yes → Launch vision_mcp_server.py as hidden process
  │         (writes PID to %TEMP%\vision_watchdog.pid)
  │
  └── No  → Kill child process, delete PID file
```

#### Quick start

```cmd
:: Start the watchdog (double-click)
wscript.exe //nologo "C:\path\to\vision_watchdog.vbs"
```

Add to startup folder (`shell:startup`) so it runs every time you log in:

```powershell
$ws = New-Object -ComObject WScript.Shell
$s = $ws.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\vision-tool-watchdog.lnk")
$s.TargetPath = "wscript.exe"
$s.Arguments = "C:\path\to\vision_watchdog.vbs"
$s.WorkingDirectory = "C:\path\to\vision-tool"
$s.Description = "vision-tool watchdog"
$s.Save()
```

Or create a Task Scheduler task (user login, not system boot):

```cmd
schtasks /create /tn "vision-tool-watchdog" /tr "wscript.exe C:\path\to\vision_watchdog.vbs" /sc onlogon /delay 0000:30 /ru %USERNAME% /f
```

#### Zero-flash option (no wscript icon)

For absolute invisibility (no wscript.exe taskbar icon), compile the C# version:

```cmd
:: Install .NET Framework or dotnet, then:
csc.exe /target:winexe /out:vision_watchdog.exe vision_watchdog.cs

:: Run the compiled EXE instead
vision_watchdog.exe
```

The compiled EXE has zero presence — no console, no window, no icon.

#### Custom command

By default the watchdog launches `vision_mcp_server.py`. You can point it at
any process:

```cmd
wscript.exe //nologo vision_watchdog.vbs "notepad.exe"
wscript.exe //nologo vision_watchdog.vbs "python my_script.py" "my_pid.pid"
```

### 6. Python import (programmatic)

```python
from vision_proxy import analyze

# Analyse an image
description = analyze("screenshot.png")
print(description)

# Analyse a video with custom prompt
description = analyze("demo.mp4", "Describe the UI flow step by step")
print(description)

# Analyse with custom prompt
description = analyze("diagram.jpg", "Extract all visible text and explain the architecture")
print(description)
```

## Model compatibility

The vision tool works with **any AI model** — it doesn't matter if the model
has vision or not. The model never processes the image/video directly; the
vision proxy handles that externally and returns plain text.

| Model / Client | How it connects | Verified |
|----------------|-----------------|----------|
| **OpenCode** (`big-pickle`, `DeepSeek`, etc.) | MCP server or skill | ✅ Yes |
| **Claude Desktop** / **Claude Code** | MCP server | ✅ Yes |
| **Cursor** | MCP server | ✅ Yes |
| **Windsurf** | MCP server | ✅ Yes |
| **Continue.dev** | MCP server | ✅ Yes |
| **VSCode** (native MCP via Copilot Agent) | MCP server (`.vscode/mcp.json` or user `mcp.json`) | ✅ Yes |
| **Antigravity** (Google AI-first IDE) | MCP server (`mcp_config.json`) | ✅ Yes |
| **Hermes** (NousResearch) | MCP server or CLI | ✅ Compatible (standard MCP) |
| **OpenClaw** | MCP server or CLI | ✅ Compatible (standard MCP) |
| **Ollama** (any local model) | MCP server + `"model": "ollama/..."` | ✅ Yes |
| **LM Studio** | MCP server | ✅ Yes |
| **llama.cpp** | MCP server | ✅ Yes |
| **Any terminal** | CLI (`python vision_proxy.py`) | ✅ Yes |

All MCP-compatible tools use the same protocol — if your client supports
MCP, it works.

## How it works

```
User: "What's in this image?"  or  "describe this naturally"
        │
        ▼
  AI model (no vision)
        │
        ▼
  CLI / MCP / Skill
        │
        ▼
  vision_proxy.py analyze()
        │
        ├── Images → resize to 1024px → JPEG @75 quality
        └── Videos → ffmpeg extracts 8 keyframes
        │
        ▼
  Fire ALL configured backends:
    ☆ Gemini models       (first, 2 fast sequential attempts)
    ☆ Azure models        
    ☆ Groq Llama 4 Scout
    ☆ HuggingFace Qwen3-VL
    ☆ Mistral pixtral-large
    ☆ Fireworks Llama 3.2 90B Vision
    ☆ ZAI Glm-4.5-Flash
        │
        ▼
  First success wins → rest cancelled
        │
        ▼
  Returns natural text description
```

## File structure

```
vision-tool/
├── README.md                 # This file
├── SKILL.md                  # opencode skill def. + always-on rules (AI reads to install)
├── ALWAYS_ON.md              # Permanent system instruction: never say "can't view"
├── install.py                # Auto-installer (one command setup)
├── vision_proxy.py           # Core analysis engine (CLI + Python API)
├── vision_mcp_server.py      # MCP server (stdio + HTTP modes)
├── vision_watchdog.vbs       # Invisible background process manager (WMI)
├── vision_watchdog.cs        # C# source for zero-flash compiled EXE
├── setup.py                  # First-run API key wizard (10 providers: Gemini, OpenRouter, Cloudflare, Azure, OpenAI, Anthropic, Mistral, Groq, HF, Vertex AI)
├── config.json.example       # Example config (safe to commit)
├── config.json               # Your actual keys (gitignored)
├── requirements.txt          # pip dependencies
├── .gitignore                # Ignores config.json, __pycache__
├── NOTICE                    # Legal notice
└── LICENSE                   # GPL-3.0
```

## Requirements

- **Python 3.8+**
- **`pillow`** — image resize/resample (`pip install pillow`)
- **`ffmpeg`** — video keyframe extraction ([download](https://ffmpeg.org/download.html))

## Security

- **No API keys in code.** All keys go into `config.json` (in `.gitignore`) or
  environment variables.
- **No telemetry.** This script never phones home. It only talks to the API
  providers you configure.
- **No data storage.** Images/videos are never saved or logged; keyframes are
  written to a temp directory and immediately cleaned up.

## Version

### v8 (Current) - Capability memory, auto-detection, and provider expansion
- Added persistent backend memory for quota, token, rate-limit, and health states.
- Limited models are skipped on later runs, then retried after the 24-hour cooldown.
- Added first-install capability profiling to detect whether working access is local, free/included, paid/metered, quota-limited, or payment/plan-limited.
- Added background capability refresh every 2 days at startup, so new provider/model access is discovered without blocking the agent.
- Added auto-detection for local VLMs, cloud credentials, MCP environment blocks, and CLI/provider setups before asking for API keys.
- Expanded provider routing and detection across local runtimes, OpenRouter, Gemini, OpenAI, Anthropic, Together, DeepInfra, Cohere, xAI, Mistral, Groq, HuggingFace, Fireworks, ZAI, Cloudflare, Azure AI, Ollama, and LM Studio.
- Added `--refresh-profile` for manual capability refresh and JSON profile output.
- Hardened setup/install so non-interactive installs do not hang on prompts.
- Verified with syntax checks, focused capability tests, aggressive tests, and fuzz/stress tests.

### v7 - Local/cloud vision auto-setup
- Installer checks for already-working vision models before asking for API keys.
- Local runtimes such as Ollama and LM Studio are probed with a tiny image test.
- Existing CLI, MCP, and provider credentials can be reused when they pass a real vision request.
- OpenRouter can be scanned for vision-capable models even when the active CLI model is text-only.
- Manual provider additions remain simple config/env updates.

### v6 — Fireworks & Fuzz Hardening
- Added **Fireworks AI** backend (Llama 3.2 90B Vision) — 22 total backends
- Fixed 4 pre-existing **fuzz test failures** (312/312 passing):
  - MCP int path crash — `_resolve_path()` type guard
  - Resource leak false positive — `_INITIAL_TMP_COUNT` baseline
  - `show_keys` crash on closed stdout — `_is_tty()` / `_safe_print()` wrappers
  - Corrupted config crash — same print hardening
- **Gemini-first priority** — swapped backend order so Gemini is always tried first
- **Secure config save** — `securesave()` auto-merges env vars into config.json
- **Bytes JSON serialization fix** — `call_gemini_multi()` tuple frame handling
- `test_*.py` / `list_*.py` / `assets/` added to `.gitignore`

### v5 — Fuzz Testing & Security Hardening
- Added `fuzz_stress_test.py` — 312 tests covering encoding attacks, path traversal, concurrency, memory pressure, corrupted inputs, protocol violations, subprocess failures, environment corruption, type confusion, resource leaks
- Config corruption protection — `load_config()` resilient to all JSON attack formats
- MCP server fuzzing — type confusion, HTTP attacks, tool call attacks
- Stdio wrapping safety — safe `_REAL_STDOUT` preservation across all subprocesses
- GraphQL introspection blocked — `/mcp` endpoint hardened

### v4 — Gemini Backend & Parallel Fire
- Added **Google Gemini** as primary backend (6 models: 2.5 Flash, 3 Flash Preview, 2.0 Flash, 2.0 Flash Lite, 2.5 Pro, 3 Pro Preview)
- Added **OpenRouter** support
- **Parallel fire mode** — first 2 backends sequential (8s), rest simultaneous (12s)
- **Fireworks AI** (planned, fully stubbed)
- `DEFAULT_MODEL` config support
- `requirements.txt` added

### v3 — MCP Server & Always-On Mode
- `vision_mcp_server.py` — stdio + HTTP MCP server
- `ALWAYS_ON.md` — permanent system instruction for never saying "can't view"
- `vision_watchdog.vbs` + `vision_watchdog.cs` — invisible background process manager
- `install.py` — interactive and non-interactive auto-installer
- OpenCode skill integration (`SKILL.md`)
- Dynamic-skill-loader `alwaysOn` support

### v2 — Multi-Provider & Video
- Added **Groq**, **HuggingFace**, **Mistral AI** backends
- **Video support** — ffmpeg keyframe extraction, 8 evenly-spaced frames
- `setup.py` — interactive API key wizard with validation
- `_has_key()` provider detection for runtime backend filtering
- `get_mime()` MIME detection for unknown file types
- `extract_video_frames()` GIF support (no ffmpeg needed)

### v1 — Initial Release
- Basic image analysis via **Cloudflare Workers AI** + **Azure AI Foundry**
- CLI entry point (`vision_proxy.py main()`)
- Pillow-based resize/JPEG compression
- File search across Desktop, Downloads, Pictures, Documents
- `first_success` sequential backend strategy
- `config.json` with gitignored secrets
- `setup.py` initial version with Cloudflare + Azure only

## License

GNU General Public License v3.0 — see [LICENSE](./LICENSE).

This program is free software: you can redistribute and/or modify it under the terms of the GPLv3.
Modified versions must be licensed under GPLv3 with clear attribution to the original author.

© 2026 Farhan Dhrubo.
