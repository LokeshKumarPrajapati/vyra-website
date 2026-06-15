"""
win_archives.py — ZIP and 7Z archive operations for VYRA Windows control.
Uses stdlib zipfile/shutil for ZIP, py7zr for 7Z (optional).
"""
import zipfile
import shutil
import json
import os


def _ok(output: str, action: str = "") -> str:
    return json.dumps({"status": "ok", "action": action, "output": output})


def _err(msg: str, action: str = "") -> str:
    return json.dumps({"status": "error", "action": action, "error": msg})


def _resolve(path: str) -> str:
    shortcuts = {
        "desktop": os.path.join(os.path.expanduser("~"), "Desktop"),
        "downloads": os.path.join(os.path.expanduser("~"), "Downloads"),
        "documents": os.path.join(os.path.expanduser("~"), "Documents"),
        "home": os.path.expanduser("~"),
    }
    lower = path.lower().strip()
    for key, val in shortcuts.items():
        if lower == key or lower.startswith(key + "/") or lower.startswith(key + "\\"):
            return val + path[len(key):]
    return path


def win_archives(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action = parameters.get("action", "").lower().strip()
    source = _resolve(parameters.get("source_path", ""))
    archive = _resolve(parameters.get("archive_path", ""))
    extract_to = _resolve(parameters.get("extract_to", ""))
    password = parameters.get("password", None)
    level = int(parameters.get("compression_level", 6))

    try:
        if action == "create_zip":
            if not source:
                return _err("source_path is required.", action)
            if not archive:
                archive = source.rstrip("/\\") + ".zip"
            _compress_to_zip(source, archive, level)
            return _ok(f"Created ZIP: {archive}", action)

        elif action == "extract_zip":
            if not archive:
                return _err("archive_path is required.", action)
            dest = extract_to or os.path.dirname(archive)
            os.makedirs(dest, exist_ok=True)
            pwd = password.encode() if password else None
            with zipfile.ZipFile(archive, "r") as zf:
                zf.extractall(dest, pwd=pwd)
            return _ok(f"Extracted to: {dest}", action)

        elif action == "list_zip":
            if not archive:
                return _err("archive_path is required.", action)
            with zipfile.ZipFile(archive, "r") as zf:
                names = zf.namelist()
            return _ok("\n".join(names[:200]) + (f"\n... and {len(names)-200} more" if len(names) > 200 else ""), action)

        elif action == "add_to_zip":
            if not source or not archive:
                return _err("source_path and archive_path are required.", action)
            mode = "a" if os.path.exists(archive) else "w"
            with zipfile.ZipFile(archive, mode, compression=zipfile.ZIP_DEFLATED, compresslevel=level) as zf:
                if os.path.isfile(source):
                    zf.write(source, os.path.basename(source))
                else:
                    for root, _, files in os.walk(source):
                        for f in files:
                            fp = os.path.join(root, f)
                            zf.write(fp, os.path.relpath(fp, os.path.dirname(source)))
            return _ok(f"Added to ZIP: {archive}", action)

        elif action == "compress_folder":
            if not source:
                return _err("source_path is required.", action)
            out = archive or source.rstrip("/\\") + ".zip"
            _compress_to_zip(source, out, level)
            return _ok(f"Folder compressed to: {out}", action)

        elif action in ("create_7z", "extract_7z"):
            try:
                import py7zr
            except ImportError:
                return _err("py7zr not installed. Run: pip install py7zr", action)

            if action == "create_7z":
                if not source:
                    return _err("source_path is required.", action)
                out = archive or source.rstrip("/\\") + ".7z"
                pwd = password if password else None
                with py7zr.SevenZipFile(out, "w", password=pwd) as sz:
                    if os.path.isfile(source):
                        sz.write(source, os.path.basename(source))
                    else:
                        sz.writeall(source, os.path.basename(source))
                return _ok(f"Created 7Z: {out}", action)

            else:  # extract_7z
                if not archive:
                    return _err("archive_path is required.", action)
                dest = extract_to or os.path.dirname(archive)
                os.makedirs(dest, exist_ok=True)
                pwd = password if password else None
                with py7zr.SevenZipFile(archive, "r", password=pwd) as sz:
                    sz.extractall(dest)
                return _ok(f"Extracted 7Z to: {dest}", action)

        else:
            return _err(f"Unknown action: '{action}'. Use: create_zip, extract_zip, list_zip, add_to_zip, compress_folder, create_7z, extract_7z", action)

    except FileNotFoundError as e:
        return _err(f"File not found: {e}", action)
    except zipfile.BadZipFile:
        return _err("Invalid or corrupt ZIP file.", action)
    except Exception as e:
        return _err(str(e), action)


def _compress_to_zip(source: str, dest: str, level: int):
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=level) as zf:
        if os.path.isfile(source):
            zf.write(source, os.path.basename(source))
        else:
            base = os.path.dirname(source)
            for root, _, files in os.walk(source):
                for f in files:
                    fp = os.path.join(root, f)
                    zf.write(fp, os.path.relpath(fp, base))
