# vision-tool

> Created by [Farhan Dhrubo](https://github.com/farhanic017) — [Submit an issue](https://github.com/farhanic017/vision-tool/issues)

**Image & video analysis for AI coding assistants that don't have eyes.**

vision-tool lets any AI model — including local models, free APIs, or
models without built-in vision (like `big-pickle`, `DeepSeek`) — describe
images and videos by routing them through 12 external vision backends.

## Features

- **Images** — PNG, JPG, WebP, BMP, animated GIF
- **Videos** — MP4, WebM, MOV, AVI, MKV, FLV, WMV, M4V (via ffmpeg keyframe extraction)
- **12 fallback backends** — 6 free models first, then 6 paid models for reliability
- **Zero hardcoded secrets** — API keys in `config.json` (gitignored) or env vars
- **Works everywhere** — CLI, MCP server, opencode skill, or direct Python import

## Quick start

### Drop-in install (tell your AI)

Just send this URL to your AI assistant:

```
https://github.com/farhanic017/vision-tool
```

Your AI will clone, install deps, set up API keys, and configure everything
automatically. The `SKILL.md` file contains step-by-step instructions that
any AI agent reads and follows.

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

The tool chains through **6 free models** first, then **6 paid models** as fallback.
It stops at the first backend that returns a result.

| # | Tier | Model | Provider | Cost |
|---|------|-------|----------|------|
| 1 | ☆ | **Gemini 2.5 Flash** | Google (direct) | Free tier |
| 2 | ☆ | Gemini 2.0 Flash | Google (direct) | Free tier |
| 3 | ☆ | NVIDIA Nemotron Omni | OpenRouter | Free |
| 4 | ☆ | Gemma 4 26B | OpenRouter | Free |
| 5 | ☆ | NVIDIA Nemotron VL | OpenRouter | Free |
| 6 | ☆ | OpenRouter free router | OpenRouter | Free (any available model) |
| 7 | ★ | **GPT-4o** | OpenRouter | Paid (~$0.01/image) |
| 8 | ★ | GPT-4o-mini | OpenRouter | Cheap (~$0.001/image) |
| 9 | ★ | Claude 3.5 Sonnet | OpenRouter | Paid |
| 10 | ★ | Claude 3 Haiku | OpenRouter | Cheap |
| 11 | ★ | Llama 3.2 90B Vision | OpenRouter | Paid |
| 12 | ★ | Qwen VL 8B | OpenRouter | Cheap (~$0.0001/image) |

> The paid backends only try if your OpenRouter account has billing configured.
> If you only have a free OpenRouter key, the first 6 free models will still work.

## Getting API keys

You need at least **one** of these:

| Key | Get it | Powers |
|-----|--------|--------|
| **Gemini API key** | https://aistudio.google.com/apikey | Backends 1–2 (native image + video, free tier) |
| **OpenRouter API key** | https://openrouter.ai/keys | Backends 3–12 (free + paid vision models) |

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

### 2. MCP server (OpenCode, Claude Desktop, Cursor, Windsurf, Continue.dev)

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
  }
}
```

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

#### Cursor

In Cursor's MCP server settings:

```
Name: vision-tool
Type: command
Command: python path/to/vision_mcp_server.py
```

Once added, your AI can call `analyze_image` or `analyze_video` with any
file path — no shell commands needed.

### 3. OpenCode skill

Add to your `opencode.jsonc` under `skills.paths`:

```jsonc
{
  "skills": {
    "paths": [
      "path/to/vision-tool"
    ]
  }
}
```

Now when you ask your AI to "look at this image" or "analyse this video",
the skill activates automatically and the AI knows to use `vision_proxy.py`.

> **Tip**: Combine with the [skill-dispatcher](https://github.com/farhanic017/dynamic-skill-loader-for-opencode)
> for on-demand loading.

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
whenever `opencode.exe` runs and kills it when opencode exits — all hidden,
no windows, no taskbar icons.

**How it works:**

```
Windows starts
  │
  ▼
vision_watchdog.vbs launches (invisible via wscript.exe)
  │
  ▼
Every 10s polls WMI: "Is opencode.exe running?"
  │
  ├── Yes → Launch vision_mcp_server.py as hidden process
  │         (writes PID to %TEMP%\vision_watchdog.pid)
  │
  └── No  → Kill child process, delete PID file
```

#### Quick start

```cmd
:: Start the watchdog (double-click or run at login)
wscript.exe //nologo "C:\path\to\vision_watchdog.vbs"
```

Add it to your startup folder (`shell:startup`) so it runs at every boot:

```cmd
:: Copy shortcut to Startup folder
powershell -Command "$wshell = New-Object -ComObject WScript.Shell; $shortcut = $wshell.CreateShortcut((Join-Path $wshell.SpecialFolders('Startup') 'vision-tool.lnk')); $shortcut.TargetPath = 'wscript.exe'; $shortcut.Arguments = '//nologo \"C:\path\to\vision_watchdog.vbs\"'; $shortcut.WindowStyle = 7; $shortcut.Save()"
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
User: "What's in this image?"
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
        ├── Images → resize to 1024px
        └── Videos → ffmpeg extracts 8 keyframes
        │
        ▼
  Try 12 backends in order:
    ☆ 1. Gemini 2.5 Flash      (free, best quality)
    ☆ 2. Gemini 2.0 Flash      (free fallback)
    ☆ 3. NVIDIA Nemotron Omni  (free)
    ☆ 4. Gemma 4 26B           (free)
    ☆ 5. NVIDIA Nemotron VL    (free)
    ☆ 6. OpenRouter free       (free catch-all)
    ★ 7. GPT-4o                (paid, best reliability)
    ★ 8. GPT-4o-mini           (cheap paid)
    ★ 9. Claude 3.5 Sonnet     (paid)
    ★10. Claude 3 Haiku        (cheap paid)
    ★11. Llama 3.2 90B Vision  (paid)
    ★12. Qwen VL 8B            (cheap paid, last resort)
        │
        ▼
  Returns text description → model reads it to you
```

## File structure

```
vision-tool/
├── README.md                 # This file
├── SKILL.md                  # opencode skill definition (AI reads this to install)
├── install.py                # Auto-installer (one command setup)
├── vision_proxy.py           # Core analysis engine (CLI + Python API)
├── vision_mcp_server.py      # MCP server (stdio + HTTP modes)
├── vision_watchdog.vbs       # Invisible background process manager (WMI)
├── vision_watchdog.cs        # C# source for zero-flash compiled EXE
├── setup.py                  # First-run API key wizard
├── config.json.example       # Example config (safe to commit)
├── config.json               # Your actual keys (gitignored)
├── requirements.txt          # pip dependencies
├── .gitignore                # Ignores config.json, __pycache__
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

## License

GNU General Public License v3.0 — see [LICENSE](./LICENSE).

This program is free software: you can redistribute and/or modify it under the terms of the GPLv3.
Modified versions must be licensed under GPLv3 with clear attribution to the original author.

© 2026 Farhan Dhrubo.
