# -*- coding: UTF-8 -*-
"""
__Author__ = "WECENG"
__Version__ = "1.0.0"
__Description__ = "配置类"
__Created__ = 2023/10/27 09:54
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


class Config:
    def __init__(self, server_url, keyword, users, city, date, price, price_index, if_commit_order,
                 device_name="Android", platform_version=None, udid=None,
                 sale_start_time=None, wait_poll_interval=0.5,
                 prefilled_mode=False, order_flow_timeout=60):
        self.server_url = server_url
        self.keyword = keyword
        self.users = users
        self.city = city
        self.date = date
        self.price = price
        self.price_index = price_index
        self.if_commit_order = if_commit_order
        self.device_name = device_name
        self.platform_version = platform_version
        self.udid = udid
        self.sale_start_time = sale_start_time
        self.wait_poll_interval = float(wait_poll_interval)
        self.prefilled_mode = prefilled_mode
        self.order_flow_timeout = float(order_flow_timeout)
        if not isinstance(prefilled_mode, bool):
            raise ValueError("prefilled_mode 必须是 true 或 false")
        if not 1 <= self.order_flow_timeout <= 180:
            raise ValueError("order_flow_timeout 必须在 1 到 180 秒之间")
        if not 0.2 <= self.wait_poll_interval <= 10:
            raise ValueError("wait_poll_interval 必须在 0.2 到 10 秒之间")
        # 在连接设备前验证时间格式。使用固定 UTC+8，不依赖 Windows 的 tzdata。
        self.sale_start_datetime

    @property
    def sale_start_datetime(self):
        if self.sale_start_time in (None, ""):
            return None
        value = str(self.sale_start_time).strip().replace("：", ":")
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(value, pattern).replace(
                    tzinfo=timezone(timedelta(hours=8)))
            except ValueError:
                continue
        raise ValueError("sale_start_time 请填写北京时间，例如 2026-10-29 10:18:00")

    @staticmethod
    def load_config():
        config_path = Path(__file__).resolve().with_name('config.jsonc')
        with config_path.open('r', encoding='utf-8') as config_file:
            config = json.load(config_file)
        return Config(config['server_url'],
                      config['keyword'],
                      config['users'],
                      config['city'],
                      config['date'],
                      config['price'],
                      config['price_index'],
                      config['if_commit_order'],
                      device_name=config.get('device_name', 'Android'),
                      platform_version=config.get('platform_version'),
                      udid=config.get('udid'),
                      sale_start_time=config.get('sale_start_time'),
                      wait_poll_interval=config.get('wait_poll_interval', 0.5),
                      prefilled_mode=config.get('prefilled_mode', False),
                      order_flow_timeout=config.get('order_flow_timeout', 60))
