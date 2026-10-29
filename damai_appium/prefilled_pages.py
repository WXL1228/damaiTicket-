"""解析预填购票页面的证据；不连接设备，也不执行任何动作。"""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re
import unicodedata
from typing import Dict, List, Optional, Tuple
from xml.etree import ElementTree


Bounds = Tuple[int, int, int, int]
PREFIX = "cn.damai:id/"
TITLE_IDS = {PREFIX + name for name in (
    "info_v2_title_tv1", "title_tv", "project_detail_title_bar_title",
)}
PURCHASE_BAR = PREFIX + "trade_project_detail_purchase_status_bar_container_fl"
PRICE_CONTAINER = PREFIX + "project_detail_perform_price_flowlayout"
BUY_IDS = {PREFIX + "btn_buy_view", PREFIX + "btn_buy", "btn_buy_view", "btn_buy"}
SKU_ROOT_IDS = {PREFIX + "sku_contanier", PREFIX + "layout_sku"}
SKU_FOOTER_IDS = {PREFIX + "id_sku_bottom_bar_container",
                  PREFIX + "id_sku_bottom_bar_action_content", PREFIX + "btn_buy_bottom_div"}
SKU_GENERIC_TITLES = {"选择场次", "选择票档", "选择场次票档", "选择场次及票档", "选择场次和票档",
                      "选择场次/票档", "场次票档", "请选择场次", "请选择票档", "选票", "选择规格"}
QUANTITY_LAYOUT_IDS = {PREFIX + "layout_num", PREFIX + "layout_sku_num_ll"}
PREFILL_IDS = {PREFIX + "goto_setinfo_btn_text", "goto_setinfo_btn_text"}
BACK_IDS = {PREFIX + "title_back_btn", "title_back_btn"}
RESERVATION_LABELS = {"预约想看场次", "预约想看票档"}
SUBMIT_LABELS = {"提交订单", "立即提交", "确认提交"}
SOLD_OUT_LABELS = {"售罄", "已售罄", "已售完", "暂无余票", "暂时缺货", "缺货登记", "提交缺货登记"}


@dataclass
class Page:
    stage: str
    reason: str
    title: str = ""
    entry_bounds: Optional[Bounds] = None
    action_bounds: Optional[Bounds] = None
    can_submit: bool = False
    prefill_complete: bool = False
    order_id: Optional[str] = None
    amount: Optional[str] = None
    quantity: Optional[int] = None
    action_control_id: str = ""
    action_label: str = ""
    sku_options: List[dict] = field(default_factory=list)
    quantity_increase_bounds: Optional[Bounds] = None
    quantity_decrease_bounds: Optional[Bounds] = None
    checks: Dict[str, bool] = field(default_factory=dict)


def _norm(value):
    value = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", value).strip()


def _compact(value):
    return re.sub(r"\s+", "", _norm(value))


def _get(config, name, default=None):
    return config.get(name, default) if isinstance(config, dict) else getattr(config, name, default)


def _bounds(node):
    match = re.fullmatch(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", node.get("bounds", ""))
    if not match:
        return None
    x1, y1, x2, y2 = map(int, match.groups())
    return (x1, y1, x2, y2) if x1 >= 0 and y1 >= 0 and x2 > x1 and y2 > y1 else None


def _number(value):
    match = re.search(r"(?<![\d.])(\d+(?:\.\d{1,2})?)(?![\d.])", _norm(value))
    if not match:
        return None
    try:
        return Decimal(match.group(1))
    except InvalidOperation:
        return None


def _date_matches(expected, text):
    expected = _norm(expected).replace("：", ":")
    text = _norm(text).replace("：", ":")
    wanted = re.search(r"(?<!\d)(\d{4})[-./年](\d{1,2})[-./月](\d{1,2})日?(?!\d)", expected)
    if not wanted:
        return False
    year, month, day = map(int, wanted.groups())
    full_dates = [tuple(map(int, m.groups())) for m in re.finditer(
        r"(?<!\d)(\d{4})[-./年](\d{1,2})[-./月](\d{1,2})日?(?!\d)", text)]
    if full_dates:
        date_ok = (year, month, day) in full_dates
    else:
        date_ok = bool(re.search(
            rf"(?<!\d)0?{month}[月./-]0?{day}日?(?!\d)", text))
    wanted_time = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", expected)
    if not wanted_time:
        return date_ok
    times = [tuple(map(int, m.groups())) for m in re.finditer(
        r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", text)]
    return date_ok and tuple(map(int, wanted_time.groups())) in times


def _quantity(text):
    direct = [int(m.group(1)) for m in re.finditer(
        r"(?:购票数量|购买数量|数量|票数)\s*[:：×x]?\s*(\d{1,2})(?!\d)", text)]
    ticket_counts = []
    for match in re.finditer(r"(?<!\d)(\d{1,2})\s*张", text):
        preceding = text[max(0, match.start() - 10):match.start()]
        if not re.search(r"限购|最多|最少|至少|每单|每人|上限|可购|剩余|仅剩|余票", preceding):
            ticket_counts.append(int(match.group(1)))
    selected = [int(m.group(1)) for m in re.finditer(
        r"已选(?:择)?\s*(?:观演人|观众|购票人)\s*[:：]?\s*(\d{1,2})\s*(?:人|位)?", text)]
    counts = set(direct or ticket_counts or selected)
    if len(counts) != 1:
        return None
    count = next(iter(counts))
    return count if 1 <= count <= 99 else None


def _amount(text):
    match = re.search(
        r"(?:应付金额|应付总额|实付金额|订单金额|待支付金额|合计|总计|应付)\s*[:：]?\s*[¥￥]?\s*"
        r"(\d+(?:\.\d{1,2})?)(?![\d.])", text)
    return str(Decimal(match.group(1))) if match else None


def _name_present(value, name):
    return bool(re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", value))


def parse_prefilled_page(source, config):
    """将 XML 分类并核对预填信息；只有 checkout.can_submit 才表示提交前核验通过。

    config.target_verified 可由调用方保存本次已核验详情的上下文，仅补足无标题的 SKU。
    payment.checks['locked'] 需要订单号和明确待支付状态，不能据支付按钮单独推断锁单。
    """
    try:
        root = ElementTree.fromstring(source)
    except (ElementTree.ParseError, TypeError, ValueError):
        return Page("unknown", "页面 XML 无法解析")
    nodes = list(root.iter())
    parents = {child: parent for parent in nodes for child in parent}

    def visible(node):
        while node is not None:
            if any(node.get(key) == "false" for key in ("displayed", "visible-to-user")):
                return False
            node = parents.get(node)
        return True

    def enabled(node):
        while node is not None:
            if node.get("enabled") == "false":
                return False
            node = parents.get(node)
        return True

    def labels(node):
        return {_norm(node.get("text")), _norm(node.get("content-desc"))} - {""}

    shown = [node for node in nodes if visible(node)]
    sku_roots = [node for node in shown if node.get("resource-id") in SKU_ROOT_IDS]
    sku_nodes = {child for node in sku_roots for child in node.iter() if visible(child)}

    def belongs_to(node, identifiers):
        while node is not None:
            if node.get("resource-id") in identifiers:
                return True
            node = parents.get(node)
        return False

    def selected_quantity():
        # tv_num 位于实际计数区域；限购提示不参与当前数量判断。
        count_nodes = [node for node in shown if node.get("resource-id") == PREFIX + "tv_num"
                       and belongs_to(node, QUANTITY_LAYOUT_IDS)]
        if count_nodes:
            counts = set()
            for node in count_nodes:
                for value in labels(node):
                    match = re.fullmatch(r"(?:数量\s*[:：]?\s*)?(\d{1,2})\s*张?", value)
                    if match and 1 <= int(match.group(1)) <= 99:
                        counts.add(int(match.group(1)))
            return next(iter(counts)) if len(counts) == 1 else None
        return _quantity(all_text)

    texts = [text for node in shown for text in sorted(labels(node))]
    all_text = "\n".join(texts)
    title_nodes = set()
    title_values = []
    for node in shown:
        # 已观察到正式 SKU 的标题是 tv_title；该通用 ID 仅在 SKU 根内部有效。
        is_title = (node.get("resource-id") in TITLE_IDS
                    or (node in sku_nodes and node.get("resource-id") == PREFIX + "tv_title"))
        if is_title and (not sku_roots or node in sku_nodes):
            children = [child for child in node.iter() if visible(child)]
            title_nodes.update(children)
            value = _compact(" ".join(text for child in children for text in sorted(labels(child))))
            if value:
                title_values.append(value)
    title = _compact(" ".join(text for node in nodes if node in title_nodes for text in sorted(labels(node))))
    keyword, city = _compact(_get(config, "keyword")), _compact(_get(config, "city"))
    title_keyword = bool(keyword) and keyword in title
    title_city = not city or city in title
    target = title_keyword and title_city
    if sku_roots and title_values:
        event_titles = [value for value in title_values if value not in SKU_GENERIC_TITLES]
        title_keyword = bool(event_titles) and bool(keyword) and all(keyword in value for value in event_titles)
        title_city = not city or (bool(event_titles) and all(city in value for value in event_titles))
        target = title_keyword and title_city
    generic_sku_title = bool(sku_roots and title_values and
                             all(value in SKU_GENERIC_TITLES for value in title_values))
    context = bool(_get(config, "target_verified", False)) and (not title or generic_sku_title)
    checks = {"target": target or context, "keyword": title_keyword, "city": title_city,
              "context": context, "locked": False}

    def action_bounds(node):
        if not visible(node) or not enabled(node):
            return None
        if _bounds(node):
            return _bounds(node)
        ancestor = parents.get(node)
        for _ in range(3):
            if ancestor is None:
                break
            if (ancestor.get("clickable") == "true" and visible(ancestor)
                    and enabled(ancestor) and _bounds(ancestor)):
                return _bounds(ancestor)
            ancestor = parents.get(ancestor)
        return None

    def quantity_action(identifier):
        controls = [action_bounds(node) for node in shown
                    if node.get("resource-id") == PREFIX + identifier
                    and belongs_to(node, {PREFIX + "layout_num"})
                    and action_bounds(node)]
        return controls[0] if len(controls) == 1 else None

    def option_price(option):
        prices = set()
        number_pattern = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
        for child in option.iter():
            if not visible(child):
                continue
            for value in labels(child):
                # 币种紧邻的数字才是价格；同文案里的“限购4张”等数字不能混入。
                currency = re.findall(rf"[¥￥]\s*({number_pattern})|({number_pattern})\s*元", value)
                amounts = [left or right for left, right in currency]
                if not amounts and "price" in child.get("resource-id", "").lower():
                    amounts = re.findall(rf"(?<![\d.]){number_pattern}(?![\d.])", value)
                for number in amounts:
                    prices.add(Decimal(number.replace(",", "")))
        return format(next(iter(prices)).normalize(), "f") if len(prices) == 1 else None

    def price_options(containers):
        options = []
        for container in containers:
            for option in container:
                # 一个直接子选项可能包含多层 ll_perform_item；只保留外层实际点击区域。
                if (not visible(option) or option.get("clickable") != "true"
                        or option.get("class") not in {
                            "android.widget.FrameLayout", "android.view.ViewGroup", "android.widget.LinearLayout"}
                        or not _bounds(option)):
                    continue
                stock_labels = {value for child in option.iter() if visible(child) for value in labels(child)}
                options.append({"bounds": _bounds(option),
                                "unavailable": not enabled(option) or bool(stock_labels & SOLD_OUT_LABELS),
                                "price": option_price(option)})
        return options

    # 验证只能由用户在官方界面完成；此分类永远不携带可点击坐标。
    if any(word in all_text for word in ("验证码", "滑块", "安全验证")):
        return Page("verification", "检测到验证码或安全验证，需要用户在手机完成", title=title, checks=checks)

    order_match = re.search(r"(?:订单号|订单编号)\s*[:：]?\s*([A-Za-z0-9_-]{8,40})(?![A-Za-z0-9_-])", all_text)
    order_id = order_match.group(1) if order_match else None
    pending = any(labels(node) & {"待支付", "等待付款", "待付款", "订单待支付", "订单等待付款"}
                  for node in shown) or bool(re.search(
                      r"(?:订单状态|当前状态)\s*[:：]?\s*(?:待支付|等待付款|待付款)", all_text))
    countdown = any(word in all_text for word in ("剩余支付时间", "支付剩余时间"))
    pay_button = any(labels(node) & {"立即支付", "去支付", "确认支付", "立即付款", "去付款"}
                     for node in shown)
    if ((pending and (order_id or countdown)) or (countdown and (order_id or pay_button))
            or (order_id and pay_button)):
        amount = _amount(all_text)
        ticket_price = _number(_get(config, "price"))
        expected_total = ticket_price * len(_get(config, "users", []) or []) if ticket_price is not None else None
        # 支付页可能只显示通用页名，缺失演出标题本身不是另一演出的正向证据。
        generic_titles = {"订单详情", "确认订单", "订单确认", "支付订单", "订单支付", "收银台",
                          "支付", "待支付", "订单", "支付详情"}
        title_conflict = bool(title and title not in generic_titles and not target)
        amount_conflict = amount is not None and expected_total is not None and Decimal(amount) != expected_total
        checks["payment_target_conflict"] = title_conflict
        checks["amount"] = not amount_conflict
        checks["locked"] = bool(order_id and pending and not title_conflict and not amount_conflict)
        return Page("payment", "已识别支付界面" if not checks["locked"] else "已识别订单号及待支付状态",
                    title=title, order_id=order_id, amount=amount, checks=checks)

    if any(labels(node) & RESERVATION_LABELS for node in shown):
        back = next((action_bounds(node) for node in shown if node.get("resource-id") in BACK_IDS
                     and action_bounds(node)), None)
        return Page("reservation", "当前为预约选票页", title=title, action_bounds=back, checks=checks)

    price_nodes = [node for node in shown if node.get("resource-id") == PRICE_CONTAINER
                   and (not sku_roots or node in sku_nodes)]
    buy = next((node for node in shown if node.get("resource-id") in BUY_IDS
                and (not sku_roots or node in sku_nodes)), None)
    footers = [node for node in shown if node.get("resource-id") in SKU_FOOTER_IDS
               and node in sku_nodes]
    footer_nodes = {child for footer in footers for child in footer.iter() if visible(child)}
    # 只看动作区的缺货文案；其他未选票档的“缺货登记”不代表当前票档售罄。
    buy_labels = {value for child in buy.iter() if visible(child) for value in labels(child)} if buy is not None else set()
    missing_stock = bool(buy_labels & SOLD_OUT_LABELS)
    if buy is None and sku_roots and price_nodes:
        missing_stock = any(labels(node) & SOLD_OUT_LABELS for node in footer_nodes)
    if missing_stock:
        return Page("sold_out", "购买按钮显示缺货或售罄", title=title, checks=checks)
    if sku_roots or (price_nodes and buy is not None):
        # SKU 的确认按钮也可能写“提交订单”，必须先按结构分类，绝不能视作最终提交。
        if buy is None and sku_roots and price_nodes:
            candidates = [node for node in shown if node in footer_nodes and labels(node) & {"确定"}
                          and action_bounds(node)]
            if len(candidates) == 1:
                buy = candidates[0]
        known_structure = bool(price_nodes and buy is not None)
        ready = known_structure and (target or context)
        reason = ("已识别正式选票结构" if ready else
                  "选票页缺少匹配目标或已核验上下文" if known_structure else "选票页确认控件尚未完整识别")
        return Page("sku", reason, title=title,
                    action_bounds=action_bounds(buy) if ready else None,
                    action_control_id=buy.get("resource-id", "") if buy is not None else "",
                    sku_options=price_options(price_nodes) if target or context else [],
                    quantity_increase_bounds=quantity_action("img_jia") if target or context else None,
                    quantity_decrease_bounds=quantity_action("img_jian") if target or context else None,
                    quantity=selected_quantity(), checks=checks)

    submit = next((node for node in shown if labels(node) & SUBMIT_LABELS), None)
    if submit is not None:
        keyword_ok = bool(keyword) and keyword in _compact(all_text)
        city_ok = not city or city in _compact(all_text)
        expected_price = _number(_get(config, "price"))
        price_ok = False
        if expected_price is not None:
            for node in shown:
                for value in labels(node):
                    if (re.search(r"元|¥|￥|票价|票档", value)
                            or "price" in node.get("resource-id", "").lower()):
                        numbers = re.findall(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])", value)
                        if any(Decimal(number) == expected_price for number in numbers):
                            price_ok = True
        users = [_norm(user) for user in (_get(config, "users", []) or []) if _norm(user)]
        quantity = selected_quantity()
        expected_quantity = len(users)

        def checkable(node):
            return (node.get("checkable") == "true"
                    or any(word in node.get("class", "") for word in ("CheckBox", "RadioButton")))

        def selected(node):
            return node.get("checked") == "true" or node.get("selected") == "true"

        confirmed_users = set()
        for user in users:
            matching_nodes = [node for node in shown if any(_name_present(value, user) for value in labels(node))]
            for name_node in matching_nodes:
                if selected(name_node):
                    confirmed_users.add(user)
                    break
                # 有明确角色前缀的不可编辑摘要，不等同于人员列表中的孤立姓名。
                parent = parents.get(name_node)
                inline_summary = any(re.match(r"^(?:观演人|购票人|已选观演人)\s*[:：]\s*\S", value)
                                     for value in labels(name_node))
                if (inline_summary and name_node.get("clickable") != "true"
                        and name_node.get("editable") != "true"
                        and "EditText" not in name_node.get("class", "")
                        and parent is not None
                        and not any(checkable(node) for node in parent.iter() if visible(node))):
                    confirmed_users.add(user)
                    break
                ancestor = parents.get(name_node)
                for _ in range(2):
                    if ancestor is None or ancestor is root:
                        break
                    descendants = [node for node in ancestor.iter() if visible(node)]
                    descendant_text = "\n".join(value for node in descendants for value in labels(node))
                    options = [node for node in descendants if checkable(node)]
                    named_users = {name for name in users if _name_present(descendant_text, name)}
                    # 一个选项对应一个观演人，避免把同列表其他人的勾选算给当前姓名。
                    row_selected = len(options) == 1 and selected(options[0]) and named_users == {user}
                    immutable = (
                        any(labels(node) & {"观演人", "购票人", "已选观演人"} for node in descendants)
                        and not options
                        and all(node.get("clickable") != "true"
                                and node.get("editable") != "true"
                                and "EditText" not in node.get("class", "") for node in descendants)
                    )
                    if row_selected or immutable:
                        confirmed_users.add(user)
                        break
                    ancestor = parents.get(ancestor)
                if user in confirmed_users:
                    break
        viewer_options = set()
        for heading in shown:
            if not labels(heading) & {"观演人", "购票人", "已选观演人"}:
                continue
            ancestor = parents.get(heading)
            for _ in range(2):
                if ancestor is None or ancestor is root:
                    break
                descendants = [node for node in ancestor.iter() if visible(node)]
                section_text = "\n".join(value for node in descendants for value in labels(node))
                options = [node for node in descendants if checkable(node)]
                if options and any(_name_present(section_text, user) for user in users):
                    viewer_options.update(options)
                    break
                ancestor = parents.get(ancestor)
        selected_count_ok = not viewer_options or sum(selected(node) for node in viewer_options) == expected_quantity
        amount = _amount(all_text)
        expected_amount = expected_price * expected_quantity if expected_price is not None else None
        amount_ok = amount is None or (expected_amount is not None and Decimal(amount) == expected_amount)
        button_bounds = action_bounds(submit)
        checks.update({
            "keyword": keyword_ok, "city": city_ok, "target": keyword_ok and city_ok,
            "date": _date_matches(_get(config, "date"), all_text), "price": price_ok,
            "quantity": expected_quantity > 0 and quantity == expected_quantity,
            "viewers": bool(users) and len(set(users)) == len(users) and set(users) <= confirmed_users,
            "viewer_count": selected_count_ok,
            "amount": amount_ok, "submit_button": button_bounds is not None,
        })
        required = ("keyword", "city", "date", "price", "quantity", "viewers", "viewer_count", "amount", "submit_button")
        can_submit = all(checks[key] for key in required)
        missing = [key for key in required if not checks[key]]
        return Page("checkout", "订单信息核对通过" if can_submit else "确认页信息未完整匹配：" + ",".join(missing),
                    title=title, action_bounds=button_bounds, can_submit=can_submit,
                    action_control_id=submit.get("resource-id", ""),
                    action_label=next(iter(labels(submit) & SUBMIT_LABELS), ""),
                    amount=amount, quantity=quantity, checks=checks)

    bars = [node for node in shown if node.get("resource-id") == PURCHASE_BAR]
    sold = any(labels(node) & SOLD_OUT_LABELS for bar in bars for node in bar.iter() if visible(node))
    if sold or (not bars and not price_nodes and any(labels(node) & SOLD_OUT_LABELS for node in shown)):
        return Page("sold_out", "页面显示缺货或售罄", title=title, checks=checks)

    if bars:
        prefill = any(node.get("resource-id") in PREFILL_IDS and "已完成" in labels(node) for node in shown)
        entry = next((action_bounds(bar) for bar in bars if action_bounds(bar)), None)
        checks["prefill"] = prefill
        checks["entry"] = entry is not None
        ready = target and prefill and entry is not None
        reason = "目标详情与已完成预填已核验" if ready else "详情尚未满足标题、已完成预填及购买栏坐标核验"
        return Page("detail", reason, title=title, entry_bounds=entry if ready else None,
                    prefill_complete=prefill, checks=checks)
    return Page("unknown", "尚无足够页面证据", title=title, checks=checks)
