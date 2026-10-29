import json
from pathlib import Path
import runpy
import sys
from unittest.mock import Mock

import pytest

pytest.importorskip("appium", reason="Android tests require the optional mobile dependencies")

from damai_appium import config as config_module
from damai_appium import damai_app_v2
from damai_appium import sale_wait
from damai_appium import page_diagnostics
from damai_appium.config import Config


def make_config(**overrides):
    values = dict(
        server_url="http://127.0.0.1:4723",
        keyword="测试演出",
        users=["测试观众"],
        city="深圳",
        date="12.06",
        price="799元",
        price_index=1,
        if_commit_order=False,
    )
    values.update(overrides)
    return Config(**values)


def test_script_import_uses_config_without_starting_a_device(monkeypatch):
    remote = Mock(name="Remote")
    monkeypatch.setattr(damai_app_v2.webdriver, "Remote", remote)
    monkeypatch.setitem(sys.modules, "config", config_module)
    monkeypatch.setitem(sys.modules, "sale_wait", sale_wait)
    monkeypatch.setitem(sys.modules, "page_diagnostics", page_diagnostics)

    namespace = runpy.run_path(str(Path(damai_app_v2.__file__)), run_name="import_check")

    assert namespace["Config"] is Config
    remote.assert_not_called()


@pytest.fixture
def bot(monkeypatch):
    """Run the existing flow with every device interaction mocked."""
    remote = Mock(name="Remote")
    remote.return_value.find_elements.return_value = []
    monkeypatch.setattr(damai_app_v2.webdriver, "Remote", remote)
    monkeypatch.setattr(damai_app_v2.time, "sleep", Mock())
    monkeypatch.setattr(Config, "load_config", staticmethod(make_config))
    instance = damai_app_v2.DamaiBot()
    # Sale-page recognition and timed waiting have separate XML/clock tests.
    instance._wait_for_sale = Mock(return_value="detail")
    instance.smart_wait_and_click = Mock(return_value=True)
    instance.ultra_fast_click = Mock(return_value=True)
    instance.ultra_batch_click = Mock()
    return instance


@pytest.mark.parametrize("reservation_label", ["预约想看场次", "预约想看票档"])
def test_reservation_page_stops_before_clicking_and_does_not_retry(bot, reservation_label, capsys):
    bot.driver.find_elements.side_effect = lambda by, value: (
        [Mock()] if value == f'new UiSelector().text("{reservation_label}")' else []
    )
    bot._setup_driver = Mock()

    assert bot.run_with_retry(max_retries=3) is False

    bot.smart_wait_and_click.assert_not_called()
    bot.ultra_fast_click.assert_not_called()
    bot.ultra_batch_click.assert_not_called()
    bot.driver.find_element.assert_not_called()
    bot.driver.execute_script.assert_not_called()
    bot._setup_driver.assert_not_called()
    bot.driver.quit.assert_called_once()
    output = capsys.readouterr().out
    assert "当前为预约页" in output
    assert "等待开售" in output
    assert "第 2 次尝试" not in output


@pytest.mark.parametrize("reservation_label", ["预约想看场次", "预约想看票档"])
def test_purchase_entry_opening_reservation_sku_stops_before_changing_selections(bot, reservation_label, capsys):
    reservation_sku_open = False
    purchase_entry_id = "cn.damai:id/trade_project_detail_purchase_status_bar_container_fl"

    def click_entry(by, value, backup_selectors=None, timeout=1.5):
        nonlocal reservation_sku_open
        if purchase_entry_id in value:
            reservation_sku_open = True
        return True

    def find_visible_labels(by, value):
        if reservation_sku_open and value == f'new UiSelector().text("{reservation_label}")':
            return [Mock()]
        return []

    bot.smart_wait_and_click.side_effect = click_entry
    bot.driver.find_elements.side_effect = find_visible_labels
    bot._setup_driver = Mock()
    bot.config.if_commit_order = True

    assert bot.run_with_retry(max_retries=3) is False

    # Only the verified detail entry may be clicked; never alter reservation prefill.
    assert bot.smart_wait_and_click.call_count == 1
    assert purchase_entry_id in bot.smart_wait_and_click.call_args.args[1]
    bot.driver.find_element.assert_not_called()
    bot.driver.execute_script.assert_not_called()
    bot.ultra_fast_click.assert_not_called()
    bot.ultra_batch_click.assert_not_called()
    assert all(call.args[1] != "layout_num" for call in bot.driver.find_elements.call_args_list)
    bot._setup_driver.assert_not_called()
    bot.driver.quit.assert_called_once()
    output = capsys.readouterr().out
    assert "当前为预约页" in output
    assert "选择票价" not in output
    assert "选择数量" not in output
    assert "选择用户" not in output
    assert "提交订单" not in output
    assert "第 2 次尝试" not in output


@pytest.mark.parametrize("container_uses_fallback", [False, True])
def test_delayed_reservation_title_is_checked_after_price_container_is_ready(bot, container_uses_fallback):
    reservation_sku_open = False
    price_container = Mock()

    def ready_price_container(*args):
        nonlocal reservation_sku_open
        reservation_sku_open = True
        return price_container

    if container_uses_fallback:
        bot.driver.find_element.side_effect = damai_app_v2.NoSuchElementException("SKU is still loading")
    else:
        bot.driver.find_element.side_effect = ready_price_container
    bot.wait = Mock()
    bot.wait.until.side_effect = ready_price_container
    bot.driver.find_elements.side_effect = lambda by, value: (
        [Mock()] if reservation_sku_open and value == 'new UiSelector().text("预约想看票档")' else []
    )
    bot._setup_driver = Mock()
    bot.config.if_commit_order = True

    assert bot.run_with_retry(max_retries=3) is False

    assert bot.smart_wait_and_click.call_count == 1
    price_container.find_element.assert_not_called()
    bot.driver.execute_script.assert_not_called()
    bot.ultra_fast_click.assert_not_called()
    bot.ultra_batch_click.assert_not_called()
    bot._setup_driver.assert_not_called()
    bot.driver.quit.assert_called_once()


def test_generic_reservation_word_on_purchase_detail_does_not_block_flow(bot):
    visible_labels = {"预约提醒", "立即购买"}
    bot.driver.find_elements.side_effect = lambda by, value: (
        [Mock()] if value in {f'new UiSelector().text("{label}")' for label in visible_labels} else []
    )

    assert bot.run_ticket_grabbing() is True

    assert bot._reservation_page_detected is False
    assert bot.smart_wait_and_click.call_count == 1


def test_purchase_fallback_does_not_match_cancellation_or_reservation_titles(bot):
    assert bot.run_ticket_grabbing() is True

    purchase_call = bot.smart_wait_and_click.call_args_list[0]
    assert purchase_call.args[0] == damai_app_v2.By.XPATH
    xpath = purchase_call.args[1]
    assert "cn.damai:id/trade_project_detail_purchase_status_bar_container_fl" in xpath
    for label in ("取消预约", "预约想看场次", "预约想看票档", "立即预约"):
        assert label not in xpath
    assert "contains(" not in xpath
    assert "预约" not in xpath
    assert '@text="立即购买"' in xpath


def test_submission_disabled_does_not_click_submit(bot, capsys):
    assert bot.run_ticket_grabbing() is True

    # Only the verified purchase control uses this helper before submit.
    assert bot.smart_wait_and_click.call_count == 1
    assert all("提交" not in str(call) for call in bot.smart_wait_and_click.call_args_list)
    bot.driver.quit.assert_called_once()
    assert "已跳过提交订单" in capsys.readouterr().out


def test_submission_enabled_but_click_fails_reports_failure(bot, capsys):
    bot.config.if_commit_order = True
    bot.smart_wait_and_click.side_effect = [True, False]

    assert bot.run_ticket_grabbing() is False

    assert bot.smart_wait_and_click.call_count == 2
    assert "立即提交" in bot.smart_wait_and_click.call_args.args[1]
    bot.driver.quit.assert_called_once()
    output = capsys.readouterr().out
    assert "提交按钮点击失败" in output
    assert "抢票流程完成" not in output


def test_submission_click_only_reports_flow_complete(bot, capsys):
    bot.config.if_commit_order = True

    assert bot.run_with_retry(max_retries=1) is True

    assert bot.smart_wait_and_click.call_count == 2
    output = capsys.readouterr().out
    assert "请在大麦 APP 中确认订单结果" in output
    assert "流程执行完成" in output
    assert "抢票成功" not in output


def test_failed_submission_is_not_reported_as_retry_success(bot, capsys):
    bot.config.if_commit_order = True
    bot.smart_wait_and_click.side_effect = [True, False]

    assert bot.run_with_retry(max_retries=1) is False

    output = capsys.readouterr().out
    assert "所有尝试均失败" in output
    assert "流程执行完成" not in output
    assert "抢票成功" not in output


@pytest.mark.parametrize(
    "device_options, expected_device_caps",
    [
        ({}, {"appium:deviceName": "Android"}),
        (
            {"device_name": "测试手机", "platform_version": "14", "udid": "device-123"},
            {
                "appium:deviceName": "测试手机",
                "appium:platformVersion": "14",
                "appium:udid": "device-123",
            },
        ),
    ],
)
def test_driver_uses_optional_device_configuration(monkeypatch, device_options, expected_device_caps):
    config = make_config(**device_options)
    monkeypatch.setattr(Config, "load_config", staticmethod(lambda: config))
    remote = Mock(name="Remote")
    monkeypatch.setattr(damai_app_v2.webdriver, "Remote", remote)

    damai_app_v2.DamaiBot()

    remote.assert_called_once()
    assert remote.call_args.args == (config.server_url,)
    capabilities = remote.call_args.kwargs["options"].to_capabilities()
    assert capabilities["platformName"] == "Android"
    for name in ("appium:deviceName", "appium:platformVersion", "appium:udid"):
        if name in expected_device_caps:
            assert capabilities[name] == expected_device_caps[name]
        else:
            assert name not in capabilities


def test_native_driver_does_not_require_settings_initialization_or_keyboard_permissions(monkeypatch):
    monkeypatch.setattr(Config, "load_config", staticmethod(make_config))
    remote = Mock(name="Remote")
    monkeypatch.setattr(damai_app_v2.webdriver, "Remote", remote)

    damai_app_v2.DamaiBot()

    capabilities = remote.call_args.kwargs["options"].to_capabilities()
    assert capabilities["appium:skipDeviceInitialization"] is True
    assert capabilities["appium:skipUnlock"] is True
    # Keep the explicit empty string: AppiumOptions removes None and restores the driver's default.
    assert capabilities["appium:mockLocationApp"] == ""
    for name in ("unicodeKeyboard", "resetKeyboard", "hideKeyboard", "disableWindowAnimation"):
        assert f"appium:{name}" not in capabilities
    assert capabilities["appium:noReset"] is True
    assert capabilities["appium:shouldTerminateApp"] is False
    assert capabilities["appium:ignoreHiddenApiPolicyError"] is True
    assert capabilities["appium:skipServerInstallation"] is False


@pytest.mark.parametrize(
    "device_options",
    [{}, {"device_name": "测试手机", "platform_version": "14", "udid": "device-123"}],
)
def test_config_is_loaded_next_to_module_from_another_working_directory(monkeypatch, tmp_path, device_options):
    module_dir = tmp_path / "damai_appium"
    module_dir.mkdir()
    config_data = vars(make_config(**device_options)).copy()
    # Existing config files have no device keys; keep that format covered.
    if not device_options:
        for name in ("device_name", "platform_version", "udid", "sale_start_time", "wait_poll_interval"):
            config_data.pop(name)
    (module_dir / "config.jsonc").write_text(json.dumps(config_data), encoding="utf-8")
    monkeypatch.setattr(config_module, "__file__", str(module_dir / "config.py"))
    monkeypatch.chdir(tmp_path)

    loaded = Config.load_config()

    assert loaded.server_url == config_data["server_url"]
    assert loaded.users == ["测试观众"]
    assert loaded.if_commit_order is False
    assert loaded.device_name == device_options.get("device_name", "Android")
    assert loaded.platform_version == device_options.get("platform_version")
    assert loaded.udid == device_options.get("udid")
    assert loaded.sale_start_time is None
    assert loaded.wait_poll_interval == 0.5


@pytest.mark.parametrize("value", ["2026-10-29 10:18", "2026-10-29 10：18：00"])
def test_sale_start_time_is_parsed_as_beijing_time(value):
    config = make_config(sale_start_time=value)
    assert config.sale_start_datetime.isoformat() == "2026-10-29T10:18:00+08:00"


@pytest.mark.parametrize("options", [
    {"sale_start_time": "10:18"}, {"sale_start_time": "2026-02-30 10:18"},
    {"wait_poll_interval": 0}, {"wait_poll_interval": float("nan")},
])
def test_invalid_wait_configuration_fails_before_device_connection(options):
    with pytest.raises(ValueError):
        make_config(**options)


def test_formal_sku_skips_purchase_entry_and_city_switch(bot):
    bot._wait_for_sale.return_value = "sku"
    assert bot.run_ticket_grabbing() is True
    bot.smart_wait_and_click.assert_not_called()


@pytest.mark.parametrize("visible, enabled", [(False, True), (True, False)])
def test_smart_click_rechecks_visible_and_enabled_state(bot, monkeypatch, visible, enabled):
    button = Mock()
    button.is_displayed.return_value = visible
    button.is_enabled.return_value = enabled
    bot.driver.find_element.return_value = button

    def check_condition(condition):
        if not condition(bot.driver):
            raise damai_app_v2.TimeoutException()
        return button

    wait = Mock()
    wait.until.side_effect = check_condition
    monkeypatch.setattr(damai_app_v2, "WebDriverWait", Mock(return_value=wait))
    assert damai_app_v2.DamaiBot.smart_wait_and_click(bot, "xpath", "purchase") is False
    bot.driver.execute_script.assert_not_called()


def test_interrupt_during_driver_settings_releases_session(monkeypatch):
    monkeypatch.setattr(Config, "load_config", staticmethod(make_config))
    remote = Mock()
    remote.return_value.update_settings.side_effect = KeyboardInterrupt()
    monkeypatch.setattr(damai_app_v2.webdriver, "Remote", remote)
    with pytest.raises(KeyboardInterrupt):
        damai_app_v2.DamaiBot()
    remote.return_value.quit.assert_called_once()


def test_page_check_only_reads_and_saves_summary_without_entering_purchase_flow(bot, monkeypatch, tmp_path):
    monkeypatch.setattr(damai_app_v2, "__file__", str(tmp_path / "damai_appium" / "damai_app_v2.py"))
    bot.driver.page_source = '''<hierarchy><node package="cn.damai">
      <node package="cn.damai" resource-id="cn.damai:id/info_v2_title_tv1" text="深圳·测试演出"/>
      <node package="cn.damai" resource-id="cn.damai:id/trade_project_detail_purchase_status_bar_container_fl" clickable="true">
        <node package="cn.damai" text="立即购买"/>
      </node><node package="cn.damai" text="测试观众13800138000"/>
    </node></hierarchy>'''

    assert bot.check_current_page() is True

    bot._wait_for_sale.assert_not_called()
    bot.smart_wait_and_click.assert_not_called()
    bot.ultra_fast_click.assert_not_called()
    bot.driver.execute_script.assert_not_called()
    bot.driver.quit.assert_called_once()
    saved = (tmp_path / "logs" / "mobile-page-check.json").read_text(encoding="utf-8")
    assert "深圳·测试演出" in saved
    assert "测试观众" not in saved
    assert "13800138000" not in saved


def test_check_page_cli_never_runs_ticket_flow(monkeypatch, tmp_path):
    from damai_appium import prefilled_flow
    monkeypatch.setattr(prefilled_flow, "STATE_DIR", tmp_path)
    monkeypatch.setattr(Config, "load_config", staticmethod(make_config))
    instance = Mock()
    factory = Mock(return_value=instance)
    monkeypatch.setattr(damai_app_v2, "DamaiBot", factory)
    damai_app_v2.main(["--check-page"])
    instance.check_current_page.assert_called_once_with()
    instance.run_with_retry.assert_not_called()


def test_prefilled_cli_does_not_enter_legacy_retry_flow(monkeypatch, tmp_path):
    from damai_appium import prefilled_flow
    config = make_config(prefilled_mode=True)
    monkeypatch.setattr(Config, "load_config", staticmethod(lambda: config))
    monkeypatch.setattr(prefilled_flow, "STATE_DIR", tmp_path)
    instance = Mock()
    monkeypatch.setattr(damai_app_v2, "DamaiBot", Mock(return_value=instance))
    damai_app_v2.main([])
    instance.run_prefilled_order.assert_called_once_with()
    instance.run_with_retry.assert_not_called()
    instance.check_current_page.assert_not_called()


def test_parallel_page_check_is_rejected_before_creating_another_session(monkeypatch, tmp_path):
    from damai_appium import prefilled_flow
    config = make_config(prefilled_mode=True)
    monkeypatch.setattr(Config, "load_config", staticmethod(lambda: config))
    monkeypatch.setattr(prefilled_flow, "STATE_DIR", tmp_path)
    factory = Mock()
    monkeypatch.setattr(damai_app_v2, "DamaiBot", factory)
    with prefilled_flow.DeviceRunLock(config):
        assert damai_app_v2.main(["--check-page"]) is False
    factory.assert_not_called()


def test_cli_help_does_not_connect_to_phone(monkeypatch):
    factory = Mock()
    monkeypatch.setattr(damai_app_v2, "DamaiBot", factory)
    with pytest.raises(SystemExit) as result:
        damai_app_v2.main(["--help"])
    assert result.value.code == 0
    factory.assert_not_called()
