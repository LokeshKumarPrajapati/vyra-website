import asyncio
import threading
import time
import re
import os
from pathlib import Path

from playwright.async_api import async_playwright
import win32com.client
import pyautogui
import pygetwindow as gw

from actions.send_message import send_message


class _WhatsAppAutoReplyService:
    def __init__(self):
        self._thread = None
        self._loop = None
        self._stop_event = threading.Event()
        self._running = False
        self._message = "I am busy right now. I will call you back soon."
        self._call_message = "I am busy right now. Please text me and I will call you back."
        self._mode = "desktop"
        self._interval = 4
        self._cooldown_sec = 300
        self._last_replied = {}
        self._player = None
        self._auto_answer_calls = True
        self._last_call_action = {}
        self._call_cooldown_sec = 90
        self._page = None

    @staticmethod
    def _speak_out_loud(text: str):
        speaker = win32com.client.Dispatch("SAPI.SpVoice")
        
        # Try to route directly into VB-Cable if installed
        for i in range(speaker.GetAudioOutputs().Count):
            device = speaker.GetAudioOutputs().Item(i)
            if "CABLE" in device.GetDescription():
                speaker.AudioOutputStream = device
                break
                
        speaker.Speak(text)

    def _log(self, text: str):
        print(f"[WA-AutoReply] {text}")
        if self._player:
            try:
                self._player.write_log(f"[wa] {text}")
            except Exception:
                pass

    def start(
        self,
        message: str | None = None,
        call_message: str | None = None,
        interval: int = 4,
        auto_answer_calls: bool = True,
        mode: str = "desktop",
        player=None,
    ) -> str:
        if self._running:
            return "WhatsApp auto-reply is already running."

        if message:
            self._message = message.strip()
        if call_message:
            self._call_message = call_message.strip()
        self._mode = (mode or "desktop").strip().lower()
        if self._mode not in {"desktop", "web"}:
            self._mode = "desktop"
        self._interval = max(2, min(int(interval or 4), 30))
        self._auto_answer_calls = bool(auto_answer_calls)
        self._player = player

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="WhatsAppAutoReply")
        self._thread.start()
        self._running = True
        if self._mode == "desktop":
            return (
                "WhatsApp Desktop assistant started. Incoming calls will be monitored in your installed WhatsApp app."
            )
        return (
            "WhatsApp assistant started. Open WhatsApp Web once and keep it logged in. "
            "Incoming call auto-answer is ON."
            if self._auto_answer_calls
            else "WhatsApp assistant started. Open WhatsApp Web once and keep it logged in."
        )

    def stop(self) -> str:
        if not self._running:
            return "WhatsApp auto-reply is not running."
        self._stop_event.set()
        self._running = False
        return "WhatsApp auto-reply stopped."

    def status(self) -> str:
        state = "running" if self._running else "stopped"
        mode = "ON" if self._auto_answer_calls else "OFF"
        return (
            f"WhatsApp auto-reply is {state}. Mode: {self._mode}. Incoming call auto-answer: {mode}. "
            f"Chat message: {self._message} | Call message: {self._call_message}"
        )

    def say(self, message: str) -> str:
        text = (message or "").strip()
        if not text:
            return "Please provide a message to say on the call."

        try:
            self._speak_out_loud(text)
        except Exception as e:
            return f"Could not speak call message: {e}"

        if self._loop and self._page:
            try:
                fut = asyncio.run_coroutine_threadsafe(
                    self._send_message(self._page, text), self._loop
                )
                sent = bool(fut.result(timeout=4))
                if sent:
                    return "Spoken on system audio and also sent as WhatsApp text message."
            except Exception:
                pass

        return "Spoken on system audio."

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._monitor())
        except Exception as e:
            self._log(f"Service crashed: {e}")
        finally:
            self._running = False

    async def _monitor(self):
        if self._mode == "desktop":
            await self._monitor_desktop()
            return

        profile_dir = Path(__file__).resolve().parent.parent / "data" / "whatsapp_profile"
        profile_dir.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=False,
                viewport=None,
                args=["--start-maximized"],
            )

            page = context.pages[0] if context.pages else await context.new_page()
            self._page = page
            await page.goto("https://web.whatsapp.com", wait_until="domcontentloaded")
            self._log("Monitoring WhatsApp Web for missed/incoming call indicators...")

            while not self._stop_event.is_set():
                try:
                    await self._scan_and_reply(page)
                except Exception as e:
                    self._log(f"Scan error: {e}")
                await asyncio.sleep(self._interval)

            await context.close()
            self._page = None

    async def _monitor_desktop(self):
        self._open_whatsapp_desktop()
        self._log("Monitoring WhatsApp Desktop for incoming call windows...")

        while not self._stop_event.is_set():
            try:
                await self._scan_desktop_calls()
            except Exception as e:
                self._log(f"Desktop scan error: {e}")
            await asyncio.sleep(self._interval)

    @staticmethod
    def _open_whatsapp_desktop():
        try:
            os.startfile("whatsapp:")
            time.sleep(1.2)
        except Exception:
            pass

    async def _scan_desktop_calls(self):
        try:
            import uiautomation as auto
            
            # Find all top-level windows with "WhatsApp" in the name
            for win in auto.GetRootControl().GetChildren():
                if not win.Name or "whatsapp" not in win.Name.lower():
                    continue
                    
                # Look for accept buttons inside this window
                answered = False
                found_call = False
                accept_btn = None
                
                for bname in ["Accept", "Answer", "Accept voice call", "Accept video call", "Accept call"]:
                    btn = win.ButtonControl(searchDepth=6, Name=bname)
                    if btn.Exists(0, 0):
                        found_call = True
                        accept_btn = btn
                        break
                        
                if found_call and accept_btn:
                    # Cooldown check
                    key = f"uiauto_{win.Name}_{bname}"
                    last_ts = self._last_call_action.get(key, 0)
                    if time.time() - last_ts < self._call_cooldown_sec:
                        continue
                        
                    self._last_call_action[key] = time.time()
                    self._log(f"Detected WhatsApp Call via UIAutomation: {win.Name}")
                    
                    if self._auto_answer_calls:
                        try:
                            # Try to invoke the button directly
                            accept_btn.Invoke()
                            answered = True
                            self._log(f"Auto-answered via UIAutomation ({bname}).")
                            await asyncio.sleep(0.5)
                        except Exception as e:
                            self._log(f"UIAutomation Invoke failed: {e}")
                            
                        # Fallback click
                        if not answered:
                            try:
                                rect = accept_btn.BoundingRectangle
                                cx = (rect.left + rect.right) // 2
                                cy = (rect.top + rect.bottom) // 2
                                pyautogui.click(cx, cy)
                                answered = True
                                self._log("Tried to answer the call (Fallback Click on Button).")
                                await asyncio.sleep(0.5)
                            except Exception as inner_e:
                                self._log(f"Fallback click failed: {inner_e}")
                    
                    if self._call_message:
                        try:
                            await asyncio.to_thread(self._speak_out_loud, self._call_message)
                            self._log(f"Spoke call message: {self._call_message}")
                        except Exception as e:
                            self._log(f"Desktop call speech failed: {e}")
                            
                    # Extract receiver from text paths if possible (heuristic)
                    receiver = None
                    # UWP WhatsApp often puts caller name in a text control before the voice call text
                    try:
                        texts = [t.Name for t in win.GetChildren()[0].GetChildren() if t.ControlType == auto.ControlType.TextControl and t.Name]
                        for idx, txt in enumerate(texts):
                            if "call" in txt.lower():
                                if idx > 0:
                                    receiver = texts[idx-1]
                                    break
                    except Exception:
                        pass
                        
                    if not receiver:
                        receiver = self._extract_name_from_title(win.Name)
                        
                    if receiver:
                        try:
                            await asyncio.to_thread(
                                send_message,
                                {"platform": "whatsapp", "receiver": receiver, "message_text": self._call_message},
                                None,
                                self._player,
                                None,
                            )
                            self._log(f"Sent WhatsApp message to {receiver}: {self._call_message}")
                        except Exception as e:
                            self._log(f"Desktop follow-up message failed: {e}")

        except Exception as e:
            self._log(f"Desktop scan error: {e}")

    @staticmethod
    def _extract_name_from_title(title: str) -> str | None:
        # Common patterns: "WhatsApp - John Doe calling" or "Incoming call from John Doe - WhatsApp"
        patterns = [
            r"from\s+(.+?)\s*-\s*whatsapp",
            r"whatsapp\s*-\s*(.+?)\s+calling",
            r"incoming\s+call\s+(.+?)\s*-\s*whatsapp",
        ]
        s = (title or "").strip()
        for pat in patterns:
            m = re.search(pat, s, flags=re.IGNORECASE)
            if m:
                name = m.group(1).strip()
                if name:
                    return name
        return None

    async def _scan_and_reply(self, page):
        if self._auto_answer_calls:
            await self._scan_and_handle_incoming_call(page)

        # Match common missed-call labels.
        candidates = [
            "Missed voice call",
            "Missed video call",
            "Missed call",
            "Incoming voice call",
            "Incoming video call",
        ]

        for text in candidates:
            rows = page.locator(f"div[role='listitem']:has-text('{text}')")
            count = await rows.count()
            if count == 0:
                continue

            for i in range(min(count, 5)):
                row = rows.nth(i)
                try:
                    await row.click(timeout=1200)
                    await asyncio.sleep(0.4)

                    title_loc = page.locator("header span[title]").first
                    chat_name = await title_loc.get_attribute("title") if await title_loc.count() else "unknown"
                    if not chat_name:
                        chat_name = "unknown"

                    last_ts = self._last_replied.get(chat_name, 0)
                    if time.time() - last_ts < self._cooldown_sec:
                        continue

                    sent = await self._send_message(page, self._message)
                    if sent:
                        self._last_replied[chat_name] = time.time()
                        self._log(f"Auto-replied to {chat_name}: {self._message}")
                except Exception:
                    continue

    async def _scan_and_handle_incoming_call(self, page):
        call_answer_selectors = [
            "button[aria-label*='Accept']",
            "button[aria-label*='Answer']",
            "div[role='button'][aria-label*='Accept']",
            "div[role='button'][aria-label*='Answer']",
            "button:has-text('Accept')",
            "button:has-text('Answer')",
        ]

        answer_btn = None
        for selector in call_answer_selectors:
            loc = page.locator(selector).first
            if await loc.count() > 0:
                answer_btn = loc
                break

        if not answer_btn:
            return

        chat_name = "unknown"
        title_loc = page.locator("header span[title]").first
        if await title_loc.count():
            t = await title_loc.get_attribute("title")
            if t:
                chat_name = t

        last_ts = self._last_call_action.get(chat_name, 0)
        if time.time() - last_ts < self._call_cooldown_sec:
            return

        await answer_btn.click(timeout=1200)
        await asyncio.sleep(0.8)

        self._last_call_action[chat_name] = time.time()
        self._log(f"Accepted WhatsApp call from {chat_name}.")

        # Best-effort: speak message aloud and send same text in chat.
        if self._call_message:
            try:
                await asyncio.to_thread(self._speak_out_loud, self._call_message)
            except Exception as e:
                self._log(f"Call speech failed: {e}")

            try:
                sent = await self._send_message(page, self._call_message)
                if sent:
                    self._log(f"Sent call follow-up message to {chat_name}: {self._call_message}")
            except Exception as e:
                self._log(f"Call follow-up message failed: {e}")

    async def _send_message(self, page, text: str) -> bool:
        input_selectors = [
            "div[aria-label='Type a message']",
            "div[contenteditable='true'][data-tab='10']",
            "footer div[contenteditable='true']",
        ]

        box = None
        for selector in input_selectors:
            loc = page.locator(selector).first
            if await loc.count() > 0:
                box = loc
                break

        if box is None:
            return False

        await box.click(timeout=1000)
        await box.fill(text)
        await page.keyboard.press("Enter")
        return True


_SERVICE = _WhatsAppAutoReplyService()


def whatsapp_auto_reply(parameters=None, response=None, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = str(params.get("action", "status")).strip().lower()
    message = params.get("message")
    call_message = params.get("call_message")
    auto_answer_calls = bool(params.get("auto_answer_calls", True))
    mode = str(params.get("mode", "desktop")).strip().lower()
    interval = int(params.get("interval", 4) or 4)

    if action == "start":
        return _SERVICE.start(
            message=message,
            call_message=call_message,
            interval=interval,
            auto_answer_calls=auto_answer_calls,
            mode=mode,
            player=player,
        )
    if action == "stop":
        return _SERVICE.stop()
    if action == "say":
        return _SERVICE.say(message or "")
    return _SERVICE.status()
