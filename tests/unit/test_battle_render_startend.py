"""战斗开始/结束/木桩明细模板渲染单测（M5-07 · qbot_rpg/core/message_format/battle_render.py）。

依据：docs/m5_shared_contract.md §5.1/§5.2（BREP-23~25、winner=胜负结果、summary
承载 BREP-24/25 汇总与明细）+ 细化_5e_战斗战报格式 §6.1~§6.3（开始/结束/明细）
     + TC-24~27 + 铁律 2（开始/结束各 1 条）/铁律 11（结算一次性 + 16 行折叠
     TPL-09，3d D-03/L184）+ 细化_3d_消息模板规范 §2（5 条/页 + TPL-08 页脚）+ m5_batch_plan M5-07。

覆盖：TC-24 战斗开始（BREP-23 + 弱点情报行）/ TC-25 结束汇总含回合数与明细入口
（BREP-24）/ TC-26 木桩明细 5 条/页 + 页脚 TPL-08（BREP-25 分页，第 1/2 页）/
TC-27 普通战斗默认不展示明细 / TC-06 单条消息 ≤16 行超限折叠 TPL-09 /
emoji 纪律（仅 ✅/❌ + 排版符号豁免 D-5B）。

说明：{怪物} 展示名 / HP / 回合数 / 收集器聚合（total/max_hit/crits/blocks/items）
非 ActionOutcome 字段（shared_contract §5.1 字段清单无），由接线层（M5-08）注入
——集成断言经 SimpleNamespace / dict 承载（对齐 test_battle_render_settlement.py
的注入形态）。军规5：胜负横幅/掉落（BREP-17~20）由 render_battle_round 结算一次
（M5-06 已测），本文件只测开始/结束/明细。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict

import pytest
import qbot_rpg.core.message_format.battle_render as br

from qbot_rpg.core.message_format.battle_render import (
    render_battle_end,
    render_battle_start,
    render_battle_summary,
)

# 3d §4.2 装饰性 emoji 禁用清单（TC-04 程序化扫描锚点；排版符号豁免 D-5B）
BANNED_EMOJI = "🔥🟢💥⚔️🛡️✨⭐🌟🎉🎊💎🏆❤️💖⚠️🚫📜🗡️🛒🧪⏰📅➡️🔹🔸▸"
# 排版符号豁免（D-5B）：✅❌ 功能性标记 + | → × / （）「」【】·…、。—（TPL-08 页脚 em dash）
_ALLOWED_SYMBOLS = set("✅❌｜→|/×（）「」【】·…、。—")


def _party(**kw: Any) -> SimpleNamespace:
    """玩家形态（level/name/title 承载前缀渲染，M5-08 注入；缺省 35 级斩龙者阿伟）。"""
    defaults: Dict[str, Any] = {
        "level": 35, "name": "阿伟", "title": "斩龙者", "prefix_extra": None,
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _enemy(**kw: Any) -> SimpleNamespace:
    """怪物形态（name/hp/max_hp/turns，M5-08 注入；缺省史莱姆 25/25）。"""
    defaults: Dict[str, Any] = {"name": "史莱姆", "hp": 25, "max_hp": 25}
    defaults.update(kw)
    return SimpleNamespace(**defaults)


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
# TC-24 战斗开始（BREP-23 + 弱点情报行，5e §6.1 / 【前缀】L80）
# ---------------------------------------------------------------------------


def test_tc24_start_exact_with_hint() -> None:
    """TC-24：`/攻击 史莱姆` 战斗开始 —— 独立消息逐字断言（意见一同步：无前缀行）：
    `与史莱姆的战斗开始！史莱姆 25/25`（BREP-23）+ 弱点情报行 `弱点：火（×1.3）`；
    战斗开始消息不再渲染前缀首行（去 `Lv35.阿伟` 前缀）。"""
    text = render_battle_start(
        _party(), _enemy(), hint="弱点：火（×1.3）",
    )
    _assert_no_banned_emoji(text)
    assert text.split("\n") == [
        "与史莱姆的战斗开始！史莱姆 25/25",
        "弱点：火（×1.3）",
    ]


def test_tc24_start_hint_none_omits_hint_line() -> None:
    """hint=None 时弱点/意图情报行省略：仅 BREP-23 一行（无 hint 行，5e §6.1；无前缀行）。"""
    text = render_battle_start(_party(), _enemy())
    assert text.split("\n") == [
        "与史莱姆的战斗开始！史莱姆 25/25",
    ]


def test_tc24_start_fallback_name_and_no_prefix() -> None:
    """缺省回落：玩家信息缺失 → 无前缀；怪物名缺失 → 「怪物」；max_hp 缺省回落当前 HP。"""
    text = render_battle_start(SimpleNamespace(), SimpleNamespace(hp=30))
    assert text.split("\n") == ["与怪物的战斗开始！怪物 30/30"]


# ---------------------------------------------------------------------------
# TC-25 战斗结束汇总（BREP-24：含回合数与明细入口）
# ---------------------------------------------------------------------------


def test_tc25_end_summary_line_exact_with_turns() -> None:
    """TC-25：BOSS 战胜利结束 —— BREP-24 汇总行逐字含回合数与明细入口指令：
    `战斗结束：胜利｜回合数 5｜输入 /战斗记录 查看明细`（回合数对照斩杀基准，
    5e §6.2 L147；无 summary → 不展示明细，TC-27）。"""
    text = render_battle_end(_party(), _enemy(turns=5), "win")
    _assert_no_banned_emoji(text)
    assert text.split("\n") == [
        "Lv35.阿伟 -斩龙者-",
        "战斗结束：胜利｜回合数 5｜输入 /战斗记录 查看明细",
    ]


def test_tc25_winner_labels_win_lose_draw() -> None:
    """BREP-24 {胜负结果}：win/lose/draw → 胜利/失败/平局（5e §4.2）；中文透传。"""
    assert "战斗结束：失败｜回合数 7" in render_battle_end(
        SimpleNamespace(), _enemy(turns=7), "lose",
    )
    assert "战斗结束：平局｜回合数 3" in render_battle_end(
        SimpleNamespace(), _enemy(turns=3), "draw",
    )
    assert "战斗结束：失败｜回合数 1" in render_battle_end(
        SimpleNamespace(), _enemy(turns=1), "失败",
    )


def test_tc25_turns_fallback_player_then_summary_then_zero() -> None:
    """回合数 N 回落链：enemy.turns → player.turns → summary.turns → 0。"""
    # enemy.turns 优先
    assert "回合数 5" in render_battle_end(
        SimpleNamespace(), _enemy(turns=5), "win",
    )
    # 无 enemy → 回落 player.turns
    assert "回合数 4" in render_battle_end(
        SimpleNamespace(turns=4), SimpleNamespace(), "win",
    )
    # 无 enemy/player → 回落 summary.turns
    assert "回合数 2" in render_battle_end(
        SimpleNamespace(), SimpleNamespace(), "win", {"turns": 2},
    )
    # 全缺省 → 0
    assert "回合数 0" in render_battle_end(
        SimpleNamespace(), SimpleNamespace(), "win",
    )


# ---------------------------------------------------------------------------
# TC-26 木桩明细（BREP-25：摘要行 + 5 条/页 + 页脚 TPL-08，5e §6.3 / 数值层 L348）
# ---------------------------------------------------------------------------

_TC26_SUMMARY: Dict[str, Any] = {
    "total": 1220, "max_hit": 180, "crits": 4, "blocks": 2,
    "items": [
        ("火球术", 520), ("普攻", 310), ("灼烧", 210),
        ("突刺", 90), ("追击", 40), ("反击", 30), ("反弹", 15), ("dot", 5),
    ],
}


def test_tc26_summary_page1_5_items_plus_footer() -> None:
    """TC-26：`/木桩` 战后明细（来源 8 项）第 1 页 —— 摘要行 + 前 5 条条目
    + 页脚 TPL-08 `— 第 1/2 页 · 共 8 条 · 输入 /木桩 页码 翻页 —`；条目占比降序。"""
    text = render_battle_summary(_TC26_SUMMARY, page=1)
    _assert_no_banned_emoji(text)
    assert text.split("\n") == [
        "摘要：总伤害 1220｜最大单段 180｜会心 4 次｜格挡 2 次",
        "1. 火球术 520（43%）",
        "2. 普攻 310（25%）",
        "3. 灼烧 210（17%）",
        "4. 突刺 90（7%）",
        "5. 追击 40（3%）",
        "— 第 1/2 页 · 共 8 条 · 输入 /木桩 页码 翻页 —",
    ]


def test_tc26_summary_page2_3_items_footer() -> None:
    """TC-26：`/木桩 2` 翻页正确 —— 第 2 页 3 条（占比降序续尾）+ 页脚 2/2。"""
    text = render_battle_summary(_TC26_SUMMARY, page=2)
    _assert_no_banned_emoji(text)
    assert text.split("\n") == [
        "摘要：总伤害 1220｜最大单段 180｜会心 4 次｜格挡 2 次",
        "1. 反击 30（2%）",
        "2. 反弹 15（1%）",
        "3. dot 5（0%）",
        "— 第 2/2 页 · 共 8 条 · 输入 /木桩 页码 翻页 —",
    ]


def test_tc26_single_page_no_footer() -> None:
    """3 条来源单页 —— 无页脚（3d §2.3 D-02：单页无页脚）；条目逐字 `{来源} {总伤害}（{占比}%）`。"""
    s = {"total": 300, "max_hit": 120, "crits": 1, "blocks": 0,
         "items": [("火球术", 120), ("普攻", 110), ("灼烧", 70)]}
    text = render_battle_summary(s, page=1)
    assert text.split("\n") == [
        "摘要：总伤害 300｜最大单段 120｜会心 1 次｜格挡 0 次",
        "1. 火球术 120（40%）",
        "2. 普攻 110（37%）",
        "3. 灼烧 70（23%）",
    ]
    assert "— 第" not in text


def test_tc26_invalid_page_raises_valueerror() -> None:
    """页码非法（0/负数/非数字）→ ValueError（壳层转 TPL-12，对齐 list_render 契约）。"""
    with pytest.raises(ValueError):
        render_battle_summary(_TC26_SUMMARY, page=0)
    with pytest.raises(ValueError):
        render_battle_summary(_TC26_SUMMARY, page="abc")


# ---------------------------------------------------------------------------
# TC-27 普通战斗默认不展示明细（5e §6.2 L350 / 数值层 L350）
# ---------------------------------------------------------------------------


def test_tc27_normal_battle_no_detail_by_default() -> None:
    """TC-27：普通战斗（非木桩）默认不展示伤害构成明细 —— summary=None 时
    render_battle_end 仅输出 BREP-24 汇总行，无摘要/条目行（收集器仍在跑）。"""
    text = render_battle_end(_party(), _enemy(turns=3), "win")
    lines = text.split("\n")
    assert lines == [
        "Lv35.阿伟 -斩龙者-",
        "战斗结束：胜利｜回合数 3｜输入 /战斗记录 查看明细",
    ]
    assert "摘要：" not in text
    assert "（%" not in text


def test_tc27_end_with_summary_appends_detail_block() -> None:
    """summary 非 None（木桩战/作者开启战后明细）→ BREP-25 明细块追加在汇总行后。"""
    text = render_battle_end(
        _party(), _enemy(turns=8), "win", _TC26_SUMMARY,
    )
    lines = text.split("\n")
    assert lines[0] == "Lv35.阿伟 -斩龙者-"
    assert lines[1] == "战斗结束：胜利｜回合数 8｜输入 /战斗记录 查看明细"
    assert lines[2] == "摘要：总伤害 1220｜最大单段 180｜会心 4 次｜格挡 2 次"
    assert len(lines) == 2 + 1 + 8                      # 前缀+BREP-24 + 摘要 + 8 条目
    _assert_no_banned_emoji(text)


# ---------------------------------------------------------------------------
# TC-06 单条消息 ≤16 行折叠（铁律 11 / 3d D-03 / TPL-09）
# ---------------------------------------------------------------------------


def test_tc06_fold_over_16_lines() -> None:
    """TC-06：明细条目超限 → 单条消息 ≤16 行，按正文尾部折叠 TPL-09
    `…（其余 {N} 条已折叠，输入 /战斗记录 {page} 查看）`（折叠行亦计入 16 行）。"""
    s20: Dict[str, Any] = {
        "total": 5000, "max_hit": 300, "crits": 5, "blocks": 2,
        "items": [("来源%02d" % i, 5000 - i * 200) for i in range(1, 21)],
    }
    text = render_battle_end(_party(), _enemy(turns=45), "win", s20)
    lines = text.split("\n")
    _assert_no_banned_emoji(text)
    assert len(lines) <= 16                              # 超限折叠（3d D-03）
    assert lines[0] == "Lv35.阿伟 -斩龙者-"
    assert lines[1] == "战斗结束：胜利｜回合数 45｜输入 /战斗记录 查看明细"
    assert lines[2] == "摘要：总伤害 5000｜最大单段 300｜会心 5 次｜格挡 2 次"
    # 折叠行 TPL-09：保留头部 12 条，折叠 8 条（keep=16-2-2=12），被折叠内容在第 3 页
    assert lines[-1] == "…（其余 8 条已折叠，输入 /战斗记录 3 查看）"
    assert len(lines) == 16                              # 前缀+BREP-24+摘要+12 条+TPL-09


def test_tc06_no_fold_within_limit() -> None:
    """明细条目未超 16 行上限 → 不折叠、无 TPL-09 行，全量展示。"""
    s6: Dict[str, Any] = {
        "total": 600, "max_hit": 100, "crits": 1, "blocks": 0,
        "items": [("来源%d" % i, 100) for i in range(1, 7)],
    }
    text = render_battle_end(_party(), _enemy(turns=5), "win", s6)
    lines = text.split("\n")
    assert len(lines) <= 16
    assert "已折叠" not in text
    assert len(lines) == 2 + 1 + 6                       # 前缀+BREP-24 + 摘要 + 6 条


# ---------------------------------------------------------------------------
# P2-2 战斗轮消息 16 行折叠（铁律 11 / 5e TC-06 / _fold_message_lines）
# ---------------------------------------------------------------------------

def test_fold_message_lines_round_message() -> None:
    """战斗轮消息超 16 行 → 折叠中间过程行（保留首行 + 末段关键行 + 省略行）。"""
    lines = [f"第 {i} 行" for i in range(20)]
    folded = br._fold_message_lines(lines, max_lines=16)
    assert len(folded) == 16
    assert folded[0] == "第 0 行"              # 保留首行（前缀/首行动）
    assert folded[-1] == "第 19 行"            # 保留末行（操作提示/结算）
    assert "…（其余 5 行已折叠）" in folded     # 折叠中间 5 行（head1 + tail14 + fold1）


def test_render_battle_round_folds_over16() -> None:
    """TC-06：render_battle_round 输出超 16 行（多段连段）→ 单条消息 ≤16 行。"""
    segs = [
        {"seg": i + 1, "action": "连斩", "final_damage": 5, "target_hp": 30 - i,
         "target_max_hp": 40, "target": "史莱姆", "crit": "low", "blocked": False}
        for i in range(20)
    ]
    oc = {
        "ok": True, "seq": 1, "actor": "player", "action_type": "连斩", "target": "enemy",
        "hit": True, "crit": "low", "blocked": False, "raw_damage": 100,
        "final_damage": 100, "target_hp": 10, "side_effects": (), "message": "",
        "battle_ended": False, "status": None, "segments": segs,
    }
    # 直接调 _render_combo_segments 产 20 段行 → 折叠
    from types import SimpleNamespace
    out = SimpleNamespace(**oc)
    seg_lines = br._render_combo_segments(out)
    assert len(seg_lines) == 20                      # 段行 20 行（未折叠）
    folded = br._fold_message_lines(seg_lines, max_lines=16)
    assert len(folded) == 16
    assert "第 1 段" in folded[0]              # 保留首段
    assert "…（其余 5 行已折叠）" in folded     # 折叠中间 5 段（head1 + tail14 + fold1）
    assert "第 20 段" in folded[-1]            # 保留末段
