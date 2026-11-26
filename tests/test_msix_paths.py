import os
import sys
import tempfile

import opening_fenix.core.utils as utils
from opening_fenix.core.services.update_service import UpdateCheckWorker, should_check_for_updates


TEST_PFN = "TakaisChess.OpeningFenixChess_re6rtymtb0s24"


def test_get_default_user_dir_uses_real_msix_localcache_when_packaged(tmp_path, monkeypatch):
    utils._FROZEN_DEFAULT_DIR_CACHE.clear()
    try:
        fake_exe = str(tmp_path / "app" / "Opening Fenix.exe")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", fake_exe, raising=False)
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.setattr(utils, "get_msix_package_family_name", lambda: TEST_PFN)

        expected = os.path.join(
            str(tmp_path), "Packages", TEST_PFN, "LocalCache", "Roaming", "Opening Fenix"
        )
        result = utils.get_default_user_dir()
        assert result == expected
        assert os.path.isdir(expected)
    finally:
        utils._FROZEN_DEFAULT_DIR_CACHE.clear()


def test_get_real_temp_dir_msix_and_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(utils, "get_msix_package_family_name", lambda: TEST_PFN)

    expected = os.path.join(str(tmp_path), "Packages", TEST_PFN, "LocalCache", "Local", "Temp")
    result = utils.get_real_temp_dir()
    assert result == expected
    assert os.path.isdir(expected)

    monkeypatch.setattr(utils, "get_msix_package_family_name", lambda: None)
    assert utils.get_real_temp_dir() == tempfile.gettempdir()


def test_get_msix_package_family_name_non_packaged():
    assert utils.get_msix_package_family_name() is None


def test_store_version_disables_github_update_checks(monkeypatch):
    monkeypatch.setenv("FENIX_STORE_BUILD", "1")
    assert utils.is_store_version() is True
    assert should_check_for_updates(manual=True) is False
    assert should_check_for_updates(manual=False) is False

    worker = UpdateCheckWorker(manual=True)
    events = {"found": 0, "none": 0, "error": 0}
    worker.update_found.connect(lambda _info: events.__setitem__("found", events["found"] + 1))
    worker.no_update_found.connect(lambda: events.__setitem__("none", events["none"] + 1))
    worker.check_error.connect(lambda _err: events.__setitem__("error", events["error"] + 1))

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("safe_urlopen must not be called in Store build")

    monkeypatch.setattr("opening_fenix.core.services.update_service.safe_urlopen", fail_if_called)
    worker.run()

    assert events == {"found": 0, "none": 1, "error": 0}
