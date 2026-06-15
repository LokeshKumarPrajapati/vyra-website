"""
win_ocr.py — OCR / screen text reading for VYRA Windows control.
Primary: pytesseract + mss. Fallback: Windows.Media.Ocr via PowerShell WinRT.
"""
import json
import subprocess
import os


def _ok(output: str, action: str = "") -> str:
    return json.dumps({"status": "ok", "action": action, "output": output})


def _err(msg: str, action: str = "") -> str:
    return json.dumps({"status": "error", "action": action, "error": msg})


def _run_ps(script: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return r.stdout.strip() or r.stderr.strip() or "No output."
    except Exception as e:
        return f"Error: {e}"


def _grab_screen(x=None, y=None, width=None, height=None):
    """Grab screen region or full screen. Returns PIL Image."""
    import mss
    from PIL import Image
    with mss.mss() as sct:
        if x is not None and y is not None and width and height:
            monitor = {"top": int(y), "left": int(x), "width": int(width), "height": int(height)}
        else:
            monitor = sct.monitors[0]
        sshot = sct.grab(monitor)
        return Image.frombytes("RGB", sshot.size, sshot.bgra, "raw", "BGRX")


def _ocr_image(img, lang="eng", preprocess=True) -> str:
    """Run pytesseract OCR on a PIL Image."""
    import pytesseract
    from PIL import ImageFilter, ImageEnhance

    if preprocess:
        # Grayscale + contrast + slight sharpen for better accuracy
        img = img.convert("L")
        img = ImageEnhance.Contrast(img).enhance(2.0)
        img = img.filter(ImageFilter.SHARPEN)

    config = "--psm 3 --oem 3"  # auto page segmentation, LSTM
    try:
        text = pytesseract.image_to_string(img, lang=lang, config=config)
        return text.strip()
    except pytesseract.pytesseract.TesseractNotFoundError:
        raise RuntimeError(
            "Tesseract not found. Install from: https://github.com/UB-Mannheim/tesseract/wiki\n"
            "Then add it to PATH or set pytesseract.pytesseract.tesseract_cmd")


def _winrt_ocr(img_path: str) -> str:
    """Fallback: use Windows.Media.Ocr via PowerShell for machines without Tesseract."""
    ps_script = f"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Storage.StorageFile,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Foundation,ContentType=WindowsRuntime]

$lang = [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | Select-Object -First 1
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
if (-not $engine) {{ Write-Output "Windows OCR engine not available."; exit }}

$file = [Windows.Storage.StorageFile]::GetFileFromPathAsync("{img_path.replace(chr(92), chr(92)*2)}").GetAwaiter().GetResult()
$stream = $file.OpenAsync([Windows.Storage.FileAccessMode]::Read).GetAwaiter().GetResult()
$decoder = [Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream).GetAwaiter().GetResult()
$bitmap = $decoder.GetSoftwareBitmapAsync().GetAwaiter().GetResult()
$result = $engine.RecognizeAsync($bitmap).GetAwaiter().GetResult()
$result.Lines | ForEach-Object {{ $_.Text }}
"""
    return _run_ps(ps_script, timeout=30)


def win_ocr(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action   = parameters.get("action", "").lower().strip()
    x        = parameters.get("x")
    y        = parameters.get("y")
    width    = parameters.get("width")
    height   = parameters.get("height")
    img_path = parameters.get("image_path", "").strip()
    lang     = parameters.get("language", "eng")
    save_screenshot = parameters.get("save_screenshot", False)

    try:
        # ── read_screen ───────────────────────────────────────────────────────
        if action == "read_screen":
            try:
                img = _grab_screen()
                text = _ocr_image(img, lang)
                if not text.strip():
                    return _ok("No readable text detected on screen.", action)
                return _ok(text, action)
            except RuntimeError as e:
                # Fallback to WinRT OCR
                import tempfile
                tmp = os.path.join(tempfile.gettempdir(), "vyra_ocr_screen.png")
                img.save(tmp)
                text = _winrt_ocr(tmp)
                try:
                    os.remove(tmp)
                except Exception:
                    pass
                return _ok(text if text.strip() else "No text detected.", action)
            except ImportError as e:
                return _err(f"Missing dependency: {e}. Run: pip install pytesseract mss Pillow", action)

        # ── read_region ───────────────────────────────────────────────────────
        elif action == "read_region":
            if x is None or y is None or not width or not height:
                return _err("'x', 'y', 'width', 'height' are required for read_region.", action)
            try:
                img = _grab_screen(x, y, width, height)
                if save_screenshot:
                    tmp = os.path.join(os.path.expanduser("~"), "Desktop", "vyra_region_ocr.png")
                    img.save(tmp)
                text = _ocr_image(img, lang)
                return _ok(text if text.strip() else "No text detected in region.", action)
            except RuntimeError as e:
                img = _grab_screen(x, y, width, height)
                import tempfile
                tmp = os.path.join(tempfile.gettempdir(), "vyra_ocr_region.png")
                img.save(tmp)
                text = _winrt_ocr(tmp)
                try:
                    os.remove(tmp)
                except Exception:
                    pass
                return _ok(text if text.strip() else "No text in region.", action)
            except ImportError as e:
                return _err(f"Missing dependency: {e}. Run: pip install pytesseract mss Pillow", action)

        # ── read_file ─────────────────────────────────────────────────────────
        elif action == "read_file":
            if not img_path:
                return _err("'image_path' is required.", action)
            if not os.path.exists(img_path):
                return _err(f"File not found: {img_path}", action)
            try:
                from PIL import Image
                img = Image.open(img_path)
                text = _ocr_image(img, lang)
                return _ok(text if text.strip() else "No readable text in image.", action)
            except RuntimeError as e:
                text = _winrt_ocr(img_path)
                return _ok(text if text.strip() else "No text detected.", action)
            except ImportError as e:
                return _err(f"Missing dependency: {e}. Run: pip install pytesseract Pillow", action)

        # ── read_clipboard_image ──────────────────────────────────────────────
        elif action == "read_clipboard_image":
            try:
                from PIL import ImageGrab
                img = ImageGrab.grabclipboard()
                if img is None:
                    return _err("No image found in clipboard.", action)
                text = _ocr_image(img, lang)
                return _ok(text if text.strip() else "No text in clipboard image.", action)
            except ImportError as e:
                return _err(f"Missing dependency: {e}. Run: pip install pytesseract Pillow", action)

        # ── find_text_on_screen ───────────────────────────────────────────────
        elif action == "find_text_on_screen":
            """Locate where specific text appears on screen (returns bounding boxes)."""
            search_text = parameters.get("search_text", "").strip()
            if not search_text:
                return _err("'search_text' is required.", action)
            try:
                import pytesseract
                from PIL import Image
                img = _grab_screen()
                data = pytesseract.image_to_data(img, lang=lang, output_type=pytesseract.Output.DICT)
                matches = []
                for i, word in enumerate(data["text"]):
                    if search_text.lower() in word.lower() and int(data["conf"][i]) > 30:
                        matches.append({
                            "word": word,
                            "x": data["left"][i],
                            "y": data["top"][i],
                            "w": data["width"][i],
                            "h": data["height"][i],
                            "confidence": data["conf"][i],
                        })
                if matches:
                    lines = [f"Found '{search_text}' at {len(matches)} location(s):"]
                    for m in matches:
                        lines.append(f"  '{m['word']}' at ({m['x']}, {m['y']}) size {m['w']}x{m['h']} conf={m['confidence']}%")
                    return _ok("\n".join(lines), action)
                return _ok(f"'{search_text}' not found on screen.", action)
            except ImportError as e:
                return _err(f"Missing dependency: {e}. Run: pip install pytesseract Pillow", action)

        # ── screenshot_with_ocr ───────────────────────────────────────────────
        elif action == "screenshot_with_ocr":
            """Take a screenshot, save it, AND return OCR text."""
            try:
                save_path = parameters.get("save_path",
                            os.path.join(os.path.expanduser("~"), "Desktop", "vyra_screenshot.png"))
                img = _grab_screen()
                img.save(save_path)
                text = _ocr_image(img, lang)
                return _ok(f"Screenshot saved to: {save_path}\n\n--- OCR Text ---\n{text}", action)
            except ImportError as e:
                return _err(f"Missing: {e}. Run: pip install pytesseract mss Pillow", action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: read_screen, read_region, read_file, "
                "read_clipboard_image, find_text_on_screen, screenshot_with_ocr",
                action)

    except Exception as e:
        return _err(str(e), action)
