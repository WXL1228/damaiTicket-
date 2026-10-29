import builtins

from damai import check_environment


def test_dependency_check_uses_the_driver_installer_used_at_startup(monkeypatch):
    imported = []

    def installed_dependencies(name):
        imported.append(name)
        if name not in {"selenium", "chromedriver_autoinstaller"}:
            raise ImportError(name)
        return object()

    monkeypatch.setattr(builtins, "__import__", installed_dependencies)

    assert check_environment.check_dependencies() is True
    assert imported == ["selenium", "chromedriver_autoinstaller"]


def test_missing_driver_installer_shows_the_pip_package_name(monkeypatch, capsys):
    real_import = builtins.__import__

    def missing_driver_installer(name, *args, **kwargs):
        if name == "chromedriver_autoinstaller":
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing_driver_installer)

    assert check_environment.check_dependencies() is False
    assert "pip install chromedriver-autoinstaller" in capsys.readouterr().out
