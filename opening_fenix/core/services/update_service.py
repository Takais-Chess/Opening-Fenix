import os
import sys
import json
import re
import urllib.request
import urllib.error
import datetime
from typing import Optional, Dict, Any, Tuple, List
from PyQt6.QtCore import QThread, pyqtSignal, QObject

from opening_fenix.core.version import APP_VERSION
from opening_fenix.core.utils import get_user_dir
from opening_fenix.core.logger import logger

GITHUB_REPO = "Takais-Chess/Opening-Fenix"
GITHUB_RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

def parse_version(v_str: str) -> Tuple[int, ...]:
    """
    Parses version strings like 'v1.0.0', '1.2.3', 'v2.2.0-beta' into numeric tuples like (1, 0, 0).
    """
    if not v_str:
        return (0, 0, 0)
    cleaned = re.sub(r'^[vV]', '', str(v_str).strip())
    # Extract numeric components
    match = re.match(r'^(\d+)(?:\.(\d+))?(?:\.(\d+))?', cleaned)
    if match:
        parts = match.groups()
        return tuple(int(p) if p is not None else 0 for p in parts)
    return (0, 0, 0)

def is_newer_version(remote_tag: str, current_version: str = APP_VERSION) -> bool:
    """Returns True if remote_tag is strictly newer than current_version."""
    remote_parsed = parse_version(remote_tag)
    current_parsed = parse_version(current_version)
    return remote_parsed > current_parsed

def get_config_dict() -> Dict[str, Any]:
    config_path = os.path.join(get_user_dir(), "config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load config.json: {e}")
    return {}

def save_config_dict(cfg: Dict[str, Any]) -> None:
    config_dir = get_user_dir()
    os.makedirs(config_dir, exist_ok=True)
    config_path = os.path.join(config_dir, "config.json")
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Could not write config.json: {e}")

class _UpdateSignals(QObject):
    check_completed = pyqtSignal(str)

class _UpdateSignalDispatcher:
    _instance = None

    def _get_obj(self):
        from PyQt6 import sip
        if self._instance is None or sip.isdeleted(self._instance):
            self._instance = _UpdateSignals()
        return self._instance

    @property
    def check_completed(self):
        return self._get_obj().check_completed

update_signals = _UpdateSignalDispatcher()

def record_update_check_time() -> str:
    """
    Saves the current timestamp into config.json as last_update_check, emits signal, and returns the formatted string.
    """
    cfg = get_config_dict()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cfg["last_update_check"] = now_str
    save_config_dict(cfg)
    try:
        update_signals.check_completed.emit(now_str)
    except Exception:
        pass
    return now_str

def get_last_update_check_time() -> Optional[str]:
    """
    Returns the last update check timestamp string from config.json, or None.
    """
    cfg = get_config_dict()
    return cfg.get("last_update_check")

def should_check_for_updates(manual: bool = False, current_version: str = APP_VERSION) -> bool:
    """
    Checks whether update checking should proceed based on user settings and snooze timers.
    """
    if manual:
        return True

    cfg = get_config_dict()
    if cfg.get("auto_check_updates") is False:
        return False

    snooze_until_str = cfg.get("update_snooze_until")
    if snooze_until_str:
        try:
            snooze_until = datetime.datetime.fromisoformat(snooze_until_str)
            if datetime.datetime.now() < snooze_until:
                return False
        except Exception:
            pass

    return True

def is_version_ignored(remote_tag: str) -> bool:
    cfg = get_config_dict()
    ignored = cfg.get("ignored_versions", [])
    if isinstance(ignored, list):
        tag_clean = str(remote_tag).strip().lstrip('vV')
        return any(str(ig).strip().lstrip('vV') == tag_clean for ig in ignored)
    return False

def set_snooze_period(snooze_type: str, tag_name: str) -> None:
    """
    Sets snooze timer or ignores a version.
    Options: 'next_start', '1_week', '1_month', '1_year', 'ignore'
    """
    cfg = get_config_dict()
    now = datetime.datetime.now()

    if snooze_type == "1_week":
        until = now + datetime.timedelta(days=7)
        cfg["update_snooze_until"] = until.isoformat()
    elif snooze_type == "1_month":
        until = now + datetime.timedelta(days=30)
        cfg["update_snooze_until"] = until.isoformat()
    elif snooze_type == "1_year":
        until = now + datetime.timedelta(days=365)
        cfg["update_snooze_until"] = until.isoformat()
    elif snooze_type == "next_start":
        cfg["update_snooze_until"] = None
    elif snooze_type == "ignore":
        cfg["update_snooze_until"] = None
        ignored = cfg.get("ignored_versions", [])
        if not isinstance(ignored, list):
            ignored = []
        if tag_name not in ignored:
            ignored.append(tag_name)
        cfg["ignored_versions"] = ignored

    save_config_dict(cfg)

class UpdateCheckWorker(QThread):
    """
    Worker thread that checks GitHub Releases API for the latest release.
    """
    update_found = pyqtSignal(dict)    # Emits release info dict
    no_update_found = pyqtSignal()
    check_error = pyqtSignal(str)

    def __init__(self, manual: bool = False, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.manual = manual

    def run(self):
        try:
            logger.info(f"UpdateCheckWorker: Checking GitHub releases for updates (manual={self.manual})...")
            req = urllib.request.Request(
                GITHUB_RELEASES_API,
                headers={"User-Agent": "OpeningFenix-App"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    self.check_error.emit(f"HTTP {resp.status}")
                    return
                data = json.loads(resp.read().decode('utf-8'))

            tag_name = data.get("tag_name", "")
            title = data.get("name", tag_name)
            body = data.get("body", "")
            html_url = data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases/latest")

            # Look for attached .exe installer asset
            download_url = None
            asset_name = None
            assets = data.get("assets", [])
            for asset in assets:
                name = asset.get("name", "")
                if name.lower().endswith(".exe"):
                    download_url = asset.get("browser_download_url")
                    asset_name = name
                    break

            check_time = record_update_check_time()
            logger.info(f"UpdateCheckWorker: Check completed at {check_time}. Remote tag: {tag_name}, Local version: {APP_VERSION}")

            if is_newer_version(tag_name, APP_VERSION):
                if not self.manual and is_version_ignored(tag_name):
                    logger.info(f"UpdateCheckWorker: Version {tag_name} is ignored by user.")
                    self.no_update_found.emit()
                    return

                release_info = {
                    "version": tag_name,
                    "title": title,
                    "body": body,
                    "html_url": html_url,
                    "download_url": download_url,
                    "asset_name": asset_name
                }
                self.update_found.emit(release_info)
            else:
                self.no_update_found.emit()

        except urllib.error.HTTPError as e:
            record_update_check_time()
            if e.code == 404:
                self.no_update_found.emit()
            else:
                self.check_error.emit(f"HTTP Fehler: {e.code}")
        except Exception as e:
            logger.warning(f"Update check error: {e}")
            self.check_error.emit(str(e))

class DownloaderWorker(QThread):
    """
    Worker thread that streams the installer executable to local temp directory.
    """
    progress = pyqtSignal(int, int)  # (downloaded_bytes, total_bytes)
    finished = pyqtSignal(str)       # local file path
    error = pyqtSignal(str)

    def __init__(self, download_url: str, file_name: str, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.download_url = download_url
        self.file_name = file_name
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        import tempfile
        try:
            temp_dir = tempfile.gettempdir()
            dest_path = os.path.join(temp_dir, self.file_name)

            req = urllib.request.Request(
                self.download_url,
                headers={"User-Agent": "OpeningFenix-App"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                total_size = int(resp.headers.get('Content-Length', 0))
                downloaded = 0
                chunk_size = 1024 * 64

                with open(dest_path, "wb") as f_out:
                    while True:
                        if self._is_cancelled:
                            f_out.close()
                            if os.path.exists(dest_path):
                                os.remove(dest_path)
                            return
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f_out.write(chunk)
                        downloaded += len(chunk)
                        self.progress.emit(downloaded, total_size)

            self.finished.emit(dest_path)
        except Exception as e:
            logger.error(f"Download error: {e}")
            self.error.emit(str(e))
