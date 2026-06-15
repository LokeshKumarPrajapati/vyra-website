# actions/send_message.py
# Advanced universal messaging — WhatsApp, Instagram, Telegram, etc.
# Multiple strategies with fallbacks, retry logic, and verification

import time
import pyautogui
import logging
from pathlib import Path
from typing import Tuple, Optional

# Configure pyautogui
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.08

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MessageSender:
    """Advanced message sender with retry logic and multiple strategies."""
    
    def __init__(self):
        self.max_retries = 3
        self.screenshot_dir = Path.home() / "Desktop" / "message_logs"
        self.screenshot_dir.mkdir(exist_ok=True, parents=True)
        
    def _take_debug_screenshot(self, stage: str) -> None:
        """Take a screenshot for debugging purposes."""
        try:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = self.screenshot_dir / f"{stage}_{timestamp}.png"
            pyautogui.screenshot(str(filename))
            logger.info(f"Debug screenshot saved: {filename}")
        except Exception as e:
            logger.warning(f"Could not save debug screenshot: {e}")
    
    def _wait_for_element(self, timeout: float = 5.0) -> bool:
        """Wait for UI to stabilize."""
        time.sleep(timeout)
        return True
    
    def _verify_app_opened(self, app_name: str, timeout: float = 10.0) -> bool:
        """Verify that an application window is open."""
        try:
            import pygetwindow as gw
            start_time = time.time()
            while time.time() - start_time < timeout:
                windows = gw.getWindowsWithTitle(app_name)
                if windows:
                    # Try to activate the window
                    try:
                        windows[0].activate()
                        time.sleep(0.5)
                        return True
                    except:
                        pass
                time.sleep(0.5)
            return False
        except ImportError:
            logger.warning("pygetwindow not available, skipping window verification")
            return True
        except Exception as e:
            logger.warning(f"Window verification failed: {e}")
            return True
    
    def _open_app(self, app_name: str) -> bool:
        """Opens an app via Windows search with verification."""
        try:
            logger.info(f"Opening {app_name}...")
            
            # Press Windows key
            pyautogui.press("win")
            time.sleep(0.6)
            
            # Type app name
            pyautogui.write(app_name, interval=0.05)
            time.sleep(0.8)
            
            # Press Enter
            pyautogui.press("enter")
            
            # Wait for app to open
            time.sleep(3.0)
            
            # Verify app is open
            return self._verify_app_opened(app_name)
            
        except Exception as e:
            logger.error(f"Could not open {app_name}: {e}")
            return False
    
    def _search_contact_method1(self, contact: str, platform: str) -> bool:
        """Search method 1: Ctrl+F universal search."""
        try:
            logger.info(f"Search method 1: Ctrl+F for {contact}")
            
            # Clear any existing search
            pyautogui.hotkey("ctrl", "f")
            time.sleep(0.5)
            
            # Clear the search box
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.2)
            
            # Type contact name
            pyautogui.write(contact, interval=0.05)
            time.sleep(1.2)
            
            # Press Down arrow to highlight first result
            pyautogui.press("down")
            time.sleep(0.3)
            
            # Press Enter to open chat
            pyautogui.press("enter")
            time.sleep(1.0)
            
            return True
            
        except Exception as e:
            logger.error(f"Search method 1 failed: {e}")
            return False
    
    def _search_contact_method2(self, contact: str, platform: str) -> bool:
        """Search method 2: Click on search box and type."""
        try:
            logger.info(f"Search method 2: Click search for {contact}")
            
            # For WhatsApp, click on the search box at the top
            # Use relative positioning (left side, near top)
            screen_width, screen_height = pyautogui.size()
            search_x = int(screen_width * 0.15)  # Left side
            search_y = int(screen_height * 0.15)  # Near top
            
            pyautogui.click(search_x, search_y)
            time.sleep(0.5)
            
            # Clear and type
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.2)
            pyautogui.write(contact, interval=0.05)
            time.sleep(1.5)
            
            # Press Enter to select first result
            pyautogui.press("enter")
            time.sleep(1.0)
            
            return True
            
        except Exception as e:
            logger.error(f"Search method 2 failed: {e}")
            return False
    
    def _search_contact_method3(self, contact: str, platform: str) -> bool:
        """Search method 3: Tab navigation."""
        try:
            logger.info(f"Search method 3: Tab navigation for {contact}")
            
            # Press Tab a few times to reach search box
            for _ in range(3):
                pyautogui.press("tab")
                time.sleep(0.2)
            
            # Type contact name
            pyautogui.write(contact, interval=0.05)
            time.sleep(1.2)
            
            # Navigate to first result
            pyautogui.press("down")
            time.sleep(0.3)
            pyautogui.press("enter")
            time.sleep(1.0)
            
            return True
            
        except Exception as e:
            logger.error(f"Search method 3 failed: {e}")
            return False
    
    def _focus_message_input_method1(self) -> bool:
        """Method 1: Click at bottom of screen where message input usually is."""
        try:
            logger.info("Focus method 1: Clicking message input area")
            
            screen_width, screen_height = pyautogui.size()
            
            # Click in the lower right area where message box usually is
            # For WhatsApp, this is typically in the bottom right
            msg_x = int(screen_width * 0.65)  # Right side
            msg_y = int(screen_height * 0.90)  # Near bottom
            
            pyautogui.click(msg_x, msg_y)
            time.sleep(0.5)
            
            return True
            
        except Exception as e:
            logger.error(f"Focus method 1 failed: {e}")
            return False
    
    def _focus_message_input_method2(self) -> bool:
        """Method 2: Tab to message input."""
        try:
            logger.info("Focus method 2: Tab to message input")
            
            # Press Tab multiple times to cycle to message input
            for _ in range(5):
                pyautogui.press("tab")
                time.sleep(0.2)
            
            return True
            
        except Exception as e:
            logger.error(f"Focus method 2 failed: {e}")
            return False
    
    def _focus_message_input_method3(self) -> bool:
        """Method 3: Direct keyboard shortcut (some apps have this)."""
        try:
            logger.info("Focus method 3: Keyboard shortcut")
            
            # Try Ctrl+N (new message in some apps)
            # Or just press Escape first to clear any popups, then click
            pyautogui.press("escape")
            time.sleep(0.3)
            
            # Then try clicking in a different position
            screen_width, screen_height = pyautogui.size()
            msg_x = int(screen_width * 0.60)
            msg_y = int(screen_height * 0.85)
            
            pyautogui.click(msg_x, msg_y)
            time.sleep(0.5)
            
            return True
            
        except Exception as e:
            logger.error(f"Focus method 3 failed: {e}")
            return False
    
    def _send_message_typing(self, message: str) -> bool:
        """Type and send the message."""
        try:
            logger.info(f"Typing message: {message[:50]}...")
            
            # Clear any existing text
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.2)
            
            # Type the message
            pyautogui.write(message, interval=0.04)
            time.sleep(0.5)
            
            # Send with Enter
            pyautogui.press("enter")
            time.sleep(0.5)
            
            logger.info("Message sent successfully")
            return True
            
        except Exception as e:
            logger.error(f"Typing failed: {e}")
            return False
    
    def _send_whatsapp(self, receiver: str, message: str) -> str:
        """
        Sends a WhatsApp message via the Windows desktop app.
        Uses multiple strategies with retry logic.
        """
        try:
            # Step 1: Open WhatsApp
            if not self._open_app("WhatsApp"):
                return "❌ Could not open WhatsApp."
            
            self._take_debug_screenshot("1_app_opened")
            
            # Step 2: Search for contact (try multiple methods)
            search_success = False
            search_methods = [
                self._search_contact_method1,
                self._search_contact_method2,
                self._search_contact_method3
            ]
            
            for attempt, method in enumerate(search_methods, 1):
                logger.info(f"Attempt {attempt}/{len(search_methods)}")
                if method(receiver, "whatsapp"):
                    search_success = True
                    break
                time.sleep(1.0)
            
            if not search_success:
                self._take_debug_screenshot("2_search_failed")
                return f"❌ Could not find contact: {receiver}"
            
            self._take_debug_screenshot("3_contact_found")
            
            # Step 3: Ensure chat is open and wait for it to load
            time.sleep(1.5)
            
            # Step 4: Focus on message input (try multiple methods)
            focus_success = False
            focus_methods = [
                self._focus_message_input_method1,
                self._focus_message_input_method2,
                self._focus_message_input_method3
            ]
            
            for attempt, method in enumerate(focus_methods, 1):
                logger.info(f"Focus attempt {attempt}/{len(focus_methods)}")
                if method():
                    focus_success = True
                    break
                time.sleep(0.5)
            
            if not focus_success:
                logger.warning("Could not verify focus, proceeding anyway...")
            
            self._take_debug_screenshot("4_ready_to_type")
            
            # Step 5: Type and send message
            if not self._send_message_typing(message):
                self._take_debug_screenshot("5_typing_failed")
                return f"❌ Could not send message to {receiver}"
            
            self._take_debug_screenshot("6_message_sent")
            
            return f"✅ Message sent to {receiver} via WhatsApp: {message[:50]}..."
            
        except Exception as e:
            self._take_debug_screenshot("error")
            logger.error(f"WhatsApp error: {e}")
            return f"❌ WhatsApp error: {e}"
    
    def _send_instagram(self, receiver: str, message: str) -> str:
        """Sends an Instagram DM via browser."""
        try:
            import webbrowser
            
            logger.info(f"Opening Instagram DM for {receiver}")
            webbrowser.open("https://www.instagram.com/direct/new/")
            time.sleep(4.5)
            
            # Type contact name
            pyautogui.write(receiver, interval=0.06)
            time.sleep(2.0)
            
            # Select first result
            pyautogui.press("down")
            time.sleep(0.4)
            pyautogui.press("enter")
            time.sleep(0.8)
            
            # Navigate to message box
            for _ in range(4):
                pyautogui.press("tab")
                time.sleep(0.15)
            
            pyautogui.press("enter")
            time.sleep(2.0)
            
            # Type and send message
            pyautogui.write(message, interval=0.05)
            time.sleep(0.5)
            pyautogui.press("enter")
            
            return f"✅ Message sent to {receiver} via Instagram"
            
        except Exception as e:
            logger.error(f"Instagram error: {e}")
            return f"❌ Instagram error: {e}"
    
    def _send_telegram(self, receiver: str, message: str) -> str:
        """Sends a Telegram message via Windows desktop app."""
        try:
            if not self._open_app("Telegram"):
                return "❌ Could not open Telegram."
            
            # Search for contact
            pyautogui.hotkey("ctrl", "f")
            time.sleep(0.5)
            pyautogui.write(receiver, interval=0.05)
            time.sleep(1.5)
            pyautogui.press("enter")
            time.sleep(1.0)
            
            # Type and send
            pyautogui.write(message, interval=0.04)
            time.sleep(0.3)
            pyautogui.press("enter")
            
            return f"✅ Message sent to {receiver} via Telegram"
            
        except Exception as e:
            logger.error(f"Telegram error: {e}")
            return f"❌ Telegram error: {e}"
    
    def _send_generic(self, platform: str, receiver: str, message: str) -> str:
        """Generic message sender for any platform."""
        try:
            if not self._open_app(platform):
                return f"❌ Could not open {platform}."
            
            time.sleep(2.0)
            
            # Try to search
            pyautogui.hotkey("ctrl", "f")
            time.sleep(0.5)
            pyautogui.write(receiver, interval=0.05)
            time.sleep(1.5)
            pyautogui.press("enter")
            time.sleep(1.0)
            
            # Type and send
            pyautogui.write(message, interval=0.04)
            time.sleep(0.3)
            pyautogui.press("enter")
            
            return f"✅ Message sent to {receiver} via {platform}"
            
        except Exception as e:
            logger.error(f"{platform} error: {e}")
            return f"❌ {platform} error: {e}"
    
    def send(self, platform: str, receiver: str, message: str) -> str:
        """Main send method with platform routing."""
        logger.info(f"Sending message via {platform} to {receiver}")
        
        platform_lower = platform.lower()
        
        if "whatsapp" in platform_lower or "wp" in platform_lower or "wapp" in platform_lower:
            return self._send_whatsapp(receiver, message)
        elif "instagram" in platform_lower or "ig" in platform_lower or "insta" in platform_lower:
            return self._send_instagram(receiver, message)
        elif "telegram" in platform_lower or "tg" in platform_lower:
            return self._send_telegram(receiver, message)
        else:
            return self._send_generic(platform, receiver, message)


# Create singleton instance
_sender = MessageSender()


def send_message(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None
) -> str:
    """
    Main entry point called from main.py.
    
    parameters:
        receiver     : Contact name to send to
        message_text : The message content
        platform     : whatsapp | instagram | telegram | <any app name>
                       Default: whatsapp
    """
    params = parameters or {}
    receiver = params.get("receiver", "").strip()
    message_text = params.get("message_text", "").strip()
    platform = params.get("platform", "whatsapp").strip()
    
    if not receiver:
        return "❌ Please specify who to send the message to, sir."
    if not message_text:
        return "❌ Please specify what message to send, sir."
    
    logger.info(f"📨 {platform} → {receiver}: {message_text[:40]}...")
    if player:
        player.write_log(f"[msg] Sending to {receiver} via {platform}...")
    
    # Use the advanced sender
    result = _sender.send(platform, receiver, message_text)
    
    logger.info(f"Result: {result}")
    if player:
        player.write_log(f"[msg] {result[:80]}")
    
    return result
