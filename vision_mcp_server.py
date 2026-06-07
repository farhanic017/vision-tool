#!/usr/bin/env python3
#  Vision Tool — MCP server for image & video analysis
#  Copyright (c) 2026 Farhan Dhrubo  <farhaiee123@gmail.com>
#  License: GPL-3.0  —  https://github.com/farhanic017/vision-tool
#
#  This program is free software. You may NOT remove this notice,
#  re-distribute as your own work, or sell without attribution.
# =============================================================================

"""
vision_mcp_server.py — MCP server for vision-tool.
Copyright (C) 2026 Farhan Dhrubo

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Exposes vision_proxy.py as MCP tools so any MCP-compatible client
(OpenCode, Claude Desktop, Cursor, Windsurf, Continue.dev, etc.)
can analyse images and videos via natural language.

Tools:
  - analyze_image(path, prompt?)
  - analyze_video(path, prompt?)

Add to any MCP client:
  {
    "mcpServers": {
      "vision-tool": {
        "command": "python",
        "args": ["path/to/vision_mcp_server.py"]
      }
    }
  }

Protocol: JSON-RPC 2.0 over stdio (standard MCP).
"""

import json
import sys
import os
import io
import traceback
import argparse

# Safe stderr output at module level (not wrapped, to avoid pipe issues)
_SAFE_STDERR = sys.stderr

# Set up paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# Lazy import — loaded on first use, not at module level
_vp = None
def _get_vp():
    global _vp
    if _vp is None:
        import vision_proxy
        _vp = vision_proxy
    return _vp


def _start_background_refresh():
    """Kick the 2-day capability refresh as soon as the MCP process starts."""
    try:
        vp = _get_vp()
        starter = getattr(vp, "start_background_capability_refresh", None)
        if callable(starter):
            starter(reason="mcp_startup")
    except Exception as exc:
        try:
            _SAFE_STDERR.write(f"vision-tool refresh startup skipped: {exc}\n")
            _SAFE_STDERR.flush()
        except Exception:
            pass

TOOLS = {
    "analyze_image": {
        "name": "analyze_image",
        "description": "Analyse an image file and return a description prefixed with the filename. Covers text, colours, layout, UI elements, typography, spacing, etc. Pass a custom prompt for focus.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the image (png, jpg, webp, bmp, gif). Can be absolute or relative."},
                "prompt": {"type": "string", "description": "Optional custom prompt, e.g. 'Extract all text from this diagram' or 'Focus only on colours and typography'"},
                "model": {"type": "string", "description": "Optional model name, e.g. 'ollama/llava:latest', 'openrouter/google/gemini-2.5-flash', 'openai/gpt-4o-mini', 'anthropic/claude-sonnet-4-5', or 'cohere/command-a-vision-07-2025'"},
            },
            "required": ["path"],
        },
    },
    "analyze_video": {
        "name": "analyze_video",
        "description": "Analyse a video file by extracting keyframes and returning a description prefixed with the filename. Covers frame-by-frame actions, UI flow, text, scene changes, interactions, etc.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the video (mp4, webm, mov, avi, mkv, flv, wmv, m4v). Can be absolute or relative."},
                "prompt": {"type": "string", "description": "Optional custom prompt, e.g. 'Describe the UI flow step by step' or 'Focus only on text appearing on screen'"},
                "model": {"type": "string", "description": "Optional model name, e.g. 'ollama/llava:latest', 'openrouter/google/gemini-2.5-flash', 'openai/gpt-4o-mini', 'anthropic/claude-sonnet-4-5', or 'cohere/command-a-vision-07-2025'"},
            },
            "required": ["path"],
        },
    },
}


def _resolve_path(raw):
    """Resolve an image/video path to absolute — handles relative paths, ~, and Windows backslashes."""
    if not raw:
        return raw
    if not isinstance(raw, str):
        return ""
    raw = raw.strip().strip('"').strip("'")
    # Expand ~ to user home
    raw = os.path.expanduser(raw)
    # Normalise Windows backslashes but keep drive letters
    raw = os.path.normpath(raw)
    # If not absolute, resolve against a reasonable CWD
    if not os.path.isabs(raw):
        # Try: client's CWD via env, user profile, or script dir
        cwd = os.environ.get("INITIAL_CWD") or os.environ.get("PWD") or os.getcwd()
        raw = os.path.abspath(os.path.join(cwd, raw))
    return raw


def handle_tool_call(name, args):
    vp = _get_vp()
    tool_map = {
        "analyze_image": vp.analyze,
        "analyze_video": vp.analyze,
    }

    if name not in tool_map:
        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}

    raw_path = args.get("path", "")
    path = _resolve_path(raw_path)
    prompt = args.get("prompt", "")
    model = args.get("model", None)

    try:
        result = tool_map[name](path, prompt, model)
        return {"content": [{"type": "text", "text": result}]}
    except FileNotFoundError as e:
        return {"content": [{"type": "text", "text": str(e)}], "isError": True}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}


def send(msg):
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def process_message(msg):
    """Handle a single JSON-RPC message and return a response, or None for notifications."""
    msg_id = msg.get("id")
    method = msg.get("method")
    params = msg.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {
                        name: {
                            "description": info["description"],
                            "inputSchema": info["inputSchema"],
                        }
                        for name, info in TOOLS.items()
                    }
                },
                "serverInfo": {"name": "vision-tool", "version": "1.0.0"},
            },
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": list(TOOLS.values())}}

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        try:
            result = handle_tool_call(tool_name, tool_args)
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32603, "message": str(e), "data": traceback.format_exc()},
            }

    if method == "notifications/initialized":
        return None

    if msg_id is None:
        return None

    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}


def handle_http_request(environ, start_response):
    """WSGI handler for HTTP MCP mode."""
    path = environ.get("PATH_INFO", "").rstrip("/")

    if path == "/mcp" and environ["REQUEST_METHOD"] == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", 0))
            body = environ["wsgi.input"].read(length).decode("utf-8")
            msg = json.loads(body)
            resp = process_message(msg)
            if resp is None:
                start_response("202 Accepted", [("Content-Type", "application/json")])
                return [b'{"status":"accepted"}']
            js = json.dumps(resp, ensure_ascii=False)
            start_response("200 OK", [("Content-Type", "application/json")])
            return [js.encode("utf-8")]
        except json.JSONDecodeError:
            start_response("400 Bad Request", [("Content-Type", "application/json")])
            return [b'{"error":"Invalid JSON"}']
        except Exception as e:
            start_response("500 Internal Server Error", [("Content-Type", "application/json")])
            return [json.dumps({"error": str(e)}).encode("utf-8")]

    if path == "/health":
        start_response("200 OK", [("Content-Type", "application/json")])
        return [b'{"status":"ok","version":"1.0.0"}']
    if path == "/tools":
        resp = process_message({"id": 1, "method": "tools/list"})
        js = json.dumps(resp, ensure_ascii=False)
        start_response("200 OK", [("Content-Type", "application/json")])
        return [js.encode("utf-8")]

    start_response("404 Not Found", [("Content-Type", "text/plain")])
    return [b"Not Found"]


def run_stdio():
    """Run MCP server over stdin/stdout (default)."""
    buf = ""
    while True:
        try:
            chunk = sys.stdin.read(4096)
            if not chunk:
                break
            buf += chunk
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                resp = process_message(msg)
                if resp is not None:
                    send(resp)
        except (EOFError, KeyboardInterrupt):
            break
        except Exception as e:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)}})


def run_http(port=3789):
    """Run MCP server as HTTP server (for watchdog background mode)."""
    from wsgiref.simple_server import make_server
    httpd = make_server("127.0.0.1", port, handle_http_request)
    httpd.timeout = 0.5
    while True:
        try:
            httpd.handle_request()
        except KeyboardInterrupt:
            break


def main():
    import argparse
    parser = argparse.ArgumentParser(description="vision-tool MCP server")
    parser.add_argument("--http", type=int, nargs="?", const=3789, default=0,
                        help="Run as HTTP server on given port (default: 3789). Omit for stdio mode.")
    args = parser.parse_args()
    _start_background_refresh()

    if args.http:
        _SAFE_STDERR.write(f"Starting HTTP MCP server on port {args.http}...\n")
        _SAFE_STDERR.flush()
        run_http(args.http)
    else:
        run_stdio()


if __name__ == "__main__":
    main()
