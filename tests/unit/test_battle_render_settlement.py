"""结算 + 连段模板渲染单测（M5-06 · qbot_rpg/core/message_format/battle_render.py）。

依据：docs/m5_shared_contract.md §5.1/§5.2（BREP 模板、ActionOutcome 真实字段：
伤害取 final_damage、目标 HP 取 target_hp，P2-8 不直接复用引擎 message）
     + 细化_5e_战斗战报格式 §4.1~§4.3/§5.1~§5.2（BREP-15~22 + TC-16~23）
     + 铁律 11 / 军规5（结算一次性：胜负/奖励/掉落当轮事件末尾结算一次，经验/掉落
       只在战斗结束消息输出一次）+ m5_batch_plan M5-06 验收。

覆盖：TC-16 击杀紧跟伤害行 / TC-17 玩家死亡（BREP-16）/ TC-18 胜利完整消息含掉落
且仅一次 / TC-19 互杀平局（默认 draw + 可配 player_loss）/ TC-20 玩家死亡非互杀
（无胜利/掉落）/ TC-21 连段段行连续 1-4 / TC-22 鞭尸（第 3 段击杀第 4 段照常）/
TC-23 BOSS 提前结束后续作废 + 派生封顶附注 / 结算一次性（掉落只在结束消息）/
emoji 纪律（仅 ✅/❌ + 排版符号豁免 D-5B）。

说明：连段 segments / 经验金币掉落 / enemy_name 非 ActionOutcome 字段
（shared_contract §5.1 字段清单无），由接线层（M5-08）注入 —— 集成断言经
SimpleNamespace 承载（对齐 test_battle_render_player.py 的 _enriched 形态）。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict

from qbot_rpg.core.battle import ActionOutcome, TurnReport
from qbot_rpg.core.message_format.battle_render import (
    _render_combo_segments,
    _render_combo_settle,
    _render_combo_settle_line,
    _render_kill_line,
    _render_reward_line,
    _render_settlement,
    render_battle_end,
    render_battle_round,
)

# 3d §4.2 装饰性 emoji 禁用清单（TC-04 程序化扫描锚点；排版符号豁免 D-5B）
BANNED_EMOJI = "🔥🟢💥⚔️🛡️✨⭐🌟🎉🎊💎🏆❤️💖⚠️🚫📜🗡️🛒🧪⏰📅➡️🔹🔸▸"
# 排版符号豁免（D-5B）：✅❌ 功能性标记 + | → × / （）「」【】·…、。
_ALLOWED_SYMBOLS = set("✅❌｜→|/×（）「」【】·…、。")


def _outcome(**kw: Any) -> ActionOutcome:
    """构造 ActionOutcome（真实字段；缺省 = 一次普通命中模板，史莱姆 25→7）。"""
    defaults: Dict[str, Any] = {
        "ok": True, "seq": 1, "actor": "player", "action_type": "normal",
        "target": "史莱姆", "hit": True, "crit": "low", "blocked": False,
        "raw_damage": 18, "final_damage": 18, "target_hp": 7,
        "side_effects": (), "message": "阿伟 对 史莱姆 造成 18 伤害",
        "battle_ended": False, "status": None,
    }
    defaults.update(kw)
    return ActionOutcome(**defaults)  # type: ignore[arg-type]


def _enriched(oc: ActionOutcome, **extra: Any) -> SimpleNamespace:
    """接线层形态 outcome：真实字段（ActionOutcome 全部字段经 __dict__ 承载）
    + 展示信息/连段 segments（target_max_hp/segments/early_end 等，M5-08 注入）。"""
    return SimpleNamespace(**{**oc.__dict__, **extra})


def _round(**kw: Any) -> SimpleNamespace:
    """接线层形态 round_result：TurnReport 真实字段 + 注入字段
    （enemy_name/exp/gold/drops 等，TurnReport dataclass 不承载，M5-08 注入）。"""
    std = {"turn", "phases", "player", "enemy", "ended", "status", "log", "outcomes"}
    defaults: Dict[str, Any] = {
        "turn": 1, "phases": ("player_action",), "player": 21, "enemy": 0,
        "ended": False, "status": None, "log": (), "outcomes": (),
    }
    merged = {**defaults, **{k: v for k, v in kw.items() if k in std}}
    tr = TurnReport(**merged)  # type: ignore[arg-type]
    extra = {k: v for k, v in kw.items() if k not in std}
    return SimpleNamespace(**{**tr.__dict__, **extra})


def _combo(segments: list, target_hp: int, **extra: Any) -> SimpleNamespace:
    """连段行动 outcome：聚合 final_damage=各段之和、target_hp=末段 HP + segments。"""
    total = sum(int(s.get("final_damage", 0)) for s in segments)
    oc = _outcome(final_damage=total, target_hp=target_hp)
    return _enriched(oc, segments=segments, **extra)


def _assert_no_banned_emoji(text: str) -> None:
    """TC-04/05：零装饰 emoji（仅 ✅/❌ 功能性标记 + 排版符号豁免 D-5B）。"""
    for ch in text:
        if ch in BANNED_EMOJI:
            raise AssertionError(f"战报出现禁用 emoji：{ch!r}（{text}）")
        if ch in _ALLOWED_SYMBOLS or ch.isascii():
            continue
        cp = ord(ch)
        # CJK 统一表意 + 扩展 A / CJK 标点 / 全角形式
        if 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF:
            continue
        if 0x3000 <= cp <= 0x303F or 0xFF00 <= cp <= 0xFFEF:
            continue
        raise AssertionError(f"非法字符（疑似装饰 emoji）：{ch!r} in {text!r}")


# ---------------------------------------------------------------------------
# TC-16 击杀（BREP-15，紧跟伤害行）
# ---------------------------------------------------------------------------


def test_tc16_kill_line_exact() -> None:
    """BREP-15 逐字：`✅ 你击败了史莱姆！`。"""
    assert _render_kill_line(_outcome(target="史莱姆")) == "✅ 你击败了史莱姆！"


def test_tc16_kill_line_right_after_damage_line() -> None:
    """TC-16：普攻击杀普通怪 —— 击杀行紧跟伤害行（L54/铁律9）；当轮只出行动+击杀，
    结算（胜利+掉落）由结束消息 render_battle_end 一次性输出（P1-1 方案 A / 军规5）。"""
    oc = _enriched(_outcome(final_damage=25, target_hp=0, target="史莱姆"),
                   target_max_hp=25)
    text = render_battle_round(_round(
        outcomes=(oc,), ended=True, status="win",
        exp=42, gold=25, drops=[("史莱姆凝胶", 2)],
    ))
    lines = text.split("\n")
    assert lines[0] == "✅ 你攻击，造成 25 伤害（史莱姆 0/25）"
    assert lines[1] == "✅ 你击败了史莱姆！"      # 击杀行紧跟伤害行
    assert "✅ 战斗胜利！" not in text            # 结算已移结束消息（P1-1）
    end = render_battle_end(
        SimpleNamespace(), SimpleNamespace(name="史莱姆", turn=1), "win",
        status="win", enemy_name="史莱姆", exp=42, gold=25, drops=[("史莱姆凝胶", 2)],
    )
    assert "✅ 战斗胜利！" in end                 # BREP-17 结束消息同一消息
    assert "✅ 获得 经验 42、金币 25、史莱姆凝胶×2" in end   # BREP-20 掉落


# ---------------------------------------------------------------------------
# TC-17 玩家死亡（BREP-16）· TC-20 玩家死亡非互杀（BREP-18）
# ---------------------------------------------------------------------------


def test_tc17_player_dead_line() -> None:
    """TC-17：回合开始 dot 杀死玩家 → `❌ 你倒下了…`（BREP-16）→ 失败标记（BREP-18）。"""
    text = render_battle_end(
        SimpleNamespace(), SimpleNamespace(name="史莱姆", turn=1), "lose",
        status="lose", enemy_name="史莱姆",
    )
    lines = text.split("\n")
    assert lines[0] == "❌ 你倒下了…"                       # BREP-16
    assert lines[1] == "❌ 战斗失败：你被史莱姆击败了"       # BREP-18
    assert "战斗结束：失败" in text                          # BREP-24 汇总同消息（P1-1）


def test_tc20_player_death_no_victory_no_drop() -> None:
    """TC-20：玩家死亡（非互杀）—— 输出 BREP-18；胜利/掉落行不出现（即使注入掉落数据）。"""
    text = render_battle_end(
        SimpleNamespace(), SimpleNamespace(name="史莱姆", turn=1), "lose",
        status="lose", enemy_name="史莱姆", exp=42, gold=25, drops=[("史莱姆凝胶", 2)],
    )
    assert "❌ 战斗失败：你被史莱姆击败了" in text
    assert "战斗胜利" not in text
    assert "获得" not in text


# ---------------------------------------------------------------------------
# TC-18 胜利完整消息（BREP-17 + BREP-20 掉落仅一次）
# ---------------------------------------------------------------------------


def test_tc18_victory_full_message_with_drops_once() -> None:
    """TC-18：胜利完整消息同含 BREP-17 + BREP-20；掉落仅输出一次（军规5）。"""
    oc = _enriched(_outcome(final_damage=25, target_hp=0, target="史莱姆"),
                   target_max_hp=25)
    text = render_battle_end(
        SimpleNamespace(), SimpleNamespace(name="史莱姆", turn=1), "win",
        status="win", enemy_name="史莱姆", exp=42, gold=25, drops=[("史莱姆凝胶", 2)],
    )
    assert "✅ 战斗胜利！" in text
    assert "战斗结束：胜利" in text                          # BREP-24 同消息（TC-18 语义）
    assert "✅ 获得 经验 42、金币 25、史莱姆凝胶×2" in text
    assert text.count("✅ 获得") == 1
    assert text.count("史莱姆凝胶×2") == 1        # 掉落只在结束消息输出一次


def test_reward_line_exact_and_multi_drop() -> None:
    """BREP-20 逐字；多素材以 `、` 分隔。"""
    assert _render_reward_line(42, 25, [("史莱姆凝胶", 2)]) == (
        "✅ 获得 经验 42、金币 25、史莱姆凝胶×2"
    )
    assert _render_reward_line(10, 5, [("甲", 1), ("乙", 3)]) == (
        "✅ 获得 经验 10、金币 5、甲×1、乙×3"
    )


# ---------------------------------------------------------------------------
# TC-19 互杀平局（BREP-19，默认 draw；可配 player_loss → BREP-18）
# ---------------------------------------------------------------------------


def test_tc19_mutual_kill_draw() -> None:
    """TC-19：同回合互杀默认 draw → `双方同归于尽，战斗以平局结束`（BREP-19）。"""
    text = render_battle_end(
        SimpleNamespace(), SimpleNamespace(name="史莱姆", turn=1), "draw",
        status="draw",
    )
    assert text.split("\n")[0] == "双方同归于尽，战斗以平局结束"  # BREP-19
    assert "战斗结束：平局" in text                                # BREP-24 同消息


def test_tc19_mutual_kill_player_loss_config() -> None:
    """TC-19：可配 player_loss（引擎已落 lose）→ 改走 BREP-18 失败。"""
    text = render_battle_end(
        SimpleNamespace(), SimpleNamespace(name="史莱姆", turn=1), "lose",
        status="lose", enemy_name="史莱姆",
    )
    assert "❌ 战斗失败：你被史莱姆击败了" in text
    assert "同归于尽" not in text


# ---------------------------------------------------------------------------
# TC-21 连段段行（BREP-21，段号连续 1-4）
# ---------------------------------------------------------------------------


def test_tc21_combo_four_segments_continuous() -> None:
    """TC-21：4 段连段全命中 —— 每段独立一行、段号连续 1-4、每段独立取整；
    目标存活 → BREP-22 正常完结无备注。"""
    segs = [
        {"seg": 1, "action": "突刺", "final_damage": 6, "target_hp": 19,
         "target_max_hp": 25, "target": "史莱姆"},
        {"seg": 2, "action": "突刺", "final_damage": 6, "target_hp": 13,
         "target_max_hp": 25, "target": "史莱姆"},
        {"seg": 3, "action": "突刺", "final_damage": 6, "target_hp": 7,
         "target_max_hp": 25, "target": "史莱姆"},
        {"seg": 4, "action": "突刺", "final_damage": 6, "target_hp": 1,
         "target_max_hp": 25, "target": "史莱姆"},
    ]
    oc = _combo(segs, target_hp=1)
    lines = render_battle_round(_round(outcomes=(oc,))).split("\n")
    assert lines == [
        "第 1 段：突刺 造成 6 伤害（史莱姆 19/25）",
        "第 2 段：突刺 造成 6 伤害（史莱姆 13/25）",
        "第 3 段：突刺 造成 6 伤害（史莱姆 7/25）",
        "第 4 段：突刺 造成 6 伤害（史莱姆 1/25）",
        "连段 4 段已结算",
    ]


def test_tc21_combo_seg_crit_note() -> None:
    """5e §5.1 示例：段行尾可拼 BREP-04 会心附注（`（会心·中阶 ×1.7）`）。"""
    segs = [
        {"seg": 1, "action": "突刺", "final_damage": 6, "target_hp": 19,
         "target_max_hp": 25, "target": "史莱姆"},
        {"seg": 2, "action": "突刺", "final_damage": 6, "target_hp": 13,
         "target_max_hp": 25, "target": "史莱姆"},
        {"seg": 3, "action": "突刺", "final_damage": 11, "target_hp": 2,
         "target_max_hp": 25, "target": "史莱姆", "crit": "mid"},
    ]
    oc = _combo(segs, target_hp=2)
    lines = _render_combo_segments(oc)
    assert lines[2] == "第 3 段：突刺 造成 11 伤害（会心·中阶 ×1.7）（史莱姆 2/25）"


# ---------------------------------------------------------------------------
# TC-22 鞭尸（第 3 段击杀，第 4 段照常）
# ---------------------------------------------------------------------------


def test_tc22_third_seg_kills_fourth_still_renders() -> None:
    """TC-22：连段第 3 段击杀普通怪 —— 击杀行紧跟第 3 段伤害行，
    第 4 段照常渲染（鞭尸）→ BREP-22 备注「目标已倒下，下一回合退出战场」。"""
    segs = [
        {"seg": 1, "action": "你挥动铁剑攻击史莱姆", "final_damage": 8,
         "target_hp": 17, "target_max_hp": 25, "target": "史莱姆"},
        {"seg": 2, "action": "你挥动铁剑攻击史莱姆", "final_damage": 8,
         "target_hp": 9, "target_max_hp": 25, "target": "史莱姆"},
        {"seg": 3, "action": "你挥动铁剑攻击史莱姆", "final_damage": 10,
         "target_hp": 0, "target_max_hp": 25, "target": "史莱姆"},
        {"seg": 4, "action": "你挥动铁剑攻击史莱姆", "final_damage": 9,
         "target_hp": 0, "target_max_hp": 25, "target": "史莱姆"},
    ]
    oc = _combo(segs, target_hp=0)
    lines = render_battle_round(_round(outcomes=(oc,))).split("\n")
    # 段行模板（§1.4 BREP-21 / 任务口径）：`第 {N} 段：{动作} 造成 {伤害} 伤害`——无逗号
    assert lines[0] == "第 1 段：你挥动铁剑攻击史莱姆 造成 8 伤害（史莱姆 17/25）"
    assert lines[2] == "第 3 段：你挥动铁剑攻击史莱姆 造成 10 伤害（史莱姆 0/25）"
    assert lines[3] == "✅ 你击败了史莱姆！"       # 击杀行紧跟第 3 段伤害行（L54）
    assert lines[4] == "第 4 段：你挥动铁剑攻击史莱姆 造成 9 伤害（史莱姆 0/25）"
    assert lines[5] == "连段 4 段已结算（目标已倒下，下一回合退出战场）"


# ---------------------------------------------------------------------------
# TC-23 BOSS 提前结束（后续段作废）+ 派生封顶附注
# ---------------------------------------------------------------------------


def test_tc23_boss_early_end_subsequent_segments_dropped() -> None:
    """TC-23：连段击杀 BOSS → 击杀行后立即进入结束结算，
    后续段数作废不渲染（BREP-22 备注「BOSS 已倒下，战斗结束，后续段数作废」）。"""
    segs = [
        {"seg": 1, "action": "突刺", "final_damage": 6, "target_hp": 19,
         "target_max_hp": 25, "target": "史莱姆王"},
        {"seg": 2, "action": "突刺", "final_damage": 6, "target_hp": 13,
         "target_max_hp": 25, "target": "史莱姆王"},
        {"seg": 3, "action": "突刺", "final_damage": 13, "target_hp": 0,
         "target_max_hp": 25, "target": "史莱姆王"},
        {"seg": 4, "action": "突刺", "final_damage": 9, "target_hp": 0,
         "target_max_hp": 25, "target": "史莱姆王"},
    ]
    oc = _combo(segs, target_hp=0, early_end=True)
    text = render_battle_round(_round(
        outcomes=(oc,), ended=True, status="win",
        exp=120, gold=60, drops=[("史莱姆王冠", 1)],
    ))
    lines = text.split("\n")
    assert "✅ 你击败了史莱姆王！" in lines
    assert "第 4 段" not in text                     # 后续段作废不渲染（L57/L69）
    assert "连段 3 段已结算（BOSS 已倒下，战斗结束，后续段数作废）" in lines
    assert "✅ 战斗胜利！" not in text                # 结算已移结束消息（P1-1）
    end = render_battle_end(
        SimpleNamespace(), SimpleNamespace(name="史莱姆王", turn=1), "win",
        status="win", enemy_name="史莱姆王", exp=120, gold=60, drops=[("史莱姆王冠", 1)],
    )
    assert "✅ 战斗胜利！" in end
    assert "✅ 获得 经验 120、金币 60、史莱姆王冠×1" in end
    assert "战斗结束：胜利" in end                    # BREP-24 同消息（TC-18 语义）


def test_tc23_derived_cap_note_on_segment_line() -> None:
    """TC-23：派生累计倍率触及封顶（≤1.5×，L133）→ 段行尾附 `（派生倍率已达上限 1.5×）`。"""
    segs = [
        {"seg": 1, "action": "突刺", "final_damage": 6, "target_hp": 19,
         "target_max_hp": 25, "target": "史莱姆"},
        {"seg": 2, "action": "突刺", "final_damage": 8, "target_hp": 11,
         "target_max_hp": 25, "target": "史莱姆", "derived_capped": True},
    ]
    oc = _combo(segs, target_hp=11)
    text = render_battle_round(_round(outcomes=(oc,)))
    assert "第 2 段：突刺 造成 8 伤害（史莱姆 11/25）（派生倍率已达上限 1.5×）" in text


def test_combo_settle_line_variants() -> None:
    """BREP-22 备注四态：正常完结（无备注）/ 鞭尸 / BOSS 提前结束 / 派生封顶。"""
    assert _render_combo_settle_line(3) == "连段 3 段已结算"
    assert _render_combo_settle_line(4, "目标已倒下，下一回合退出战场") == (
        "连段 4 段已结算（目标已倒下，下一回合退出战场）"
    )
    assert _render_combo_settle_line(3, "BOSS 已倒下，战斗结束，后续段数作废") == (
        "连段 3 段已结算（BOSS 已倒下，战斗结束，后续段数作废）"
    )
    assert _render_combo_settle_line(3, "派生倍率已达上限 1.5×") == (
        "连段 3 段已结算（派生倍率已达上限 1.5×）"
    )


# ---------------------------------------------------------------------------
# 结算一次性（军规5：胜负/掉落当轮事件末尾结算一次）
# ---------------------------------------------------------------------------


def test_settlement_rendered_once_only_when_ended() -> None:
    """军规5：ended=False 不输出结算块；ended=True 结算块恰一次（掉落只在结束消息）。"""
    oc = _enriched(_outcome(final_damage=18, target_hp=7), target_max_hp=25)
    text = render_battle_round(_round(outcomes=(oc,), ended=False, status=None))
    assert "战斗胜利" not in text                              # 当轮无结算（P1-1）
    assert "获得" not in text
    text = render_battle_end(
        SimpleNamespace(), SimpleNamespace(name="史莱姆", turn=1), "win",
        status="win", enemy_name="史莱姆", exp=42, gold=25, drops=[("史莱姆凝胶", 2)],
    )
    assert text.count("✅ 战斗胜利！") == 1
    assert text.count("✅ 获得") == 1
    assert text.count("史莱姆凝胶×2") == 1


def test_settlement_returns_none_when_no_ended() -> None:
    """_render_settlement 直接调用：ended 缺失/False → None（调用方省略结算块）。"""
    assert _render_settlement(SimpleNamespace(ended=False, status="win")) is None
    assert _render_settlement(SimpleNamespace(ended=True, status="escape")) is None


# ---------------------------------------------------------------------------
# emoji 纪律（TC-04/05：仅 ✅/❌ + 排版符号，零装饰 emoji）
# ---------------------------------------------------------------------------


def test_no_banned_emoji_in_settlement_templates() -> None:
    """本路全部模板输出零装饰 emoji；行首功能性标记仅 ✅/❌（D-01 / 5e 军规2）。"""
    samples = [
        _render_kill_line(_outcome(target="史莱姆")),
        _render_reward_line(42, 25, [("史莱姆凝胶", 2)]),
        _render_settlement(SimpleNamespace(ended=True, status="win",
                                           exp=42, gold=25,
                                           drops=[("史莱姆凝胶", 2)])),
        _render_settlement(SimpleNamespace(ended=True, status="lose",
                                           enemy_name="史莱姆")),
        _render_settlement(SimpleNamespace(ended=True, status="draw")),
        _render_combo_settle_line(4, "目标已倒下，下一回合退出战场"),
        _render_combo_settle_line(3, "BOSS 已倒下，战斗结束，后续段数作废"),
        _render_combo_settle_line(3, "派生倍率已达上限 1.5×"),
    ]
    for text in samples:
        _assert_no_banned_emoji(text)
