import asyncio
import io
import threading
import concurrent.futures
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Any
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout


# ---------------------------------------------------------------------------
# Registry helpers using subprocess (reg.exe) — no winreg import needed
# ---------------------------------------------------------------------------

def _reg_query_value(hive: str, key_path: str, value_name: str = "") -> Optional[str]:
    """
    Query a single registry value using 'reg.exe'.
    hive: 'HKCU' or 'HKLM'
    Returns the data string, or None on failure.
    """
    args = ["reg", "query", f"{hive}\\{key_path}"]
    if value_name:
        args += ["/v", value_name]
    else:
        args.append("/ve")  # default value
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            # Lines look like: "    ProgId    REG_SZ    ChromeHTML"
            if "REG_SZ" in line:
                parts = line.split("REG_SZ", 1)
                if len(parts) > 1:
                    return parts[1].strip()
    except Exception:
        pass
    return None


def _get_default_browser_id() -> str:
    """Returns raw default browser identifier string for current OS."""
    system = platform.system()
    try:
        if system == "Windows":
            val = _reg_query_value(
                "HKCU",
                r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
                "ProgId"
            )
            if val:
                return val.lower()

        elif system == "Darwin":
            result = subprocess.run(
                ["defaults", "read",
                 "com.apple.LaunchServices/com.apple.launchservices.secure",
                 "LSHandlers"],
                capture_output=True, text=True, timeout=5
            )
            return result.stdout.lower()

        elif system == "Linux":
            result = subprocess.run(
                ["xdg-settings", "get", "default-web-browser"],
                capture_output=True, text=True, timeout=5
            )
            return result.stdout.lower()

    except Exception:
        pass

    return ""


_BROWSER_BINARIES: dict[str, dict[str, list[str]]] = {
    "Windows": {
        "opera":   ["opera.exe"],
        "brave":   ["brave.exe"],
        "vivaldi": ["vivaldi.exe"],
        "chrome":  ["chrome.exe"],
        "firefox": ["firefox.exe"],
    },
    "Darwin": {
        "opera":   ["opera"],
        "brave":   ["brave browser", "brave"],
        "vivaldi": ["vivaldi"],
        "chrome":  ["google chrome", "google-chrome"],
        "firefox": ["firefox"],
    },
    "Linux": {
        "opera":   ["opera", "opera-stable"],
        "brave":   ["brave-browser", "brave"],
        "vivaldi": ["vivaldi-stable", "vivaldi"],
        "chrome":  ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"],
        "firefox": ["firefox"],
    },
}


def _get_opera_executable() -> Optional[str]:
    """Locate Opera executable via reg.exe on Windows."""
    if platform.system() != "Windows":
        return None
    candidate_keys = [
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\opera.exe",
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\launcher.exe",
        r"SOFTWARE\Clients\StartMenuInternet\OperaStable\shell\open\command",
        r"SOFTWARE\Clients\StartMenuInternet\OperaGXStable\shell\open\command",
    ]
    for key_path in candidate_keys:
        for hive in ["HKLM", "HKCU"]:
            val = _reg_query_value(hive, key_path)
            if val:
                exe = val.strip().strip('"').split('"')[0].split(" --")[0].strip()
                if exe and Path(exe).exists():
                    print(f"[Browser] 🔍 Opera found via registry: {exe}")
                    return exe
    return None


def _find_browser_executable(prog_id: str) -> tuple[str, Optional[str], Optional[str]]:
    system: str  = platform.system()
    os_bins      = _BROWSER_BINARIES.get(system, {})

    if any(x in prog_id for x in ["firefox", "mozilla"]):
        return "firefox", None, None

    if "safari" in prog_id:
        return "webkit", None, None

    if "edge" in prog_id:
        return "chromium", None, "msedge"

    if "opera" in prog_id:
        exe = _get_opera_executable()
        if exe:
            return "chromium", exe, None
        for binary in os_bins.get("opera", []):
            path = shutil.which(binary)
            if path:
                return "chromium", path, None

    browser_patterns: dict[str, list[str]] = {
        "brave":   ["brave"],
        "vivaldi": ["vivaldi"],
        "chrome":  ["chrome"],
    }
    for browser_name, patterns in browser_patterns.items():
        if not any(p in prog_id for p in patterns):
            continue
        binaries = os_bins.get(browser_name, [])
        for binary in binaries:
            path = shutil.which(binary)
            if path:
                print(f"[Browser] 🔍 Found {browser_name} at: {path}")
                return "chromium", path, None

    if "chrome" in prog_id or not prog_id:
        return "chromium", None, "chrome"

    return "chromium", None, None


# ---------------------------------------------------------------------------
# Browser Thread — runs its own asyncio event loop in a daemon thread
# ---------------------------------------------------------------------------

class _BrowserThread:

    def __init__(self) -> None:
        self._loop:       Optional[asyncio.AbstractEventLoop] = None
        self._thread:     Optional[threading.Thread]          = None
        self._ready:      threading.Event                     = threading.Event()
        self._playwright: Any                                 = None
        self._browser:    Any                                 = None
        self._context:    Any                                 = None
        self._page:       Any                                 = None

    def start(self) -> None:
        thread = self._thread
        if thread is not None and thread.is_alive():
            return
        new_thread = threading.Thread(
            target=self._run_loop, daemon=True, name="BrowserThread"
        )
        new_thread.start()
        self._thread = new_thread
        self._ready.wait(timeout=15)

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._init())
        self._ready.set()
        loop.run_forever()

    async def _init(self) -> None:
        self._playwright = await async_playwright().start()

    def run(self, coro: Any, timeout: int = 30) -> Any:
        loop = self._loop
        if loop is None:
            raise RuntimeError("BrowserThread not started.")
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=timeout)

    async def _get_page(self) -> Any:
        if self._page is None or self._page.is_closed():
            await self._launch()
        return self._page

    async def _launch(self) -> None:
        prog_id                        = _get_default_browser_id()
        engine_name, exe_path, channel = _find_browser_executable(prog_id)
        engine                         = getattr(self._playwright, engine_name)

        launch_kwargs: dict[str, Any] = {"headless": False}

        if engine_name == "chromium":
            launch_kwargs["args"] = ["--start-maximized"]

        if exe_path is not None:
            launch_kwargs["executable_path"] = exe_path
        elif channel is not None:
            launch_kwargs["channel"] = channel

        try:
            if self._browser is None or not self._browser.is_connected():
                self._browser = await engine.launch(**launch_kwargs)
                print(
                    f"[Browser] ✅ Launched ({engine_name}"
                    f"{' / ' + channel if channel else ''}"
                    f"{' / ' + exe_path if exe_path else ''})"
                )
        except Exception as e:
            print(f"[Browser] ⚠️ Launch failed ({e}), falling back to built-in Chromium")
            self._browser = await self._playwright.chromium.launch(
                headless=False,
                args=["--start-maximized"]
            )
        self._context = await self._browser.new_context(
            viewport=None,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        self._page = await self._context.new_page()

    async def _close(self) -> None:
        browser = self._browser
        if browser is not None:
            await browser.close()
            self._browser = None
            self._page    = None
        pw = self._playwright
        if pw is not None:
            await pw.stop()
            self._playwright = None

    async def _go_to(self, url: str) -> str:
        if not url.startswith("http"):
            url = "https://" + url
        page = await self._get_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            current_url: str = page.url
            return f"Opened: {current_url}"
        except PlaywrightTimeout:
            return f"Timeout loading: {url}"
        except Exception as e:
            return f"Navigation error: {e}"

    async def _search(self, query: str, engine: str = "google") -> str:
        engines: dict[str, str] = {
            "google":     f"https://www.google.com/search?q={query.replace(' ', '+')}",
            "bing":       f"https://www.bing.com/search?q={query.replace(' ', '+')}",
            "duckduckgo": f"https://duckduckgo.com/?q={query.replace(' ', '+')}",
        }
        url = engines.get(engine.lower(), engines["google"])
        return await self._go_to(url)

    async def _click(self, selector: Optional[str] = None, text: Optional[str] = None) -> str:
        page = await self._get_page()
        try:
            if text is not None:
                await page.get_by_text(text, exact=False).first.click(timeout=8000)
                return f"Clicked: '{text}'"
            elif selector is not None:
                await page.click(selector, timeout=8000)
                return f"Clicked: {selector}"
            return "No selector or text provided."
        except PlaywrightTimeout:
            return "Element not found or not clickable."
        except Exception as e:
            return f"Click error: {e}"

    async def _type(
        self,
        selector: Optional[str] = None,
        text: str = "",
        clear_first: bool = True
    ) -> str:
        page = await self._get_page()
        try:
            element = page.locator(selector).first if selector is not None else page.locator(":focus")
            if clear_first:
                await element.clear()
            await element.type(text, delay=50)
            return "Text typed."
        except Exception as e:
            return f"Type error: {e}"

    async def _scroll(self, direction: str = "down", amount: int = 500) -> str:
        page = await self._get_page()
        try:
            y = amount if direction == "down" else -amount
            await page.mouse.wheel(0, y)
            return f"Scrolled {direction}."
        except Exception as e:
            return f"Scroll error: {e}"

    async def _press(self, key: str) -> str:
        page = await self._get_page()
        try:
            await page.keyboard.press(key)
            return f"Pressed: {key}"
        except Exception as e:
            return f"Key error: {e}"

    async def _get_text(self) -> str:
        page = await self._get_page()
        try:
            text: str = await page.inner_text("body")
            # Use io.StringIO.read(n) — avoids slice syntax that Pyre2 rejects on str
            return io.StringIO(text).read(4000)
        except Exception as e:
            return f"Could not get page text: {e}"

    async def _fill_form(self, fields: dict[str, Any]) -> str:
        page    = await self._get_page()
        results: list[str] = []
        for selector, value in fields.items():
            try:
                el = page.locator(selector).first
                await el.clear()
                await el.type(str(value), delay=40)
                results.append(f"✓ {selector}")
            except Exception as e:
                results.append(f"✗ {selector}: {e}")
        return "Form filled: " + ", ".join(results)

    async def _smart_click(self, description: str) -> str:
        page       = await self._get_page()
        desc_lower = description.lower()

        role_hints: dict[str, list[str]] = {
            "button":    ["button", "buton", "btn"],
            "link":      ["link", "bağlantı"],
            "searchbox": ["search", "arama"],
            "textbox":   ["input", "field", "alan"],
        }
        for role, keywords in role_hints.items():
            if any(k in desc_lower for k in keywords):
                try:
                    await page.get_by_role(role).first.click(timeout=5000)
                    return f"Clicked ({role}): '{description}'"
                except Exception:
                    pass

        try:
            await page.get_by_text(description, exact=False).first.click(timeout=5000)
            return f"Clicked (text): '{description}'"
        except Exception:
            pass

        try:
            await page.get_by_placeholder(description, exact=False).first.click(timeout=5000)
            return f"Clicked (placeholder): '{description}'"
        except Exception:
            pass

        return f"Could not find: '{description}'"

    async def _smart_type(self, description: str, text: str) -> str:
        page = await self._get_page()

        locators: list[tuple[str, Any]] = [
            ("placeholder", page.get_by_placeholder(description, exact=False)),
            ("label",       page.get_by_label(description, exact=False)),
            ("role",        page.get_by_role("textbox")),
        ]
        for method, locator in locators:
            try:
                el = locator.first
                await el.clear()
                await el.type(text, delay=50)
                return f"Typed into ({method}): '{description}'"
            except Exception:
                continue

        return f"Could not find input: '{description}'"

    async def _close_browser(self) -> str:
        await self._close()
        return "Browser closed."


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_bt:         _BrowserThread = _BrowserThread()
_bt_started: bool           = False
_bt_lock:    threading.Lock = threading.Lock()


def _ensure_started() -> None:
    global _bt_started
    with _bt_lock:
        if not _bt_started:
            _bt.start()
            _bt_started = True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def browser_control(
    parameters:     dict[str, Any],
    response:       Any  = None,
    player:         Any  = None,
    session_memory: Any  = None
) -> str:
    """
    Browser controller — auto-detects and uses system default browser.

    parameters:
        action      : go_to | search | click | type | scroll | fill_form |
                      smart_click | smart_type | get_text | press | close
        url         : URL for go_to
        query       : search query
        engine      : google | bing | duckduckgo (default: google)
        selector    : CSS selector for click/type
        text        : text to click or type
        description : element description for smart_click/smart_type
        direction   : up | down for scroll
        amount      : scroll amount in pixels (default: 500)
        key         : key name for press (e.g. Enter, Escape, Tab)
        fields      : {selector: value} dict for fill_form
        clear_first : bool, clear input before typing (default: True)
    """
    _ensure_started()

    action: str  = (parameters or {}).get("action", "").lower().strip()
    result: str  = "Unknown action."

    try:
        if action == "go_to":
            result = str(_bt.run(_bt._go_to(parameters.get("url", ""))))

        elif action == "search":
            result = str(_bt.run(_bt._search(
                parameters.get("query", ""),
                parameters.get("engine", "google")
            )))

        elif action == "click":
            result = str(_bt.run(_bt._click(
                selector=parameters.get("selector"),
                text=parameters.get("text")
            )))

        elif action == "type":
            result = str(_bt.run(_bt._type(
                selector=parameters.get("selector"),
                text=parameters.get("text", ""),
                clear_first=parameters.get("clear_first", True)
            )))

        elif action == "scroll":
            result = str(_bt.run(_bt._scroll(
                direction=parameters.get("direction", "down"),
                amount=parameters.get("amount", 500)
            )))

        elif action == "fill_form":
            result = str(_bt.run(_bt._fill_form(parameters.get("fields", {}))))

        elif action == "smart_click":
            result = str(_bt.run(_bt._smart_click(parameters.get("description", ""))))

        elif action == "smart_type":
            result = str(_bt.run(_bt._smart_type(
                parameters.get("description", ""),
                parameters.get("text", "")
            )))

        elif action == "get_text":
            result = str(_bt.run(_bt._get_text()))

        elif action == "press":
            result = str(_bt.run(_bt._press(parameters.get("key", "Enter"))))

        elif action == "close":
            result = str(_bt.run(_bt._close_browser()))

        else:
            result = f"Unknown action: {action}"

    except concurrent.futures.TimeoutError:
        result = "Browser action timed out."
    except Exception as e:
        result = f"Browser error: {e}"

    print(f"[Browser] {io.StringIO(result).read(80)}")
    if player is not None:
        player.write_log(f"[browser] {io.StringIO(result).read(60)}")

    return result