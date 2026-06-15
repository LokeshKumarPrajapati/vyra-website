from kasa_agent import KasaAgent
from mood_music_mapper import mood_sync as run_mood_sync
from spotify_agent import SpotifyAgent, SpotifyPremiumRequired, SpotifyNoActiveDevice
from fastapi import HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import FileResponse, StreamingResponse
import uuid
import signal
from fastapi.middleware.cors import CORSMiddleware
from vcf_parser import parse_vcf_file
from contact_manager import ContactManager
from file_upload_utils import parse_file, validate_file, get_file_summary
from user_memory import UserMemory
from google.genai import types as genai_types
from google import genai
import vyra
import sys
import asyncio

# Fix for asyncio subprocess support on Windows
# MUST BE SET BEFORE OTHER IMPORTS
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# GPU + CPU resource allocation — must run before torch/ML imports load models
import gpu_config  # noqa: E402  (intentional early import)
_cuda_ready = gpu_config.CUDA_AVAILABLE  # touches the module so Pylance is happy

import socketio
import uvicorn
from fastapi import FastAPI, Body
import asyncio
import sys
import os
import json
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel
from typing import List, Optional, Dict
import time
from dotenv import load_dotenv

# Let dotenv find the nearest .env file (stops at workspace root)
load_dotenv()

# Ensure we can import vyra
sys.path.append(os.path.dirname(os.path.abspath(__file__)))


# Initialize Gemini Client for API Endpoint
# Using the same API key as vyra
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
api_client = None
if GEMINI_API_KEY:
    try:
        api_client = genai.Client(
            http_options={"api_version": "v1beta"}, api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"[SERVER] Failed to initialize Gemini API Client: {e}")

# OpenAI Compatibility Models


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "vyra"
    messages: List[ChatMessage]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None
    stream: Optional[bool] = False


class ChatCompletionResponseChoice(BaseModel):
    index: int
    message: ChatMessage
    finish_reason: str


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatCompletionResponseChoice]
    usage: Dict[str, int]


# Create a Socket.IO server with extended timeout settings (reduces "lost connection" during model reconnects)
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins='*',
    ping_timeout=180000,  # 3 minutes - allow model/Gemini reconnects without dropping socket
    ping_interval=20000,  # 20 seconds - keep connection alive
    max_http_buffer_size=10000000  # 10MB - for large video frames
)
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Cursor Intelligence routes ────────────────────────────────────────────────
try:
    from actions.cursor_intelligence import router as cursor_router
    app.include_router(cursor_router)
    print("[Server] Cursor Intelligence routes registered at /cursor/*")
except Exception as _ce:
    print(f"[Server] Cursor Intelligence not loaded: {_ce}")

# ── Serve jarvis/ui/dist as static files (dashboard) ──────────────────────────
_BACKEND_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
_UI_DIST = _BACKEND_DIR.parent / "jarvis" / "ui" / "dist"

if _UI_DIST.exists():
    from fastapi.staticfiles import StaticFiles as _StaticFiles
    # Serve assets (JS/CSS/fonts) from the dist directory
    app.mount("/assets", _StaticFiles(directory=str(_UI_DIST / "assets")), name="assets") if (_UI_DIST / "assets").exists() else None

    @app.get("/")
    async def serve_dashboard_root():
        """Serve the jarvis/ui SPA."""
        return FileResponse(str(_UI_DIST / "index.html"))

    @app.get("/dashboard")
    @app.get("/workflows")
    @app.get("/goals")
    @app.get("/tasks")
    @app.get("/settings")
    @app.get("/memory")
    @app.get("/office")
    @app.get("/authority")
    @app.get("/calendar")
    @app.get("/pipeline")
    @app.get("/command")
    @app.get("/awareness")
    @app.get("/knowledge")
    async def serve_dashboard_spa():
        """Catch-all for SPA client-side routes."""
        return FileResponse(str(_UI_DIST / "index.html"))

app_socketio = socketio.ASGIApp(sio, app)

# ── Plain WebSocket manager (used by useWebSocket.ts in the frontend) ──────────
# The frontend connects to /ws as a plain JSON WebSocket (not SocketIO protocol).
# We bridge workflow_event, goal_event, and status messages here.

class _WSManager:
    """Manages plain WebSocket connections from the React frontend."""
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, msg: dict):
        import json
        data = json.dumps(msg)
        dead = []
        for ws in list(self.active):
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


_ws_manager = _WSManager()

# ── Windows Tool Event Store & Broadcast ─────────────────────────────────────
_win_events: list[dict] = []   # ring buffer, last 500 events
_win_stats: dict = {}          # tool_name → {calls, errors, last_ts}

async def _broadcast_win_event(event: dict):
    """Store and broadcast a win_tool_event to all dashboard clients."""
    global _win_events, _win_stats
    _win_events = ([*_win_events, event])[-500:]
    tool = event.get("tool", "unknown")
    if tool not in _win_stats:
        _win_stats[tool] = {"calls": 0, "errors": 0, "last_ts": 0}
    _win_stats[tool]["calls"] += 1
    if event.get("status") == "error":
        _win_stats[tool]["errors"] += 1
    _win_stats[tool]["last_ts"] = event.get("timestamp", 0)
    # Emit to Socket.IO and plain WS
    await sio.emit("win_tool_event", event)
    await _ws_manager.broadcast({
        "type": "win_tool_event",
        "payload": event,
        "timestamp": event.get("timestamp", time.time() * 1000),
    })

# Register callback in vyra module so it can fire events
try:
    import vyra as _vyra_mod
    _vyra_mod.win_event_broadcast_callback = _broadcast_win_event
    print("[SERVER] ✅ win_event_broadcast_callback registered in vyra.")
except Exception as _e:
    print(f"[SERVER] ⚠️  Could not register win_event_broadcast_callback: {_e}")

# ── Live Terminal Log ─────────────────────────────────────────────────────────
# Ring-buffer storing the last 500 terminal lines (tool calls, shell output, Vyra activity)
_terminal_log: list[dict] = []   # {id, type, text, ts, source}

def _terminal_push(text: str, source: str = "system", line_type: str = "output"):
    """Append a line to the shared terminal log and broadcast to all WS clients."""
    import time as _t
    entry = {
        "id": str(_t.time() * 1000),
        "type": line_type,   # "output" | "error" | "info" | "tool"
        "text": text,
        "ts": _t.time() * 1000,
        "source": source,
    }
    global _terminal_log
    _terminal_log = (_terminal_log + [entry])[-500:]
    # Non-blocking broadcast to WS clients
    import asyncio as _asyncio
    try:
        loop = _asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_ws_manager.broadcast({
                "type": "terminal_output",
                "payload": entry,
                "timestamp": entry["ts"],
            }))
    except Exception:
        pass

# Register so vyra can push terminal lines
try:
    import vyra as _vyra_mod2
    _vyra_mod2.terminal_push_callback = _terminal_push
    print("[SERVER] ✅ terminal_push_callback registered in vyra.")
except Exception as _e2:
    print(f"[SERVER] ⚠️  Could not register terminal_push_callback: {_e2}")

@app.get("/api/vyra/terminal/history")
async def terminal_history(limit: int = 200):
    """Return last N terminal log lines."""
    return {"lines": _terminal_log[-limit:]}

class TerminalRunRequest(BaseModel):
    command: str
    cwd: Optional[str] = None

@app.post("/api/vyra/terminal/run")
async def terminal_run_sse(request: TerminalRunRequest):
    """
    Execute a shell command and stream its stdout/stderr as SSE events.
    Each line is also pushed to the shared terminal log so Vyra can read it.
    """
    import asyncio as _aio
    import subprocess as _sp
    import shlex

    cmd = request.command.strip()
    cwd = request.cwd or os.getcwd()

    _terminal_push(f"$ {cmd}", source="user", line_type="info")

    async def stream_gen():
        try:
            proc = await _aio.create_subprocess_shell(
                cmd,
                stdout=_sp.PIPE,
                stderr=_sp.STDOUT,
                cwd=cwd,
            )
            while True:
                line_bytes = await proc.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").rstrip()
                _terminal_push(line, source="shell", line_type="output")
                payload = json.dumps({"type": "output", "text": line, "ts": time.time() * 1000})
                yield f"data: {payload}\n\n"
            rc = await proc.wait()
            done = json.dumps({"type": "done", "exit_code": rc, "ts": time.time() * 1000})
            _terminal_push(f"[exit {rc}]", source="shell", line_type="info")
            yield f"data: {done}\n\n"
        except Exception as exc:
            err = json.dumps({"type": "error", "text": str(exc), "ts": time.time() * 1000})
            _terminal_push(str(exc), source="shell", line_type="error")
            yield f"data: {err}\n\n"

    return StreamingResponse(
        stream_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )

class TerminalAnalyzeRequest(BaseModel):
    context: Optional[str] = ""   # Extra context from user
    lines: Optional[int] = 100    # How many recent lines to send to Vyra

@app.post("/api/vyra/terminal/analyze")
async def terminal_analyze(request: TerminalAnalyzeRequest):
    """
    Send the last N terminal lines to Vyra/Gemini for analysis.
    Vyra will identify errors, suggest fixes, and return a structured response.
    """
    recent = _terminal_log[-(request.lines or 100):]
    log_text = "\n".join(f"[{e['source']}] {e['text']}" for e in recent)

    prompt = f"""You are VYRA, an intelligent AI assistant analyzing live terminal output.

Terminal Output (last {len(recent)} lines):
```
{log_text}
```

{f'User context: {request.context}' if request.context else ''}

Analyze this terminal output:
1. Identify any errors or warnings
2. Explain what Vyra was doing
3. Suggest specific fixes if there are errors
4. Rate the current status: SUCCESS / IN_PROGRESS / ERROR / WARNING

Respond in JSON format:
{{
  "status": "SUCCESS|IN_PROGRESS|ERROR|WARNING",
  "summary": "Brief 1-line summary",
  "errors": ["list of errors found"],
  "fixes": ["specific fix suggestions"],
  "explanation": "Detailed explanation"
}}"""

    if api_client:
        try:
            response = api_client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=[{"role": "user", "parts": [{"text": prompt}]}]
            )
            text = response.text if hasattr(response, 'text') else str(response)
            # Try to parse JSON
            import re as _re
            json_match = _re.search(r'\{.*\}', text, _re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group())
                    return {"ok": True, "analysis": parsed, "raw": text}
                except Exception:
                    pass
            return {"ok": True, "analysis": {"status": "INFO", "summary": text, "errors": [], "fixes": [], "explanation": text}, "raw": text}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    else:
        return {"ok": False, "error": "Vyra API client not configured"}



@app.get("/api/win/events")
async def api_win_events(limit: int = 100):
    """Return recent Windows tool events for the dashboard."""
    return {"events": _win_events[-limit:], "stats": _win_stats}

@app.post("/api/win/event")
async def api_win_event_post(body: dict = Body(...)):
    """Manually push a win tool event (e.g. from CLI testing)."""
    await _broadcast_win_event(body)
    return {"ok": True}

@app.get("/api/win/stats")
async def api_win_stats():
    """Aggregated per-tool call/error stats."""
    return {"stats": _win_stats, "total_events": len(_win_events)}

@app.post("/api/win/run")
async def api_win_run(body: dict = Body(...)):
    """
    Execute a Windows tool directly from the dashboard Quick Run panel.
    Body: { tool: str, action: str, ...extra_params }
    Runs synchronously in a thread and returns the result.
    """
    tool_name = body.get("tool", "")
    if not tool_name:
        return {"status": "error", "output": "Missing 'tool' field."}

    # Build the args dict the win_* modules expect
    args = {k: v for k, v in body.items() if k != "tool"}

    # Resolve the function from vyra module
    try:
        import vyra as _vyra_run
        fn = None
        for attr in (f"_{tool_name}", tool_name):
            fn = getattr(_vyra_run, attr, None)
            if callable(fn):
                break
        if fn is None:
            return {"status": "error", "output": f"Tool '{tool_name}' not found in vyra module."}
    except Exception as e:
        return {"status": "error", "output": str(e)}

    ts = time.time() * 1000
    # Broadcast "running" event
    await _broadcast_win_event({
        "id": str(ts),
        "tool": tool_name,
        "action": args.get("action", ""),
        "args": {k: v for k, v in args.items() if k not in ("password", "confirmed")},
        "status": "running",
        "result": None,
        "timestamp": ts,
    })

    try:
        import asyncio as _aio, json as _json
        result_raw = await _aio.to_thread(fn, args, None, None, None)
        try:
            parsed = _json.loads(result_raw) if isinstance(result_raw, str) else result_raw
        except Exception:
            parsed = {"status": "ok", "output": str(result_raw)[:2000]}

        await _broadcast_win_event({
            "id": str(time.time() * 1000),
            "tool": tool_name,
            "action": args.get("action", ""),
            "args": {k: v for k, v in args.items() if k not in ("password", "confirmed")},
            "status": parsed.get("status", "ok") if isinstance(parsed, dict) else "ok",
            "result": parsed.get("output", str(parsed)[:500]) if isinstance(parsed, dict) else str(parsed)[:500],
            "timestamp": time.time() * 1000,
        })
        return parsed
    except Exception as e:
        err = str(e)
        await _broadcast_win_event({
            "id": str(time.time() * 1000),
            "tool": tool_name,
            "action": args.get("action", ""),
            "args": {},
            "status": "error",
            "result": err[:300],
            "timestamp": time.time() * 1000,
        })
        return {"status": "error", "output": err}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Plain WebSocket endpoint consumed by the React frontend's useWebSocket hook."""
    await _ws_manager.connect(websocket)
    import time
    try:
        while True:
            # The frontend may send JSON (user chat) or Binary (microphone PCM/WebM audio)
            message = await websocket.receive()
            
            if "text" in message:
                raw = message["text"]
                try:
                    import json as _json
                    msg = _json.loads(raw)
                    
                    # Handle text chat from dashboard
                    if msg.get("type") == "chat" and msg.get("payload", {}).get("text"):
                        text = msg["payload"]["text"]
                        
                        # 1. Forward to Voice if active
                        if audio_loop and audio_loop.session:
                            try:
                                await audio_loop.session.send(input=text, end_of_turn=True)
                                continue # Let audio loop handle response
                            except Exception as ex:
                                print(f"[WS] Failed to forward chat to Vyra Voice: {ex}")
                                
                        # 2. Fallback: Process using text-based Gemini API immediately
                        if api_client:
                            try:
                                # Use generate_content_stream for a streaming "typing" effect
                                system_instruction = "You are J.A.R.V.I.S., a highly intelligent, concise, and helpful AI assistant managing this system dashboard."
                                response_stream = api_client.models.generate_content_stream(
                                    model="gemini-2.0-flash-exp",
                                    contents=[
                                        {"role": "user", "parts": [{"text": system_instruction + "\n\nUser: " + text}]}
                                    ]
                                )
                                for chunk in response_stream:
                                    if chunk.text:
                                        stream_msg = {
                                            "type": "stream",
                                            "payload": {"text": chunk.text, "source": "assistant"},
                                            "timestamp": int(time.time() * 1000)
                                        }
                                        await websocket.send_text(_json.dumps(stream_msg))
                                        
                                # Send 'done' status
                                await websocket.send_text(_json.dumps({
                                    "type": "status",
                                    "payload": {"status": "done"},
                                    "timestamp": int(time.time() * 1000)
                                }))
                            except Exception as ex:
                                print(f"[WS] Gemini text API error: {ex}")
                                await websocket.send_text(_json.dumps({
                                    "type": "error",
                                    "payload": {"message": f"Vyra AI Error: {ex}"},
                                    "timestamp": int(time.time() * 1000)
                                }))
                        else:
                            await websocket.send_text(_json.dumps({
                                "type": "error",
                                "payload": {"message": "Vyra API is not configured (missing api_client)."},
                                "timestamp": int(time.time() * 1000)
                            }))
                            
                    elif msg.get("type") == "voice_start":
                        # Dashboard microphone started
                        print("[WS] Dashboard voice session started")
                    elif msg.get("type") == "voice_end":
                        # Dashboard microphone stopped
                        print("[WS] Dashboard voice session ended")
                        
                except Exception as e:
                    print(f"[WS] Error processing JSON message: {e}")
                    pass
                    
            elif "bytes" in message:
                # Binary audio chunk from the dashboard microphone
                audio_data = message["bytes"]
                # For now, we just log it or forward it to the live audio session if connected
                if audio_loop and audio_loop.session:
                    try:
                        # JARVIS sends a WAV buffer (not raw PCM). Gemini expects raw PCM bytes
                        # for `mime_type="audio/pcm"`, otherwise transcription can lag until a long pause.
                        pcm_bytes = audio_data
                        is_wav = False
                        send_mime_type = "audio/pcm"
                        send_end_of_turn = False
                        try:
                            if isinstance(audio_data, (bytes, bytearray)) and len(audio_data) >= 12:
                                is_wav = audio_data[0:4] == b"RIFF" and audio_data[8:12] == b"WAVE"
                        except Exception:
                            is_wav = False

                        if is_wav:
                            import io
                            import wave

                            try:
                                with wave.open(io.BytesIO(audio_data)) as wf:
                                    # Note: JARVIS encodes mono 16-bit PCM at 16kHz.
                                    # If this deviates, Gemini may still work but quality may drop.
                                    pcm_bytes = wf.readframes(wf.getnframes())
                                send_mime_type = "audio/pcm"
                                send_end_of_turn = True
                            except Exception:
                                # If WAV decoding fails for any reason, fall back to sending the WAV bytes.
                                pcm_bytes = audio_data
                                send_mime_type = "audio/wav"
                                send_end_of_turn = True

                        # For voice sessions JARVIS currently sends one-shot WAV per turn.
                        # Using `end_of_turn=True` makes Gemini finalize immediately instead of waiting.
                        await audio_loop.session.send(
                            input={"mime_type": send_mime_type, "data": pcm_bytes},
                            end_of_turn=send_end_of_turn,
                        )
                    except Exception as e:
                        pass

    except WebSocketDisconnect:
        _ws_manager.disconnect(websocket)
    except Exception as e:
        print(f"[WS] Disconnected with error: {e}")
        _ws_manager.disconnect(websocket)



# --- SHUTDOWN HANDLER ---

def signal_handler(sig, frame):
    print(f"\n[SERVER] Caught signal {sig}. Exiting gracefully...")
    # Clean up audio loop
    if audio_loop:
        try:
            print("[SERVER] Stopping Audio Loop...")
            audio_loop.stop()
        except:
            pass
            
    # Clean up Jarvis process
    global jarvis_process
    if jarvis_process is not None:
        try:
            print("[SERVER] Shutting down JARVIS daemon...")
            jarvis_process.terminate()
            jarvis_process.wait(timeout=3)
        except Exception as e:
            print(f"[SERVER] Failed to terminate JARVIS smoothly: {e}")
            try:
                jarvis_process.kill()
            except:
                pass
                
    # Force kill
    print("[SERVER] Force exiting...")
    os._exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Global state
audio_loop = None
loop_task = None
jarvis_process = None
kasa_agent = KasaAgent()
SETTINGS_FILE = "settings.json"

# ── Background services (Phase 14: ambient presence) ─────────────────────────
_clap_detector = None   # ClapDetectorService instance
_clap_task     = None   # asyncio Task
_monitor_task  = None   # asyncio Task (passive window monitor)

# Web Agent global state
web_agent_instance = None       # Active WebAgent instance
web_agent_task = None           # asyncio Task running the agent
web_agent_mode_global = "autonomous"  # Current interaction mode

DEFAULT_SETTINGS = {
    "face_auth_enabled": False,  # Default OFF as requested
    # Global auto-allow for all tool authorization requests
    "auto_allow_all_tools": True,
    "tool_permissions": {
        "generate_cad": True,
        "run_web_agent": True,
        "write_file": True,
        "read_directory": True,
        "read_file": True,
        "create_project": True,
        "switch_project": True,
        "list_projects": True,
        "openclaw_send_message": True,
        "openclaw_run_agent": True,
        "openclaw_invoke_tool": True,
        "openclaw_get_status": False,
        "openclaw_list_skills": False,
        "run_code": True,
        "run_shell_command": True,
        "jarvis_chat": True,
        "jarvis_vault_search": True,
        "jarvis_vault_get_active_conversation": True,
        "jarvis_vault_append_message": True,
        "jarvis_execute": True,
        "jarvis_list_tools": True,
        "jarvis_show_page": True,
    },
    "printers": [],  # List of {host, port, name, type}
    "kasa_devices": [],  # List of {ip, alias, model}
    "camera_flipped": False  # Invert cursor horizontal direction
}

SETTINGS = DEFAULT_SETTINGS.copy()


def load_settings():
    global SETTINGS
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                loaded = json.load(f)
                # Merge with defaults to ensure new keys exist
                # Deep merge for tool_permissions would be better but shallow merge of top keys + tool_permissions check is okay for now
                for k, v in loaded.items():
                    if k == "tool_permissions" and isinstance(v, dict):
                        SETTINGS["tool_permissions"].update(v)
                    else:
                        SETTINGS[k] = v
            print(f"Loaded settings: {SETTINGS}")
        except Exception as e:
            print(f"Error loading settings: {e}")


def save_settings():
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(SETTINGS, f, indent=4)
        print("Settings saved.")
    except Exception as e:
        print(f"Error saving settings: {e}")


# Load on startup
load_settings()

kasa_agent = KasaAgent(known_devices=SETTINGS.get("kasa_devices"))
# Initialize Contact Manager
backend_dir = os.path.dirname(os.path.abspath(__file__))
contact_manager = ContactManager(data_dir=os.path.join(backend_dir, "data"))
# tool_permissions is now SETTINGS["tool_permissions"]


@app.on_event("startup")
async def startup_event():
    import sys
    print(f"[SERVER DEBUG] Startup Event Triggered")
    print(f"[SERVER DEBUG] Python Version: {sys.version}")
    try:
        loop = asyncio.get_running_loop()
        print(f"[SERVER DEBUG] Running Loop: {type(loop)}")
        policy = asyncio.get_event_loop_policy()
        print(f"[SERVER DEBUG] Current Policy: {type(policy)}")
    except Exception as e:
        print(f"[SERVER DEBUG] Error checking loop: {e}")

    # Start Jarvis Daemon Automatically
    global jarvis_process
    jarvis_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'jarvis')
    if os.path.exists(os.path.join(jarvis_dir, 'package.json')):
        try:
            import subprocess
            import socket

            JARVIS_DEFAULT_PORT = 3142

            def _port_in_use(port: int) -> bool:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    return s.connect_ex(('127.0.0.1', port)) == 0

            def find_free_port(start_port=JARVIS_DEFAULT_PORT, max_port=3200):
                for port in range(start_port, max_port):
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                        try:
                            s.bind(('127.0.0.1', port))
                            return port
                        except OSError:
                            continue
                return start_port

            if _port_in_use(JARVIS_DEFAULT_PORT):
                # JARVIS is already running on the default port — skip auto-start.
                os.environ["JARVIS_PORT"] = str(JARVIS_DEFAULT_PORT)
                print(f"[SERVER] JARVIS already running on port {JARVIS_DEFAULT_PORT} — skipping auto-start.")
                jarvis_process = None
            else:
                free_port = find_free_port()
                os.environ["JARVIS_PORT"] = str(free_port)
                print(f"[SERVER] Starting JARVIS daemon automatically on port {free_port}...")
                jarvis_process = subprocess.Popen(
                    ["bun", "run", "src/daemon/index.ts", "--port", str(free_port)],
                    cwd=jarvis_dir,
                    shell=True
                )
                print(f"[SERVER] JARVIS started with PID {jarvis_process.pid} on port {free_port}")
        except Exception as e:
            print(f"[SERVER] Failed to start JARVIS: {e}")
            jarvis_process = None
    else:
        print(f"[SERVER] JARVIS directory not found at {jarvis_dir}, skipping auto-start.")

    print("[SERVER] Startup: Initializing Kasa Agent...")
    await kasa_agent.initialize()

    # ── Start ClapDetectorService ─────────────────────────────────────────────
    global _clap_detector, _clap_task, _monitor_task
    try:
        from services.clap_detector import ClapDetectorService
        _running_loop = asyncio.get_running_loop()
        _clap_detector = ClapDetectorService(
            sio=sio,
            ws_manager=_ws_manager,
            loop=_running_loop,
        )
        _clap_task = asyncio.create_task(_clap_detector.start())
        print("[SERVER] ✅ ClapDetectorService started.")
    except Exception as _ce:
        print(f"[SERVER] ⚠️  ClapDetectorService failed to start: {_ce}")

    # ── Start PassiveMonitor ──────────────────────────────────────────────────
    try:
        from services.passive_monitor import run_passive_monitor
        _monitor_task = asyncio.create_task(run_passive_monitor())
        print("[SERVER] ✅ PassiveMonitor started.")
    except Exception as _me:
        print(f"[SERVER] ⚠️  PassiveMonitor failed to start: {_me}")


@app.get("/status")
async def status():
    return {"status": "running", "service": "VYRA Backend"}


@app.get("/openclaw/status")
async def openclaw_status():
    """Check if OpenClaw Gateway is reachable and return status."""
    try:
        from openclaw_client import get_openclaw_client
        client = get_openclaw_client()
        r = await client.get_status()
        return {"openclaw": r.get("ok", False), "details": r}
    except Exception as e:
        return {"openclaw": False, "error": str(e)}


# --- OpenAI Compatible Chat Endpoint ---


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    """
    OpenAI-compatible endpoint to allow OpenClaw (and other tools) to use 'Vyra' as a model.
    This routes the request to Google Gemini with Vyra's system instructions and personality.
    """
    if not api_client:
        raise HTTPException(
            status_code=503, detail="Gemini API Client not initialized (Missing Key)")

    try:
        # 1. Determine System Instruction
        # Check if 'vyra-girlfriend', 'vyra-professional', etc. is requested via model name
        personality = "girlfriend"
        if "professional" in request.model:
            personality = "professional"
        elif "bestfriend" in request.model:
            personality = "bestfriend"

        system_instruction = vyra.get_system_instruction(
            personality_mode=personality)

        # 2. Convert Messages to Gemini Format
        contents = []
        for msg in request.messages:
            role = "user" if msg.role == "user" else "model"
            contents.append(genai_types.Content(
                role=role,
                parts=[genai_types.Part(text=msg.content)]
            ))

        # 3. Call Gemini
        # We reuse the same model version as vyra
        model_name = "gemini-2.0-flash-exp"  # Or pull from vyra.MODEL if accessible

        response = api_client.models.generate_content(
            model=model_name,
            contents=contents,
            config=genai_types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=request.temperature,
                max_output_tokens=request.max_tokens,
            )
        )

        # 4. Format Response
        reply_text = response.text if response.text else ""

        return ChatCompletionResponse(
            id=f"chatcmpl-{int(time.time())}",
            created=int(time.time()),
            model=request.model,
            choices=[
                ChatCompletionResponseChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=reply_text),
                    finish_reason="stop"
                )
            ],
            usage={"prompt_tokens": 0, "completion_tokens": 0,
                   "total_tokens": 0}  # Placeholder
        )

    except Exception as e:
        print(f"[SERVER] Chat Completion Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Static file serving for output visualizations


@app.get("/outputs/{filename}")
async def serve_output_file(filename: str):
    """Serve generated output files (charts, diagrams, terminal outputs)"""
    file_path = Path("projects") / "outputs" / filename
    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path)
    else:
        raise HTTPException(status_code=404, detail="File not found")


@sio.event
async def connect(sid, environ):
    print(f"Client connected: {sid}")
    await sio.emit('status', {'msg': 'Connected to VYRA Backend'}, room=sid)

    # Auto-authenticate
    await sio.emit('auth_status', {'authenticated': True})


@sio.event
async def disconnect(sid):
    global audio_loop
    if audio_loop:
        audio_loop.client_plays_audio = False
    print(f"Client disconnected: {sid}")


@sio.event
async def client_audio_playback(sid, data=None):
    """Client plays audio locally for lip sync; server skips playback to avoid echo."""
    global audio_loop
    if audio_loop:
        audio_loop.client_plays_audio = data.get('playOnClient', True)
        print(
            f"[SERVER] Client audio playback: {'client plays (no echo)' if audio_loop.client_plays_audio else 'server plays'}")


@sio.event
async def start_audio(sid, data=None):
    global audio_loop, loop_task

    # Pause clap detector — Windows cannot share the mic between two PyAudio streams
    if _clap_detector:
        _clap_detector.pause()

    print("Starting Audio Loop...")

    device_index = None
    device_name = None
    if data:
        if 'device_index' in data:
            device_index = data['device_index']
        if 'device_name' in data:
            device_name = data['device_name']

    print(f"Using input device: Name='{device_name}', Index={device_index}")

    if audio_loop:
        if loop_task and (loop_task.done() or loop_task.cancelled()):
            print(
                "Audio loop task appeared finished/cancelled. Clearing and restarting...")
            audio_loop = None
            loop_task = None
        else:
            print("Audio loop already running. Re-connecting client to session.")
            await sio.emit('status', {'msg': 'VYRA Already Running'})
            return

    # Callback to send audio data to frontend

    def on_audio_data(data_bytes):
        # We need to schedule this on the event loop
        # This is high frequency, so we might want to downsample or batch if it's too much
        asyncio.create_task(sio.emit('audio_data', {'data': list(data_bytes)}))

    # Callback to send CAL data to frontend
    def on_cad_data(data):
        info = f"{len(data.get('vertices', []))} vertices" if 'vertices' in data else f"{len(data.get('data', ''))} bytes (STL)"
        print(f"Sending CAD data to frontend: {info}")
        asyncio.create_task(sio.emit('cad_data', data))

    # Callback to send Browser data to frontend
    def on_web_data(data):
        print(
            f"Sending Browser data to frontend: {len(data.get('log', ''))} chars logs")
        asyncio.create_task(sio.emit('browser_frame', data))

    # Callback to send Transcription data to frontend
    def on_transcription(data):
        # data = {"sender": "User"|"ada", "text": "..."}
        asyncio.create_task(sio.emit('transcription', data))

    # Callback to send Confirmation Request to frontend
    def on_tool_confirmation(data):
        # data = {"id": "uuid", "tool": "tool_name", "args": {...}}
        print(f"Requesting confirmation for tool: {data.get('tool')}")
        asyncio.create_task(sio.emit('tool_confirmation_request', data))

    # Broadcast every tool call to the frontend Live Terminal
    def on_tool_call(data):
        # data = {"name": "tool_name", "args": {...}}
        asyncio.create_task(sio.emit('tool_call', data))

    # Callback to send CAD status to frontend
    def on_cad_status(status):
        # status can be:
        # - a string like "generating" (from ada.py handle_cad_request)
        # - a dict with {status, attempt, max_attempts, error} (from Cadagent)
        if isinstance(status, dict):
            print(
                f"Sending CAD Status: {status.get('status')} (attempt {status.get('attempt')}/{status.get('max_attempts')})")
            asyncio.create_task(sio.emit('cad_status', status))
        else:
            # Legacy: simple string
            print(f"Sending CAD Status: {status}")
            asyncio.create_task(sio.emit('cad_status', {'status': status}))

    # Callback to send CAD thoughts to frontend (streaming)
    def on_cad_thought(thought_text):
        asyncio.create_task(sio.emit('cad_thought', {'text': thought_text}))

    # Callback to send Project Update to frontend
    def on_project_update(project_name):
        print(f"Sending Project Update: {project_name}")
        asyncio.create_task(
            sio.emit('project_update', {'project': project_name}))

    # Callback to send Device Update to frontend
    def on_device_update(devices):
        # devices is a list of dicts
        print(f"Sending Kasa Device Update: {len(devices)} devices")
        asyncio.create_task(sio.emit('kasa_devices', devices))

    # Callback to send Personality Update to frontend
    def on_personality_update(mode):
        print(f"Sending Personality Update: {mode}")
        asyncio.create_task(sio.emit('personality_update', {'mode': mode}))

    # Callback to send Environmental State Update to frontend
    def on_environmental_update(env_data):
        print(
            f"Sending Environmental Update: people={env_data.get('people_count')}, activity={env_data.get('activity_level')}, music={env_data.get('has_music')}")
        asyncio.create_task(sio.emit('environmental_update', env_data))

    # Callback to send explicit Emotion Update to frontend
    def on_emotion_update(emotion):
        print(f"Sending Emotion Update: {emotion}")
        asyncio.create_task(sio.emit('emotion', {'emotion': emotion}))

    # Callback to send Visualization Data to frontend
    def on_visualization_data(viz_data):
        print(
            f"Sending Visualization Data: {viz_data.get('type')} - {viz_data.get('title')}")
        asyncio.create_task(sio.emit('visualization_data', viz_data))

    # Callback to open JARVIS dashboard in frontend overlay
    def on_jarvis_dashboard(data):
        # data = {"show": True, "page": "dashboard", "url": "http://localhost:3142/#/dashboard"}
        print(f"Sending JARVIS dashboard event: page={data.get('page')}, url={data.get('url')}")
        try:
            loop = asyncio.get_event_loop()
            loop.create_task(sio.emit('jarvis_dashboard', data))
        except Exception as e:
            print(f"[JARVIS] Failed to emit jarvis_dashboard event: {e}")

    # Callback to send Error to frontend
    def on_error(msg):
        print(f"Sending Error to frontend: {msg}")
        asyncio.create_task(sio.emit('error', {'msg': msg}))

    # Callbacks when model (Gemini Live) connection drops/restores — so UI shows reconnecting, not "Disconnected"
    async def on_session_lost(reason):
        short = str(reason)[:120]
        print(f"[SERVER] Model connection lost: {reason}")
        await sio.emit('status', {'msg': f'Reconnecting... ({short})'})

    async def on_session_restored():
        print("[SERVER] Model connection restored.")
        await sio.emit('status', {'msg': 'VYRA Started'})

    # Persistent user memory for personalization and context-aware reasoning
    backend_dir = os.path.dirname(os.path.abspath(__file__))
    user_memory = UserMemory(data_dir=os.path.join(
        backend_dir, "data"), primary_user_id="Lokesh")

    # Initialize vyra
    try:
        print(f"Initializing AudioLoop with device_index={device_index}")
        audio_loop = vyra.AudioLoop(
            video_mode="none",
            on_audio_data=on_audio_data,
            on_cad_data=on_cad_data,
            on_web_data=on_web_data,
            on_transcription=on_transcription,
            on_tool_confirmation=on_tool_confirmation,
            on_tool_call=on_tool_call,
            on_cad_status=on_cad_status,
            on_cad_thought=on_cad_thought,
            on_project_update=on_project_update,
            on_device_update=on_device_update,
            on_personality_update=on_personality_update,
            on_environmental_update=on_environmental_update,
            on_emotion_update=on_emotion_update,
            on_visualization_data=on_visualization_data,
            on_jarvis_dashboard=on_jarvis_dashboard,
            on_error=on_error,
            on_session_lost=on_session_lost,
            on_session_restored=on_session_restored,
            user_memory=user_memory,
            input_device_index=device_index,
            input_device_name=device_name,
            kasa_agent=kasa_agent,
            spotify_agent=spotify_agent,
            sio=sio,
        )
        print("AudioLoop initialized successfully.")

        # Apply current permissions (include global auto_allow setting)
        permissions_with_global = {
            "auto_allow_all_tools": SETTINGS.get("auto_allow_all_tools", False)}
        permissions_with_global.update(SETTINGS["tool_permissions"])
        audio_loop.update_permissions(permissions_with_global)

        # Check initial mute state
        if data and data.get('muted', False):
            print("Starting with Audio Paused")
            audio_loop.set_paused(True)

        print("Creating asyncio task for AudioLoop.run()")
        loop_task = asyncio.create_task(audio_loop.run())

        # Add a done callback to catch silent failures in the loop
        def handle_loop_exit(task):
            try:
                task.result()
            except asyncio.CancelledError:
                print("Audio Loop Cancelled")
            except Exception as e:
                print(f"Audio Loop Crashed: {e}")
                # You could emit 'error' here if you have context

        loop_task.add_done_callback(handle_loop_exit)

        print("Emitting 'VYRA Started'")
        await sio.emit('status', {'msg': 'VYRA Started'})

        # Load saved printers
        saved_printers = SETTINGS.get("printers", [])
        if saved_printers and audio_loop.printer_agent:
            print(f"[SERVER] Loading {len(saved_printers)} saved printers...")
            for p in saved_printers:
                audio_loop.printer_agent.add_printer_manually(
                    name=p.get("name", p["host"]),
                    host=p["host"],
                    port=p.get("port", 80),
                    printer_type=p.get("type", "moonraker"),
                    camera_url=p.get("camera_url")
                )

        # Start Printer Monitor
        asyncio.create_task(monitor_printers_loop())

    except Exception as e:
        print(f"CRITICAL ERROR STARTING vyra: {e}")
        import traceback
        traceback.print_exc()
        await sio.emit('error', {'msg': f"Failed to start: {str(e)}"})
        audio_loop = None  # Ensure we can try again


async def monitor_printers_loop():
    """Background task to query printer status periodically."""
    print("[SERVER] Starting Printer Monitor Loop")
    while audio_loop and audio_loop.printer_agent:
        try:
            agent = audio_loop.printer_agent
            if not agent.printers:
                await asyncio.sleep(5)
                continue

            tasks = []
            for host, printer in agent.printers.items():
                if printer.printer_type.value != "unknown":
                    tasks.append(agent.get_print_status(host))

            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for res in results:
                    if isinstance(res, Exception):
                        pass  # Ignore errors for now
                    elif res:
                        # res is PrintStatus object
                        await sio.emit('print_status_update', res.to_dict())

        except asyncio.CancelledError:
            print("[SERVER] Printer Monitor Cancelled")
            break
        except Exception as e:
            print(f"[SERVER] Monitor Loop Error: {e}")

        await asyncio.sleep(2)  # Update every 2 seconds for responsiveness


@sio.event
async def stop_audio(sid):
    global audio_loop
    if audio_loop:
        audio_loop.stop()
        print("Stopping Audio Loop")
        audio_loop = None
        await sio.emit('status', {'msg': 'VYRA Stopped'})

    # Resume clap detector now that the mic is free
    if _clap_detector:
        _clap_detector.resume()


@sio.event
async def pause_audio(sid):
    global audio_loop
    if audio_loop:
        audio_loop.set_paused(True)
        print("Pausing Audio")
        await sio.emit('status', {'msg': 'Audio Paused'})


@sio.event
async def resume_audio(sid):
    global audio_loop
    if audio_loop:
        audio_loop.set_paused(False)
        print("Resuming Audio")
        await sio.emit('status', {'msg': 'Audio Resumed'})


@sio.event
async def interrupt(sid, data=None):
    global audio_loop
    if audio_loop:
        print("[SERVER] Interrupt signal received, clearing audio queue...")
        import time
        audio_loop.clear_audio_queue()
        audio_loop._interrupt_active_until = time.time() + 4.0
        # To truly stop Gemini if it's currently streaming, we send a system interrupt
        if audio_loop.session:
            try:
                await audio_loop.session.send(input="[SYSTEM INTERRUPT: Stop talking immediately. DO NOT acknowledge this action. Say absolutely nothing.]", end_of_turn=True)
            except Exception as e:
                print(f"[SERVER] Failed to send interrupt to session: {e}")
        await sio.emit('status', {'msg': 'Vyra Interrupted'})


@sio.event
async def set_personality(sid, data):
    """Switch between girlfriend, bestfriend, and professional personality modes"""
    global audio_loop
    mode = data.get('mode', 'girlfriend')

    if not audio_loop:
        await sio.emit('error', {'msg': 'Audio loop not active'})
        return

    # Await the async method!
    # Logic inside set_personality_mode now handles sending the system instruction update.
    if await audio_loop.set_personality_mode(mode):
        print(f"[SERVER] Personality mode switched to: {mode}")
        await sio.emit('status', {'msg': f'Switched to {mode.capitalize()} Mode'})
    else:
        await sio.emit('error', {'msg': f'Invalid personality mode: {mode}'})


@sio.event
async def confirm_tool(sid, data):
    # data: { "id": "...", "confirmed": True/False }
    request_id = data.get('id')
    confirmed = data.get('confirmed', False)

    print(
        f"[SERVER DEBUG] Received confirmation response for {request_id}: {confirmed}")

    if audio_loop:
        audio_loop.resolve_tool_confirmation(request_id, confirmed)
    else:
        print("Audio loop not active, cannot resolve confirmation.")


@sio.event
async def shutdown(sid, data=None):
    """Gracefully shutdown the server when the application closes."""
    global audio_loop, loop_task

    print("[SERVER] ========================================")
    print("[SERVER] SHUTDOWN SIGNAL RECEIVED FROM FRONTEND")
    print("[SERVER] ========================================")

    # Stop audio loop
    if audio_loop:
        print("[SERVER] Stopping Audio Loop...")
        audio_loop.stop()
        audio_loop = None

    # Cancel the loop task if running
    if loop_task and not loop_task.done():
        print("[SERVER] Cancelling loop task...")
        loop_task.cancel()
        loop_task = None

    print("[SERVER] Graceful shutdown complete. Terminating process...")

    # Force exit immediately - os._exit bypasses cleanup but ensures termination
    os._exit(0)


@sio.event
async def user_input(sid, data):
    text = data.get('text')
    print(f"[SERVER DEBUG] User input received: '{text}'")

    if not audio_loop:
        print("[SERVER DEBUG] [Error] Audio loop is None. Cannot send text.")
        return

    # Session can be None during reconnect (e.g. right after switching to Girlfriend mode)
    if not audio_loop.session:
        if text:
            audio_loop._pending_user_text = text
            print(
                "[SERVER DEBUG] Session reconnecting. Queued message; will send when VYRA is ready.")
            await sio.emit('status', {'msg': 'Reconnecting... Your message will be sent when VYRA is ready.'})
        return

    if text:
        print(f"[SERVER DEBUG] Sending message to model: '{text}'")

        # Log User Input to Project History
        if audio_loop and audio_loop.project_manager:
            audio_loop.project_manager.log_chat("User", text)

        # Use the same 'send' method that worked for audio, as 'send_realtime_input' and 'send_client_content' seem unstable in this env
        # INJECT VIDEO FRAME IF AVAILABLE (VAD-style logic for Text Input)
        if audio_loop and audio_loop._latest_image_payload:
            print(f"[SERVER DEBUG] Piggybacking video frame with text input.")
            try:
                # Send frame first
                await audio_loop.session.send(input=audio_loop._latest_image_payload, end_of_turn=False)
            except Exception as e:
                print(f"[SERVER DEBUG] Failed to send piggyback frame: {e}")

        await audio_loop.session.send(input=text, end_of_turn=True)
        print(f"[SERVER DEBUG] Message sent to model successfully.")


# ... (imports)


@sio.event
async def video_frame(sid, data):
    # data should contain 'image' which is binary (blob) or base64 encoded
    image_data = data.get('image')
    if image_data and audio_loop:
        # We don't await this because we don't want to block the socket handler
        # But send_frame is async, so we create a task
        asyncio.create_task(audio_loop.send_frame(image_data))


@sio.event
async def toggle_vision(sid, data):
    """
    Called by frontend to explicitly hand camera ownership to the Python backend
    so that CameraManager can run natively without Chrome locking the camera.
    Tracking works even when Vyra is minimized - only the UI preview feed pauses.
    """
    active = data.get('active', False)
    print(f"[SERVER] Received toggle_vision: active={active}")
    from camera_manager import get_camera_manager
    cm = get_camera_manager()
    global audio_loop

    if active:
        print("[SERVER] Starting native Video/Vision tracking (Iron Man Mode)...")
        cm.start()
        
        # Tell Vyra (if running) that vision is alive so it can stream to Gemini
        if audio_loop:
            audio_loop.video_mode = "camera"
            if not getattr(audio_loop, '_video_task_started', False) and getattr(audio_loop, 'session', None):
                 audio_loop._video_task_started = True
                 asyncio.create_task(audio_loop.get_frames())
                 print("[SERVER] Vyra get_frames stream task started.")
                 
        # Stream a low-FPS preview back to the frontend PIP Window
        # NOTE: Tracking runs at full 60fps in CameraManager regardless of this feed
        async def stream_ui_feed():
            print("[SERVER] UI Video Preview Stream Started (10 FPS)")
            await sio.emit('status', {'msg': 'Backend Vision Initializing...'})
            frame_count = 0
            while cm.running:
                try:
                    # Check if frontend told us it is hidden (minimized)
                    if getattr(cm, '_ui_paused', False):
                        await asyncio.sleep(0.5)
                        continue
                    
                    await asyncio.sleep(0.1)  # 10 FPS - PIP is tiny
                    frame_b64 = await cm.get_latest_frame_b64(annotated=True)
                    if frame_b64:
                        frame_count += 1
                        if frame_count == 1:
                            print("[SERVER] First frame captured. Streaming to frontend.", flush=True)
                            await sio.emit('status', {'msg': 'Backend Vision Running'})
                        await sio.emit('video_stream', {'image': frame_b64})
                    else:
                        if frame_count == 0:
                            await sio.emit('status', {'msg': 'Wait: Camera returning null frame...'})
                except Exception as e:
                    print(f"[SERVER] Exception in stream_ui_feed: {e}")
                    await sio.emit('status', {'msg': f'Error: {e}'})
            print("[SERVER] UI Video Preview Stream Stopped")

        asyncio.create_task(stream_ui_feed())
    else:
        print("[SERVER] Stopping native Video/Vision tracking...")
        cm.stop()
        if audio_loop:
            audio_loop.video_mode = "none"
            audio_loop._video_task_started = False


@sio.event
async def vision_visibility(sid, data):
    """
    Frontend tells us when window is minimized/hidden so we can pause the UI feed.
    IMPORTANT: This pauses ONLY the UI preview stream, NOT the hand tracking.
    Tracking always runs at full speed in the CameraManager thread.
    """
    visible = data.get('visible', True)
    label = 'visible' if visible else 'hidden (tracking continues)'
    print(f"[SERVER] Vision UI visibility: {label}")
    from camera_manager import get_camera_manager
    cm = get_camera_manager()
    cm._ui_paused = not visible


@sio.event
async def save_memory(sid, data):
    try:
        messages = data.get('messages', [])
        if not messages:
            print("No messages to save.")
            return

        # Ensure directory exists
        memory_dir = Path("long_term_memory")
        memory_dir.mkdir(exist_ok=True)

        # Generate filename
        # Use provided filename if available, else timestamp
        provided_name = data.get('filename')

        if provided_name:
            # Simple sanitization
            if not provided_name.endswith('.txt'):
                provided_name += '.txt'
            # Prevent directory traversal
            filename = memory_dir / Path(provided_name).name
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = memory_dir / f"memory_{timestamp}.txt"

        # Write to file
        with open(filename, 'w', encoding='utf-8') as f:
            for msg in messages:
                msg.get('sender', 'Unknown')
                msg.get('text', '')
        print(f"Conversation saved to {filename}")
        await sio.emit('status', {'msg': 'Memory Saved Successfully'})

    except Exception as e:
        print(f"Error saving memory: {e}")
        await sio.emit('error', {'msg': f"Failed to save memory: {str(e)}"})


@sio.event
async def upload_memory(sid, data):
    print(f"Received memory upload request")
    try:
        memory_text = data.get('memory', '')
        if not memory_text:
            print("No memory data provided.")
            return

        if not audio_loop:
            print("[SERVER DEBUG] [Error] Audio loop is None. Cannot load memory.")
            await sio.emit('error', {'msg': "System not ready (Audio Loop inactive)"})
            return

        if not audio_loop.session:
            print("[SERVER DEBUG] [Error] Session is None. Cannot load memory.")
            await sio.emit('error', {'msg': "System not ready (No active session)"})
            return

        # Send to model
        print("Sending memory context to model...")
        context_msg = f"System Notification: The user has uploaded a long-term memory file. Please load the following context into your understanding. The format is a text log of previous conversations:\n\n{memory_text}"

        await audio_loop.session.send(input=context_msg, end_of_turn=True)
        print("Memory context sent successfully.")
        await sio.emit('status', {'msg': 'Memory Loaded into Context'})

    except Exception as e:
        print(f"Error uploading memory: {e}")
        await sio.emit('error', {'msg': f"Failed to upload memory: {str(e)}"})


@sio.event
async def discover_kasa(sid):
    print(f"Received discover_kasa request")
    try:
        devices = await kasa_agent.discover_devices()
        await sio.emit('kasa_devices', devices)
        await sio.emit('status', {'msg': f"Found {len(devices)} Kasa devices"})

        # Save to settings
        # devices is a list of full device info dicts. minimizing for storage.
        saved_devices = []
        for d in devices:
            saved_devices.append({
                "ip": d["ip"],
                "alias": d["alias"],
                "model": d["model"]
            })

        # Merge with existing to preserve any manual overrides?
        # For now, just overwrite with latest scan result + previously known if we want to be fancy,
        # but user asked for "Any new devices that are scanned are added there".
        # A simple full persistence of current state is safest.
        SETTINGS["kasa_devices"] = saved_devices
        save_settings()
        print(f"[SERVER] Saved {len(saved_devices)} Kasa devices to settings.")

    except Exception as e:
        print(f"Error discovering kasa: {e}")
        await sio.emit('error', {'msg': f"Kasa Discovery Failed: {str(e)}"})


@sio.event
async def iterate_cad(sid, data):
    # data: { prompt: "make it bigger" }
    prompt = data.get('prompt')
    print(f"Received iterate_cad request: '{prompt}'")

    if not audio_loop or not audio_loop.cad_agent:
        await sio.emit('error', {'msg': "CAD Agent not available"})
        return

    try:
        # Notify user work has started
        await sio.emit('status', {'msg': 'Iterating design...'})
        await sio.emit('cad_status', {'status': 'generating'})

        # Call the agent with project path
        cad_output_dir = str(
            audio_loop.project_manager.get_current_project_path() / "cad")
        result = await audio_loop.cad_agent.iterate_prototype(prompt, output_dir=cad_output_dir)

        if result:
            info = f"{len(result.get('data', ''))} bytes (STL)"
            print(f"Sending updated CAD data: {info}")
            await sio.emit('cad_data', result)
            # Save to Project
            if 'file_path' in result:
                saved_path = audio_loop.project_manager.save_cad_artifact(
                    result['file_path'], prompt)
                if saved_path:
                    print(f"[SERVER] Saved iterated CAD to {saved_path}")

            await sio.emit('status', {'msg': 'Design updated'})
        else:
            await sio.emit('error', {'msg': 'Failed to update design'})

    except Exception as e:
        print(f"Error iterating CAD: {e}")
        await sio.emit('error', {'msg': f"Iteration Error: {str(e)}"})


@sio.event
async def generate_cad(sid, data):
    # data: { prompt: "make a cube" }
    prompt = data.get('prompt')
    print(f"Received generate_cad request: '{prompt}'")

    if not audio_loop or not audio_loop.cad_agent:
        await sio.emit('error', {'msg': "CAD Agent not available"})
        return

    try:
        await sio.emit('status', {'msg': 'Generating new design...'})
        await sio.emit('cad_status', {'status': 'generating'})

        # Use generate_prototype based on prompt with project path
        cad_output_dir = str(
            audio_loop.project_manager.get_current_project_path() / "cad")
        result = await audio_loop.cad_agent.generate_prototype(prompt, output_dir=cad_output_dir)

        if result:
            info = f"{len(result.get('data', ''))} bytes (STL)"
            print(f"Sending newly generated CAD data: {info}")
            await sio.emit('cad_data', result)

            # Save to Project
            if 'file_path' in result:
                saved_path = audio_loop.project_manager.save_cad_artifact(
                    result['file_path'], prompt)
                if saved_path:
                    print(f"[SERVER] Saved generated CAD to {saved_path}")

            await sio.emit('status', {'msg': 'Design generated'})
        else:
            await sio.emit('error', {'msg': 'Failed to generate design'})

    except Exception as e:
        print(f"Error generating CAD: {e}")
        await sio.emit('error', {'msg': f"Generation Error: {str(e)}"})

# ─────────────────────────────────────────────────────────
# WEB AUTOMATION AGENT EVENTS
# ─────────────────────────────────────────────────────────


@sio.event
async def prompt_web_agent(sid, data):
    """Launch an automation task with live screenshot/log streaming."""
    global web_agent_instance, web_agent_task, web_agent_mode_global

    prompt = data.get('prompt', '').strip()
    # autonomous | semi_auto | manual
    mode = data.get('mode', web_agent_mode_global)

    print(f"[WEB_AGENT] Received request (mode={mode}): '{prompt}'")

    if not prompt:
        await sio.emit('error', {'msg': 'Please provide a task for the Web Agent'})
        return

    if not SETTINGS.get('tool_permissions', {}).get('run_web_agent', True):
        await sio.emit('error', {'msg': 'Web Agent is disabled in permissions'})
        return

    # Stop any existing running agent
    if web_agent_instance and web_agent_task and not web_agent_task.done():
        web_agent_instance.stop()
        try:
            await asyncio.wait_for(web_agent_task, timeout=5)
        except Exception:
            web_agent_task.cancel()

    await sio.emit('web_agent_status', {'status': 'Web agent feature removed'})
    return
    web_agent_mode_global = mode

    # ── Callbacks ──────────────────────────────────────────
    async def on_update(screenshot_b64, log_msg, url, entry_dict):
        """Called after every browser action — sends live frame to frontend."""
        await sio.emit('browser_frame', {
            'image':  screenshot_b64 or '',
            'log':    log_msg or '',
            'url':    url or '',
            'entry':  entry_dict or {},
        })

    async def on_action_request(entry_dict):
        """Called in semi-auto mode before each action — ask frontend to approve."""
        await sio.emit('web_agent_action_request', entry_dict)

    async def on_status(status_msg):
        await sio.emit('web_agent_status', {'status': status_msg})
        await sio.emit('status', {'msg': f'Web Agent: {status_msg}'})

    # ── Run Task ───────────────────────────────────────────
    async def run():
        global web_agent_instance
        try:
            await on_status('Starting…')
            result = await web_agent_instance.run_task(
                prompt,
                update_callback=on_update,
                action_request_callback=on_action_request,
                status_callback=on_status,
                mode=mode,
            )
            # Emit completion
            await sio.emit('web_agent_complete', {
                'success':      result.get('success', False),
                'summary':      result.get('summary', ''),
                'action_count': result.get('action_count', 0),
                'final_url':    result.get('final_url', ''),
                'session_info': result.get('session_info', {}),
                'actions':      result.get('actions', []),
            })
            await on_status('Finished' if result.get('success') else 'Failed')
        except asyncio.CancelledError:
            await on_status('Stopped')
        except Exception as e:
            import traceback
            traceback.print_exc()
            await sio.emit('error', {'msg': f'Web Agent error: {e}'})
            await on_status('Error')

    # Send initial acknowledgement
    await sio.emit('browser_frame', {
        'image': '', 'log': f'Starting: {prompt}', 'url': 'about:blank', 'entry': {}
    })

    web_agent_task = asyncio.create_task(run())


@sio.event
async def web_agent_pause(sid, data=None):
    """Pause the running web agent."""
    global web_agent_instance
    if web_agent_instance:
        web_agent_instance.pause()
        await sio.emit('web_agent_status', {'status': 'Paused'})
        await sio.emit('status', {'msg': 'Web Agent paused'})
    else:
        await sio.emit('error', {'msg': 'No active Web Agent session'})


@sio.event
async def web_agent_resume(sid, data=None):
    """Resume a paused web agent."""
    global web_agent_instance
    if web_agent_instance:
        web_agent_instance.resume()
        await sio.emit('web_agent_status', {'status': 'Running'})
        await sio.emit('status', {'msg': 'Web Agent resumed'})
    else:
        await sio.emit('error', {'msg': 'No active Web Agent session'})


@sio.event
async def web_agent_stop(sid, data=None):
    """Stop and cancel the running web agent task."""
    global web_agent_instance, web_agent_task
    if web_agent_instance:
        web_agent_instance.stop()
        if web_agent_task and not web_agent_task.done():
            web_agent_task.cancel()
        web_agent_instance = None
        web_agent_task = None
        await sio.emit('web_agent_status', {'status': 'Stopped'})
        await sio.emit('status', {'msg': 'Web Agent stopped'})
    else:
        await sio.emit('error', {'msg': 'No active Web Agent session'})


@sio.event
async def web_agent_mode(sid, data):
    """Switch the interaction mode (autonomous | semi_auto | manual)."""
    global web_agent_instance, web_agent_mode_global
    mode = data.get('mode', 'autonomous')
    web_agent_mode_global = mode
    if web_agent_instance:
        web_agent_instance.set_mode(mode)
    await sio.emit('web_agent_status', {'status': f'Mode: {mode}', 'mode': mode})
    await sio.emit('status', {'msg': f'Web Agent mode: {mode}'})


@sio.event
async def web_agent_approve(sid, data):
    """Approve or reject a pending semi-auto action."""
    global web_agent_instance
    approved = data.get('approved', False)
    if web_agent_instance:
        web_agent_instance.approve_action(approved)
        await sio.emit('web_agent_status', {
            'status': 'Action approved' if approved else 'Action rejected'
        })
    else:
        await sio.emit('error', {'msg': 'No active Web Agent session'})


@sio.event
async def get_web_agent_logs(sid, data=None):
    """Return the full structured action log for the current session."""
    global web_agent_instance
    if web_agent_instance:
        logs = web_agent_instance.get_logs()
        session = web_agent_instance.get_session_info()
        await sio.emit('web_agent_logs', {'logs': logs, 'session': session})
    else:
        await sio.emit('web_agent_logs', {'logs': [], 'session': {}})


@sio.event
async def discover_printers(sid):
    print("Received discover_printers request")

    # If audio_loop isn't ready yet, return saved printers from settings
    if not audio_loop or not audio_loop.printer_agent:
        saved_printers = SETTINGS.get("printers", [])
        if saved_printers:
            # Convert saved printers to the expected format
            printer_list = []
            for p in saved_printers:
                printer_list.append({
                    "name": p.get("name", p["host"]),
                    "host": p["host"],
                    "port": p.get("port", 80),
                    "printer_type": p.get("type", "unknown"),
                    "camera_url": p.get("camera_url")
                })
            print(
                f"[SERVER] Returning {len(printer_list)} saved printers (audio_loop not ready)")
            await sio.emit('printer_list', printer_list)
            return
        else:
            await sio.emit('printer_list', [])
            await sio.emit('status', {'msg': "Connect to VYRA to enable printer discovery"})
            return

    try:
        printers = await audio_loop.printer_agent.discover_printers()
        await sio.emit('printer_list', printers)
        await sio.emit('status', {'msg': f"Found {len(printers)} printers"})
    except Exception as e:
        print(f"Error discovering printers: {e}")
        await sio.emit('error', {'msg': f"Printer Discovery Failed: {str(e)}"})


@sio.event
async def add_printer(sid, data):
    # data: { host: "192.168.1.50", name: "My Printer", type: "moonraker" }
    raw_host = data.get('host')
    name = data.get('name') or raw_host
    ptype = data.get('type', "moonraker")

    # Parse port if present
    if ":" in raw_host:
        host, port_str = raw_host.split(":")
        port = int(port_str)
    else:
        host = raw_host
        port = 80

    print(f"Received add_printer request: {host}:{port} ({ptype})")

    if not audio_loop or not audio_loop.printer_agent:
        await sio.emit('error', {'msg': "Printer Agent not available"})
        return

    try:
        # Add manually
        camera_url = data.get('camera_url')
        printer = audio_loop.printer_agent.add_printer_manually(
            name, host, port=port, printer_type=ptype, camera_url=camera_url)

        # Save to settings
        new_printer_config = {
            "name": name,
            "host": host,
            "port": port,
            "type": ptype,
            "camera_url": camera_url
        }

        # Check if already exists to avoid duplicates
        exists = False
        for p in SETTINGS.get("printers", []):
            if p["host"] == host and p["port"] == port:
                exists = True
                break

        if not exists:
            if "printers" not in SETTINGS:
                SETTINGS["printers"] = []
            SETTINGS["printers"].append(new_printer_config)
            save_settings()
            print(f"[SERVER] Saved printer {name} to settings.")

        # Probe to confirm/correct type
        print(f"Probing {host} to confirm type...")
        # Try port 7125 (Moonraker) and 4408 (Fluidd/K1)
        ports_to_try = [80, 7125, 4408]

        actual_type = "unknown"
        for port in ports_to_try:
            found_type = await audio_loop.printer_agent._probe_printer_type(host, port)
            if found_type.value != "unknown":
                actual_type = found_type
                # Update port if different
                if port != 80:
                    printer.port = port
                break

        if actual_type != "unknown" and actual_type != printer.printer_type:
            printer.printer_type = actual_type
            print(
                f"Corrected type to {actual_type.value} on port {printer.port}")

        # Refresh list for everyone
        printers = [p.to_dict()
                    for p in audio_loop.printer_agent.printers.values()]
        await sio.emit('printer_list', printers)
        await sio.emit('status', {'msg': f"Added printer: {name}"})

    except Exception as e:
        print(f"Error adding printer: {e}")
        await sio.emit('error', {'msg': f"Failed to add printer: {str(e)}"})


@sio.event
async def print_stl(sid, data):
    print(f"Received print_stl request: {data}")
    # data: { stl_path: "path/to.stl" | "current", printer: "name_or_ip", profile: "optional" }

    if not audio_loop or not audio_loop.printer_agent:
        await sio.emit('error', {'msg': "Printer Agent not available"})
        return

    try:
        stl_path = data.get('stl_path', 'current')
        printer_name = data.get('printer')
        profile = data.get('profile')

        if not printer_name:
            await sio.emit('error', {'msg': "No printer specified"})
            return

        await sio.emit('status', {'msg': f"Preparing print for {printer_name}..."})

        # Get current project path for resolution
        current_project_path = None
        if audio_loop and audio_loop.project_manager:
            current_project_path = str(
                audio_loop.project_manager.get_current_project_path())
            print(f"[SERVER DEBUG] Using project path: {current_project_path}")

        # Resolve STL path before slicing so we can preview it
        resolved_stl = audio_loop.printer_agent._resolve_file_path(
            stl_path, current_project_path)

        if resolved_stl and os.path.exists(resolved_stl):
            # Open the STL in the CAD module for preview
            try:
                import base64
                with open(resolved_stl, 'rb') as f:
                    stl_data = f.read()
                stl_b64 = base64.b64encode(stl_data).decode('utf-8')
                stl_filename = os.path.basename(resolved_stl)

                print(f"[SERVER] Opening STL in CAD module: {stl_filename}")
                await sio.emit('cad_data', {
                    'format': 'stl',
                    'data': stl_b64,
                    'filename': stl_filename
                })
            except Exception as e:
                print(f"[SERVER] Warning: Could not preview STL: {e}")

        # Progress Callback
        async def on_slicing_progress(percent, message):
            await sio.emit('slicing_progress', {
                'printer': printer_name,
                'percent': percent,
                'message': message
            })
            if percent < 100:
                await sio.emit('status', {'msg': f"Slicing: {percent}%"})

        result = await audio_loop.printer_agent.print_stl(
            stl_path,
            printer_name,
            profile,
            progress_callback=on_slicing_progress,
            root_path=current_project_path
        )

        await sio.emit('print_result', result)
        await sio.emit('status', {'msg': f"Print Job: {result.get('status', 'unknown')}"})

    except Exception as e:
        print(f"Error printing STL: {e}")
        await sio.emit('error', {'msg': f"Print Failed: {str(e)}"})


@sio.event
async def get_slicer_profiles(sid):
    """Get available OrcaSlicer profiles for manual selection."""
    print("Received get_slicer_profiles request")
    if not audio_loop or not audio_loop.printer_agent:
        await sio.emit('error', {'msg': "Printer Agent not available"})
        return

    try:
        profiles = audio_loop.printer_agent.get_available_profiles()
        await sio.emit('slicer_profiles', profiles)
    except Exception as e:
        print(f"Error getting slicer profiles: {e}")
        await sio.emit('error', {'msg': f"Failed to get profiles: {str(e)}"})


@sio.event
async def control_kasa(sid, data):
    # data: { ip, action: "on"|"off"|"brightness"|"color", value: ... }
    ip = data.get('ip')
    action = data.get('action')
    print(f"Kasa Control: {ip} -> {action}")

    try:
        success = False
        if action == "on":
            success = await kasa_agent.turn_on(ip)
        elif action == "off":
            success = await kasa_agent.turn_off(ip)
        elif action == "brightness":
            val = data.get('value')
            success = await kasa_agent.set_brightness(ip, val)
        elif action == "color":
            # value is {h, s, v} - convert to tuple for set_color
            h = data.get('value', {}).get('h', 0)
            s = data.get('value', {}).get('s', 100)
            v = data.get('value', {}).get('v', 100)
            success = await kasa_agent.set_color(ip, (h, s, v))

        if success:
            await sio.emit('kasa_update', {
                'ip': ip,
                'is_on': True if action == "on" else (False if action == "off" else None),
                'brightness': data.get('value') if action == "brightness" else None,
            })

        else:
            await sio.emit('error', {'msg': f"Failed to control device {ip}"})

    except Exception as e:
        print(f"Error controlling kasa: {e}")
        await sio.emit('error', {'msg': f"Kasa Control Error: {str(e)}"})


@sio.event
async def get_settings(sid):
    await sio.emit('settings', SETTINGS)


@sio.event
async def update_settings(sid, data):
    # Generic update
    print(f"Updating settings: {data}")

    # Handle specific keys if needed
    if "tool_permissions" in data:
        SETTINGS["tool_permissions"].update(data["tool_permissions"])
        if audio_loop:
            permissions_with_global = {
                "auto_allow_all_tools": SETTINGS.get("auto_allow_all_tools", False)}
            permissions_with_global.update(SETTINGS["tool_permissions"])
            audio_loop.update_permissions(permissions_with_global)

    if "face_auth_enabled" in data:
        SETTINGS["face_auth_enabled"] = data["face_auth_enabled"]
        # If turned OFF, maybe emit auth status true?
        if not data["face_auth_enabled"]:
            await sio.emit('auth_status', {'authenticated': True})
            # Stop auth loop if running?
            if authenticator:
                authenticator.stop()

    if "camera_flipped" in data:
        SETTINGS["camera_flipped"] = data["camera_flipped"]
        print(f"[SERVER] Camera flip set to: {data['camera_flipped']}")

    save_settings()
    # Broadcast new full settings
    await sio.emit('settings', SETTINGS)


# Deprecated/Mapped for compatibility if frontend still uses specific events
@sio.event
async def get_tool_permissions(sid):
    await sio.emit('tool_permissions', SETTINGS["tool_permissions"])


@sio.event
async def update_tool_permissions(sid, data):
    print(f"Updating permissions (legacy event): {data}")
    SETTINGS["tool_permissions"].update(data)
    save_settings()

    if audio_loop:
        permissions_with_global = {
            "auto_allow_all_tools": SETTINGS.get("auto_allow_all_tools", False)}
        permissions_with_global.update(SETTINGS["tool_permissions"])
        audio_loop.update_permissions(permissions_with_global)
    # Broadcast update to all
    await sio.emit('tool_permissions', SETTINGS["tool_permissions"])


@sio.event
async def upload_file(sid, data):
    """
    Handle file upload from client
    data: {
        'filename': str,
        'file_data': base64 encoded file content,
        'file_size': int (bytes)
    }
    """
    try:
        filename = data.get('filename')
        file_data_b64 = data.get('file_data')
        file_size = data.get('file_size', 0)

        print(f"[FILE_UPLOAD] Received file: {filename} ({file_size} bytes)")

        # Validate file
        validation = validate_file(filename, file_size)
        if not validation.get('valid'):
            await sio.emit('error', {'msg': validation.get('error')})
            return

        # Decode file data
        import base64
        file_bytes = base64.b64decode(file_data_b64)

        # Determine storage path - use current project's uploads folder
        if audio_loop and audio_loop.project_manager:
            project_path = audio_loop.project_manager.get_current_project_path()
            uploads_dir = project_path / "uploads"
        else:
            # Fallback to backend/uploads if no project active
            uploads_dir = Path(os.path.dirname(
                os.path.abspath(__file__))) / "uploads"

        uploads_dir.mkdir(exist_ok=True)

        # Save file with unique name if file already exists
        file_path = uploads_dir / filename
        counter = 1
        base_name = Path(filename).stem
        extension = Path(filename).suffix

        while file_path.exists():
            new_name = f"{base_name}_{counter}{extension}"
            file_path = uploads_dir / new_name
            counter += 1

        # Write file to disk
        with open(file_path, 'wb') as f:
            f.write(file_bytes)

        print(f"[FILE_UPLOAD] Saved to: {file_path}")

        # Parse the file
        file_extension = validation.get('extension')
        parsed_result = parse_file(str(file_path), file_extension)

        if not parsed_result.get('success'):
            await sio.emit('error', {'msg': f"Failed to parse file: {parsed_result.get('error')}"})
            # Still keep the file saved, just notify of parse error

        # Generate summary for AI context
        summary = get_file_summary(parsed_result, filename)

        # Send parsed content to AI if session is active
        if audio_loop and audio_loop.session:
            try:
                context_msg = f"System Notification: User uploaded a file. Here is the content:\\n\\n{summary}"
                await audio_loop.session.send(input=context_msg, end_of_turn=True)
                print(f"[FILE_UPLOAD] Sent file content to AI context")
            except Exception as e:
                print(f"[FILE_UPLOAD] Failed to send to AI: {e}")

        # Notify frontend of successful upload
        await sio.emit('file_uploaded', {
            'filename': file_path.name,
            'original_filename': filename,
            'path': str(file_path),
            'size': file_size,
            'type': file_extension,
            'summary': parsed_result.get('summary', ''),
            'success': parsed_result.get('success', False)
        })

        await sio.emit('status', {'msg': f'File uploaded: {filename}'})

    except Exception as e:
        print(f"[FILE_UPLOAD] Error: {e}")
        import traceback
        traceback.print_exc()
        await sio.emit('error', {'msg': f"File upload failed: {str(e)}"})


@sio.event
async def get_uploaded_files(sid):
    """Get list of uploaded files in current project"""
    try:
        if audio_loop and audio_loop.project_manager:
            project_path = audio_loop.project_manager.get_current_project_path()
            uploads_dir = project_path / "uploads"
        else:
            uploads_dir = Path(os.path.dirname(
                os.path.abspath(__file__))) / "uploads"

        if not uploads_dir.exists():
            await sio.emit('uploaded_files_list', [])
            return

        files_list = []
        for file_path in uploads_dir.iterdir():
            if file_path.is_file():
                stat = file_path.stat()
                files_list.append({
                    'filename': file_path.name,
                    'path': str(file_path),
                    'size': stat.st_size,
                    'modified': stat.st_mtime,
                    'extension': file_path.suffix[1:] if file_path.suffix else ''
                })

        await sio.emit('uploaded_files_list', files_list)

    except Exception as e:
        print(f"[FILE_UPLOAD] Error getting files: {e}")
        await sio.emit('error', {'msg': f"Failed to get uploaded files: {str(e)}"})


@sio.event
async def delete_uploaded_file(sid, data):
    """Delete an uploaded file"""
    try:
        filename = data.get('filename')

        if audio_loop and audio_loop.project_manager:
            project_path = audio_loop.project_manager.get_current_project_path()
            uploads_dir = project_path / "uploads"
        else:
            uploads_dir = Path(os.path.dirname(
                os.path.abspath(__file__))) / "uploads"

        file_path = uploads_dir / filename

        if not file_path.exists():
            await sio.emit('error', {'msg': 'File not found'})
            return

        # Security check - ensure file is within uploads directory
        if uploads_dir not in file_path.parents and file_path.parent != uploads_dir:
            await sio.emit('error', {'msg': 'Invalid file path'})
            return

        os.remove(file_path)
        print(f"[FILE_UPLOAD] Deleted: {file_path}")

        await sio.emit('file_deleted', {'filename': filename})
        await sio.emit('status', {'msg': f'Deleted: {filename}'})

    except Exception as e:
        print(f"[FILE_UPLOAD] Error deleting file: {e}")
        await sio.emit('error', {'msg': f"Failed to delete file: {str(e)}"})


# ============================================
# CONTACT MANAGEMENT SOCKET EVENTS
# ============================================

@sio.event
async def get_contacts(sid):
    """Get all contacts"""
    try:
        contacts = contact_manager.list_contacts()
        await sio.emit('contacts_list', contacts)
    except Exception as e:
        print(f"[CONTACTS] Error getting contacts: {e}")
        await sio.emit('error', {'msg': f"Failed to get contacts: {str(e)}"})


@sio.event
async def add_contact(sid, data):
    """
    Add a new contact
    data: {name, phone, email, whatsapp_number, notes}
    """
    try:
        result = contact_manager.add_contact(
            name=data.get('name'),
            phone=data.get('phone'),
            email=data.get('email'),
            whatsapp_number=data.get('whatsapp_number'),
            notes=data.get('notes')
        )

        if result.get('success'):
            # Broadcast updated contact list
            contacts = contact_manager.list_contacts()
            await sio.emit('contacts_list', contacts)
            await sio.emit('status', {'msg': f"Added contact: {result['contact']['name']}"})
        else:
            await sio.emit('error', {'msg': result.get('error')})

    except Exception as e:
        print(f"[CONTACTS] Error adding contact: {e}")
        await sio.emit('error', {'msg': f"Failed to add contact: {str(e)}"})


@sio.event
async def update_contact(sid, data):
    """
    Update existing contact
    data: {id, name, phone, email, whatsapp_number, notes}
    """
    try:
        contact_id = data.get('id')
        if not contact_id:
            await sio.emit('error', {'msg': 'Contact ID is required'})
            return

        # Extract update fields
        updates = {}
        for field in ['name', 'phone', 'email', 'whatsapp_number', 'notes']:
            if field in data:
                updates[field] = data[field]

        result = contact_manager.update_contact(contact_id, **updates)

        if result.get('success'):
            # Broadcast updated contact list
            contacts = contact_manager.list_contacts()
            await sio.emit('contacts_list', contacts)
            await sio.emit('status', {'msg': f"Updated contact: {result['contact']['name']}"})
        else:
            await sio.emit('error', {'msg': result.get('error')})

    except Exception as e:
        print(f"[CONTACTS] Error updating contact: {e}")
        await sio.emit('error', {'msg': f"Failed to update contact: {str(e)}"})


@sio.event
async def delete_contact(sid, data):
    """
    Delete a contact
    data: {id}
    """
    try:
        contact_id = data.get('id')
        if not contact_id:
            await sio.emit('error', {'msg': 'Contact ID is required'})
            return

        result = contact_manager.delete_contact(contact_id)

        if result.get('success'):
            # Broadcast updated contact list
            contacts = contact_manager.list_contacts()
            await sio.emit('contacts_list', contacts)
            await sio.emit('status', {'msg': result.get('message')})
        else:
            await sio.emit('error', {'msg': result.get('error')})

    except Exception as e:
        print(f"[CONTACTS] Error deleting contact: {e}")
        await sio.emit('error', {'msg': f"Failed to delete contact: {str(e)}"})


@sio.event
async def search_contacts(sid, data):
    """
    Search contacts by name or phone
    data: {query}
    """
    try:
        query = data.get('query', '')
        results = contact_manager.search_contacts(query)
        await sio.emit('contacts_search_results', results)
    except Exception as e:
        print(f"[CONTACTS] Error searching contacts: {e}")
        await sio.emit('error', {'msg': f"Search failed: {str(e)}"})


@sio.event
async def import_contacts(sid, data):
    """
    Import contacts from VCF/CSV/JSON file
    data: {file_data: base64, filename, file_type}
    """
    try:
        filename = data.get('filename')
        file_data_b64 = data.get('file_data')
        file_type = data.get('file_type', '').lower()

        print(f"[CONTACTS] Importing from {filename} (type: {file_type})")

        # Decode file data
        import base64
        file_bytes = base64.b64decode(file_data_b64)

        # Save temporary file
        import tempfile
        with tempfile.NamedTemporaryFile(mode='wb', suffix=f'.{file_type}', delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        try:
            if file_type in ['vcf', 'vcard']:
                # Parse VCF file
                vcf_result = parse_vcf_file(tmp_path)
                import_result = contact_manager.import_from_vcf(vcf_result)

                if import_result.get('success'):
                    # Broadcast updated contact list
                    contacts = contact_manager.list_contacts()
                    await sio.emit('contacts_list', contacts)

                    msg = f"Imported {import_result['imported']} contact(s)"
                    if import_result.get('skipped', 0) > 0:
                        msg += f" ({import_result['skipped']} skipped - duplicates or errors)"

                    await sio.emit('status', {'msg': msg})
                    await sio.emit('contacts_import_complete', import_result)
                else:
                    await sio.emit('error', {'msg': import_result.get('error')})

            # TODO: Add CSV/JSON import support in future
            elif file_type == 'csv':
                await sio.emit('error', {'msg': 'CSV import not yet supported'})
            elif file_type == 'json':
                await sio.emit('error', {'msg': 'JSON import not yet supported'})
            else:
                await sio.emit('error', {'msg': f'Unsupported file type: {file_type}'})

        finally:
            # Clean up temp file
            import os
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    except Exception as e:
        print(f"[CONTACTS] Error importing contacts: {e}")
        import traceback
        traceback.print_exc()
        await sio.emit('error', {'msg': f"Import failed: {str(e)}"})


@sio.event
async def export_contacts(sid):
    """Export all contacts as VCF file"""
    try:
        vcf_content = contact_manager.export_to_vcf()

        # Send VCF content to frontend
        await sio.emit('contacts_export_ready', {
            'content': vcf_content,
            'filename': f'contacts_{datetime.now().strftime("%Y%m%d_%H%M%S")}.vcf',
            'count': len(contact_manager.list_contacts())
        })

    except Exception as e:
        print(f"[CONTACTS] Error exporting contacts: {e}")
        await sio.emit('error', {'msg': f"Export failed: {str(e)}"})


# ─────────────────────────────────────────────────────────────────────────────
# SPOTIFY INTEGRATION
# ─────────────────────────────────────────────────────────────────────────────

spotify_agent = SpotifyAgent()

# Restore saved Spotify session on startup (non-blocking)


async def _restore_spotify():
    restored = await spotify_agent.restore_session()
    if restored:
        await sio.emit('spotify_connected', {
            'display_name': spotify_agent.state.display_name,
            'user_id': spotify_agent.state.user_id,
        })
        # Start the now-playing poller
        asyncio.create_task(_now_playing_loop())


async def _now_playing_loop():
    def on_track_update(data):
        asyncio.create_task(sio.emit('now_playing', data))
    await spotify_agent.poll_now_playing(on_track_update)

# Kick off session restore when server starts


@app.on_event("startup")
async def spotify_startup():
    asyncio.create_task(_restore_spotify())


# ── HTTP Routes: OAuth ─────────────────────────────────────────────────────────

@app.get("/spotify/auth/start")
async def spotify_auth_start():
    """Return the Spotify OAuth authorization URL."""
    if not spotify_agent.state.connected:
        url = spotify_agent.start_auth()
        return {"auth_url": url}
    return {"auth_url": None, "already_connected": True, "display_name": spotify_agent.state.display_name}


@app.get("/spotify/callback")
async def spotify_callback(code: str = None, error: str = None):
    """OAuth redirect callback — exchanges code, saves tokens, notifies frontend."""
    from fastapi.responses import HTMLResponse
    if error or not code:
        await sio.emit('spotify_error', {'error': error or 'auth_cancelled'})
        return HTMLResponse("<html><body><script>window.close();</script><p>Auth cancelled.</p></body></html>")
    try:
        profile = await spotify_agent.finish_auth(code)
        await sio.emit('spotify_connected', {
            'display_name': profile['display_name'],
            'user_id': profile['user_id'],
        })
        # Update settings.json
        SETTINGS.setdefault('spotify', {})['connected'] = True
        save_settings()
        # Start now-playing poller
        asyncio.create_task(_now_playing_loop())
        return HTMLResponse("""
        <html><head><title>Spotify Connected</title></head>
        <body style="background:#191414;color:#1DB954;font-family:sans-serif;text-align:center;padding:40px">
            <h2>✅ Spotify Connected!</h2>
            <p style="color:#fff">You can close this tab.</p>
            <script>setTimeout(()=>window.close(),1500);</script>
        </body></html>
        """)
    except Exception as e:
        print(f"[SERVER] Spotify callback error: {e}")
        await sio.emit('spotify_error', {'error': str(e)})
        return HTMLResponse(f"<html><body><p>Error: {e}</p></body></html>")


@app.get("/spotify/token")
async def get_spotify_token():
    """Provide the current access token to the frontend Web Playback SDK."""
    if not spotify_agent.state.connected:
        return {"token": None}
    try:
        # get_token automatically refreshes if needed
        token = await spotify_agent.get_token()
        return {"token": token}
    except Exception as e:
        print(f"[SERVER] Failed to get Spotify token: {e}")
        return {"token": None, "error": str(e)}


# ── SocketIO Events: Spotify ───────────────────────────────────────────────────

@sio.event
async def get_spotify_status(sid):
    """Return current Spotify connection state and immediately push current track."""
    await sio.emit('spotify_status', {
        'connected': spotify_agent.state.connected,
        'display_name': spotify_agent.state.display_name,
        'mood_sync_active': spotify_agent.state.mood_sync_active,
        'current_mood': spotify_agent.state.current_mood,
        'settings': SETTINGS.get('spotify', {}),
    }, room=sid)

    # If a track is already cached (from the background poller), push it immediately
    # so the frontend shows the player without waiting for the next poll cycle
    if spotify_agent.state.connected and spotify_agent.state.current_track_name:
        await sio.emit('now_playing', {
            'track': spotify_agent.state.current_track_name,
            'artist': spotify_agent.state.current_artist,
            'album_art': spotify_agent.state.current_album_art,
            'is_playing': spotify_agent.state.is_playing,
            'progress_ms': spotify_agent.state.progress_ms,
            'duration_ms': spotify_agent.state.duration_ms,
            'device': spotify_agent.state.active_device_name,
            'uri': spotify_agent.state.current_track_uri,
        }, room=sid)


@sio.event
async def disconnect_spotify(sid, data=None):
    """Disconnect Spotify and clear stored tokens."""
    spotify_agent.disconnect()
    SETTINGS.setdefault('spotify', {})['connected'] = False
    save_settings()
    await sio.emit('spotify_disconnected', {})


@sio.event
async def get_spotify_devices(sid):
    """List all available Spotify playback devices."""
    if not spotify_agent.state.connected:
        await sio.emit('spotify_error', {'error': 'not_connected'}, room=sid)
        return
    try:
        devices = await spotify_agent.get_devices()
        await sio.emit('spotify_devices', {'devices': devices}, room=sid)
    except SpotifyPremiumRequired:
        await sio.emit('spotify_error', {'error': 'premium_required'}, room=sid)
    except Exception as e:
        await sio.emit('spotify_error', {'error': str(e)}, room=sid)


@sio.event
async def transfer_spotify_device(sid, data):
    """Transfer Spotify playback to a chosen device."""
    device_id = data.get('device_id')
    if not device_id:
        return
    try:
        await spotify_agent.transfer_playback(device_id)
        spotify_agent.save_preferred_device(device_id)
        SETTINGS.setdefault('spotify', {})['preferred_device_id'] = device_id
        save_settings()
        await sio.emit('spotify_device_transferred', {'device_id': device_id})
    except SpotifyPremiumRequired:
        await sio.emit('spotify_error', {'error': 'premium_required'})
    except SpotifyNoActiveDevice:
        await sio.emit('spotify_error', {'error': 'device_not_found'})
    except Exception as e:
        await sio.emit('spotify_error', {'error': str(e)})


@sio.event
async def get_spotify_playlists(sid):
    """Return the user's Spotify playlists."""
    if not spotify_agent.state.connected:
        await sio.emit('spotify_error', {'error': 'not_connected'}, room=sid)
        return
    try:
        playlists = await spotify_agent.get_playlists()
        simplified = [{'id': p['id'], 'name': p['name'], 'uri': p['uri'],
                       'tracks': p.get('tracks', p.get('items', {})).get('total', 0),
                       'image': p.get('images', [{}])[0].get('url', '') if p.get('images') else ''}
                      for p in playlists if p]
        await sio.emit('spotify_playlists', {'playlists': simplified}, room=sid)
    except Exception as e:
        await sio.emit('spotify_error', {'error': str(e)}, room=sid)


@sio.event
async def get_spotify_playlist_tracks(sid, data):
    """Return tracks for a specific playlist."""
    if not spotify_agent.state.connected:
        await sio.emit('spotify_error', {'error': 'not_connected'}, room=sid)
        return
    playlist_id = data.get('playlist_id')
    if not playlist_id:
        return
    try:
        tracks_data = await spotify_agent.get_playlist_tracks(playlist_id)
        # Parse tracks out of the nested 'track' object
        simplified = []
        for item in tracks_data:
            track = item.get('track')
            if not track:
                continue
            simplified.append({
                'id': track['id'],
                'uri': track['uri'],
                'name': track['name'],
                'artist': ', '.join([a['name'] for a in track.get('artists', [])]),
                'duration_ms': track.get('duration_ms', 0),
                'album': track.get('album', {}).get('name', ''),
                'album_art': track.get('album', {}).get('images', [{}])[0].get('url', '') if track.get('album', {}).get('images') else ''
            })
        await sio.emit('spotify_playlist_tracks', {'playlist_id': playlist_id, 'tracks': simplified}, room=sid)
    except Exception as e:
        err_str = str(e)
        if '403' in err_str or 'Access denied' in err_str or 'denied' in err_str.lower():
            # 403: collaborative/private playlist — send empty list with soft message
            await sio.emit('spotify_playlist_tracks', {'playlist_id': playlist_id, 'tracks': [], 'error': 'Cannot load tracks for this playlist. Try reconnecting Spotify to grant full access.'}, room=sid)
        else:
            await sio.emit('spotify_error', {'error': err_str}, room=sid)


@sio.event
async def play_spotify_playlist(sid, data):
    """Play a specific Spotify playlist."""
    if not spotify_agent.state.connected:
        await sio.emit('spotify_error', {'error': 'not_connected'}, room=sid)
        return

    context_uri = data.get('context_uri')
    if not context_uri:
        await sio.emit('spotify_error', {'error': 'No playlist URI provided'}, room=sid)
        return

    try:
        await spotify_agent.play(context_uri=context_uri)
    except SpotifyPremiumRequired:
        await sio.emit('spotify_error', {'error': 'premium_required'}, room=sid)
    except SpotifyNoActiveDevice:
        await sio.emit('spotify_error', {'error': 'device_not_found'}, room=sid)
    except Exception as e:
        await sio.emit('spotify_error', {'error': str(e)}, room=sid)


@sio.event
async def play_spotify_track(sid, data):
    """Play a specific Spotify track(s)."""
    if not spotify_agent.state.connected:
        await sio.emit('spotify_error', {'error': 'not_connected'}, room=sid)
        return

    uris = data.get('uris')
    if not uris:
        await sio.emit('spotify_error', {'error': 'No track URIs provided'}, room=sid)
        return

    try:
        await spotify_agent.play(uris=uris)
    except SpotifyPremiumRequired:
        await sio.emit('spotify_error', {'error': 'premium_required'}, room=sid)
    except SpotifyNoActiveDevice:
        await sio.emit('spotify_error', {'error': 'device_not_found'}, room=sid)
    except Exception as e:
        await sio.emit('spotify_error', {'error': str(e)}, room=sid)


@sio.event
async def spotify_seek(sid, data):
    """Seek to a position in the current track."""
    if not spotify_agent.state.connected:
        return
    position_ms = data.get('position_ms', 0)
    try:
        await spotify_agent._api_request('PUT', '/me/player/seek', params={'position_ms': int(position_ms)})
    except Exception as e:
        await sio.emit('spotify_error', {'error': str(e)}, room=sid)


@sio.event
async def create_spotify_playlist(sid, data):
    name = data.get('name', 'My Vyra Playlist')
    description = data.get('description', 'Created by VYRA')
    try:
        playlist = await spotify_agent.create_playlist(name, description)
        await sio.emit('spotify_playlist_created', {'playlist': {
            'id': playlist.get('id'), 'name': playlist.get('name'),
            'uri': playlist.get('uri'),
        }})
        # Refresh list
        asyncio.create_task(
            sio.emit('status', {'msg': f"Playlist '{name}' created"}))
    except Exception as e:
        await sio.emit('spotify_error', {'error': str(e)})


@sio.event
async def rename_spotify_playlist(sid, data):
    playlist_id = data.get('playlist_id')
    name = data.get('name')
    if not playlist_id or not name:
        return
    try:
        await spotify_agent.rename_playlist(playlist_id, name)
        await sio.emit('spotify_playlist_renamed', {'playlist_id': playlist_id, 'name': name})
    except Exception as e:
        await sio.emit('spotify_error', {'error': str(e)})


@sio.event
async def delete_spotify_playlist(sid, data):
    playlist_id = data.get('playlist_id')
    if not playlist_id:
        return
    try:
        await spotify_agent.delete_playlist(playlist_id)
        await sio.emit('spotify_playlist_deleted', {'playlist_id': playlist_id})
    except Exception as e:
        await sio.emit('spotify_error', {'error': str(e)})


@sio.event
async def spotify_play(sid, data=None):
    try:
        context_uri = data.get('context_uri') if data else None
        uris = data.get('uris') if data else None
        await spotify_agent.play(context_uri=context_uri, uris=uris)
    except SpotifyPremiumRequired:
        await sio.emit('spotify_error', {'error': 'premium_required'})
    except Exception as e:
        await sio.emit('spotify_error', {'error': str(e)})


@sio.event
async def spotify_pause(sid, data=None):
    try:
        await spotify_agent.pause()
    except Exception as e:
        await sio.emit('spotify_error', {'error': str(e)})


@sio.event
async def spotify_next(sid, data=None):
    try:
        await spotify_agent.next_track()
    except Exception as e:
        await sio.emit('spotify_error', {'error': str(e)})


@sio.event
async def spotify_prev(sid, data=None):
    try:
        await spotify_agent.prev_track()
    except Exception as e:
        await sio.emit('spotify_error', {'error': str(e)})


@sio.event
async def spotify_shuffle(sid, data):
    state = data.get('state', True)
    try:
        await spotify_agent.set_shuffle(state)
    except Exception as e:
        await sio.emit('spotify_error', {'error': str(e)})


@sio.event
async def spotify_repeat(sid, data):
    mode = data.get('mode', 'off')
    try:
        await spotify_agent.set_repeat(mode)
    except Exception as e:
        await sio.emit('spotify_error', {'error': str(e)})


@sio.event
async def spotify_volume(sid, data):
    volume = data.get('volume_percent', 50)
    try:
        await spotify_agent.set_volume(int(volume))
    except Exception as e:
        await sio.emit('spotify_error', {'error': str(e)})


@sio.event
async def trigger_spotify_mood_sync(sid, data):
    """Manually trigger mood sync from frontend."""
    emotion = data.get('emotion', 'neutral')
    personality = data.get('personality', 'professional')
    result = await run_mood_sync(spotify_agent, emotion, personality)
    await sio.emit('mood_sync_applied', result)


@sio.event
async def create_spotify_mood_playlist(sid, data):
    """Create a VYRA-curated mood playlist."""
    from mood_music_mapper import create_vyra_mood_playlist
    emotion = data.get('emotion', 'happy')
    playlist_id = await create_vyra_mood_playlist(spotify_agent, emotion)
    if playlist_id:
        await sio.emit('status', {'msg': f'Created VYRA – {emotion.title()} playlist!'})
    else:
        await sio.emit('spotify_error', {'error': 'Failed to create playlist'})


@sio.event
async def update_spotify_settings(sid, data):
    """Update spotify settings block (mood_sync_enabled, volume_mood_adjust, etc)."""
    spotify_settings = SETTINGS.setdefault('spotify', {})
    for key, val in data.items():
        spotify_settings[key] = val
    save_settings()
    await sio.emit('settings', SETTINGS, room=sid)


# Expose spotify_agent for use in AudioLoop
def get_spotify_agent() -> SpotifyAgent:
    return spotify_agent


# =============================================================================
# DASHBOARD & WORKFLOW REST API ROUTES
# All routes below are newly added to power the frontend dashboard and
# workflow pages. Vyra controls workflows via SocketIO events at the bottom.
# =============================================================================

from workflow_engine import get_db, get_executor, NODE_CATALOG
from fastapi import Body
import platform
import psutil  # optional — gracefully degraded below

# ── /api/health ───────────────────────────────────────────────────────────────

@app.get("/api/health")
async def api_health():
    """System health snapshot for the dashboard."""
    started_at_ts = getattr(api_health, "_started_at", None)
    if started_at_ts is None:
        api_health._started_at = time.time()
        started_at_ts = api_health._started_at

    uptime = time.time() - started_at_ts

    # Memory info (best-effort, no hard dependency on psutil)
    mem_info = {"heapUsed": 0, "heapTotal": 0, "rss": 0}
    try:
        import psutil as _psutil
        proc = _psutil.Process(os.getpid())
        info = proc.memory_info()
        mem_info = {"heapUsed": info.rss, "heapTotal": info.vms, "rss": info.rss}
    except Exception:
        pass

    # Database info
    db = get_db()
    db_size = 0
    try:
        db_size = os.path.getsize(db.db_path)
    except Exception:
        pass

    services: Dict[str, str] = {
        "vyra": "online" if audio_loop else "offline",
        "spotify": "connected" if spotify_agent.state.connected else "disconnected",
        "workflow_engine": "online",
    }

    return {
        "uptime": uptime,
        "startedAt": started_at_ts * 1000,  # ms
        "services": services,
        "memory": mem_info,
        "database": {"connected": True, "size": db_size},
        "platform": platform.system(),
    }


# ── /api/agents ───────────────────────────────────────────────────────────────

@app.get("/api/agents")
async def api_agents():
    """Return the list of active agents (from audio_loop if running)."""
    agents = []
    if audio_loop:
        try:
            # AudioLoop exposes an agent registry when agents are present
            registry = getattr(audio_loop, "agent_registry", None) or getattr(audio_loop, "agents", None)
            if registry and isinstance(registry, dict):
                for agent_id, agent_obj in registry.items():
                    agents.append({
                        "id": agent_id,
                        "role": {"id": getattr(agent_obj, "role_id", agent_id), "name": getattr(agent_obj, "name", agent_id)},
                        "status": "active",
                        "current_task": getattr(agent_obj, "current_task", None),
                        "created_at": int(time.time() * 1000),
                    })
        except Exception:
            pass

        # Fallback: expose the full roster of active and available simulated agents
        if not agents:
            _ts = int(time.time() * 1000)
            agents = [
                {"id": "personal-assistant", "role": {"id": "personal-assistant", "name": "Personal Assistant"}, "status": "active", "current_task": "Listening…", "created_at": _ts},
                {"id": "vyra", "role": {"id": "vyra", "name": "VYRA"}, "status": "active", "current_task": "Listening…", "created_at": _ts},
                {"id": "software-engineer", "role": {"id": "software-engineer", "name": "Software Engineer"}, "status": "idle", "current_task": None, "created_at": _ts},
                {"id": "research-analyst", "role": {"id": "research-analyst", "name": "Research Analyst"}, "status": "idle", "current_task": None, "created_at": _ts},
                {"id": "content-writer", "role": {"id": "content-writer", "name": "Content Writer"}, "status": "idle", "current_task": None, "created_at": _ts},
                {"id": "data-analyst", "role": {"id": "data-analyst", "name": "Data Analyst"}, "status": "idle", "current_task": None, "created_at": _ts},
                {"id": "system-administrator", "role": {"id": "system-administrator", "name": "System Administrator"}, "status": "idle", "current_task": None, "created_at": _ts},
                {"id": "legal-advisor", "role": {"id": "legal-advisor", "name": "Legal Advisor"}, "status": "idle", "current_task": None, "created_at": _ts},
                {"id": "financial-analyst", "role": {"id": "financial-analyst", "name": "Financial Analyst"}, "status": "idle", "current_task": None, "created_at": _ts},
                {"id": "hr-specialist", "role": {"id": "hr-specialist", "name": "HR Specialist"}, "status": "idle", "current_task": None, "created_at": _ts},
                {"id": "project-coordinator", "role": {"id": "project-coordinator", "name": "Project Coordinator"}, "status": "idle", "current_task": None, "created_at": _ts},
                {"id": "marketing-strategist", "role": {"id": "marketing-strategist", "name": "Marketing Strategist"}, "status": "idle", "current_task": None, "created_at": _ts},
                {"id": "customer-support", "role": {"id": "customer-support", "name": "Customer Support"}, "status": "idle", "current_task": None, "created_at": _ts},
            ]
    return agents


# ── /api/session ──────────────────────────────────────────────────────────────

@app.get("/api/session/state")
async def api_session_state_get():
    """Return the current session state (last route, VS Code workspace, etc.)."""
    from services import session_store
    return session_store.load()


@app.post("/api/session/state")
async def api_session_state_post(body: dict = Body(...)):
    """Merge incoming fields into the session state and persist."""
    from services import session_store
    state = session_store.load()
    for key, value in body.items():
        state[key] = value
    session_store.save(state)
    return {"ok": True}


@app.post("/api/session/route")
async def api_session_route(body: dict = Body(...)):
    """Update the last visited route."""
    route = body.get("route", "")
    if route:
        from services import session_store
        session_store.update_route(route)
    return {"ok": True}


@app.post("/api/session/restore")
async def api_session_restore():
    """Restore the last VS Code workspace and return the last route."""
    from services import session_store
    state = session_store.load()
    vscode_result = await asyncio.to_thread(session_store.restore_vscode_workspace)
    return {
        "last_route": state.get("last_route", "dashboard"),
        "vscode": vscode_result,
        "workspace_name": state.get("vscode", {}).get("workspace_name", ""),
    }


# ── /api/vault/entities ───────────────────────────────────────────────────────

@app.get("/api/vault/entities")
async def api_vault_entities():
    """Return memory entities from RAG memory store."""
    try:
        from rag_memory import RAGMemory
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        rag = RAGMemory(data_dir=os.path.join(backend_dir, "data"))
        # Try get_all_entities or fallback to empty
        if hasattr(rag, "get_all_entities"):
            entities = rag.get_all_entities()
        elif hasattr(rag, "list_entities"):
            entities = rag.list_entities()
        else:
            entities = []
        # Normalise to expected shape
        result = []
        for e in entities:
            if isinstance(e, dict):
                result.append({
                    "id": e.get("id", str(uuid.uuid4())),
                    "type": e.get("type", "concept"),
                    "name": e.get("name", e.get("title", "Unknown")),
                    "description": e.get("description", e.get("summary", "")),
                    "created_at": e.get("created_at", time.time()) * 1000 if isinstance(e.get("created_at", 0), float) and e.get("created_at", 0) < 1e12 else e.get("created_at", int(time.time() * 1000)),
                    "updated_at": e.get("updated_at", time.time()) * 1000 if isinstance(e.get("updated_at", 0), float) and e.get("updated_at", 0) < 1e12 else e.get("updated_at", int(time.time() * 1000)),
                })
        return result
    except Exception as ex:
        print(f"[SERVER] /api/vault/entities error: {ex}")
        return []


# ── /api/goals ────────────────────────────────────────────────────────────────

async def _goal_event_broadcast(action: str, goal: dict):
    """Broadcast a goal event to SocketIO and WebSocket clients."""
    event = {
        "type": action,
        "goalId": goal.get("id") if goal else None,
        "data": goal or {},
        "timestamp": time.time() * 1000,
    }
    await sio.emit("goal_event", event)
    await _ws_manager.broadcast({
        "type": "goal_event",
        "payload": event,
        "timestamp": event["timestamp"],
    })

@app.get("/api/goals")
async def api_list_goals(status: Optional[str] = None, limit: int = 50):
    db = get_db()
    return db.list_goals(status=status, limit=limit)


@app.post("/api/goals")
async def api_create_goal(body: dict = Body(...)):
    db = get_db()
    goal = db.create_goal(
        title=body.get("title", "Untitled Goal"),
        description=body.get("description", ""),
        score=float(body.get("score", 0.0)),
        status=body.get("status", "active"),
        health=body.get("health", "on_track"),
        level=body.get("level", "strategic"),
        deadline=body.get("deadline"),
    )
    asyncio.create_task(_goal_event_broadcast("created", goal))
    return goal


@app.patch("/api/goals/{goal_id}")
async def api_update_goal(goal_id: str, body: dict = Body(...)):
    db = get_db()
    goal = db.update_goal(goal_id, **body)
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    asyncio.create_task(_goal_event_broadcast("updated", goal))
    return goal


@app.delete("/api/goals/{goal_id}")
async def api_delete_goal(goal_id: str):
    db = get_db()
    db.delete_goal(goal_id)
    asyncio.create_task(_goal_event_broadcast("deleted", {"id": goal_id}))
    return {"ok": True}


# ── /api/workflows — CRUD ─────────────────────────────────────────────────────

@app.get("/api/workflows/nodes")
async def api_workflow_nodes():
    """Return the node type catalog for the frontend drag-and-drop palette."""
    return NODE_CATALOG


@app.get("/api/workflows")
async def api_list_workflows():
    db = get_db()
    return db.list_workflows()


@app.post("/api/workflows")
async def api_create_workflow(body: dict = Body(...)):
    db = get_db()
    wf = db.create_workflow(
        name=body.get("name", "Untitled Workflow"),
        description=body.get("description", ""),
        definition=body.get("definition"),
        tags=body.get("tags", []),
    )
    return wf


@app.get("/api/workflows/{wf_id}")
async def api_get_workflow(wf_id: str):
    db = get_db()
    wf = db.get_workflow(wf_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return wf


@app.patch("/api/workflows/{wf_id}")
async def api_update_workflow(wf_id: str, body: dict = Body(...)):
    db = get_db()
    wf = db.update_workflow(wf_id, **body)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return wf


@app.delete("/api/workflows/{wf_id}")
async def api_delete_workflow(wf_id: str):
    db = get_db()
    db.delete_workflow(wf_id)
    return {"ok": True}


# ── /api/workflows/{id}/versions ──────────────────────────────────────────────

@app.get("/api/workflows/{wf_id}/versions")
async def api_list_versions(wf_id: str):
    db = get_db()
    return db.list_versions(wf_id)


@app.post("/api/workflows/{wf_id}/versions")
async def api_create_version(wf_id: str, body: dict = Body(...)):
    db = get_db()
    wf = db.get_workflow(wf_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    definition = body.get("definition", {})
    changelog = body.get("changelog")
    version = db.create_version(wf_id, definition, changelog)
    return version


# ── /api/workflows/{id}/executions ────────────────────────────────────────────

@app.get("/api/workflows/{wf_id}/executions")
async def api_list_executions(wf_id: str, limit: int = 20):
    db = get_db()
    return db.list_executions(wf_id, limit=limit)


@app.get("/api/workflows/executions/{exec_id}")
async def api_get_execution(exec_id: str):
    """Return details of a single execution (steps reconstructed from workflow events)."""
    db = get_db()
    with db._connect() as conn:
        row = conn.execute(
            "SELECT * FROM workflow_executions WHERE id=?", (exec_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Execution not found")
    exec_data = dict(row)
    # Since we don't store per-step rows, reconstruct minimal steps from status
    steps = []
    if exec_data.get("error"):
        steps = [{
            "id": str(uuid.uuid4()),
            "node_id": "unknown",
            "node_type": "unknown",
            "status": "failed",
            "error_message": exec_data.get("error"),
            "retry_count": 0,
            "started_at": exec_data.get("started_at"),
            "completed_at": exec_data.get("finished_at"),
        }]
    return {"execution": exec_data, "steps": steps}


# ── /api/workflows/{id}/execute ───────────────────────────────────────────────

async def _workflow_event_broadcast(event: dict):
    """Broadcast a workflow step/execution event to SocketIO AND plain /ws clients."""
    # SocketIO clients (SocketIO native protocol)
    await sio.emit("workflow_event", event)
    # Plain WebSocket clients (React useWebSocket hook)
    await _ws_manager.broadcast({
        "type": "workflow_event",
        "payload": event,
        "timestamp": event.get("timestamp", time.time() * 1000),
    })


@app.post("/api/workflows/{wf_id}/execute")
async def api_execute_workflow(wf_id: str):
    """Run a workflow asynchronously. Returns immediately; events stream via SocketIO."""
    db = get_db()
    wf = db.get_workflow(wf_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if not wf.get("enabled", True):
        raise HTTPException(status_code=400, detail="Workflow is disabled")

    executor = get_executor(event_callback=_workflow_event_broadcast)
    asyncio.create_task(executor.execute(wf_id))
    return {"ok": True, "message": "Workflow execution started"}


# ── /api/workflows/{id}/chat — NL sidebar (Vyra-powered) ─────────────────────

@app.post("/api/workflows/{wf_id}/chat")
async def api_workflow_chat(wf_id: str, body: dict = Body(...)):
    """
    NL chat sidebar: user sends a message, Vyra responds with a definition update
    or a descriptive answer. Uses Gemini directly (no audio loop required).
    """
    message = body.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    db = get_db()
    wf = db.get_workflow(wf_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    version_data = db.get_latest_version(wf_id)
    definition_str = json.dumps(version_data["definition"], indent=2) if version_data else "{}"

    prompt = f"""You are Vyra, an AI assistant helping the user design a workflow called "{wf.get('name')}".

Current workflow definition (JSON):
{definition_str}

User request: {message}

Respond in JSON with this structure:
{{
  "reply": "Your conversational reply explaining what you did or what the user should do next",
  "definition_update": null or a complete updated workflow definition object (same shape as above)
}}

If the user is asking a question or something that doesn't require changing the definition, set definition_update to null.
Only return valid JSON, no markdown fences."""

    try:
        if api_client:
            response = api_client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=[{"role": "user", "parts": [{"text": prompt}]}],
            )
            raw = response.text.strip()
            # Strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            result = json.loads(raw)
        else:
            result = {"reply": "Vyra API not configured. Please add your Gemini API key.", "definition_update": None}
    except Exception as ex:
        print(f"[SERVER] Workflow chat error: {ex}")
        result = {"reply": f"I encountered an error: {ex}", "definition_update": None}

    # If Vyra updated the definition, save a new version
    if result.get("definition_update"):
        try:
            db.create_version(wf_id, result["definition_update"], changelog=f"AI: {message[:60]}")
        except Exception as ex:
            print(f"[SERVER] Failed to save AI-updated version: {ex}")

    return result


# =============================================================================
# VYRA WORKFLOW CONTROL — SocketIO events
# These let Vyra manage workflows by voice / text commands.
# =============================================================================

@sio.event
async def workflow_list(sid, data=None):
    """Vyra can ask for the workflow list."""
    db = get_db()
    workflows = db.list_workflows()
    await sio.emit("workflow_list", workflows, room=sid)


@sio.event
async def workflow_create(sid, data):
    """Vyra creates a new workflow."""
    db = get_db()
    name = data.get("name", "Unnamed Workflow")
    description = data.get("description", "")
    wf = db.create_workflow(name=name, description=description)
    await sio.emit("workflow_created", wf)
    await sio.emit("status", {"msg": f"Workflow '{name}' created"})


@sio.event
async def workflow_run(sid, data):
    """Vyra runs a workflow by id or by name."""
    db = get_db()
    wf_id = data.get("id")
    name = data.get("name")

    if not wf_id and name:
        workflows = db.list_workflows()
        match = next((w for w in workflows if w["name"].lower() == name.lower()), None)
        if match:
            wf_id = match["id"]

    if not wf_id:
        await sio.emit("error", {"msg": f"Workflow not found: {name or 'unknown'}"})
        return

    wf = db.get_workflow(wf_id)
    if not wf:
        await sio.emit("error", {"msg": "Workflow not found"})
        return
    if not wf.get("enabled", True):
        await sio.emit("error", {"msg": f"Workflow '{wf['name']}' is disabled"})
        return

    await sio.emit("status", {"msg": f"Running workflow: {wf['name']}"})
    executor = get_executor(event_callback=_workflow_event_broadcast)
    asyncio.create_task(executor.execute(wf_id))


@sio.event
async def workflow_toggle(sid, data):
    """Vyra enables or disables a workflow."""
    db = get_db()
    wf_id = data.get("id")
    enabled = data.get("enabled")
    if wf_id is None or enabled is None:
        await sio.emit("error", {"msg": "workflow_toggle requires id and enabled"})
        return
    wf = db.update_workflow(wf_id, enabled=enabled)
    if not wf:
        await sio.emit("error", {"msg": "Workflow not found"})
        return
    state = "enabled" if enabled else "disabled"
    await sio.emit("status", {"msg": f"Workflow '{wf['name']}' {state}"})
    await sio.emit("workflow_toggled", wf)


@app.get("/api/vyra/status")
async def api_vyra_status():
    """Return VYRA's current runtime status + memory stats for the JARVIS dashboard."""
    import os
    from pathlib import Path

    status: dict = {
        "online": False,
        "personality_mode": "unknown",
        "speaker_mode": "unknown",
        "vault_context_cached": False,
        "memory": {
            "people_count": 0,
            "facts_count": 0,
            "preferences_count": 0,
            "rag_chunks": 0,
            "rag_model": "local:all-MiniLM-L6-v2",
        },
        "last_sync": None,
    }

    # Check if AudioLoop is running
    try:
        from vyra import _jarvis_vault_context  # type: ignore
        status["vault_context_cached"] = bool(_jarvis_vault_context)
    except Exception:
        pass

    # Read user_memory.json for stats
    try:
        mem_path = Path(__file__).parent / "data" / "user_memory.json"
        if mem_path.exists():
            import json as _j
            with open(mem_path, "r", encoding="utf-8") as f:
                mem = _j.load(f)
            status["online"] = True
            status["memory"]["people_count"] = len(mem.get("important_people", []))
            status["memory"]["facts_count"] = len(mem.get("important_facts", []))
            status["memory"]["preferences_count"] = len(mem.get("preferences", {}))
            status["last_sync"] = mem.get("metadata", {}).get("last_updated")
    except Exception:
        pass

    # Read RAG chunk count from rag_store.json
    try:
        import json as _j
        rag_path = Path(__file__).parent / "data" / "rag_store.json"
        if rag_path.exists():
            with open(rag_path, "r", encoding="utf-8") as f:
                rag_data = _j.load(f)
            status["memory"]["rag_chunks"] = rag_data.get("total", len(rag_data.get("chunks", [])))
    except Exception:
        pass

    return status


@app.post("/api/vyra/sync")
async def api_vyra_sync():
    return {"success": False, "error": "Jarvis integration removed"}


@app.get("/api/vyra/rag/search")
async def api_vyra_rag_search(q: str = "", k: int = 5):
    """Semantic search across VYRA's RAG vector store.
    Allows JARVIS agents and the UI to query VYRA's conversation memory."""
    if not q or len(q.strip()) < 3:
        return {"results": [], "error": "Query too short (min 3 chars)"}
    try:
        from rag_memory import RagMemory  # type: ignore
        rag = RagMemory(data_dir=str(Path(__file__).parent / "data"))
        results = await rag.search(query=q.strip(), k=min(k, 20))
        return {"results": results, "total_chunks": len(rag.chunks)}
    except Exception as e:
        return {"results": [], "error": str(e)}


# =============================================================================
# UNIFIED MEMORY — Single AGI-like Memory API
# =============================================================================

# Lazy singleton for UnifiedMemory
_unified_memory_instance = None

def _get_unified_memory():
    global _unified_memory_instance
    if _unified_memory_instance is None:
        from unified_memory import UnifiedMemory
        _unified_memory_instance = UnifiedMemory(data_dir=os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "data"))
    return _unified_memory_instance


@app.get("/api/memory/graph")
async def api_memory_graph():
    """Return full knowledge graph for D3 visualization."""
    try:
        mem = _get_unified_memory()
        return mem.get_graph_data()
    except Exception as e:
        return {"nodes": [], "links": [], "error": str(e)}


@app.get("/api/memory/stats")
async def api_memory_stats():
    """Return comprehensive memory statistics."""
    try:
        mem = _get_unified_memory()
        return {"success": True, **mem.get_stats()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/memory/search")
async def api_memory_search(request: Request):
    """Unified search across all memory layers (semantic + graph + keyword)."""
    try:
        body = await request.json()
        query = body.get("query", "")
        k = body.get("k", 10)
        entity_type = body.get("entity_type")

        if not query:
            return {"results": [], "error": "query is required"}

        mem = _get_unified_memory()
        results = await mem.search(query=query, k=k, entity_type=entity_type)
        return {"results": results, "count": len(results)}
    except Exception as e:
        return {"results": [], "error": str(e)}


@app.get("/api/memory/entity/{entity_id}")
async def api_memory_entity(entity_id: str):
    """Get a single entity with all facts, connections, and metadata."""
    try:
        mem = _get_unified_memory()
        entity = mem.get_entity(entity_id)
        if not entity:
            return {"error": "Entity not found"}

        connections = mem.get_connections(entity_id)
        return {
            "success": True,
            **entity.to_dict(),
            "connections": connections,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/memory/store")
async def api_memory_store(request: Request):
    """Store a new entity or add facts to an existing one."""
    try:
        body = await request.json()
        name = body.get("name", "").strip()
        if not name:
            return {"error": "name is required"}

        mem = _get_unified_memory()
        eid = mem.store_entity(
            name=name,
            entity_type=body.get("type", "concept"),
            facts=body.get("facts", []),
            notes=body.get("notes", ""),
            priority=body.get("priority", 3),
            connections=body.get("connections", []),
        )
        return {"success": True, "entity_id": eid}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/memory/store")
async def api_memory_store_get():
    """Return full memory store data (preferences, rules, people, entities)."""
    try:
        mem = _get_unified_memory()
        # Force a reload from disk so extraction loops running offline or in other scopes sync perfectly
        mem._load()
        
        entities = []
        for eid, e in mem.entities.items():
            entities.append({
                "name": e.name,
                "type": e.entity_type,
                "fact_count": len(e.facts),
                "priority": e.priority,
                "facts": e.facts,
            })
        people = [
            {
                "name": e.name,
                "relation": next((f for f in e.facts if "relation" in f.lower()), e.notes),
                "notes": next((f for f in e.facts if "notes" in f.lower() or "mentioned" in f.lower()), ""),
            }
            for e in mem.entities.values()
            if e.entity_type == "person"
        ]
        return {
            "preferences": mem.preferences,
            "behavioral_rules": mem.behavioral_rules,
            "people": people,
            "entities": entities,
        }
    except Exception as e:
        return {"preferences": {}, "behavioral_rules": [], "people": [], "entities": [], "error": str(e)}



@app.post("/api/memory/sync-obsidian")
async def api_memory_sync_obsidian(request: Request):
    """Export unified memory to Obsidian vault."""
    try:
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        vault_path = body.get("vault_path") if body else None

        from obsidian_exporter import export_to_obsidian
        result = await asyncio.to_thread(export_to_obsidian, vault_path)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


# Keep old obsidian endpoints as aliases for backwards compatibility
@app.post("/api/obsidian/sync")
async def api_obsidian_sync(request: Request):
    """Legacy alias — redirect to unified memory sync."""
    return await api_memory_sync_obsidian(request)


@app.get("/api/obsidian/graph")
async def api_obsidian_graph():
    """Legacy alias — use unified memory graph."""
    return await api_memory_graph()


@app.get("/api/obsidian/status")
async def api_obsidian_status():
    """Return Obsidian vault status."""
    try:
        from obsidian_exporter import get_obsidian_status
        return await asyncio.to_thread(get_obsidian_status)
    except Exception as e:
        return {"vault_path": "", "vault_exists": False, "error": str(e)}


@app.post("/api/obsidian/settings")
async def api_obsidian_settings(body: dict = Body(...)):
    """Update Obsidian vault settings."""
    try:
        from obsidian_exporter import set_vault_path, _load_settings, _save_settings
        vault_path = body.get("vault_path")
        if vault_path:
            set_vault_path(vault_path)
        auto_sync = body.get("auto_sync")
        if auto_sync is not None:
            settings = _load_settings()
            settings["auto_sync"] = bool(auto_sync)
            _save_settings(settings)
        from obsidian_exporter import get_obsidian_status
        return get_obsidian_status()
    except Exception as e:
        return {"error": str(e)}


# ── Phase 13: Brain Memory Endpoints ─────────────────────────────────────────

@app.get("/api/memory/health")
async def api_memory_health():
    """Memory health scores (5 dimensions + overall) + 30-day trend."""
    try:
        from memory.memory_health import get_memory_health_monitor
        mhm  = get_memory_health_monitor()
        snap = mhm.compute_snapshot()
        trend = mhm.get_trend(days=30)
        return {
            "success": True,
            "overall": snap.to_score_100(),
            "dimensions": {
                "encoding":      round(snap.encoding_health * 100),
                "retention":     round(snap.retention_health * 100),
                "consolidation": round(snap.consolidation_health * 100),
                "growth":        round(snap.growth_rate * 100),
                "retrieval":     round(snap.retrieval_quality * 100),
            },
            "trend": [
                {
                    "timestamp": s.timestamp,
                    "overall": s.to_score_100(),
                    "encoding": round(s.encoding_health * 100),
                    "retention": round(s.retention_health * 100),
                    "consolidation": round(s.consolidation_health * 100),
                    "growth": round(s.growth_rate * 100),
                    "retrieval": round(s.retrieval_quality * 100),
                }
                for s in trend
            ],
        }
    except Exception as e:
        return {"success": False, "error": str(e), "overall": 50, "dimensions": {}, "trend": []}


@app.get("/api/memory/forgetting")
async def api_memory_forgetting():
    """Retention distribution + at-risk entity list."""
    try:
        from memory.forgetting_curve import get_forgetting_curve
        fc   = get_forgetting_curve()
        dist = fc.get_distribution()
        at_risk = [
            {
                "entity_id": r.entity_id,
                "entity_name": r.entity_name,
                "retention": round(r.retention_score(), 3),
                "strength": r.strength_label(),
                "stability_days": round(r.stability, 1),
                "review_count": r.review_count,
            }
            for r in fc.get_at_risk_memories(threshold=0.40)[:20]
        ]
        return {
            "success": True,
            "distribution": dist,
            "total_tracked": len(fc._records),
            "mean_retention": round(fc.mean_retention(), 3),
            "at_risk": at_risk,
            "all_scores": fc.get_all_scores()[:50],
        }
    except Exception as e:
        return {"success": False, "error": str(e), "distribution": {}, "at_risk": []}


@app.get("/api/memory/timeline")
async def api_memory_timeline():
    """Weekly entity + episode counts for growth chart (last 12 weeks)."""
    try:
        from memory.episodic_memory import get_episodic_memory
        from unified_memory import get_unified_memory
        import math as _math
        from datetime import timedelta

        mem   = get_episodic_memory()
        um    = get_unified_memory()
        now   = datetime.utcnow()

        weekly = []
        for week_back in range(11, -1, -1):
            week_start = (now - timedelta(weeks=week_back + 1)).isoformat()
            week_end   = (now - timedelta(weeks=week_back)).isoformat()
            label      = (now - timedelta(weeks=week_back)).strftime("W%U")
            episodes   = [e for e in mem.recent(n=5000)
                          if week_start <= e.timestamp <= week_end]
            # Entity creation approximated from access_count + updated_at
            entities_added = sum(
                1 for e in um.entities.values()
                if week_start <= datetime.utcfromtimestamp(e.updated_at).isoformat() <= week_end
            ) if hasattr(um, "entities") else 0
            weekly.append({
                "week": label,
                "episodes": len(episodes),
                "entities": entities_added,
            })

        return {"success": True, "weekly": weekly}
    except Exception as e:
        return {"success": False, "error": str(e), "weekly": []}


@app.get("/api/memory/brain-map")
async def api_memory_brain_map():
    """Domain knowledge depth map for radial chart."""
    try:
        from unified_memory import get_unified_memory
        from memory.semantic_memory import get_semantic_memory

        um   = get_unified_memory()
        sm   = get_semantic_memory()
        stats = um.get_stats() if hasattr(um, "get_stats") else {}
        type_counts = stats.get("type_counts", {})

        domains = []
        for entity_type, count in type_counts.items():
            domains.append({
                "name": entity_type,
                "entity_count": count,
                "depth": min(1.0, count / 20.0),
                "type": "entity",
            })

        # Add semantic concept domains
        for c in sm.get_all_concepts()[:10]:
            domains.append({
                "name": c["concept"],
                "entity_count": c["fact_count"],
                "depth": c["depth"],
                "type": "semantic",
            })

        return {"success": True, "domains": domains}
    except Exception as e:
        return {"success": False, "error": str(e), "domains": []}


@app.get("/api/memory/improvement")
async def api_memory_improvement():
    """Week-over-week improvement report."""
    try:
        from memory.memory_health import get_memory_health_monitor
        mhm    = get_memory_health_monitor()
        report = mhm.get_improvement_report()
        return {"success": True, **report}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/memory/recall")
async def api_memory_recall(body: dict = Body(...)):
    """Record that an entity was retrieved (updates forgetting curve stability)."""
    try:
        from memory.forgetting_curve import get_forgetting_curve
        fc = get_forgetting_curve()
        entity_id      = body.get("entity_id", "")
        entity_name    = body.get("entity_name", entity_id)
        was_successful = body.get("was_successful", True)
        if entity_id:
            fc.record_access(entity_id, entity_name, was_successful)
        return {"success": True, "entity_id": entity_id,
                "new_retention": round(fc.get_retention_score(entity_id), 3)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/memory/semantic")
async def api_memory_semantic():
    """All semantic facts, contradiction list, concept tree."""
    try:
        from memory.semantic_memory import get_semantic_memory
        sm = get_semantic_memory()
        contradictions = [
            {"a": f"{a.concept}.{a.property}={a.value}",
             "b": f"{b.concept}.{b.property}={b.value}"}
            for a, b in sm.detect_contradictions()
        ]
        return {
            "success": True,
            "concepts": sm.get_all_concepts(),
            "contradictions": contradictions,
            "snapshot": sm.snapshot(),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "concepts": []}


@app.get("/api/memory/consolidation-log")
async def api_memory_consolidation_log():
    """Recent consolidation cycle history for dashboard feed."""
    try:
        from memory.consolidation import get_consolidator
        c = get_consolidator()
        return {
            "success": True,
            "cycles": list(reversed(c._cycle_history)),
            "last_cycle": c._last_cycle_stats or {},
        }
    except Exception as e:
        return {"success": False, "error": str(e), "cycles": []}


# ── End Phase 13 Endpoints ────────────────────────────────────────────────────


# ─── Phase 15: VYRA Inner Life Endpoints ─────────────────────────────────────

@app.get("/api/vyra/consciousness")
async def api_vyra_consciousness():
    """Deep emotional state + full working memory with decay/source data."""
    try:
        from consciousness.emotional_core import get_emotional_core
        from consciousness.working_memory import get_working_memory
        import time, dataclasses
        ec = get_emotional_core()
        wm = get_working_memory()
        es = ec.get_snapshot()
        # Deep WM: include source, tags, decay_minutes, last_accessed per chunk
        now = time.time()
        deep_chunks = []
        for c in wm._slots:
            decay_rate = 0.08  # activation lost per minute
            minutes_since = (now - c.last_accessed) / 60.0
            minutes_until_zero = c.activation / max(decay_rate, 0.001)
            deep_chunks.append({
                "id": c.id,
                "content": c.content,
                "category": c.category,
                "activation": round(c.activation, 3),
                "source": c.source,
                "tags": c.tags,
                "created_at": c.created_at,
                "last_accessed": c.last_accessed,
                "minutes_since_access": round(minutes_since, 1),
                "minutes_until_fade": round(max(0, minutes_until_zero - minutes_since), 1),
            })
        return {
            "success": True,
            "emotional": {**es, "last_updated": ec.state.last_updated},
            "working_memory": {
                "chunks": deep_chunks,
                "capacity": 6,
                "slots_used": len(deep_chunks),
                "current_task": wm.current_task(),
            },
        }
    except Exception as e:
        return {
            "success": False, "error": str(e),
            "emotional": {
                "curiosity": 0.5, "satisfaction": 0.5, "frustration": 0.1,
                "excitement": 0.4, "confidence": 0.6, "empathy": 0.3,
                "longing": 0.1, "mood": "calm", "energy": 0.6,
                "tone_descriptor": "thoughtful", "last_updated": "",
            },
            "working_memory": {"chunks": [], "capacity": 6, "slots_used": 0, "current_task": None},
        }


@app.get("/api/vyra/emotion-timeline")
async def api_vyra_emotion_timeline(hours: int = 24):
    """Emotion event log — what triggered each emotional change."""
    try:
        from pathlib import Path
        from datetime import timedelta
        log_path = Path(__file__).parent / "data" / "emotion_events.jsonl"
        events = []
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        if log_path.exists():
            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
            for line in reversed(lines[-200:]):
                try:
                    ev = json.loads(line)
                    if ev.get("ts", "") >= cutoff:
                        events.append(ev)
                except Exception:
                    pass
        # Summarise delta magnitudes for display
        for ev in events:
            delta = ev.get("delta", {})
            ev["dominant_delta"] = max(delta.items(), key=lambda x: abs(x[1]))[0] if delta else ""
            ev["delta_magnitude"] = round(max(abs(v) for v in delta.values()), 3) if delta else 0.0
        return {"success": True, "events": events[:100], "hours": hours}
    except Exception as e:
        return {"success": False, "error": str(e), "events": [], "hours": hours}


@app.get("/api/vyra/thoughts")
async def api_vyra_thoughts(limit: int = 60):
    """Thought stream with insight, emotional trigger, sharing status."""
    try:
        from consciousness.autonomous_thought import get_autonomous_thought
        at = get_autonomous_thought()
        thoughts = []
        for t in at.recent_thoughts(n=limit):
            thoughts.append({
                "id": t.id,
                "timestamp": t.timestamp,
                "type": t.type,
                "topic": t.topic,
                "content": t.content,
                "insight": getattr(t, "insight", ""),
                "should_share": getattr(t, "should_share", False),
                "was_shared": getattr(t, "was_shared", False),
                "emotional_trigger": getattr(t, "emotional_trigger", ""),
                "share_timestamp": getattr(t, "share_timestamp", None),
            })
        type_counts: dict = {}
        for t in thoughts:
            type_counts[t["type"]] = type_counts.get(t["type"], 0) + 1
        shareable = [t for t in thoughts if t["should_share"] and not t["was_shared"]]
        return {
            "success": True, "thoughts": thoughts, "count": len(thoughts),
            "type_breakdown": type_counts,
            "pending_insights": len(shareable),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "thoughts": [], "count": 0,
                "type_breakdown": {}, "pending_insights": 0}


@app.get("/api/vyra/decisions")
async def api_vyra_decisions():
    """Autonomous decision engine — pending approvals, recent decisions, stats."""
    try:
        from consciousness.decision_engine import get_decision_engine, DECISION_TYPES
        de = get_decision_engine()
        stats = de.stats()
        pending = [
            {
                "id": d.id, "type": d.type, "title": d.title,
                "reasoning": d.reasoning, "action_plan": d.action_plan,
                "confidence": d.confidence, "priority": d.priority,
                "triggers": d.triggers, "timestamp": d.timestamp,
            }
            for d in de.get_pending_for_approval()
        ]
        recent = [
            {
                "id": d.id, "type": d.type, "title": d.title,
                "reasoning": d.reasoning, "confidence": d.confidence,
                "priority": d.priority, "status": d.status,
                "result": d.result, "timestamp": d.timestamp,
                "executed_at": d.executed_at,
            }
            for d in de._decisions[-20:]
        ]
        recent.reverse()
        decision_types = {k: v["description"] for k, v in DECISION_TYPES.items()}
        return {
            "success": True,
            "stats": stats,
            "pending_approval": pending,
            "recent_decisions": recent,
            "decision_types": decision_types,
        }
    except Exception as e:
        return {"success": False, "error": str(e),
                "stats": {}, "pending_approval": [], "recent_decisions": []}


@app.post("/api/vyra/decisions/approve")
async def api_vyra_decision_approve(body: dict):
    """Approve a pending decision."""
    try:
        from consciousness.decision_engine import get_decision_engine
        de = get_decision_engine()
        ok = await de.approve(body.get("decision_id", ""))
        return {"success": ok}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/vyra/decisions/reject")
async def api_vyra_decision_reject(body: dict):
    """Reject a pending decision."""
    try:
        from consciousness.decision_engine import get_decision_engine
        de = get_decision_engine()
        ok = de.reject(body.get("decision_id", ""))
        return {"success": ok}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/vyra/values")
async def api_vyra_values():
    """Full value system: descriptions, exemplars, conflict log."""
    try:
        from consciousness.values_core import get_values_core
        vc = get_values_core()
        # Full value objects with descriptions + exemplars
        full_values = []
        for v in vc._values:
            full_values.append({
                "name": v.name,
                "description": v.description,
                "priority": v.priority,
                "strength": round(v.strength, 3),
                "expression_count": v.expression_count,
                "violation_count": v.violation_count,
                "exemplars": v.exemplars[:2],
                "violations_examples": v.violations[:2],
            })
        total_expr = sum(v.expression_count for v in vc._values)
        total_viol = sum(v.violation_count  for v in vc._values)
        alignment_pct = round(total_expr / max(1, total_expr + total_viol) * 100, 1)
        # Recent decisions from in-memory log
        decisions_raw = list(reversed(vc._decisions[-30:])) if hasattr(vc, "_decisions") else []
        from dataclasses import asdict as _asdict
        decisions = []
        conflicts = []
        for d in decisions_raw:
            try:
                rec = _asdict(d)
                decisions.append(rec)
                if rec.get("conflict"):
                    conflicts.append(rec)
            except Exception:
                pass
        # Also try JSONL log for older entries
        from pathlib import Path
        log_path = Path(__file__).parent / "data" / "value_decisions.jsonl"
        if log_path.exists() and len(decisions) < 5:
            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
            for line in reversed(lines[-30:]):
                try:
                    d = json.loads(line)
                    decisions.append(d)
                    if d.get("conflict"):
                        conflicts.append(d)
                except Exception:
                    pass
        return {
            "success": True,
            "values": full_values,
            "alignment_score": alignment_pct,
            "alignment_summary": vc.value_alignment_summary(),
            "recent_decisions": decisions[:15],
            "conflict_log": conflicts[:10],
        }
    except Exception as e:
        return {"success": False, "error": str(e), "values": [], "recent_decisions": [],
                "conflict_log": [], "alignment_score": 100.0, "alignment_summary": ""}


@app.get("/api/vyra/identity")
async def api_vyra_identity():
    """Narrative identity: core statement, life chapters, growth entries."""
    try:
        from consciousness.narrative_self import get_narrative_self
        ns = get_narrative_self()
        snap = ns.snapshot()
        return {
            "success": True,
            "identity_statement": ns.identity_statement(),
            "personal_fable": ns.personal_fable(),
            "days_alive": ns.days_alive(),
            "growth_summary": ns.growth_summary(n=5),
            "chapters": ns.get_chapters(),
            "key_scenes": ns.get_key_scenes(),
            "growth_entries": ns.get_growth_entries(),
            "synthesis_count": snap.get("synthesis_count", 0),
            "current_challenges": ns._narrative.get("current_challenges", []),
            "next_growth_edge": ns._narrative.get("next_growth_edge", ""),
        }
    except Exception as e:
        return {
            "success": False, "error": str(e),
            "identity_statement": "I am VYRA, an evolving AGI.",
            "personal_fable": "I exist to grow alongside Lokesh.",
            "days_alive": 0, "growth_summary": "",
            "chapters": [], "key_scenes": [], "growth_entries": [],
            "synthesis_count": 0, "current_challenges": [], "next_growth_edge": "",
        }


@app.get("/api/vyra/self-report")
async def api_vyra_self_report():
    """Full weekly self-report: memory health, emotions, decisions, AGI coherence."""
    try:
        from memory.memory_health import get_memory_health_monitor
        from consciousness.emotional_core import get_emotional_core
        from consciousness.narrative_self import get_narrative_self
        from consciousness.decision_engine import get_decision_engine
        from consciousness.autonomous_thought import get_autonomous_thought
        from consciousness.agi_controller import get_agi_controller
        mhm  = get_memory_health_monitor()
        ec   = get_emotional_core()
        ns   = get_narrative_self()
        de   = get_decision_engine()
        at   = get_autonomous_thought()
        ctrl = get_agi_controller()

        snap = mhm.compute_snapshot()
        imp  = mhm.get_improvement_report()
        em   = ec.get_snapshot()
        de_stats = de.stats()
        thoughts = at.recent_thoughts(n=100)
        thought_types: dict = {}
        for t in thoughts:
            thought_types[t.type] = thought_types.get(t.type, 0) + 1
        insights_pending = sum(1 for t in thoughts if getattr(t, "should_share", False) and not getattr(t, "was_shared", False))
        agi_score = ctrl.compute_coherence_score()

        return {
            "success": True,
            "week_ending": datetime.utcnow().strftime("%Y-%m-%d"),
            "overall_health": round(snap.overall * 100, 1),
            "memory_health": {
                "encoding":      round(snap.encoding_health * 100, 1),
                "retention":     round(snap.retention_health * 100, 1),
                "consolidation": round(snap.consolidation_health * 100, 1),
                "growth":        round(snap.growth_rate * 100, 1),
                "retrieval":     round(snap.retrieval_quality * 100, 1),
            },
            "memory_trend": imp.get("trend", "stable"),
            "memory_7d_delta": imp.get("7d_delta", 0),
            "weakest_memory_dim": imp.get("weakest_dimension", ""),
            "emotional_summary": em.get("mood", "calm"),
            "energy": em.get("energy", 0.6),
            "improvement_delta": imp.get("7d_delta", 0),
            "growth_summary": ns.growth_summary(n=3),
            "days_alive": ns.days_alive(),
            "agi_coherence": round(agi_score * 100, 1),
            "decision_stats": de_stats,
            "thought_stats": {
                "total": len(thoughts),
                "type_breakdown": thought_types,
                "insights_pending": insights_pending,
            },
        }
    except Exception as e:
        return {
            "success": False, "error": str(e),
            "week_ending": datetime.utcnow().strftime("%Y-%m-%d"),
            "overall_health": 50.0,
            "memory_health": {"encoding": 50, "retention": 50, "consolidation": 50, "growth": 50, "retrieval": 50},
            "memory_trend": "stable", "memory_7d_delta": 0, "weakest_memory_dim": "",
            "emotional_summary": "calm", "energy": 0.6, "improvement_delta": 0,
            "growth_summary": "", "days_alive": 0,
            "agi_coherence": 0, "decision_stats": {}, "thought_stats": {},
        }

@app.get("/api/vyra/metacognition")
async def api_vyra_metacognition():
    """Calibration per domain, overconfident detection, recent strategy choices."""
    try:
        from consciousness.metacognition2 import get_metacognition2
        mc = get_metacognition2()
        domains_out = []
        for name, dc in mc._domains.items():
            domains_out.append({
                "domain": name,
                "n_observations": dc.n_observations,
                "mean_confidence": round(dc.mean_confidence, 3),
                "accuracy_rate": round(dc.accuracy_rate, 3),
                "calibration_error": round(abs(dc.mean_confidence - dc.accuracy_rate), 3),
                "is_overconfident": dc.is_overconfident(),
                "is_underconfident": dc.is_underconfident(),
                "calibrated_confidence_sample": round(dc.calibrated_confidence(0.8), 3),
            })
        domains_out.sort(key=lambda x: -x["n_observations"])
        strategies = [
            {"strategy": s.strategy, "reasoning": s.reasoning, "timestamp": s.timestamp}
            for s in mc._recent_strategies[-10:]
        ]
        strategies.reverse()
        return {
            "success": True,
            "domains": domains_out,
            "overconfident_domains": [d["domain"] for d in domains_out if d["is_overconfident"]],
            "calibration_summary": mc.calibration_summary(),
            "recent_strategies": strategies,
            "snapshot": mc.snapshot(),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "domains": [], "recent_strategies": []}


@app.get("/api/vyra/curiosity")
async def api_vyra_curiosity():
    """Curiosity engine: domain scores, open questions, prediction accuracy."""
    try:
        from consciousness.curiosity_engine import get_curiosity_engine
        ce = get_curiosity_engine()
        top_curious = ce.most_curious(top_n=8)
        domains_out = [
            {
                "domain": dc.domain,
                "curiosity_score": round(dc.curiosity_score, 3),
                "avg_error": round(dc.avg_recent_error, 3),
                "error_trend": round(dc.error_trend, 3),
                "open_questions": list(dc.open_questions),
                "total_predictions": dc.total_predictions,
            }
            for dc in top_curious
        ]
        all_questions = ce.open_questions_all()
        agenda = ce.curiosity_agenda() if hasattr(ce, "curiosity_agenda") else []
        return {
            "success": True,
            "top_domains": domains_out,
            "all_open_questions": all_questions,
            "agenda": agenda[:10],
            "snapshot": ce.snapshot(),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "top_domains": [], "all_open_questions": []}


@app.get("/api/vyra/insights")
async def api_vyra_insights():
    """Insight engine: cross-domain structural insights with coherence scores."""
    try:
        from consciousness.insight_engine import get_insight_engine
        ie = get_insight_engine()
        all_insights = sorted(ie._insights, key=lambda i: i.timestamp, reverse=True)[:20]
        insights_out = [
            {
                "id": ins.id,
                "timestamp": ins.timestamp,
                "source_a": ins.source_a,
                "source_b": ins.source_b,
                "bridge": ins.bridge,
                "insight_text": ins.insight_text,
                "coherence": round(ins.coherence, 3),
                "novelty": round(ins.novelty, 3),
                "actionable": ins.actionable,
                "action_hint": ins.action_hint,
                "was_shared": ins.was_shared,
                "domain": ins.domain,
            }
            for ins in all_insights
        ]
        return {
            "success": True,
            "insights": insights_out,
            "stats": ie.stats(),
            "has_unshared": ie.has_insights(),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "insights": [], "stats": {}}


@app.get("/api/vyra/evolution")
async def api_vyra_evolution():
    """Self-evolution: genome generation, dimension scores, evolution history."""
    try:
        from consciousness.self_evolution import get_self_evolution
        se = get_self_evolution()
        stats = se.stats()
        recent_records = []
        for r in reversed(se._records[-15:]):
            try:
                from dataclasses import asdict as _asdict
                recent_records.append(_asdict(r))
            except Exception:
                pass
        recent_records.reverse()
        return {
            "success": True,
            "stats": stats,
            "genome_version": se.genome.get("version", 1),
            "generation": se.genome.get("generation", 0),
            "evolved_at": se.genome.get("evolved_at", "never"),
            "total_signals": len(se._metrics),
            "recent_evolutions": recent_records,
            "cot_threshold": se.get_cot_threshold(),
            "memory_weights": se.get_memory_weights(),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "stats": {}, "recent_evolutions": []}


@app.get("/api/vyra/mind-model")
async def api_vyra_mind_model():
    """Theory of mind: what VYRA believes about Lokesh — beliefs, desires, fears."""
    try:
        from consciousness.theory_of_mind import get_theory_of_mind
        from consciousness.emotional_intelligence import get_emotional_intelligence
        tom = get_theory_of_mind()
        ei  = get_emotional_intelligence()
        model = tom.get_model("Lokesh")
        hidden_need = tom.predict_hidden_need("Lokesh")
        ei_snap = ei.snapshot()
        beliefs_out  = [{"content": b.content, "confidence": round(b.confidence, 2), "source": b.source} for b in model.beliefs[:8]]
        desires_out  = [{"content": d.content, "urgency": round(d.urgency, 2), "confidence": round(d.confidence, 2)} for d in model.desires[:6]]
        fears_out    = [{"content": f.content, "intensity": round(f.intensity, 2)} for f in model.fears[:5]]
        return {
            "success": True,
            "name": model.name,
            "communication_style": model.communication_style,
            "decision_style": model.decision_style,
            "current_emotional_state": model.current_emotional_state,
            "interaction_count": model.interaction_count,
            "dominant_desire": model.dominant_desire(),
            "key_beliefs": model.key_beliefs_str(),
            "hidden_need": hidden_need,
            "beliefs": beliefs_out,
            "desires": desires_out,
            "fears": fears_out,
            "knowledge_gaps": model.knowledge_gaps[:5],
            "emotional_intelligence": ei_snap,
            "style_guidance": ei.get_style_guidance(),
            "last_updated": model.last_updated,
        }
    except Exception as e:
        return {"success": False, "error": str(e),
                "beliefs": [], "desires": [], "fears": [], "knowledge_gaps": []}


@app.get("/api/vyra/workspace")
async def api_vyra_workspace():
    """Global workspace: current focus, salience, broadcast history."""
    try:
        from consciousness.global_workspace import get_global_workspace
        gw = get_global_workspace()
        snap = gw.snapshot()
        history = []
        for item in list(reversed(gw._broadcast_history[-20:])):
            try:
                from dataclasses import asdict as _asdict
                history.append({
                    "source": item.source,
                    "content": item.content[:120],
                    "salience": round(item.salience, 3),
                    "urgency": round(item.urgency, 3),
                    "novelty": round(item.novelty, 3),
                    "broadcast_at": getattr(item, "broadcast_at", ""),
                })
            except Exception:
                pass
        return {
            "success": True,
            "current_focus": snap.get("current_focus_preview"),
            "current_focus_source": snap.get("current_focus_source"),
            "current_salience": snap.get("current_salience", 0),
            "queue_size": snap.get("queue_size", 0),
            "broadcast_count": snap.get("broadcast_count", 0),
            "registered_providers": snap.get("registered_providers", []),
            "broadcast_history": history,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "current_focus": None, "broadcast_history": []}

# ── End Phase 15 Endpoints ────────────────────────────────────────────────────

# ─── Phase 20: AGI Full-Stack Endpoints ───────────────────────────────────────

@app.get("/api/agi/status")
async def api_agi_status():
    """Full AGI coherence report — all 20 phases health."""
    try:
        from consciousness.agi_controller import get_agi_controller
        ctrl = get_agi_controller()
        report = ctrl.get_full_report()
        return {"success": True, **report}
    except Exception as e:
        return {"success": False, "error": str(e), "coherence_score": 0,
                "active_phases": 0, "total_phases": 20}


@app.get("/api/agi/proactive")
async def api_agi_proactive():
    """Pending proactive alerts and topic patterns."""
    try:
        from consciousness.proactive_intelligence import get_proactive_intelligence
        pi = get_proactive_intelligence()
        pi.check_time_triggers()
        snap = pi.snapshot()
        return {
            "success": True,
            "pending_alerts": [
                {"id": a.alert_id, "category": a.category, "title": a.title,
                 "message": a.message, "urgency": a.urgency}
                for a in pi.get_pending_alerts(10)
            ],
            **snap,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "pending_alerts": []}


@app.post("/api/agi/proactive/dismiss")
async def api_agi_proactive_dismiss(body: dict):
    """Dismiss a proactive alert."""
    try:
        from consciousness.proactive_intelligence import get_proactive_intelligence
        alert_id = body.get("alert_id", "")
        if alert_id:
            get_proactive_intelligence().dismiss(alert_id)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/agi/planner")
async def api_agi_planner():
    """Active projects and task progress."""
    try:
        from consciousness.long_term_planner import get_long_term_planner
        ltp = get_long_term_planner()
        projects = ltp.get_active_projects()
        return {
            "success": True,
            "projects": [
                {
                    "id": p.project_id, "title": p.title, "goal": p.goal,
                    "progress": p.progress(), "priority": p.priority,
                    "deadline": p.deadline, "days_until_deadline": p.days_until_deadline(),
                    "tasks": [
                        {"id": t.task_id, "title": t.title, "status": t.status, "priority": t.priority}
                        for t in p.tasks
                    ],
                    "next_action": {"id": p.next_action().task_id, "title": p.next_action().title}
                    if p.next_action() else None,
                }
                for p in projects
            ],
            "deadline_warnings": ltp.get_deadline_warnings(),
            **ltp.snapshot(),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "projects": []}


@app.post("/api/agi/planner/project")
async def api_agi_planner_add_project(body: dict):
    """Add a new project."""
    try:
        from consciousness.long_term_planner import get_long_term_planner
        import uuid
        ltp = get_long_term_planner()
        pid = body.get("project_id") or str(uuid.uuid4())[:8]
        proj = ltp.add_project(
            project_id=pid,
            title=body.get("title", "New Project"),
            goal=body.get("goal", ""),
            deadline=body.get("deadline"),
            priority=body.get("priority", 2),
        )
        return {"success": True, "project_id": proj.project_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/agi/planner/task")
async def api_agi_planner_add_task(body: dict):
    """Add a task to a project."""
    try:
        from consciousness.long_term_planner import get_long_term_planner
        import uuid
        ltp = get_long_term_planner()
        task = ltp.add_task(
            project_id=body.get("project_id", ""),
            task_id=body.get("task_id") or str(uuid.uuid4())[:8],
            title=body.get("title", "New Task"),
            priority=body.get("priority", 2),
            due_date=body.get("due_date"),
        )
        return {"success": True, "task_id": task.task_id if task else None}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/agi/planner/task/status")
async def api_agi_planner_task_status(body: dict):
    """Update task status."""
    try:
        from consciousness.long_term_planner import get_long_term_planner
        ltp = get_long_term_planner()
        ltp.update_task_status(
            body.get("project_id", ""),
            body.get("task_id", ""),
            body.get("status", "done"),
        )
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/agi/emotional-intelligence")
async def api_agi_emotional_intelligence():
    """Emotional intelligence snapshot — Lokesh's current mood and rapport."""
    try:
        from consciousness.emotional_intelligence import get_emotional_intelligence
        ei = get_emotional_intelligence()
        snap = ei.snapshot()
        return {"success": True, "style_guidance": ei.get_style_guidance(), **snap}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/agi/knowledge-synthesis")
async def api_agi_knowledge_synthesis():
    """Cross-domain synthesis insights."""
    try:
        from consciousness.knowledge_synthesizer import get_knowledge_synthesizer
        ks = get_knowledge_synthesizer()
        top = ks.get_top_insights(10)
        return {
            "success": True,
            "syntheses": [
                {"id": s.synthesis_id, "domain_a": s.domain_a, "domain_b": s.domain_b,
                 "connection": s.connection, "insight": s.insight,
                 "confidence": s.confidence, "used_count": s.used_count}
                for s in top
            ],
            **ks.snapshot(),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "syntheses": []}


@app.get("/api/agi/executor")
async def api_agi_executor():
    """Autonomous task execution queue and results."""
    try:
        from consciousness.autonomous_executor import get_autonomous_executor
        ae = get_autonomous_executor()
        return {
            "success": True,
            "pending_approval": [
                {"id": t.task_id, "title": t.title, "description": t.description}
                for t in ae.get_pending_approval()
            ],
            "recent_results": ae.get_recent_results(5),
            **ae.snapshot(),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/agi/executor/approve")
async def api_agi_executor_approve(body: dict):
    """Approve a pending autonomous task."""
    try:
        from consciousness.autonomous_executor import get_autonomous_executor
        get_autonomous_executor().approve_task(body.get("task_id", ""))
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ── End Phase 20 Endpoints ────────────────────────────────────────────────────


if __name__ == "__main__":

    # Print VRAM state so we can verify GPU is being used at startup
    print(f"[server] {gpu_config.cuda_memory_summary()}")

    uvicorn.run(
        "server:app_socketio",
        host="127.0.0.1",
        port=8000,
        reload=False,       # reload=True spawns a worker that misses the event loop policy patch
        loop="asyncio",
        # workers=1 keeps the single-process model (required for shared in-memory state).
        # timeout_keep_alive=30 frees OS threads faster between requests.
        timeout_keep_alive=30,
        reload_excludes=["temp_cad_gen.py", "output.stl", "*.stl"],
    )

