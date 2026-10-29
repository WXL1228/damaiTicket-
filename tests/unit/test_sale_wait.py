from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from xml.etree import ElementTree

import pytest

from damai_appium.config import Config
from damai_appium.sale_wait import inspect_sale_page


BEIJING = timezone(timedelta(hours=8))
TITLE = "北京·侯明昊《属于我们的》演唱会-北京站"


def page_xml(*, title=TITLE, reservation=None, reservation_enabled="true",
             buy_label="立即购买", buy_enabled="true", buy_visible="true",
             bar_clickable="true", known_bar=True, sku=False):
    root = ElementTree.Element("hierarchy")
    app = ElementTree.SubElement(root, "node", {
        "package": "cn.damai", "enabled": "true", "displayed": "true",
    })

    def node(parent, **attributes):
        defaults = {"package": "cn.damai", "enabled": "true", "displayed": "true"}
        defaults.update(attributes)
        return ElementTree.SubElement(parent, "node", defaults)

    node(app, **{"resource-id": "cn.damai:id/info_v2_title_tv1", "text": title})
    if reservation:
        node(app, text=reservation, enabled=reservation_enabled)
    if sku:
        node(app, **{"resource-id": "cn.damai:id/project_detail_perform_price_flowlayout"})
        node(app, **{
            "resource-id": "cn.damai:id/btn_buy_view", "text": buy_label,
            "clickable": "true", "enabled": buy_enabled, "displayed": buy_visible,
        })
    else:
        bar = node(app, **{
            "resource-id": ("cn.damai:id/trade_project_detail_purchase_status_bar_container_fl"
                            if known_bar else "cn.damai:id/unrelated_panel"),
            "clickable": bar_clickable, "enabled": buy_enabled, "displayed": buy_visible,
        })
        # The label is intentionally not clickable: the enclosing purchase bar is.
        node(bar, text=buy_label, clickable="false")
    return ElementTree.tostring(root, encoding="unicode")


@pytest.mark.parametrize("label", ["预约想看场次", "预约想看票档"])
def test_reservation_sku_is_not_a_purchase_page(label):
    stage, message = inspect_sale_page(
        page_xml(reservation=label, sku=True, buy_label="确定"), "侯明昊", "北京")
    assert stage is None
    assert "预约" in message


def test_visible_disabled_reservation_heading_still_identifies_reservation():
    # A noninteractive heading can be disabled while remaining fully visible.
    stage, _ = inspect_sale_page(page_xml(
        reservation="预约想看票档", reservation_enabled="false", sku=True, buy_label="确定"
    ), "侯明昊", "北京")
    assert stage is None


def test_purchase_text_accepts_enabled_clickable_parent():
    stage, _ = inspect_sale_page(page_xml(), "侯明昊", "北京")
    assert stage == "detail"


@pytest.mark.parametrize("options", [
    {"buy_enabled": "false"}, {"buy_visible": "false"}, {"bar_clickable": "false"},
])
def test_disabled_hidden_or_nonclickable_purchase_entry_is_not_ready(options):
    stage, _ = inspect_sale_page(page_xml(**options), "侯明昊", "北京")
    assert stage is None


@pytest.mark.parametrize("title", ["北京·其他歌手演唱会", "上海·侯明昊演唱会"])
def test_wrong_show_or_city_is_not_ready(title):
    stage, _ = inspect_sale_page(page_xml(title=title), "侯明昊", "北京")
    assert stage is None


def test_unlabelled_purchase_bar_does_not_release_standby():
    stage, _ = inspect_sale_page(page_xml(buy_label=""), "侯明昊", "北京")
    assert stage is None


def test_purchase_text_outside_known_bar_does_not_release_standby():
    stage, _ = inspect_sale_page(page_xml(known_bar=False), "侯明昊", "北京")
    assert stage is None


def test_manually_opened_formal_sku_requires_visible_purchase_confirmation():
    stage, _ = inspect_sale_page(page_xml(sku=True, buy_label="立即购买"), "侯明昊", "北京")
    assert stage == "sku"
    stage, _ = inspect_sale_page(page_xml(sku=True, buy_label="确定"), "侯明昊", "北京")
    assert stage is None
    stage, _ = inspect_sale_page(page_xml(sku=True, buy_label=""), "侯明昊", "北京")
    assert stage is None


def test_malformed_page_stays_in_standby():
    stage, _ = inspect_sale_page("<hierarchy", "侯明昊", "北京")
    assert stage is None


@pytest.mark.parametrize("title_format", ["description", "descendant", "whitespace"])
def test_title_can_be_read_from_description_children_or_wrapped_text(title_format):
    root = ElementTree.fromstring(page_xml())
    title = root.find('.//*[@resource-id="cn.damai:id/info_v2_title_tv1"]')
    title.set("text", "")
    if title_format == "description":
        title.set("content-desc", TITLE)
    elif title_format == "descendant":
        ElementTree.SubElement(title, "node", {"text": TITLE, "displayed": "true"})
    else:
        title.set("text", "北 京·侯 明 昊\n演唱会")
    assert inspect_sale_page(ElementTree.tostring(root), "侯明昊", "北京")[0] == "detail"


def test_missing_title_reports_unadapted_page_instead_of_accusing_wrong_show():
    root = ElementTree.fromstring(page_xml())
    title = root.find('.//*[@resource-id="cn.damai:id/info_v2_title_tv1"]')
    title.set("resource-id", "cn.damai:id/unknown_title")
    stage, message = inspect_sale_page(ElementTree.tostring(root), "侯明昊", "北京")
    assert stage is None
    assert "读不到已适配的标题控件" in message
    assert "--check-page" in message


@pytest.fixture
def mobile_module():
    pytest.importorskip("appium", reason="Wait-loop tests require optional mobile dependencies")
    from damai_appium import damai_app_v2
    return damai_app_v2


class ReadOnlyDriver:
    def __init__(self, pages):
        self._pages = iter(pages)
        self.page_reads = 0
        self.quit = Mock()
        self.execute_script = Mock()
        self.find_element = Mock()
        self.find_elements = Mock()

    @property
    def page_source(self):
        self.page_reads += 1
        result = next(self._pages)
        if isinstance(result, BaseException):
            raise result
        return result


def waiting_bot(module, pages, sale_start_time=None):
    bot = module.DamaiBot.__new__(module.DamaiBot)
    bot.config = Config(
        "http://127.0.0.1:4723", "侯明昊", ["测试观众"], "北京",
        "2026-11-28 19:00", "399元", 0, False,
        sale_start_time=sale_start_time, wait_poll_interval=0.5,
    )
    bot.driver = ReadOnlyDriver(pages)
    bot._reservation_page_detected = False
    bot._setup_driver = Mock()
    bot.smart_wait_and_click = Mock()
    return bot


def mock_clock(monkeypatch, module, times):
    values = iter(times)

    class Clock:
        @staticmethod
        def now(tz):
            return next(values).astimezone(tz)

    monkeypatch.setattr(module, "datetime", Clock)
    sleep = Mock()
    monkeypatch.setattr(module.time, "sleep", sleep)
    monkeypatch.setattr(module.time, "monotonic", lambda: 0.0)
    return sleep


def assert_no_actions(bot):
    bot.driver.execute_script.assert_not_called()
    bot.driver.find_element.assert_not_called()
    bot.driver.find_elements.assert_not_called()
    bot.smart_wait_and_click.assert_not_called()


def test_wait_keeps_reading_until_beijing_sale_time(monkeypatch, mobile_module):
    bot = waiting_bot(mobile_module, [page_xml(), page_xml()], "2026-10-29 10:18")
    sleep = mock_clock(monkeypatch, mobile_module, [
        datetime(2026, 10, 29, 10, 17, 59, tzinfo=BEIJING),
        datetime(2026, 10, 29, 10, 18, 0, tzinfo=BEIJING),
    ])

    assert bot._wait_for_sale() == "detail"

    assert bot.driver.page_reads == 2
    sleep.assert_called_once_with(0.5)
    assert_no_actions(bot)


def test_time_reached_does_not_release_reservation_page(monkeypatch, mobile_module, capsys):
    bot = waiting_bot(mobile_module, [
        page_xml(reservation="预约想看场次", sku=True, buy_label="确定"), page_xml(),
    ], "2026-10-29 10:18:00")
    mock_clock(monkeypatch, mobile_module, [
        datetime(2026, 10, 29, 10, 18, 0, tzinfo=BEIJING),
        datetime(2026, 10, 29, 10, 18, 1, tzinfo=BEIJING),
    ])

    assert bot._wait_for_sale() == "detail"

    assert bot.driver.page_reads == 2
    assert "手动返回演出详情" in capsys.readouterr().out
    assert_no_actions(bot)


def test_wait_can_recognize_manual_formal_sku_without_clicking(monkeypatch, mobile_module):
    bot = waiting_bot(mobile_module, [page_xml(sku=True, buy_label="立即购买")])
    mock_clock(monkeypatch, mobile_module, [datetime(2026, 10, 29, 10, 18, tzinfo=BEIJING)])

    assert bot._wait_for_sale() == "sku"

    assert_no_actions(bot)


def test_opening_time_does_not_release_unlabelled_purchase_bar(monkeypatch, mobile_module):
    bot = waiting_bot(mobile_module, [page_xml(buy_label=""), page_xml()], "2026-10-29 10:18")
    mock_clock(monkeypatch, mobile_module, [
        datetime(2026, 10, 29, 10, 18, 0, tzinfo=BEIJING),
        datetime(2026, 10, 29, 10, 18, 1, tzinfo=BEIJING),
    ])

    assert bot._wait_for_sale() == "detail"

    assert bot.driver.page_reads == 2
    assert_no_actions(bot)


def test_ctrl_c_in_standby_closes_session_without_retry(monkeypatch, mobile_module, capsys):
    bot = waiting_bot(mobile_module, [KeyboardInterrupt()])
    monkeypatch.setattr(mobile_module.time, "sleep", Mock())

    assert bot.run_with_retry(max_retries=3) is False

    bot.driver.quit.assert_called_once()
    bot._setup_driver.assert_not_called()
    assert_no_actions(bot)
    output = capsys.readouterr().out
    assert "已手动停止" in output
    assert "第 2 次尝试" not in output


def test_page_read_failure_closes_session_without_reconnecting(monkeypatch, mobile_module, capsys):
    bot = waiting_bot(mobile_module, [RuntimeError("device disconnected")])
    monkeypatch.setattr(mobile_module.time, "sleep", Mock())

    assert bot.run_with_retry(max_retries=3) is False

    bot.driver.quit.assert_called_once()
    bot._setup_driver.assert_not_called()
    assert_no_actions(bot)
    output = capsys.readouterr().out
    assert "device disconnected" in output
    assert "第 2 次尝试" not in output


def test_unrecognized_page_stops_after_opening_instead_of_waiting_forever(monkeypatch, mobile_module, capsys):
    bot = waiting_bot(mobile_module, [page_xml(buy_label=""), page_xml(title="未知页面")],
                      "2026-10-29 10:18:00")
    bot._save_page_diagnostics = Mock()
    mock_clock(monkeypatch, mobile_module, [
        datetime(2026, 10, 29, 10, 18, 0, tzinfo=BEIJING),
        datetime(2026, 10, 29, 10, 18, 3, tzinfo=BEIJING),
    ])

    assert bot.run_with_retry(max_retries=30) is False

    bot.driver.quit.assert_called_once()
    bot._setup_driver.assert_not_called()
    bot._save_page_diagnostics.assert_called_once()
    assert_no_actions(bot)
    output = capsys.readouterr().out
    assert "请立即在手机当前页手动继续" in output
    assert "不必返回详情" in output
    assert "第 2 次尝试" not in output


def test_unknown_page_warning_appears_before_sale(monkeypatch, mobile_module, capsys):
    bot = waiting_bot(mobile_module, [page_xml(buy_label=""), KeyboardInterrupt()],
                      "2026-10-29 10:18:00")
    mock_clock(monkeypatch, mobile_module, [
        datetime(2026, 10, 29, 10, 17, 0, tzinfo=BEIJING),
    ])
    assert bot.run_with_retry(max_retries=3) is False
    assert "倒计时不表示已适配" in capsys.readouterr().out
    assert_no_actions(bot)
