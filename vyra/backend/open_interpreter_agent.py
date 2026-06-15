"""
Open Interpreter Agent for VYRA
================================
Wraps the `interpreter` library so VYRA can:
  - Run Python / JavaScript / shell code snippets
  - Execute single shell commands
  - Delegate complex natural-language tasks to Open Interpreter (multi-step autonomous execution)

All public methods are async-safe (blocking work is offloaded to a thread pool).
"""

import asyncio
import os
from dotenv import load_dotenv

load_dotenv()  # Ensure GEMINI_API_KEY is loaded from .env


# ---------------------------------------------------------------------------
# Bootstrap – configure interpreter BEFORE importing it so the settings land
# ---------------------------------------------------------------------------

def _build_interpreter():
    """Create and configure an Open Interpreter instance."""
    try:
        from interpreter import interpreter as oi

        # Use Gemini via LiteLLM so no extra API key is needed
        gemini_key = os.getenv("GEMINI_API_KEY", "")

        oi.llm.model = "gemini/gemini-2.0-flash"   # LiteLLM prefix for Gemini
        oi.llm.api_key = gemini_key

        # Never launch an interactive browser / GUI
        oi.auto_run = True       # Execute code without asking the user each time
        oi.require_confirmation = False  # Disable secondary confirmation prompts
        oi.llm.max_budget = 0.0  # Bypass budget warnings/prompts entirely
        oi.verbose = False
        oi.safe_mode = "off"     # VYRA already has its own confirmation layer

        # Keep responses coming (don't block for display)
        oi.computer.emit_images = False

        # Patch internal bug in OI 0.2.x where a 429 error causes a NameError or is swallowed
        def _patched_display_message(markdown_text, *args, **kwargs):
            text_str = str(markdown_text).lower()
            if "429" in text_str or "rate limit" in text_str or "quota" in text_str:
                raise Exception("API_RATE_LIMIT")
            raise Exception(f"API_ERROR: {markdown_text}")

        try:
            import interpreter.core.respond
            if not hasattr(interpreter.core.respond, "display_markdown_message"):
                interpreter.core.respond.display_markdown_message = _patched_display_message
        except Exception:
            pass

        print("[OpenInterpreter] Initialized with Gemini backend.")
        return oi

    except ImportError:
        print("[OpenInterpreter] WARNING: 'open-interpreter' is not installed. "
              "Run: pip install open-interpreter")
        return None


class OpenInterpreterAgent:
    """Async wrapper around Open Interpreter for use inside VYRA's AudioLoop."""

    def __init__(self):
        self._oi = None  # Lazy-init to avoid blocking server startup

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def oi(self):
        """Lazily initialise the interpreter on first use."""
        if self._oi is None:
            self._oi = _build_interpreter()
        return self._oi

    def _is_available(self) -> bool:
        return self.oi is not None

    def _capture_stream(self, messages) -> str:
        """
        Consume a streaming response from Open Interpreter and return
        the full text output as a single string.
        """
        output_parts = []
        for chunk in messages:
            # Each chunk is a dict like {'type': 'message', 'content': '...'}
            # or {'type': 'code', 'format': 'python', 'content': '...'}
            # or {'type': 'output', 'content': '...'}
            if isinstance(chunk, dict):
                chunk_type = chunk.get("type", "")
                content = chunk.get("content", "")
                if chunk_type == "message" and content:
                    output_parts.append(content)
                elif chunk_type == "output" and content:
                    output_parts.append(f"[Output]\n{content}")
                elif chunk_type == "code" and content:
                    fmt = chunk.get("format", "")
                    output_parts.append(f"[Code ({fmt})]\n{content}")
        return "\n".join(output_parts).strip()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_code(self, code: str, language: str = "python") -> str:
        """
        Execute a code block and return its output.

        Args:
            code:     Source code to execute.
            language: 'python', 'javascript', 'shell', 'bash', etc.

        Returns:
            A string containing stdout / stderr / return values.
        """
        if not self._is_available():
            return "Open Interpreter is not installed. Run: pip install open-interpreter"

        def _run():
            try:
                # Wrap the code in a message so OI executes it directly
                prompt = f"Please run this {language} code and return the output:\n\n```{language}\n{code}\n```"
                messages = self.oi.chat(prompt, display=False, stream=True)
                result = self._capture_stream(messages)
                return result or "Code executed successfully (no output)."
            except Exception as e:
                err_str = str(e).lower()
                if "api_rate_limit" in err_str or "rate limit" in err_str or "429" in err_str:
                    return "Error: Gemini API Rate Limit Exceeded (15 requests/min). Please wait 1 minute before trying again."
                if "openrouter" in err_str and ("402" in err_str or "paid account" in err_str):
                    return "Error: OpenRouter Payment Required. Your OpenRouter API key has $0 balance. Please add credits to your OpenRouter account to use Claude 3.5 Sonnet."
                # Don't return massive JSON tracebacks that crash the VYRA TTS engine
                return f"Error: Open Interpreter encountered an API issue. Check the backend logs for details."

        return await asyncio.to_thread(_run)

    async def run_shell_command(self, command: str) -> str:
        """
        Execute a single shell command and return the output.

        Args:
            command: The shell command to run (e.g. 'dir', 'ls -la', 'echo hello').

        Returns:
            Command output as a string.
        """
        if not self._is_available():
            return "Open Interpreter is not installed. Run: pip install open-interpreter"

        def _run():
            try:
                prompt = f"Run this shell command and return its output: `{command}`"
                messages = self.oi.chat(prompt, display=False, stream=True)
                result = self._capture_stream(messages)
                return result or f"Command `{command}` executed (no output)."
            except Exception as e:
                err_str = str(e).lower()
                if "api_rate_limit" in err_str or "rate limit" in err_str or "429" in err_str:
                    return "Error: Gemini API Rate Limit Exceeded (15 requests/min). Please wait 1 minute before trying again."
                if "openrouter" in err_str and ("402" in err_str or "paid account" in err_str):
                    return "Error: OpenRouter Payment Required. Your OpenRouter API key has $0 balance. Please add credits to your OpenRouter account to use Claude 3.5 Sonnet."
                # Don't return massive JSON tracebacks that crash the VYRA TTS engine
                return f"Error: Open Interpreter encountered an API issue. Check the backend logs for details."

        return await asyncio.to_thread(_run)

    async def chat(self, message: str, reset_context: bool = False) -> str:
        """
        Send a natural-language task to Open Interpreter.
        OI will plan, write, and execute multi-step code autonomously.

        Args:
            message:       The task description in natural language.
            reset_context: If True, clears OI's conversation history first.

        Returns:
            OI's final response / summary string.
        """
        if not self._is_available():
            return "Open Interpreter is not installed. Run: pip install open-interpreter"

        def _run():
            try:
                if reset_context:
                    self.oi.messages = []
                messages = self.oi.chat(message, display=False, stream=True)
                result = self._capture_stream(messages)
                return result or "Task completed by Open Interpreter."
            except Exception as e:
                err_str = str(e).lower()
                if "api_rate_limit" in err_str or "rate limit" in err_str or "429" in err_str:
                    return "Error: Gemini API Rate Limit Exceeded (15 requests/min). Please wait 1 minute before trying again."
                if "openrouter" in err_str and ("402" in err_str or "paid account" in err_str):
                    return "Error: OpenRouter Payment Required. Your OpenRouter API key has $0 balance. Please add credits to your OpenRouter account to use Claude 3.5 Sonnet."
                # Don't return massive JSON tracebacks that crash the VYRA TTS engine
                return f"Error: Open Interpreter encountered an API issue. Check the backend logs for details."

        return await asyncio.to_thread(_run)

    def reset(self):
        """Clear conversation history (start fresh context)."""
        if self._is_available():
            self.oi.messages = []
            print("[OpenInterpreter] Context reset.")
