"""预填购票流程：提前准备入口，到点点击，提交一次，付款留给用户。"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import time
from types import SimpleNamespace

if __package__:
    from .prefilled_pages import parse_prefilled_page
else:
    from prefilled_pages import parse_prefilled_page


BEIJING = timezone(timedelta(hours=8))
STATE_DIR = Path(__file__).resolve().parents[1] / "logs" / "prefilled"


class SystemClock:
    now = staticmethod(lambda: datetime.now(BEIJING))
    monotonic = staticmethod(time.monotonic)
    sleep = staticmethod(time.sleep)


class DeviceRunLock:
    """进程退出时由操作系统释放，阻止同一设备运行两个购票进程。"""

    def __init__(self, config, state_dir=None):
        device = config.udid or config.device_name
        digest = hashlib.sha256(device.encode("utf-8")).hexdigest()[:20]
        self.path = Path(state_dir or STATE_DIR) / f"device-{digest}.lock"
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        self.file.seek(0, 2)
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            self.file = None
            raise RuntimeError("这台手机已有一个抢票进程，请勿重复运行") from exc
        return self

    def __exit__(self, *args):
        if self.file is not None:
            try:
                self.file.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
            finally:
                self.file.close()


class PrefilledOrderFlow:
    def __init__(self, driver, config, *, clock=None, state_dir=None, diagnostics=None):
        self.driver = driver
        self.config = config
        self.clock = clock or SystemClock()
        self.diagnostics = diagnostics
        self.last_source = None
        self.submit_attempted = False
        self.target_verified = False
        self.screen_marker = None
        self.state_dir = Path(state_dir or STATE_DIR)
        identity = [config.udid, config.keyword, config.city, config.date, config.price,
                    config.users, config.sale_start_time]
        digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode("utf-8")).hexdigest()
        self.attempt_path = self.state_dir / f"submission-{digest}.json"

    def _page(self):
        self.last_source = self.driver.page_source
        # 此字段仅用于本次已经核验详情后的无标题 SKU，不写回用户配置。
        context = SimpleNamespace(**vars(self.config))
        context.target_verified = self.target_verified
        return parse_prefilled_page(self.last_source, context)

    def _click(self, bounds):
        x1, y1, x2, y2 = bounds
        self.driver.execute_script("mobile: clickGesture", {
            "x": (x1 + x2) // 2, "y": (y1 + y2) // 2,
        })

    def _checked_detail(self):
        for attempt in range(3):
            page = self._page()
            if page.stage == "detail" and page.entry_bounds and page.prefill_complete:
                self.target_verified = True
                return page
            # 系统浮层/页面重绘可使单次 XML 暂时为空；不能把一次空读数当作目标改变。
            if page.stage == "unknown" and attempt < 2:
                print("详情页短暂不可读，重新读取核验")
                self.clock.sleep(0.1)
                continue
            raise RuntimeError(f"开售前准备未通过：{page.reason}")

    def _wait_and_click_entry(self, sale_time):
        # 校验和坐标读取提前完成，最后两秒不再读取整页 XML。
        page = self._checked_detail()
        self._verify_foreground()
        deadline = self.clock.monotonic() + (sale_time - self.clock.now()).total_seconds()
        if deadline <= self.clock.monotonic():
            raise RuntimeError("开售时间已过，未自动点击；请修改为下一次实际开售时间")
        print(f"预填模式已就绪：{self.config.keyword} / {self.config.city}，{len(self.config.users)} 张")
        print(f"开售：{sale_time:%Y-%m-%d %H:%M:%S}（北京时间）；优先保留手机预填，未生效时按配置选档并核对实际票数")
        print("保持手机解锁并停在该详情页；按 Ctrl+C 停止")
        last_check = self.clock.monotonic()
        last_log = float("-inf")
        final_check_done = False
        while True:
            current = self.clock.monotonic()
            remaining = deadline - current
            if remaining <= 0:
                break
            if remaining > 2:
                if current - last_check >= 5:
                    self._verify_foreground()
                    last_check = self.clock.monotonic()
                if current - last_log >= 15:
                    print(f"已准备，距开售约 {max(1, int(remaining))} 秒")
                    last_log = current
                self.clock.sleep(min(1.0, max(0.001, remaining - 2)))
            elif not final_check_done:
                self._verify_foreground()
                final_check_done = True
            else:
                self.clock.sleep(min(0.02, remaining))
        sent_at = self.clock.monotonic()
        self._click(page.entry_bounds)
        print(f"购买点击已发出：本机计时偏差约 {max(0, sent_at - deadline) * 1000:.0f}ms（不含手机及网络响应）")
        return sent_at

    def _verify_foreground(self):
        """入口已经预先核验；待命只查前台及屏幕，不依赖可能短暂为空的 XML。"""
        if self.driver.is_locked():
            raise RuntimeError("手机已锁屏，已停止待命，未点击")
        if self.driver.current_package != "cn.damai":
            raise RuntimeError("大麦已离开前台，已停止待命，未点击")
        activity = self.driver.current_activity
        if not activity.endswith("ProjectDetailActivity"):
            raise RuntimeError("已离开演出详情页，已停止待命，未点击")
        size = self.driver.get_window_size()
        marker = (self.driver.orientation, size["width"], size["height"])
        if self.screen_marker is not None and marker != self.screen_marker:
            raise RuntimeError("屏幕方向或尺寸已改变，入口坐标失效，未点击")
        self.screen_marker = marker

    def _record_submission(self, page):
        if page.stage != "checkout" or not page.can_submit:
            raise RuntimeError("当前不是已核验的订单确认页，禁止记录或发送最终提交")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        # 先落盘再发送点击；点击超时或进程重启也不会再次提交同一目标。
        record = {"state": "submit_attempted", "at": self.clock.now().isoformat(),
                  "stage": page.stage, "action_control_id": page.action_control_id,
                  "action_label": page.action_label,
                  "action_bounds": page.action_bounds, "checks": page.checks}
        with self.attempt_path.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, ensure_ascii=False)
        self.submit_attempted = True

    def _configured_sku_option(self, page):
        match = re.search(r"\d+(?:\.\d{1,2})?", self.config.price.replace(",", ""))
        if not match:
            raise RuntimeError("配置票价无法读取，未选择票档")
        expected = Decimal(match.group())
        matches = [option for option in page.sku_options
                   if option.get("price") is not None and Decimal(option["price"]) == expected]
        if len(matches) == 1:
            option = matches[0]
        else:
            index = self.config.price_index
            if (not isinstance(index, int) or isinstance(index, bool)
                    or index < 0 or index >= len(page.sku_options)):
                raise RuntimeError("price_index 不在当前票档范围，未选择其它票价")
            option = page.sku_options[index]
            if option.get("price") is not None and Decimal(option["price"]) != expected:
                raise RuntimeError("price_index 对应票价与配置不一致，未选择其它票价")
        if option.get("unavailable"):
            raise RuntimeError("配置票档显示缺货或售罄，未改选其它价格")
        return option

    def _record_result(self, page):
        try:
            try:
                record = json.loads(self.attempt_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                record = {}
            record.update({"state": "locked_awaiting_payment", "result_at": self.clock.now().isoformat(),
                           "order_id_hint": (page.order_id or "")[-6:], "amount": page.amount})
            self.attempt_path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            print(f"订单结果记录未更新：{exc}")

    def run(self):
        try:
            sale_time = self.config.sale_start_datetime
            if sale_time is None:
                raise RuntimeError("预填模式必须填写 sale_start_time（北京时间开售时间）")
            if self.attempt_path.exists():
                raise RuntimeError("这个目标已有提交尝试记录；请先在大麦确认订单结果，不会重复提交")
            if self.clock.now() >= sale_time:
                raise RuntimeError("开售时间已过，未自动点击；请修改为下一次实际开售时间")
            first_click = self._wait_and_click_entry(sale_time)
            end = self.clock.monotonic() + self.config.order_flow_timeout
            entry_clicks = 1
            last_action = first_click
            sku_clicks = 0
            sku_selection_sent = False
            awaiting_quantity_change = None
            reservation_returns = 0
            last_reason = None
            while self.clock.monotonic() < end:
                page = self._page()
                now = self.clock.monotonic()
                if page.stage == "payment":
                    if self.submit_attempted and page.checks.get("locked"):
                        self._record_result(page)
                        print("已识别订单号和待支付状态，订单已锁定；请在手机完成支付")
                        return True
                    if self.submit_attempted:
                        if page.reason != last_reason:
                            print("已到支付相关页面，正在只读确认订单号；请在手机完成支付")
                            last_reason = page.reason
                        self.clock.sleep(0.1)
                        continue
                    print("已到支付相关页面，停止自动点击；请在手机核对订单并支付")
                    return False
                if page.stage == "verification":
                    if page.reason != last_reason:
                        print("大麦要求验证，请在手机完成；程序只等待，不自动操作验证")
                    # 用户完成平台验证后可以自动继续；不返回、不重建会话。
                    last_reason = page.reason
                    self.clock.sleep(0.2)
                    continue
                if self.submit_attempted:
                    # 提交后的任何状态都只观察结果，绝不重复提交或点击购买。
                    if page.stage == "sku" and now - last_action >= 2:
                        raise RuntimeError("提交尝试后回到选票页，订单结果尚未确认；已停止重复操作，请检查待支付订单")
                    if page.reason != last_reason:
                        print(f"提交已尝试，正在核对订单结果：{page.reason}")
                        last_reason = page.reason
                    self.clock.sleep(0.1)
                    continue
                if page.stage == "checkout" and page.can_submit and page.action_bounds:
                    if not self.config.if_commit_order:
                        print("已核对订单确认页；if_commit_order=false，未提交、尚未锁单")
                        return False
                    self._record_submission(page)
                    try:
                        self._click(page.action_bounds)
                        print("已发送提交订单，等待订单号及待支付结果；不会重复提交")
                    except Exception as exc:
                        print(f"提交点击结果不明，将只核对订单、不再点击：{exc}")
                    last_action = now
                    continue
                if page.stage == "sku" and page.checks.get("target") and sku_clicks < 1:
                    expected_quantity = len(self.config.users)
                    if expected_quantity <= 0:
                        raise RuntimeError("配置没有观演人，未确认选票")
                    if page.quantity is None:
                        if not sku_selection_sent and page.sku_options:
                            option = self._configured_sku_option(page)
                            self._click(option["bounds"])
                            sku_selection_sent = True
                            last_action = now
                            print("预填票档尚未生效，已按配置选择票档，等待数量控件")
                            continue
                        if sku_selection_sent and now - last_action > 3:
                            raise RuntimeError("选择配置票档后仍未读到实际数量，未点击确定")
                    elif page.quantity != expected_quantity:
                        if awaiting_quantity_change == page.quantity:
                            if now - last_action > 2:
                                raise RuntimeError("数量调整未得到页面确认，未继续加减或提交")
                        else:
                            bounds = (page.quantity_increase_bounds if page.quantity < expected_quantity
                                      else page.quantity_decrease_bounds)
                            if not bounds:
                                raise RuntimeError("实际票数与配置不一致且数量按钮不可用，未点击确定")
                            awaiting_quantity_change = page.quantity
                            self._click(bounds)
                            last_action = now
                            print(f"按实际数量调整：当前 {page.quantity} 张，目标 {expected_quantity} 张")
                            continue
                    elif page.action_bounds:
                        # 只有实际数量正确才确认；保留已匹配的预填，不重复加票或勾选姓名。
                        self._click(page.action_bounds)
                        sku_clicks += 1
                        last_action = now
                        print("选票数量已核对，已点击确定，等待订单确认页")
                        continue
                if page.stage == "reservation" and page.action_bounds and reservation_returns < 2:
                    self._click(page.action_bounds)
                    reservation_returns += 1
                    last_action = now
                    print("入口仍打开预约页，已返回详情等待正式购买；未修改预约")
                    continue
                if (page.stage == "detail" and page.entry_bounds and entry_clicks < 5
                        and now - first_click < 5 and now - last_action >= 0.3):
                    self._click(page.entry_bounds)
                    entry_clicks += 1
                    last_action = now
                    continue
                if page.stage == "sold_out":
                    print("页面显示缺货或售罄，未获得锁单结果")
                    return False
                if page.reason != last_reason:
                    print(f"正在识别后续页面：{page.reason}")
                    last_reason = page.reason
                self.clock.sleep(0.1)
            if self.submit_attempted:
                raise RuntimeError("提交后未取得可确认的订单结果；请查看手机待支付订单，程序不会重复提交")
            raise RuntimeError("购票页面处理超时，尚未取得锁单结果；已保存页面摘要以便适配")
        except KeyboardInterrupt:
            print("已手动停止；如已提交，请在手机确认待支付订单")
            return False
        except Exception as exc:
            print(f"预填购票流程停止：{exc}")
            if self.last_source and self.diagnostics:
                try:
                    self.diagnostics(self.last_source, str(exc))
                except Exception:
                    pass
            return False
