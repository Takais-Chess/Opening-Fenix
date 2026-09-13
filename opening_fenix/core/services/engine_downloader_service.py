import os
import sys
import json
import shutil
import zipfile
import tempfile
import urllib.request
import urllib.error
from typing import Optional, Tuple
from PyQt6.QtCore import QThread, pyqtSignal, QObject

from opening_fenix.core.utils import get_default_user_dir
from opening_fenix.core.services.update_service import get_config_dict, save_config_dict
from opening_fenix.core.logger import logger


STOCKFISH_API_LATEST = "https://api.github.com/repos/official-stockfish/Stockfish/releases/latest"
STOCKFISH_FALLBACK_URL = "https://github.com/official-stockfish/Stockfish/releases/latest/download/stockfish-windows-x86-64-universal.zip"
STOCKFISH_FALLBACK_NAME = "stockfish-windows-x86-64-universal.zip"


def get_engines_dir() -> str:
    """Returns the dedicated directory where chess engine executables are stored."""
    user_dir = get_default_user_dir()
    engines_dir = os.path.join(user_dir, "engines")
    os.makedirs(engines_dir, exist_ok=True)
    return engines_dir


def is_engine_valid(engine_path: Optional[str]) -> bool:
    """
    Checks if the provided path points to a valid, existing executable file.
    """
    if not engine_path or not isinstance(engine_path, str):
        return False
    clean_path = engine_path.strip().strip('"\'')
    if not clean_path or not os.path.isfile(clean_path):
        return False
    
    # On Windows, check for executable extension
    if sys.platform == "win32":
        ext = os.path.splitext(clean_path)[1].lower()
        if ext not in (".exe", ".bat", ".cmd"):
            return False
    else:
        if not os.access(clean_path, os.X_OK):
            return False
            
    return True


def get_latest_stockfish_asset_url(timeout: int = 6) -> Tuple[str, str]:
    """
    Queries GitHub Releases API for the latest Stockfish Windows x86-64 binary asset.
    Returns (download_url, asset_name).
    Falls back to a verified direct download URL if the API is unavailable or rate-limited.
    """
    try:
        req = urllib.request.Request(
            STOCKFISH_API_LATEST,
            headers={"User-Agent": "OpeningFenix-App"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                assets = data.get("assets", [])
                
                # Preferred order: universal -> avx2 -> modern -> any windows x86_64 zip
                candidates = []
                for asset in assets:
                    name = asset.get("name", "").lower()
                    if name.endswith(".zip") and "windows" in name and "x86-64" in name:
                        url = asset.get("browser_download_url")
                        if url:
                            candidates.append((asset.get("name"), url))
                
                if candidates:
                    for pref in ("universal", "avx2", "modern"):
                        for name, url in candidates:
                            if pref in name.lower():
                                logger.info(f"Resolved Stockfish release asset: {name}")
                                return url, name
                    # Fall back to first matching candidate
                    return candidates[0][1], candidates[0][0]
    except Exception as e:
        logger.warning(f"Could not fetch latest Stockfish release via GitHub API ({e}), using fallback URL.")

    return STOCKFISH_FALLBACK_URL, STOCKFISH_FALLBACK_NAME


class StockfishDownloaderWorker(QThread):
    """
    Background worker thread that streams official Stockfish release zip from GitHub,
    extracts the executable into the app's engines directory, and saves it to config.json.
    """
    progress = pyqtSignal(int, int)  # (downloaded_bytes, total_bytes)
    status = pyqtSignal(str)         # Status text
    finished = pyqtSignal(str)       # Extracted executable path
    error = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None, target_dir: Optional[str] = None):
        super().__init__(parent)
        self.target_dir = target_dir or get_engines_dir()
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        temp_zip_path = None
        try:
            self.status.emit("Resolving latest official Stockfish release...")
            download_url, asset_name = get_latest_stockfish_asset_url()

            if self._is_cancelled:
                return

            self.status.emit("Connecting to official download server...")
            req = urllib.request.Request(
                download_url,
                headers={"User-Agent": "OpeningFenix-App"}
            )

            temp_dir = tempfile.gettempdir()
            temp_zip_path = os.path.join(temp_dir, f"sf_download_{os.getpid()}.zip")

            with urllib.request.urlopen(req, timeout=30) as resp:
                total_size = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                chunk_size = 1024 * 64

                self.status.emit("Downloading Stockfish...")
                with open(temp_zip_path, "wb") as f_out:
                    while True:
                        if self._is_cancelled:
                            f_out.close()
                            if os.path.exists(temp_zip_path):
                                os.remove(temp_zip_path)
                            return
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f_out.write(chunk)
                        downloaded += len(chunk)
                        self.progress.emit(downloaded, total_size)

            if self._is_cancelled:
                if os.path.exists(temp_zip_path):
                    os.remove(temp_zip_path)
                return

            # Extract executable from zip
            self.status.emit("Extracting chess engine...")
            os.makedirs(self.target_dir, exist_ok=True)
            extracted_exe_path = None

            with zipfile.ZipFile(temp_zip_path, "r") as zf:
                # Find the main executable inside archive
                exe_members = [
                    m for m in zf.namelist() 
                    if m.lower().endswith(".exe") and not m.startswith("__MACOSX")
                ]

                if not exe_members:
                    raise RuntimeError("No executable (.exe) found inside Stockfish archive.")

                # Choose best member (prefer universal or avx2 if multiple)
                chosen_member = exe_members[0]
                for m in exe_members:
                    if "universal" in m.lower() or "avx2" in m.lower():
                        chosen_member = m
                        break

                exe_filename = os.path.basename(chosen_member)
                if not exe_filename:
                    exe_filename = "stockfish.exe"

                extracted_exe_path = os.path.join(self.target_dir, exe_filename)

                # Extract and flatten into engines directory
                with zf.open(chosen_member) as src_file, open(extracted_exe_path, "wb") as dst_file:
                    shutil.copyfileobj(src_file, dst_file)

                # Also extract any accompanying license/copying file if present
                for m in zf.namelist():
                    base_low = os.path.basename(m).lower()
                    if base_low in ("copying.txt", "copying", "license.txt", "license"):
                        lic_path = os.path.join(self.target_dir, "STOCKFISH_LICENSE.txt")
                        try:
                            with zf.open(m) as src_lic, open(lic_path, "wb") as dst_lic:
                                shutil.copyfileobj(src_lic, dst_lic)
                        except Exception:
                            pass

            # Clean up temp file
            if temp_zip_path and os.path.exists(temp_zip_path):
                try:
                    os.remove(temp_zip_path)
                except Exception:
                    pass

            # Verify executable was created
            if not is_engine_valid(extracted_exe_path):
                raise RuntimeError(f"Extracted engine file is invalid or unreadable: {extracted_exe_path}")

            # Save to config.json
            cfg = get_config_dict()
            cfg["engine_path"] = extracted_exe_path
            save_config_dict(cfg)
            logger.info(f"Stockfish successfully installed to {extracted_exe_path} and saved to config.json")

            self.status.emit("Stockfish successfully installed!")
            self.finished.emit(extracted_exe_path)

        except Exception as e:
            logger.error(f"Failed to download or extract Stockfish: {e}", exc_info=True)
            if temp_zip_path and os.path.exists(temp_zip_path):
                try:
                    os.remove(temp_zip_path)
                except Exception:
                    pass
            self.error.emit(str(e))
