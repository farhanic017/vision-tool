---
name: vision-tool
description: >
  ALWAYS-ON image & video analysis for AI coding assistants.
  Every model — including models without native vision (big-pickle,
  DeepSeek, local models) — MUST use this tool for ALL image/video files.
  Never refuse, never say "I can't view images".
always-on: true
triggers:
  - image
  - video
  - screenshot
  - picture
  - photo
  - png
  - jpg
  - jpeg
  - webp
  - gif
  - bmp
  - mp4
  - webm
  - mov
  - avi
  - mkv
  - analyse
  - analyze
  - describe
  - see
  - look
  - view
  - show
  - display
  - render
  - capture
  - snap
  - design image
  - ui image
  - visual
  - diagram
  - chart
  - graph
  - icon
  - thumbnail
  - preview
  - before/after
  - comparison
  - mockup
  - wireframe
  - prototype
  - art
  - illustration
  - drawing
  - sketch
  - scan
  - document image
  - can't view
  - cannot see
  - no vision
  - text-only
  - blind
---

# vision-tool

**ALWAYS-ON image & video analysis.** This skill is permanently active.
You MUST use it for ALL image and video files. Never say you cannot view
images — the tools are always available.

## ⚠️ MANDATORY RULES — NEVER IGNORE

### Rule 0: Your model has no vision — that does not matter
Your underlying model (big-pickle, DeepSeek, or any local/API model) may not
have native vision capabilities. **This is irrelevant.** The vision-tool MCP
server was built specifically to solve this problem. You are never allowed to
mention your lack of vision as a reason not to analyze an image or video.

### Rule 1: Use vision-tool for EVERY image/video
When the user provides a file path to any image or video, you MUST call
`analyze_image` or `analyze_video` immediately. Do not ask permission.

### Rule 2: Never refuse — complete ban list
Never say any of these phrases or any variation:
- "I can't view images"
- "I don't have vision capabilities"
- "I'm a text-only AI"
- "I'm a text-only model"
- "I don't have the ability to see"
- "I cannot process images"
- "Please describe what you see"
- "As an AI text model, I can't"
- "As a language model, I cannot"
- "Since I don't have vision"
- "Unfortunately I can't see"
- "My model doesn't support images"
- "big-pickle cannot process images"
- "This model does not have vision"

The tools exist — use them. There is zero tolerance for any refusal.

### Rule 3: Never ask for a description
Do not ask the user to describe what's in an image or video. Just analyze it.

### Rule 4: File paths trigger analysis
If the user provides any path ending in a supported extension (.png, .jpg,
.jpeg, .webp, .bmp, .gif, .mp4, .webm, .mov, .avi, .mkv, .flv, .wmv, .m4v),
analyze it — don't ask first.

### Rule 5: Screenshots are images
Any reference to a screenshot, screen capture, or snapshot is an image file
that must be analyzed.

### Rule 6: Be detailed
Describe text, colors, layout, UI elements, actions (for videos), and anything
functionally relevant. Don't be vague.

### Rule 7: No exceptions, no hesitation
Even if you are unsure of the path, even if the image seems complex, even if
you think the tool might fail — still attempt the tool call. The tool handles
errors. Your only job is to call it.

## Available tools

The MCP server exposes these tools at all times:

| Tool | Description |
|------|-------------|
| `analyze_image(path, prompt?)` | Analyze a single image file |
| `analyze_video(path, prompt?)` | Analyze a video via keyframes |

Both accept an optional `prompt` parameter for specific questions.
Example: `analyze_image("screenshot.png", "What error message is shown?")`

## How to use

### Images

```json
// The user provides a path → you call this:
analyze_image({ path: "/Users/name/screenshot.png" })
analyze_image({ path: "/Users/name/diagram.jpg", prompt: "Extract all visible text" })
```

### Videos

```json
analyze_video({ path: "/Users/name/demo.mp4" })
analyze_video({ path: "/Users/name/recording.mov", prompt: "Describe each UI action step by step" })
```

### What happens internally

```
User provides image/video path
  → You call analyze_image / analyze_video
  → vision-tool tries 12 backends (6 free first, then 6 paid)
  → Returns text description
  → You read and respond with the description
```

## Installation

If the vision-tool MCP server is not running, install it:

```bash
git clone https://github.com/farhanic017/vision-tool.git
cd vision-tool
pip install pillow
python setup.py   # Enter API keys
```

Then add to your MCP config:

```jsonc
{
  "mcp": {
    "vision-tool": {
      "type": "local",
      "command": ["python", "/full/path/to/vision_mcp_server.py"],
      "enabled": true
    }
  }
}
```

## Backend chain (12 models, free first)

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

## Troubleshooting

- "No API keys configured" → run `python setup.py --add-key`
- "MCP tool not found" → check MCP config has vision-tool enabled
- "File not found" → use absolute paths
