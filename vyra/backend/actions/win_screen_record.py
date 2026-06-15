"""
win_screen_record.py — Screen recording and screenshot utilities for VYRA.
Uses mss + OpenCV for recording; MSS + PIL for burst screenshots.
Fallback: PowerShell Xbox Game Bar / OBS CLI.
"""
import json
import subprocess
import os
import threading
import time


def _ok(output: str, action: str = "") -> str:
    return json.dumps({"status": "ok", "action": action, "output": output})


def _err(msg: str, action: str = "") -> str:
    return json.dumps({"status": "error", "action": action, "error": msg})


def _run_ps(script: str, timeout: int = 20) -> str:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return r.stdout.strip() or r.stderr.strip() or "Done."
    except Exception as e:
        return f"Error: {e}"


# Global recording state
_recording_state = {"active": False, "thread": None, "stop_event": None, "output_path": ""}


def _record_worker(output_path: str, fps: int, region: dict, stop_event: threading.Event):
    """Background thread that records screen frames to an AVI file."""
    try:
        import mss
        import cv2
        import numpy as np

        with mss.mss() as sct:
            monitor = region or sct.monitors[0]
            w = monitor.get("width", monitor.get("width", 1920))
            h = monitor.get("height", monitor.get("height", 1080))
            fourcc = cv2.VideoWriter_fourcc(*"XVID")
            out = cv2.VideoWriter(output_path, fourcc, fps, (w, h))
            frame_time = 1.0 / fps
            while not stop_event.is_set():
                t0 = time.perf_counter()
                img = np.array(sct.grab(monitor))
                frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                out.write(frame)
                elapsed = time.perf_counter() - t0
                sleep_time = frame_time - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
            out.release()
    except ImportError as e:
        print(f"[VYRA Screen Record] Missing: {e}")
    except Exception as e:
        print(f"[VYRA Screen Record] Error: {e}")


def win_screen_record(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action    = parameters.get("action", "").lower().strip()
    fps       = int(parameters.get("fps", 15))
    duration  = parameters.get("duration")  # seconds; None = manual stop
    x         = parameters.get("x")
    y         = parameters.get("y")
    width     = parameters.get("width")
    height    = parameters.get("height")

    try:
        # ── start_recording ───────────────────────────────────────────────────
        if action == "start_recording":
            if _recording_state["active"]:
                return _err("Recording already in progress. Stop it first.", action)
            output_path = parameters.get("output_path",
                          os.path.join(os.path.expanduser("~"), "Desktop",
                                       f"vyra_recording_{int(time.time())}.avi"))
            region = None
            if x is not None and y is not None and width and height:
                region = {"top": int(y), "left": int(x), "width": int(width), "height": int(height)}

            try:
                import cv2, mss
            except ImportError as e:
                return _err(f"Missing: {e}. Run: pip install opencv-python mss", action)

            stop_event = threading.Event()
            t = threading.Thread(target=_record_worker,
                                 args=(output_path, fps, region, stop_event),
                                 daemon=True)
            t.start()
            _recording_state.update({
                "active": True, "thread": t, "stop_event": stop_event,
                "output_path": output_path
            })

            if duration:
                # Auto-stop after duration seconds
                def auto_stop():
                    time.sleep(float(duration))
                    stop_event.set()
                    _recording_state["active"] = False
                threading.Thread(target=auto_stop, daemon=True).start()
                return _ok(f"Recording started ({fps}fps, {duration}s). Output: {output_path}", action)

            return _ok(f"Recording started ({fps}fps). Call stop_recording when done. Output: {output_path}", action)

        # ── stop_recording ────────────────────────────────────────────────────
        elif action == "stop_recording":
            if not _recording_state["active"]:
                return _err("No recording in progress.", action)
            _recording_state["stop_event"].set()
            _recording_state["thread"].join(timeout=3)
            path = _recording_state["output_path"]
            _recording_state.update({"active": False, "thread": None, "stop_event": None})
            return _ok(f"Recording stopped. Saved to: {path}", action)

        # ── take_screenshot ───────────────────────────────────────────────────
        elif action == "take_screenshot":
            save_path = parameters.get("save_path",
                        os.path.join(os.path.expanduser("~"), "Desktop",
                                     f"screenshot_{int(time.time())}.png"))
            try:
                import mss
                from PIL import Image
                with mss.mss() as sct:
                    if x is not None and y is not None and width and height:
                        monitor = {"top": int(y), "left": int(x), "width": int(width), "height": int(height)}
                    else:
                        monitor = sct.monitors[0]
                    img = sct.grab(monitor)
                    mss.tools.to_png(img.rgb, img.size, output=save_path)
                return _ok(f"Screenshot saved: {save_path}", action)
            except ImportError:
                # Fallback: PrintScreen via PowerShell
                _run_ps(
                    f"Add-Type -AssemblyName System.Windows.Forms; "
                    "[System.Windows.Forms.SendKeys]::SendWait('%{{PRTSC}}')"
                )
                return _ok("Screenshot taken via PrintScreen key (check clipboard).", action)

        # ── take_burst ────────────────────────────────────────────────────────
        elif action == "take_burst":
            """Take N screenshots rapidly (for creating GIFs or time-lapse)."""
            count    = int(parameters.get("count", 5))
            interval = float(parameters.get("interval", 1.0))  # seconds between shots
            out_dir  = parameters.get("output_dir",
                       os.path.join(os.path.expanduser("~"), "Desktop", "vyra_burst"))
            os.makedirs(out_dir, exist_ok=True)
            try:
                import mss
                saved = []
                with mss.mss() as sct:
                    monitor = sct.monitors[0]
                    for i in range(count):
                        path = os.path.join(out_dir, f"burst_{i+1:03d}.png")
                        img = sct.grab(monitor)
                        mss.tools.to_png(img.rgb, img.size, output=path)
                        saved.append(path)
                        if i < count - 1:
                            time.sleep(interval)
                return _ok(f"Burst: {len(saved)} screenshots in {out_dir}", action)
            except ImportError as e:
                return _err(f"Missing: {e}. Run: pip install mss", action)

        # ── create_gif ────────────────────────────────────────────────────────
        elif action == "create_gif":
            """Convert burst screenshots in a folder to an animated GIF."""
            input_dir = parameters.get("input_dir", "").strip()
            output_path = parameters.get("output_path",
                          os.path.join(os.path.expanduser("~"), "Desktop", "vyra_timelapse.gif"))
            duration_ms = int(parameters.get("frame_duration_ms", 200))
            if not input_dir or not os.path.isdir(input_dir):
                return _err("'input_dir' pointing to a folder of PNG/JPG files is required.", action)
            try:
                from PIL import Image
                frames = []
                for f in sorted(os.listdir(input_dir)):
                    if f.lower().endswith((".png", ".jpg", ".jpeg")):
                        frames.append(Image.open(os.path.join(input_dir, f)).convert("RGB"))
                if not frames:
                    return _err("No images found in input_dir.", action)
                frames[0].save(output_path, save_all=True, append_images=frames[1:],
                               duration=duration_ms, loop=0, optimize=True)
                return _ok(f"GIF created ({len(frames)} frames): {output_path}", action)
            except ImportError:
                return _err("Pillow not installed. Run: pip install Pillow", action)

        # ── get_recording_status ──────────────────────────────────────────────
        elif action == "get_recording_status":
            if _recording_state["active"]:
                return _ok(f"Recording IN PROGRESS → {_recording_state['output_path']}", action)
            return _ok("No recording active.", action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: start_recording, stop_recording, "
                "take_screenshot, take_burst, create_gif, get_recording_status",
                action)

    except Exception as e:
        return _err(str(e), action)
