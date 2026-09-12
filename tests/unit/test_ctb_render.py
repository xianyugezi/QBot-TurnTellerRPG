"""CTB 三渲染入口单测（tests/unit/test_ctb_render.py）—— CTB 重写 · Agent 5（DataRender）。

覆盖（qbot_rpg/core/message_format/battle_render.py 新增入口）：
  1. render_battle_action        单次行动完整链路（prefix + 玩家/怪物积木 + 状态行 + 折叠）
  2. render_battle_action_batch  多 NPC 连锁行动合并为一条（ActionBatchReport 形态）
  3. render_battle_ready         玩家 ready 提示（轮到你行动）
  4. 复用性：新入口输出与既有 render_battle_round 积木逐字一致（复用而非重写）
  5. 既有三入口（start/round/end）在 CTB 数据形态下仍可用 + 兜底不崩
  6. 数据层 qbot_rpg/data/ctb.py（纯数据）+ 装配层 qbot_rpg/core/ctb_config.py
     （recovery 解析 / 覆盖表 / CtbRuleConfig 装配 / settings["ctb"] 段）
     —— 架构修复后按分层分别取符号；并断言 data 层零 qbot_rpg 依赖（TC-03）

依据：
  - docs/ctb/01_asset_inventory.md §0.2 CTB 事件位点词典 + §0.1 三分类口径
  - docs/ctb/02_wave_a_decisions.md 裁决 1（recovery = 总行动恢复值）+ 修复 2
    （per-action recovery 注入入口）；core/ctb_rules.ActionBatchReport
  - 既有渲染契约：3d S1 返回 str / S2 无 "[CQ:" / 铁律 11 ≤16 行折叠 / D-01 禁装饰 emoji

说明：本文件 import ActionOutcome / TurnReport（真实字段载体，与既有渲染测试同口径）；
展示信息（action_name / 最大 HP）非 ActionOutcome 字段，由接线层经可省略属性注入。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict

from qbot_rpg.core.battle import ActionOutcome
from qbot_rpg.core.message_format.battle_render import (
    render_battle_action,
    render_battle_action_batch,
    render_battle_end,
    render_battle_ready,
    render_battle_round,
    render_battle_start,
)

# 3d §4.2 装饰性 emoji 禁用清单（复用既有渲染测试锚点；排版符号豁免 D-5B）
BANNED_EMOJI = "🔥🟢💥⚔️🛡️✨⭐🌟🎉🎊💎🏆❤️💖⚠️🚫📜🗡️🛒🧪⏰📅➡️🔹🔸▸"
ALLOWED_MARKERS = "✅❌"


def _outcome(**kw: Any) -> ActionOutcome:
    """构造 ActionOutcome（真实字段；缺省 = 玩家普攻命中史莱姆 25→7）。"""
    defaults: Dict[str, Any] = {
        "ok": True, "seq": 1, "actor": "player", "action_type": "normal",
        "target": "史莱姆", "hit": True, "crit": "low", "blocked": False,
        "raw_damage": 18, "final_damage": 18, "target_hp": 7,
        "side_effects": (), "message": "阿伟 对 史莱姆 造成 18 伤害",
        "battle_ended": False, "status": None,
    }
    defaults.update(kw)
    return ActionOutcome(**defaults)


def _enriched(oc: ActionOutcome, **extra: Any) -> SimpleNamespace:
    """接线层形态 outcome：真实字段（ActionOutcome.__dict__）+ 展示信息注入。"""
    return SimpleNamespace(**{**oc.__dict__, **extra})


def _assert_no_banned_emoji(text: str) -> None:
    for ch in text:
        assert ch not in BANNED_EMOJI, f"战报出现禁用 emoji：{ch!r}（{text}）"


# ---------------------------------------------------------------------------
# render_battle_action（单次行动渲染）
# ---------------------------------------------------------------------------
def test_action_player_hit_reuses_round_blocks() -> None:
    """单次行动（玩家命中）= 复用回合制玩家积木 → 与 render_battle_round 逐字一致。"""
    oc = _enriched(_outcome(action_type="skill"), action_name="施放火球术", target_max_hp=25)
    src = SimpleNamespace(outcomes=(oc,), actor_id="player")
    assert render_battle_action(src) == render_battle_round(src)
    assert render_battle_action(src) == "✅ 你施放火球术\n造成 18 伤害"


def test_action_prefix_first_line_and_ctb_status() -> None:
    """前缀首行 + CTB 状态行（距离你下次行动：{n}）；前缀仅首行。"""
    oc = _enriched(_outcome(action_type="skill"), action_name="施放火球术", target_max_hp=25)
    src = SimpleNamespace(outcomes=(oc,), actor_id="player", ready_in=33,
                          level=35, name="阿伟", title="斩龙者")
    lines = render_battle_action(src).split("\n")
    assert lines[0] == "Lv35.阿伟 -斩龙者-"
    assert lines[1] == "✅ 你施放火球术"
    assert lines[2] == "造成 18 伤害"
    assert len(lines) == 4                              # 批4：目标血量行已砍
    assert lines[-1] == "距离你下次行动：33"
    assert not any("Lv35" in ln for ln in lines[1:])


def test_action_npc_turn_head_line() -> None:
    """NPC 行动输出行动头行（轮到 {actor} 行动）；玩家侧不输出头行。"""
    oc = _enriched(_outcome(actor="enemy", action_type="normal", target="player",
                            target_hp=21),
                   action_name="撞击", attacker_name="史莱姆", player_max_hp=30)
    npc = SimpleNamespace(outcomes=(oc,), actor_id="e1", turn_name="史莱姆")
    lines = render_battle_action(npc).split("\n")
    assert lines[0] == "轮到 史莱姆 行动"
    assert "史莱姆撞击" in lines[1]

    player = SimpleNamespace(outcomes=(oc,), actor_id="player", turn_name="史莱姆")
    assert "轮到" not in render_battle_action(player)


def test_action_kill_line_follows_damage() -> None:
    """扣血后 target_hp<=0 → 击杀行紧跟伤害行（铁律 9）。"""
    oc = _enriched(_outcome(action_type="skill", final_damage=25, target_hp=0),
                   action_name="施放火球术", target_max_hp=25)
    text = render_battle_action(SimpleNamespace(outcomes=(oc,), actor_id="player"))
    assert text.split("\n") == [
        "✅ 你施放火球术",
        "造成 25 伤害",
        "✅ 你击败了史莱姆！",
    ]


def test_action_end_settlement_block() -> None:
    """行动即终局（ended/status=win）→ 结算块并入同一条消息（军规5）。"""
    oc = _enriched(_outcome(action_type="skill", final_damage=25, target_hp=0),
                   action_name="施放火球术", target_max_hp=25)
    src = SimpleNamespace(outcomes=(oc,), actor_id="player", ended=True, status="win",
                          exp=30, gold=12, drops=(("狼牙", 2),), enemy_name="史莱姆")
    text = render_battle_action(src)
    assert "✅ 你击败了史莱姆！" in text
    assert "获得经验：30" in text and "获得金币：12" in text
    assert "1.狼牙×2" in text


def test_action_batch_entries_merged_into_action() -> None:
    """action_result 携带 batch → 其 entries 并入单次行动渲染（可选路径）。"""
    p = _enriched(_outcome(), action_name="攻击", target_max_hp=25)
    e = _enriched(_outcome(actor="enemy", action_type="normal", target="player"),
                  action_name="撞击", attacker_name="史莱姆", player_max_hp=30)
    src = SimpleNamespace(outcomes=(p,), actor_id="player",
                          batch={"entries": [e.__dict__]})
    text = render_battle_action(src)
    assert "✅ 你攻击" in text and "造成 18 伤害" in text   # 玩家行动（三行化）
    assert "史莱姆撞击" in text              # 批量并入的 NPC 行动


def test_action_fold_over_16_lines() -> None:
    """超 16 行折叠（铁律 11）：折叠行计入 ≤16 行上限。"""
    ocs = [_enriched(_outcome(seq=i), action_name="攻击", target_max_hp=25)
           for i in range(1, 21)]
    text = render_battle_action(SimpleNamespace(outcomes=tuple(ocs), actor_id="player"))
    assert len(text.split("\n")) <= 16
    assert "行已折叠" in text


def test_action_tolerates_bad_input() -> None:
    """兜底不崩：None / 空 outcomes / 非 Mapping 异常对象 → 返回 str（不抛）。"""
    for bad in (None, SimpleNamespace(), SimpleNamespace(outcomes=()), 12345):
        out = render_battle_action(bad)
        assert isinstance(out, str)


# ---------------------------------------------------------------------------
# render_battle_action_batch（多 NPC 连锁行动合并一条）
# ---------------------------------------------------------------------------
def test_batch_merges_npc_actions_one_message() -> None:
    """多 NPC 行动合并为**一条**消息（ActionBatchReport 形态；含时间头）。"""
    e1 = _enriched(_outcome(actor="enemy", action_type="normal", target="player",
                            target_hp=21),
                   action_name="撞击", attacker_name="史莱姆", player_max_hp=30)
    e2 = _enriched(_outcome(actor="enemy", action_type="normal", target="player",
                            target_hp=14),
                   action_name="撕咬", attacker_name="狼", player_max_hp=30)
    batch = {"entries": [e1.__dict__, e2.__dict__], "start_time": 100, "end_time": 133.33}
    lines = render_battle_action_batch(batch).split("\n")
    assert lines[0] == "（怪物行动）"
    assert lines[1] == "❌ 史莱姆撞击，你受到 18 伤害（HP 21/30）"
    assert lines[2] == "❌ 狼撕咬，你受到 18 伤害（HP 14/30）"
    assert isinstance(render_battle_action_batch(batch), str)


def test_batch_object_and_outcomes_fallback() -> None:
    """对象形态 entries 支持；无 entries → 退化为 outcomes 序列（均合并且不抛）。"""
    e = _enriched(_outcome(actor="enemy", action_type="normal", target="player",
                           target_hp=21),
                  action_name="撞击", attacker_name="史莱姆", player_max_hp=30)
    obj = SimpleNamespace(entries=[SimpleNamespace(**e.__dict__)], start_time=0.0,
                          end_time=0.0)
    assert "史莱姆撞击" in render_battle_action_batch(obj)
    fallback = SimpleNamespace(outcomes=(SimpleNamespace(**e.__dict__),))
    assert "史莱姆撞击" in render_battle_action_batch(fallback)


def test_batch_paused_ready_line() -> None:
    """批次末尾暂停（paused_ready_at）→ CTB 状态行（玩家 ready 距下次）。"""
    e = _enriched(_outcome(actor="enemy", action_type="normal", target="player",
                           target_hp=21),
                  action_name="撞击", attacker_name="史莱姆", player_max_hp=30)
    batch = {"entries": [e.__dict__], "paused_ready_at": 200}
    assert render_battle_action_batch(batch).split("\n")[-1] == "距离你下次行动：200"


def test_batch_tolerates_bad_input() -> None:
    """兜底不崩：None / 空 / 非 Mapping → 返回 str。"""
    for bad in (None, {}, SimpleNamespace(), "nonsense"):
        assert isinstance(render_battle_action_batch(bad), str)


# ---------------------------------------------------------------------------
# render_battle_ready（玩家 ready 提示）
# ---------------------------------------------------------------------------
def test_ready_minimal() -> None:
    """玩家 ready 提示：前缀 + 「轮到你行动了」。"""
    text = render_battle_ready(SimpleNamespace(level=35, name="阿伟", title="斩龙者"))
    assert text.split("\n") == ["Lv35.阿伟 -斩龙者-", "轮到你行动了"]


def test_ready_with_ready_in_and_hint() -> None:
    """ready_in → CTB 状态行；显式 hint 优先于自动组装提示行。"""
    src = SimpleNamespace(level=35, name="阿伟", title=None, ready_in=50)
    lines = render_battle_ready(src, hint="攻击 或 防御").split("\n")
    assert lines[0].startswith("Lv35.阿伟")
    assert lines[1] == "轮到你行动了"
    assert lines[2] == "距离你下次行动：50"
    assert lines[3] == "攻击 或 防御"


def test_ready_auto_hint_from_hp_snapshot() -> None:
    """无显式 hint 时复用 render_action_hint（HP/方位操作提示行）。"""
    src = SimpleNamespace(level=1, name="阿伟", player=21, enemy=7,
                          player_max_hp=30, enemy_max_hp=25, enemy_name="史莱姆")
    text = render_battle_ready(src)
    assert "你 21/30\n史莱姆 7/25\n→ 攻击 或 攻击 <技能名>" in text


def test_ready_no_prefix_when_info_missing() -> None:
    """玩家信息缺失 → 无前缀行（不臆造），仍输出 ready 行。"""
    assert render_battle_ready(None).split("\n") == ["轮到你行动了"]


def test_ready_tolerates_bad_input() -> None:
    """兜底不崩：None / 非 Mapping / 异常对象 → 返回 str。"""
    for bad in (None, 123, SimpleNamespace()):
        assert isinstance(render_battle_ready(bad), str)


# ---------------------------------------------------------------------------
# 既有三入口不回归（CTB 数据形态下仍可用 + 兜底不崩）
# ---------------------------------------------------------------------------
def test_existing_entries_still_work() -> None:
    """render_battle_start / render_battle_round / render_battle_end 保持可用。"""
    enemy = SimpleNamespace(name="史莱姆", hp=25, max_hp=25)
    assert render_battle_start(None, enemy) == "与史莱姆的战斗开始！\n史莱姆 25/25"

    oc = _enriched(_outcome(action_type="skill"), action_name="施放火球术", target_max_hp=25)
    assert render_battle_round(SimpleNamespace(outcomes=(oc,))) == (
        "✅ 你施放火球术\n造成 18 伤害")

    end = render_battle_end(SimpleNamespace(), enemy, "lose", status="lose",
                            enemy_name="史莱姆")
    assert "战斗结束：失败" in end


def test_existing_entries_tolerate_bad_input() -> None:
    """既有入口兜底不崩（CTB 重写不得破坏原有健壮性）。"""
    assert isinstance(render_battle_start(None, None), str)
    assert isinstance(render_battle_round(None), str)
    assert isinstance(render_battle_end(None, None, "win"), str)


# ---------------------------------------------------------------------------
# emoji 纪律（D-01；仅 ✅/❌ + 排版符号）
# ---------------------------------------------------------------------------
def test_no_banned_emoji_in_new_templates() -> None:
    """三入口全部模板输出零装饰 emoji。"""
    p = SimpleNamespace(**_enriched(_outcome(action_type="skill"), action_name="施放火球术",
                                    target_max_hp=25).__dict__, level=35, name="阿伟")
    npc = _enriched(_outcome(actor="enemy", action_type="normal", target="player",
                             target_hp=21),
                    action_name="撞击", attacker_name="史莱姆", player_max_hp=30)
    samples = [
        render_battle_action(SimpleNamespace(outcomes=(p,), actor_id="player", ready_in=33)),
        render_battle_action_batch({"entries": [npc.__dict__], "start_time": 1, "end_time": 2}),
        render_battle_ready(SimpleNamespace(level=35, name="阿伟", ready_in=50)),
    ]
    for text in samples:
        _assert_no_banned_emoji(text)


# ---------------------------------------------------------------------------
# 数据层 qbot_rpg/data/ctb.py（纯数据）+ 装配层 qbot_rpg/core/ctb_config.py（逻辑）
#
# 架构修复（2026-09-10 主 Agent）：原 data/ctb.py 同时承载数据与逻辑，且 data 层
# import core 违反 TC-03 依赖矩阵（data 允许依赖集 = set()，细化_3a §1.4）。
# 现拆分——纯数据留在 data/ctb.py，解析/装配逻辑迁至 core/ctb_config.py。
# 下列用例按新分层取符号。
# ---------------------------------------------------------------------------
def test_ctb_data_layer_is_dependency_free() -> None:
    """data/ctb.py 零 qbot_rpg 依赖（TC-03 硬约束）+ 数值与 core/ctb_rules 对齐。"""
    import qbot_rpg.data.ctb as ctb_data
    from qbot_rpg.core import ctb_rules

    # （1）纯数据层不得 import 任何 qbot_rpg 层（扫真实 import 语句，忽略文档提及）
    src_lines = Path(ctb_data.__file__).read_text(encoding="utf-8").splitlines()
    import_lines = [
        ln.strip() for ln in src_lines
        if ln.strip().startswith(("import ", "from "))
    ]
    assert import_lines, "data/ctb.py 应至少有一行 import（typing）"
    for line in import_lines:
        assert "qbot_rpg" not in line, f"data 层出现 qbot_rpg 依赖：{line}"

    # （2）分层两处落值必须同口径（ctb_config._assert_no_value_drift 同判据）
    assert ctb_data.DEFAULT_ACTION_RECOVERY == ctb_rules.DEFAULT_RECOVERY
    for kind in ("basic", "skill", "item", "guard", "flee"):
        assert ctb_data.ACTION_RECOVERY_TABLE[kind] == ctb_rules.DEFAULT_RECOVERY
    # 行动种类标识与规则层缺省值口径一致（无漂移）
    assert ctb_data.RECOVERY_KEY == "recovery"
    assert ctb_data.RECOVERY_KEY_CN == "行动恢复"


def test_ctb_data_settings_defaults_aligned_with_rules() -> None:
    """data 层 DEFAULT_CTB_SETTINGS 的公式三参 + 时间标准两参对齐 ctb_rules 常量。"""
    from qbot_rpg.core import ctb_rules
    from qbot_rpg.data.ctb import DEFAULT_CTB_SETTINGS

    assert DEFAULT_CTB_SETTINGS["speed_reference"] == ctb_rules.SPEED_REFERENCE
    assert DEFAULT_CTB_SETTINGS["min_speed"] == ctb_rules.MIN_SPEED
    assert DEFAULT_CTB_SETTINGS["action_delay"] == ctb_rules.ACTION_DELAY
    assert DEFAULT_CTB_SETTINGS["default_recovery"] == ctb_rules.DEFAULT_RECOVERY
    assert DEFAULT_CTB_SETTINGS["enabled"] is True
    # 时间标准（2026-09-11 增补 v1 §〇/§一：隐性口径、可调）
    assert DEFAULT_CTB_SETTINGS["time_unit"] == ctb_rules.TIME_UNIT
    assert DEFAULT_CTB_SETTINGS["default_action_time"] == ctb_rules.DEFAULT_ACTION_TIME


def test_ctb_resolve_action_recovery_override() -> None:
    """action 自带 recovery 键 → 覆盖种类缺省（覆盖关系，非附加）。"""
    from qbot_rpg.core.ctb_config import resolve_action_recovery
    from qbot_rpg.data.ctb import DEFAULT_ACTION_RECOVERY

    assert resolve_action_recovery({"kind": "skill"}) == DEFAULT_ACTION_RECOVERY
    assert resolve_action_recovery({"kind": "skill", "recovery": 200}) == 200.0
    assert resolve_action_recovery({"kind": "skill", "行动恢复": 150}) == 150.0
    assert resolve_action_recovery(120) == 120.0
    assert resolve_action_recovery(None) == DEFAULT_ACTION_RECOVERY
    # 非法值（负数 / bool）→ 不采纳，回落默认
    assert resolve_action_recovery({"kind": "skill", "recovery": -5}) == (
        DEFAULT_ACTION_RECOVERY)
    assert resolve_action_recovery({"kind": "skill", "recovery": True}) == (
        DEFAULT_ACTION_RECOVERY)


def test_ctb_default_recovery_for_kind() -> None:
    """按种类取默认恢复值；未知种类 → 兜底默认。"""
    from qbot_rpg.core.ctb_config import default_recovery_for_kind

    for kind in ("basic", "SKILL", " item ", "guard", "flee"):
        assert default_recovery_for_kind(kind) == 100.0
    assert default_recovery_for_kind("unknown_kind") == 100.0
    assert default_recovery_for_kind(None) == 100.0


def test_ctb_build_recovery_table_and_config() -> None:
    """action.json 全量解析 → {id: recovery} 覆盖表；仅收录显式 recovery 条目。"""
    from qbot_rpg.core.ctb_config import build_recovery_table, resolve_recovery_config

    actions = [{"id": "claw_swipe", "recovery": 80}, {"id": "tail_sweep"}, 200]
    table = build_recovery_table(actions)
    assert table["claw_swipe"] == 80.0
    assert "tail_sweep" not in table                 # 无显式 recovery → 不固化
    assert build_recovery_table(None) == {}          # 空入参 → 空表
    cfg = resolve_recovery_config(None, actions)
    assert cfg.recovery_table["claw_swipe"] == 80.0
    # source 显式覆盖优先
    from qbot_rpg.core.ctb_rules import CtbRuleConfig

    src = CtbRuleConfig(recovery_table={"claw_swipe": 55.0})
    assert resolve_recovery_config(src, actions).recovery_table["claw_swipe"] == 55.0


def test_ctb_recovery_for_action_entry() -> None:
    """装配层 recovery_for_action = 引擎注入入口（按 action 取总恢复值）。"""
    from qbot_rpg.core.ctb_config import recovery_for_action
    from qbot_rpg.core.ctb_rules import CtbRuleConfig

    cfg = CtbRuleConfig(recovery_table={"claw_swipe": 200.0})
    assert recovery_for_action({"id": "claw_swipe"}, cfg) == 200.0
    # 未命中覆盖表 → 走 default_recovery，不抛错
    assert recovery_for_action({"id": "unknown", "kind": "basic"}, cfg) == 100.0
    assert recovery_for_action(None, cfg) == 100.0


def test_ctb_settings_section_defaults_and_override() -> None:
    """settings["ctb"] 段：默认启用 + 数值可覆盖（缺省对齐 ctb_rules）。"""
    from qbot_rpg.core.ctb_config import ctb_enabled, resolve_ctb_settings

    assert ctb_enabled(None) is True
    assert ctb_enabled({"ctb": {"enabled": False}}) is False
    default = resolve_ctb_settings(None)
    assert default["speed_reference"] == 100.0
    assert default["default_recovery"] == 100.0
    assert default["enabled"] is True
    overridden = resolve_ctb_settings({"ctb": {
        "default_recovery": 150, "recovery_table": {"claw_swipe": 80}}})
    assert overridden["default_recovery"] == 150.0
    assert overridden["recovery_table"] == {"claw_swipe": 80.0}
    # 非 Mapping 段（脏数据）→ 回落默认，不崩
    assert resolve_ctb_settings({"ctb": "oops"}) == default
    assert resolve_ctb_settings(object()) == default
