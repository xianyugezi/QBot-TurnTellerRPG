"""任务指令接线单测（M4 批次4·路E3 · qbot_rpg/commands/quest_commands.py）。

依据：m4_shared_contract.md §2.3+§3.3（/任务 接取 N / 交付 N（+任务信息/放弃）；双板仲裁
日常+主线主线置顶；完成交付 → 统一 reward 发放结果提示）+ docs/细化/细化_2b4_任务引擎契约.md
（§5 任务板：主线置顶 / 接取序号 / 交付 / 双板仲裁；§3 统一 reward 逐键入账 + P1-2 逐条目失败
黄字跳过；TC-24~28）+ 细化_3d（TPL-08/TPL-12、5 条/页、页码夹取）+ 2026-08-27 用户裁决②
（页码夹取最后一页；0/负数/非数字 → TPL-12）。

集成口径：直接驱动**真实引擎** qbot_rpg/core/quest.py（路E2 已收口落盘），构造全字段 ctx
（quests/quest_active/quest_completed/quest_daily/longline_counters/items/currencies/
now 注入确定性），断言命令层解析/渲染/路由/装配/错误全链路输出。

覆盖：/任务 无参（主线置顶 + 双板段头 + 5 条/页 + TPL-08 页脚 + 操作指引）· 页码翻页 ·
超页夹取 + 已到最后一页（裁决②）· 0/负数/非数字 → TPL-12 · 接取（空格/紧凑/固定子词放弃/
已完成拦截/越界序号）· 交付（统一 reward 发放结果提示 + skipped 黄字跳过注记 + consume 扣物）·
信息（三原语进度逐条）· 主线常驻（完成仍在板）· 放弃 · 缺序号/非法序号 → TPL-12 ·
超参解析错误 → TPL-12 · 注册与解析接线 · 懒加载/待接线防御 · 页脚 TPL-08 逐字 · 无装饰 emoji。
"""

from __future__ import annotations

import pytest

import qbot_rpg.commands.quest_commands as qc
from qbot_rpg.commands.parsers import parse_command
from qbot_rpg.commands.quest_commands import (
    QUEST_CMD,
    board_line,
    cmd_quest,
    register_quest_commands,
    render_board,
)
from qbot_rpg.commands.router import Router
from qbot_rpg.core import quest as quest_engine

# ---------------------------------------------------------------------------
# 夹具：双板任务内容包（TC-24 口径：主线 2 + 板上 3 + NPC 支线 1 = 6 行 → 2 页）
# ---------------------------------------------------------------------------

QUESTS = {
    "main_special_weapon": {"id": "main_special_weapon", "name": "特制武器", "main": True,
                            "conditions": [], "reward": "exp=100"},
    "main_forge": {"id": "main_forge", "name": "锻造试炼", "main": True,
                   "conditions": [], "reward": "coins=50"},
    "collect_iron": {"id": "collect_iron", "name": "收集铁矿",
                     "conditions": [{"var": "gain_count", "op": "ge", "value": 20, "param": "铁矿"}],
                     "reward": [{"exp": 50}, {"coins": 80}]},
    "slay_beetle": {"id": "slay_beetle", "name": "清剿熔岩甲虫",
                    "conditions": [{"var": "kill_count", "op": "ge", "value": 3, "param": "熔岩甲虫"}],
                    "reward": [{"coins": 30}]},
    "forge_weapon": {"id": "forge_weapon", "name": "打造武器",
                     "conditions": [{"var": "item_count", "op": "ge", "value": 1, "param": "铁剑"}],
                     "reward": [{"item": "铁矿", "count": 3}], "consume": True},
    "scout_npc": {"id": "scout_npc", "name": "矿洞侦察",
                  "conditions": [], "reward": "", "npc": {"id": "blacksmith"}},
}

# 2026-08-26 09:00 UTC+8（确定性：日界桶键=2026-08-26）
NOW = 1787706000


def make_ctx(**over):
    """全字段玩家任务 ctx（core/quest.py 工程补白 2 契约；每场景新造避免互污染）。"""
    inv = {"铁剑": 1, "铁矿": 5}

    def _add_item(item_id, count, bound=True):
        """reward 入包 hook（A1 工程补白③：物品条目经 add_item 实际入包）。"""
        inv[item_id] = inv.get(item_id, 0) + int(count)
        return True

    base = {
        "level": 5,
        "name": "阿伟",
        "quests": {k: dict(v) for k, v in QUESTS.items()},
        "quest_active": {},
        "quest_completed": set(),
        "quest_daily": {},
        "longline_counters": {"gain_count": {"铁矿": 25}, "kill_count": {"熔岩甲虫": 5}},
        "inventory": inv,
        "add_item": _add_item,
        "items": {"铁矿": {"id": "铁矿", "name": "铁矿"},
                  "铁剑": {"id": "铁剑", "name": "铁剑"}},
        "currencies": {"coins": 1000, "gems": 5},
        "exp": 100,
        "settings": {"currencies": [
            {"id": "coins", "name": "金币"},
            {"id": "gems", "name": "宝石"},
        ]},
        "now": NOW,
        "quest_engine": quest_engine,
    }
    base.update(over)
    return base


def parse(raw: str):
    """parse_command 封装（默认白名单已含 任务，parsers.DEFAULT_WHITELIST）。"""
    return parse_command(raw)


# ---------------------------------------------------------------------------
# /任务 无参：任务板列表（双板主线置顶 + 5 条/页 + TPL-08 页脚 + 操作指引）
# ---------------------------------------------------------------------------

def test_quest_noarg_board_page1():
    """TC-24：/任务 → 主线置顶 + 每日板上任务 + NPC 支线；5 条/页 + TPL-08 页脚 + 操作指引。"""
    out = cmd_quest(parse("/任务"), make_ctx())
    # 双板段头（主线在前，板上任务在后）——主线置顶成立
    assert out.index("━━ 主线（常驻） ━━") < out.index("━━ 每日板上任务 ━━")
    # 主线行带 [主线] 前缀（main 常驻置顶）
    assert "1. [主线] 特制武器" in out
    assert "2. [主线] 锻造试炼" in out
    # 板上任务行：进度（三原语 current/target 摘要）
    assert "3. 收集铁矿  进度 25/20" in out
    assert "4. 清剿熔岩甲虫  进度 5/3" in out
    assert "5. 打造武器  进度 1/1" in out
    # 5 条/页（m4 §2.2）：第 1 页 5 条 + TPL-08 页脚
    assert "当前页：1/2" in out
    # 操作指引行（2b4 §5.2 语义，意见一同步：Tip 改「领取任务 序号」）
    assert "Tip:发送'领取任务 序号'即可领取任务" in out


def test_quest_board_npc_section_page2():
    """TC-24 尾段：第 2 页 = NPC 支线段（段头 + 行）。"""
    out = cmd_quest(parse("/任务 2"), make_ctx())
    assert "━━ NPC 支线 ━━" in out
    assert "6. 矿洞侦察" in out
    assert "当前页：2/2" in out


def test_quest_noarg_command_equivalence():
    """/任务（第 1 页）与 /任务 1 输出一致。"""
    assert cmd_quest(parse("/任务"), make_ctx()) == cmd_quest(parse("/任务 1"), make_ctx())


def test_quest_clamp_last_page():
    """裁决②：/任务 9 超总页数 → 夹取最后一页 + （已到最后一页）。"""
    out = cmd_quest(parse("/任务 9"), make_ctx())
    assert "6. 矿洞侦察" in out
    assert "（已到最后一页）" in out
    assert "当前页：2/2" in out


@pytest.mark.parametrize("raw, fragment", [
    ("/任务 0", "/任务 0"),
    ("/任务 -1", "/任务 -1"),
    ("/任务 abc", "/任务 abc"),
    ("/任务 列表", "/任务 列表"),  # 非子指令亦非页码 → TPL-12
])
def test_quest_invalid_input_tpl12(raw, fragment):
    """裁决② + 3d §5.1：0/负数/非数字 → TPL-12 统一报错。"""
    out = cmd_quest(parse(raw), make_ctx())
    assert out == f"❌ 指令不正确：{fragment}。输入 /帮助 查看可用指令。"


def test_quest_empty_board():
    """空任务板 → 空板文案（无操作指引/无页脚，单页）。"""
    out = cmd_quest(parse("/任务"), make_ctx(quests={}))
    assert out == "（任务板空空如也）"


def test_quest_single_page_no_footer():
    """3d §2.3：≤5 条单页不输出页脚。"""
    out = cmd_quest(parse("/任务"), make_ctx(quests={
        "main_special_weapon": {"id": "main_special_weapon", "name": "特制武器",
                                "main": True, "conditions": [], "reward": "exp=100"}}))
    assert "1. [主线] 特制武器" in out
    assert "翻页" not in out


# ---------------------------------------------------------------------------
# /任务 接取 N
# ---------------------------------------------------------------------------

def test_quest_accept_seq():
    """TC-25：/任务 接取 3 → 引擎 quest_accept(collect_iron)，消息透传。"""
    out = cmd_quest(parse("/任务 接取 3"), make_ctx())
    assert out == "✅ 已接取：收集铁矿（同时进行 1/5）"


def test_quest_accept_compact_forms():
    """紧凑双认：/任务 接取3（子词+序号粘合）与 /任务接取 3（指令名紧凑）。"""
    assert cmd_quest(parse("/任务 接取3"), make_ctx()) == "✅ 已接取：收集铁矿（同时进行 1/5）"
    assert cmd_quest(parse("/任务接取 4"), make_ctx()) == "✅ 已接取：清剿熔岩甲虫（同时进行 1/5）"


def test_quest_accept_alias_lingqu():
    """P2-12 QA：Tip 引导「领取任务 序号」→ 别名「领取」等价「接取」（空格/紧凑双认）。"""
    assert cmd_quest(parse("/任务 领取 3"), make_ctx()) == "✅ 已接取：收集铁矿（同时进行 1/5）"
    assert cmd_quest(parse("/任务 领取3"), make_ctx()) == "✅ 已接取：收集铁矿（同时进行 1/5）"
    assert cmd_quest(parse("/任务领取 4"), make_ctx()) == "✅ 已接取：清剿熔岩甲虫（同时进行 1/5）"


def test_quest_board_tip_matches_accept_alias():
    """P2-12 QA：任务板 Tip「领取任务 序号」与可用子词一致（「领取」已注册为「接取」等价子词）。"""
    tip = qc._BOARD_TAIL_TIP
    assert "领取任务" in tip and "接取" not in tip  # 口语化引导词保留
    assert qc.SUB_ACCEPT_ALIASES == ("领取",)
    # Tip 引导的形式能直接路由成功
    out = cmd_quest(parse("/任务 领取 3"), make_ctx())
    assert out == "✅ 已接取：收集铁矿（同时进行 1/5）"


def test_quest_accept_marked_in_board():
    """TC-25：接取后 /任务 列表该序号变 *（已接取标记，不参与可接序号计数）。"""
    ctx = make_ctx()
    cmd_quest(parse("/任务 接取 3"), ctx)
    out = cmd_quest(parse("/任务"), ctx)
    assert "3. 收集铁矿*  进度 25/20" in out


def test_quest_accept_already_active():
    """/任务 接取 3 重复 → 引擎「该任务已在进行中」透传。"""
    ctx = make_ctx(quest_active={"collect_iron": {"name": "收集铁矿"}})
    out = cmd_quest(parse("/任务 接取 3"), ctx)
    assert out == "❌ 该任务已在进行中"


def test_quest_accept_out_of_range():
    """展示序号越界 → resolve_board_index None → 「❌ 任务不存在」（工程补白 6）。"""
    out = cmd_quest(parse("/任务 接取 99"), make_ctx())
    assert out == "❌ 任务不存在"


def test_quest_accept_already_completed():
    """TC-21 后半：主线完成后再接（非 repeatable）→ 「❌ 任务已完成」。"""
    ctx = make_ctx(quest_completed={"main_special_weapon"})
    out = cmd_quest(parse("/任务 接取 1"), ctx)
    assert out == "❌ 任务已完成"


# ---------------------------------------------------------------------------
# /任务 交付 N（统一 reward 发放结果提示 + skipped 黄字跳过 + consume 扣物）
# ---------------------------------------------------------------------------

def test_quest_deliver_reward_result_prompt():
    """TC-26/3.2：/任务 交付 3 → 完成交付 → 统一 reward 发放结果提示（引擎 message 透传）。"""
    ctx = make_ctx(quest_active={"collect_iron": {"name": "收集铁矿"}})
    out = cmd_quest(parse("/任务 交付 3"), ctx)
    assert "✅ 交付完成：收集铁矿" in out
    assert "exp50" in out  # 统一 reward 发放结果提示（+exp50 / 80 coins）
    assert "今日已完成 1/10" in out
    assert ctx["currencies"]["coins"] == 1080  # 真实入账：+80 金币
    assert ctx["exp"] == 150                   # 真实入账：+50 经验
    assert "collect_iron" not in ctx["quest_active"]  # 完成即移出（F-3）


def test_quest_deliver_consume_removes_items():
    """TC-26 consume=true：/任务 交付 5 → 校验背包够数 + 扣物出包 + 奖励入包。"""
    ctx = make_ctx(quest_active={"forge_weapon": {"name": "打造武器"}})
    out = cmd_quest(parse("/任务 交付 5"), ctx)
    assert "✅ 交付完成：打造武器" in out
    assert "铁矿×3" in out
    assert ctx["inventory"]["铁剑"] == 0  # consume 扣物出包（item_count 条件推导）
    assert ctx["inventory"]["铁矿"] == 8  # 奖励 3 个铁矿入包（5 + 3）


def test_quest_deliver_skipped_note():
    """P1-2：交付 reward 逐条目失败黄字跳过注记（不吞整批、不中断结果提示）。"""
    quests = {k: dict(v) for k, v in QUESTS.items()}
    quests["collect_iron"]["reward"] = [{"item": "不存在的物品", "count": 1}]
    ctx = make_ctx(quests=quests, quest_active={"collect_iron": {"name": "收集铁矿"}})
    out = cmd_quest(parse("/任务 交付 3"), ctx)
    assert "✅ 交付完成：收集铁矿" in out  # 整批结果提示仍在（跳过不中断）
    assert "（跳过：item_not_found）" in out


def test_quest_deliver_not_active():
    """/任务 交付 3（未接取）→ 引擎「该任务未在进行中（请先 /接取）」透传。"""
    out = cmd_quest(parse("/任务 交付 3"), make_ctx())
    assert out == "❌ 该任务未在进行中（请先 /接取）"


def test_quest_deliver_condition_not_met():
    """条件未达成 → 拒绝交付（引擎消息透传）。"""
    ctx = make_ctx(quest_active={"slay_beetle": {"name": "清剿熔岩甲虫"}},
                   longline_counters={"kill_count": {"熔岩甲虫": 1}})
    out = cmd_quest(parse("/任务 交付 4"), ctx)
    assert out == "❌ 任务条件未达成，暂不能交付"


def test_quest_deliver_daily_limit():
    """F-1：每日完成达上限（settings.quest_daily_limit=1 且今日已完成 1）→ 拒绝交付。"""
    ctx = make_ctx(
        settings={"quest_daily_limit": 1, "currencies": [{"id": "coins", "name": "金币"},
                                                         {"id": "gems", "name": "宝石"}]},
        quest_active={"collect_iron": {"name": "收集铁矿"}, "slay_beetle": {"name": "清剿熔岩甲虫"}},
        quest_daily={"key": "2026-08-26", "completed": 1, "accepted": 0, "decay": {}},
    )
    out = cmd_quest(parse("/任务 交付 3"), ctx)
    assert out == "❌ 今日任务已完成 1/1，明早 5 点刷新"


def test_quest_deliver_main_stays_on_board():
    """TC-22：main:true 主线交付完成 → 常驻不移除、仍在置顶显示（可重复查看/推进）。"""
    ctx = make_ctx(quest_active={"main_special_weapon": {"name": "特制武器"}})
    out = cmd_quest(parse("/任务 交付 1"), ctx)
    assert "✅ 交付完成：特制武器" in out
    assert "main_progress" in ctx["longline_counters"]  # 主线 done 计数 +1
    assert ctx["longline_counters"]["main_progress"] == 1
    # 完成后再看 /任务：主线仍在置顶（常驻不移除）
    board = cmd_quest(parse("/任务"), ctx)
    assert "1. [主线] 特制武器" in board


# ---------------------------------------------------------------------------
# /任务 信息 N（三原语进度逐条显示）
# ---------------------------------------------------------------------------

def test_quest_info():
    """/任务 信息 3 → 三原语进度逐条显示 + 交付判定。"""
    out = cmd_quest(parse("/任务 信息 3"), make_ctx())
    assert "✅ 任务进度：收集铁矿" in out
    assert "累计获得 ≥ 20（铁矿），当前 25 ✅" in out
    assert "✅ 条件已满足，可交付（/任务 交付 3）" in out


def test_quest_info_not_met():
    """/任务 信息 4（条件未达成）→ 未满足逐条 + 未达成提示。"""
    ctx = make_ctx(longline_counters={"kill_count": {"熔岩甲虫": 1}})
    out = cmd_quest(parse("/任务 信息 4"), ctx)
    assert "✅ 任务进度：清剿熔岩甲虫" in out
    assert "累计击杀 ≥ 3（熔岩甲虫），当前 1 ❌" in out
    assert "❌ 条件未达成，继续努力" in out


def test_quest_info_out_of_range():
    """/任务 信息 99 → 「❌ 任务不存在」。"""
    assert cmd_quest(parse("/任务 信息 99"), make_ctx()) == "❌ 任务不存在"


# ---------------------------------------------------------------------------
# /任务 放弃 N（固定子词路径）
# ---------------------------------------------------------------------------

def test_quest_abandon_fixed_subword():
    """TC-27：/任务 放弃 2（放弃=解析器固定子词 → fixed_subword 路径）→ 引擎移除 active。"""
    ctx = make_ctx(quest_active={"main_forge": {"name": "锻造试炼"}})
    out = cmd_quest(parse("/任务 放弃 2"), ctx)
    assert out == "✅ 已放弃：锻造试炼"
    assert "main_forge" not in ctx["quest_active"]


def test_quest_abandon_compact_no_space():
    """紧凑形式：任务放弃2（无空格）→ 引擎 seq=2。"""
    ctx = make_ctx(quest_active={"main_forge": {"name": "锻造试炼"}})
    assert cmd_quest(parse("任务放弃2"), ctx) == "✅ 已放弃：锻造试炼"


def test_quest_abandon_not_active():
    """/任务 放弃 2（未进行中）→ 引擎「该任务未在进行中」。"""
    assert cmd_quest(parse("/任务 放弃 2"), make_ctx()) == "❌ 该任务未在进行中"


# ---------------------------------------------------------------------------
# 缺参 / 非法序号 / 超参 → TPL-12
# ---------------------------------------------------------------------------

def test_quest_missing_seq_tpl12():
    """缺序号 → TPL-12（接取 / 信息 / 放弃 / 交付 均需 N）。"""
    for raw in ("/任务 接取", "/任务 信息", "/任务 放弃", "/任务 交付"):
        out = cmd_quest(parse(raw), make_ctx())
        assert out.startswith("❌ 指令不正确："), raw
        assert "输入 /帮助 查看可用指令。" in out, raw


@pytest.mark.parametrize("raw", ["/任务 接取 abc", "/任务 接取 0", "/任务 接取 -2"])
def test_quest_bad_seq_tpl12(raw):
    """非法序号（非数字/0/负数）→ TPL-12（不触碰引擎）。"""
    out = cmd_quest(parse(raw), make_ctx())
    assert out.startswith("❌ 指令不正确：")


def test_quest_parse_error_tpl12():
    """超参（3 个位置参数）→ 解析 error → TPL-12。"""
    out = cmd_quest(parse("/任务 接取 3 4"), make_ctx())
    assert out.startswith("❌ 指令不正确：")


# ---------------------------------------------------------------------------
# 渲染工具（纯函数）
# ---------------------------------------------------------------------------

def test_render_board_sections_pagination():
    """5 条/页边界：6 行 → 页 1 五条 + 页脚，页 2 一条 + 页脚。"""
    board = quest_engine.quest_board(make_ctx())
    p1 = render_board(board, 1)
    assert "━━ 主线（常驻） ━━" in p1  # 主线段头
    assert "━━ 每日板上任务 ━━" in p1  # 每日板段头（双板）
    assert "━━ NPC 支线 ━━" not in p1  # NPC 段在页 2
    assert "5. 打造武器" in p1
    p2 = render_board(board, 2)
    assert "6. 矿洞侦察" in p2
    assert "当前页：2/2" in p2


def test_board_line_markers():
    """board_line 纯函数：主线前缀 / marked * / 进度摘要。"""
    assert board_line(1, {"name": "A", "main": True, "marked": False, "progress": []}) == "1. [主线] A"
    assert board_line(2, {"name": "B", "main": False, "marked": True,
                          "progress": [{"current": 1, "target": 5}]}) == "2. B*  进度 1/5"
    assert board_line(3, {"name": "C", "main": False, "marked": False,
                          "progress": [{"current": None, "target": 5}]}) == "3. C"


# ---------------------------------------------------------------------------
# 接线：Router 注册 / 解析集成 / 懒加载 / 待接线防御
# ---------------------------------------------------------------------------

def test_register_quest_commands():
    """批次6/7 装配入口：注册 任务 一条 CommandSpec。"""
    router = Router()
    register_quest_commands(router, make_context=lambda p: make_ctx())
    assert router.has(QUEST_CMD)
    assert router.get(QUEST_CMD).whitelisted  # 可快捷白名单


def test_register_without_make_context_raises():
    """【待接线】无 make_context 时 handler 调用抛 RuntimeError（装配未注入的显式错误）。"""
    router = Router()
    register_quest_commands(router)
    with pytest.raises(RuntimeError):
        router.get(QUEST_CMD).handler(parse("/任务"))


def test_lazy_import_engine_fallback():
    """懒加载回退：ctx 未注入 quest_engine → 自动加载 core.quest（路E2 已落盘）。"""
    ctx = make_ctx()
    ctx.pop("quest_engine")
    out = cmd_quest(parse("/任务"), ctx)
    assert "━━ 主线（常驻） ━━" in out


def test_engine_missing_raises_wiring_pending(monkeypatch):
    """【待接线】防御：引擎缺失（core.quest 不可导入 + 未注入）→ RuntimeError 显式标注。"""
    def boom(name):
        raise ImportError(f"no module {name}")
    monkeypatch.setattr(qc.importlib, "import_module", boom)
    with pytest.raises(RuntimeError) as ei:
        cmd_quest(parse("/任务"), make_ctx(quest_engine=None))
    assert "【待接线】" in str(ei.value)
    assert "core/quest.py" in str(ei.value)


def test_parse_command_integration():
    """解析接线：/任务 各形态经 parsers.parse_command 产出结构化字段。"""
    p = parse("/任务")
    assert p.command == "任务" and p.args == []
    p = parse("/任务 接取 3")
    assert p.command == "任务" and p.args == ["接取", "3"]
    p = parse("/任务 接取3")
    assert p.command == "任务" and p.args == ["接取3"]
    p = parse("/任务 放弃 2")
    assert p.command == "任务" and p.args == ["2"] and p.fixed_subword == "放弃"
    p = parse("任务放弃2")
    assert p.command == "任务" and p.args == ["放弃2"] and p.compact is True


def test_footer_tpl08_exact():
    """3d TC-12：页脚 TPL-08 逐字（无自造变体）。"""
    out = cmd_quest(parse("/任务"), make_ctx())
    assert "当前页：1/2" in out


def test_no_decorative_emoji():
    """3d §四 D-01：命令层渲染输出零装饰 emoji（仅 ✅/❌ 功能性标记允许）。"""
    ctx = make_ctx(quest_active={"collect_iron": {"name": "收集铁矿"},
                                 "main_forge": {"name": "锻造试炼"}})
    outputs = [
        cmd_quest(parse("/任务"), make_ctx()),
        cmd_quest(parse("/任务 2"), make_ctx()),
        cmd_quest(parse("/任务 接取 3"), make_ctx()),
        cmd_quest(parse("/任务 交付 3"), ctx),
        cmd_quest(parse("/任务 信息 3"), make_ctx()),
        cmd_quest(parse("/任务 放弃 2"), ctx),
    ]
    banned = set("🔥🟢💥⚔️🛡️✨⭐🌟🎉🎊💎🏆❤️💖⚠️🚫📜🗡️🛒🧪⏰📅➡️🔹🔸▸")
    for text in outputs:
        for ch in text:
            assert ch not in banned, f"命中禁用装饰 emoji：{ch} in {text!r}"
            assert ch in ("✅", "❌") or not (0x1F000 <= ord(ch) <= 0x1FAFF), \
                f"命中未登记 emoji：{ch} in {text!r}"
