"""
gpu_config.py — VYRA Resource Distribution Layer
=================================================
Import this module FIRST in server.py and vyra.py before any other heavy imports.

Strategy for RTX 3050 Laptop (4GB VRAM, Compute 8.6) + 4-core/8-thread CPU:
  GPU  → All ML inference: voice embedding, speaker diarization, torch models
  CPU  → Async I/O (FastAPI/uvicorn), audio preprocessing (librosa), CV2 frames
  RAM  → Shared CUDA memory pool capped so system stays responsive
"""

import os
import sys
import logging

log = logging.getLogger("gpu_config")

# ── 1. PIN CUDA TO RTX 3050 (device 0) ──────────────────────────────────────
# Prevents accidental fallback to Intel Iris Xe (device 1) for torch models.
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")

# ── 2. CUDA MEMORY ALLOCATOR — prevent fragmentation on 4 GB VRAM ───────────
# max_split_size_mb: largest contiguous chunk the caching allocator will split.
# 512 MB keeps VRAM fragmentation low while still allowing large batch allocs.
os.environ.setdefault(
    "PYTORCH_CUDA_ALLOC_CONF",
    "max_split_size_mb:512"   # expandable_segments not supported on Windows builds
)

# ── 3. cuDNN / cuBLAS environment ────────────────────────────────────────────
# TF32 gives ~2-3x speedup on Ampere (RTX 30xx) with negligible accuracy loss.
os.environ.setdefault("NVIDIA_TF32_OVERRIDE", "1")

# Deterministic ops off → faster (non-reproducible, which is fine for inference)
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")

# ── 4. NUMPY / OpenBLAS — don't fight torch for CPU threads ─────────────────
# Physical cores = 4. Reserve 2 for the asyncio event loop + I/O, give 2 to
# numpy/scipy/librosa CPU work.  Torch gets its own tuning below.
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "2")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "2")

# ── 5. TORCH THREAD TUNING ───────────────────────────────────────────────────
def _configure_torch() -> bool:
    """Apply torch GPU/CPU settings. Returns True if CUDA is available."""
    try:
        import torch

        # ── GPU: cuDNN benchmark ──────────────────────────────────────────────
        # Runs a short benchmark on first call to find fastest conv algorithm.
        # Great for models with fixed input sizes (voice, CV).
        torch.backends.cudnn.benchmark = True
        torch.backends.cudnn.enabled   = True

        # TF32 on Ampere — big speed win, trivial precision loss
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32        = True

        # ── CPU threads ───────────────────────────────────────────────────────
        # intra-op: how many threads a single op (e.g. matmul) uses.
        # With 4 physical cores and asyncio taking 1-2, give torch 4.
        torch.set_num_threads(4)

        # inter-op: parallelism between independent ops in the compute graph.
        # 2 is plenty; more than 4 physical cores causes contention.
        torch.set_num_interop_threads(2)

        cuda_ok = torch.cuda.is_available()
        if cuda_ok:
            dev = torch.cuda.get_device_properties(0)
            vram_gb = dev.total_memory / 1024 ** 3

            log.info(
                "[gpu_config] GPU: %s | VRAM: %.1f GB | Compute: %d.%d | "
                "cuDNN benchmark ON | TF32 ON",
                dev.name, vram_gb, dev.major, dev.minor,
            )

            # Warm up CUDA context so first inference isn't slow
            _warmup_cuda(torch)
        else:
            log.warning("[gpu_config] CUDA not available — running on CPU only")

        log.info(
            "[gpu_config] Torch intra-op threads: %d | inter-op threads: %d",
            torch.get_num_threads(), torch.get_num_interop_threads(),
        )
        return cuda_ok

    except ImportError:
        log.warning("[gpu_config] torch not installed — skipping GPU config")
        return False


def _warmup_cuda(torch) -> None:
    """
    Push a tiny tensor through CUDA to initialize the context.
    Avoids a ~300 ms stall on the first real inference call.
    """
    try:
        dummy = torch.zeros(1, device="cuda")
        dummy.add_(1)   # in-place: no unused assignment
        del dummy
        torch.cuda.synchronize()
        log.info("[gpu_config] CUDA context warmed up")
    except Exception as exc:
        log.warning("[gpu_config] CUDA warmup failed: %s", exc)


# ── 6. DEVICE HELPER — use everywhere in the project ───────────────────────
def get_device() -> "torch.device":          # type: ignore[name-defined]
    """Return the best available torch device (cuda:0 or cpu)."""
    import torch
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def move_to_device(model):                   # type: ignore[return]
    """Move a torch model to the optimal device and return it."""
    import torch
    device = get_device()
    try:
        model = model.to(device)
        log.info("[gpu_config] Model moved to %s", device)
    except Exception as exc:
        log.warning("[gpu_config] Could not move model to %s: %s", device, exc)
    return model


# ── 7. MEMORY MANAGEMENT HELPERS ────────────────────────────────────────────
def clear_cuda_cache() -> None:
    """Release unused VRAM back to the pool. Call after heavy inference."""
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def cuda_memory_summary() -> str:
    """Return a human-readable VRAM usage string."""
    try:
        import torch
        if not torch.cuda.is_available():
            return "CUDA unavailable"
        alloc  = torch.cuda.memory_allocated(0)  / 1024 ** 2
        reserv = torch.cuda.memory_reserved(0)   / 1024 ** 2
        total  = torch.cuda.get_device_properties(0).total_memory / 1024 ** 2
        return (
            f"VRAM allocated: {alloc:.0f} MB | "
            f"reserved: {reserv:.0f} MB | "
            f"total: {total:.0f} MB"
        )
    except ImportError:
        return "torch not installed"


# ── 8. RUN CONFIGURATION ON IMPORT ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

CUDA_AVAILABLE: bool = _configure_torch()
DEVICE_NAME: str = (
    "cuda" if CUDA_AVAILABLE else "cpu"
)

log.info("[gpu_config] Active compute device: %s", DEVICE_NAME)
log.info("[gpu_config] OMP/OpenBLAS threads capped at 2 (asyncio gets the rest)")
