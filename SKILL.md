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

**CRITICAL: Do NOT use the Read tool on image/video files.**
Your model cannot process images directly. Calling Read on a PNG/JPG/etc
will fail with "model does not support image input". Always pass the file
path to analyze_image/analyze_video instead.

### Rule 1b: ALWAYS use absolute paths
You MUST pass the FULL absolute path to `analyze_image` / `analyze_video`.
Never pass a relative path. If the user gives a relative path, resolve it
to absolute first. The path must work directly on the user's filesystem.

**New: Auto-file search.** If the path doesn't exist, the tool automatically
searches Desktop, Downloads, Pictures, Documents, and user profile for a
matching filename. You can pass just `"screenshot.png"` and it will find it.

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

**Output format:** Both tools return `[filename]\n<description>`. The filename
header lets you tell the user which file you're describing instead of just
saying "this image shows…". Use the filename directly in your response.

## How to use

### Quick start — MCP tool (0 thinking needed):

```json
analyze_image({ path: "screenshot.png" })
```

If the MCP tool `analyze_image` is **not in your function list**, skip all thinking and use the bash fallback immediately.

### Bash fallback (used when MCP tool not visible):

```bash
python C:\Users\Farhan\Desktop\vision-tool\vision_proxy.py "C:\path\to\image.png"
```

The bash fallback works identically. Do NOT think about alternatives. Do NOT check if the file exists first. Do NOT use Read tool. Just run the command. Zero seconds of deliberation.

**IMPORTANT: Pass timeout=60000 to the bash tool** — analysis typically completes in 3-15s (Gemini) or up to 30s (fallback chain). Set timeout to at least 60000ms for safety.

### What the script prints (read this to understand which backends work):

```
KEYS: Gemini ✓  Azure AI Foundry ✓  Groq ✓  HuggingFace ✓  Mistral ✓
KEYS: 6 backends available
  ☆ CF Gemma 4 26B: OK   <-- first success wins
```

All backends run in parallel — first response wins, rest are cancelled.
`KEYS:` lines tell you instantly which APIs are configured.

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

## Backend chain (23 models)

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

## Troubleshooting

- "No API keys configured" → run `python setup.py --add-key`
- "MCP tool not found" → check MCP config has vision-tool enabled
- "File not found" → the file might not be in Desktop, Downloads, Pictures, or Documents. Pass the full absolute path.
