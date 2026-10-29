import json
from xml.etree import ElementTree

from damai_appium.page_diagnostics import summarize_page


TITLE_ID = "cn.damai:id/info_v2_title_tv1"
PURCHASE_BAR = "cn.damai:id/trade_project_detail_purchase_status_bar_container_fl"


def add_node(parent, resource_id="", text="", description="", **attrs):
    values = {
        "package": "cn.damai", "resource-id": resource_id, "text": text,
        "content-desc": description, "enabled": "true", "displayed": "true",
        "clickable": "false", "class": "android.widget.TextView",
    }
    values.update(attrs)
    return ElementTree.SubElement(parent, "node", values)


def serialize(root):
    return ElementTree.tostring(root, encoding="unicode")


def test_summary_excludes_personal_information_and_arbitrary_page_text():
    root = ElementTree.Element("hierarchy")
    add_node(root, TITLE_ID, "合肥·李健演唱会")
    name = "测试观众甲"
    identity = "110101199001011234"
    phone = "13800138000"
    add_node(root, "cn.damai:id/audience_name", name)
    add_node(root, "cn.damai:id/identity", identity)
    add_node(root, "cn.damai:id/mobile", description=phone)
    bar = add_node(root, PURCHASE_BAR)
    add_node(bar, text="立即购买")
    add_node(bar, "cn.damai:id/private_nested_field", text=name, description=f"证件{identity} 手机{phone}")
    add_node(bar, text="立即购买 " + phone)

    summary = summarize_page(serialize(root), "李健", "合肥")
    encoded = json.dumps(summary, ensure_ascii=False)

    for value in (name, identity, phone):
        assert value not in encoded
    assert "cn.damai:id/audience_name" in summary["resource_ids"]
    assert "cn.damai:id/private_nested_field" in summary["resource_ids"]
    assert any(control.get("text") == "立即购买" for control in summary["purchase_controls"])
    assert "<hierarchy" not in encoded


def test_known_title_controls_include_text_and_match_results():
    root = ElementTree.Element("hierarchy")
    add_node(root, TITLE_ID, "合肥·李健演唱会")
    add_node(root, "cn.damai:id/title_tv", "北京·其他演出")
    add_node(root, "cn.damai:id/unknown_title", "不得保存的其他标题")

    summary = summarize_page(serialize(root), "李健", "合肥")

    assert len(summary["known_title_controls"]) == 2
    title = summary["known_title_controls"][0]
    assert title["text"] == "合肥·李健演唱会"
    assert title["keyword_matches"] is True
    assert title["city_matches"] is True
    assert title["visible"] is True
    other = summary["known_title_controls"][1]
    assert other["keyword_matches"] is False
    assert other["city_matches"] is False
    assert "不得保存的其他标题" not in json.dumps(summary, ensure_ascii=False)


def test_title_content_description_is_preserved_and_matched():
    root = ElementTree.Element("hierarchy")
    parent = add_node(root, displayed="false")
    add_node(parent, TITLE_ID, description="合肥·李健演唱会")

    summary = summarize_page(serialize(root), "李健", "合肥")

    title = summary["known_title_controls"][0]
    assert title["text"] == ""
    assert title["content-desc"] == "合肥·李健演唱会"
    assert title["keyword_matches"] is True
    assert title["city_matches"] is True
    assert title["visible"] is False


def test_title_numbers_are_redacted():
    root = ElementTree.Element("hierarchy")
    add_node(root, TITLE_ID, "李健 13800138000", "合肥 110101199001011234")

    summary = summarize_page(serialize(root), "李健", "合肥")
    encoded = json.dumps(summary, ensure_ascii=False)

    assert "13800138000" not in encoded
    assert "110101199001011234" not in encoded
    assert summary["known_title_controls"][0]["keyword_matches"] is True


def test_resource_ids_are_unique_and_do_not_export_unknown_control_text():
    root = ElementTree.Element("hierarchy")
    for _ in range(2):
        add_node(root, "cn.damai:id/new_unknown_control", "动态隐私内容")
    add_node(root, "foreign.app:id/private", "外部应用文本", package="foreign.app")

    summary = summarize_page(serialize(root), "李健", "合肥")

    assert summary["resource_ids"] == ["cn.damai:id/new_unknown_control"]
    assert summary["purchase_controls"] == []
    assert "动态隐私内容" not in json.dumps(summary, ensure_ascii=False)


def test_purchase_descendants_only_keep_exact_whitelisted_labels_and_structure():
    root = ElementTree.Element("hierarchy")
    bar = add_node(root, PURCHASE_BAR, clickable="true", enabled="false")
    price = add_node(bar, "cn.damai:id/project_detail_perform_price_flowlayout")
    add_node(price, "cn.damai:id/price", "看台380元", "测试观众乙")
    add_node(bar, "cn.damai:id/btn_buy_view", text="确定", description="已预约")
    add_node(root, "cn.damai:id/reservation_heading", "预约想看票档")
    add_node(root, text="预约想看票档 测试观众乙")

    summary = summarize_page(serialize(root), "李健", "合肥")

    assert len(summary["purchase_controls"]) == 4
    assert summary["purchase_controls"][0]["enabled"] is False
    assert summary["purchase_controls"][0]["clickable"] is True
    assert summary["purchase_controls"][0]["visible"] is True
    assert "text" not in summary["purchase_controls"][2]
    assert "content-desc" not in summary["purchase_controls"][2]
    assert summary["purchase_controls"][3]["text"] == "确定"
    assert summary["purchase_controls"][3]["content-desc"] == "已预约"
    assert summary["reservation_labels"] == ["已预约", "预约想看票档"]
    assert "测试观众乙" not in json.dumps(summary, ensure_ascii=False)


def test_invalid_xml_returns_safe_empty_summary_without_parser_input():
    summary = summarize_page("<hierarchy private='13800138000'>", "李健", "合肥")

    assert summary["parser_error"] == "invalid_xml"
    assert summary["known_title_controls"] == []
    assert summary["resource_ids"] == []
    assert summary["purchase_controls"] == []
    assert "13800138000" not in json.dumps(summary)
