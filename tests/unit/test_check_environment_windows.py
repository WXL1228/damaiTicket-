import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from damai import check_environment


WINDOWS_CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
WINDOWS_CHROMEDRIVER = r"C:\Tools\chromedriver.exe"


@pytest.fixture(autouse=True)
def isolate_executable_version(monkeypatch):
    # These tests simulate Chrome installations, including on a Windows host.
    monkeypatch.setattr(check_environment, "_get_windows_executable_version", lambda path: None)


def test_check_chrome_detects_windows_program_files_install(monkeypatch):
    """Chrome installed in Program Files should be detected on Windows."""

    def fake_exists(path):
        return path == WINDOWS_CHROME

    def fake_version(command):
        if command[0] == WINDOWS_CHROME:
            return "Google Chrome 136.0.7103.114"
        return None

    monkeypatch.setattr(check_environment.os.path, "exists", fake_exists)
    monkeypatch.setattr(check_environment, "_run_command_get_version", fake_version)

    assert check_environment.check_chrome() is True


def test_check_version_match_uses_windows_chrome_and_driver_paths(monkeypatch):
    """Version matching should work for Windows Chrome and chromedriver.exe."""

    def fake_exists(path):
        return path in {WINDOWS_CHROME, WINDOWS_CHROMEDRIVER}

    def fake_islink(path):
        return False

    def fake_version(command):
        if command[0] == WINDOWS_CHROME:
            return "Google Chrome 136.0.7103.114"
        if command[0] == WINDOWS_CHROMEDRIVER:
            return "ChromeDriver 136.0.7103.114"
        return None

    monkeypatch.setenv("CHROMEDRIVER_PATH", WINDOWS_CHROMEDRIVER)
    monkeypatch.setattr(check_environment.os.path, "exists", fake_exists)
    monkeypatch.setattr(check_environment.os.path, "islink", fake_islink)
    monkeypatch.setattr(check_environment, "_run_command_get_version", fake_version)

    assert check_environment.check_version_match() is True


def test_find_chrome_reads_windows_install_version_directory(monkeypatch, tmp_path):
    """
    On Windows, chrome.exe --version can open an existing browser session instead
    of printing a version, so fall back to the versioned install directory.
    """
    chrome_path = str(tmp_path / "Google" / "Chrome" / "Application" / "chrome.exe")
    version_dir = Path(chrome_path).parent / "136.0.7103.114"

    def fake_exists(path):
        return path == chrome_path

    def fake_listdir(path):
        if path == str(Path(chrome_path).parent):
            return [version_dir.name]
        return []

    def fake_isdir(path):
        return path == str(version_dir)

    monkeypatch.setattr(check_environment, "_get_chrome_paths", lambda: [chrome_path], raising=False)
    monkeypatch.setattr(check_environment.os.path, "exists", fake_exists)
    monkeypatch.setattr(check_environment.os.path, "isdir", fake_isdir)
    monkeypatch.setattr(check_environment.os, "listdir", fake_listdir)
    monkeypatch.setattr(check_environment, "_run_command_get_version", lambda command: "正在现有的浏览器会话中打开。")

    assert check_environment._find_chrome() == (
        chrome_path,
        "Google Chrome 136.0.7103.114",
        "136",
    )


def test_get_chromedriver_paths_includes_autoinstaller_cache(monkeypatch, tmp_path):
    """Environment checks should find drivers downloaded by chromedriver-autoinstaller."""
    package_dir = tmp_path / "chromedriver_autoinstaller"
    driver_dir = package_dir / "136"
    driver_dir.mkdir(parents=True)
    driver_path = driver_dir / "chromedriver.exe"
    driver_path.write_text("")

    fake_autoinstaller = SimpleNamespace(__file__=str(package_dir / "__init__.py"))
    monkeypatch.setitem(sys.modules, "chromedriver_autoinstaller", fake_autoinstaller)

    assert str(driver_path) in check_environment._get_chromedriver_paths()


def test_find_chrome_prefers_running_executable_over_pending_update(monkeypatch, tmp_path):
    chrome_path = tmp_path / "chrome.exe"
    chrome_path.touch()
    (tmp_path / "155.0.8059.85").mkdir()
    (tmp_path / "156.0.8078.49").mkdir()
    monkeypatch.setattr(check_environment, "_get_chrome_paths", lambda: [str(chrome_path)])
    monkeypatch.setattr(check_environment, "_get_windows_executable_version", lambda path: "155.0.8059.85")

    def must_not_launch_chrome(command):
        raise AssertionError("Version detection must not open the browser")

    monkeypatch.setattr(check_environment, "_run_command_get_version", must_not_launch_chrome)

    assert check_environment._find_chrome() == (str(chrome_path), "Google Chrome 155.0.8059.85", "155")
    assert check_environment._get_windows_chrome_version(str(chrome_path)) == "155.0.8059.85"


def test_driver_download_uses_actual_browser_version_and_restores_detector(monkeypatch):
    utils = SimpleNamespace(get_chrome_version=lambda: "156.0.8078.49")
    original_detector = utils.get_chrome_version

    def install():
        assert utils.get_chrome_version() == "155.0.8059.85"
        return WINDOWS_CHROMEDRIVER

    installer = SimpleNamespace(utils=utils, install=install)
    monkeypatch.setitem(sys.modules, "chromedriver_autoinstaller", installer)
    monkeypatch.setattr(check_environment, "_find_chrome", lambda: (WINDOWS_CHROME, "Google Chrome 155.0.8059.85", "155"))
    monkeypatch.setattr(check_environment, "_get_chromedriver_paths", lambda: [])
    monkeypatch.setattr(check_environment, "_run_command_get_version", lambda command: "ChromeDriver 155.0.8059.85")

    assert check_environment.get_chromedriver_path() == WINDOWS_CHROMEDRIVER
    assert utils.get_chrome_version is original_detector


def test_downloaded_driver_version_must_match_browser(monkeypatch):
    installer = SimpleNamespace(
        utils=SimpleNamespace(get_chrome_version=lambda: "156.0.8078.49"),
        install=lambda: WINDOWS_CHROMEDRIVER,
    )
    monkeypatch.setitem(sys.modules, "chromedriver_autoinstaller", installer)
    monkeypatch.setattr(check_environment, "_find_chrome", lambda: (WINDOWS_CHROME, "Google Chrome 155.0.8059.85", "155"))
    monkeypatch.setattr(check_environment, "_get_chromedriver_paths", lambda: [])
    monkeypatch.setattr(check_environment, "_run_command_get_version", lambda command: "ChromeDriver 156.0.8078.73")

    with pytest.raises(RuntimeError, match="不匹配"):
        check_environment.get_chromedriver_path()


def test_version_check_searches_all_cached_drivers_for_a_match(monkeypatch):
    drivers = {
        r"C:\cache\156\chromedriver.exe": "ChromeDriver 156.0.8078.73",
        r"C:\cache\155\chromedriver.exe": "ChromeDriver 155.0.8059.85",
    }
    monkeypatch.setattr(check_environment, "_find_chrome", lambda: (WINDOWS_CHROME, "Google Chrome 155.0.8059.85", "155"))
    monkeypatch.setattr(check_environment, "_get_chromedriver_paths", lambda: list(drivers))
    monkeypatch.setattr(check_environment.os.path, "exists", lambda path: path in drivers)
    monkeypatch.setattr(check_environment, "_run_command_get_version", lambda command: drivers[command[0]])

    assert check_environment.check_version_match() is True
