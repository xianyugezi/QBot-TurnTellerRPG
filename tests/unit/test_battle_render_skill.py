"""BREP-07~09 战斗渲染单测（M5-04 · qbot_rpg/core/message_format/battle_render.py）。

依据：细化_5e_战斗战报格式 §1.4（BREP-07/08/09）+ §2.3（技能释放）+ TC-11 + D-5D
     + 开发规则 L509（状态数默认前 5 个，超出追加「还有 N 个状态」）
     + shared_contract §5.2（引擎输出源：TurnReport + ActionOutcome；P2-8：不直接复用引擎 message）
     + m5_batch_plan M5-04 验收（TC-11 逐字 / 只显变化轴 / 操作提示行含 /最大 分母）。

覆盖：TC-11 逐字断言（治疗术 MP 30→22 消耗 8 落小技 5-10）· 状态差分只显变化轴（D-5D）·
状态数前 5 超出追加「还有 N 个状态」（L509）· 操作提示行含 /最大 分母（BREP-09）·
多怪取第一个存活怪 · emoji 纪律（唯二 ✅❌，排版符号豁免 D-5B）。
"""
from __future__ import annotations

from qbot_rpg.core.message_format.battle_render import (
    DEFAULT_MAX_STATUS,
    first_alive_enemy,
    format_resource_cur_max,
    render_action_hint,
    render_skill_cast,
    render_status_diff,
)

# 3d §4.2 装饰性 emoji 禁用清单（程序化扫描锚点，TC-04）
BANNED = "🔥🟢💥⚔️🛡️✨⭐🌟🎉🎊💎🏆❤️💖⚠️🚫📜🗡️🛒🧪⏰📅➡️🔹🔸▸"
# 排版符号豁免清单（D-5B）：竖线 ｜ / | 、ASCII 箭头 → 、×、/、（）「」【】
ALLOWED_SYMBOLS = set("✅❌｜→|/×（）「」【】·…")


def _assert_emoji_discipline(text: str) -> None:
    """唯二 emoji = ✅❌；其余非 ASCII 仅限 CJK 汉字 / 全角标点 / 排版符号豁免（D-5B，TC-04/05）。"""
    for ch in text:
        if ch in ALLOWED_SYMBOLS or ch.isascii():
            continue
        cp = ord(ch)
        # CJK 统一表意 + 扩展 A / CJK 标点（、。「」【】）/ 全角形式（：（）｜）
        if 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF:
            continue
        if 0x3000 <= cp <= 0x303F or 0xFF00 <= cp <= 0xFFEF:
            continue
        raise AssertionError(f"非法字符（疑似装饰 emoji）：{ch!r} in {text!r}")


# ---------------------------------------------------------------------------
# BREP-07 技能释放（TC-11 逐字）
# ---------------------------------------------------------------------------


def test_skill_cast_tc11_exact():
    """TC-11：BREP-07 逐字 = `✅ 你施放治疗术：回复 30 点 HP（MP 22/60）`。"""
    assert render_skill_cast("治疗术", "回复 30 点 HP", "MP 22/60") == (
        "✅ 你施放治疗术：回复 30 点 HP（MP 22/60）"
    )


def test_skill_cast_mp_cost_small_skill_range():
    """TC-11：MP 消耗 8（30→22）落在小技区间 5-10（数值层 L168）。"""
    old_mp, new_mp = 30, 22
    cost = old_mp - new_mp
    assert 5 <= cost <= 10


def test_skill_cast_no_resource_omits_parenthesis():
    """无资源消耗的技能不输出空括号（兜底：resource_text 空串省略括号）。"""
    assert render_skill_cast("鼓舞", "攻击提升", "") == "✅ 你施放鼓舞：攻击提升"


def test_format_resource_cur_max():
    """BREP-07 资源括号内文本拼装：`MP 22/60`。"""
    assert format_resource_cur_max("MP", 22, 60) == "MP 22/60"


# ---------------------------------------------------------------------------
# BREP-08 状态资源差分行（D-5D 只显变化轴 / 开发规则 L509 前 5 个）
# ---------------------------------------------------------------------------


def test_status_diff_tc11_single_axis():
    """TC-11：BREP-08 资源差分行 `MP 30→22`。"""
    assert render_status_diff([("MP", 30, 22)]) == "MP 30→22"


def test_status_diff_multi_axis_matches_doc_example():
    """5e §1.4 示例逐字：`MP 30→22 ｜ 印记 0→2`（竖线 ｜ 排版符号豁免 D-5B）。"""
    assert render_status_diff([("MP", 30, 22), ("印记", 0, 2)]) == "MP 30→22 ｜ 印记 0→2"


def test_status_diff_only_changed_axes():
    """D-5D：只渲染实际变化的轴，old == new 的轴自动跳过（传入全量快照也只会输出变化轴）。"""
    assert render_status_diff([("MP", 30, 30), ("印记", 0, 2), ("连段", 3, 3)]) == "印记 0→2"


def test_status_diff_all_unchanged_returns_empty():
    """无变化轴 → 空串（调用方据此省略状态行）。"""
    assert render_status_diff([("MP", 30, 30)]) == ""


def test_status_diff_default_max_five():
    """开发规则 L509：状态数默认前 5 个；不超限不追加提示。"""
    assert DEFAULT_MAX_STATUS == 5
    changes = [(f"轴{i}", i, i + 1) for i in range(1, 6)]
    line = render_status_diff(changes)
    assert line.count("→") == 5
    assert "还有" not in line


def test_status_diff_over_five_appends_remainder():
    """开发规则 L509：超出 5 个 → 前 5 个 + 追加「还有 N 个状态」。"""
    changes = [(f"轴{i}", i, i + 1) for i in range(1, 8)]
    assert render_status_diff(changes) == (
        "轴1 1→2 ｜ 轴2 2→3 ｜ 轴3 3→4 ｜ 轴4 4→5 ｜ 轴5 5→6 ｜ 还有 2 个状态"
    )


def test_status_diff_custom_max():
    """max_status 可配（作者收敛）：超限追加剩余计数。"""
    changes = [(f"轴{i}", i, i + 1) for i in range(1, 5)]
    assert render_status_diff(changes, max_status=2) == "轴1 1→2 ｜ 轴2 2→3 ｜ 还有 2 个状态"


def test_status_diff_accepts_dicts():
    """兼容含 label/old/new 键的 dict 序列（引擎侧快照形态）。"""
    changes = [
        {"label": "MP", "old": 30, "new": 22},
        {"label": "印记", "old": 0, "new": 0},
    ]
    assert render_status_diff(changes) == "MP 30→22"


# ---------------------------------------------------------------------------
# BREP-09 操作提示行（含 /最大 分母 + 多怪第一存活怪）
# ---------------------------------------------------------------------------


def test_action_hint_exact_with_denominator():
    """BREP-09：操作提示行含 /最大 分母（5e 原文，【前缀】L31）。"""
    assert render_action_hint(21, 30, 7, 25, target_name="史莱姆") == (
        "你 21/30 | 史莱姆 7/25 → /攻击[技能] /道具 /防御 /逃跑"
    )


def test_action_hint_default_target():
    """缺省目标名 =「目标」（模板 `{目标}` 占位）。"""
    assert render_action_hint(21, 30, 7, 25) == (
        "你 21/30 | 目标 7/25 → /攻击[技能] /道具 /防御 /逃跑"
    )


def test_first_alive_enemy_skips_dead():
    """多怪时目标取战场第一个存活怪（hp>0 且无 dead_mark）。"""
    enemies = [
        {"name": "史莱姆", "hp": 0},
        {"name": "史莱姆王", "hp": 25},
        {"name": "史莱姆", "hp": 7},
    ]
    alive = first_alive_enemy(enemies)
    assert alive is not None
    assert alive["name"] == "史莱姆王"


def test_first_alive_enemy_skips_dead_mark():
    """dead_mark=True 的怪物视为非存活（回合死亡判定 L50-52）。"""
    enemies = [
        {"name": "甲", "hp": 5, "dead_mark": True},
        {"name": "乙", "hp": 9},
    ]
    alive = first_alive_enemy(enemies)
    assert alive is not None
    assert alive["name"] == "乙"


def test_first_alive_enemy_all_dead_none():
    """全灭 / 空序列 → None（调用方据此省略目标段）。"""
    assert first_alive_enemy([{"name": "甲", "hp": 0}]) is None
    assert first_alive_enemy([]) is None


# ---------------------------------------------------------------------------
# emoji 纪律（TC-04/05 程序化扫描）
# ---------------------------------------------------------------------------


def test_emoji_discipline_samples():
    """渲染样本全量扫描：唯二 emoji = ✅❌，无装饰 emoji（3d D-01 / D-5B）。"""
    samples = [
        render_skill_cast("治疗术", "回复 30 点 HP", "MP 22/60"),
        render_status_diff([("MP", 30, 22), ("印记", 0, 2)]),
        render_status_diff([(f"轴{i}", i, i + 1) for i in range(1, 8)]),
        render_action_hint(21, 30, 7, 25, target_name="史莱姆"),
    ]
    for s in samples:
        for ch in BANNED:
            assert ch not in s, f"禁用 emoji {ch!r} 出现在 {s!r}"
        _assert_emoji_discipline(s)
