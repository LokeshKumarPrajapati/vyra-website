# actions/dev_agent.py
# AI-powered development agent — plans, builds, and debugs full projects.
#
# Flow:
#   Describe project → Gemini plans file structure → Files written one by one
#   → VSCode opened → Entry point executed → Error? → Identify file → Fix → Retry
#   → Speaks only when done (success or failure)
#
# Models:
#   Planning : gemini-2.5-flash       (architecture, structure, debugging)
#   Writing  : gemini-2.5-flash-lite  (fast file generation)

import subprocess
import sys
import json
import re
import time
from pathlib import Path

def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR           = get_base_dir()
API_CONFIG_PATH    = BASE_DIR / "config" / "api_keys.json"
PROJECTS_DIR       = Path.home() / "Desktop" / "JarvisProjects"
MAX_FIX_ATTEMPTS   = 4
MODEL_PLANNER      = "gemini-2.5-flash"
MODEL_WRITER       = "gemini-2.5-flash"  # upgraded from lite — better design output

# ── Web design system injected into every HTML/CSS/JS file prompt ────────────
_WEB_DESIGN_SYSTEM = """
DESIGN SYSTEM (MANDATORY — apply to every HTML/CSS/JS file):

AESTHETIC:
- Style: Ultra-modern, minimalist, brutalist-clean, premium dark-first
- Color palette: Deep dark backgrounds (#0a0a0f, #0d0d1a, #111827) + electric accent (neon cyan #00d4ff, violet #7c3aed, or gold #f59e0b) — pick ONE accent and stick to it
- Typography: Google Fonts — "Inter" for UI text, "Space Grotesk" or "Outfit" for headings; always import in <head>
- Layout: Full-viewport hero sections, asymmetric grids, generous whitespace

3D & DEPTH:
- CSS 3D transforms: use `transform-style: preserve-3d`, `perspective: 1000px` on cards and hero sections
- Floating card effect: `transform: translateZ(20px) rotateX(5deg)` on hover
- Parallax layers: multiple divs with different `transform: translateZ()` depths inside a perspective container
- Glassmorphism panels: `background: rgba(255,255,255,0.05); backdrop-filter: blur(20px); border: 1px solid rgba(255,255,255,0.1); border-radius: 16px;`
- Subtle depth shadows: `box-shadow: 0 25px 50px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.05);`

ANIMATIONS:
- CSS custom properties for animation control
- Smooth entrance animations: `@keyframes fadeInUp { from { opacity:0; transform:translateY(30px); } to { opacity:1; transform:translateY(0); } }`
- Staggered children: use `animation-delay: calc(var(--i) * 0.1s)` pattern
- Hover microinteractions: scale, glow, lift (use `transition: all 0.3s cubic-bezier(0.4,0,0.2,1)`)
- Gradient shimmer on accent elements: animated `background-position`
- Cursor glow effect: JS mousemove listener that moves a radial-gradient overlay

LAYOUT RULES:
- Hero: 100vh, centered or left-aligned with massive heading (clamp(3rem,8vw,7rem)), sub-heading, CTA button
- Grid: CSS Grid with `grid-template-columns: repeat(auto-fit, minmax(320px, 1fr))` for cards
- No Bootstrap/Tailwind CDN — write pure CSS in <style> tags
- Every section has a visible, intentional divider or spacing rhythm

INTERACTIVE ELEMENTS:
- Buttons: gradient background, `border-radius: 8px`, glow box-shadow on hover, scale(1.02) transform
- Cards: 3D tilt on mousemove (JS — max ±10deg), glassmorphism, inner glow border on hover
- Navigation: sticky, frosted glass (`backdrop-filter: blur(16px)`), smooth scroll
- Scroll-triggered reveals: use Intersection Observer API, class-toggle animations

CODE RULES:
- Single self-contained HTML file unless JS/CSS are explicitly separate files in the plan
- All CSS inline in <style> tag, all JS inline in <script> tag (or separate .css/.js if multi-file project)
- Mobile-responsive: all font-sizes use clamp(), layout switches at 768px breakpoint
- NO placeholder images — use CSS gradient shapes, SVG inline icons, or emoji as decorative elements
- Add <meta> viewport, charset, description tags
- Make it look like a $10,000 Awwwards-winning site, not a tutorial project
"""


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _get_model(model_name: str):
    import google.generativeai as genai
    genai.configure(api_key=_get_api_key())
    return genai.GenerativeModel(model_name)


def _clean_code(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _clean_json(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    return text.strip()


def _is_rate_limit(error: Exception) -> bool:
    return "429" in str(error) or "quota" in str(error).lower()


def _get_interpreter(path: Path) -> list[str] | None:
    return {
        ".py":  [sys.executable],
        ".js":  ["node"],
        ".ts":  ["ts-node"],
        ".sh":  ["bash"],
        ".ps1": ["powershell", "-File"],
        ".rb":  ["ruby"],
        ".php": ["php"],
    }.get(path.suffix.lower())


def _has_error(output: str) -> bool:
    if "timed out" in output.lower():
        return False
    signals = ["error", "exception", "traceback", "syntaxerror",
               "nameerror", "typeerror", "importerror", "stderr", "failed"]
    return any(s in output.lower() for s in signals)

def _identify_error_file(error_output: str, project_files: list[str]) -> str | None:
    """
    Try to find which file caused the error from traceback.
    Returns filename or None.
    """
    for line in error_output.splitlines():
        for f in project_files:
            if Path(f).name in line or f in line:
                return f
    return None

def _is_web_project(language: str, description: str) -> bool:
    """Returns True if this is an HTML/CSS/JS website project."""
    lang = language.lower()
    desc = description.lower()
    web_langs = ("html", "css", "javascript", "js", "web", "website", "frontend", "landing")
    return any(w in lang for w in web_langs) or any(w in desc for w in ("website", "landing page", "portfolio", "webpage", "html", "frontend"))


def _plan_project(description: str, language: str) -> dict:
    """
    Ask Gemini to plan the full project structure.
    """
    model = _get_model(MODEL_PLANNER)

    is_web = _is_web_project(language, description)
    web_note = ""
    if is_web:
        web_note = """
FOR WEB PROJECTS:
- Prefer a single index.html if the site is a landing/portfolio/promo page
- Use index.html + style.css + script.js if the project benefits from separation
- entry_point must be "index.html"
- run_command must be "start index.html"
- dependencies array must be empty (no npm packages — pure HTML/CSS/JS)
"""

    prompt = f"""You are a senior software architect.
Plan the complete file structure for the following project.

Language: {language}
Description: {description}
{web_note}
Return ONLY a valid JSON object with this exact structure:
{{
  "project_name": "short_snake_case_name",
  "entry_point": "main.py",
  "files": [
    {{"path": "main.py", "description": "what this file does"}},
    {{"path": "utils/helpers.py", "description": "what this file does"}}
  ],
  "run_command": "python main.py",
  "dependencies": ["package1", "package2"]
}}

Rules:
- Keep it simple. Only include files that are truly necessary.
- No explanation, no markdown, no backticks. Pure JSON only.
- Entry point must be one of the files listed.
- Use relative paths only.

JSON:"""

    try:
        response = model.generate_content(prompt)
        raw = _clean_json(response.text)
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Planner returned invalid JSON: {e}\nRaw: {response.text[:300]}")


def _write_file(
    file_path: str,
    file_description: str,
    project_description: str,
    all_files: list[dict],
    language: str,
    project_dir: Path
) -> str:
    """Write one file. Returns the generated code."""
    model = _get_model(MODEL_WRITER)

    file_list = "\n".join(
        f"  - {f['path']}: {f['description']}" for f in all_files
    )

    # Inject web design system for HTML/CSS/JS files
    is_web_file = Path(file_path).suffix.lower() in (".html", ".css", ".js")
    design_block = _WEB_DESIGN_SYSTEM if is_web_file else ""

    prompt = f"""You are an expert {language} developer and UI/UX designer.
Write the code for ONE specific file in a larger project.
{design_block}
Project goal: {project_description}

All files in this project:
{file_list}

Now write ONLY the file: {file_path}
Purpose of this file: {file_description}

Rules:
- Output ONLY the code for this file. No explanation, no markdown, no backticks.
- Import from other project files using relative imports where needed.
- Handle errors properly.
- Use modern best practices.
{"- MANDATORY: Apply the full DESIGN SYSTEM above. Make it look stunning — 3D, professional, minimalist. DO NOT produce a basic tutorial-style page." if is_web_file else ""}

Code for {file_path}:"""

    try:
        response = model.generate_content(prompt)
        code = _clean_code(response.text)

        # Save file
        full_path = project_dir / file_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(code, encoding="utf-8")

        print(f"[DevAgent] ✅ Written: {file_path}")
        return code

    except Exception as e:
        if _is_rate_limit(e):
            raise RateLimitError(str(e))
        raise


def _install_dependencies(dependencies: list[str], project_dir: Path) -> str:
    if not dependencies:
        return "No dependencies to install."

    print(f"[DevAgent] 📦 Installing: {dependencies}")

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install"] + dependencies,
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=120, cwd=str(project_dir)
        )
        if result.returncode == 0:
            return f"Installed: {', '.join(dependencies)}"
        return f"Install warning: {result.stderr[:200]}"
    except subprocess.TimeoutExpired:
        return "Dependency install timed out."
    except Exception as e:
        return f"Install error: {e}"


def _open_vscode(project_dir: Path) -> bool:
    vscode_paths = [
        "code",
        r"C:\Users\{}\AppData\Local\Programs\Microsoft VS Code\bin\code.cmd".format(
            Path.home().name
        ),
    ]
    for cmd in vscode_paths:
        try:
            subprocess.Popen(
                [cmd, str(project_dir)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=True  
            )
            time.sleep(2)
            print(f"[DevAgent] 💻 VSCode opened: {project_dir}")
            return True
        except Exception:
            continue
    print("[DevAgent] ⚠️ VSCode not found.")
    return False


def _run_project(run_command: str, project_dir: Path, timeout: int = 30) -> str:
    """Run the project entry point, return output."""
    print(f"[DevAgent] 🚀 Running: {run_command}")

    # Web project: open HTML in browser, no error checking needed
    cmd_lower = run_command.strip().lower()
    if cmd_lower.startswith("start ") and cmd_lower.endswith(".html"):
        html_file = run_command.strip().split(None, 1)[1]
        full_html = project_dir / html_file
        try:
            import os as _os
            _os.startfile(str(full_html))
            return "Opened in browser."
        except Exception as e:
            return f"Could not open browser: {e}"

    try:
        parts = run_command.split()
        if parts[0] == "python":
            parts[0] = sys.executable

        result = subprocess.run(
            parts,
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=timeout, cwd=str(project_dir)
        )

        output = result.stdout.strip()
        error  = result.stderr.strip()

        parts_out = []
        if output: parts_out.append(f"Output:\n{output}")
        if error:  parts_out.append(f"Stderr:\n{error}")
        return "\n\n".join(parts_out) if parts_out else "Ran with no output."

    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s. (Long-running app may be working fine.)"
    except FileNotFoundError as e:
        return f"Command not found: {e}"
    except Exception as e:
        return f"Run error: {e}"

def _fix_file(
    file_path: str,
    current_code: str,
    error_output: str,
    project_description: str,
    all_files: list[dict],
    language: str,
    project_dir: Path
) -> str:
    """Ask Gemini to fix a specific file based on error output."""
    model = _get_model(MODEL_PLANNER)

    file_list = "\n".join(
        f"  - {f['path']}: {f['description']}" for f in all_files
    )

    prompt = f"""You are an expert {language} debugger.
Fix the file below. It caused an error when the project was run.

Project goal: {project_description}

All files in this project:
{file_list}

File to fix: {file_path}

Error output:
{error_output[:3000]}

Current code:
{current_code}

Return ONLY the fixed code — no explanation, no markdown, no backticks.

Fixed code:"""

    try:
        response = model.generate_content(prompt)
        fixed = _clean_code(response.text)

        full_path = project_dir / file_path
        full_path.write_text(fixed, encoding="utf-8")

        print(f"[DevAgent] 🔧 Fixed: {file_path}")
        return fixed

    except Exception as e:
        if _is_rate_limit(e):
            raise RateLimitError(str(e))
        raise

class RateLimitError(Exception):
    pass
def _build_project(
    description: str,
    language: str,
    project_name: str,
    timeout: int,
    speak=None,
    player=None
) -> str:
    """
    Full build loop:
    Plan → Write files → Install deps → Open VSCode → Run → Fix loop
    """

    def log(msg: str):
        print(f"[DevAgent] {msg}")
        if player:
            player.write_log(f"[DevAgent] {msg}")

    log("Planning project structure...")
    try:
        plan = _plan_project(description, language)
    except RateLimitError:
        msg = "You have reached the rate limit, sir. Please try again shortly."
        if speak: speak(msg)
        return msg
    except ValueError as e:
        msg = f"Planning failed: {e}"
        if speak: speak(msg)
        return msg

    proj_name = project_name or plan.get("project_name", "jarvis_project")
    proj_name = re.sub(r"[^\w\-]", "_", proj_name)
    project_dir = PROJECTS_DIR / proj_name
    project_dir.mkdir(parents=True, exist_ok=True)

    files       = plan.get("files", [])
    entry_point = plan.get("entry_point", "main.py")
    run_command = plan.get("run_command", f"python {entry_point}")
    dependencies = plan.get("dependencies", [])

    log(f"Project: {proj_name} | Files: {len(files)} | Entry: {entry_point}")

    file_codes: dict[str, str] = {}

    for file_info in files:
        file_path = file_info.get("path", "")
        file_desc = file_info.get("description", "")
        if not file_path:
            continue

        log(f"Writing {file_path}...")
        try:
            code = _write_file(
                file_path, file_desc, description,
                files, language, project_dir
            )
            file_codes[file_path] = code
        except RateLimitError:
            msg = "You have reached the rate limit, sir. Please try again shortly."
            if speak: speak(msg)
            return msg
        except Exception as e:
            log(f"Failed to write {file_path}: {e}")
            continue

    if not file_codes:
        msg = "I could not write any files for this project, sir."
        if speak: speak(msg)
        return msg

    if dependencies:
        log(f"Installing dependencies: {dependencies}")
        _install_dependencies(dependencies, project_dir)

    _open_vscode(project_dir)

    # Web projects: just open in browser — no error-fix loop needed
    if entry_point.endswith(".html"):
        last_output = _run_project(run_command, project_dir, timeout)
        msg = (
            f"Website '{proj_name}' is ready, sir. "
            f"Opened in your browser and in VSCode at {project_dir}."
        )
        if speak: speak(msg)
        return msg

    last_output = ""
    for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
        log(f"Running project (attempt {attempt}/{MAX_FIX_ATTEMPTS})...")

        last_output = _run_project(run_command, project_dir, timeout)
        log(f"Output: {last_output[:150]}")

        if not _has_error(last_output):
            msg = (
                f"Project '{proj_name}' is working, sir. "
                f"Built in {attempt} attempt{'s' if attempt > 1 else ''}. "
                f"Opened in VSCode at {project_dir}."
            )
            if speak: speak(msg)
            return f"{msg}\n\nOutput:\n{last_output}"

        if attempt == MAX_FIX_ATTEMPTS:
            break

        error_file = _identify_error_file(last_output, list(file_codes.keys()))
        if not error_file:
            error_file = entry_point

        log(f"Error in '{error_file}', fixing...")

        try:
            fixed = _fix_file(
                error_file,
                file_codes.get(error_file, ""),
                last_output,
                description,
                files,
                language,
                project_dir
            )
            file_codes[error_file] = fixed
        except RateLimitError:
            msg = "You have reached the rate limit, sir. Please try again shortly."
            if speak: speak(msg)
            return msg
        except Exception as e:
            log(f"Fix failed: {e}")

    msg = (
        f"I was unable to get '{proj_name}' working after {MAX_FIX_ATTEMPTS} attempts, sir. "
        f"The project is saved at {project_dir} — you can open it in VSCode and check manually."
    )
    if speak: speak(msg)
    return f"{msg}\n\nLast error:\n{last_output[:500]}"

def dev_agent(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None
) -> str:
    """
    Called from main.py.

    parameters:
        description  : What the project should do (required)
        language     : Programming language (default: python)
        project_name : Optional folder name (auto-generated if not given)
        timeout      : Run timeout in seconds (default: 30)
    """
    p            = parameters or {}
    description  = p.get("description", "").strip()
    language     = p.get("language", "python").strip()
    project_name = p.get("project_name", "").strip()
    timeout      = int(p.get("timeout", 30))

    if not description:
        return "Please describe the project you want me to build, sir."

    return _build_project(
        description  = description,
        language     = language,
        project_name = project_name,
        timeout      = timeout,
        speak        = speak,
        player       = player
    )