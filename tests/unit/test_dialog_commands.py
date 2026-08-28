"""M7 N-01 /对话 指令壳接线单测（qbot_rpg/commands/dialog_commands.py）。

依据：docs/细化/细化_M7_NPC对话接线.md（N-01 RN-01~RN-04 + TCN-01~TCN-12）+ 细化_2b2
（七态/十五迁移/中断恢复）+ 细化_2b1（dealer/发牌员/一次一物）。

集成口径：直接驱动**真实引擎** qbot_rpg/core/dialog.py（DialogSession/parse_dialog_command/
render_*）+ qbot_rpg/core/npc.py（dispatch_action/deal/mark_delivered），构造全字段 ctx
（npcs/heard/npc_delivered/settings/rng/event_counts/longline_counters/npc_rotate/...），
断言命令层输出与 ctx 副作用。零 NoneBot。

覆盖：注册与白名单 · 无参列表/空地图提示 · 序号/名称（名称优先/禁空格）· 会话子词
（digit/select/continue/exit）· 菜单 N.离开收尾 · 动作执行（quest/shop/heal/intel/reply）·
一次一物双轨键（heard + intel:{ref_id}）· 商店移交 · 发牌员（发牌/孤寂卡/rotate 推进）·
事件双表写入 · 中断恢复简报 · 快照落盘 · 收尾清理 · 会话路由（ROUTE_SESSION / R2 带指令词）。
"""

from __future__ import annotations

import random

from qbot_rpg.commands.dialog_commands import (
    DIALOG_CMD,
    cmd_dialog,
    cmd_dialog_confirm,
    cmd_dialog_interrupt,
    cmd_dialog_session,
    normalize_dialog_result,
    register_dialog_commands,
)
from qbot_rpg.commands.parsers import ParsedCommand
from qbot_rpg.commands.router import (
    ROUTE_COMMAND,
    ROUTE_SESSION,
    CommandSpec,
    Router,
    route_message,
)
from qbot_rpg.core.dialog import DialogSession, S_MENU, S_EXEC
from qbot_rpg.core.npc import is_delivered


# ---------------------------------------------------------------------------
# 夹具：NPC / ctx 工厂
# ---------------------------------------------------------------------------

BLACKSMITH = {
    "id": "blacksmith_zhou",
    "name": "铁匠·老周",
    "icon": "铁",
    "type": "blacksmith",
    "visible": True,
    "interactions": [
        {"text": "接任务", "action": "quest", "quests": [{"quest_id": "q_fetch"}]},
        {"text": "打开商店", "action": "shop", "shop_refs": ["blacksmith_shop"]},
        {"text": "帮忙治疗", "action": "heal", "cost": {"coins": 10}, "heal": {"hp": 50}},
        {"text": "打听消息", "action": "intel", "intel_refs": [{"id": "lore1"}]},
    ],
}

SHOPKEEP = {
    "id": "shopkeep_lin",
    "name": "杂货商人·林",
    "icon": "杂",
    "type": "merchant",
    "visible": True,
    "interactions": [
        {"text": "闲聊", "action": "reply", "lines": ["今天天气不错", "路上小心"]},
    ],
}

DEALER = {
    "id": "traveling_dealer",
    "name": "行商·骆驼",
    "icon": "行",
    "type": "dealer",
    "visible": True,
    "dialogues": {"greeting": "来抽一张吧"},
    "dealer": {
        "strategy": "condition",
        "pool": [
            {"id": "c1", "once": True,
             "deliver": {"action": "intel", "intel_refs": [{"id": "d1"}]}},
        ],
    },
    "interactions": [],
}

HIDDEN = {
    "id": "hidden_guy",
    "name": "隐者·影",
    "icon": "影",
    "type": "wanderer",
    "visible": False,
    "interactions": [],
}


def _fresh_ctx(**overrides) -> dict:
    """全新 ctx（每测试独立，避免会话/已听跨用例串扰）。"""
    ctx = {
        "registered": True,
        "npcs": [BLACKSMITH, SHOPKEEP, DEALER, HIDDEN],
        "heard": set(),
        "npc_delivered": {},
        "npc_rotate": {},
        "codex_state": {},
        "settings": {},
        "currencies": {"coins": 100},
        "hp": 80,
        "mp": 50,
        "max_hp": 100,
        "max_mp": 100,
        "inventory": {},
        "quest_active": [],
        "quest_completed": [],
        "quest_daily": {},
        "event_counts": {},
        "longline_counters": {},
        "current_shop_ref": [],
        "rng": random.Random(42),
        "dialog_active": False,
        "dialog_session": None,
    }
    ctx.update(overrides)
    return ctx


def _pc(*args: str) -> ParsedCommand:
    """构造 /对话 的 ParsedCommand（args 为 /对话 后的参数 token）。"""
    raw = ("/对话 " + " ".join(args)).strip()
    return ParsedCommand(raw, command=DIALOG_CMD, args=list(args))


def _menu_text(out: str) -> str:
    """取输出中的菜单区（忽略发牌员前置交付行）。"""
    return out


# ---------------------------------------------------------------------------
# 注册与白名单（RN-04）
# ---------------------------------------------------------------------------

def test_register_registers_dialog_command() -> None:
    """RN-04：register_dialog_commands 注册「对话」CommandSpec（白名单参与匹配）。"""
    router = Router()
    register_dialog_commands(router)
    spec = router.get(DIALOG_CMD)
    assert isinstance(spec, CommandSpec)
    assert spec.name == "对话"
    assert spec.whitelisted is True
    assert spec.handler is not None
    assert DIALOG_CMD in router.whitelist_names()


def test_register_without_make_context_raises() -> None:
    """RN-04：make_context=None 且无注入 ctx 时 handler 调用抛 RuntimeError（【待接线】）。"""
    router = Router()
    register_dialog_commands(router)
    spec = router.get(DIALOG_CMD)
    assert spec is not None and spec.handler is not None
    try:
        spec.handler(_pc())
    except RuntimeError as exc:
        assert "make_context" in str(exc)
    else:  # pragma: no cover —— 应抛
        raise AssertionError("未注入 make_context 时应抛 RuntimeError")


def test_register_with_make_context_returns_str() -> None:
    """RN-04：make_context 注入后 handler 返回 str 回复。"""
    router = Router()
    register_dialog_commands(router, make_context=lambda parsed: _fresh_ctx())
    spec = router.get(DIALOG_CMD)
    assert spec is not None and spec.handler is not None
    out = spec.handler(_pc())
    assert isinstance(out, str)
    assert "这里的人：" in out


# ---------------------------------------------------------------------------
# /对话 无参列表 / 序号 / 名称（RN-01 · TCN-01/02）
# ---------------------------------------------------------------------------

def test_dialog_no_args_lists_npcs() -> None:
    """TCN-01：无参 → 当前地图 visible NPC 列表（序号+名字；visible=false 过滤）。"""
    ctx = _fresh_ctx()
    out = cmd_dialog(_pc(), ctx)
    assert "这里的人：" in out
    assert "铁匠·老周" in out
    assert "杂货商人·林" in out
    assert "行商·骆驼" in out
    assert "隐者·影" not in out  # visible=false 不列出
    assert ctx["dialog_active"] is True
    assert ctx["dialog_session"].state == "list"


def test_dialog_empty_map_hint() -> None:
    """TCN-01：无 NPC 地图 → 「当前地图没有可对话的人」，不建会话。"""
    ctx = _fresh_ctx(npcs=[])
    out = cmd_dialog(_pc(), ctx)
    assert "当前地图没有可对话的人" in out
    assert ctx["dialog_active"] is False
    assert ctx["dialog_session"] is None  # 不建会话（快照清空）


def test_dialog_index_selects_npc() -> None:
    """TCN-02：/对话 2 → 序号选中「杂货商人·林」菜单。"""
    ctx = _fresh_ctx()
    out = cmd_dialog(_pc("2"), ctx)
    assert "杂货商人·林：" in out
    assert "1.闲聊" in out
    assert ctx["dialog_session"].npc_id == "shopkeep_lin"
    assert ctx["dialog_session"].state == "menu"


def test_dialog_name_precedence() -> None:
    """TCN-02：名称优先于序号——/对话 铁匠·老周 → 铁匠菜单。"""
    ctx = _fresh_ctx()
    out = cmd_dialog(_pc("铁匠·老周"), ctx)
    assert "铁匠·老周：" in out
    assert "1.接任务" in out
    assert ctx["dialog_session"].npc_id == "blacksmith_zhou"


def test_dialog_index_out_of_range_relist() -> None:
    """TCN-02：序号超界 → 「没有 9 号」 + 重列列表。"""
    ctx = _fresh_ctx()
    out = cmd_dialog(_pc("9"), ctx)
    assert "没有 9 号" in out
    assert "这里的人：" in out
    assert ctx["dialog_session"].state == "list"


def test_dialog_name_with_space_not_found() -> None:
    """TCN-02：名称禁空格——含空格参数无法命中任何名称 → 「没找到这个人」。"""
    ctx = _fresh_ctx()
    out = cmd_dialog(_pc("铁匠", "老周"), ctx)
    assert "没找到这个人" in out
    assert ctx["dialog_active"] is False
    assert ctx["dialog_session"] is None  # 名称未命中不建会话


# ---------------------------------------------------------------------------
# 会话路由（RN-02 · TCN-03）
# ---------------------------------------------------------------------------

def test_router_sends_session_digit() -> None:
    """TCN-03：dialog_active=True 时纯数字 → ROUTE_SESSION（subword=("digit", N)）。"""
    router = Router()
    register_dialog_commands(router)
    r = route_message("2", {"registry": router, "dialog_active": True, "shortcuts": {}})
    assert r.kind == ROUTE_SESSION
    assert r.subword == ("digit", 2)


def test_router_keeps_command_with_word() -> None:
    """TCN-03：会话激活时带指令词（攻击1）→ 正常解析（R2，不送会话）。"""
    router = Router()
    register_dialog_commands(router)
    router.register(CommandSpec("攻击", handler=lambda p: "ok"))
    r = route_message("攻击1", {"registry": router, "dialog_active": True, "shortcuts": {}})
    assert r.kind == ROUTE_COMMAND
    assert r.command == "攻击"


def test_session_select_word_executes() -> None:
    """RN-02：菜单激活后「选择 2」→ select 子词 → shop 动作执行。"""
    ctx = _fresh_ctx()
    cmd_dialog(_pc("铁匠·老周"), ctx)
    out = cmd_dialog_session(("select", 2), ctx)
    assert "打开商店" in out  # dispatch 反馈 + 已打开商店行
    assert ctx["dialog_session"].state == "menu"


def test_session_digit_executes() -> None:
    """RN-02：菜单激活后纯数字 1 → quest 动作执行（T07→T10 回菜单）。"""
    ctx = _fresh_ctx()
    cmd_dialog(_pc("铁匠·老周"), ctx)
    out = cmd_dialog_session(("digit", 1), ctx)
    assert "接取任务" in out
    assert "铁匠·老周：" in out  # 回菜单
    assert ctx["dialog_session"].state == "menu"


def test_session_continue_pages_narration() -> None:
    """RN-02：叙述型 exec（reply 两段 text[]）→ 渲染叙述段；继续翻段后收尾回菜单。"""
    ctx = _fresh_ctx()
    cmd_dialog(_pc("杂货商人·林"), ctx)
    out1 = cmd_dialog_session(("digit", 1), ctx)
    assert out1 in ("今天天气不错", "路上小心")  # 首段叙述
    assert ctx["dialog_session"].state == S_EXEC
    out2 = cmd_dialog_session(("continue", None), ctx)
    assert out2 in ("今天天气不错", "路上小心")
    assert out2 != out1  # 翻到第二段
    out3 = cmd_dialog_session(("continue", None), ctx)  # 末段 → 收尾回菜单
    assert "杂货商人·林：" in out3
    assert ctx["dialog_session"].state == "menu"


def test_session_exit_clears_and_bumps_events() -> None:
    """TCN-08/11：退出 → 清 dialog_active + 快照 + 事件双表写入 [事件:NPC对话:ID]。"""
    ctx = _fresh_ctx()
    cmd_dialog(_pc("铁匠·老周"), ctx)
    key = "[事件:NPC对话:blacksmith_zhou]"
    out = cmd_dialog_session(("exit", None), ctx)
    assert out == ""
    assert ctx["dialog_active"] is False
    assert ctx["dialog_session"] is None
    assert ctx["event_counts"].get(key) == 1
    assert ctx["longline_counters"].get(key) == 1


def test_menu_fixed_leave_exit() -> None:
    """RN-02：菜单固定 N.离开（选项数+1）→ 结束收尾 + 事件计数。"""
    ctx = _fresh_ctx()
    cmd_dialog(_pc("铁匠·老周"), ctx)  # 4 选项 → 离开 = 5
    out = cmd_dialog_session(("digit", 5), ctx)
    assert out == ""
    assert ctx["dialog_active"] is False
    assert ctx["event_counts"].get("[事件:NPC对话:blacksmith_zhou]") == 1


def test_session_invalid_option_stays() -> None:
    """RN-02：无效编号 → 「没有 9 号」留菜单。"""
    ctx = _fresh_ctx()
    cmd_dialog(_pc("铁匠·老周"), ctx)
    out = cmd_dialog_session(("digit", 9), ctx)
    assert "没有 9 号" in out
    assert ctx["dialog_session"].state == "menu"


# ---------------------------------------------------------------------------
# 动作执行（RN-03 · TCN-04/05）
# ---------------------------------------------------------------------------

def test_action_quest_delivery() -> None:
    """TCN-04：选 quest 动作 → dispatch_action 调用 + ✅ 反馈 + 回菜单。"""
    ctx = _fresh_ctx()
    cmd_dialog(_pc("铁匠·老周"), ctx)
    out = cmd_dialog_session(("digit", 1), ctx)
    assert "接取任务" in out
    assert "铁匠·老周：" in out
    assert ctx["dialog_session"].state == "menu"


def test_action_shop_transfers_current_shop() -> None:
    """TCN-05：选 shop 动作 → ctx["current_shop_ref"] 改写 + 已打开商店行。"""
    ctx = _fresh_ctx()
    cmd_dialog(_pc("铁匠·老周"), ctx)
    assert ctx["current_shop_ref"] == []
    out = cmd_dialog_session(("digit", 2), ctx)
    assert "已打开商店：blacksmith_shop" in out
    assert ctx["current_shop_ref"] == "blacksmith_shop"
    assert ctx["dialog_session"].state == "menu"


def test_action_heal_delivery_deducts_coins() -> None:
    """RN-03：选 heal 动作 → 治疗反馈 + 扣费 + 回血。"""
    ctx = _fresh_ctx()
    cmd_dialog(_pc("铁匠·老周"), ctx)
    out = cmd_dialog_session(("digit", 3), ctx)
    assert "治疗完成" in out
    assert ctx["currencies"]["coins"] == 90
    assert ctx["hp"] == 100  # 80 + 50 封顶 100
    assert ctx["dialog_session"].state == "menu"


def test_action_heal_insufficient_coins() -> None:
    """RN-03：heal 金币不足 → 失败反馈 + 回菜单（不扣费不误报）。"""
    ctx = _fresh_ctx(currencies={"coins": 5})
    cmd_dialog(_pc("铁匠·老周"), ctx)
    out = cmd_dialog_session(("digit", 3), ctx)
    assert "金币不足" in out
    assert ctx["currencies"]["coins"] == 5
    assert ctx["hp"] == 80


def test_action_intel_once_marks_both_tracks() -> None:
    """TCN-07：intel 交付 → 双轨键：heard(info_key) + npc_delivered intel:{ref_id} + codex。

    引擎对带 text 的信息类选项以叙述交付（_narration_of 取 text）：选 4 → S_EXEC 显示
    「打听消息」；npc 侧记账（codex/npc_delivered）由壳在 select 时 dispatch 完成；继续 →
    _exec_done 收尾 mark_heard + 「已交付」回菜单。
    """
    ctx = _fresh_ctx()
    cmd_dialog(_pc("铁匠·老周"), ctx)
    out1 = cmd_dialog_session(("digit", 4), ctx)
    assert "打听消息" in out1  # 叙述段
    assert ctx["dialog_session"].state == S_EXEC
    # npc 侧：npc_delivered 含 intel:lore1（dispatch_action 内部 + 壳双轨兜底）
    assert is_delivered(ctx, "blacksmith_zhou", "intel:lore1")
    assert ctx["codex_state"].get("lore1") is True
    # 继续 → 收尾交付：dialog 侧 heard 标记 + 回菜单
    out2 = cmd_dialog_session(("continue", None), ctx)
    assert "已交付" in out2
    assert "intel:4" in ctx["heard"]
    assert ctx["dialog_session"].state == "menu"


def test_action_intel_already_heard_greyed() -> None:
    """TCN-07：已听后重选 → 「你已经听过了」置灰留菜单，不重复交付。"""
    ctx = _fresh_ctx()
    cmd_dialog(_pc("铁匠·老周"), ctx)
    cmd_dialog_session(("digit", 4), ctx)
    cmd_dialog_session(("continue", None), ctx)  # 完成交付回菜单（heard 已记）
    out2 = cmd_dialog_session(("digit", 4), ctx)
    assert "你已经听过了" in out2
    assert ctx["dialog_session"].state == "menu"


# ---------------------------------------------------------------------------
# 发牌员（RN-03 · TCN-06）
# ---------------------------------------------------------------------------

def test_dealer_deals_card_on_landing() -> None:
    """TCN-06：落地发牌员 NPC → deal 抽牌交付（文案前置菜单）+ 牌级 once 出池。"""
    ctx = _fresh_ctx()
    out = cmd_dialog(_pc("行商·骆驼"), ctx)
    assert "情报已记入图鉴" in out
    assert "行商·骆驼：" in out
    assert is_delivered(ctx, "traveling_dealer", "card:c1")
    assert is_delivered(ctx, "traveling_dealer", "intel:d1")


def test_dealer_lonely_greeting_after_pool_empty() -> None:
    """TCN-06：牌池抽空（once 出池）→ 再次对话 → 孤寂卡 greeting 兜底。"""
    ctx = _fresh_ctx()
    cmd_dialog(_pc("行商·骆驼"), ctx)  # 第一张 c1 出池
    cmd_dialog_session(("exit", None), ctx)
    out = cmd_dialog(_pc("行商·骆驼"), ctx)
    assert "来抽一张吧" in out  # 孤寂卡 greeting
    assert "情报已记入图鉴" not in out


def test_dealer_rotate_state_advances() -> None:
    """RN-03：rotate 策略 → 每次对话推进指针，两卡轮换。"""
    dealer = {
        "strategy": "rotate",
        "pool": [
            {"id": "r1", "deliver": {"action": "reply", "text": ["第一张"]}},
            {"id": "r2", "deliver": {"action": "reply", "text": ["第二张"]}},
        ],
    }
    ctx = _fresh_ctx(npcs=[{**DEALER, "dealer": dealer}])
    out1 = cmd_dialog(_pc("行商·骆驼"), ctx)
    assert "第一张" in out1
    assert ctx["npc_rotate"]["traveling_dealer"]["index"] == 1
    cmd_dialog_session(("exit", None), ctx)
    out2 = cmd_dialog(_pc("行商·骆驼"), ctx)
    assert "第二张" in out2
    assert ctx["npc_rotate"]["traveling_dealer"]["index"] == 2


# ---------------------------------------------------------------------------
# 中断与恢复（RN-12 · TCN-09/10）
# ---------------------------------------------------------------------------

def test_interrupt_keeps_active_and_snapshot() -> None:
    """TCN-09/10：中断 → 状态不变（菜单）激活保持，快照落 ctx["dialog_session"]。"""
    ctx = _fresh_ctx()
    cmd_dialog(_pc("铁匠·老周"), ctx)
    out = cmd_dialog_interrupt(ctx)
    assert out == ""
    assert ctx["dialog_active"] is True
    session = ctx["dialog_session"]
    assert isinstance(session, DialogSession)
    assert session.state == S_MENU
    assert session.npc_id == "blacksmith_zhou"


def test_resume_brief_on_return() -> None:
    """TCN-09：中断后再次 /对话 → 恢复简报「【续·对话】铁匠·老周」+ 菜单重显。"""
    ctx = _fresh_ctx()
    cmd_dialog(_pc("铁匠·老周"), ctx)
    cmd_dialog_interrupt(ctx)
    out = cmd_dialog(_pc(), ctx)
    assert "【续·对话】铁匠·老周" in out
    assert "1.接任务" in out  # 菜单层重显
    assert ctx["dialog_session"].state == S_MENU  # 状态原样重入


def test_interrupt_in_exec_resume_keeps_page() -> None:
    """TCN-09：长叙述中断 → 简报标注「已读第 N 段，继续阅读」。"""
    ctx = _fresh_ctx()
    cmd_dialog(_pc("杂货商人·林"), ctx)
    cmd_dialog_session(("digit", 1), ctx)  # 进入叙述（S_EXEC）
    assert ctx["dialog_session"].state == S_EXEC
    cmd_dialog_interrupt(ctx)
    out = cmd_dialog(_pc(), ctx)
    assert "【续·对话】杂货商人·林" in out
    assert "继续阅读" in out


# ---------------------------------------------------------------------------
# 事件写入（RN-10 · TCN-08）
# ---------------------------------------------------------------------------

def test_bump_event_hook_preferred() -> None:
    """RN-10：ctx 提供 bump_event hook → 走 hook（双表直写不重复）。"""
    calls: list = []

    def hook(c: dict, key: str) -> None:
        calls.append((c, key))

    ctx = _fresh_ctx(bump_event=hook)
    cmd_dialog(_pc("铁匠·老周"), ctx)
    cmd_dialog_session(("exit", None), ctx)
    assert len(calls) == 1
    assert calls[0][1] == "[事件:NPC对话:blacksmith_zhou]"
    # hook 存在 → 不双表直写
    assert ctx["event_counts"] == {}
    assert ctx["longline_counters"] == {}


# ---------------------------------------------------------------------------
# 边界 / 辅助
# ---------------------------------------------------------------------------

def test_cmd_dialog_session_without_active_returns_empty() -> None:
    """RN-02：无激活会话时子词入口不消费 → 空串。"""
    ctx = _fresh_ctx()
    assert cmd_dialog_session(("digit", 1), ctx) == ""


def test_cmd_dialog_confirm_guard_outside_subui() -> None:
    """RN-03：非 S5 SUBUI 状态 confirm → 空串（不消费）。"""
    ctx = _fresh_ctx()
    cmd_dialog(_pc("铁匠·老周"), ctx)
    assert cmd_dialog_confirm(ctx) == ""


def test_normalize_dialog_result_shape() -> None:
    """细化 §1.2：step 结果归一为 {ok, kind, state, lines}。"""
    ctx = _fresh_ctx()
    session = DialogSession()
    result = session.step(("dialog", {"mode": "list"}), ctx)
    norm = normalize_dialog_result(result)
    assert norm["ok"] is True
    assert norm["kind"] == "list"
    assert norm["state"] == "list"
    assert "这里的人：" in norm["lines"][0]
