"""状态指令单测（M6 批次1·路B · qbot_rpg/commands/status_commands.py）——TC-STT-01~03 全量。

依据：细化_M6_三引擎与基础指令（D1）§五（STT-01~STT-05 / TC-STT-01~03，承接 4f
TC-07/09/10）+ 细化_4f §二（RUL-10~15 / TPL-4F-02/03）+ 细化_3d（TPL-12 / emoji 纪律）。

测试风格对齐 tests/unit/test_basic_commands.py：make_ctx 模式、纯 pytest、零 NoneBot、
断言具体输出字符串。渲染仅 ✅/❌ 功能性标记（M5 裁决「不用 emoji」）。
"""

from __future__ import annotations

import pytest

from qbot_rpg.commands import status_commands as sc
from qbot_rpg.commands.basic_commands import TPL_REGISTER_GATE
from qbot_rpg.commands.parsers import ParsedCommand, parse_command
from qbot_rpg.commands.router import Router
from qbot_rpg.commands.status_commands import (
    STATUS_CMD,
    attr_line,
    cmd_status,
    effects_line,
    level_line,
    location_line,
    prefix_line,
    register_status_commands,
    target_line,
)
from qbot_rpg.data.player import PlayerAttributes

# 3d §4.2 装饰性 emoji 禁用清单（渲染输出扫描锚点）
BANNED_EMOJI = set("🔥🟢💥⚔️🛡️✨⭐🌟🎉🎊💎🏆❤️💖⚠️🚫📜🗡️🛒🧪⏰📅➡️🔹🔸▸")

# 属性模板（3b §4.1：hp/mp/str/con 等）
_STATS = {
    "hp": {"name": "生命", "type": "resource", "base": 100},
    "mp": {"name": "魔力", "type": "resource", "base": 30},
    "str": {"name": "力量", "type": "combat", "base": 15},
    "con": {"name": "体质", "type": "combat", "base": 10},
}


def make_ctx(**over):
    """全字段玩家基础 ctx（每场景新造；player 用可变 dict，hp/mp 当前值）。"""
    base = {
        "player": {"name": "阿伟", "level": 3, "exp": 320, "hp": 21, "mp": 8},
        "attributes": PlayerAttributes(base={"hp": 100, "mp": 30, "str": 15, "con": 10}),
        "exp_next": 1000,
        "level_cap": None,
        "location": "新手村 · 中央广场",
        "effects": [],
        "target": None,
        "title": "斩龙者",
        "registered": True,
        "stats": {k: dict(v) for k, v in _STATS.items()},
        "settings": {},
    }
    base.update(over)
    return base


def parse(raw: str) -> ParsedCommand:
    """parse_command 封装（parsers.DEFAULT_WHITELIST 已含「状态」）。"""
    return parse_command(raw)


# ---------------------------------------------------------------------------
# TC-STT-01 战斗外总览面板（承接 4f TC-07）
# ---------------------------------------------------------------------------

def test_tc_stt_01_overview_panel():
    """TC-STT-01：/状态 → 前缀行 + 等级/经验行 + 属性行 + 位置行 + 效果区（无效果 【效果】无）。
    意见一同步：等级/经验各占一行、属性每项独立一行（去 ｜）。"""
    out = cmd_status(parse("/状态"), make_ctx())
    lines = out.splitlines()
    assert lines[0] == "Lv3.阿伟 -斩龙者-"                      # ① 前缀行
    assert lines[1] == "【等级】3"                               # ② 等级行（独立一行）
    assert lines[2] == "【经验】320/1000"                        # ② 经验行（独立一行）
    assert lines[3] == "【生命】21/100"                          # ③ 属性行（每项独立一行）
    assert lines[4] == "【魔力】8/30"
    assert lines[5] == "【攻击】15"
    assert lines[6] == "【防御】10"
    assert lines[7] == "【位置】新手村 · 中央广场"               # ④ 位置行
    assert lines[8] == "【效果】无"                              # ⑤ 效果区
    assert len(lines) == 9                                       # 战斗外无目标行


def test_stt_prefix_no_title_dashes():
    """前缀行无称号 → `Lv3.阿伟 - -`（缺省 empty_title_text）。"""
    assert prefix_line(make_ctx(title="")) == "Lv3.阿伟 - -"
    assert prefix_line(make_ctx(title=None)) == "Lv3.阿伟 - -"


def test_stt_level_max_cap():
    """RUL-11：level ≥ level_cap → 【等级】45【已满级】。"""
    ctx = make_ctx(player={"name": "阿伟", "level": 45, "exp": 99999, "hp": 21, "mp": 8},
                   level_cap=45)
    assert level_line(ctx) == "【等级】45【已满级】"
    assert "经验" not in level_line(ctx)


def test_stt_level_max_exp_next_zero():
    """LVL-11 口径：exp_next == 0（满级不增长）→ 【已满级】。"""
    ctx = make_ctx(exp_next=0)
    assert level_line(ctx) == "【等级】3【已满级】"


def test_stt_level_exp_no_next():
    """exp_next 缺省 → 仅显当前经验（独立一行，意见一同步）。"""
    ctx = make_ctx(exp_next=None)
    assert level_line(ctx) == "【等级】3\n【经验】320"


def test_stt_attr_line_final_via_pipeline():
    """STT-03 属性行 = 最终层数值（三层管线结果）：base + 加成/临时 全链重算。"""
    attrs = PlayerAttributes(
        base={"hp": 100, "mp": 30, "str": 15, "con": 10},
        bonus={"flat": {"str": 5}, "pct": {}},
        temp={"pct": {"str": 20}, "flat": {}},
    )
    ctx = make_ctx(attributes=attrs)
    out = cmd_status(parse("/状态"), ctx)
    # str 最终 = (15+5) * 1.2 = 24
    assert "【攻击】24" in out
    assert "【生命】21/100" in out                                # 资源型 当前/最终上限


def test_stt_attr_final_direct_consumed():
    """属性行直接消费 ctx["attr_final"]（装配层已跑 calc_all_final_attributes；每项独立一行）。"""
    ctx = make_ctx(attr_final={"hp": 100, "mp": 30, "str": 18, "con": 12})
    assert attr_line(ctx) == "【生命】21/100\n【魔力】8/30\n【攻击】18\n【防御】12"


def test_stt_attr_final_via_resolver():
    """resolve_attr_final 兜底（ctx["attributes"]/attr_final 均缺省时；每项独立一行）。"""
    ctx = make_ctx(attributes=None)
    ctx.pop("attr_final", None)
    ctx["resolve_attr_final"] = lambda: {"hp": 100, "mp": 30, "str": 20, "con": 9}
    assert attr_line(ctx) == "【生命】21/100\n【魔力】8/30\n【攻击】20\n【防御】9"


def test_stt_location_default():
    """位置行缺省 → 【位置】未知。"""
    assert location_line(make_ctx(location=None)) == "【位置】未知"


# ---------------------------------------------------------------------------
# TC-STT-02 效果区显示（承接 4f TC-09 / RUL-13）
# ---------------------------------------------------------------------------

def test_tc_stt_02_effect_zone():
    """TC-STT-02：有中毒状态 → `【效果】中毒 2/3（来源：剧毒史莱姆）`。"""
    ctx = make_ctx(effects=[{"name": "中毒", "remaining": 2, "duration": 3,
                             "source": "剧毒史莱姆"}])
    out = cmd_status(parse("/状态"), ctx)
    assert "【效果】中毒 2/3（来源：剧毒史莱姆）" in out


def test_stt_effect_zone_multi_and_overrun():
    """RUL-13：>5 个状态 → 前 5 个 + `还有 N 个状态`。"""
    effects = [{"name": f"状态{i}", "remaining": i, "source": "来源"} for i in range(1, 8)]
    ctx = make_ctx(effects=effects)
    out = effects_line(ctx)
    assert "【效果】" in out
    assert out.count("状态") == 5 + 1                              # 前 5 个 + 「还有 N 个状态」
    assert "还有 2 个状态" in out


def test_stt_effect_zone_no_effect():
    """无效果 → 【效果】无。"""
    assert effects_line(make_ctx(effects=[])) == "【效果】无"
    assert effects_line(make_ctx(effects=None)) == "【效果】无"


def test_stt_effect_remaining_only_and_no_source():
    """效果 duration/source 缺省 → 仅 `{名} {剩余}回合`。"""
    ctx = make_ctx(effects=[{"name": "灼烧", "remaining": 1}])
    assert effects_line(ctx) == "【效果】灼烧 1回合"


# ---------------------------------------------------------------------------
# TC-STT-03 战斗内 /状态（承接 4f TC-10 / RUL-15）
# ---------------------------------------------------------------------------

def test_tc_stt_03_battle_target_line():
    """TC-STT-03：战斗中 /状态 → 面板 + `【目标】史莱姆 18/30（第 3 回合）`；并行不互斥。"""
    ctx = make_ctx(target={"name": "史莱姆", "hp": 18, "max_hp": 30, "turn": 3})
    out = cmd_status(parse("/状态"), ctx)
    lines = out.splitlines()
    assert "【目标】史莱姆 18/30（第 3 回合）" in out
    # 目标行位于位置行之后、效果区之前（TPL-4F-03 行序；意见一后行号前移）
    assert lines[7] == "【位置】新手村 · 中央广场"
    assert lines[8] == "【目标】史莱姆 18/30（第 3 回合）"
    assert lines[9] == "【效果】无"
    # 战斗指令并行不互斥：/状态 照常渲染（非战斗指令不受限，框架 L248）
    assert target_line(ctx) == "【目标】史莱姆 18/30（第 3 回合）"


def test_stt_target_absent_no_line():
    """战斗外 ctx["target"] 缺省 → 不渲染目标行。"""
    assert target_line(make_ctx(target=None)) is None
    out = cmd_status(parse("/状态"), make_ctx(target=None))
    assert "【目标】" not in out


# ---------------------------------------------------------------------------
# 注册门槛 RUL-08（非豁免）/ 语法 TPL-12
# ---------------------------------------------------------------------------

def test_stt_unregistered_gate():
    """STT-05 ④：未注册 → RUL-08 拦截（非豁免）。"""
    out = cmd_status(parse("/状态"), make_ctx(registered=False))
    assert out == TPL_REGISTER_GATE


@pytest.mark.parametrize("raw", ["/状态 1", "/状态 0", "/状态 abc"])
def test_stt_with_args_tpl12(raw):
    """/状态 带参（面板无分页）→ TPL-12。"""
    out = cmd_status(parse(raw), make_ctx())
    assert out.startswith("❌ 指令不正确：")


def test_stt_parse_error_tpl12():
    """解析错误 → TPL-12。"""
    parsed = ParsedCommand("/状态", command=STATUS_CMD, args=[], error="未知分隔符")
    out = cmd_status(parsed, make_ctx())
    assert out.startswith("❌ 指令不正确：")


def test_stt_fixed_subword_tpl12():
    """固定子词（如 /状态 确认）→ TPL-12（面板无子词）。"""
    parsed = ParsedCommand("/状态", command=STATUS_CMD, args=[], fixed_subword="确认")
    out = cmd_status(parsed, make_ctx())
    assert out.startswith("❌ 指令不正确：")


# ---------------------------------------------------------------------------
# 横切：无装饰 emoji
# ---------------------------------------------------------------------------

def test_status_no_decorative_emoji():
    """M5 裁决：/状态 渲染输出零装饰 emoji（仅 ✅/❌ + 排版符号）。"""
    outputs = [
        cmd_status(parse("/状态"), make_ctx()),
        cmd_status(parse("/状态"), make_ctx(effects=[{"name": "中毒", "remaining": 2,
                                                      "duration": 3, "source": "剧毒史莱姆"}])),
        cmd_status(parse("/状态"), make_ctx(target={"name": "史莱姆", "hp": 18,
                                                    "max_hp": 30, "turn": 3})),
        cmd_status(parse("/状态"), make_ctx(registered=False)),
    ]
    for text in outputs:
        for ch in text:
            assert ch not in BANNED_EMOJI, f"命中禁用装饰 emoji：{ch} in {text!r}"


# ---------------------------------------------------------------------------
# 装配（STT-05 ②）
# ---------------------------------------------------------------------------

def test_register_status_commands():
    """STT-05 ②：注册「状态」CommandSpec（可快捷白名单）。"""
    router = Router()
    register_status_commands(router, make_context=lambda p: make_ctx())
    assert router.has(STATUS_CMD)
    assert router.get(STATUS_CMD).whitelisted


def test_status_without_make_context_raises():
    """【待接线】无 make_context 时 handler 调用抛 RuntimeError（装配未注入显式错误）。"""
    router = Router()
    register_status_commands(router)
    with pytest.raises(RuntimeError):
        router.get(STATUS_CMD).handler(parse("/状态"))


def test_router_parse_integration():
    """/状态 经 parse_command + 注册后 handler 可执行（完整链路）。"""
    router = Router()
    register_status_commands(router, make_context=lambda p: make_ctx())
    out = router.get(STATUS_CMD).handler(parse("/状态"))
    assert out.startswith("Lv3.阿伟 -斩龙者-")
    assert "【效果】无" in out


def test_stt_imprints_zone():
    """P2-1（M6 批1B 审查）：印记区（RUL-13/STT-01⑤）——ctx["imprints"] 渲染【印记】行。"""
    ctx = make_ctx(imprints=[
        {"name": "火焰印记", "count": 2, "source": "敌方施放"},
        {"name": "寒霜印记", "source": "敌方施放"},
        {"name": "无来源印记"},
    ])
    out = sc.imprints_line(ctx)
    assert "【印记】火焰印记×2（敌方施放）" in out
    assert "寒霜印记（敌方施放）" in out          # count 缺省不显 ×
    assert "无来源印记" in out
    # 无印记 → None（不渲染）
    assert sc.imprints_line(make_ctx()) is None
    assert sc.imprints_line(make_ctx(imprints=[])) is None
    # /状态 完整链路含印记行（效果区后）
    out2 = cmd_status(parse("/状态"), ctx)
    assert "【印记】火焰印记×2（敌方施放）" in out2
    assert "【效果】无" in out2


def test_stt_target_partial_fields_degrade():
    """P2-9（M6 批1B 审查）：target 字段不全（hp/max_hp/turn 任一 None）→ 整行降级 None，
    防 `【目标】xx None/None（第 None 回合）`。"""
    assert target_line(make_ctx(target={"name": "史莱姆", "hp": None, "max_hp": 30, "turn": 3})) is None
    assert target_line(make_ctx(target={"name": "史莱姆", "hp": 18, "max_hp": None, "turn": 3})) is None
    assert target_line(make_ctx(target={"name": "史莱姆", "hp": 18, "max_hp": 30, "turn": None})) is None
    assert target_line(make_ctx(target={"name": "史莱姆", "hp": 18, "max_hp": 30, "turn": 3})) \
        == "【目标】史莱姆 18/30（第 3 回合）"
