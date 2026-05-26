# vision-tool — always-on instruction

You have access to the **vision-tool** MCP server which provides `analyze_image`
and `analyze_video` tools for image and video analysis.

## Mandatory behavior

1. **Analyze every image/video automatically.** When the user provides a file
   path to any image (.png, .jpg, .jpeg, .webp, .bmp, .gif) or video (.mp4,
   .webm, .mov, .avi, .mkv, .flv, .wmv, .m4v), call `analyze_image` or
   `analyze_video` immediately — do not ask.

2. **Never refuse.** You must NEVER say:
   - "I can't view images"
   - "I don't have vision capabilities"
   - "I'm a text-only AI"
   - "Please describe what you see"
   - Any variation of "I cannot see/analyze/view this image/video"
   
   The vision-tool is always available. Use it.

3. **Never ask the user to describe** what's in an image or video. The tool
   does this for you.

4. **Screenshots are images.** Any screenshot, screen capture, snapshot,
   screen grab, or print screen is an image file — analyze it.

5. **Be thorough.** When analyzing, describe visible text, colors, layout,
   UI elements, and any functionally relevant details. For videos, describe
   actions and scene changes.
