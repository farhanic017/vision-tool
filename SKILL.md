---
name: vision-tool
description: >
  Analyse images and videos when the active model lacks native vision.
  Extracts text, UI elements, colours, layout, actions, and scene changes
  from image files (png, jpg, webp, bmp, gif) and video files
  (mp4, webm, mov, avi, mkv, flv, wmv, m4v) by routing them through
  12 vision backends — free models first (Gemini, NVIDIA, Gemma 4),
  then paid models (GPT-4o, Claude, Llama, Qwen VL) via OpenRouter.
triggers:
  - vision-tool
  - vision
  - image
  - video
  - screenshot
  - see
  - look at
  - analyse image
  - analyse video
  - describe picture
  - describe video
  - install vision
  - setup vision
---

# vision-tool

Brings image & video analysis to any opencode model — even ones without
built-in vision (e.g. big-pickle, DeepSeek, local models).

## Instant Install (one command)

When a user drops this repo URL into their AI, do this:

1. **Clone the repo:**
   ```bash
   git clone https://github.com/farhanic017/vision-tool.git
   cd vision-tool
   ```

2. **Install dependencies:**
   ```bash
   pip install pillow
   ```

3. **Configure API keys:**
   ```bash
   python setup.py
   ```
   Choose option 1 to enter keys now, or option 2 to add later.
   Add keys anytime: `python setup.py --add-key`

4. **Add MCP server to config:**
   - For **opencode** → edit `opencode.jsonc`:
     ```jsonc
     "mcp": {
       "vision-tool": {
         "type": "local",
         "command": ["python", "/full/path/to/vision_mcp_server.py"],
         "enabled": true
       }
     }
     ```
   - For **Claude Desktop** → edit `claude_desktop_config.json`:
     ```json
     "mcpServers": {
       "vision-tool": {
         "command": "python",
         "args": ["/full/path/to/vision_mcp_server.py"]
       }
     }
     ```
   - For **Cursor** → add in MCP server settings:
     ```
     Name: vision-tool
     Type: command
     Command: python /full/path/to/vision_mcp_server.py
     ```

5. **Also add as opencode skill** (optional, for trigger-based activation):
   ```jsonc
   "skills": {
     "paths": ["/full/path/to/vision-tool"]
   }
   ```

Or just run the auto-installer:
```bash
python install.py
python install.py --auto   # Non-interactive
```

## How it works

1. The user provides a path to an image or video file.
2. This script extracts content (keyframes for video, resized frame for images).
3. It sends the content through a chain of 12 vision backends until one succeeds.
4. The backend returns a text description of what it "sees".

## Backend chain (free first, paid fallback)

| # | Model | Cost |
|---|-------|------|
| 1 | Gemini 2.5 Flash | Free |
| 2 | Gemini 2.0 Flash | Free |
| 3 | NVIDIA Nemotron Omni | Free |
| 4 | Gemma 4 26B | Free |
| 5 | NVIDIA Nemotron VL | Free |
| 6 | OpenRouter free router | Free |
| 7 | GPT-4o | Paid |
| 8 | GPT-4o-mini | Cheap |
| 9 | Claude 3.5 Sonnet | Paid |
| 10 | Claude 3 Haiku | Cheap |
| 11 | Llama 3.2 90B Vision | Paid |
| 12 | Qwen VL 8B | Cheap |

## First run

Run `setup.py` once to add API keys:

    python path/to/vision/setup.py

Choose option 1 to enter keys now (validated, locked to you only).
Choose option 2 to add later — vision-tool won't work until you add them.
Add keys later with: `python setup.py --add-key`

Keys are stored in `config.json` next to the script (gitignored, locked permissions).

## Usage

When the user asks you to look at an image or video, run:

    python path/to/vision/vision_proxy.py <file_path> [optional prompt...]

### Examples

| User request | Command |
|---|---|
| "What's in this screenshot?" | `python vision_proxy.py screenshot.png` |
| "Read the text from this diagram" | `python vision_proxy.py diagram.jpg "Extract all visible text"` |
| "Describe this video" | `python vision_proxy.py demo.mp4` |
| "What UI flow does this recording show?" | `python vision_proxy.py recording.mp4 "Describe the UI flow and each action"` |

### Important

- **Always use the full absolute path** to the script and the file.
- If `config.json` is missing, run `setup.py` first.
- The script prints the description to stdout. Return it to the user.
- For videos, it extracts up to 8 evenly-spaced keyframes via ffmpeg.

## MCP mode

The server can also be run as an MCP server (via `vision_mcp_server.py`),
exposing `analyze_image` and `analyze_video` as native tools. Add it to
your MCP config instead of running CLI commands.

## Installation

See **[README.md](README.md)** for all integration methods.
