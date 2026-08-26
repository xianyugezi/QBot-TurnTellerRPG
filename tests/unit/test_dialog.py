"""对话会话状态机单测（M4 批次2·路C3 · qbot_rpg/core/dialog.py）。

依据：m4_shared_contract §3.1（会话路由 / 对话树 ≤ max_dialog_depth / 三词同义 / 菜单 ≤6 折叠）
+ 细化_2b2_对话会话状态机.md（七态 S0-S6 / 主迁移 T01-T15 / 会话路由 R1-R5 / 菜单折叠 §四 /
  无 NPC 提示 §五 / 恢复简报 §2.3 / 验收 TC-01~TC-21）
+ 审查参考/NPC系统设计定稿.md（L37-53 / L55-71 / L83-102 / L108-123 / L289 / L316-328）
+ 2026-08-27 裁决③（settings.max_dialog_depth 默认 2，0=不限，超深软拦）。

覆盖：/对话 参数解析（TC-01~08）· 会话子词/路由（R1-R5，TC-15~18）· 状态机主链（TC-09）·
条件不满足（TC-10）· 已听置灰（TC-11）· 长叙述翻页（TC-12）· 结束词三同义（TC-13）·
子界面中断恢复（TC-14）· 菜单折叠（TC-19/20/21）· 深度可配（裁决③）· 恢复简报 · 事件计数 ·
15 迁移全覆盖 · 快照 round-trip。
"""

from __future__ import annotations

import pytest

from qbot_rpg.core.dialog import (
    DIALOG_ALREADY_HEARD_HINT,
    DIALOG_DEPTH_HINT,
    DIALOG_EMPTY_MAP_HINT,
    DIALOG_NOT_FOUND_HINT,
    DEFAULT_MAX_DIALOG_DEPTH,
    S_END,
    S_EXEC,
    S_IDLE,
    S_LIST,
    S_MENU,
    S_NPCSEL,
    S_SUBUI,
    TRANSITION_COUNT,
    TRANSITION_IDS,
    DialogSession,
    authored_node_depth,
    build_resume_brief,
    classify_session_input,
    condition_hint,
    dialog_event_key,
    is_depth_blocked,
    parse_dialog_command,
    render_interaction_menu,
    render_npc_list,
    resolve_max_dialog_depth,
    resolve_menu_selection,
    route_session_input,
)

# ---------------------------------------------------------------------------
# 夹具：当前地图 NPC 列表 + 状态机 ctx
# ---------------------------------------------------------------------------

NPC_LAO = {
    "id": "blacksmith_lao",
    "name": "铁匠·老周",
    "icon": "🔨",
    "type": "quest_giver",
    "visible": True,
    "interactions": [
        {"action": "quest", "text": "接点活儿"},
        {"action": "shop", "text": "打开商店", "shop_refs": ["blacksmith_shop"]},
        {"action": "heal", "text": "帮忙治疗",
         "condition": {"var": "level", "op": "ge", "value": 10}},
        {"action": "intel", "text": "打听消息", "info": True, "info_key": "intel:lao:1",
         "lines": ["村北的矿洞最近闹鬼……", "据说和铁矿有关。"]},
    ],
}

NPC_LIN = {
    "id": "grocer_lin",
    "name": "杂货商人·林",
    "icon": "🧺",
    "type": "merchant",
    "visible": True,
    "interactions": [
        {"action": "shop", "text": "看看货物", "shop_refs": ["grocer_shop"]},
        {"action": "reply", "text": "随便聊聊"},
    ],
}

NPC_DU = {
    "id": "scholar_du2",
    "name": "学者·杜Ⅱ",
    "icon": "📖",
    "type": "intel_giver",
    "visible": True,
    "interactions": [
        {"action": "intel", "text": "讲讲历史", "info": True, "info_key": "intel:du:1",
         "lines": ["这座城的城墙比你还老。", "地下的水道藏着一座旧城。"]},
    ],
}

MAP_NPCS = [NPC_LAO, NPC_LIN, NPC_DU]


def make_ctx(**overrides) -> dict:
    """默认状态机 ctx：当前地图 3 个 visible NPC；无条件 hook（A2 求值 → 默认不满足用于条件测试）。"""
    ctx = {
        "npcs": MAP_NPCS,
        "settings": {"max_dialog_depth": DEFAULT_MAX_DIALOG_DEPTH},
        "heard": set(),
        "eval_condition": lambda cond, cctx: bool(
            cctx and cctx.get("level", 0) >= (cond.get("value") if isinstance(cond, dict) else 0)),
        "condition_ctx": {"level": 1},
        **overrides,
    }
    return ctx


def trace_ids(result: dict) -> set:
    return {t for t, _ in result["trace"]}


# ===========================================================================
# 一、/对话 参数解析（2b2 §一 · TC-01 ~ TC-08）
# ===========================================================================
def test_parse_dialog_no_args_list():
    assert parse_dialog_command(None, MAP_NPCS) == {"mode": "list"}
    assert parse_dialog_command("", MAP_NPCS) == {"mode": "list"}
    assert parse_dialog_command("   ", MAP_NPCS) == {"mode": "list"}


def test_parse_dialog_name_priority_over_digit():
    # 名称优先：即便名字是纯数字形态也按名称（L42）
    assert parse_dialog_command("铁匠·老周", MAP_NPCS) == {"mode": "name", "value": "铁匠·老周"}


def test_parse_dialog_index_fallback():
    assert parse_dialog_command("1", MAP_NPCS) == {"mode": "index", "value": 1}
    assert parse_dialog_command("9", MAP_NPCS) == {"mode": "index", "value": 9}


def test_parse_dialog_space_name_never_matches():
    # L49 名称禁空格：含空格参数必然无法命中任何名称
    assert parse_dialog_command("铁匠 老周", MAP_NPCS) == {"mode": "name", "value": "铁匠 老周"}


def test_parse_dialog_dot_roman_allowed():
    # L49 允许 · / Ⅱ
    assert parse_dialog_command("学者·杜Ⅱ", MAP_NPCS) == {"mode": "name", "value": "学者·杜Ⅱ"}


# ===========================================================================
# 二、会话子词分类 + 路由（2b2 §三 R1-R5 · TC-13/15/16/17/18）
# ===========================================================================
def test_classify_session_subwords():
    assert classify_session_input("1") == ("digit", 1)
    assert classify_session_input("继续") == ("continue", None)
    assert classify_session_input("选择 2") == ("select", 2)
    assert classify_session_input("选择2") == ("select", 2)
    for w in ("离开", "再见", "退出"):
        assert classify_session_input(w) == ("exit", None)


def test_classify_non_subword_returns_none():
    assert classify_session_input("攻击1") is None
    assert classify_session_input("使用1") is None
    assert classify_session_input("背包2") is None
    assert classify_session_input("") is None
    assert classify_session_input(None) is None


def test_route_session_active_subword_goes_session():
    # R1/R3：会话激活中纯数字 → 送状态机（不触发快捷，TC-15）
    assert route_session_input("1", session_active=True) == {
        "kind": "session", "subword": ("digit", 1)}


def test_route_session_active_command_word_normal_parse():
    # R2：会话中带指令词照常解析（TC-16）
    for t in ("攻击1", "使用1", "背包2"):
        assert route_session_input(t, session_active=True) == {
            "kind": "command", "subword": None}


def test_route_no_session_shortcut_domain():
    # R4：无会话 → 快捷表/常规指令（TC-17）
    assert route_session_input("1", session_active=False) == {
        "kind": "command", "subword": None}


# ===========================================================================
# 三、状态机主链（TC-09）与迁移
# ===========================================================================
def test_tc01_no_args_list_enters_s1():
    s = DialogSession()
    r = s.step(("dialog", {"mode": "list"}), make_ctx())
    assert r["transition"] == "T01"
    assert r["to_state"] == S_LIST
    assert r["session_active"] is True
    assert r["output"][0] == "这里的人：1.🔨铁匠·老周 2.🧺杂货商人·林 3.📖学者·杜Ⅱ"


def test_tc02_index_shortcut_to_menu():
    s = DialogSession()
    r = s.step(("dialog", {"mode": "index", "value": 1}), make_ctx())
    assert r["to_state"] == S_MENU
    assert r["snapshot"]["npc_id"] == "blacksmith_lao"
    assert trace_ids(r) == {"T02", "T05"}
    assert "铁匠·老周：" in r["output"][0]
    assert "5.离开" in r["output"]


def test_tc03_name_dialog_to_menu():
    s = DialogSession()
    r = s.step(("dialog", {"mode": "name", "value": "铁匠·老周"}), make_ctx())
    assert r["to_state"] == S_MENU
    assert r["snapshot"]["npc_id"] == "blacksmith_lao"


def test_tc04_name_special_chars():
    s = DialogSession()
    r = s.step(("dialog", {"mode": "name", "value": "学者·杜Ⅱ"}), make_ctx())
    assert r["to_state"] == S_MENU
    assert r["snapshot"]["npc_id"] == "scholar_du2"


def test_tc05_space_name_not_found_no_session():
    s = DialogSession()
    r = s.step(("dialog", {"mode": "name", "value": "铁匠 老周"}), make_ctx())
    assert r["to_state"] == S_IDLE
    assert r["session_active"] is False
    assert DIALOG_NOT_FOUND_HINT in r["output"]


def test_tc06_index_out_of_range_back_to_list():
    s = DialogSession()
    r = s.step(("dialog", {"mode": "index", "value": 9}), make_ctx())
    assert r["to_state"] == S_LIST
    assert "没有 9 号" in r["output"][0]
    assert trace_ids(r) == {"T02", "T06"}


def test_tc07_name_not_found_no_session():
    s = DialogSession()
    r = s.step(("dialog", {"mode": "name", "value": "不存在的人"}), make_ctx())
    assert r["to_state"] == S_IDLE
    assert r["session_active"] is False
    assert DIALOG_NOT_FOUND_HINT in r["output"]


def test_tc08_empty_map_hint_no_session():
    s = DialogSession()
    r = s.step(("dialog", {"mode": "list"}), make_ctx(npcs=[]))
    assert r["to_state"] == S_IDLE
    assert r["session_active"] is False
    assert DIALOG_EMPTY_MAP_HINT in r["output"]


def test_tc09_full_main_chain_shop():
    """/对话 1 → 选择 2（打开商店）→ 交付 → N.离开：S0→S2→S3→S4→S3→S6→S0。"""
    s = DialogSession()
    ctx = make_ctx()
    r = s.step(("dialog", {"mode": "index", "value": 1}), ctx)
    assert r["to_state"] == S_MENU
    # 选择 2 = 打开商店 → T07 EXEC
    r = s.step(("select", 2), ctx)
    assert r["transition"] == "T07"
    assert r["to_state"] == S_EXEC
    assert r["action"]["action"] == "shop"
    assert r["handoff"] == {"type": "shop", "shop_refs": ["blacksmith_shop"]}
    # 交付（商店独立交付路径，2b3）→ T10 回菜单
    r = s.step(("exec_done", {"shop_refs": ["blacksmith_shop"]}), ctx)
    assert r["transition"] == "T10"
    assert r["to_state"] == S_MENU
    assert "已打开商店：blacksmith_shop" in r["output"]
    # N.离开（5 = 4 选项 + 1）→ T09 → T15 → S0
    r = s.step(("select", 5), ctx)
    assert r["to_state"] == S_IDLE
    assert r["session_active"] is False
    assert trace_ids(r) == {"T09", "T15"}


def test_tc09_select_N_equivalent_to_digit():
    s = DialogSession()
    ctx = make_ctx()
    s.step(("dialog", {"mode": "index", "value": 1}), ctx)
    r = s.step(("select", 1), ctx)  # 选择 1 = 接点活儿
    assert r["transition"] == "T07"
    assert r["action"]["action"] == "quest"


def test_tc10_condition_unmet_stays_menu():
    s = DialogSession()
    ctx = make_ctx(condition_ctx={"level": 1})  # 等级不足
    s.step(("dialog", {"mode": "index", "value": 1}), ctx)
    r = s.step(("select", 3), ctx)  # 帮忙治疗：需要等级≥10
    assert r["transition"] == "T08"
    assert r["to_state"] == S_MENU
    assert r["output"][0] == "需要：等级 ≥10"


def test_tc11_heard_gray_and_reselect():
    s = DialogSession()
    ctx = make_ctx()
    s.step(("dialog", {"mode": "index", "value": 1}), ctx)
    # 交付情报（多段叙述）
    r = s.step(("select", 4), ctx)
    assert r["transition"] == "T07"
    assert r["output"][0] == "村北的矿洞最近闹鬼……"
    r = s.step(("continue", None), ctx)
    assert r["transition"] == "T11"
    assert r["output"][0] == "据说和铁矿有关。"
    r = s.step(("continue", None), ctx)  # 末段 → 单轮交付回菜单
    assert r["transition"] == "T10"
    assert r["mark_heard"] == ["intel:lao:1"]
    # 玩家存档已写入 heard，重选同项 → 「你已经听过了」
    ctx["heard"] = {"intel:lao:1"}
    r = s.step(("select", 4), ctx)
    assert r["to_state"] == S_MENU
    assert DIALOG_ALREADY_HEARD_HINT in r["output"]


def test_tc12_long_narration_page_index_snapshot():
    s = DialogSession()
    ctx = make_ctx()
    s.step(("dialog", {"mode": "index", "value": 1}), ctx)
    s.step(("select", 4), ctx)
    r = s.step(("continue", None), ctx)
    assert r["transition"] == "T11"
    assert r["snapshot"]["page_index"] == 1
    assert r["snapshot"]["state"] == S_EXEC


def test_tc13_exit_words_synonym():
    for w in ("离开", "再见", "退出"):
        s = DialogSession()
        ctx = make_ctx()
        s.step(("dialog", {"mode": "index", "value": 1}), ctx)
        r = s.step(("exit", None), ctx)
        assert r["to_state"] == S_IDLE, f"{w} 应结束会话"
        assert trace_ids(r) == {"T09", "T15"}


def test_tc13_exit_from_list_t04():
    s = DialogSession()
    ctx = make_ctx()
    s.step(("dialog", {"mode": "list"}), ctx)
    r = s.step(("exit", None), ctx)
    assert trace_ids(r) == {"T04", "T15"}
    assert r["to_state"] == S_IDLE


def test_tc14_subui_interrupt_resume():
    s = DialogSession()
    ctx = make_ctx()
    s.step(("dialog", {"mode": "index", "value": 1}), ctx)
    s.step(("select", 2), ctx)  # shop
    r = s.step(("exec_done", {"subui": True, "label": "帮忙治疗"}), ctx)
    assert r["transition"] == "T12"
    assert r["to_state"] == S_SUBUI
    snap = s.to_snapshot()
    # 中断恢复：简报注明未完成
    brief = build_resume_brief(snap)
    assert brief is not None
    assert "上次的『帮忙治疗』未完成" in brief
    # 重入会话（from_snapshot）→ 确认完成 → T13 回菜单
    s2 = DialogSession.from_snapshot(snap)
    r2 = s2.step(("confirm_done", {"completed": True}), make_ctx())
    assert r2["transition"] == "T13"
    assert r2["to_state"] == S_MENU


def test_t14_exit_from_subui():
    s = DialogSession()
    ctx = make_ctx()
    s.step(("dialog", {"mode": "index", "value": 1}), ctx)
    s.step(("select", 2), ctx)
    s.step(("exec_done", {"subui": True, "label": "领取补给"}), ctx)
    r = s.step(("exit", None), ctx)
    assert trace_ids(r) == {"T14", "T15"}
    assert r["to_state"] == S_IDLE


def test_t04_t06_via_list_pick():
    # T03 列表选人：会话激活中纯数字 → 选 NPC
    s = DialogSession()
    ctx = make_ctx()
    s.step(("dialog", {"mode": "list"}), ctx)
    r = s.step(("digit", 2), ctx)
    assert r["to_state"] == S_MENU
    assert r["snapshot"]["npc_id"] == "grocer_lin"
    assert trace_ids(r) == {"T03", "T05"}
    # T03 失败：纯数字超界 → T06 回列表
    s2 = DialogSession()
    s2.step(("dialog", {"mode": "list"}), ctx)
    r2 = s2.step(("digit", 99), ctx)
    assert r2["to_state"] == S_LIST
    assert trace_ids(r2) == {"T03", "T06"}
    assert "没有 99 号" in r2["output"][0]


# ===========================================================================
# 四、菜单折叠（§四 · TC-19/20/21）
# ===========================================================================
def test_render_menu_six_options_exact_tc19():
    its = [{"action": "reply", "text": f"选项{i}"} for i in range(1, 7)]
    menu = render_interaction_menu(its)
    assert menu["folded"] is False
    assert menu["leave_no"] == 7
    assert menu["lines"][-1] == "7.离开"
    assert len(menu["lines"]) == 7


def test_render_menu_fold_over_six_tc20():
    its = [{"action": "reply", "text": f"选项{i}"} for i in range(1, 9)]
    menu = render_interaction_menu(its)
    assert menu["folded"] is True
    assert menu["shown"] == 6
    assert menu["more_no"] == 7
    assert menu["leave_no"] == 8
    assert menu["lines"] == [
        "1.选项1", "2.选项2", "3.选项3", "4.选项4", "5.选项5", "6.选项6",
        "7.更多…", "8.离开",
    ]
    # 二级页：续显 7-8 + 本页离开
    page2 = render_interaction_menu(its, page=1)
    assert page2["lines"] == ["7.选项7", "8.选项8", "3.离开"]


def test_render_menu_condition_one_line_tc21():
    its = [
        {"action": "shop", "text": "看看货物",
         "condition": {"var": "level", "op": "ge", "value": 5}},
        {"action": "heal", "text": "帮忙治疗"},
    ]
    menu = render_interaction_menu(its, conditions={0: False})
    assert "（需要：等级 ≥5）" in menu["lines"][0]
    assert len(menu["lines"][0]) < 40  # 一行，不展开长文本


def test_render_menu_heard_gray():
    its = [{"action": "intel", "text": "打听消息", "info": True, "info_key": "intel:a:1"}]
    menu = render_interaction_menu(its, heard={"intel:a:1"})
    assert "（已听）" in menu["lines"][0]


def test_resolve_menu_selection():
    its = [{"action": "reply", "text": "a"} for _ in range(8)]
    m0 = render_interaction_menu(its)
    assert resolve_menu_selection(m0, 3) == ("option", 2)
    assert resolve_menu_selection(m0, 7) == ("more", None)
    assert resolve_menu_selection(m0, 8) == ("leave", None)
    assert resolve_menu_selection(m0, 9) == ("invalid", None)
    m1 = render_interaction_menu(its, page=1)
    assert resolve_menu_selection(m1, 7) == ("option", 6)
    assert resolve_menu_selection(m1, 3) == ("leave", None)


def test_menu_fold_navigation_in_state_machine():
    many = [{"action": "reply", "text": f"选项{i}"} for i in range(1, 9)]
    npc = {"id": "n", "name": "多选项NPC", "icon": "?", "visible": True,
           "interactions": many}
    ctx = make_ctx(npcs=[npc])
    s = DialogSession()
    s.step(("dialog", {"mode": "index", "value": 1}), ctx)
    r = s.step(("select", 7), ctx)  # 「7.更多…」→ 二级页
    assert r["to_state"] == S_MENU
    assert "7.选项7" in r["output"]
    r = s.step(("select", 7), ctx)  # 二级页选 7.选项7
    assert r["transition"] == "T07"
    assert r["action"]["text"] == "选项7"


# ===========================================================================
# 五、对话树深度可配（2026-08-27 裁决③ / L324/L328）
# ===========================================================================
def test_resolve_max_dialog_depth_default_and_config():
    assert resolve_max_dialog_depth(None) == 2
    assert resolve_max_dialog_depth({}) == 2
    assert resolve_max_dialog_depth({"max_dialog_depth": 0}) == 0   # 0=不限
    assert resolve_max_dialog_depth({"max_dialog_depth": 5}) == 5
    assert resolve_max_dialog_depth({"max_dialog_depth": -1}) == 2  # 非法 → 默认
    assert resolve_max_dialog_depth({"max_dialog_depth": "x"}) == 2
    assert resolve_max_dialog_depth({"max_dialog_depth": True}) == 2


def test_is_depth_blocked_zero_unlimited():
    assert is_depth_blocked(3, 2) is True
    assert is_depth_blocked(2, 2) is False
    assert is_depth_blocked(3, 0) is False   # 0=不限不拦
    assert is_depth_blocked(10, 0) is False


def test_authored_node_depth_flat_and_nested():
    assert authored_node_depth({"action": "shop"}) == 1
    deep = {
        "action": "reply",
        "sub_dialog": {"greeting": "g", "options": [
            {"action": "reply", "text": "a", "sub_dialog": {"options": [
                {"action": "reply", "text": "leaf"}]}},
        ]},
    }
    assert authored_node_depth(deep) == 3


def test_depth_soft_block_at_default_2():
    deep = {
        "action": "reply", "text": "深入话题",
        "sub_dialog": {"greeting": "第一层", "options": [
            {"action": "reply", "text": "第二层", "sub_dialog": {
                "greeting": "第三层",
                "options": [{"action": "reply", "text": "太深了"}]}},
        ]},
    }
    npc = {"id": "n", "name": "深NPC", "icon": "?", "visible": True,
           "interactions": [deep]}
    ctx = make_ctx(npcs=[npc], settings={"max_dialog_depth": 2})
    s = DialogSession()
    s.step(("dialog", {"mode": "index", "value": 1}), ctx)
    r = s.step(("select", 1), ctx)
    assert r["to_state"] == S_MENU          # 软拦：留菜单
    assert r["kind"] == "depth_blocked"
    assert DIALOG_DEPTH_HINT in r["output"]


def test_depth_zero_unlimited_no_block():
    deep = {
        "action": "reply", "text": "深入话题",
        "sub_dialog": {"greeting": "第一层", "options": [
            {"action": "reply", "text": "第二层", "sub_dialog": {
                "greeting": "第三层",
                "options": [{"action": "reply", "text": "太深了"}]}},
        ]},
    }
    npc = {"id": "n", "name": "深NPC", "icon": "?", "visible": True,
           "interactions": [deep]}
    ctx = make_ctx(npcs=[npc], settings={"max_dialog_depth": 0})
    s = DialogSession()
    s.step(("dialog", {"mode": "index", "value": 1}), ctx)
    r = s.step(("select", 1), ctx)
    assert r["transition"] == "T07"         # 0=不限不拦
    assert r["to_state"] == S_EXEC
    assert r["output"][0] == "第一层"


def test_flat_interactions_never_depth_blocked():
    # 默认 2：平铺 interactions（深度 1）永不触发软拦
    ctx = make_ctx()
    s = DialogSession()
    s.step(("dialog", {"mode": "index", "value": 1}), ctx)
    r = s.step(("select", 1), ctx)
    assert r["transition"] == "T07"
    assert r["to_state"] == S_EXEC


# ===========================================================================
# 六、恢复简报（2b2 §2.3 · L94-102）
# ===========================================================================
def test_resume_brief_idle_end_none():
    assert build_resume_brief({"state": S_IDLE}) is None
    assert build_resume_brief({"state": S_END}) is None


def test_resume_brief_menu_layer():
    s = DialogSession(state=S_MENU, npc_id="blacksmith_lao", npc_name="铁匠·老周")
    assert build_resume_brief(s.to_snapshot()) == "【续·对话】铁匠·老周"


def test_resume_brief_exec_page_index():
    s = DialogSession(state=S_EXEC, npc_id="blacksmith_lao", npc_name="铁匠·老周", page_index=1)
    brief = build_resume_brief(s.to_snapshot())
    assert brief == "【续·对话】铁匠·老周 · 已读第 2 段，继续阅读"


def test_resume_brief_subui_label():
    s = DialogSession(state=S_SUBUI, npc_id="blacksmith_lao", npc_name="铁匠·老周",
                      subui_label="领取补给")
    brief = build_resume_brief(s.to_snapshot())
    assert brief == "【续·对话】铁匠·老周 · 上次的『领取补给』未完成，请重新选择"


# ===========================================================================
# 七、事件计数（T15 · L289）
# ===========================================================================
def test_dialog_event_key():
    assert dialog_event_key("blacksmith_lao") == "[事件:NPC对话:blacksmith_lao]"


def test_end_fires_event_count_once():
    s = DialogSession()
    ctx = make_ctx()
    s.step(("dialog", {"mode": "index", "value": 1}), ctx)
    r = s.step(("exit", None), ctx)
    assert r["events"] == ["[事件:NPC对话:blacksmith_lao]"]
    assert r["ended"] == "T09"


# ===========================================================================
# 八、状态机不变量：15 迁移全覆盖 + 中断不迁移 + 快照 round-trip
# ===========================================================================
def test_transition_table_has_exactly_15():
    assert TRANSITION_COUNT == 15
    assert len(set(TRANSITION_IDS)) == 15


def test_grand_tour_covers_all_15_transitions():
    seen = set()
    ctx = make_ctx()
    s = DialogSession()

    def cap(r):
        seen.update(t for t, _ in r["trace"])
        return r

    cap(s.step(("dialog", {"mode": "list"}), ctx))                       # T01
    cap(s.step(("digit", 1), ctx))                                       # T03+T05
    assert s.state == S_MENU
    cap(s.step(("select", 3), ctx))                                      # T08 条件不满足
    cap(s.step(("select", 2), ctx))                                      # T07 shop
    cap(s.step(("exec_done", {"shop_refs": ["blacksmith_shop"]}), ctx))  # T10
    cap(s.step(("select", 4), ctx))                                      # T07 intel
    cap(s.step(("continue", None), ctx))                                 # T11
    cap(s.step(("continue", None), ctx))                                 # T10 末段
    cap(s.step(("select", 2), ctx))                                      # T07 shop 复用
    cap(s.step(("exec_done", {"subui": True, "label": "帮忙治疗"}), ctx))  # T12
    cap(s.step(("confirm_done", {"completed": True}), ctx))              # T13
    assert s.state == S_MENU
    cap(s.step(("select", 5), ctx))                                      # T09+T15 离开
    assert s.state == S_IDLE
    cap(s.step(("dialog", {"mode": "index", "value": 9}), ctx))          # T02+T06
    assert s.state == S_LIST
    cap(s.step(("exit", None), ctx))                                     # T04+T15
    assert s.state == S_IDLE
    cap(s.step(("dialog", {"mode": "name", "value": "铁匠·老周"}), ctx))  # T02+T05
    assert s.state == S_MENU
    cap(s.step(("select", 2), ctx))                                      # T07
    cap(s.step(("exec_done", {"subui": True, "label": "领取补给"}), ctx))  # T12
    cap(s.step(("exit", None), ctx))                                     # T14+T15
    assert s.state == S_IDLE

    assert seen == set(TRANSITION_IDS)


def test_interrupt_does_not_migrate_state():
    s = DialogSession()
    ctx = make_ctx()
    s.step(("dialog", {"mode": "index", "value": 1}), ctx)
    r = s.step(("interrupt", None), ctx)
    assert r["kind"] == "interrupted"
    assert r["transition"] is None
    assert r["to_state"] == S_MENU
    assert s.state == S_MENU


def test_command_word_not_consumed_while_session_active():
    s = DialogSession()
    ctx = make_ctx()
    s.step(("dialog", {"mode": "index", "value": 1}), ctx)
    r = s.step("攻击1", ctx)   # 带指令词 → 不消费（R2，走正常解析）
    assert r["kind"] == "command"
    assert r["transition"] is None
    assert s.state == S_MENU
    r = s.step("1", ctx)       # 会话子词照常消费
    assert r["kind"] == "exec"
    assert s.state == S_EXEC


def test_idle_digit_not_consumed_after_end():
    s = DialogSession()
    ctx = make_ctx()
    s.step(("dialog", {"mode": "index", "value": 1}), ctx)
    s.step(("exit", None), ctx)
    r = s.step("1", ctx)       # 会话结束 → R4 快捷/常规指令，不消费
    assert r["kind"] == "idle_noop"
    assert r["transition"] is None
    assert s.state == S_IDLE


def test_snapshot_roundtrip_json_serializable():
    import json
    s = DialogSession()
    ctx = make_ctx()
    s.step(("dialog", {"mode": "index", "value": 1}), ctx)
    s.step(("select", 4), ctx)                     # intel EXEC
    s.step(("continue", None), ctx)                # page 1
    snap = s.to_snapshot()
    text = json.dumps(snap, ensure_ascii=False)    # JSON 可序列化
    s2 = DialogSession.from_snapshot(json.loads(text))
    assert s2.state == S_EXEC
    assert s2.npc_id == "blacksmith_lao"
    assert s2.page_index == 1
    assert s2.narration == ["村北的矿洞最近闹鬼……", "据说和铁矿有关。"]


def test_current_shop_ref_reported_via_handoff_only():
    # 裁决 T12/T13 修复：current_shop_ref 记录移到商店独立交付路径，本状态机只经结果上报
    s = DialogSession()
    ctx = make_ctx()
    s.step(("dialog", {"mode": "index", "value": 1}), ctx)
    r = s.step(("select", 2), ctx)
    assert r["handoff"]["type"] == "shop"
    r2 = s.step(("exec_done", {"shop_refs": ["blacksmith_shop"]}), ctx)
    assert r2["shop_refs"] == ["blacksmith_shop"]
    assert r2["handoff"] == {"type": "shop", "shop_refs": ["blacksmith_shop"]}
    assert r2["to_state"] == S_MENU   # 商店选购不在此层（S5 无选购分支）


# ===========================================================================
# 九、condition_hint 一行提示（L112）
# ===========================================================================
def test_condition_hint_one_line():
    assert condition_hint({"var": "level", "op": "ge", "value": 10}) == "需要：等级 ≥10"
    assert condition_hint({"var": "item_count", "op": "ge", "value": 50, "param": "铁矿"}) \
        == "需要：持有 ≥50（铁矿）"
    assert condition_hint(None) == "需要：条件未满足"
    assert condition_hint({"any": []}) == "需要：条件未满足"


# ===========================================================================
# 十、渲染辅助
# ===========================================================================
def test_render_npc_list_icon_and_name():
    lines = render_npc_list(MAP_NPCS)
    assert lines[0] == "这里的人：1.🔨铁匠·老周 2.🧺杂货商人·林 3.📖学者·杜Ⅱ"
