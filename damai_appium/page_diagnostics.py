"""构造范围受限的页面诊断摘要，不读取设备、不保存页面原文。"""

import re
from xml.etree import ElementTree

if __package__:
    from .sale_wait import PRICE_CONTAINER, PURCHASE_BAR, PURCHASE_LABELS, RESERVATION_LABELS, normalized_text
else:
    from sale_wait import PRICE_CONTAINER, PURCHASE_BAR, PURCHASE_LABELS, RESERVATION_LABELS, normalized_text


TITLE_IDS = {
    "cn.damai:id/info_v2_title_tv1",
    "cn.damai:id/title_tv",
}
PURCHASE_IDS = {
    PURCHASE_BAR, PRICE_CONTAINER, "cn.damai:id/btn_buy_view", "btn_buy_view",
}
RESERVATION_TEXT_LABELS = RESERVATION_LABELS | {
    "预约", "立即预约", "取消预约", "已预约", "预约成功",
}
CONTROL_TEXT_LABELS = PURCHASE_LABELS | RESERVATION_TEXT_LABELS | {
    "购买", "确认购买", "确定", "缺货", "缺货登记", "提交缺货登记",
    "售罄", "已售罄", "无票", "暂时缺货", "开售提醒", "设置开售提醒",
    "已设置开售提醒", "取消开售提醒", "即将开售", "待开售",
}
# 已知标题允许保留以排查匹配失败，但号码仍应脱敏。
SENSITIVE_NUMBER = re.compile(r"(?<!\d)(?:\d{17}[\dXx]|\d{15}|1[3-9]\d{9})(?!\d)")


def summarize_page(source, keyword, city):
    """只返回结构、两个已知标题和静态白名单标签组成的 JSON 可序列化摘要。"""
    summary = {
        "known_title_controls": [],
        "resource_ids": [],
        "purchase_controls": [],
        "reservation_labels": [],
        "parser_error": None,
    }
    try:
        root = ElementTree.fromstring(source)
    except (ElementTree.ParseError, TypeError, ValueError):
        # 不返回异常原文，避免解析器错误信息夹带页面内容。
        summary["parser_error"] = "invalid_xml"
        return summary

    nodes = list(root.iter())
    parents = {child: parent for parent in nodes for child in parent}

    def visible(node):
        while node is not None:
            if any(node.get(name) == "false" for name in ("displayed", "visible-to-user")):
                return False
            node = parents.get(node)
        return True

    def is_damai(node):
        return (node.get("package") == "cn.damai"
                or node.get("resource-id", "").startswith("cn.damai:id/"))

    def boolean_attribute(node, name):
        return {"true": True, "false": False}.get(node.get(name))

    resource_ids = set()
    reservations = set()
    purchase_nodes = set()
    for node in nodes:
        resource_id = node.get("resource-id", "")
        if is_damai(node):
            if resource_id and resource_id not in resource_ids:
                summary["resource_ids"].append(resource_id)
                resource_ids.add(resource_id)
            for name in ("text", "content-desc"):
                value = node.get(name, "").strip()
                if value in RESERVATION_TEXT_LABELS and value not in reservations:
                    summary["reservation_labels"].append(value)
                    reservations.add(value)
            if resource_id in PURCHASE_IDS:
                purchase_nodes.update(node.iter())

        if resource_id in TITLE_IDS:
            text = node.get("text", "")
            description = node.get("content-desc", "")
            readable_title = " ".join(
                child.get("text", "") + " " + child.get("content-desc", "")
                for child in node.iter())
            normalized_title = normalized_text(readable_title)
            summary["known_title_controls"].append({
                "resource-id": resource_id,
                "text": SENSITIVE_NUMBER.sub("[redacted]", text),
                "content-desc": SENSITIVE_NUMBER.sub("[redacted]", description),
                "readable_title": SENSITIVE_NUMBER.sub("[redacted]", readable_title).strip(),
                "visible": visible(node),
                "keyword_matches": bool(normalized_text(keyword)) and normalized_text(keyword) in normalized_title,
                "city_matches": not city or normalized_text(city) in normalized_title,
            })

    # 使用原页面顺序，并通过 set 避免嵌套购买控件产生重复条目。
    for node in nodes:
        if node not in purchase_nodes:
            continue
        control = {
            "resource-id": node.get("resource-id", ""),
            "class": node.get("class", ""),
            "enabled": boolean_attribute(node, "enabled"),
            "clickable": boolean_attribute(node, "clickable"),
            "visible": visible(node),
        }
        for name in ("text", "content-desc"):
            value = node.get(name, "").strip()
            if value in CONTROL_TEXT_LABELS:
                control[name] = value
        summary["purchase_controls"].append(control)
    return summary
