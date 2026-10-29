"""只读判断待命页面；时间到达本身不代表有票或可以点击。"""

from xml.etree import ElementTree
import unicodedata


PURCHASE_LABELS = {"立即购买", "立即预订", "立即抢票", "选座购买"}
RESERVATION_LABELS = {"预约想看场次", "预约想看票档"}
PURCHASE_BAR = "cn.damai:id/trade_project_detail_purchase_status_bar_container_fl"
PRICE_CONTAINER = "cn.damai:id/project_detail_perform_price_flowlayout"


def normalized_text(value):
    """兼容标题中的全角符号、换行和空格，不放宽目标关键词本身。"""
    return "".join(unicodedata.normalize("NFKC", value).split())


def inspect_sale_page(source, keyword, city):
    """返回 (detail/sku/None, 状态说明)，只接受已知页面结构和明确购买标签。"""
    try:
        root = ElementTree.fromstring(source)
    except ElementTree.ParseError:
        return None, "页面仍在加载，等待可识别的演出详情"
    nodes = list(root.iter())
    parents = {child: parent for parent in nodes for child in parent}

    def visible(node):
        while node is not None:
            if (node.get("displayed") == "false"
                    or node.get("visible-to-user") == "false"):
                return False
            node = parents.get(node)
        return True

    def visible_enabled(node):
        if not visible(node):
            return False
        while node is not None:
            if node.get("enabled") == "false":
                return False
            node = parents.get(node)
        return True

    def label(node):
        return {node.get("text", "").strip(), node.get("content-desc", "").strip()}

    damai_nodes = [node for node in nodes if node.get("package") == "cn.damai"]
    if not damai_nodes:
        return None, "请保持手机解锁，并将目标演出详情放在大麦前台"
    if any(label(node) & RESERVATION_LABELS for node in damai_nodes
           if visible(node)):
        return None, "当前为预约页，请手动返回演出详情；程序继续待命，不改动预约"

    titles = [node for node in damai_nodes if node.get("resource-id") in {
        "cn.damai:id/info_v2_title_tv1", "cn.damai:id/title_tv"
    } and visible(node)]
    if not titles:
        return None, "读不到已适配的标题控件，当前页尚未适配；请运行 --check-page 检查"
    title_values = [normalized_text(" ".join(
        child.get("text", "") + " " + child.get("content-desc", "")
        for child in node.iter() if visible(child))) for node in titles]
    if not any(title_values):
        return None, "标题控件存在但文字不可读，无法核验目标；请运行 --check-page 检查"
    if not normalized_text(keyword) or not any(
            normalized_text(keyword) in title
            and (not city or normalized_text(city) in title) for title in title_values):
        return None, "读取到的标题未匹配 keyword、city；请核对配置并运行 --check-page 检查"

    # 购买文字常在 TextView，实际点击的是父容器；只接受已知详情购买栏。
    for node in damai_nodes:
        if not label(node) & PURCHASE_LABELS or not visible_enabled(node):
            continue
        ancestor = node
        has_click_target = False
        while ancestor is not None:
            has_click_target |= ancestor.get("clickable") == "true"
            if ancestor.get("resource-id") == PURCHASE_BAR:
                if has_click_target and visible_enabled(ancestor):
                    return "detail", "已识别可用购买入口"
                break
            ancestor = parents.get(ancestor)

    # 部分详情的按钮文字不暴露给 UIAutomator，允许用户手动进入正式选票页。
    # 仅有票价容器不够：预约页也有同一容器，必须同时看到明确的购买确认按钮。
    if any(node.get("resource-id") == PRICE_CONTAINER and visible_enabled(node)
           for node in damai_nodes):
        for node in damai_nodes:
            if (node.get("resource-id") in {"cn.damai:id/btn_buy_view", "btn_buy_view"}
                    and label(node) & {"立即购买", "购买", "确认购买"}
                    and node.get("clickable") == "true" and visible_enabled(node)):
                return "sku", "已识别正式选票页"
    return None, "标题已匹配，但购买入口文字或控件结构未识别；开售时请直接手动继续"
