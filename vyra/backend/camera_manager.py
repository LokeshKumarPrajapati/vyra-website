"""
CameraManager v3 — Iron Man Ultra-Smooth Hand Tracking
------------------------------------------------------
Performance:
  • Dedicated cursor worker thread (no thread-per-frame spawning)
  • Win32 SetCursorPos via ctypes (~0.1ms vs pyautogui's ~5ms)
  • 60 FPS ML inference (matching camera)
  • Kalman-only smoothing with tuned process noise  
  • 640×480 inference downscale for faster ML
  • Pre-allocated numpy arrays in hot path

Gesture System (Hand State + Swipe Direction):
  ☝️ Point     → Cursor movement, pinch-click, drag
  🖐️ Open Palm → Tab switch (L/R), Task View (Up), Desktop (Down), Alt+Tab (Hold)
  ✊ Fist       → Back/Forward (L/R), Maximize (Up), Minimize (Down), Close Tab (Hold)
  ✌️ Two Fingers → Scroll (Up/Down), Zoom In/Out (spread/pinch)
  Three Fingers → Virtual Desktop Switch (L/R)
  👍 Thumbs Up  → Play/Pause Media (Hold 1s)

Works when Vyra is minimized (backend-native tracking).
"""

import cv2
import threading
import time
import os
import sys
import urllib.request
import asyncio
import base64
import queue
import numpy as np
import io
import collections
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Deque
from PIL import Image

import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision
import pyautogui

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

# ─── Win32 Direct Cursor API (30x faster than pyautogui) ─────────────────────
if sys.platform == "win32":
    import ctypes
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32

    def _win_set_cursor(x: int, y: int):
        _user32.SetCursorPos(int(x), int(y))

    def _win_mouse_event(flags: int, dx: int = 0, dy: int = 0):
        _user32.mouse_event(flags, dx, dy, 0, 0)

    MOUSEEVENTF_LEFTDOWN   = 0x0002
    MOUSEEVENTF_LEFTUP     = 0x0004
    MOUSEEVENTF_RIGHTDOWN  = 0x0008
    MOUSEEVENTF_RIGHTUP    = 0x0010
    MOUSEEVENTF_WHEEL      = 0x0800
else:
    def _win_set_cursor(x, y):
        pyautogui.moveTo(x, y, _pause=False)
    def _win_mouse_event(flags, dx=0, dy=0):
        pass
    MOUSEEVENTF_LEFTDOWN = MOUSEEVENTF_LEFTUP = 0
    MOUSEEVENTF_RIGHTDOWN = MOUSEEVENTF_RIGHTUP = 0


# ─────────────────────────────────────────────────────────────────────────────
# Kalman Filter — 1-D constant-velocity model (pre-allocated)
# ─────────────────────────────────────────────────────────────────────────────
class KalmanFilter1D:
    __slots__ = ('x', 'P', 'Q', 'R', 'H', '_dt', '_F', '_S', '_K', '_I')

    def __init__(self, process_noise: float = 1e-3, measurement_noise: float = 0.03):
        self.x = np.array([[0.0], [0.0]], dtype=np.float64)
        self.P = np.eye(2, dtype=np.float64) * 1000.0
        self.Q = np.array([[process_noise, 0],
                           [0, process_noise * 10]], dtype=np.float64)
        self.R = np.array([[measurement_noise]], dtype=np.float64)
        self.H = np.array([[1.0, 0.0]], dtype=np.float64)
        self._dt = 1.0 / 60.0
        # Pre-allocate scratch arrays
        self._F = np.eye(2, dtype=np.float64)
        self._S = np.zeros((1, 1), dtype=np.float64)
        self._K = np.zeros((2, 1), dtype=np.float64)
        self._I = np.eye(2, dtype=np.float64)

    def step(self, measurement: float, dt: float) -> float:
        dt = max(dt, 1e-4)
        # Build F in-place
        self._F[0, 1] = dt
        F = self._F
        # Predict
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + self.Q
        # Update
        np.dot(self.H, np.dot(self.P, self.H.T), out=self._S)
        self._S += self.R
        self._K = self.P @ self.H.T / self._S[0, 0]
        innovation = measurement - float(self.H @ self.x)
        self.x += self._K * innovation
        self.P = (self._I - self._K @ self.H) @ self.P
        return float(self.x[0, 0])


# ─────────────────────────────────────────────────────────────────────────────
# Micro-Jitter Suppressor — very light EMA with near-unity alpha
# ─────────────────────────────────────────────────────────────────────────────
class JitterSuppressor:
    """Ultra-light jitter filter. Only suppresses sub-pixel noise."""
    __slots__ = ('value', '_deadzone')

    def __init__(self, deadzone: float = 1.5):
        self.value = 0.0
        self._deadzone = deadzone

    def step(self, target: float) -> float:
        delta = target - self.value
        if abs(delta) < self._deadzone:
            return self.value  # Suppress micro-jitter
        self.value = target - np.sign(delta) * self._deadzone * 0.3
        return self.value


# ─────────────────────────────────────────────────────────────────────────────
# Gesture State Machine
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class GestureState:
    name: str
    active: bool = False
    start_time: float = 0.0
    last_triggered: float = 0.0
    cooldown: float = 0.3

    def try_activate(self, now: float) -> bool:
        if not self.active and (now - self.last_triggered) >= self.cooldown:
            self.active = True
            self.start_time = now
            return True
        return False

    def deactivate(self, now: float):
        if self.active:
            self.active = False
            self.last_triggered = now

    def held_duration(self, now: float) -> float:
        return (now - self.start_time) if self.active else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Velocity Tracker — for inertial scroll
# ─────────────────────────────────────────────────────────────────────────────
class VelocityTracker:
    def __init__(self, window: int = 5):
        self._history: Deque[Tuple[float, float]] = collections.deque(maxlen=window)

    def push(self, value: float, now: float):
        self._history.append((now, value))

    def velocity(self) -> float:
        if len(self._history) < 2:
            return 0.0
        t0, v0 = self._history[0]
        t1, v1 = self._history[-1]
        dt = t1 - t0
        return (v1 - v0) / dt if dt > 1e-4 else 0.0

    def clear(self):
        self._history.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Swipe Detector — tracks origin and detects directional swipes
# ─────────────────────────────────────────────────────────────────────────────
class SwipeDetector:
    """Tracks the origin point of a gesture and detects swipe direction."""

    def __init__(self, threshold: float = 0.12, ratio: float = 1.4):
        self.threshold = threshold   # Minimum movement to trigger swipe
        self.ratio = ratio           # Direction ratio (must be X:Y dominant)
        self.origin: Optional[Tuple[float, float]] = None
        self.locked = False          # True after a swipe fires (prevents double-fire)

    def start(self, x: float, y: float):
        if self.origin is None:
            self.origin = (x, y)
            self.locked = False

    def reset(self):
        self.origin = None
        self.locked = False

    def detect(self, x: float, y: float) -> Optional[str]:
        """Returns 'left', 'right', 'up', 'down' or None."""
        if self.origin is None or self.locked:
            return None
        dx = x - self.origin[0]
        dy = y - self.origin[1]
        abs_dx, abs_dy = abs(dx), abs(dy)

        if abs_dx > self.threshold and abs_dx > abs_dy * self.ratio:
            self.locked = True
            return "right" if dx > 0 else "left"
        if abs_dy > self.threshold and abs_dy > abs_dx * self.ratio:
            self.locked = True
            return "down" if dy > 0 else "up"
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Hand Geometry Helpers
# ─────────────────────────────────────────────────────────────────────────────
def hand_scale(landmarks) -> float:
    wrist = landmarks[0]
    mid_mcp = landmarks[9]
    return max(
        ((wrist.x - mid_mcp.x) ** 2 + (wrist.y - mid_mcp.y) ** 2) ** 0.5,
        1e-5
    )

def pinch_ratio(tip_a, tip_b, scale: float) -> float:
    d = ((tip_a.x - tip_b.x) ** 2 + (tip_a.y - tip_b.y) ** 2) ** 0.5
    return d / scale

def is_finger_extended(tip, pip, mcp=None, threshold: float = 0.01) -> bool:
    """True when fingertip is above PIP joint (lower Y in camera coords)."""
    return tip.y < pip.y - threshold

def is_thumb_extended(thumb_tip, thumb_ip, thumb_mcp, wrist) -> bool:
    """Thumb extension check using X-axis distance from wrist."""
    # Thumb is extended when tip is far from wrist in X direction
    dx_tip = abs(thumb_tip.x - wrist.x)
    dx_mcp = abs(thumb_mcp.x - wrist.x)
    return dx_tip > dx_mcp * 1.3

def is_thumb_up(thumb_tip, thumb_ip, index_mcp, wrist) -> bool:
    """True when thumb points upward and is the only extended digit."""
    return thumb_tip.y < thumb_ip.y and thumb_tip.y < wrist.y - 0.08


# ─────────────────────────────────────────────────────────────────────────────
# Hand State Classifier
# ─────────────────────────────────────────────────────────────────────────────
class HandState:
    POINT = "POINT"            # ☝️  Index only
    OPEN_PALM = "OPEN_PALM"    # 🖐️  All fingers
    FIST = "FIST"              # ✊  All curled
    TWO_FINGERS = "TWO_FINGER" # ✌️  Index + Middle
    THREE_FINGERS = "THREE_FINGER"  # Index + Middle + Ring
    THUMBS_UP = "THUMBS_UP"   # 👍  Only thumb extended upward
    UNKNOWN = "UNKNOWN"


def classify_hand_state(lm) -> str:
    """Classify the hand into one of the defined states."""
    # Landmark indices
    thumb_tip = lm[4]; thumb_ip = lm[3]; thumb_mcp = lm[2]
    idx_tip = lm[8];   idx_pip = lm[6]
    mid_tip = lm[12];  mid_pip = lm[10]
    ring_tip = lm[16]; ring_pip = lm[14]
    pinky_tip = lm[20]; pinky_pip = lm[18]
    wrist = lm[0]

    ext_idx   = is_finger_extended(idx_tip,   idx_pip,   threshold=0.01)
    ext_mid   = is_finger_extended(mid_tip,   mid_pip,   threshold=0.01)
    ext_ring  = is_finger_extended(ring_tip,  ring_pip,  threshold=0.01)
    ext_pinky = is_finger_extended(pinky_tip, pinky_pip, threshold=0.01)
    ext_thumb = is_thumb_extended(thumb_tip, thumb_ip, thumb_mcp, wrist)

    n_ext = sum([ext_idx, ext_mid, ext_ring, ext_pinky])

    # Thumbs Up: only thumb extended, rest curled, thumb pointing up
    if not ext_idx and not ext_mid and not ext_ring and not ext_pinky:
        if is_thumb_up(thumb_tip, thumb_ip, lm[5], wrist):
            return HandState.THUMBS_UP
        return HandState.FIST

    # Open Palm: all 4 fingers + thumb
    if n_ext >= 4 and ext_thumb:
        return HandState.OPEN_PALM

    # Three Fingers: index + middle + ring (not pinky)
    if ext_idx and ext_mid and ext_ring and not ext_pinky:
        return HandState.THREE_FINGERS

    # Two Fingers: index + middle only
    if ext_idx and ext_mid and not ext_ring and not ext_pinky:
        return HandState.TWO_FINGERS

    # Point: index only
    if ext_idx and not ext_mid and not ext_ring and not ext_pinky:
        return HandState.POINT

    return HandState.UNKNOWN


# ─────────────────────────────────────────────────────────────────────────────
# Main CameraManager v3
# ─────────────────────────────────────────────────────────────────────────────
class CameraManager:
    _instance = None
    _lock = threading.Lock()

    HAND_MODEL_URL = (
        "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
        "hand_landmarker/float16/1/hand_landmarker.task"
    )
    POSE_MODEL_URL = (
        "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
        "pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
    )

    # Pinch thresholds (fraction of hand scale)
    PINCH_CLOSED = 0.22
    PINCH_OPEN   = 0.30

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self, camera_index: int = 0):
        if self._initialized:
            return

        self.camera_index = camera_index
        self.cap = None
        self.latest_frame = None
        self.latest_annotated_frame = None
        self.running = False
        self.thread = None
        self._frame_lock = threading.Lock()

        # Landmark cache for overlay
        self._last_hand_landmarks = None
        self._last_pose_landmarks = None
        self._last_hand_state = HandState.UNKNOWN
        self._last_action_label = ""

        self.models_dir = os.path.dirname(os.path.abspath(__file__))
        self.hand_model_path = os.path.join(self.models_dir, "hand_landmarker.task")
        self.pose_model_path = os.path.join(self.models_dir, "pose_landmarker_lite.task")

        self.hand_landmarker = None
        self.pose_landmarker = None

        self.screen_width, self.screen_height = pyautogui.size()

        self._ensure_models()
        self._init_landmarkers()

        # ── Cursor Tracking (Kalman + micro-jitter suppressor) ────────────
        self._kf_x = KalmanFilter1D(process_noise=8e-4, measurement_noise=0.025)
        self._kf_y = KalmanFilter1D(process_noise=8e-4, measurement_noise=0.025)
        self._js_x = JitterSuppressor(deadzone=1.2)
        self._js_y = JitterSuppressor(deadzone=1.2)
        self._last_cursor_time = time.perf_counter()

        # ROI: Use central portion of camera for full screen mapping
        self.cam_roi_x = (0.12, 0.88)
        self.cam_roi_y = (0.08, 0.92)

        # ── Dedicated Cursor Worker Thread ────────────────────────────────
        self._cursor_pos: Optional[Tuple[int, int]] = None
        self._cursor_lock = threading.Lock()
        self._cursor_event = threading.Event()
        self._cursor_thread = threading.Thread(target=self._cursor_worker, daemon=True)
        self._cursor_thread.start()

        # ── Gesture States ────────────────────────────────────────────────
        self.gs_left_click  = GestureState("left_click",  cooldown=0.06)
        self.gs_right_click = GestureState("right_click", cooldown=0.40)
        self.gs_drag        = GestureState("drag",        cooldown=0.05)
        self.gs_scroll      = GestureState("scroll",      cooldown=0.00)

        # Swipe-based gesture states
        self.gs_palm_swipe     = GestureState("palm_swipe",     cooldown=0.8)
        self.gs_fist_swipe     = GestureState("fist_swipe",     cooldown=0.8)
        self.gs_three_swipe    = GestureState("three_swipe",    cooldown=0.8)
        self.gs_palm_hold      = GestureState("palm_hold",      cooldown=2.0)
        self.gs_fist_hold      = GestureState("fist_hold",      cooldown=2.0)
        self.gs_thumbs_up      = GestureState("thumbs_up",      cooldown=1.5)
        self.gs_zoom           = GestureState("zoom",           cooldown=0.3)

        # Swipe detectors (one per hand state that uses swiping)
        self._palm_swipe = SwipeDetector(threshold=0.12, ratio=1.3)
        self._fist_swipe = SwipeDetector(threshold=0.12, ratio=1.3)
        self._three_swipe = SwipeDetector(threshold=0.14, ratio=1.3)

        # ── Scroll / Inertia ─────────────────────────────────────────────
        self._scroll_vel_tracker = VelocityTracker(window=6)
        self._scroll_ref_y: Optional[float] = None
        self._inertia_active = False

        # ── Two-finger zoom tracking ─────────────────────────────────────
        self._zoom_ref_dist: Optional[float] = None

        # ── Drag safety ──────────────────────────────────────────────────
        self._drag_active = False

        # ── Admin / Pose ─────────────────────────────────────────────────
        self.admin_present = False
        self.admin_gesture_history: List[Tuple[float, str]] = []

        # ── Hand state vote buffer ───────────────────────────────────────
        self._state_vote: Deque[str] = collections.deque(maxlen=4)

        # ── Performance counters ─────────────────────────────────────────
        self._fps_counter = 0
        self._fps_time = time.perf_counter()
        self._current_fps = 0.0

        self._initialized = True
        print("[CameraManager v3] ✓ Initialized — Iron Man Mode ready.")

    # ─────────────────────────────────────────────────────────────────────────
    # Model management
    # ─────────────────────────────────────────────────────────────────────────
    def _ensure_models(self):
        for url, path, name in [
            (self.HAND_MODEL_URL, self.hand_model_path, "Hand Landmarker"),
            (self.POSE_MODEL_URL, self.pose_model_path, "Pose Landmarker"),
        ]:
            if not os.path.exists(path):
                print(f"[CameraManager] Downloading {name}…")
                try:
                    urllib.request.urlretrieve(url, path)
                    print(f"[CameraManager] ✓ {name} downloaded.")
                except Exception as e:
                    print(f"[CameraManager] ✗ {name} download failed: {e}")

    def _init_landmarkers(self):
        try:
            if os.path.exists(self.hand_model_path):
                opts = vision.HandLandmarkerOptions(
                    base_options=mp_python.BaseOptions(model_asset_path=self.hand_model_path),
                    num_hands=1,
                    min_hand_detection_confidence=0.55,
                    min_hand_presence_confidence=0.55,
                    min_tracking_confidence=0.55,
                )
                self.hand_landmarker = vision.HandLandmarker.create_from_options(opts)
                print("[CameraManager] ✓ Hand Landmarker ready.")

            if os.path.exists(self.pose_model_path):
                opts_pose = vision.PoseLandmarkerOptions(
                    base_options=mp_python.BaseOptions(model_asset_path=self.pose_model_path),
                    output_segmentation_masks=False,
                    min_pose_detection_confidence=0.55,
                    min_pose_presence_confidence=0.55,
                    min_tracking_confidence=0.55,
                )
                self.pose_landmarker = vision.PoseLandmarker.create_from_options(opts_pose)
                print("[CameraManager] ✓ Pose Landmarker ready.")
        except Exception as e:
            print(f"[CameraManager] ✗ Landmarker init failed: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # Camera lifecycle
    # ─────────────────────────────────────────────────────────────────────────
    def start(self):
        if self.running:
            return
        print("[CameraManager v3] Starting camera loop…")
        backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
        self.cap = cv2.VideoCapture(self.camera_index, backend)

        if self.cap is None or not self.cap.isOpened():
            print("[CameraManager] ✗ Failed to open camera.")
            return

        # Request optimal settings for low latency
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        self.cap.set(cv2.CAP_PROP_FPS, 60)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self.running = True
        self.thread = threading.Thread(target=self._update_loop, daemon=True)
        self.thread.start()

    def stop(self):
        print("[CameraManager v3] Stopping…")
        self.running = False
        self._inertia_active = False
        if self.thread:
            self.thread.join(timeout=2.0)
        if self.cap:
            self.cap.release()
            self.cap = None
        self.latest_frame = None

    # ─────────────────────────────────────────────────────────────────────────
    # Dedicated Cursor Worker — processes latest position only (drops stale)
    # ─────────────────────────────────────────────────────────────────────────
    def _cursor_worker(self):
        """High-priority thread that moves the cursor. Drops stale positions."""
        while True:
            self._cursor_event.wait()
            self._cursor_event.clear()
            with self._cursor_lock:
                pos = self._cursor_pos
            if pos is not None:
                _win_set_cursor(pos[0], pos[1])

    def _queue_cursor_move(self, x: int, y: int):
        """Non-blocking: updates the target position and wakes the worker."""
        with self._cursor_lock:
            self._cursor_pos = (x, y)
        self._cursor_event.set()

    # ─────────────────────────────────────────────────────────────────────────
    # Main capture + processing loop — 60 FPS ML inference
    # ─────────────────────────────────────────────────────────────────────────
    def _update_loop(self):
        # Pre-allocate inference frame
        infer_size = (640, 480)

        while self.running:
            if not self.cap:
                break
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.002)
                continue

            frame = cv2.flip(frame, 1)

            with self._frame_lock:
                self.latest_frame = frame

            now = time.perf_counter()

            # ── FPS Counter ──────────────────────────────────────────────
            self._fps_counter += 1
            if now - self._fps_time >= 1.0:
                self._current_fps = self._fps_counter / (now - self._fps_time)
                self._fps_counter = 0
                self._fps_time = now

            # ── ML Inference at full camera rate ─────────────────────────
            # Downscale for inference (640x480 is plenty for MediaPipe)
            small = cv2.resize(frame, infer_size, interpolation=cv2.INTER_LINEAR)
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

            self._process_hands(mp_img, now)
            self._process_pose(mp_img, now)

            # Build annotated preview frame
            annotated = self._draw_overlays(frame)
            with self._frame_lock:
                self.latest_annotated_frame = annotated

    # ─────────────────────────────────────────────────────────────────────────
    # Cursor mapping with Kalman + deadzone
    # ─────────────────────────────────────────────────────────────────────────
    def _map_to_screen(self, nx: float, ny: float, now: float) -> Tuple[int, int]:
        x0, x1 = self.cam_roi_x
        y0, y1 = self.cam_roi_y
        nx = (nx - x0) / max(x1 - x0, 1e-5)
        ny = (ny - y0) / max(y1 - y0, 1e-5)
        nx = max(0.0, min(1.0, nx))
        ny = max(0.0, min(1.0, ny))

        raw_x = nx * self.screen_width
        raw_y = ny * self.screen_height

        dt = now - self._last_cursor_time
        self._last_cursor_time = now

        # Stage 1: Kalman filter
        kx = self._kf_x.step(raw_x, dt)
        ky = self._kf_y.step(raw_y, dt)

        # Stage 2: Micro-jitter suppressor (sub-pixel deadzone only)
        sx = self._js_x.step(kx)
        sy = self._js_y.step(ky)

        return (int(max(0, min(sx, self.screen_width - 1))),
                int(max(0, min(sy, self.screen_height - 1))))

    # ─────────────────────────────────────────────────────────────────────────
    # Hand processing
    # ─────────────────────────────────────────────────────────────────────────
    def _process_hands(self, mp_image, now: float):
        if not self.hand_landmarker:
            return
        try:
            result = self.hand_landmarker.detect(mp_image)
        except Exception:
            return

        if not result.hand_landmarks:
            self._last_hand_landmarks = None
            self._on_hand_lost(now)
            return

        lm = result.hand_landmarks[0]
        self._last_hand_landmarks = lm

        # Classify hand state with vote buffer for stability
        raw_state = classify_hand_state(lm)
        self._state_vote.append(raw_state)
        votes = collections.Counter(self._state_vote)
        top_state, count = votes.most_common(1)[0]
        # Require 3/4 frames agreement for state change
        hand_state = top_state if count >= 3 else self._last_hand_state
        
        # Detect state transitions to reset swipe detectors
        if hand_state != self._last_hand_state:
            self._on_state_change(hand_state, now)
        self._last_hand_state = hand_state

        # Dispatch based on hand state
        self._dispatch_gesture(hand_state, lm, now)

    def _on_state_change(self, new_state: str, now: float):
        """Reset swipe detectors and release held gestures on state change."""
        self._palm_swipe.reset()
        self._fist_swipe.reset()
        self._three_swipe.reset()

        # Release any held click/drag
        if self._drag_active:
            if sys.platform == "win32":
                _win_mouse_event(MOUSEEVENTF_LEFTUP)
            else:
                pyautogui.mouseUp(_pause=False)
            self._drag_active = False
        if self.gs_left_click.active:
            self.gs_left_click.deactivate(now)
            if sys.platform == "win32":
                _win_mouse_event(MOUSEEVENTF_LEFTUP)
            else:
                pyautogui.mouseUp(_pause=False)

        # Release scroll
        if self.gs_scroll.active:
            self.gs_scroll.deactivate(now)
            self._scroll_ref_y = None
            self._fire_inertia()

        # Release palm/fist holds
        self.gs_palm_hold.deactivate(now)
        self.gs_fist_hold.deactivate(now)
        self.gs_thumbs_up.deactivate(now)

        # Reset zoom
        self._zoom_ref_dist = None

    def _on_hand_lost(self, now: float):
        """Gracefully release all held gestures when tracking is lost."""
        if self.gs_left_click.active or self._drag_active:
            if sys.platform == "win32":
                _win_mouse_event(MOUSEEVENTF_LEFTUP)
            else:
                pyautogui.mouseUp(_pause=False)
            self._drag_active = False
            self.gs_left_click.deactivate(now)
        if self.gs_scroll.active:
            self.gs_scroll.deactivate(now)
            self._scroll_ref_y = None
            self._fire_inertia()
        self._scroll_vel_tracker.clear()

        # Reset all swipe detectors
        self._palm_swipe.reset()
        self._fist_swipe.reset()
        self._three_swipe.reset()
        self.gs_palm_hold.deactivate(now)
        self.gs_fist_hold.deactivate(now)
        self.gs_thumbs_up.deactivate(now)
        self._last_hand_state = HandState.UNKNOWN

    # ─────────────────────────────────────────────────────────────────────────
    # Gesture Dispatcher — routes based on hand state
    # ─────────────────────────────────────────────────────────────────────────
    def _dispatch_gesture(self, state: str, lm, now: float):
        idx_tip = lm[8]
        thumb_tip = lm[4]
        mid_tip = lm[12]
        scale = hand_scale(lm)
        screen_x, screen_y = self._map_to_screen(idx_tip.x, idx_tip.y, now)

        if state == HandState.POINT:
            self._handle_point_mode(lm, idx_tip, thumb_tip, mid_tip, scale, screen_x, screen_y, now)
            self._last_action_label = "CURSOR"

        elif state == HandState.OPEN_PALM:
            self._handle_palm_mode(lm, idx_tip, now)

        elif state == HandState.FIST:
            self._handle_fist_mode(lm, idx_tip, now)

        elif state == HandState.TWO_FINGERS:
            self._handle_two_finger_mode(lm, idx_tip, mid_tip, scale, now)

        elif state == HandState.THREE_FINGERS:
            self._handle_three_finger_mode(lm, idx_tip, now)

        elif state == HandState.THUMBS_UP:
            self._handle_thumbs_up(lm, now)

        else:
            # Unknown state — still move cursor
            self._queue_cursor_move(screen_x, screen_y)
            self._last_action_label = "TRACKING"

    # ─────────────────────────────────────────────────────────────────────────
    # POINT MODE — Cursor, Click, Drag
    # ─────────────────────────────────────────────────────────────────────────
    def _handle_point_mode(self, lm, idx_tip, thumb_tip, mid_tip, scale,
                           screen_x, screen_y, now):
        # Always move cursor
        self._queue_cursor_move(screen_x, screen_y)

        lp = pinch_ratio(idx_tip, thumb_tip, scale)
        rp = pinch_ratio(mid_tip, thumb_tip, scale)

        left_pinch = lp < self.PINCH_CLOSED
        left_open = lp > self.PINCH_OPEN
        right_pinch = rp < self.PINCH_CLOSED and not left_pinch

        if left_pinch:
            self._handle_left_click(now)
            self._last_action_label = "CLICK" if not self._drag_active else "DRAG"
        elif right_pinch:
            self._handle_right_click(now)
            self._last_action_label = "RIGHT CLICK"
        else:
            if self.gs_left_click.active and left_open:
                self._release_left_click(now)
            self._last_action_label = "CURSOR"

    # ─────────────────────────────────────────────────────────────────────────
    # OPEN PALM MODE — Tab Switch, Task View, Desktop, Alt+Tab
    # ─────────────────────────────────────────────────────────────────────────
    def _handle_palm_mode(self, lm, idx_tip, now: float):
        self._palm_swipe.start(idx_tip.x, idx_tip.y)

        # Check for swipe
        direction = self._palm_swipe.detect(idx_tip.x, idx_tip.y)
        if direction and self.gs_palm_swipe.try_activate(now):
            if direction == "left":
                pyautogui.hotkey("ctrl", "shift", "tab")
                self._last_action_label = "◀ PREV TAB"
            elif direction == "right":
                pyautogui.hotkey("ctrl", "tab")
                self._last_action_label = "NEXT TAB ▶"
            elif direction == "up":
                pyautogui.hotkey("win", "tab")
                self._last_action_label = "⬆ TASK VIEW"
            elif direction == "down":
                pyautogui.hotkey("win", "d")
                self._last_action_label = "⬇ DESKTOP"
            self._palm_swipe.reset()
            self.gs_palm_swipe.deactivate(now)
            return

        # Hold detection — Alt+Tab
        if not direction:
            if not self.gs_palm_hold.active:
                self.gs_palm_hold.try_activate(now)
            elif self.gs_palm_hold.held_duration(now) > 1.5:
                pyautogui.hotkey("alt", "tab")
                self._last_action_label = "ALT+TAB"
                self.gs_palm_hold.deactivate(now)
                self._palm_swipe.reset()
                return

        self._last_action_label = "🖐️ PALM"

    # ─────────────────────────────────────────────────────────────────────────
    # FIST MODE — Back/Forward, Maximize/Minimize, Close Tab
    # ─────────────────────────────────────────────────────────────────────────
    def _handle_fist_mode(self, lm, idx_tip, now: float):
        # Use wrist for fist tracking (more stable when fingers are curled)
        wrist = lm[0]
        self._fist_swipe.start(wrist.x, wrist.y)

        direction = self._fist_swipe.detect(wrist.x, wrist.y)
        if direction and self.gs_fist_swipe.try_activate(now):
            if direction == "left":
                pyautogui.hotkey("alt", "left")
                self._last_action_label = "◀ BACK"
            elif direction == "right":
                pyautogui.hotkey("alt", "right")
                self._last_action_label = "FORWARD ▶"
            elif direction == "up":
                pyautogui.hotkey("win", "up")
                self._last_action_label = "⬆ MAXIMIZE"
            elif direction == "down":
                pyautogui.hotkey("win", "down")
                self._last_action_label = "⬇ MINIMIZE"
            self._fist_swipe.reset()
            self.gs_fist_swipe.deactivate(now)
            return

        # Hold detection — Close Tab
        if not direction:
            if not self.gs_fist_hold.active:
                self.gs_fist_hold.try_activate(now)
            elif self.gs_fist_hold.held_duration(now) > 1.5:
                pyautogui.hotkey("ctrl", "w")
                self._last_action_label = "CLOSE TAB ✕"
                self.gs_fist_hold.deactivate(now)
                self._fist_swipe.reset()
                return

        self._last_action_label = "✊ FIST"

    # ─────────────────────────────────────────────────────────────────────────
    # TWO FINGER MODE — Scroll + Zoom
    # ─────────────────────────────────────────────────────────────────────────
    def _handle_two_finger_mode(self, lm, idx_tip, mid_tip, scale, now: float):
        # Inter-finger distance for zoom detection
        ip_dist = pinch_ratio(idx_tip, mid_tip, scale)

        # Scroll (vertical movement)
        if not self.gs_scroll.active:
            self.gs_scroll.try_activate(now)
            self._scroll_ref_y = idx_tip.y
            self._scroll_vel_tracker.clear()
            self._inertia_active = False
            self._zoom_ref_dist = ip_dist
            self._last_action_label = "✌️ SCROLL"
            return

        if self._scroll_ref_y is None:
            self._scroll_ref_y = idx_tip.y
            return

        dy = idx_tip.y - self._scroll_ref_y
        self._scroll_vel_tracker.push(idx_tip.y, now)

        if abs(dy) > 0.006:
            scroll_px = -int(np.sign(dy) * (abs(dy) * 10000) ** 1.1)
            scroll_px = int(np.clip(scroll_px, -800, 800))
            if sys.platform == "win32":
                # Direct Win32 scroll (faster)
                ctypes.windll.user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, scroll_px, 0)
            else:
                pyautogui.scroll(scroll_px)
            self._scroll_ref_y = idx_tip.y
            self._last_action_label = "SCROLL ↕"
        else:
            # Check for zoom (fingers spreading/pinching)
            if self._zoom_ref_dist is not None:
                zoom_delta = ip_dist - self._zoom_ref_dist
                if abs(zoom_delta) > 0.06 and self.gs_zoom.try_activate(now):
                    if zoom_delta > 0:
                        pyautogui.hotkey("ctrl", "=")  # Zoom in (= is + without shift)
                        self._last_action_label = "ZOOM IN 🔍"
                    else:
                        pyautogui.hotkey("ctrl", "-")
                        self._last_action_label = "ZOOM OUT 🔍"
                    self._zoom_ref_dist = ip_dist
                    self.gs_zoom.deactivate(now)

    # ─────────────────────────────────────────────────────────────────────────
    # THREE FINGER MODE — Virtual Desktop Switch
    # ─────────────────────────────────────────────────────────────────────────
    def _handle_three_finger_mode(self, lm, idx_tip, now: float):
        self._three_swipe.start(idx_tip.x, idx_tip.y)

        direction = self._three_swipe.detect(idx_tip.x, idx_tip.y)
        if direction and self.gs_three_swipe.try_activate(now):
            if direction == "left":
                pyautogui.hotkey("win", "ctrl", "left")
                self._last_action_label = "◀ DESKTOP"
            elif direction == "right":
                pyautogui.hotkey("win", "ctrl", "right")
                self._last_action_label = "DESKTOP ▶"
            elif direction == "up":
                pyautogui.hotkey("win", "tab")
                self._last_action_label = "⬆ TASK VIEW"
            elif direction == "down":
                pyautogui.hotkey("win", "d")
                self._last_action_label = "⬇ DESKTOP"
            self._three_swipe.reset()
            self.gs_three_swipe.deactivate(now)
            return

        self._last_action_label = "🤟 3-FINGER"

    # ─────────────────────────────────────────────────────────────────────────
    # THUMBS UP — Play/Pause
    # ─────────────────────────────────────────────────────────────────────────
    def _handle_thumbs_up(self, lm, now: float):
        if not self.gs_thumbs_up.active:
            self.gs_thumbs_up.try_activate(now)
        elif self.gs_thumbs_up.held_duration(now) > 0.8:
            pyautogui.press("playpause")
            self._last_action_label = "▶⏸ PLAY/PAUSE"
            self.gs_thumbs_up.deactivate(now)
            return
        self._last_action_label = "👍 THUMBS UP"

    # ─────────────────────────────────────────────────────────────────────────
    # Click Handlers
    # ─────────────────────────────────────────────────────────────────────────
    def _handle_left_click(self, now: float):
        if not self.gs_left_click.active:
            activated = self.gs_left_click.try_activate(now)
            if activated:
                gap = now - self.gs_left_click.last_triggered
                if 0.08 < gap < 0.40:
                    # Double-click
                    pyautogui.doubleClick(_pause=False)
                    self._drag_active = False
                else:
                    if sys.platform == "win32":
                        _win_mouse_event(MOUSEEVENTF_LEFTDOWN)
                    else:
                        pyautogui.mouseDown(_pause=False)
        else:
            # Long-hold → drag
            if self.gs_left_click.held_duration(now) > 0.40 and not self._drag_active:
                self._drag_active = True

    def _release_left_click(self, now: float):
        if self.gs_left_click.active:
            self.gs_left_click.deactivate(now)
            if sys.platform == "win32":
                _win_mouse_event(MOUSEEVENTF_LEFTUP)
            else:
                pyautogui.mouseUp(_pause=False)
            self._drag_active = False

    def _handle_right_click(self, now: float):
        if self.gs_right_click.try_activate(now):
            if sys.platform == "win32":
                _win_mouse_event(MOUSEEVENTF_RIGHTDOWN)
                time.sleep(0.02)
                _win_mouse_event(MOUSEEVENTF_RIGHTUP)
            else:
                pyautogui.rightClick(_pause=False)
            self.gs_right_click.deactivate(now)

    # ─────────────────────────────────────────────────────────────────────────
    # Scroll Inertia
    # ─────────────────────────────────────────────────────────────────────────
    def _fire_inertia(self):
        vel = self._scroll_vel_tracker.velocity()
        if abs(vel) < 0.005:
            return
        self._inertia_active = True

        def _inertia():
            v = -vel * 4000
            friction = 0.80
            while self._inertia_active and abs(v) > 5:
                if sys.platform == "win32":
                    ctypes.windll.user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, int(v), 0)
                else:
                    pyautogui.scroll(int(v))
                v *= friction
                time.sleep(0.016)
            self._inertia_active = False

        threading.Thread(target=_inertia, daemon=True).start()

    # ─────────────────────────────────────────────────────────────────────────
    # Pose processing (admin detection)
    # ─────────────────────────────────────────────────────────────────────────
    def _process_pose(self, mp_image, now: float):
        if not self.pose_landmarker:
            return
        try:
            result = self.pose_landmarker.detect(mp_image)
        except Exception:
            return

        if not result.pose_landmarks:
            self.admin_present = False
            self._last_pose_landmarks = None
            return

        self.admin_present = True
        plm = result.pose_landmarks[0]
        self._last_pose_landmarks = plm

        # Gesture recognition
        left_wrist    = plm[15]; right_wrist   = plm[16]
        left_shoulder = plm[11]; right_shoulder= plm[12]
        nose          = plm[0]
        left_hip      = plm[23]; right_hip     = plm[24]

        gestures: List[str] = []
        if left_wrist.y < left_shoulder.y and right_wrist.y < right_shoulder.y:
            gestures.append("Hands Raised")
        if left_wrist.y < left_shoulder.y and right_wrist.y >= right_shoulder.y:
            gestures.append("Left Wave")
        elif right_wrist.y < right_shoulder.y and left_wrist.y >= left_shoulder.y:
            gestures.append("Right Wave")

        hip_mid_x = (left_hip.x + right_hip.x) / 2
        if nose.x < hip_mid_x - 0.10:
            gestures.append("Leaning Left")
        elif nose.x > hip_mid_x + 0.10:
            gestures.append("Leaning Right")

        for g in gestures:
            self.admin_gesture_history.append((now, g))
        if len(self.admin_gesture_history) > 100:
            self.admin_gesture_history = self.admin_gesture_history[-100:]

    # ─────────────────────────────────────────────────────────────────────────
    # Overlay drawing — HUD
    # ─────────────────────────────────────────────────────────────────────────
    _HAND_CONNECTIONS = [
        (0,1),(1,2),(2,3),(3,4),
        (0,5),(5,6),(6,7),(7,8),
        (0,9),(9,10),(10,11),(11,12),
        (0,13),(13,14),(14,15),(15,16),
        (0,17),(17,18),(18,19),(19,20),
        (5,9),(9,13),(13,17),
    ]

    _POSE_CONNECTIONS = [
        (11,12),(11,13),(13,15),(12,14),(14,16),
        (11,23),(12,24),(23,24),
    ]

    # Color scheme by hand state
    _STATE_COLORS = {
        HandState.POINT:         (0, 255, 120),    # Green
        HandState.OPEN_PALM:     (255, 180, 0),    # Orange
        HandState.FIST:          (0, 100, 255),     # Blue
        HandState.TWO_FINGERS:   (255, 200, 0),    # Yellow
        HandState.THREE_FINGERS: (255, 100, 50),    # Red-Orange
        HandState.THUMBS_UP:     (180, 80, 255),   # Purple
        HandState.UNKNOWN:       (150, 150, 150),   # Gray
    }

    def _draw_overlays(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        out = frame.copy()

        lm = self._last_hand_landmarks
        state = self._last_hand_state
        state_color = self._STATE_COLORS.get(state, (150, 150, 150))

        if lm is not None:
            pts = [(int(p.x * w), int(p.y * h)) for p in lm]

            # Skeleton with state-colored lines
            for a, b in self._HAND_CONNECTIONS:
                cv2.line(out, pts[a], pts[b], state_color, 2, cv2.LINE_AA)

            # Landmark dots
            for i, (px, py) in enumerate(pts):
                radius = 7 if i in (4, 8, 12, 16, 20) else 4
                cv2.circle(out, (px, py), radius, (255, 255, 255), -1, cv2.LINE_AA)
                cv2.circle(out, (px, py), radius, state_color, 2, cv2.LINE_AA)

            # State + Action badge
            cx, cy = pts[0]  # Wrist position for badge
            badge_text = f"{state} | {self._last_action_label}"
            text_size = cv2.getTextSize(badge_text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)[0]
            badge_x = max(4, cx - text_size[0] // 2)
            badge_y = max(30, cy - 30)

            # Badge background
            cv2.rectangle(out,
                          (badge_x - 4, badge_y - 18),
                          (badge_x + text_size[0] + 4, badge_y + 4),
                          (10, 10, 10), -1)
            cv2.rectangle(out,
                          (badge_x - 4, badge_y - 18),
                          (badge_x + text_size[0] + 4, badge_y + 4),
                          state_color, 1)
            cv2.putText(out, badge_text, (badge_x, badge_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, state_color, 1, cv2.LINE_AA)

            # Cursor crosshair at index fingertip
            if state == HandState.POINT:
                cx, cy = pts[8]
                cv2.drawMarker(out, (cx, cy), (0, 255, 200),
                               cv2.MARKER_CROSS, 22, 2, cv2.LINE_AA)

        # ── Pose skeleton ─────────────────────────────────────────────────
        plm = self._last_pose_landmarks
        if plm is not None:
            ppts = [(int(p.x * w), int(p.y * h)) for p in plm]
            for a, b in self._POSE_CONNECTIONS:
                if a < len(ppts) and b < len(ppts):
                    cv2.line(out, ppts[a], ppts[b], (80, 160, 255), 2, cv2.LINE_AA)
            for i in [11, 12, 13, 14, 15, 16, 23, 24]:
                if i < len(ppts):
                    cv2.circle(out, ppts[i], 5, (255, 220, 60), -1, cv2.LINE_AA)

        # ── HUD ──────────────────────────────────────────────────────────
        # Top-left: Admin status
        status_color = (0, 220, 100) if self.admin_present else (80, 80, 80)
        status_text = "ADMIN DETECTED" if self.admin_present else "NO ADMIN"
        cv2.rectangle(out, (8, 8), (200, 30), (10, 10, 10), -1)
        cv2.putText(out, status_text, (14, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.52, status_color, 1, cv2.LINE_AA)

        # Top-right: FPS + Hand indicator
        fps_text = f"{self._current_fps:.0f} FPS"
        cv2.putText(out, fps_text, (w - 90, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 200), 1, cv2.LINE_AA)

        hand_color = (0, 230, 120) if lm is not None else (60, 60, 60)
        cv2.circle(out, (w - 100, 18), 6, hand_color, -1, cv2.LINE_AA)

        # Bottom: Mode indicator bar
        mode_text = f"MODE: {state}"
        cv2.rectangle(out, (0, h - 28), (w, h), (10, 10, 10), -1)
        cv2.putText(out, mode_text, (10, h - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, state_color, 1, cv2.LINE_AA)

        action_text = self._last_action_label
        if action_text:
            act_size = cv2.getTextSize(action_text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)[0]
            cv2.putText(out, action_text, (w - act_size[0] - 10, h - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)

        return out

    # ─────────────────────────────────────────────────────────────────────────
    # Public APIs
    # ─────────────────────────────────────────────────────────────────────────
    async def get_latest_frame_b64(self, annotated: bool = False) -> Optional[dict]:
        with self._frame_lock:
            src = self.latest_annotated_frame if annotated else self.latest_frame
            if src is None:
                src = self.latest_frame
            if src is None:
                return None
            frame = src.copy()

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(frame_rgb)
        img.thumbnail([1024, 1024])

        def _encode() -> str:
            buf = io.BytesIO()
            img.save(buf, format="jpeg", quality=80)
            buf.seek(0)
            return "data:image/jpeg;base64," + base64.b64encode(buf.read()).decode()

        return await asyncio.to_thread(_encode)

    def get_admin_status(self) -> str:
        if not self.admin_present:
            return "Admin is not present."
        cutoff = time.time() - 5.0
        recent = [g for t, g in self.admin_gesture_history if t >= cutoff]
        if recent:
            most_common = collections.Counter(recent).most_common(1)[0][0]
            return f"Admin is present and gesturing: {most_common}."
        return "Admin is present and neutral."

    def get_debug_info(self) -> dict:
        return {
            "hand_state": self._last_hand_state,
            "action": self._last_action_label,
            "drag_active": self._drag_active,
            "scroll_active": self.gs_scroll.active,
            "admin_present": self.admin_present,
            "fps": self._current_fps,
            "recent_gestures": [
                g for t, g in self.admin_gesture_history
                if time.time() - t < 5.0
            ],
        }


# ─────────────────────────────────────────────────────────────────────────────
# Singleton accessor
# ─────────────────────────────────────────────────────────────────────────────
def get_camera_manager(camera_index: int = 0) -> CameraManager:
    return CameraManager(camera_index)