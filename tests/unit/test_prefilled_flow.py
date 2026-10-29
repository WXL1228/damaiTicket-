"""Exercise the timed flow without Appium, a device, or wall-clock sleeps."""

from datetime import datetime, timedelta
import json
from unittest.mock import Mock, call

import pytest

from damai_appium.config import Config
from damai_appium import prefilled_flow
from damai_appium.prefilled_flow import BEIJING, DeviceRunLock, PrefilledOrderFlow
from damai_appium.prefilled_pages import Page


class FakeClock:
    def __init__(self):
        self.start = datetime(2026, 10, 29, 9, 0, tzinfo=BEIJING)
        self.elapsed = 0.0

    def now(self):
        return self.start + timedelta(seconds=self.elapsed)

    def monotonic(self):
        return self.elapsed

    def sleep(self, seconds):
        assert seconds >= 0
        self.elapsed += seconds


class FakeDriver:
    def __init__(self, clock):
        self.clock = clock
        self.read_times = []
        self.click_times = []
        self.execute_script = Mock(side_effect=self._execute)
        self.is_locked = Mock(return_value=False)
        self.current_package = "cn.damai"
        self.current_activity = ".trade.newtradeorder.ui.projectdetail.ui.activity.ProjectDetailActivity"
        self.orientation = "PORTRAIT"
        self.get_window_size = Mock(return_value={"width": 1200, "height": 2670})

    @property
    def page_source(self):
        self.read_times.append(self.clock.monotonic())
        return "<hierarchy />"

    def _execute(self, *args):
        self.click_times.append(self.clock.monotonic())


def make_config(clock, **overrides):
    values = dict(
        server_url="http://127.0.0.1:4723", keyword="示例演出", city="北京",
        users=["测试甲", "测试乙"], date="2026-11-28 周六 19:00",
        price="看台399元", price_index=0, if_commit_order=True,
        udid="unit-test-device", prefilled_mode=True,
        sale_start_time=(clock.now() + timedelta(seconds=10)).strftime("%Y-%m-%d %H:%M:%S"),
        order_flow_timeout=60,
    )
    values.update(overrides)
    return Config(**values)


def detail():
    return Page("detail", "预填已核验", title="北京·示例演出",
                entry_bounds=(10, 90, 110, 190), prefill_complete=True)


def checkout():
    return Page("checkout", "订单核验通过", action_bounds=(200, 400, 400, 500),
                can_submit=True, action_control_id="cn.damai:id/submit_order",
                checks={"target": True, "date": True, "price": True, "quantity": True,
                        "viewers": True, "amount": True, "submit_button": True})


def sku_page(quantity=2, *, options=None, increase=(800, 200, 900, 300),
             decrease=(600, 200, 700, 300)):
    return Page("sku", "已识别预填选票", action_bounds=(0, 200, 100, 300),
                action_control_id="cn.damai:id/btn_buy_view", quantity=quantity,
                sku_options=options or [], quantity_increase_bounds=increase,
                quantity_decrease_bounds=decrease, checks={"target": True})


def option(bounds, price=None, unavailable=False):
    return {"bounds": bounds, "price": price, "unavailable": unavailable}


def payment():
    return Page("payment", "订单待支付", order_id="202610290123456789",
                amount="798", checks={"locked": True})


def setup_flow(monkeypatch, tmp_path, pages, **overrides):
    clock = FakeClock()
    config = make_config(clock, **overrides)
    driver = FakeDriver(clock)
    diagnostics = Mock()
    queue = list(pages)

    def parse(source, context):
        assert source == "<hierarchy />"
        if clock.now() < config.sale_start_datetime:
            return detail()
        return queue.pop(0) if len(queue) > 1 else queue[0]

    parser = Mock(side_effect=parse)
    monkeypatch.setattr(prefilled_flow, "parse_prefilled_page", parser)
    flow = PrefilledOrderFlow(driver, config, clock=clock, state_dir=tmp_path,
                             diagnostics=diagnostics)
    return flow, driver, clock, parser, diagnostics


def assert_clicks(driver, *centres):
    assert driver.execute_script.call_args_list == [
        call("mobile: clickGesture", {"x": x, "y": y}) for x, y in centres
    ]


def test_single_empty_preflight_read_is_retried_without_any_click(monkeypatch, tmp_path):
    flow, driver, _, _, _ = setup_flow(monkeypatch, tmp_path, [checkout(), payment()])
    flow._page = Mock(side_effect=[Page("unknown", "empty snapshot"), detail()])
    assert flow._checked_detail().entry_bounds == detail().entry_bounds
    assert flow._page.call_count == 2
    driver.execute_script.assert_not_called()


def test_persistently_unknown_preflight_is_bounded_and_never_clicked(monkeypatch, tmp_path):
    flow, driver, _, _, _ = setup_flow(monkeypatch, tmp_path, [checkout(), payment()])
    flow._page = Mock(return_value=Page("unknown", "empty snapshot"))
    with pytest.raises(RuntimeError, match="开售前准备未通过"):
        flow._checked_detail()
    assert flow._page.call_count == 3
    driver.execute_script.assert_not_called()


def test_warmed_entry_click_is_at_deadline_and_last_two_seconds_have_no_xml_reads(monkeypatch, tmp_path):
    flow, driver, clock, _, _ = setup_flow(monkeypatch, tmp_path, [checkout(), payment()])

    assert flow.run() is True

    assert driver.click_times == pytest.approx([10, 10])
    assert min(driver.click_times) >= 10
    assert all(not 8 < when < 10 for when in driver.read_times)
    assert max(when for when in driver.read_times if when < 10) == pytest.approx(0)
    assert_clicks(driver, (60, 140), (300, 450))
    assert clock.now() >= flow.config.sale_start_datetime


def test_prefill_is_kept_and_payment_is_never_clicked(monkeypatch, tmp_path):
    flow, driver, _, _, diagnostics = setup_flow(monkeypatch, tmp_path, [checkout(), payment()])

    assert flow.run() is True

    assert_clicks(driver, (60, 140), (300, 450))
    diagnostics.assert_not_called()
    record = json.loads(flow.attempt_path.read_text(encoding="utf-8"))
    assert record["state"] == "locked_awaiting_payment"
    assert record["order_id_hint"] == "456789"
    # State persistence contains no cleartext viewer names or full order identifier.
    stored = flow.attempt_path.read_text(encoding="utf-8") + flow.attempt_path.name
    assert all(viewer not in stored for viewer in flow.config.users)
    assert payment().order_id not in stored


def test_existing_prefilled_sku_is_confirmed_once_without_touching_quantity_or_viewers(monkeypatch, tmp_path):
    sku = sku_page()
    flow, driver, _, _, _ = setup_flow(monkeypatch, tmp_path, [sku, sku, checkout(), payment()])

    assert flow.run() is True

    assert_clicks(driver, (60, 140), (50, 250), (300, 450))


def test_submission_disabled_stops_at_review_without_locking_order(monkeypatch, tmp_path, capsys):
    flow, driver, _, _, _ = setup_flow(monkeypatch, tmp_path, [checkout()], if_commit_order=False)

    assert flow.run() is False

    assert_clicks(driver, (60, 140))
    assert not flow.submit_attempted
    assert not flow.attempt_path.exists()
    assert "尚未锁单" in capsys.readouterr().out


def test_uncertain_submission_does_not_repeat_and_can_observe_locked_result(monkeypatch, tmp_path):
    flow, driver, _, _, _ = setup_flow(monkeypatch, tmp_path, [checkout(), checkout(), payment()])

    def click_then_timeout(*args):
        driver.click_times.append(driver.clock.monotonic())
        if len(driver.click_times) == 2:
            raise TimeoutError("response lost after the device accepted the tap")

    driver.execute_script.side_effect = click_then_timeout

    assert flow.run() is True

    assert driver.execute_script.call_count == 2
    assert json.loads(flow.attempt_path.read_text(encoding="utf-8"))["state"] == "locked_awaiting_payment"


def test_submit_timeout_retains_attempt_record_and_never_reclicks(monkeypatch, tmp_path, capsys):
    flow, driver, _, _, diagnostics = setup_flow(
        monkeypatch, tmp_path, [checkout()], order_flow_timeout=1)

    def click_then_timeout(*args):
        driver.click_times.append(driver.clock.monotonic())
        if len(driver.click_times) == 2:
            raise TimeoutError("submission response is unknown")

    driver.execute_script.side_effect = click_then_timeout

    assert flow.run() is False

    assert driver.execute_script.call_count == 2
    assert json.loads(flow.attempt_path.read_text(encoding="utf-8"))["state"] == "submit_attempted"
    diagnostics.assert_called_once()
    assert "请查看手机待支付订单" in capsys.readouterr().out


def test_restart_with_attempt_record_never_reads_or_clicks_device(monkeypatch, tmp_path, capsys):
    flow, driver, _, _, _ = setup_flow(monkeypatch, tmp_path, [checkout(), payment()])
    flow._record_submission(checkout())
    restarted = PrefilledOrderFlow(driver, flow.config, clock=FakeClock(), state_dir=tmp_path)

    assert restarted.run() is False

    assert driver.read_times == []
    driver.execute_script.assert_not_called()
    assert "已有提交尝试记录" in capsys.readouterr().out


@pytest.mark.parametrize("offset", [0, -1, -3600])
def test_past_or_current_sale_time_never_clicks(monkeypatch, tmp_path, offset):
    clock = FakeClock()
    sale_time = (clock.now() + timedelta(seconds=offset)).strftime("%Y-%m-%d %H:%M:%S")
    flow, driver, _, parser, _ = setup_flow(monkeypatch, tmp_path, [checkout()], sale_start_time=sale_time)

    assert flow.run() is False

    driver.execute_script.assert_not_called()
    parser.assert_not_called()


def test_unknown_page_times_out_once_without_restarting_purchase(monkeypatch, tmp_path, capsys):
    flow, driver, clock, _, diagnostics = setup_flow(monkeypatch, tmp_path, [Page("unknown", "未识别页面")])

    assert flow.run() is False

    assert_clicks(driver, (60, 140))
    assert clock.monotonic() == pytest.approx(70, abs=0.11)
    diagnostics.assert_called_once()
    assert "购票页面处理超时" in capsys.readouterr().out
    assert not flow.attempt_path.exists()


def test_platform_verification_never_receives_a_click(monkeypatch, tmp_path, capsys):
    verification = Page("verification", "安全验证", action_bounds=(100, 100, 200, 200))
    flow, driver, _, _, _ = setup_flow(monkeypatch, tmp_path, [verification])

    assert flow.run() is False

    assert_clicks(driver, (60, 140))
    assert "程序只等待" in capsys.readouterr().out


def test_after_user_completes_verification_flow_can_continue(monkeypatch, tmp_path):
    verification = Page("verification", "安全验证")
    flow, driver, _, _, _ = setup_flow(monkeypatch, tmp_path, [verification, checkout(), payment()])

    assert flow.run() is True

    assert_clicks(driver, (60, 140), (300, 450))


def test_unverified_confirmation_page_never_submits(monkeypatch, tmp_path):
    incomplete = Page("checkout", "观演人不匹配", action_bounds=(200, 400, 400, 500), can_submit=False)
    flow, driver, _, _, _ = setup_flow(monkeypatch, tmp_path, [incomplete], order_flow_timeout=1)

    assert flow.run() is False

    assert_clicks(driver, (60, 140))
    assert not flow.attempt_path.exists()


def test_device_lock_excludes_duplicate_process_and_is_reusable_after_release(tmp_path):
    config = make_config(FakeClock())

    with DeviceRunLock(config, state_dir=tmp_path):
        with pytest.raises(RuntimeError, match="已有一个抢票进程"):
            with DeviceRunLock(config, state_dir=tmp_path):
                pytest.fail("a second flow acquired the same device")

    with DeviceRunLock(config, state_dir=tmp_path):
        pass


def test_device_lock_allows_distinct_devices(tmp_path):
    clock = FakeClock()
    with DeviceRunLock(make_config(clock, udid="device-one"), state_dir=tmp_path):
        with DeviceRunLock(make_config(clock, udid="device-two"), state_dir=tmp_path):
            pass


def test_unselected_sku_selects_configured_tier_adjusts_actual_quantity_then_confirms(monkeypatch, tmp_path):
    options = [option((0, 500, 200, 600), "399"), option((220, 500, 420, 600), "1088")]
    flow, driver, _, _, _ = setup_flow(
        monkeypatch, tmp_path, [sku_page(None, options=options), sku_page(1), sku_page(2),
                                checkout(), payment()])

    assert flow.run() is True

    assert_clicks(driver, (60, 140), (100, 550), (850, 250), (50, 250), (300, 450))
    assert driver.execute_script.call_args_list.count(call("mobile: clickGesture", {"x": 850, "y": 250})) == 1


@pytest.mark.parametrize("actual,users,adjustment", [
    (2, ["测试甲", "测试乙", "测试丙"], (850, 250)),
    (3, ["测试甲", "测试乙"], (650, 250)),
])
def test_quantity_changes_by_actual_difference_and_can_decrease(monkeypatch, tmp_path, actual, users, adjustment):
    flow, driver, _, _, _ = setup_flow(
        monkeypatch, tmp_path, [sku_page(actual), sku_page(len(users)), checkout(), payment()], users=users)

    assert flow.run() is True

    assert_clicks(driver, (60, 140), adjustment, (50, 250), (300, 450))


def test_configured_sold_out_tier_is_not_replaced_with_available_expensive_tier(monkeypatch, tmp_path, capsys):
    options = [option((0, 500, 200, 600), unavailable=True),
               option((220, 500, 420, 600), "1088")]
    flow, driver, _, _, _ = setup_flow(monkeypatch, tmp_path, [sku_page(None, options=options)])

    assert flow.run() is False

    assert_clicks(driver, (60, 140))
    assert not flow.attempt_path.exists()
    assert "未改选其它价格" in capsys.readouterr().out


def test_explicit_target_price_wins_over_stale_configured_index(monkeypatch, tmp_path):
    options = [option((0, 500, 200, 600), "1088"), option((220, 500, 420, 600), "399")]
    flow, driver, _, _, _ = setup_flow(
        monkeypatch, tmp_path, [sku_page(None, options=options), sku_page(2), checkout(), payment()], price_index=0)

    assert flow.run() is True

    assert_clicks(driver, (60, 140), (320, 550), (50, 250), (300, 450))


def test_explicit_price_mismatch_at_index_blocks_selecting_another_price(monkeypatch, tmp_path, capsys):
    options = [option((0, 500, 200, 600), "588"), option((220, 500, 420, 600), "1088")]
    flow, driver, _, _, _ = setup_flow(monkeypatch, tmp_path, [sku_page(None, options=options)])

    assert flow.run() is False

    assert_clicks(driver, (60, 140))
    assert not flow.attempt_path.exists()
    assert "对应票价与配置不一致" in capsys.readouterr().out


def test_quantity_without_visible_change_is_not_clicked_repeatedly(monkeypatch, tmp_path, capsys):
    flow, driver, clock, _, diagnostics = setup_flow(monkeypatch, tmp_path, [sku_page(1)])

    assert flow.run() is False

    assert_clicks(driver, (60, 140), (850, 250))
    assert clock.monotonic() == pytest.approx(12, abs=0.11)
    assert not flow.attempt_path.exists()
    diagnostics.assert_called_once()
    assert "数量调整未得到页面确认" in capsys.readouterr().out


def test_tier_selection_without_quantity_echo_is_sent_only_once(monkeypatch, tmp_path, capsys):
    page = sku_page(None, options=[option((0, 500, 200, 600), "399")])
    flow, driver, _, _, _ = setup_flow(monkeypatch, tmp_path, [page])

    assert flow.run() is False

    assert_clicks(driver, (60, 140), (100, 550))
    assert not flow.attempt_path.exists()
    assert "仍未读到实际数量" in capsys.readouterr().out


def test_sku_confirmation_never_creates_final_submission_record(monkeypatch, tmp_path):
    flow, driver, _, _, _ = setup_flow(
        monkeypatch, tmp_path, [sku_page(2), Page("unknown", "页面切换中")], order_flow_timeout=1)

    assert flow.run() is False

    assert_clicks(driver, (60, 140), (50, 250))
    assert flow.submit_attempted is False
    assert not flow.attempt_path.exists()


@pytest.mark.parametrize("page", [sku_page(), Page("checkout", "未核验", can_submit=False)])
def test_only_checked_checkout_can_write_submission_record(monkeypatch, tmp_path, page):
    flow, driver, _, _, _ = setup_flow(monkeypatch, tmp_path, [page])

    with pytest.raises(RuntimeError, match="不是已核验的订单确认页"):
        flow._record_submission(page)

    assert not flow.attempt_path.exists()
    assert flow.submit_attempted is False
    driver.execute_script.assert_not_called()


def test_final_submission_record_contains_classified_stage_control_and_checks(monkeypatch, tmp_path):
    page = checkout()
    flow, _, _, _, _ = setup_flow(monkeypatch, tmp_path, [page], order_flow_timeout=1)

    assert flow.run() is False

    record = json.loads(flow.attempt_path.read_text(encoding="utf-8"))
    assert record["state"] == "submit_attempted"
    assert record["stage"] == "checkout"
    assert record["action_control_id"] == page.action_control_id
    assert record["action_bounds"] == list(page.action_bounds)
    assert record["checks"] == page.checks
    assert all(viewer not in json.dumps(record, ensure_ascii=False) for viewer in flow.config.users)


def test_after_submission_return_to_sku_never_reconfirms_or_submits(monkeypatch, tmp_path, capsys):
    flow, driver, clock, _, _ = setup_flow(monkeypatch, tmp_path, [checkout(), sku_page(2)])

    assert flow.run() is False

    assert_clicks(driver, (60, 140), (300, 450))
    assert clock.monotonic() == pytest.approx(12, abs=0.11)
    assert json.loads(flow.attempt_path.read_text(encoding="utf-8"))["state"] == "submit_attempted"
    assert "提交尝试后回到选票页" in capsys.readouterr().out
