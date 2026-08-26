"""BREP-10~14 怪物行动模板单测（M5-05 · qbot_rpg/core/message_format/battle_render.py）。

依据：docs/m5_shared_contract.md §5.1/§5.2（ActionOutcome 真实字段：伤害取 final_damage、
目标 HP 取 target_hp，不直接复用引擎 message；P2-8）
     + docs/m5_batch_plan.md M5-05 + 细化_5e §1.4/§3.1~§3.4（BREP-10~14 + TC-12~15
     + D-5E 意图预告固定句式 + 数值层 L58-61 先手击杀不反击写死、L38/L240 拦截链）。

覆盖：TC-12 反击命中逐字（`❌ 史莱姆反击，你受到 4 伤害（HP 21/30）`）/ BREP-11
未命中逐字 / TC-13 先手击杀不渲染反击行 / TC-14 意图预告逐字（固定句式 D-5E，无 emoji）
/ TC-15 特殊行动逐字（狂暴/召唤/印记，效果纯文字）/ BREP-14 拦截链三行（吸收/反弹/免疫）
/ 玩家防御中受击分发 BREP-06 / _render_enemy_action 多行拼接 / 缺接线属性回落 /
emoji 纪律（仅 ✅/❌ + 排版符号豁免 D-5B，零装饰 emoji）。

说明：展示名（attacker_name / action_name）与玩家最大 HP（player_max_hp）非
ActionOutcome 字段（shared_contract §5.1 字段清单无），由接线层（M5-08）注入——
集成断言用真实 ActionOutcome + 接线层形态包装（SimpleNamespace 承载可省略属性）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict

from qbot_rpg.core.battle import ActionOutcome, TurnReport
from qbot_rpg.core.message_format.battle_render import (
    _render_enemy_action,
    _render_enemy_hit,
    _render_enemy_intent,
    _render_enemy_miss,
    _render_enemy_special,
    _render_interception_lines,
    render_battle_round,
)

# 3d §4.2 装饰性 emoji 禁用清单（TC-04 程序化扫描锚点）
BANNED_EMOJI = "🔥🟢💥⚔️🛡️✨⭐🌟🎉🎊💎🏆❤️💖⚠️🚫📜🗡️🛒🧪⏰📅➡️🔹🔸▸"
# 排版符号豁免清单（D-5B）：竖线 ｜ / | 、ASCII 箭头 → 、×、/、（）「」【】
ALLOWED_SYMBOLS = set("✅❌｜→|/×（）「」【】·…")


def _outcome(**kw: Any) -> ActionOutcome:
    """构造 ActionOutcome（真实字段；缺省 = 怪物反击命中玩家，4 伤后玩家 21/30）。"""
    defaults: Dict[str, Any] = {
        "ok": True, "seq": 2, "actor": "enemy", "action_type": "normal",
        "target": "player", "hit": True, "crit": "", "blocked": False,
        "raw_damage": 4, "final_damage": 4, "target_hp": 21,
        "side_effects": (), "message": "史莱姆 对 玩家 造成 4 伤害",
        "battle_ended": False, "status": None,
    }
    defaults.update(kw)
    return ActionOutcome(**defaults)  # type: ignore[arg-type]


def _report(*outcomes: Any, **kw: Any) -> TurnReport:
    """构造 TurnReport（真实字段；player/enemy 为 HP 快照，outcomes 流水）。"""
    defaults: Dict[str, Any] = {
        "turn": 1, "phases": ("player_action", "enemy_action"),
        "player": 21, "enemy": 7, "ended": False, "status": None,
        "log": (), "outcomes": tuple(outcomes),
    }
    defaults.update(kw)
    return TurnReport(**defaults)  # type: ignore[arg-type]


def _enriched(oc: ActionOutcome, **extra: Any) -> SimpleNamespace:
    """接线层形态 outcome：真实字段（ActionOutcome 全部字段经 __dict__ 承载）
    + 展示信息（attacker_name/action_name/player_max_hp 等，ActionOutcome 不承载，
    M5-08 注入）。"""
    return SimpleNamespace(**{**oc.__dict__, **extra})


def _assert_no_banned_emoji(text: str) -> None:
    """TC-04/05：零装饰 emoji（仅 ✅/❌ 功能性标记 + 排版符号豁免 D-5B）。"""
    for ch in text:
        assert ch not in BANNED_EMOJI, f"战报出现禁用 emoji：{ch!r}（{text}）"


def _assert_emoji_discipline(text: str) -> None:
    """唯二 emoji = ✅❌；其余非 ASCII 仅限 CJK 汉字 / 全角标点 / 排版符号豁免（D-5B）。"""
    for ch in text:
        if ch in ALLOWED_SYMBOLS or ch.isascii():
            continue
        cp = ord(ch)
        if 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF:   # CJK 统一表意 + 扩展 A
            continue
        if 0x3000 <= cp <= 0x303F or 0xFF00 <= cp <= 0xFFEF:  # CJK 标点 / 全角形式
            continue
        raise AssertionError(f"非法字符（疑似装饰 emoji）：{ch!r} in {text!r}")


# ---------------------------------------------------------------------------
# TC-12 怪物-反击命中（BREP-10）
# ---------------------------------------------------------------------------


def test_tc12_enemy_hit_exact() -> None:
    """TC-12：反击命中逐字 `❌ 史莱姆反击，你受到 4 伤害（HP 21/30）`（BREP-10）。"""
    oc = _outcome()
    line = _render_enemy_hit(
        _enriched(oc, attacker_name="史莱姆", action_name="反击", player_max_hp=30),
    )
    assert line == "❌ 史莱姆反击，你受到 4 伤害（HP 21/30）"
    assert oc.message not in line                    # 不直接复用引擎 message（5e P2-8）


def test_tc12_enemy_action_dispatcher() -> None:
    """TC-12：_render_enemy_action 命中分支 → BREP-10（接线层展示属性经 outcome 注入）。"""
    oc = _enriched(_outcome(), attacker_name="史莱姆", action_name="反击", player_max_hp=30)
    assert _render_enemy_action(oc) == "❌ 史莱姆反击，你受到 4 伤害（HP 21/30）"


def test_tc12_render_round_enemy_counter() -> None:
    """TC-12：render_battle_round 先手行动+怪物反击合并 1 条消息（军规3，同条换行）。"""
    player = _enriched(
        _outcome(actor="player", seq=1, target="史莱姆", raw_damage=18,
                 final_damage=18, target_hp=7),
        action_name="施放火球术", target_max_hp=25,
    )
    enemy = _enriched(_outcome(seq=2), attacker_name="史莱姆", action_name="反击",
                      player_max_hp=30)
    text = render_battle_round(_report(player, enemy))
    assert text == (
        "✅ 你施放火球术，造成 18 伤害（史莱姆 7/25）\n"
        "❌ 史莱姆反击，你受到 4 伤害（HP 21/30）"
    )


# ---------------------------------------------------------------------------
# BREP-11 怪物-攻击未命中
# ---------------------------------------------------------------------------


def test_enemy_miss_exact() -> None:
    """BREP-11：未命中逐字 `✅ 史莱姆的攻击被你躲开（HP 21/30）`；miss 不扣血（L24）。"""
    oc = _outcome(hit=False, raw_damage=0, final_damage=0, target_hp=21)
    line = _render_enemy_miss(_enriched(oc, attacker_name="史莱姆", player_max_hp=30))
    assert line == "✅ 史莱姆的攻击被你躲开（HP 21/30）"


def test_enemy_action_miss_branch() -> None:
    """_render_enemy_action：miss 分支 → BREP-11（对玩家是成功 → ✅）。"""
    oc = _enriched(
        _outcome(hit=False, raw_damage=0, final_damage=0, target_hp=21),
        attacker_name="史莱姆", player_max_hp=30,
    )
    assert _render_enemy_action(oc) == "✅ 史莱姆的攻击被你躲开（HP 21/30）"


# ---------------------------------------------------------------------------
# TC-13 先手击杀不渲染反击行（数值层 L61 写死）
# ---------------------------------------------------------------------------


def test_tc13_killed_enemy_no_counter() -> None:
    """TC-13：先手击杀 → 引擎不产出后手 outcome（L61 写死）→ 战报无反击行。"""
    player = _enriched(
        _outcome(actor="player", seq=1, target="史莱姆", raw_damage=25,
                 final_damage=25, target_hp=0),
        action_name="攻击", target_max_hp=25,
    )
    text = render_battle_round(_report(player))      # 无 enemy outcome
    assert "✅ 你攻击，造成 25 伤害（史莱姆 0/25）" in text
    assert "反击" not in text
    assert "你受到" not in text


# ---------------------------------------------------------------------------
# TC-14 怪物-意图预告（BREP-12，固定句式 D-5E，无 emoji）
# ---------------------------------------------------------------------------


def test_tc14_intent_exact() -> None:
    """TC-14：意图预告逐字 `史莱姆王 蓄力中（下回合发动「毒雾吐息」）`（BREP-12）。"""
    oc = _outcome(action_type="charge")
    line = _render_enemy_intent(
        _enriched(oc, attacker_name="史莱姆王", intent_skill="毒雾吐息"),
    )
    assert line == "史莱姆王 蓄力中（下回合发动「毒雾吐息」）"


def test_tc14_intent_via_dispatcher() -> None:
    """TC-14：action_type=charge（蓄力/读招归类）→ BREP-12 分支。"""
    oc = _enriched(_outcome(action_type="charge"), attacker_name="史莱姆王",
                   intent_skill="毒雾吐息")
    assert _render_enemy_action(oc) == "史莱姆王 蓄力中（下回合发动「毒雾吐息」）"


def test_tc14_intent_missing_skill_returns_none() -> None:
    """意图预告缺招名（数据未接）→ None（调用方省略该行，收口接线补齐）。"""
    oc = _outcome(action_type="charge")
    assert _render_enemy_intent(oc) is None
    assert _render_enemy_action(oc) is None


# ---------------------------------------------------------------------------
# TC-15 怪物-特殊行动（BREP-13，狂暴/召唤/印记）
# ---------------------------------------------------------------------------


def test_tc15_special_exact() -> None:
    """TC-15：特殊行动逐字 `史莱姆王 进入狂暴状态（攻击提升）`（效果纯文字无 emoji）。"""
    oc = _outcome(action_type="rage")
    line = _render_enemy_special(
        _enriched(oc, attacker_name="史莱姆王", special_action="进入狂暴状态",
                  effect_change="攻击提升"),
    )
    assert line == "史莱姆王 进入狂暴状态（攻击提升）"


def test_tc15_special_via_dispatcher() -> None:
    """TC-15：action_type=rage（狂暴/召唤/印记归类）→ BREP-13 分支。"""
    oc = _enriched(_outcome(action_type="rage"), attacker_name="史莱姆王",
                   special_action="进入狂暴状态", effect_change="攻击提升")
    assert _render_enemy_action(oc) == "史莱姆王 进入狂暴状态（攻击提升）"


def test_tc15_summon_and_mark_forms() -> None:
    """5e §3.3 示例：召唤挂名行 / 叠印记（效果变化纯文字；× 排版符号豁免 D-5B）。"""
    summon = _render_enemy_special(
        _enriched(_outcome(action_type="summon"), attacker_name="史莱姆王",
                  special_action="召唤了 史莱姆 ×2"),
    )
    assert summon == "史莱姆王 召唤了 史莱姆 ×2"
    mark = _render_enemy_special(
        _enriched(_outcome(action_type="mark"), attacker_name="史莱姆王",
                  special_action="叠印记 2 层", effect_change="当前印记 3/5"),
    )
    assert mark == "史莱姆王 叠印记 2 层（当前印记 3/5）"


# ---------------------------------------------------------------------------
# BREP-14 拦截链效果行（吸收 / 反弹 / 免疫，5e §3.4）
# ---------------------------------------------------------------------------


def test_brep14_interception_three_forms() -> None:
    """BREP-14：拦截链三行——吸收 / 反弹 / 免疫（各环节触发，5e §3.4）。"""
    oc = _outcome(side_effects=(
        {"kind": "absorb", "name": "冰霜结界", "amount": 5},
        {"kind": "reflect", "amount": 3, "target": "史莱姆"},
        {"kind": "immune", "effect": "中毒"},
    ))
    lines = _render_interception_lines(oc)
    assert lines == [
        "冰霜结界 吸收了 5 点伤害",
        "反弹 3 伤害给史莱姆",
        "免疫了中毒",
    ]


def test_brep14_appended_after_hit_line() -> None:
    """5e §3.4：拦截链行拼在反击行之后（反弹为派生伤害，渲染在段行后、击杀判定前）。"""
    oc = _enriched(
        _outcome(side_effects=({"kind": "absorb", "name": "冰霜结界", "amount": 5},)),
        attacker_name="史莱姆", action_name="反击", player_max_hp=30,
    )
    text = _render_enemy_action(oc)
    assert text == "❌ 史莱姆反击，你受到 4 伤害（HP 21/30）\n冰霜结界 吸收了 5 点伤害"


def test_brep14_render_round_with_interception() -> None:
    """render_battle_round：多行（行动行 + 拦截链行）合并在同一条消息内。"""
    player = _enriched(
        _outcome(actor="player", seq=1, target="史莱姆", raw_damage=18,
                 final_damage=18, target_hp=7),
        action_name="施放火球术", target_max_hp=25,
    )
    enemy = _enriched(
        _outcome(seq=2, side_effects=({"kind": "absorb", "name": "冰霜结界", "amount": 5},)),
        attacker_name="史莱姆", action_name="反击", player_max_hp=30,
    )
    text = render_battle_round(_report(player, enemy))
    assert "❌ 史莱姆反击，你受到 4 伤害（HP 21/30）\n冰霜结界 吸收了 5 点伤害" in text


def test_brep14_unknown_effect_skipped() -> None:
    """无法识别环节的 side_effect → 跳过（不臆造文案）。"""
    oc = _outcome(side_effects=({"kind": "heal", "amount": 5},))
    assert _render_interception_lines(oc) == []


# ---------------------------------------------------------------------------
# 防御中受击分发 BREP-06（5e §3.1，不再输出 BREP-10）
# ---------------------------------------------------------------------------


def test_enemy_action_defend_dispatch_brep06() -> None:
    """玩家防御中受击 → BREP-06（`✅ 你防御了…`，不再输出 BREP-10，5e §3.1）。"""
    oc = _enriched(
        _outcome(raw_damage=4, final_damage=2, target_hp=19),   # ×0.5 生效后 2 伤
        attacker_name="史莱姆", action_name="撞击", player_max_hp=30,
        player_guarding=True,
    )
    text = _render_enemy_action(oc)
    assert text == "✅ 你防御了史莱姆的撞击，受到 2 伤害（HP 19/30）"


def test_enemy_action_fallback_defaults() -> None:
    """缺接线属性（真实 ActionOutcome）→ 缺省回落：怪物名「怪物」、普攻「攻击」、最大 HP=当前。"""
    assert _render_enemy_action(_outcome()) == "❌ 怪物攻击，你受到 4 伤害（HP 21/21）"


# ---------------------------------------------------------------------------
# emoji 纪律（TC-04/05：仅 ✅/❌ + 排版符号豁免 D-5B，零装饰 emoji）
# ---------------------------------------------------------------------------


def test_emoji_discipline_enemy_templates() -> None:
    """本路全部模板输出零装饰 emoji；行首功能性标记仅 ✅/❌（3d D-01 / 5e D-5B）。"""
    samples = [
        _render_enemy_hit(
            _enriched(_outcome(), attacker_name="史莱姆", action_name="反击", player_max_hp=30),
        ),
        _render_enemy_miss(
            _enriched(_outcome(hit=False, target_hp=21), attacker_name="史莱姆",
                      player_max_hp=30),
        ),
        _render_enemy_intent(
            _enriched(_outcome(action_type="charge"), attacker_name="史莱姆王",
                      intent_skill="毒雾吐息"),
        ),
        _render_enemy_special(
            _enriched(_outcome(action_type="rage"), attacker_name="史莱姆王",
                      special_action="进入狂暴状态", effect_change="攻击提升"),
        ),
        "\n".join(_render_interception_lines(_outcome(side_effects=(
            {"kind": "absorb", "name": "冰霜结界", "amount": 5},
            {"kind": "reflect", "amount": 3, "target": "史莱姆"},
            {"kind": "immune", "effect": "中毒"},
        )))),
        _render_enemy_action(
            _enriched(_outcome(), attacker_name="史莱姆", action_name="反击", player_max_hp=30),
        ),
    ]
    for text in samples:
        _assert_no_banned_emoji(text)
        _assert_emoji_discipline(text)
