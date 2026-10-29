# -*- coding: UTF-8 -*-
"""
__Author__ = "BlueCestbon"
__Version__ = "2.0.0"
__Description__ = "大麦app抢票自动化 - 优化版"
__Created__ = 2025/09/13 19:27
"""

import time
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from appium import webdriver
from appium.options.common.base import AppiumOptions
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

if __package__:
    from .config import Config
    from .sale_wait import inspect_sale_page
    from .page_diagnostics import summarize_page
else:
    from config import Config
    from sale_wait import inspect_sale_page
    from page_diagnostics import summarize_page


class ManualTakeoverRequired(RuntimeError):
    """页面适配不足时停止自动动作，交由用户在当前页继续。"""


class DamaiBot:
    def __init__(self, config=None):
        self.config = config or Config.load_config()
        self.driver = None
        self.wait = None
        self._reservation_page_detected = False
        self._wait_failed = False
        self._cancelled = False
        self._setup_driver()

    def _setup_driver(self):
        """初始化驱动配置"""
        capabilities = {
            "platformName": "Android",  # 操作系统
            "deviceName": self.config.device_name,  # 设备名称
            "appPackage": "cn.damai",  # app 包名
            "appActivity": ".launcher.splash.SplashMainActivity",  # app 启动 Activity
            "noReset": True,  # 不重置 app
            "autoLaunch": False,  # 保留用户已打开的目标页面
            "newCommandTimeout": 6000,  # 超时时间
            "automationName": "UiAutomator2",  # 使用 uiautomator2
            "skipServerInstallation": False,  # 跳过服务器安装
            "ignoreHiddenApiPolicyError": True,  # 忽略隐藏 API 策略错误
            # 当前 Settings helper 的 location 前台服务在 Android 16 缺少定位权限时会崩溃。
            # V2 仅查询元素和原生点击，不需要 helper；由用户保持手机解锁。
            "skipDeviceInitialization": True,
            "skipUnlock": True,
            "mockLocationApp": "",  # 不将 Settings helper 配置为模拟定位提供者
            # 优化性能配置
            "mjpegServerFramerate": 1,  # 降低截图帧率
            "shouldTerminateApp": False,
            "adbExecTimeout": 20000,
        }
        if self.config.platform_version:
            capabilities["platformVersion"] = str(self.config.platform_version)
        if self.config.udid:
            capabilities["udid"] = self.config.udid

        device_app_info = AppiumOptions()
        device_app_info.load_capabilities(capabilities)
        self.driver = webdriver.Remote(self.config.server_url, options=device_app_info)

        # 更激进的性能优化设置
        try:
            self._configure_driver_settings()
        except BaseException:
            # 驱动已建立但初始化失败或被 Ctrl+C 中断时，也释放会话。
            try:
                self.driver.quit()
            except Exception:
                pass
            raise

        # 极短的显式等待，抢票场景下速度优先
        self.wait = WebDriverWait(self.driver, 2)  # 从5秒减少到2秒

    def _configure_driver_settings(self):
        self.driver.update_settings({
            "waitForIdleTimeout": 0,  # 空闲时间，0 表示不等待，让 UIAutomator2 不等页面“空闲”再返回
            "actionAcknowledgmentTimeout": 0,  # 禁止等待动作确认
            "keyInjectionDelay": 0,  # 禁止输入延迟
            "waitForSelectorTimeout": 300,  # 从500减少到300ms
            "ignoreUnimportantViews": False,  # 保持false避免元素丢失
            "allowInvisibleElements": True,
            "enableNotificationListener": False,  # 禁用通知监听
        })

    def ultra_fast_click(self, by, value, timeout=1.5):
        """超快速点击 - 适合抢票场景"""
        try:
            # 直接查找并点击，不等待可点击状态
            el = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
            # 使用坐标点击更快
            rect = el.rect
            x = rect['x'] + rect['width'] // 2
            y = rect['y'] + rect['height'] // 2
            self.driver.execute_script("mobile: clickGesture", {
                "x": x,
                "y": y,
                "duration": 50  # 极短点击时间
            })
            return True
        except TimeoutException:
            return False

    def batch_click(self, elements_info, delay=0.1):
        """批量点击操作"""
        for by, value in elements_info:
            if self.ultra_fast_click(by, value):
                if delay > 0:
                    time.sleep(delay)
            else:
                print(f"点击失败: {value}")

    def ultra_batch_click(self, elements_info, timeout=2):
        """超快批量点击 - 带等待机制"""
        coordinates = []
        # 批量收集坐标，带超时等待
        for by, value in elements_info:
            try:
                # 等待元素出现
                el = WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located((by, value))
                )
                rect = el.rect
                x = rect['x'] + rect['width'] // 2
                y = rect['y'] + rect['height'] // 2
                coordinates.append((x, y, value))
            except TimeoutException:
                print(f"超时未找到用户: {value}")
            except Exception as e:
                print(f"查找用户失败 {value}: {e}")
        print(f"成功找到 {len(coordinates)} 个用户")
        # 快速连续点击
        for i, (x, y, value) in enumerate(coordinates):
            self.driver.execute_script("mobile: clickGesture", {
                "x": x,
                "y": y,
                "duration": 30
            })
            if i < len(coordinates) - 1:
                time.sleep(0.01)
            print(f"点击用户: {value}")

    def smart_wait_and_click(self, by, value, backup_selectors=None, timeout=1.5):
        """智能等待和点击 - 支持备用选择器"""
        selectors = [(by, value)]
        if backup_selectors:
            selectors.extend(backup_selectors)

        for selector_by, selector_value in selectors:
            try:
                el = WebDriverWait(self.driver, timeout).until(
                    EC.element_to_be_clickable((selector_by, selector_value))
                )
                rect = el.rect
                x = rect['x'] + rect['width'] // 2
                y = rect['y'] + rect['height'] // 2
                self.driver.execute_script("mobile: clickGesture", {"x": x, "y": y, "duration": 50})
                return True
            except TimeoutException:
                continue
        return False

    def _stop_on_reservation_page(self):
        """只读识别已观测的预约 SKU 标题，避免改动预约选项。"""
        for label in ("预约想看场次", "预约想看票档"):
            if self.driver.find_elements(
                    AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().text("{label}")'):
                self._reservation_page_detected = True
                print("当前为预约页，请回到演出详情页等待开售；本次停止操作")
                return True
        return False

    def _wait_for_sale(self):
        """保持当前会话，只读观察页面；不刷新、不操作预约。Ctrl+C 可退出。"""
        self._wait_failed = True
        sale_time = self.config.sale_start_datetime
        if sale_time:
            print(f"开售时间：{sale_time:%Y-%m-%d %H:%M:%S}（北京时间）")
        print("提前待命中，按 Ctrl+C 停止；请保持手机解锁、大麦在前台")
        last_message = None
        last_log = float("-inf")
        warned_before_sale = False
        warned_after_sale = False
        while True:
            # 即使开售时间还没到也持续查询，避免长时间无命令导致会话过期。
            source = self.driver.page_source
            stage, message = inspect_sale_page(source, self.config.keyword, self.config.city)
            now = datetime.now(timezone(timedelta(hours=8)))
            if sale_time and now < sale_time:
                if stage is None and not warned_before_sale:
                    print("自动流程尚未就绪；倒计时不表示已适配，开售时请直接手动操作，不要等终端放行")
                    warned_before_sale = True
                remaining = max(1, int((sale_time - now).total_seconds()))
                message = f"距开售约 {remaining} 秒；{message}"
            elif stage in {"detail", "sku"}:
                self._wait_failed = False
                print(f"{message}，开始购票流程")
                return stage
            elif sale_time:
                if not warned_after_sale:
                    print("开售时间已到，但自动入口仍未识别；请立即在手机当前页手动继续，不要等待本程序")
                    warned_after_sale = True
                if now >= sale_time + timedelta(seconds=3):
                    self._save_page_diagnostics(source, message)
                    raise ManualTakeoverRequired(
                        "开售后仍无法识别页面，自动操作已停止；请在手机当前页手动继续，不必返回详情")
                message = f"已到开售时间；{message}"
            monotonic_now = time.monotonic()
            # 倒计时不逐秒刷屏，页面状态变化则立即提示。
            state = message.split("；", 1)[-1] if sale_time and now < sale_time else message
            if state != last_message or monotonic_now - last_log >= 15:
                print(message)
                last_message, last_log = state, monotonic_now
            time.sleep(self.config.wait_poll_interval)

    def _save_page_diagnostics(self, source, reason):
        """仅保存受限控件摘要，不保存原始 XML、截图或观演人字段。"""
        summary = summarize_page(source, self.config.keyword, self.config.city)
        summary["checked_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat()
        summary["reason"] = reason
        diagnostic_path = Path(__file__).resolve().parents[1] / "logs" / "mobile-page-check.json"
        try:
            diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
            diagnostic_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"页面检查摘要已保存：{diagnostic_path}")
        except OSError as e:
            print(f"无法保存页面检查摘要：{e}")
        return summary

    def check_current_page(self):
        """独立的只读检查入口，绝不进入购买或等待流程。"""
        try:
            source = self.driver.page_source
            if self.config.prefilled_mode:
                if __package__:
                    from .prefilled_pages import parse_prefilled_page
                else:
                    from prefilled_pages import parse_prefilled_page
                page = parse_prefilled_page(source, self.config)
                ready = page.stage == "detail" and bool(page.entry_bounds) and page.prefill_complete
                stage, reason = ("detail" if ready else None), page.reason
                if ready:
                    print(f"预填模式入口已核验，坐标范围：{page.entry_bounds}；本次不点击")
            else:
                stage, reason = inspect_sale_page(source, self.config.keyword, self.config.city)
            print("只读页面检查：不会点击或执行购票")
            print(f"配置目标：{self.config.keyword} / {self.config.city}")
            print(f"识别结果：{stage or '未适配/暂不可用'}；{reason}")
            summary = self._save_page_diagnostics(source, reason)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return stage in {"detail", "sku"}
        finally:
            try:
                self.driver.quit()
            except Exception as e:
                print(f"关闭连接时发生错误: {e}")

    def run_prefilled_order(self):
        if __package__:
            from .prefilled_flow import PrefilledOrderFlow
        else:
            from prefilled_flow import PrefilledOrderFlow
        try:
            return PrefilledOrderFlow(self.driver, self.config,
                                      diagnostics=self._save_page_diagnostics).run()
        finally:
            try:
                self.driver.quit()
            except Exception as e:
                print(f"关闭连接时发生错误: {e}")

    def run_ticket_grabbing(self):
        """执行抢票主流程"""
        self._reservation_page_detected = False
        try:
            ready_stage = self._wait_for_sale()
            print("开始抢票流程...")
            start_time = time.time()

            # 已观测的预约 SKU 页不能按正式购票流程处理，先只读识别，避免误点取消预约。
            if self._stop_on_reservation_page():
                return False

            # 待命已核验用户所在演出，不再切换城市，避免改变目标和购买状态。
            if ready_stage == "detail":
                print("点击购买按钮...")
                # 再定位明确标签，避免状态变化后仍按预约/购买共用的容器 ID 点击。
                labels = ("立即购买", "立即预订", "立即抢票", "选座购买")
                predicate = " or ".join(
                    f'@text="{label}" or @content-desc="{label}"' for label in labels)
                bar = '//*[@resource-id="cn.damai:id/trade_project_detail_purchase_status_bar_container_fl"]'
                purchase_xpath = f'{bar}[{predicate}] | {bar}//*[{predicate}]'
                if not self.smart_wait_and_click(By.XPATH, purchase_xpath):
                    print("购买按钮点击失败")
                    return False

            # 详情页的同一入口也可能打开预约 SKU；选票前再次核验。
            if self._stop_on_reservation_page():
                return False

            # 3. 票价选择 - 优化查找逻辑
            print("选择票价...")
            try:
                # 直接尝试点击，不等待容器，实际每次都失败，只能等待
                price_container = self.driver.find_element(By.ID, 'cn.damai:id/project_detail_perform_price_flowlayout')
                if self._stop_on_reservation_page():
                    return False
                # price_container = self.wait.until(  # 等待找到容器
                #     EC.presence_of_element_located((By.ID, 'cn.damai:id/project_detail_perform_price_flowlayout')))
                # 在容器内找 index=1 且 clickable="true" 的 FrameLayout【因为799元的票价是排在第二的，但是page里text是空的被隐藏了】
                target_price = price_container.find_element(
                    AppiumBy.ANDROID_UIAUTOMATOR,
                    f'new UiSelector().className("android.widget.FrameLayout").index({self.config.price_index}).clickable(true)'
                )
                self.driver.execute_script('mobile: clickGesture', {'elementId': target_price.id})
            except Exception as e:
                print(f"票价选择失败，启动备用方案: {e}")
                # 备用方案
                # 先找到大容器
                price_container = self.wait.until(
                    EC.presence_of_element_located((By.ID, 'cn.damai:id/project_detail_perform_price_flowlayout')))
                # 入口跳转可能异步完成，等待容器之后再次核验，避免落入预约 SKU。
                if self._stop_on_reservation_page():
                    return False
                # 在容器内找 index=1 且 clickable="true" 的 FrameLayout【因为799元的票价是排在第二的，但是page里text是空的被隐藏了】
                target_price = price_container.find_element(
                    AppiumBy.ANDROID_UIAUTOMATOR,
                    f'new UiSelector().className("android.widget.FrameLayout").index({self.config.price_index}).clickable(true)'
                )
                self.driver.execute_script('mobile: clickGesture', {'elementId': target_price.id})

                # if not self.ultra_fast_click(AppiumBy.ANDROID_UIAUTOMATOR,
                #                              'new UiSelector().textMatches(".*799.*|.*\\d+元.*")'):
                #     return False

            # 4. 数量选择
            print("选择数量...")
            if self.driver.find_elements(by=By.ID, value='layout_num'):
                clicks_needed = len(self.config.users) - 1
                if clicks_needed > 0:
                    try:
                        plus_button = self.driver.find_element(By.ID, 'img_jia')
                        for i in range(clicks_needed):
                            rect = plus_button.rect
                            x = rect['x'] + rect['width'] // 2
                            y = rect['y'] + rect['height'] // 2
                            self.driver.execute_script("mobile: clickGesture", {
                                "x": x,
                                "y": y,
                                "duration": 50
                            })
                            time.sleep(0.02)
                    except Exception as e:
                        print(f"快速点击加号失败: {e}")

            # if self.driver.find_elements(by=By.ID, value='layout_num') and self.config.users is not None:
            #     for i in range(len(self.config.users) - 1):
            #         self.driver.find_element(by=By.ID, value='img_jia').click()

            # 5. 确定购买
            print("确定购买...")
            if not self.ultra_fast_click(By.ID, "btn_buy_view"):
                # 备用按钮文本
                self.ultra_fast_click(AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textMatches(".*确定.*|.*购买.*")')

            # 6. 批量选择用户
            print("选择用户...")
            user_clicks = [(AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().text("{user}")') for user in
                           self.config.users]
            # self.batch_click(user_clicks, delay=0.05)  # 极短延迟
            self.ultra_batch_click(user_clicks)

            # 7. 提交订单
            if self.config.if_commit_order:
                print("提交订单...")
                submit_selectors = [
                    (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().text("立即提交")'),
                    (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textMatches(".*提交.*|.*确认.*")'),
                    (By.XPATH, '//*[contains(@text,"提交")]')
                ]
                if not self.smart_wait_and_click(*submit_selectors[0], submit_selectors[1:]):
                    print("提交按钮点击失败")
                    return False
                print("已点击提交按钮，请在大麦 APP 中确认订单结果")
            else:
                print("if_commit_order=false，已跳过提交订单")

            end_time = time.time()
            print(f"抢票流程完成，耗时: {end_time - start_time:.2f}秒")
            return True

        except ManualTakeoverRequired as e:
            print(e)
            return False
        except KeyboardInterrupt:
            self._cancelled = True
            print("已手动停止待命/购票流程")
            return False
        except Exception as e:
            print(f"抢票过程发生错误: {e}")
            if self._wait_failed:
                print("待命连接或页面读取失败，已停止；请检查手机及 Appium 后手动重启")
            return False
        finally:
            try:
                self.driver.quit()
            except Exception as e:
                print(f"关闭连接时发生错误: {e}")

    def run_with_retry(self, max_retries=3):
        """带重试机制的抢票"""
        for attempt in range(max_retries):
            print(f"第 {attempt + 1} 次尝试...")
            if self.run_ticket_grabbing():
                print("流程执行完成")
                return True
            elif (self._reservation_page_detected or self._wait_failed
                  or getattr(self, "_cancelled", False)):
                return False
            else:
                print(f"第 {attempt + 1} 次尝试失败")
                if attempt < max_retries - 1:
                    print("2秒后重试...")
                    time.sleep(2)
                    # 本次连接已在 finally 关闭，重新初始化驱动。
                    self._setup_driver()

        print("所有尝试均失败")
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description="大麦 Android 页面检查和购票辅助")
    parser.add_argument("--check-page", action="store_true", help="只读检查当前页面，不点击、不等待开售、不购票")
    args = parser.parse_args(argv)
    try:
        config = Config.load_config()
        if __package__:
            from .prefilled_flow import DeviceRunLock
        else:
            from prefilled_flow import DeviceRunLock
        # 只读检查也不能在活跃购票进程旁另建 UiAutomator2 会话。
        with DeviceRunLock(config):
            bot = DamaiBot(config=config)
            if args.check_page:
                return bot.check_current_page()
            if config.prefilled_mode:
                return bot.run_prefilled_order()
            return bot.run_with_retry(max_retries=30)
    except KeyboardInterrupt:
        print("已手动停止")
        return False
    except RuntimeError as e:
        print(e)
        return False


if __name__ == "__main__":
    main()
