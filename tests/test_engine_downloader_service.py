import os
import sys
import io
import json
import zipfile
import pytest
from unittest.mock import patch, MagicMock

from opening_fenix.core.services.engine_downloader_service import (
    get_engines_dir, is_engine_valid, get_latest_stockfish_asset_url,
    StockfishDownloaderWorker, STOCKFISH_FALLBACK_URL, STOCKFISH_FALLBACK_NAME
)


def test_get_engines_dir(tmp_path):
    with patch("opening_fenix.core.services.engine_downloader_service.get_default_user_dir", return_value=str(tmp_path)):
        engines_dir = get_engines_dir()
        assert os.path.exists(engines_dir)
        assert os.path.isdir(engines_dir)
        assert engines_dir == os.path.join(str(tmp_path), "engines")


def test_is_engine_valid(tmp_path):
    # None or empty
    assert not is_engine_valid(None)
    assert not is_engine_valid("")
    assert not is_engine_valid("   ")

    # Nonexistent
    assert not is_engine_valid(str(tmp_path / "nonexistent.exe"))

    # Directory
    test_dir = tmp_path / "somedir"
    test_dir.mkdir()
    assert not is_engine_valid(str(test_dir))

    # Text file (non-executable on windows)
    txt_file = tmp_path / "notes.txt"
    txt_file.write_text("hello")
    if sys.platform == "win32":
        assert not is_engine_valid(str(txt_file))

    # Valid exe file
    exe_file = tmp_path / "stockfish.exe"
    exe_file.write_bytes(b"MZ\x90\x00mock_binary")
    assert is_engine_valid(str(exe_file))


def test_get_latest_stockfish_asset_url_github_success():
    mock_payload = {
        "tag_name": "sf_19",
        "assets": [
            {
                "name": "stockfish-windows-x86-64-universal.zip",
                "browser_download_url": "https://github.com/mock/sf19-universal.zip"
            },
            {
                "name": "stockfish-ubuntu-x86-64.tar",
                "browser_download_url": "https://github.com/mock/sf19-ubuntu.tar"
            }
        ]
    }
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        url, name = get_latest_stockfish_asset_url()
        assert url == "https://github.com/mock/sf19-universal.zip"
        assert name == "stockfish-windows-x86-64-universal.zip"


def test_get_latest_stockfish_asset_url_fallback():
    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        url, name = get_latest_stockfish_asset_url()
        assert url == STOCKFISH_FALLBACK_URL
        assert name == STOCKFISH_FALLBACK_NAME


def test_downloader_worker_success(tmp_path, qapp):
    target_dir = str(tmp_path / "engines")
    os.makedirs(target_dir, exist_ok=True)

    # Create mock zip in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("stockfish-windows-x86-64-universal.exe", b"MZ\x90\x00MockStockfishBinary")
        zf.writestr("Copying.txt", b"GPLv3 License text")
    zip_bytes = zip_buffer.getvalue()

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.headers = {"Content-Length": str(len(zip_bytes))}
    
    # Stream in chunks
    chunks = [zip_bytes[:50], zip_bytes[50:], b""]
    mock_resp.read.side_effect = chunks
    mock_resp.__enter__.return_value = mock_resp

    worker = StockfishDownloaderWorker(target_dir=target_dir)

    signals_received = {
        "progress": [],
        "status": [],
        "finished": [],
        "error": []
    }

    worker.progress.connect(lambda d, t: signals_received["progress"].append((d, t)))
    worker.status.connect(lambda s: signals_received["status"].append(s))
    worker.finished.connect(lambda p: signals_received["finished"].append(p))
    worker.error.connect(lambda e: signals_received["error"].append(e))

    with patch("urllib.request.urlopen", return_value=mock_resp), \
         patch("opening_fenix.core.services.engine_downloader_service.get_latest_stockfish_asset_url", 
               return_value=("https://example.com/sf.zip", "sf.zip")), \
         patch("opening_fenix.core.services.engine_downloader_service.get_config_dict", return_value={}), \
         patch("opening_fenix.core.services.engine_downloader_service.save_config_dict") as mock_save:

        worker.run()

        assert not signals_received["error"]
        assert len(signals_received["finished"]) == 1
        extracted_exe = signals_received["finished"][0]
        assert os.path.exists(extracted_exe)
        assert os.path.isfile(extracted_exe)
        assert os.path.exists(os.path.join(target_dir, "STOCKFISH_LICENSE.txt"))
        mock_save.assert_called_once()
        saved_cfg = mock_save.call_args[0][0]
        assert saved_cfg.get("engine_path") == extracted_exe


def test_downloader_worker_cancellation(tmp_path, qapp):
    target_dir = str(tmp_path / "engines")
    worker = StockfishDownloaderWorker(target_dir=target_dir)
    worker.cancel()

    signals_received = {"finished": [], "error": []}
    worker.finished.connect(lambda p: signals_received["finished"].append(p))
    worker.error.connect(lambda e: signals_received["error"].append(e))

    with patch("opening_fenix.core.services.engine_downloader_service.get_latest_stockfish_asset_url",
               return_value=("https://example.com/sf.zip", "sf.zip")):
        worker.run()

    assert not signals_received["finished"]
    assert not signals_received["error"]
