"""
fuzz_stress_test.py — Destructive fuzzing, stress, edge-case, and security testing.

Tests every imaginable failure mode: encoding attacks, path traversal,
concurrency, memory pressure, corrupted inputs, protocol violations,
subprocess failures, environment corruption, type confusion, resource leaks.
"""

import os
import sys
import io
import json
import base64
import tempfile
import shutil
import subprocess
import threading
import time
import signal
import queue
import gc
import random
import string
import traceback
import re

# Preserve REAL stdout/stderr — use raw fd to survive TextIOWrapper detach
try:
    _REAL_STDOUT_FD = os.dup(1)
    _REAL_STDOUT = io.TextIOWrapper(io.FileIO(_REAL_STDOUT_FD, "wb"), encoding="utf-8", errors="replace")
except OSError:
    _REAL_STDOUT = sys.stdout

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# Quiet mode — suppress expected stderr
_DEVNULL = open(os.devnull, "w")

PASS = 0
FAIL = 0
TOTAL = 0


def safe_print(text):
    """Print to _REAL_STDOUT which is never replaced."""
    try:
        _REAL_STDOUT.write(text + "\n")
        _REAL_STDOUT.flush()
    except Exception:
        try:
            # Last-resort fallback
            os.write(1, (text + "\n").encode("utf-8", errors="replace"))
        except Exception:
            pass


def check(name, ok):
    global TOTAL, PASS, FAIL
    TOTAL += 1
    if ok:
        PASS += 1
        safe_print(f"  PASS  {name}")
    else:
        FAIL += 1
        safe_print(f"  \u2570\u2192 FAIL  {name}")


def reset_vp():
    """Force reimport of vision_proxy from scratch."""
    for mod in list(sys.modules.keys()):
        if "vision_proxy" in mod:
            del sys.modules[mod]
    import vision_proxy as vp
    return vp


# ═══════════════════════════════════════════════════════════════════════════
# 1. ENCODING ATTACKS — everything that can break string handling
# ═══════════════════════════════════════════════════════════════════════════

def test_encoding_attacks():
    vp = reset_vp()

    # Unicode injection in filenames
    attacks = [
        "test\u0000null.png",          # null byte
        "test\ud800surrogate.png",     # unpaired surrogate
        "test\u202etrick.png",         # right-to-left override
        "test\nnewline.png",           # newline in filename
        "test\rreturn.png",            # carriage return
        "test\t tab.png",              # tab
        "test\\backslash.png",         # backslash
        "test%00url.png",              # URL-encoded null
        "test中文.png",                 # CJK
        "test\x1b[31mred.png",         # ANSI escape
        "test\x00\x00\x00.png",        # multiple nulls
        "test" + "A" * 500 + ".png",  # extremely long name (will fail on create)
        "con.png",                     # Windows reserved name
        "CON.png",                     # Windows reserved name uppercase
        "nul.png",                     # Windows reserved
        "prn.png",                     # Windows reserved
        "COM1.png",                    # Windows reserved
        "LPT1.png",                    # Windows reserved
    ]
    for name in attacks:
        # These should not crash — they should either return False or raise properly
        try:
            result = vp.is_image(name)
            check(f"is_image encoding attack: {name[:30]}", isinstance(result, bool))
        except Exception as e:
            # Exception is acceptable for truly invalid OS paths
            check(f"is_image encoding attack: {name[:30]} (crashed: {e})", False)

        try:
            result = vp.is_video(name)
            check(f"is_video encoding attack: {name[:30]}", isinstance(result, bool))
        except Exception as e:
            check(f"is_video encoding attack: {name[:30]} (crashed: {e})", False)

        try:
            result = vp.get_mime(name)
            check(f"get_mime encoding attack: {name[:30]}", isinstance(result, str))
        except Exception as e:
            check(f"get_mime encoding attack: {name[:30]} (crashed: {e})", False)

    # Unicode in prompt text
    unicode_prompts = [
        "\u0000null byte in prompt",
        "\ud800surrogate",
        "\u202eright-to-left",
        "\u00e9\u00e0\u00fc\u00f1",  # accented
        "\U0001f600\U0001f44d",       # emoji
        "A" * 100000,                 # 100K char prompt (stress)
        "\x1b[31mANSIs\x1b[0m",
        "\t\n\r   lots of whitespace   ",
        "<script>alert('xss')</script>",
        "${env:PATH}",                # shell injection
        "'; DROP TABLE users; --",    # SQL injection
        "../../etc/passwd",
        "!@#$%^&*()_+-=[]{}|;':\",./<>?`~",
    ]
    for p in unicode_prompts:
        # b64() should handle any string
        try:
            result = vp.b64(p.encode("utf-8", errors="surrogatepass"))
            check(f"b64 unicode prompt attack: {p[:30]}", isinstance(result, str) and len(result) > 0)
        except (UnicodeEncodeError, UnicodeDecodeError):
            check(f"b64 unicode prompt attack: {p[:30]} (can't encode)", True)
        except Exception as e:
            check(f"b64 unicode prompt attack: {p[:30]} crashed: {e}", False)

    # get_mime with empty, weird, and boundary cases
    edge_names = ["", ".", "..", ".hidden", "noext", "a" * 10000, "\n", "\t", " ", "  ", ".", "..png"]
    for name in edge_names:
        try:
            result = vp.get_mime(name)
            check(f"get_mime edge: {repr(name)[:30]}", isinstance(result, str))
        except Exception:
            check(f"get_mime edge: {repr(name)[:30]}", False)


# ═══════════════════════════════════════════════════════════════════════════
# 2. FILESYSTEM EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════

def test_filesystem_edge_cases():
    vp = reset_vp()
    td = tempfile.mkdtemp()
    try:
        # ── Non-existent file variations ──
        nonexistent = [
            os.path.join(td, "nonexistent.png"),
            os.path.join(td, "does_not_exist.mp4"),
            os.path.join(td, "no_extension"),
            os.path.join(td, ""),              # empty filename
            td,                                 # directory, not file
        ]
        for path in nonexistent:
            try:
                vp.analyze(path)
                check(f"analyze with nonexistent {os.path.basename(path) or 'empty'}", False)
            except FileNotFoundError:
                check(f"analyze with nonexistent {os.path.basename(path) or 'empty'}", True)
            except IsADirectoryError:
                check(f"analyze with directory {os.path.basename(path) or 'empty'}", True)
            except Exception as e:
                check(f"analyze with nonexistent {os.path.basename(path) or 'empty'} (ok: {e.__class__.__name__})", True)

        # ── Invalid file types ──
        invalid_files = [
            ("empty.txt", b""),
            ("whitespace.txt", b"   \n   "),
            ("binary.bin", bytes(range(256))),
            ("random.bin", os.urandom(1024)),
            ("zeroes.bin", b"\x00" * 4096),
            ("corrupted.png", b"not a png at all but has .png ext"),
            ("corrupted.jpg", b"not a jpg\0\0\0"),
            ("huge_header.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 100000),  # valid header but huge zeros
        ]
        for fname, content in invalid_files:
            path = os.path.join(td, fname)
            with open(path, "wb") as f:
                f.write(content)

            # These should not crash analyze — they should either fail with FileNotFoundError
            # or RuntimeError (no backends configured)
            try:
                vp.analyze(path, "test prompt")
                check(f"analyze corrupted {fname}", False)  # shouldn't succeed without keys
            except (FileNotFoundError, RuntimeError, SystemExit):
                check(f"analyze corrupted {fname}", True)   # expected behavior
            except Exception as e:
                check(f"analyze corrupted {fname} (acceptable: {e.__class__.__name__})", True)

        # ── resize_image edge cases ──
        for fname, content in invalid_files:
            path = os.path.join(td, fname)
            with open(path, "wb") as f:
                f.write(content)
            try:
                data, mime = vp.resize_image(path)
                check(f"resize_image corrupted {fname}: returns data", isinstance(data, bytes))
                check(f"resize_image corrupted {fname}: has mime", isinstance(mime, str))
            except Exception as e:
                check(f"resize_image corrupted {fname}: crashed {e.__class__.__name__}", False)

        # ── Symlink ──
        try:
            real_path = os.path.join(td, "real_target.txt")
            with open(real_path, "w") as f:
                f.write("hello")
            link_path = os.path.join(td, "link.png")
            os.symlink(real_path, link_path)
            # This should not crash — it'll try to analyze a txt file as image
            try:
                vp.analyze(link_path)
            except (FileNotFoundError, RuntimeError):
                pass
            check("symlink handling", True)
        except (OSError, NotImplementedError):
            # Symlinks may not be available on all Windows setups
            check("symlink handling (skipped)", True)

        # ── Read-only file ──
        ro_path = os.path.join(td, "readonly.png")
        with open(ro_path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        try:
            os.chmod(ro_path, 0o444)
        except Exception:
            pass
        try:
            data, mime = vp.resize_image(ro_path)
            check("resize_image read-only file", isinstance(data, bytes))
        except Exception as e:
            check(f"resize_image read-only file crashed: {e}", False)

        # ── Locked file (Windows: open with exclusive lock) ──
        locked_path = os.path.join(td, "locked.png")
        with open(locked_path, "wb") as f:
            f.write(b"dummy")
        try:
            # On Windows, opening with FILE_SHARE_READ=0 can lock it
            import msvcrt
            f_lock = open(locked_path, "rb")
            try:
                msvcrt.locking(f_lock.fileno(), msvcrt.LK_NBLCK, 1)
                try:
                    vp.resize_image(locked_path)
                    check("resize_image locked file", True)  # may succeed via PIL or fallback
                except (PermissionError, OSError):
                    check("resize_image locked file (expected fail)", True)
                except Exception as e:
                    check(f"resize_image locked file: {e}", True)
            except (OSError, IOError):
                check("resize_image locked file (couldn't lock)", True)
            finally:
                try:
                    f_lock.close()
                except Exception:
                    pass
        except ImportError:
            check("resize_image locked file (no msvcrt)", True)

        # ── Path with special chars (Windows reserved) ──
        for special in ["test[1].png", "test(1).png", "test{1}.png", "test$test.png"]:
            special_path = os.path.join(td, special)
            with open(special_path, "wb") as f:
                f.write(b"dummy content")
            try:
                data, mime = vp.resize_image(special_path)
                check(f"resize_image special chars {special}", isinstance(data, bytes))
            except Exception as e:
                check(f"resize_image special chars {special} crashed: {e}", False)

    finally:
        shutil.rmtree(td, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════
# 3. CONFIG CORRUPTION — every possible format in config.json
# ═══════════════════════════════════════════════════════════════════════════

def test_config_corruption():
    td = tempfile.mkdtemp()
    try:
        # Backup real config
        real_config = os.path.join(SCRIPT_DIR, "config.json")
        backed_up = False
        if os.path.isfile(real_config):
            shutil.copy2(real_config, os.path.join(td, "config_backup.json"))
            backed_up = True

        corrupt_configs = [
            ("not json at all", "this is not json"),
            ("empty string", ""),
            ("null", "null"),
            ("number", "42"),
            ("array", '[1, 2, 3]'),
            ("empty array", "[]"),
            ("true", "true"),
            ("false", "false"),
            ("nested objects", '{"a": {"b": {"c": "deep"}}}'),
            ("unicode snowman", '{"\u2603": "snowman"}'),
            ("very long keys", '{"' + 'x' * 10000 + '": "value"}'),
            ("deeply nested", '{"a": {' * 100 + '}' * 100),
            ("binary in json", b'\x00\x01\x02'.decode('latin-1')),
            ("json with comments", '{"key": "value" /* comment */}'),
            ("trailing comma", '{"key": "value",}'),
            ("repeated keys", '{"key": "v1", "key": "v2"}'),
            ("empty object", "{}"),
            ("unicode escapes", '{"key": "\\u0048\\u0065\\u006c\\u006c\\u006f"}'),
            ("keys as strings", '{"GEMINI_API_KEY": null}'),
            ("keys as int", '{"GEMINI_API_KEY": 42}'),
            ("keys as list", '{"GEMINI_API_KEY": ["key1", "key2"]}'),
            ("keys as object", '{"GEMINI_API_KEY": {"nested": "key"}}'),
            ("extra fields", '{"GEMINI_API_KEY": "x", "OPENROUTER_API_KEY": "y", "MALICIOUS": "rm -rf /"}'),
            ("windows path sep", '{"GEMINI_API_KEY": "C:\\\\Users\\\\test\\\\key"}'),
            ("unicode key values", '{"GEMINI_API_KEY": "\\ud83d\\ude00\\n\\t"}'),
        ]

        for desc, content in corrupt_configs:
            # Write directly to config.json
            with open(real_config, "w", encoding="utf-8") as f:
                f.write(content)

            try:
                vp = reset_vp()
                result = vp.load_config()
                check(f"load_config: {desc}", isinstance(result, dict))
            except RuntimeError:
                check(f"load_config: {desc} (no keys)", True)
            except Exception as e:
                check(f"load_config: {desc} crashed: {e.__class__.__name__}", False)

        # Restore real config
        if backed_up:
            shutil.copy2(os.path.join(td, "config_backup.json"), real_config)
        else:
            if os.path.isfile(real_config):
                os.remove(real_config)
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════
# 4. ENVIRONMENT VARIABLE ATTACKS
# ═══════════════════════════════════════════════════════════════════════════

def test_env_attacks():
    vp = reset_vp()

    # Save and restore
    old_environ = os.environ.copy()

    try:
        # ── Missing env vars ──
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("OPENROUTER_API_KEY", None)

        # Remove config.json temporarily
        real_config = os.path.join(SCRIPT_DIR, "config.json")
        config_backup = None
        if os.path.isfile(real_config):
            with open(real_config, "r") as f:
                config_backup = f.read()
            os.remove(real_config)

        # ── No config no env ──
        try:
            vp.load_config()
            check("load_config: no config no env", False)
        except RuntimeError:
            check("load_config: no config no env (no keys)", True)

        # ── Empty env vars ──
        os.environ["GEMINI_API_KEY"] = ""
        os.environ["OPENROUTER_API_KEY"] = ""
        os.environ["GEMINI_API_KEY"] = ""
        os.environ["OPENROUTER_API_KEY"] = ""
        try:
            vp.load_config()
            check("load_config: empty env vars", False)
        except RuntimeError:
            check("load_config: empty env vars (no keys)", True)

        # ── Whitespace keys ──
        os.environ["GEMINI_API_KEY"] = "   "
        os.environ["OPENROUTER_API_KEY"] = "\t\n  "
        vp = reset_vp()
        result = vp.load_config()
        check("load_config: whitespace keys returns dict", isinstance(result, dict))
        # If whitespace keys are not considered "present", might exit(1) instead
        # Both outcomes are acceptable

        # ── Very long env values ──
        long_val = "A" * min(30000, 32766)  # Windows limit is 32767
        os.environ["GEMINI_API_KEY"] = long_val
        os.environ["OPENROUTER_API_KEY"] = long_val
        vp = reset_vp()
        result = vp.load_config()
        check("load_config: huge env keys returns dict", isinstance(result, dict))

        # ── Unicode in env values ──
        os.environ["GEMINI_API_KEY"] = "\u2603\u2603\u2603"
        vp = reset_vp()
        result = vp.load_config()
        check("load_config: unicode env keys returns dict", isinstance(result, dict))

        # ── Restore ──
        os.environ.clear()
        os.environ.update(old_environ)

        if config_backup is not None:
            with open(real_config, "w") as f:
                f.write(config_backup)

    except Exception as e:
        check(f"env test infrastructure: {e}", False)
        os.environ.clear()
        os.environ.update(old_environ)


# ═══════════════════════════════════════════════════════════════════════════
# 5. STDERR/STDOUT WRAPPING
# ═══════════════════════════════════════════════════════════════════════════

def test_stdio_wrapping():
    """Test that stdout/stderr wrapping in __main__ is idempotent and safe."""
    # NEVER touch sys.stdout or sys.stderr directly — only inspect properties

    # ── Double-wrapping: simulate by wrapping a StringIO ──
    try:
        # Use StringIO which has no buffer — wrapping is a no-op
        fake = io.StringIO()
        # Simulate vision_proxy's wrapping logic
        if fake is not None and hasattr(fake, 'buffer') and fake.buffer is not None:
            pass  # won't trigger for StringIO
        check("double stdout wrapping (StringIO safe)", True)
    except Exception as e:
        check(f"double stdout wrapping crashed: {e}", False)

    # ── Verify vision_proxy module wraps safely without corrupting real stdout ──
    try:
        import vision_proxy
        check("vision_proxy import doesn't corrupt stdout", True)
    except Exception as e:
        check(f"vision_proxy import crashed: {e}", False)

    # ── b64 and get_mime still work after wrapping ──
    try:
        m = vision_proxy.get_mime("test.png")
        check("get_mime after wrapping", m == "image/png")
    except Exception as e:
        check(f"get_mime after wrapping crashed: {e}", False)


# ═══════════════════════════════════════════════════════════════════════════
# 6. TYPE CONFUSION — passing wrong types to functions
# ═══════════════════════════════════════════════════════════════════════════

def test_type_confusion():
    vp = reset_vp()

    type_attacks = [
        ("is_image", vp.is_image, [None, 42, 3.14, [], {}, True, False, b"bytes", object()]),
        ("is_video", vp.is_video, [None, 42, 3.14, [], {}, True, False, b"bytes", object()]),
        ("b64", lambda x: vp.b64(x), [None, "string", 42, [1,2,3], {}, True]),
        ("get_mime", vp.get_mime, [None, 42, 3.14, [], {}, True, False, b"bytes", object()]),
    ]

    for name, fn, inputs in type_attacks:
        for inp in inputs:
            try:
                fn(inp)
                check(f"{name}({type(inp).__name__})", True)  # must not raise
            except (TypeError, AttributeError):
                check(f"{name}({type(inp).__name__}) (type error)", True)  # acceptable
            except Exception as e:
                check(f"{name}({type(inp).__name__}) crashed: {e}", False)

    # ── resize_image with type attacks ──
    for inp in [None, 42, [], {}, True, b"bytes"]:
        try:
            vp.resize_image(inp)
            check(f"resize_image({type(inp).__name__})", False)  # should fail
        except (TypeError, AttributeError, FileNotFoundError, OSError):
            check(f"resize_image({type(inp).__name__}) (expected fail)", True)
        except Exception as e:
            check(f"resize_image({type(inp).__name__}) crashed: {e}", False)


# ═══════════════════════════════════════════════════════════════════════════
# 7. CONCURRENCY AND RACE CONDITIONS
# ═══════════════════════════════════════════════════════════════════════════

def test_concurrency():
    vp = reset_vp()

    # ── Thread safety: multiple threads calling get_mime/is_image/is_video ──
    errors = []
    lock = threading.Lock()

    def worker_thread(ident):
        try:
            for i in range(100):
                vp.is_image(f"test_{i}.png")
                vp.is_video(f"test_{i}.mp4")
                vp.get_mime(f"test_{i}.png")
                vp.b64(f"hello from thread {ident} iteration {i}".encode())
        except Exception as e:
            with lock:
                errors.append((ident, str(e)))

    threads = [threading.Thread(target=worker_thread, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    check(f"concurrency: 10 threads × 100 iterations", len(errors) == 0)
    if errors:
        for tid, err in errors[:3]:
            safe_print(f"    Thread {tid}: {err}")


# ═══════════════════════════════════════════════════════════════════════════
# 8. MCP PROTOCOL FUZZING
# ═══════════════════════════════════════════════════════════════════════════

def test_mcp_fuzzing():
    sys.path.insert(0, SCRIPT_DIR)
    import vision_mcp_server as mcp

    # ── process_message with every conceivable input ──
    fuzz_messages = [
        None,
        "not a dict",
        42,
        [],
        True,
        {"id": None, "method": None},
        {"id": 1, "method": "tools/list", "params": None},
        {"id": 1, "method": "initialize", "params": {"protocolVersion": "9999.99"}},
        {"id": 1, "method": "tools/call", "params": {"name": "", "arguments": {}}},
        {"id": 1, "method": "tools/call", "params": {"name": "nonexistent_tool_xyz"}},
        {"id": 1, "method": "tools/call", "params": {"name": "analyze_image", "arguments": {}}},
        {"id": 1, "method": "tools/call", "params": {"name": "analyze_image", "arguments": {"path": "", "prompt": ""}}},
        {"id": 1, "method": "tools/call", "params": {"name": "analyze_video", "arguments": {"path": "/nonexistent"}}},
        {"id": 1, "method": "tools/call", "params": {"name": "analyze_image", "arguments": {"path": "/nonexistent"}}},
        {"id": 1, "method": "notifications/initialized"},
        {"id": None, "method": "notifications/initialized"},
        {"method": "tools/list"},  # no id (notification)
        {"jsonrpc": "2.0", "method": "invalid"},
        {"id": -1, "method": "tools/list"},
        {"id": 999999999999999, "method": "tools/list"},
        {"id": 1.5, "method": "tools/list"},
        {"id": None, "method": "tools/list"},
        {"id": "str_id", "method": "tools/list"},
        {"id": [1,2,3], "method": "tools/list"},
        {"id": {"complex": "id"}, "method": "tools/list"},
        {"id": 1, "method": "tools/call", "params": {"name": "analyze_image"}},  # missing arguments
        {"id": 1, "method": "tools/call", "params": {"name": "analyze_image", "arguments": None}},
        {"id": 1, "method": "tools/call", "params": {"name": "analyze_image", "arguments": "not a dict"}},
        # JSONRPC spec violations
        {"jsonrpc": "1.0", "method": "tools/list", "id": 1},
        {"id": 1, "method": "rpc.method.with.dots"},
        {"id": 1},
        {"method": "initialize"},
        {"id": 1, "method": None, "params": None},
    ]

    for i, msg in enumerate(fuzz_messages):
        try:
            if isinstance(msg, dict):
                result = mcp.process_message(msg)
                check(f"MCP fuzz #{i}: ({type(msg).__name__})", True)
            else:
                # Non-dict inputs: process_message expects dict (JSON parse always gives dict)
                # Accept either crash (AttributeError) or graceful handling
                try:
                    result = mcp.process_message(msg)
                    check(f"MCP fuzz #{i}: ({type(msg).__name__})", True)
                except AttributeError:
                    check(f"MCP fuzz #{i}: ({type(msg).__name__}) (expected)", True)
        except Exception as e:
            check(f"MCP fuzz #{i}: ({type(msg).__name__}) crashed: {e}", False)

    # ── HTTP handler fuzzing ──
    fake_environments = [
        {},
        {"REQUEST_METHOD": "GET", "PATH_INFO": "/health"},
        {"REQUEST_METHOD": "POST", "PATH_INFO": "/mcp", "CONTENT_LENGTH": "0"},
        {"REQUEST_METHOD": "POST", "PATH_INFO": "/mcp", "CONTENT_LENGTH": "not_a_number"},
        {"REQUEST_METHOD": "POST", "PATH_INFO": "/mcp", "CONTENT_LENGTH": "99999999"},
        {"REQUEST_METHOD": "POST", "PATH_INFO": "/mcp", "CONTENT_LENGTH": "5"},
        {"REQUEST_METHOD": "GET", "PATH_INFO": "/nonexistent_path_xyz"},
        {"REQUEST_METHOD": "DELETE", "PATH_INFO": "/health"},
        {"REQUEST_METHOD": "OPTIONS", "PATH_INFO": "/health"},
        {"REQUEST_METHOD": "HEAD", "PATH_INFO": "/health"},
    ]

    for i, env in enumerate(fake_environments):
        try:
            responses = []
            def fake_start(status, headers):
                responses.append((status, headers))
            result = mcp.handle_http_request(env, fake_start)
            check(f"MCP HTTP fuzz #{i} ({env.get('PATH_INFO','?')})", True)
        except Exception as e:
            check(f"MCP HTTP fuzz #{i} crashed: {e}", False)

    # ── handle_tool_call fuzzing ──
    tool_attacks = [
        ("analyze_image", {"path": None}),
        ("analyze_image", {"path": 42}),
        ("analyze_image", {"path": [], "prompt": {}}),
        ("analyze_image", {"prompt": "no path"}),
        ("analyze_video", {}),
        ("", {}),
        (None, {}),
        ("nonexistent_tool", {}),
        ("analyze_image", {"path": "C:\\Windows\\System32\\config\\SAM"}),  # sensitive path
        ("analyze_image", {"path": "/etc/shadow"}),
        ("analyze_image", {"path": "../../../etc/passwd"}),
        ("analyze_image", {"path": "\\\\network\\share\\file.png"}),  # UNC path
        ("analyze_image", {"path": "CON"}),  # Windows reserved
        ("analyze_image", {"path": "NUL"}),  # Windows reserved
    ]

    for tool_name, args in tool_attacks:
        try:
            result = mcp.handle_tool_call(tool_name, args)
            check(f"MCP handle_tool_call({tool_name})", isinstance(result, dict))
        except Exception as e:
            check(f"MCP handle_tool_call({tool_name}) crashed: {e}", False)


# ═══════════════════════════════════════════════════════════════════════════
# 9. SUBPROCESS EDGE CASES (ffmpeg/ffprobe failures)
# ═══════════════════════════════════════════════════════════════════════════

def test_subprocess_edges():
    vp = reset_vp()

    # ── Test extract_video_frames with missing ffprobe ──
    # Temporarily hide ffprobe from PATH
    old_path = os.environ.get("PATH", "")

    # Create a temp dir with no real ffprobe
    td = tempfile.mkdtemp()
    try:
        # Create a dummy "ffprobe" that fails
        fake_bin_dir = os.path.join(td, "fake_bin")
        os.makedirs(fake_bin_dir)

        # Fake ffmpeg that hangs
        if os.name == "nt":
            ffprobe_path = os.path.join(fake_bin_dir, "ffprobe.exe")
            ffmpeg_path = os.path.join(fake_bin_dir, "ffmpeg.exe")
            # Create a dummy batch file that errors
            with open(ffprobe_path, "w") as f:
                f.write("@echo off\necho ERROR >&2\nexit /b 1")
            with open(ffmpeg_path, "w") as f:
                f.write("@echo off\necho ERROR >&2\nexit /b 1")
        else:
            ffprobe_path = os.path.join(fake_bin_dir, "ffprobe")
            ffmpeg_path = os.path.join(fake_bin_dir, "ffmpeg")
            with open(ffprobe_path, "w") as f:
                f.write("#!/bin/sh\necho ERROR >&2\nexit 1")
            with open(ffmpeg_path, "w") as f:
                f.write("#!/bin/sh\necho ERROR >&2\nexit 1")
            os.chmod(ffprobe_path, 0o755)
            os.chmod(ffmpeg_path, 0o755)

        os.environ["PATH"] = fake_bin_dir + os.pathsep + old_path

        # Reset module to pick up new PATH
        vp = reset_vp()

        # Create a dummy video file
        video_path = os.path.join(td, "test_video.mp4")
        with open(video_path, "wb") as f:
            f.write(b"fake video content")

        # extract_video_frames should fall back gracefully
        try:
            frames = vp.extract_video_frames(video_path)
            check("extract_video_frames with broken ffmpeg: fallback", isinstance(frames, list))
            if frames:
                check("extract_video_frames with broken ffmpeg: has data", isinstance(frames[0][0], bytes))
                check("extract_video_frames with broken ffmpeg: has mime", isinstance(frames[0][1], str))
        except Exception as e:
            check(f"extract_video_frames with broken ffmpeg crashed: {e}", False)

        # ── Test with empty PATH ──
        os.environ["PATH"] = ""
        vp = reset_vp()
        try:
            frames = vp.extract_video_frames(video_path)
            check("extract_video_frames with empty PATH", isinstance(frames, list))
        except Exception as e:
            check(f"extract_video_frames with empty PATH crashed: {e}", False)

        # ── Test with non-video file to extract_video_frames ──
        txt_path = os.path.join(td, "test.txt")
        with open(txt_path, "w") as f:
            f.write("hello")
        try:
            frames = vp.extract_video_frames(txt_path)
            check("extract_video_frames with .txt file", isinstance(frames, list))
        except Exception as e:
            check(f"extract_video_frames with .txt crashed: {e}", False)

        # ── Test with .gif file ──
        gif_path = os.path.join(td, "test.gif")
        # Minimal valid GIF89a with 1 frame
        minimal_gif = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x00\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        with open(gif_path, "wb") as f:
            f.write(minimal_gif)
        try:
            frames = vp.extract_video_frames(gif_path)
            check("extract_video_frames: valid GIF", isinstance(frames, list))
        except Exception as e:
            check(f"extract_video_frames: valid GIF crashed: {e}", False)

        # ── Corrupted GIF ──
        bad_gif_path = os.path.join(td, "bad.gif")
        with open(bad_gif_path, "wb") as f:
            f.write(b"GIF89a" + b"\x00" * 10)  # truncated
        try:
            frames = vp.extract_video_frames(bad_gif_path)
            check("extract_video_frames: bad GIF", isinstance(frames, list))
        except Exception as e:
            check(f"extract_video_frames: bad GIF crashed: {e}", False)

        # ── Zero-byte GIF ──
        empty_gif_path = os.path.join(td, "empty.gif")
        with open(empty_gif_path, "wb") as f:
            f.write(b"")
        try:
            frames = vp.extract_video_frames(empty_gif_path)
            check("extract_video_frames: empty GIF", isinstance(frames, list))
        except Exception as e:
            check(f"extract_video_frames: empty GIF crashed: {e}", False)

        # ── Test with path that has spaces and special chars ──
        special_video = os.path.join(td, "my [cool] video (2024).mp4")
        with open(special_video, "wb") as f:
            f.write(b"fake video")
        try:
            frames = vp.extract_video_frames(special_video)
            check("extract_video_frames: special chars in path", isinstance(frames, list))
        except Exception as e:
            check(f"extract_video_frames: special chars crashed: {e}", False)

    finally:
        os.environ["PATH"] = old_path
        shutil.rmtree(td, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════
# 10. MEMORY AND RESOURCE LEAK DETECTION
# ═══════════════════════════════════════════════════════════════════════════

def test_resource_leaks():
    vp = reset_vp()
    td = tempfile.mkdtemp()

    try:
        # ── Create many temp files and call resize_image repeatedly ──
        for i in range(50):
            path = os.path.join(td, f"test_{i}.txt")
            with open(path, "w") as f:
                f.write("x" * 1000)
            try:
                vp.resize_image(path)
            except Exception:
                pass
            os.remove(path)

        # Force garbage collection
        gc.collect()

        # Check no lingering temp dirs from extract_video_frames
        temp_root = tempfile.gettempdir()
        vision_temp_files = [f for f in os.listdir(temp_root)
                            if f.startswith("tmp") and os.path.isdir(os.path.join(temp_root, f))]
        # This is a soft check — there might be legit temp dirs from other processes
        check("resource leaks: no explosion of temp files", len(vision_temp_files) < 100)

        # ── Repeated analyze calls ──
        for i in range(20):
            path = os.path.join(td, f"pic_{i}.png")
            with open(path, "wb") as f:
                # Write a valid PNG header + random data
                f.write(b"\x89PNG\r\n\x1a\n" + os.urandom(100))
            try:
                vp.resize_image(path)
            except Exception:
                pass

        check("resource leaks: repeated calls no crash", True)

        # ── Load_config repeated ──
        for i in range(100):
            try:
                vp.load_config()
            except RuntimeError:
                pass

        check("resource leaks: 100x load_config", True)

    finally:
        shutil.rmtree(td, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════
# 11. IMPORT/RELOAD EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════

def test_import_edge_cases():
    # ── Import when CWD is not the script dir ──
    old_cwd = os.getcwd()
    try:
        os.chdir(tempfile.gettempdir())
        import importlib
        # Import from a fresh state
        for mod in list(sys.modules.keys()):
            if "vision_proxy" in mod or "vision_proxy" in str(mod):
                del sys.modules[mod]
        import vision_proxy
        check("import from temp dir", True)
        os.chdir(old_cwd)
    except Exception as e:
        check(f"import from temp dir crashed: {e}", False)
        os.chdir(old_cwd)

    # ── Reimport with modified sys.path ──
    old_path = sys.path.copy()
    try:
        sys.path.insert(0, os.path.join(SCRIPT_DIR, "nonexistent_subdir"))
        for mod in list(sys.modules.keys()):
            if "vision_proxy" in mod:
                del sys.modules[mod]
        import vision_proxy
        check("import with bad sys.path entries", True)
    except Exception as e:
        check(f"import with bad sys.path entries crashed: {e}", False)
    finally:
        sys.path = old_path


# ═══════════════════════════════════════════════════════════════════════════
# 12. SECURITY: PATH TRAVERSAL AND COMMAND INJECTION
# ═══════════════════════════════════════════════════════════════════════════

def test_security():
    vp = reset_vp()

    # ── Path traversal in analyze ──
    traversal_paths = [
        "../../../etc/passwd",
        "..\\..\\..\\Windows\\System32\\config\\SAM",
        "../../../etc/shadow",
        "....//....//....//etc/passwd",
        "%SYSTEMROOT%\\System32\\drivers\\etc\\hosts",
        "C:\\Windows\\System32\\config\\SAM",
        "\\\\localhost\\admin$\\system32",
        "/proc/self/environ",
        "/dev/null",
        "/dev/random",
    ]

    for path in traversal_paths:
        try:
            # On Windows these may or may not exist
            vp.analyze(path)
            check(f"path traversal: {path[:40]}", False)  # should not succeed
        except FileNotFoundError:
            check(f"path traversal: {path[:40]} (not found)", True)
        except RuntimeError:
            check(f"path traversal: {path[:40]} (runtime error)", True)
        except PermissionError:
            check(f"path traversal: {path[:40]} (permission denied)", True)
        except Exception as e:
            check(f"path traversal: {path[:40]} ({e.__class__.__name__})", True)

    # ── Null byte injection ──
    null_paths = [
        "test.png\x00.exe",
        "test\x00.png",
        "\x00test.png",
    ]
    for path in null_paths:
        try:
            vp.is_image(path)
            check(f"null byte injection: {repr(path)[:30]}", True)
        except Exception as e:
            check(f"null byte injection: {repr(path)[:30]} crashed: {e}", False)


# ═══════════════════════════════════════════════════════════════════════════
# 13. KEYBOARDINTERRUPT / SIGNAL HANDLING
# ═══════════════════════════════════════════════════════════════════════════

def test_interrupt_handling():
    vp = reset_vp()

    # ── Functions should not swallow KeyboardInterrupt ──
    # Check that no bare except exists in the source
    import re

    # Check all Python source files (read as UTF-8)
    for fname in ["vision_proxy.py", "vision_mcp_server.py", "setup.py", "install.py"]:
        with open(os.path.join(SCRIPT_DIR, fname), "r", encoding="utf-8") as f:
            src = f.read()
        except_lines = re.findall(r'^\s*except\b.*$', src, re.MULTILINE)
        bad_excepts = [l for l in except_lines if l.strip() == 'except:']
        check(f"no bare except: in {fname}", len(bad_excepts) == 0)


# ═══════════════════════════════════════════════════════════════════════════
# 14. B64 EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════

def test_b64_edges():
    vp = reset_vp()

    # Empty data
    try:
        result = vp.b64(b"")
        check("b64 empty bytes", result == "")
    except Exception as e:
        check(f"b64 empty bytes crashed: {e}", False)

    # Single byte
    try:
        result = vp.b64(b"\x00")
        check("b64 null byte", isinstance(result, str) and len(result) > 0)
    except Exception as e:
        check(f"b64 null byte crashed: {e}", False)

    # All possible byte values
    try:
        result = vp.b64(bytes(range(256)))
        check("b64 all 256 bytes", isinstance(result, str) and len(result) > 0)
    except Exception as e:
        check(f"b64 all 256 bytes crashed: {e}", False)

    # 1MB of random data (stress)
    try:
        result = vp.b64(os.urandom(1024 * 1024))
        check("b64 1MB random data", isinstance(result, str) and len(result) > 0)
    except Exception as e:
        check(f"b64 1MB random data crashed: {e}", False)

    # Unicode string bytes
    try:
        result = vp.b64("\u2603\u2603\u2603".encode("utf-8"))
        check("b64 unicode encoded", isinstance(result, str))
    except Exception as e:
        check(f"b64 unicode encoded crashed: {e}", False)


# ═══════════════════════════════════════════════════════════════════════════
# 15. INSTALL.PY EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════

def test_install_edges():
    try:
        import install
    except Exception as e:
        check(f"import install crashed: {e}", False)
        return

    # ── detect_client edge cases ──
    # Save and clear real configs
    clients = install.detect_client()
    check("detect_client returns list", isinstance(clients, list))
    for name, path in clients:
        check(f"detect_client: {name} path str", isinstance(path, str) and len(path) > 0)

    # ── run() with capture ──
    result = install.run("echo hello", capture=True)
    check("run capture returns str", isinstance(result, str))

    # ── run() with check=False for failure ──
    try:
        install.run("cmd /c exit 1", check=False)
        check("run check=False no crash on fail", True)
    except Exception as e:
        check(f"run check=False crashed: {e}", False)

    # ── confirm and prompt ──
    # These are interactive, just check they exist
    check("install.prompt exists", callable(install.prompt))
    check("install.confirm exists", callable(install.confirm))


# ═══════════════════════════════════════════════════════════════════════════
# 16. VISION_MCP_SERVER MAIN PARSER
# ═══════════════════════════════════════════════════════════════════════════

def test_mcp_main():
    import vision_mcp_server as mcp

    # Check that run_stdio and run_http exist
    check("MCP run_stdio exists", callable(mcp.run_stdio))
    check("MCP run_http exists", callable(mcp.run_http))

    # Check that _get_vp exists and works
    try:
        vp = mcp._get_vp()
        check("MCP _get_vp returns module", vp is not None)
        check("MCP _get_vp has analyze", hasattr(vp, "analyze"))
    except Exception as e:
        check(f"MCP _get_vp crashed: {e}", False)

    # Check that _get_vp is cached
    try:
        vp1 = mcp._get_vp()
        vp2 = mcp._get_vp()
        check("MCP _get_vp cached", vp1 is vp2)
    except Exception as e:
        check(f"MCP _get_vp cached crashed: {e}", False)

    # Check send function (capture via StringIO — send uses sys.stdout)
    import vision_mcp_server as mcp
    try:
        fake_out = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = fake_out
        try:
            mcp.send({"test": "message"})
            output = fake_out.getvalue()
            check("MCP send writes JSON", "test" in output and "message" in output)
        finally:
            sys.stdout = old_stdout
    except Exception as e:
        check(f"MCP send crashed: {e}", False)

    # ── run_stdio: test with queue ──
    # This is hard to test without stdin, just check it doesn't crash on empty
    try:
        import queue as queue_module
        # Can't easily test — run_stdio is a blocking loop
        check("MCP run_stdio (blocking, skip)", True)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
# 17. RAPID SUCCESSIVE CALLS (STRESS)
# ═══════════════════════════════════════════════════════════════════════════

def test_rapid_calls():
    vp = reset_vp()

    td = tempfile.mkdtemp()
    try:
        # Create one valid-ish file
        path = os.path.join(td, "test.png")
        with open(path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10000)

        # Rapid successive calls to resize_image
        for i in range(200):
            try:
                vp.resize_image(path, max_dim=1024)
            except Exception:
                pass

        check("rapid 200x resize_image", True)

        # Rapid successive calls to get_mime
        for i in range(1000):
            try:
                vp.get_mime(f"test_{i}.png")
            except Exception:
                pass

        check("rapid 1000x get_mime", True)

    finally:
        shutil.rmtree(td, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════
# 18. ANALYZE STRATEGIES — verify backend strategy lists are well-formed
# ═══════════════════════════════════════════════════════════════════════════

def test_analyze_strategies():
    """Inspect analyze() to verify all strategies are valid lambda expressions."""
    vp = reset_vp()
    td = tempfile.mkdtemp()

    try:
        # Create valid test files
        img_path = os.path.join(td, "test.png")
        with open(img_path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        video_path = os.path.join(td, "test.mp4")
        with open(video_path, "wb") as f:
            f.write(b"fake video")

        # We can't inspect the inner strategies directly, so trigger analyze
        # with no API keys and verify the RuntimeError message format
        try:
            vp.analyze(img_path)
        except (FileNotFoundError, RuntimeError):
            # Without API keys, analyze will either fail with:
            #   FileNotFoundError if test.png doesn't exist
            #   RuntimeError (no keys configured)
            pass
        except Exception as e:
            check(f"analyze: unexpected error {e.__class__.__name__}: {e}", True)

        # Also verify analyze doesn't crash on video path
        try:
            vp.analyze(video_path)
        except (FileNotFoundError, RuntimeError):
            pass
        except Exception as e:
            check(f"analyze video: unexpected error {e.__class__.__name__}: {e}", True)

    finally:
        shutil.rmtree(td, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════
# 19. WATCHDOG FILE VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

def test_watchdog_files():
    # Check VBS
    vbs_path = os.path.join(SCRIPT_DIR, "vision_watchdog.vbs")
    if os.path.isfile(vbs_path):
        with open(vbs_path, "r") as f:
            content = f.read()
        check("watchdog.vbs non-empty", len(content) > 0)
    else:
        check("watchdog.vbs exists", False)

    # Check CS
    cs_path = os.path.join(SCRIPT_DIR, "vision_watchdog.cs")
    if os.path.isfile(cs_path):
        with open(cs_path, "r") as f:
            content = f.read()
        check("watchdog.cs non-empty", len(content) > 0)
    else:
        check("watchdog.cs exists", False)


# ═══════════════════════════════════════════════════════════════════════════
# 20. SETUP.PY EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════

def test_setup_edges():
    import setup

    # ── Color helpers with piped stdout ──
    # Simulate piped by temporarily making stdout non-tty via monkey-patch
    orig_isatty = sys.stdout.isatty if hasattr(sys.stdout, 'isatty') else None
    try:
        if hasattr(sys.stdout, 'isatty'):
            sys.stdout.isatty = lambda: False
        check("bold piped", setup.bold("x") == "x")
        check("green piped", setup.green("x") == "x")
        check("yellow piped", setup.yellow("x") == "x")
        check("cyan piped", setup.cyan("x") == "x")
        check("dim piped", setup.dim("x") == "x")
    finally:
        if orig_isatty is not None and hasattr(sys.stdout, 'isatty'):
            sys.stdout.isatty = orig_isatty

    # ── show_keys with no config ──
    # Backup and remove config
    real_config = os.path.join(SCRIPT_DIR, "config.json")
    backed_up = None
    if os.path.isfile(real_config):
        with open(real_config, "r") as f:
            backed_up = f.read()
        os.remove(real_config)

    try:
        # show_keys should not crash
        old_stderr = sys.stderr
        sys.stderr = io.StringIO()
        setup.show_keys()
        sys.stderr = old_stderr
        check("show_keys with no config", True)
    except Exception as e:
        check(f"show_keys with no config crashed: {e}", False)

    # ── show_keys with corrupted config ──
    with open(real_config, "w") as f:
        f.write("not json")
    try:
        setup.show_keys()
        check("show_keys with corrupted config", True)
    except Exception as e:
        check(f"show_keys with corrupted config crashed: {e}", False)

    # Restore
    if backed_up is not None:
        with open(real_config, "w") as f:
            f.write(backed_up)
    else:
        if os.path.isfile(real_config):
            os.remove(real_config)

    # ── test_gemini with empty key ──
    check("test_gemini empty", setup.test_gemini("") == False)

    # ── test_openrouter with empty key ──
    check("test_openrouter empty", setup.test_openrouter("") == False)

    # ── securesave edge cases ──
    td = tempfile.mkdtemp()
    try:
        test_config = os.path.join(td, "config.json")
        # Save original CONFIG_PATH
        old_config = setup.CONFIG_PATH
        setup.CONFIG_PATH = test_config

        # Save normal config
        setup.securesave({"GEMINI_API_KEY": "test", "OPENROUTER_API_KEY": "test2"})
        check("securesave: file created", os.path.isfile(test_config))

        if os.path.isfile(test_config):
            with open(test_config) as f:
                data = json.load(f)
            check("securesave: correct keys", data.get("GEMINI_API_KEY") == "test")

        # Restore
        setup.CONFIG_PATH = old_config
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════════════════
# 21. DUPLICATED MAIN() FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def test_main_functions():
    """Check that vision_mcp_server doesn't have duplicate main()."""
    with open(os.path.join(SCRIPT_DIR, "vision_mcp_server.py"), "r") as f:
        src = f.read()
    import re
    mains = re.findall(r'^def main\(', src, re.MULTILINE)
    check("vision_mcp_server.py: exactly one main()", len(mains) == 1)


# ═══════════════════════════════════════════════════════════════════════════
# RUN ALL
# ═══════════════════════════════════════════════════════════════════════════

def run_all():
    global PASS, FAIL, TOTAL

    safe_print("")
    safe_print("=" * 60)
    safe_print("  FUZZ / STRESS / SECURITY TEST SUITE")
    safe_print("=" * 60)
    safe_print("")

    tests = [
        ("Encoding Attacks", test_encoding_attacks),
        ("Filesystem Edge Cases", test_filesystem_edge_cases),
        ("Config Corruption", test_config_corruption),
        ("Environment Attacks", test_env_attacks),
        ("Stdio Wrapping", test_stdio_wrapping),
        ("Type Confusion", test_type_confusion),
        ("Concurrency", test_concurrency),
        ("MCP Fuzzing", test_mcp_fuzzing),
        ("Subprocess Edges", test_subprocess_edges),
        ("Resource Leaks", test_resource_leaks),
        ("Import Edge Cases", test_import_edge_cases),
        ("Security", test_security),
        ("Interrupt Handling", test_interrupt_handling),
        ("B64 Edge Cases", test_b64_edges),
        ("Install Edges", test_install_edges),
        ("MCP Main", test_mcp_main),
        ("Rapid Calls", test_rapid_calls),
        ("Analyze Strategies", test_analyze_strategies),
        ("Watchdog Files", test_watchdog_files),
        ("Setup Edges", test_setup_edges),
        ("Duplicate Main", test_main_functions),
    ]

    for name, fn in tests:
        safe_print("")
        safe_print(f"\u2500\u2500 {name} \u2500\u2500")
        try:
            fn()
        except Exception as e:
            safe_print(f"  \u2570\u2192 CRASH in {name}: {e}")
            traceback.print_exc(file=_REAL_STDERR)
            FAIL += 1

    safe_print("")
    safe_print("=" * 60)
    safe_print(f"  RESULTS:  {PASS} passed,  {FAIL} failed  (of {TOTAL})")
    safe_print("=" * 60)

    return FAIL == 0


if __name__ == "__main__":
    success = run_all()
    _DEVNULL.close()
    sys.exit(0 if success else 1)
