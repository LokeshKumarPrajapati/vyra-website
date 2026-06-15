"""
context_detector.py  - v2
Vyra Cursor Intelligence - Context Classification Engine
"""

import os
import re
from pathlib import Path
from typing import Optional

try:
    import win32gui
    import win32process
    _WIN32_OK = True
except ImportError:
    _WIN32_OK = False

try:
    import psutil
    _PSUTIL_OK = True
except ImportError:
    _PSUTIL_OK = False

EXT_TYPE_MAP = {
    '.png': 'image', '.jpg': 'image', '.jpeg': 'image', '.gif': 'image',
    '.svg': 'image', '.webp': 'image', '.bmp': 'image', '.ico': 'image',
    '.py': 'code', '.js': 'code', '.jsx': 'code', '.ts': 'code', '.tsx': 'code',
    '.cpp': 'code', '.c': 'code', '.h': 'code', '.go': 'code', '.rs': 'code',
    '.java': 'code', '.cs': 'code', '.rb': 'code', '.php': 'code',
    '.html': 'code', '.css': 'code', '.scss': 'code', '.json': 'code',
    '.yaml': 'code', '.yml': 'code', '.xml': 'code', '.sh': 'code',
    '.bat': 'code', '.ps1': 'code', '.toml': 'code', '.ini': 'code',
    '.pdf': 'pdf',
    '.doc': 'file', '.docx': 'file', '.odt': 'file',
    '.xls': 'file', '.xlsx': 'file', '.ods': 'file',
    '.ppt': 'file', '.pptx': 'file', '.odp': 'file',
    '.txt': 'text', '.md': 'text', '.rst': 'text', '.csv': 'text', '.log': 'text',
    '.mp4': 'video', '.mkv': 'video', '.avi': 'video', '.mov': 'video',
    '.wmv': 'video', '.flv': 'video', '.webm': 'video',
    '.mp3': 'audio', '.wav': 'audio', '.flac': 'audio', '.aac': 'audio',
}

DEFAULT_ACTIONS = {
    'file':     ['Summarize', 'Ask Questions', 'Extract Tasks', 'Convert to Notes'],
    'image':    ['Analyze Image', 'Extract Text', 'Improve Quality', 'Find Similar'],
    'code':     ['Explain Code', 'Review Code', 'Optimize', 'Generate Tests'],
    'folder':   ['Analyze Structure', 'Organize', 'Find Duplicates', 'Generate Report'],
    'text':     ['Explain', 'Summarize', 'Rewrite', 'Translate'],
    'url':      ['Summarize Page', 'Extract Data', 'Find Related', 'Save to Notes'],
    'form':     ['Auto Fill', 'Analyze Fields', 'Save as Template'],
    'pdf':      ['Summarize', 'Extract Tables', 'Ask Questions', 'Convert'],
    'video':    ['Summarize', 'Extract Audio', 'Generate Transcript'],
    'audio':    ['Transcribe', 'Summarize', 'Identify Song'],
    'browser':  ['Summarize Page', 'Extract Key Points', 'Translate', 'Save to Notes'],
    'terminal': ['Explain Command', 'Fix Error', 'Suggest Next Command', 'Document'],
    'editor':   ['Explain Code', 'Review Code', 'Find Bugs', 'Generate Tests'],
    'office':   ['Summarize', 'Extract Data', 'Improve Writing', 'Create Template'],
    'chat':     ['Summarize Conversation', 'Draft Reply', 'Extract Action Items'],
    'app':      ['Summarize Screen', 'Create Task', 'Ask Vyra', 'Take Notes'],
    'unknown':  ['Ask Vyra', 'Analyze Screen', 'Create Task'],
}

EXE_TYPE_MAP = {
    'chrome.exe': 'browser', 'msedge.exe': 'browser', 'firefox.exe': 'browser',
    'brave.exe': 'browser', 'opera.exe': 'browser', 'vivaldi.exe': 'browser',
    'arc.exe': 'browser',
    'code.exe': 'editor', 'cursor.exe': 'editor', 'devenv.exe': 'editor',
    'idea64.exe': 'editor', 'pycharm64.exe': 'editor', 'webstorm64.exe': 'editor',
    'clion64.exe': 'editor', 'notepad++.exe': 'editor', 'sublime_text.exe': 'editor',
    'atom.exe': 'editor', 'notepad.exe': 'editor', 'wordpad.exe': 'text',
    'windowsterminal.exe': 'terminal', 'wt.exe': 'terminal', 'powershell.exe': 'terminal',
    'cmd.exe': 'terminal', 'pwsh.exe': 'terminal', 'bash.exe': 'terminal',
    'ubuntu.exe': 'terminal', 'hyper.exe': 'terminal', 'alacritty.exe': 'terminal',
    'wezterm.exe': 'terminal',
    'winword.exe': 'office', 'excel.exe': 'office', 'powerpnt.exe': 'office',
    'outlook.exe': 'office', 'onenote.exe': 'office',
    'acrobat.exe': 'pdf', 'acrord32.exe': 'pdf', 'foxitpdfeditor.exe': 'pdf',
    'slack.exe': 'chat', 'teams.exe': 'chat', 'discord.exe': 'chat',
    'zoom.exe': 'chat', 'whatsapp.exe': 'chat', 'telegram.exe': 'chat',
    'vlc.exe': 'video', 'mpv.exe': 'video', 'mpc-hc64.exe': 'video',
    'spotify.exe': 'audio',
    'figma.exe': 'image', 'photoshop.exe': 'image', 'illustrator.exe': 'image',
    'xd.exe': 'image',
    'explorer.exe': 'folder',
}

EXE_LABELS = {
    'chrome.exe': 'Chrome', 'msedge.exe': 'Edge', 'firefox.exe': 'Firefox',
    'brave.exe': 'Brave', 'code.exe': 'VS Code', 'cursor.exe': 'Cursor IDE',
    'devenv.exe': 'Visual Studio', 'notepad++.exe': 'Notepad++',
    'windowsterminal.exe': 'Terminal', 'powershell.exe': 'PowerShell',
    'cmd.exe': 'Command Prompt', 'winword.exe': 'Word', 'excel.exe': 'Excel',
    'powerpnt.exe': 'PowerPoint', 'outlook.exe': 'Outlook',
    'slack.exe': 'Slack', 'teams.exe': 'Teams', 'discord.exe': 'Discord',
    'spotify.exe': 'Spotify', 'vlc.exe': 'VLC', 'figma.exe': 'Figma',
    'explorer.exe': 'File Explorer', 'acrobat.exe': 'Acrobat',
}

CLASS_TYPE_MAP = {
    'chrome_widgetwin': 'browser', 'mozillauiwindowclass': 'browser',
    'iexplore': 'browser', 'cabinetwclass': 'folder', 'explorerframe': 'folder',
    'syslistview32': 'folder', 'directuihlwnd': 'folder',
    'consolewindowclass': 'terminal', 'pseudoconsolewindow': 'terminal',
    'windowsterminalclass': 'terminal', 'wintextclass': 'text',
    'edit': 'text', 'richedit': 'text', 'scintilla': 'editor',
}


def get_exe_from_hwnd(hwnd: int) -> str:
    if not _WIN32_OK or not _PSUTIL_OK:
        return ''
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return psutil.Process(pid).name().lower()
    except Exception:
        return ''


def get_element_at(x: int, y: int) -> dict:
    info = {'hwnd': None, 'class': '', 'title': '', 'exe': '', 'root_title': ''}
    if not _WIN32_OK:
        return info
    try:
        hwnd = win32gui.WindowFromPoint((x, y))
        if not hwnd:
            return info
        root = win32gui.GetAncestor(hwnd, 2)
        info['hwnd']       = hwnd
        info['class']      = win32gui.GetClassName(hwnd).lower()
        info['title']      = win32gui.GetWindowText(hwnd)
        info['root_title'] = win32gui.GetWindowText(root) if root else info['title']
        info['exe']        = get_exe_from_hwnd(root or hwnd)
    except Exception:
        pass
    return info


def detect_from_element_info(element: dict) -> Optional[dict]:
    """
    Classify context. Priority: exe > window class > title extension > generic fallback.
    Returns a result for virtually every window that has a title.
    """
    cls        = element.get('class', '').lower()
    title      = element.get('title', '') or element.get('root_title', '')
    root_title = element.get('root_title', '') or title
    exe        = element.get('exe', '').lower()

    # 1. Executable name - most reliable
    if exe and exe in EXE_TYPE_MAP:
        ctx_type = EXE_TYPE_MAP[exe]
        label    = EXE_LABELS.get(exe, '')

        # File Explorer: use folder name from title, not generic label
        if ctx_type == 'folder' and root_title:
            folder = root_title.split('\\')[-1] if '\\' in root_title else root_title
            label  = folder[:50] or label

        # Browsers: strip " - Google Chrome" suffix
        elif ctx_type == 'browser' and root_title:
            page  = re.sub(
                r'\s[-|]\s*(Google Chrome|Microsoft Edge|Firefox|Brave|Opera|Vivaldi).*$',
                '', root_title
            ).strip()
            label = page[:50] if page else label

        # Editors: detect file type from open file name
        elif ctx_type == 'editor' and root_title:
            m = re.match(r'^(\S[^\-]*?)(?:\s[-]|$)', root_title)
            if m:
                fname = m.group(1).strip()
                ext   = Path(fname).suffix.lower()
                if ext in EXT_TYPE_MAP:
                    ctx_type = EXT_TYPE_MAP[ext]
                label = fname[:50]
            else:
                label = root_title[:50]

        # Terminals: title usually shows current directory or command
        elif ctx_type == 'terminal':
            label = root_title[:50] if root_title else 'Terminal'

        return {
            'type':    ctx_type,
            'label':   label,
            'actions': DEFAULT_ACTIONS.get(ctx_type, DEFAULT_ACTIONS['app']),
        }

    # 2. Window class heuristics
    for cls_key, ctx_type in CLASS_TYPE_MAP.items():
        if cls_key in cls:
            src   = root_title or title or ''
            if ctx_type == 'folder':
                label = src.split('\\')[-1][:50] if '\\' in src else src[:50]
            elif ctx_type in ('browser', 'editor'):
                clean = re.sub(r'\s[-|]\s*\w+.*$', '', src).strip()
                label = (clean or src)[:50]
            else:
                label = src[:50]
            return {
                'type':    ctx_type,
                'label':   label,
                'actions': DEFAULT_ACTIONS.get(ctx_type, DEFAULT_ACTIONS['app']),
            }

    # 3. File extension in title
    if title:
        ext = Path(title).suffix.lower()
        if ext in EXT_TYPE_MAP:
            return {
                'type':    EXT_TYPE_MAP[ext],
                'label':   title[:50],
                'actions': DEFAULT_ACTIONS[EXT_TYPE_MAP[ext]],
            }

    # 4. Generic fallback for any named window
    display = (root_title or title or '').strip()
    if display and len(display) > 2:
        clean = re.sub(r'\s[-|]\s*(Windows|Microsoft|Adobe|JetBrains).*$', '', display).strip()
        return {
            'type':    'app',
            'label':   clean[:50],
            'actions': DEFAULT_ACTIONS['app'],
        }

    return None


async def analyze_region(image_b64: str, x: int, y: int) -> dict:
    try:
        import base64
        from google import genai
        from google.genai import types as gt
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return {'analysis': 'GEMINI_API_KEY not set.'}
        client = genai.Client(http_options={"api_version": "v1beta"}, api_key=api_key)
        if ',' in image_b64:
            image_b64 = image_b64.split(',', 1)[1]
        image_bytes = base64.b64decode(image_b64)
        prompt = "Analyze this screen region in 2-3 sentences. Be specific. No markdown."
        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=[gt.Part.from_bytes(data=image_bytes, mime_type="image/png"), prompt],
        )
        return {'analysis': response.text.strip()}
    except Exception as e:
        return {'analysis': f'Analysis error: {e}'}


async def detect_context(x: int, y: int, image_b64=None) -> dict:
    element = get_element_at(x, y)
    result  = detect_from_element_info(element)
    if result and result.get('type') not in ('unknown', None):
        return {**result, 'x': x, 'y': y, 'confidence': 0.85, 'source': 'win32'}
    return {'type': 'unknown', 'x': x, 'y': y, 'confidence': 0.0, 'source': 'none'}
