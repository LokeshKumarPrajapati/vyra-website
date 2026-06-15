"""
backend/services/clap_detector.py

Always-on background clap detector — opens its own lightweight PyAudio stream
and listens continuously for a double-clap gesture to wake the JARVIS dashboard.

Algorithm
---------
  - Rolling 25-frame (~0.5 s) baseline RMS for adaptive threshold
  - Peak  = RMS > max(baseline × 4, 600)   [int16 scale, ~1.8% of full range]
  - Two peaks with gap 200 ms – 1500 ms     → double clap confirmed
  - 2-second cooldown before next detection

Mic sharing (Windows single-client limitation)
----------------------------------------------
  Call pause()  before VYRA AudioPipeline opens the mic.
  Call resume() after VYRA AudioPipeline releases the mic.
  The PyAudio stream is kept open during the pause (avoids ~200 ms re-open
  latency) but frames are silently discarded in _pa_callback.

On double-clap, emits to:
  - All plain WebSocket clients  via _ws_manager.broadcast()
  - All Socket.IO clients        via sio.emit('clap_detected', ...)
"""

import asyncio
import time
from collections import deque
from typing import Callable, Optional

import numpy as np
import pyaudio

# ── Audio constants (match AudioPipeline for consistency) ────────────────────
SAMPLE_RATE   = 16_000
CHANNELS      = 1
FORMAT        = pyaudio.paInt16
FRAME_MS      = 20
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000   # 320 samples
FRAME_BYTES   = FRAME_SAMPLES * 2                 # 640 bytes

# ── Detection parameters ──────────────────────────────────────────────────────
BASELINE_WINDOW_FRAMES = 25     # ~0.5 s of rolling history
PEAK_MULTIPLIER        = 4.0    # spike must exceed baseline × this
PEAK_MIN_ABSOLUTE      = 600    # int16 floor so silence (baseline≈0) never fires
MIN_GAP_SEC            = 0.20   # shortest valid inter-clap gap
MAX_GAP_SEC            = 1.50   # longest valid inter-clap gap
COOLDOWN_SEC           = 2.0    # lockout after a confirmed double-clap


def _rms(data: bytes) -> float:
    """Vectorised RMS — identical to AudioPipeline._rms_numpy (~3 µs)."""
    s = np.frombuffer(data, dtype=np.int16).astype(np.float32)
    return float(np.sqrt(np.mean(s * s)))


class ClapDetectorService:
    """
    Always-on background clap detector.

    Parameters
    ----------
    sio        : socketio.AsyncServer  — for Socket.IO broadcast
    ws_manager : _WSManager            — for plain WS broadcast
    loop       : asyncio event loop    — bridges the PyAudio C thread
    on_clap    : optional extra callback fired on the event loop on detection
    """

    def __init__(
        self,
        sio,
        ws_manager,
        loop: asyncio.AbstractEventLoop,
        on_clap: Optional[Callable] = None,
    ):
        self._sio      = sio
        self._ws       = ws_manager
        self._loop     = loop
        self._on_clap  = on_clap

        # Bridge queue: PyAudio C thread → asyncio event loop (same pattern as AudioPipeline)
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=512)

        # Rolling baseline
        self._baseline_buf: deque[float] = deque(maxlen=BASELINE_WINDOW_FRAMES)

        # Detection state
        self._last_peak_ts: float   = 0.0
        self._cooldown_until: float = 0.0

        # PyAudio resources
        self._pya:    Optional[pyaudio.PyAudio] = None
        self._stream: Optional[pyaudio.Stream]  = None

        # Control flags
        self._running: bool   = False
        self._paused:  bool   = False
        self._frag_buf: bytearray = bytearray()

    # ── PyAudio callback (C thread — must be < 1 ms) ─────────────────────────

    def _pa_callback(self, in_data, _frame_count, _time_info, _status):
        """
        Fires every 20 ms from the PyAudio C thread.
        Drops frames silently when paused to avoid stale-audio artefacts on resume.
        """
        if not self._paused:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, in_data)
        return (None, pyaudio.paContinue)

    # ── Public API ────────────────────────────────────────────────────────────

    async def start(self):
        """
        Open the microphone and begin listening.
        Retries up to 5× with a 3-second delay between attempts to handle
        the case where the audio subsystem isn't ready at boot time.
        """
        for attempt in range(5):
            try:
                self._pya = pyaudio.PyAudio()
                self._stream = self._pya.open(
                    format=FORMAT,
                    channels=CHANNELS,
                    rate=SAMPLE_RATE,
                    input=True,
                    frames_per_buffer=FRAME_SAMPLES,
                    stream_callback=self._pa_callback,
                )
                self._stream.start_stream()
                self._running = True
                print("[ClapDetector] Mic open — listening for double-clap.")
                await self._process_loop()
                return
            except asyncio.CancelledError:
                return
            except Exception as e:
                print(f"[ClapDetector] Start attempt {attempt + 1}/5 failed: {e}")
                await self._close()
                if attempt < 4:
                    await asyncio.sleep(3)
        print("[ClapDetector] Could not open mic after 5 attempts — clap detection disabled.")

    def pause(self):
        """
        Pause frame processing (stream stays open).
        Call before VYRA AudioPipeline opens the mic on Windows.
        """
        self._paused = True
        # Drain stale queue so old audio doesn't cause a false positive on resume
        try:
            while not self._queue.empty():
                self._queue.get_nowait()
        except Exception:
            pass
        self._frag_buf.clear()
        print("[ClapDetector] Paused (VYRA mic active).")

    def resume(self):
        """Resume processing after VYRA session ends."""
        self._last_peak_ts  = 0.0   # discard any half-captured peak
        self._baseline_buf.clear()   # rebuild baseline from fresh audio
        self._frag_buf.clear()
        self._paused = False
        print("[ClapDetector] Resumed.")

    def stop(self):
        """Signal the service to shut down gracefully."""
        self._running = False

    # ── Internal processing ───────────────────────────────────────────────────

    async def _process_loop(self):
        while self._running:
            try:
                raw = await asyncio.wait_for(self._queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue

            # Reassemble to exact frame boundaries (safety net for partial deliveries)
            self._frag_buf.extend(raw)
            while len(self._frag_buf) >= FRAME_BYTES:
                frame = bytes(self._frag_buf[:FRAME_BYTES])
                del self._frag_buf[:FRAME_BYTES]
                await self._process_frame(frame)

    async def _process_frame(self, frame: bytes):
        now = time.monotonic()
        rms = _rms(frame)
        self._baseline_buf.append(rms)

        # Skip during cooldown or before enough baseline is established
        if now < self._cooldown_until or len(self._baseline_buf) < 5:
            return

        baseline  = float(np.mean(self._baseline_buf))
        threshold = max(baseline * PEAK_MULTIPLIER, float(PEAK_MIN_ABSOLUTE))

        if rms > threshold:
            gap = now - self._last_peak_ts

            if self._last_peak_ts > 0 and MIN_GAP_SEC <= gap <= MAX_GAP_SEC:
                # ── Double clap confirmed ─────────────────────────────────────
                self._cooldown_until = now + COOLDOWN_SEC
                self._last_peak_ts   = 0.0
                print(f"[ClapDetector] Double-clap! gap={gap:.3f}s")
                await self._emit_clap()
            else:
                # First clap (or second was too close / too far — reset window)
                self._last_peak_ts = now

    async def _emit_clap(self):
        """Broadcast clap_detected to all connected clients."""
        ts = int(time.time() * 1000)
        payload = {
            "type":      "clap_detected",
            "payload":   {"source": "clap", "ts": ts},
            "timestamp": ts,
        }
        try:
            await self._ws.broadcast(payload)
        except Exception as e:
            print(f"[ClapDetector] WS broadcast error: {e}")
        try:
            await self._sio.emit("clap_detected", payload["payload"])
        except Exception as e:
            print(f"[ClapDetector] SocketIO emit error: {e}")
        if self._on_clap:
            try:
                self._on_clap()
            except Exception:
                pass

    async def _close(self):
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
        if self._pya:
            try:
                self._pya.terminate()
            except Exception:
                pass
        self._stream = None
        self._pya    = None
        print("[ClapDetector] Closed.")
