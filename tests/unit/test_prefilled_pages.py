from dataclasses import asdict
import json
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest

from damai_appium.prefilled_pages import parse_prefilled_page


PREFIX = "cn.damai:id/"


@pytest.fixture
def config():
    return SimpleNamespace(keyword="测试歌手", city="北京", date="2026-11-06 周五 19:00",
                           price="看台580元", users=["观众甲", "观众乙"], target_verified=False)


def node(parent, text="", resource_id="", **attributes):
    attrs = {"package": "cn.damai", "class": "android.widget.TextView", "text": text,
             "resource-id": resource_id, "displayed": "true", "enabled": "true",
             "clickable": "false", "bounds": "[0,100][1200,200]"}
    attrs.update(attributes)
    return ElementTree.SubElement(parent, "node", attrs)


def document(title="北京·测试歌手演唱会"):
    root = ElementTree.Element("hierarchy")
    app = node(root, resource_id=PREFIX + "page", **{"class": "android.widget.FrameLayout"})
    if title is not None:
        node(app, title, PREFIX + "info_v2_title_tv1")
    return root, app


def parse(root, config):
    return parse_prefilled_page(ElementTree.tostring(root, encoding="unicode"), config)


def checkout(*, day="2026.11.06 19:00", price="看台580元", count="数量：2张",
             amount="合计：1160元", selected=(True, True), immutable=False,
             submit="提交订单", title="北京·测试歌手演唱会"):
    root, app = document(title)
    for text in (day, price, count, amount):
        if text:
            node(app, text)
    viewers = node(app, resource_id=PREFIX + "viewer_summary")
    node(viewers, "观演人")
    for name, is_selected in zip(("观众甲", "观众乙"), selected):
        row = node(viewers, resource_id=PREFIX + "viewer_item")
        node(row, name)
        if not immutable:
            node(row, **{"class": "android.widget.CheckBox", "checkable": "true",
                         "checked": "true" if is_selected else "false"})
    submit_node = node(app, submit, PREFIX + "submit", bounds="[100,2400][1100,2550]")
    return root, submit_node


def test_hidden_text_nonclickable_detail_bar_is_armed_only_after_prefill_and_title(config):
    root, app = document()
    bar = node(app, resource_id=PREFIX + "trade_project_detail_purchase_status_bar_container_fl",
               bounds="[315,2460][1170,2595]")
    node(bar)
    node(app, "已完成", PREFIX + "goto_setinfo_btn_text")

    page = parse(root, config)

    assert page.stage == "detail"
    assert page.prefill_complete is True
    assert page.entry_bounds == (315, 2460, 1170, 2595)
    assert page.can_submit is False
    json.dumps(asdict(page), ensure_ascii=False)


@pytest.mark.parametrize("changes", [
    {"enabled": "false"}, {"displayed": "false"}, {"bounds": "[0,0][0,200]"},
    {"bounds": "[-10,100][100,200]"}, {"bounds": "invalid"},
])
def test_detail_invalid_or_inactive_entry_never_has_coordinates(config, changes):
    root, app = document()
    node(app, "已完成", PREFIX + "goto_setinfo_btn_text")
    node(app, resource_id=PREFIX + "trade_project_detail_purchase_status_bar_container_fl", **changes)

    assert parse(root, config).entry_bounds is None


@pytest.mark.parametrize("prefill,title", [(False, "北京·测试歌手演唱会"), (True, "上海·其他歌手演唱会")])
def test_detail_missing_prefill_or_wrong_title_is_not_armed(config, prefill, title):
    root, app = document(title)
    node(app, resource_id=PREFIX + "trade_project_detail_purchase_status_bar_container_fl")
    if prefill:
        node(app, "已完成", PREFIX + "goto_setinfo_btn_text")
    assert parse(root, config).entry_bounds is None


def test_additional_observed_title_control_is_supported(config):
    root, app = document(None)
    node(app, "北京·测试歌手演唱会", PREFIX + "project_detail_title_bar_title")
    node(app, "已完成", PREFIX + "goto_setinfo_btn_text")
    node(app, resource_id=PREFIX + "trade_project_detail_purchase_status_bar_container_fl")
    assert parse(root, config).entry_bounds is not None


@pytest.mark.parametrize("title_id", ["info_v2_title_tv1", "project_detail_title_bar_title"])
def test_title_descendants_content_description_and_spacing_are_normalized(config, title_id):
    root, app = document(None)
    title = node(app, resource_id=PREFIX + title_id)
    node(title, **{"content-desc": "北　京 · Ｔｅｓｔ　歌 手 演 唱 会"})
    node(app, "已完成", PREFIX + "goto_setinfo_btn_text")
    node(app, resource_id=PREFIX + "trade_project_detail_purchase_status_bar_container_fl")
    config.keyword = "Test歌手"

    page = parse(root, config)

    assert page.entry_bounds is not None
    assert page.title == "北京·Test歌手演唱会"


@pytest.mark.parametrize("heading", ["预约想看场次", "预约想看票档"])
def test_reservation_page_only_returns_navigation_back(config, heading):
    root, app = document()
    node(app, heading, enabled="false")
    node(app, resource_id=PREFIX + "title_back_btn", bounds="[0,0][100,100]")
    node(app, resource_id=PREFIX + "project_detail_perform_price_flowlayout")
    node(app, resource_id=PREFIX + "btn_buy_view")

    page = parse(root, config)

    assert page.stage == "reservation"
    assert page.action_bounds == (0, 0, 100, 100)
    assert page.entry_bounds is None
    assert page.can_submit is False


def test_formal_sku_allows_hidden_label_nonclickable_canvas(config):
    root, app = document()
    node(app, resource_id=PREFIX + "project_detail_perform_price_flowlayout")
    node(app, resource_id=PREFIX + "btn_buy", bounds="[0,2400][1200,2550]")

    page = parse(root, config)

    assert page.stage == "sku"
    assert page.action_bounds == (0, 2400, 1200, 2550)


def test_sku_missing_title_requires_explicit_prior_target_context(config):
    root, app = document(None)
    node(app, resource_id=PREFIX + "project_detail_perform_price_flowlayout")
    node(app, resource_id=PREFIX + "btn_buy_view")
    assert parse(root, config).action_bounds is None
    config.target_verified = True
    assert parse(root, config).action_bounds is not None


def test_prior_context_cannot_override_wrong_visible_sku_title(config):
    root, app = document("上海·其他歌手演唱会")
    node(app, resource_id=PREFIX + "project_detail_perform_price_flowlayout")
    node(app, resource_id=PREFIX + "btn_buy_view")
    config.target_verified = True
    assert parse(root, config).action_bounds is None


@pytest.mark.parametrize("day", [
    "2026.11.06 周五 19:00", "11月6日 19:00", "2026年11月6日 19：00",
    "2026-11-06 周五 19:00",
])
def test_checkout_requires_full_target_and_accepts_equivalent_dates(config, day):
    root, _ = checkout(day=day)

    page = parse(root, config)

    assert page.stage == "checkout"
    assert page.can_submit is True
    assert page.quantity == 2
    assert page.amount == "1160"
    assert page.action_bounds == (100, 2400, 1100, 2550)


@pytest.mark.parametrize("changes,failed_check", [
    ({"day": "2027.11.06 19:00"}, "date"),
    ({"day": "2026.11.06 19:30"}, "date"),
    ({"price": "看台1580元", "amount": "合计3160元"}, "price"),
    ({"count": "数量3张"}, "quantity"),
    ({"count": "每单限购2张"}, "quantity"),
    ({"selected": (True, False)}, "viewers"),
    ({"selected": (False, False)}, "viewers"),
    ({"amount": "合计1161元"}, "amount"),
    ({"title": "上海·其他歌手演唱会"}, "keyword"),
])
def test_checkout_mismatches_or_unselected_names_block_submission(config, changes, failed_check):
    root, _ = checkout(**changes)

    page = parse(root, config)

    assert page.stage == "checkout"
    assert page.can_submit is False
    assert page.checks[failed_check] is False


def test_immutable_viewer_summary_can_confirm_people(config):
    root, _ = checkout(immutable=True)
    assert parse(root, config).can_submit is True


def test_inline_immutable_viewer_summary_is_explicitly_associated_with_people(config):
    root, _ = checkout(immutable=True)
    app = root[0]
    section = next(item for item in app if item.get("resource-id") == PREFIX + "viewer_summary")
    app.remove(section)
    node(app, "观演人：观众甲、观众乙")
    assert parse(root, config).can_submit is True


def test_extra_selected_person_blocks_submission(config):
    root, _ = checkout()
    section = next(item for item in root[0] if item.get("resource-id") == PREFIX + "viewer_summary")
    row = node(section, resource_id=PREFIX + "viewer_item")
    node(row, "其他观众")
    node(row, **{"class": "android.widget.CheckBox", "checkable": "true", "checked": "true"})
    page = parse(root, config)
    assert page.can_submit is False
    assert page.checks["viewer_count"] is False


@pytest.mark.parametrize("label", ["确认", "立即支付", "去支付", "确认购买"])
def test_generic_confirmation_and_payment_labels_are_not_submit_buttons(config, label):
    root, _ = checkout(submit=label)
    page = parse(root, config)
    assert page.stage != "checkout"
    assert page.can_submit is False
    assert page.action_bounds is None


def test_disabled_submit_button_blocks_submission(config):
    root, button = checkout()
    button.set("enabled", "false")
    page = parse(root, config)
    assert page.stage == "checkout"
    assert page.can_submit is False
    assert page.action_bounds is None


def test_payment_needs_order_number_and_pending_status_for_locked_evidence(config):
    root, app = document()
    node(app, "订单号：123456789012345678")
    node(app, "待支付")
    node(app, "应付金额：1160.00元")

    page = parse(root, config)

    assert page.stage == "payment"
    assert page.order_id == "123456789012345678"
    assert page.amount == "1160.00"
    assert page.checks["locked"] is True


@pytest.mark.parametrize("title,amount", [
    ("上海·其他歌手演唱会", "应付金额1160元"),
    ("北京·测试歌手演唱会", "应付金额1580元"),
])
def test_payment_conflicting_target_or_total_is_not_target_order_lock(config, title, amount):
    root, app = document(title)
    node(app, "订单号：123456789012345678")
    node(app, "待支付")
    node(app, amount)

    page = parse(root, config)

    assert page.stage == "payment"
    assert page.checks["locked"] is False


@pytest.mark.parametrize("title", [None, "订单详情"])
def test_payment_missing_target_details_can_use_order_and_pending_minimum_evidence(config, title):
    root, app = document(title)
    node(app, "订单号：123456789012345678")
    node(app, "待支付")
    assert parse(root, config).checks["locked"] is True


def test_payment_screen_with_pay_button_only_is_not_locked(config):
    root, app = document()
    node(app, "立即支付")
    page = parse(root, config)
    assert page.stage != "payment"
    assert page.checks["locked"] is False


def test_pending_amount_label_is_not_an_order_status(config):
    root, app = document()
    node(app, "订单号：123456789012345678")
    node(app, "待支付金额1160元")
    node(app, "立即支付")
    page = parse(root, config)
    assert page.stage == "payment"
    assert page.checks["locked"] is False


def test_countdown_and_payment_button_identify_screen_but_do_not_prove_locked(config):
    root, app = document()
    node(app, "剩余支付时间 00:14:59")
    node(app, "立即支付")
    page = parse(root, config)
    assert page.stage == "payment"
    assert page.checks["locked"] is False


@pytest.mark.parametrize("label", ["请输入验证码", "拖动滑块完成验证", "安全验证"])
def test_verification_never_has_action_coordinates(config, label):
    root, app = document()
    node(app, label)
    node(app, "立即提交", clickable="true")
    page = parse(root, config)
    assert page.stage == "verification"
    assert page.can_submit is False
    assert page.entry_bounds is None
    assert page.action_bounds is None


def test_sold_out_bar_does_not_offer_entry(config):
    root, app = document()
    node(app, "已售罄", PREFIX + "trade_project_detail_purchase_status_bar_container_fl")
    node(app, "已完成", PREFIX + "goto_setinfo_btn_text")
    page = parse(root, config)
    assert page.stage == "sold_out"
    assert page.entry_bounds is None


def test_bad_xml_has_no_action(config):
    page = parse_prefilled_page("<hierarchy", config)
    assert page.stage == "unknown"
    assert page.action_bounds is None


def sku(*, title="北京·测试歌手演唱会", button_text="", button_id=PREFIX + "btn_buy_view",
        include_price=True, include_footer=True):
    """A minimal anonymized version of the observed native SKU hierarchy."""
    root, app = document(None)
    container = node(app, resource_id=PREFIX + "sku_contanier")
    layout = node(container, resource_id=PREFIX + "layout_sku")
    node(layout, title, PREFIX + "title_tv", displayed="false")
    node(layout, title, PREFIX + "tv_title")
    if include_price:
        price = node(layout, resource_id=PREFIX + "project_detail_perform_price_flowlayout")
    else:
        price = None
    footer = node(layout, resource_id=PREFIX + "id_sku_bottom_bar_container") if include_footer else layout
    button = node(footer, button_text, button_id, clickable="true", bounds="[720,2400][1140,2530]")
    return root, layout, price, footer, button


@pytest.mark.parametrize("label", ["", "确定", "提交订单", "立即提交", "确认提交"])
def test_observed_sku_structure_has_priority_over_final_submit_words(config, label):
    root, _, _, _, button = sku(button_text=label)

    page = parse(root, config)

    assert page.stage == "sku"
    assert page.can_submit is False
    assert page.action_bounds == (720, 2400, 1140, 2530)
    assert page.action_control_id == button.get("resource-id")


def test_sku_overlay_cannot_reuse_background_checkout_submit(config):
    root, _ = checkout()
    _, layout, _, _, button = sku(button_text="提交订单")
    root[0].append(layout)

    page = parse(root, config)

    assert page.stage == "sku"
    assert page.can_submit is False
    assert page.action_bounds == (720, 2400, 1140, 2530)
    assert page.action_control_id == button.get("resource-id")


def test_visible_sku_tv_title_replaces_hidden_header_without_prior_context(config):
    root, _, _, _, _ = sku()

    page = parse(root, config)

    assert page.stage == "sku"
    assert page.action_bounds is not None
    assert page.title == "北京·测试歌手演唱会"
    assert page.checks["target"] is True
    assert page.checks["context"] is False


@pytest.mark.parametrize("title", ["选择场次", "选择票档", "选择场次及票档"])
def test_generic_sku_modal_title_can_only_use_verified_session_context(config, title):
    root, _, _, _, _ = sku(title=title)
    assert parse(root, config).action_bounds is None

    config.target_verified = True
    page = parse(root, config)

    assert page.action_bounds is not None
    assert page.checks["context"] is True
    assert page.can_submit is False


def test_visible_other_event_in_sku_overrides_underlying_target_and_context(config):
    root, layout, _, _, _ = sku(title="上海·其他歌手演唱会")
    node(root[0], "北京·测试歌手演唱会", PREFIX + "info_v2_title_tv1")
    node(layout, "选择场次", PREFIX + "title_tv")
    config.target_verified = True

    page = parse(root, config)

    assert page.stage == "sku"
    assert page.action_bounds is None
    assert page.checks["context"] is False


def test_general_tv_title_outside_sku_is_not_an_event_title(config):
    root, app = document(None)
    node(app, "北京·测试歌手演唱会", PREFIX + "tv_title")
    node(app, "已完成", PREFIX + "goto_setinfo_btn_text")
    node(app, resource_id=PREFIX + "trade_project_detail_purchase_status_bar_container_fl")

    assert parse(root, config).entry_bounds is None


def test_native_current_quantity_is_not_hidden_by_preceding_limit_notice(config):
    root, _, _, footer, _ = sku()
    counter = node(footer, resource_id=PREFIX + "layout_num")
    node(counter, "每人限购4张")
    inner = node(counter, resource_id=PREFIX + "layout_sku_num_ll")
    node(inner, "3张", PREFIX + "tv_num")

    page = parse(root, config)

    assert page.stage == "sku"
    assert page.quantity == 3
    assert config.users == ["观众甲", "观众乙"]
    assert config.price == "看台580元"


def test_conflicting_native_quantity_controls_do_not_fall_back_to_other_text(config):
    root, _, _, footer, _ = sku()
    counter = node(footer, resource_id=PREFIX + "layout_num")
    node(counter, "2张", PREFIX + "tv_num")
    node(counter, "3张", PREFIX + "tv_num")
    node(footer, "数量2张")

    assert parse(root, config).quantity is None


@pytest.mark.parametrize("label", ["缺货登记", "提交缺货登记", "售罄"])
@pytest.mark.parametrize("nested", [False, True])
def test_sku_stock_notice_on_purchase_action_never_offers_confirmation(config, label, nested):
    root, _, _, _, button = sku(button_text="" if nested else label)
    if nested:
        node(button, label)

    page = parse(root, config)

    assert page.stage == "sold_out"
    assert page.action_bounds is None
    assert page.can_submit is False


def test_stock_notices_for_unselected_price_tiers_do_not_block_available_sku(config):
    root, _, price, _, _ = sku()
    unavailable = node(price, selected="false")
    node(unavailable, "缺货登记", PREFIX + "tv_tag")
    node(unavailable, "提交缺货登记")
    available = node(price, selected="true")
    node(available, "票档580元")

    page = parse(root, config)

    assert page.stage == "sku"
    assert page.action_bounds is not None


def test_stock_registration_without_button_id_in_known_footer_never_confirms(config):
    root, _, _, _, _ = sku(button_text="提交缺货登记", button_id="")
    assert parse(root, config).stage == "sold_out"


def test_exact_confirm_text_fallback_is_scoped_to_known_sku_footer(config):
    root, _, _, _, _ = sku(button_text="确定", button_id="")

    page = parse(root, config)

    assert page.stage == "sku"
    assert page.action_bounds == (720, 2400, 1140, 2530)
    assert page.action_control_id == ""
    assert page.can_submit is False


@pytest.mark.parametrize("changes", [
    {"include_price": False}, {"include_footer": False}, {"button_text": "确认"},
])
def test_confirm_text_fallback_requires_price_known_footer_and_exact_label(config, changes):
    args = dict(button_text="确定", button_id="")
    args.update(changes)
    root, _, _, _, _ = sku(**args)

    page = parse(root, config)

    assert page.stage == "sku"
    assert page.action_bounds is None
    assert page.can_submit is False


def test_multiple_confirm_candidates_are_not_guessed(config):
    root, _, _, footer, _ = sku(button_text="确定", button_id="")
    node(footer, "确定", clickable="true", bounds="[0,300][100,400]")

    assert parse(root, config).action_bounds is None


def test_unscoped_confirm_text_with_price_container_is_not_accepted(config):
    root, app = document()
    node(app, resource_id=PREFIX + "project_detail_perform_price_flowlayout")
    node(app, "确定", clickable="true")

    assert parse(root, config).action_bounds is None


def test_final_checkout_records_actual_submit_control_id(config):
    root, button = checkout()
    page = parse(root, config)
    assert page.stage == "checkout"
    assert page.can_submit is True
    assert page.action_control_id == button.get("resource-id")


@pytest.mark.parametrize("label", ["立即付款", "去付款"])
def test_additional_payment_labels_need_order_evidence_and_never_offer_action(config, label):
    root, app = document()
    node(app, label)
    assert parse(root, config).checks["locked"] is False
    assert parse(root, config).stage != "payment"

    node(app, "订单号：123456789012345678")
    page = parse(root, config)
    assert page.stage == "payment"
    assert page.checks["locked"] is False
    assert page.action_bounds is None

    node(app, "待付款")
    page = parse(root, config)
    assert page.stage == "payment"
    assert page.checks["locked"] is True
    assert page.action_bounds is None


def test_reservation_protection_precedes_sku_structure_and_submit_text(config):
    root, layout, _, _, _ = sku(button_text="提交订单")
    node(layout, "预约想看票档")
    node(layout, resource_id=PREFIX + "title_back_btn", bounds="[0,0][100,100]")
    page = parse(root, config)
    assert page.stage == "reservation"
    assert page.action_bounds == (0, 0, 100, 100)
    assert page.can_submit is False


def add_sku_option(container, *, text="", resource_id="", bounds="[0,300][300,500]", **attrs):
    option = node(container, resource_id=resource_id, bounds=bounds,
                  **{"class": "android.widget.FrameLayout", "clickable": "true", **attrs})
    if text:
        node(option, text)
    return option


def test_unselected_sku_exposes_ordered_price_options_without_assuming_footer_is_active(config):
    root, _, price, _, _ = sku()
    unavailable = add_sku_option(price, bounds="[0,300][300,500]")
    node(unavailable, "缺货登记", PREFIX + "tv_tag")
    add_sku_option(price, text="看台580元", bounds="[310,300][610,500]")
    add_sku_option(price, bounds="[0,510][300,710]")

    page = parse(root, config)

    assert page.stage == "sku"
    assert page.quantity is None
    assert page.sku_options == [
        {"bounds": (0, 300, 300, 500), "unavailable": True, "price": None},
        {"bounds": (310, 300, 610, 500), "unavailable": False, "price": "580"},
        {"bounds": (0, 510, 300, 710), "unavailable": False, "price": None},
    ]
    assert page.can_submit is False
    json.dumps(asdict(page), ensure_ascii=False)


def test_sku_options_do_not_duplicate_inner_perform_items(config):
    root, _, price, _, _ = sku()
    option = add_sku_option(price)
    inner = node(option, resource_id=PREFIX + "ll_perform_item",
                 **{"class": "android.widget.LinearLayout", "clickable": "true"})
    node(inner, "580元")

    page = parse(root, config)

    assert len(page.sku_options) == 1
    assert page.sku_options[0]["bounds"] == (0, 300, 300, 500)
    assert page.sku_options[0]["price"] == "580"


@pytest.mark.parametrize("text,resource_id,expected", [
    ("￥580.00", "", "580"), ("内场788元", "", "788"),
    ("580元，每人限购4张", "", "580"), ("¥1,088", "", "1088"),
    ("580", PREFIX + "tv_price", "580"), ("580", "", None),
    ("第1档", "", None), ("原价580元，现价480元", "", None),
])
def test_option_price_uses_explicit_price_evidence_and_preserves_other_tier_prices(
        config, text, resource_id, expected):
    root, _, price, _, _ = sku()
    option = add_sku_option(price)
    node(option, text, resource_id)

    page = parse(root, config)

    assert page.sku_options[0]["price"] == expected
    assert config.price == "看台580元"


@pytest.mark.parametrize("label", ["缺货登记", "提交缺货登记", "已售罄", "售罄"])
def test_unavailable_option_is_reported_without_declaring_entire_sku_sold_out(config, label):
    root, _, price, _, _ = sku()
    option = add_sku_option(price)
    row = node(option, resource_id=PREFIX + "ll_perform_item")
    node(row, label)
    add_sku_option(price, text="580元", bounds="[310,300][610,500]")

    page = parse(root, config)

    assert page.stage == "sku"
    assert [item["unavailable"] for item in page.sku_options] == [True, False]


def test_disabled_option_is_unavailable_even_when_stock_label_is_hidden(config):
    root, _, price, _, _ = sku()
    add_sku_option(price, enabled="false")

    assert parse(root, config).sku_options[0]["unavailable"] is True


def test_hidden_invalid_and_non_option_nodes_are_not_exposed_as_price_choices(config):
    root, _, price, _, _ = sku()
    add_sku_option(price, displayed="false")
    add_sku_option(price, bounds="[0,0][0,100]")
    node(price, "580元", clickable="true")  # Unrecognized TextView is not a selectable price tile.
    node(price, resource_id=PREFIX + "ll_perform_item", **{"class": "android.widget.LinearLayout"})

    assert parse(root, config).sku_options == []


def test_matching_sku_exposes_only_known_number_buttons_with_native_bounds(config):
    root, _, price, footer, _ = sku()
    counter = node(footer, resource_id=PREFIX + "layout_num")
    inner = node(counter, resource_id=PREFIX + "layout_sku_num_ll")
    node(inner, "3张", PREFIX + "tv_num")
    node(inner, resource_id=PREFIX + "img_jian", bounds="[700,2200][790,2300]")
    node(inner, resource_id=PREFIX + "img_jia", bounds="[1000,2200][1100,2300]")
    node(price, resource_id=PREFIX + "img_jia", bounds="[0,0][100,100]")

    page = parse(root, config)

    assert page.quantity == 3
    assert page.quantity_increase_bounds == (1000, 2200, 1100, 2300)
    assert page.quantity_decrease_bounds == (700, 2200, 790, 2300)


def test_quantity_buttons_are_not_inferred_from_unrelated_ids_or_screen_position(config):
    root, layout, _, _, _ = sku()
    node(layout, resource_id=PREFIX + "img_jia", bounds="[1000,2200][1100,2300]")
    node(layout, resource_id=PREFIX + "img_jian", bounds="[700,2200][790,2300]")
    counter = node(layout, resource_id=PREFIX + "layout_num")
    node(counter, "+", bounds="[1000,2200][1100,2300]")
    node(counter, "-", bounds="[700,2200][790,2300]")

    page = parse(root, config)

    assert page.quantity_increase_bounds is None
    assert page.quantity_decrease_bounds is None


def test_inactive_and_ambiguous_quantity_buttons_have_no_action_bounds(config):
    root, _, _, footer, _ = sku()
    counter = node(footer, resource_id=PREFIX + "layout_num")
    node(counter, resource_id=PREFIX + "img_jia", enabled="false")
    node(counter, resource_id=PREFIX + "img_jian", bounds="[0,100][100,200]")
    node(counter, resource_id=PREFIX + "img_jian", bounds="[0,300][100,400]")

    page = parse(root, config)

    assert page.quantity_increase_bounds is None
    assert page.quantity_decrease_bounds is None


def test_wrong_event_sku_exposes_no_option_or_quantity_actions_even_with_prior_context(config):
    root, _, price, footer, _ = sku(title="上海·其他歌手演唱会")
    add_sku_option(price, text="580元")
    counter = node(footer, resource_id=PREFIX + "layout_num")
    node(counter, resource_id=PREFIX + "img_jia")
    node(counter, resource_id=PREFIX + "img_jian")
    config.target_verified = True

    page = parse(root, config)

    assert page.sku_options == []
    assert page.quantity_increase_bounds is None
    assert page.quantity_decrease_bounds is None
    assert page.action_bounds is None
