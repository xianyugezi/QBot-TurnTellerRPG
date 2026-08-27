"""玩家行动基础模板渲染单测（M5-03 · qbot_rpg/core/message_format/battle_render.py）。

依据：docs/m5_shared_contract.md §5.1/§5.2（IF30/31/32 签名、BREP 模板、ActionOutcome
真实字段：伤害取 final_damage、目标 HP 取 target_hp，不直接复用引擎 message）
     + docs/m5_batch_plan.md M5-03 + 细化_5e §1.4/§2.1/§2.2（BREP-01~06 + TC-07~10）。

覆盖：TC-07 命中逐字（HP 后缀保留）/ TC-08 未命中逐字 / TC-09 会心三档·格挡分支 /
TC-10 防御两行（BREP-05 + BREP-06）/ render_battle_round 拼接（先手行 + 前缀首行钩子
+ 并行路钩子优雅跳过）/ emoji 纪律（仅 ✅/❌ + 排版符号，零装饰 emoji）。

说明：展示名（action_name / 怪物名）与最大 HP 非 ActionOutcome 字段（shared_contract
§5.1 字段清单无），由接线层（M5-08）注入 —— 直接模板断言经参数传入；render_battle_round
集成断言用真实 ActionOutcome 字段 + 接线层形态包装（真实字段经 oc.__dict__ 承载，
展示信息以可省略属性补充）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict

from qbot_rpg.core.battle import ActionOutcome, TurnReport
from qbot_rpg.core.message_format.battle_render import (
    _render_crit_block_note,
    _render_player_defend,
    _render_player_defend_hit,
    _render_player_hit,
    _render_player_miss,
    render_battle_round,
)

# 3d §4.2 装饰性 emoji 禁用清单（TC-04 程序化扫描锚点；排版符号豁免 D-5B）
BANNED_EMOJI = "🔥🟢💥⚔️🛡️✨⭐🌟🎉🎊💎🏆❤️💖⚠️🚫📜🗡️🛒🧪⏰📅➡️🔹🔸▸"
ALLOWED_MARKERS = "✅❌"


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
    return ActionOutcome(**defaults)


def _report(*outcomes: Any, **kw: Any) -> TurnReport:
    """构造 TurnReport（真实字段；player/enemy 为 HP 快照，outcomes 流水）。"""
    defaults: Dict[str, Any] = {
        "turn": 1, "phases": ("player_action", "enemy_action"),
        "player": 21, "enemy": 7, "ended": False, "status": None,
        "log": (), "outcomes": tuple(outcomes),
    }
    defaults.update(kw)
    return TurnReport(**defaults)


def _enriched(oc: ActionOutcome, **extra: Any) -> SimpleNamespace:
    """接线层形态 outcome：真实字段（ActionOutcome 全部字段经 __dict__ 承载）
    + 展示信息（action_name/target_max_hp 等，ActionOutcome 不承载，M5-08 注入）。"""
    return SimpleNamespace(**{**oc.__dict__, **extra})


def _assert_no_banned_emoji(text: str) -> None:
    """TC-04/05：零装饰 emoji（仅 ✅/❌ 功能性标记 + 排版符号豁免 D-5B）。"""
    for ch in text:
        assert ch not in BANNED_EMOJI, f"战报出现禁用 emoji：{ch!r}（{text}）"


# ---------------------------------------------------------------------------
# TC-07 玩家-攻击命中（BREP-02）
# ---------------------------------------------------------------------------

def test_tc07_player_hit_exact() -> None:
    """TC-07：命中逐字 `✅ 你施放火球术，造成 18 伤害（史莱姆 7/25）`；HP 后缀保留。"""
    oc = _outcome(action_type="skill", raw_damage=18, final_damage=18, target_hp=7)
    line = _render_player_hit(oc, action_phrase="施放火球术", target_max_hp=25)
    assert line == "✅ 你施放火球术，造成 18 伤害（史莱姆 7/25）"
    assert "（史莱姆 7/25）" in line                 # HP 后缀必须保留（P0-2 锚点）
    assert oc.message not in line                    # 不直接复用引擎 message（5e P2-8）


def test_tc07_hit_with_target_phrase() -> None:
    """5e §2.1 示例：动作短语含目标 → `✅ 你挥动铁剑攻击史莱姆，造成 12 伤害（史莱姆 18/25）`。"""
    oc = _outcome(raw_damage=12, final_damage=12, target_hp=18)
    line = _render_player_hit(oc, action_phrase="挥动铁剑攻击史莱姆", target_max_hp=25)
    assert line == "✅ 你挥动铁剑攻击史莱姆，造成 12 伤害（史莱姆 18/25）"


# ---------------------------------------------------------------------------
# TC-08 玩家-未命中（BREP-03）
# ---------------------------------------------------------------------------

def test_tc08_player_miss_exact() -> None:
    """TC-08：未命中逐字 `❌ 未命中：史莱姆 闪过了你的攻击（史莱姆 25/25）`；不扣血。"""
    oc = _outcome(hit=False, crit="low", blocked=False, raw_damage=0, final_damage=0, target_hp=25)
    line = _render_player_miss(oc, action_phrase="攻击", target_max_hp=25)
    assert line == "❌ 未命中：史莱姆 闪过了你的攻击（史莱姆 25/25）"


# ---------------------------------------------------------------------------
# TC-09 玩家-会心/格挡附注（BREP-04）
# ---------------------------------------------------------------------------

def test_tc09_crit_high_and_mid_default_on() -> None:
    """TC-09：会心 high/mid 默认输出 `（会心·高阶 ×2.2）`/`（会心·中阶 ×1.7）`。"""
    expect = {"high": "（会心·高阶 ×2.2）", "mid": "（会心·中阶 ×1.7）"}
    for crit, note in expect.items():
        oc = _outcome(crit=crit, blocked=False, final_damage=27, target_hp=1)
        line = _render_player_hit(oc, action_phrase="施放火球术攻击史莱姆", target_max_hp=25)
        assert note in line
        assert "（被格挡，伤害减半）" not in line


def test_tc09_crit_note_position_before_hp_suffix() -> None:
    """5e §2.1 示例 L150：会心附注拼在伤害值与 HP 后缀之间。"""
    oc = _outcome(crit="high", blocked=False, final_damage=27, target_hp=1)
    line = _render_player_hit(oc, action_phrase="施放火球术攻击史莱姆", target_max_hp=25)
    assert line == "✅ 你施放火球术攻击史莱姆，造成 27 伤害（会心·高阶 ×2.2）（史莱姆 1/25）"


def test_tc09_crit_low_renders_when_include_low() -> None:
    """TC-09：低级会心默认省略（D-5D 防噪声），include_low=True 输出 `（会心·低阶 ×1.3）`。"""
    oc = _outcome(crit="low", blocked=False, final_damage=18, target_hp=7)
    assert _render_crit_block_note(oc) == ""                       # 默认省略
    assert _render_crit_block_note(oc, include_low=True) == "（会心·低阶 ×1.3）"
    line = _render_player_hit(oc, action_phrase="施放火球术", target_max_hp=25, include_low=True)
    assert "（会心·低阶 ×1.3）" in line


def test_tc09_blocked_note() -> None:
    """TC-09：被格挡 → `（被格挡，伤害减半）`；会心+格挡并存都输出（判定顺序先会后挡）。"""
    oc = _outcome(crit="high", blocked=True, final_damage=9, target_hp=16)
    line = _render_player_hit(oc, action_phrase="挥动铁剑攻击史莱姆", target_max_hp=25)
    assert "（会心·高阶 ×2.2）" in line and "（被格挡，伤害减半）" in line


def test_tc09_no_note_when_plain() -> None:
    """无会心（crit 非三档）且未格挡 → 无附注。"""
    oc = _outcome(crit="", blocked=False, target_hp=7)
    assert _render_crit_block_note(oc) == ""


# ---------------------------------------------------------------------------
# TC-10 玩家-防御（BREP-05 / BREP-06）
# ---------------------------------------------------------------------------

def test_tc10_defend_enter_exact() -> None:
    """TC-10：`✅ 你进入防御姿态（本回合受到伤害减半）`（BREP-05）。"""
    oc = _outcome(action_type="guard", hit=True, raw_damage=0, final_damage=0, target_hp=7)
    assert _render_player_defend(oc) == "✅ 你进入防御姿态（本回合受到伤害减半）"


def test_tc10_defend_hit_exact() -> None:
    """TC-10：防御受击逐字 `✅ 你防御了史莱姆的撞击，受到 2 伤害（HP 19/30）`（BREP-06）。"""
    oc = _outcome(actor="enemy", action_type="normal", target="player",
                  raw_damage=4, final_damage=2, target_hp=19)   # ×0.5 生效后 2 伤
    line = _render_player_defend_hit(oc, attacker_name="史莱姆", action_phrase="撞击",
                                     player_max_hp=30)
    assert line == "✅ 你防御了史莱姆的撞击，受到 2 伤害（HP 19/30）"


# ---------------------------------------------------------------------------
# render_battle_round 拼接（先手行→击杀→后手行→结算，铁律 9）
# ---------------------------------------------------------------------------

def test_render_round_player_action_first() -> None:
    """render_battle_round：接线层形态 outcome（真实字段+展示名/最大 HP）→ 先手行输出。"""
    oc = _enriched(_outcome(action_type="skill"), action_name="施放火球术", target_max_hp=25)
    text = render_battle_round(_report(oc))
    assert text == "✅ 你施放火球术，造成 18 伤害（史莱姆 7/25）"


def test_render_round_default_phrase_normal_attack() -> None:
    """render_battle_round：真实 ActionOutcome（普攻，无展示名）→ 缺省动作短语「攻击」。"""
    text = render_battle_round(_report(_outcome()))
    assert text == "✅ 你攻击，造成 18 伤害（史莱姆 7/7）"   # 最大 HP 未接 → 回落当前 HP


def test_render_round_prefix_first_line_when_info() -> None:
    """BREP-01：round_result 携带玩家信息（接线层 M5-08 形态）→ 前缀为首行、仅首行。"""
    oc = _enriched(_outcome(action_type="skill"), action_name="施放火球术", target_max_hp=25)
    tr = _report(oc)
    ctx = SimpleNamespace(**tr.__dict__, level=35, name="阿伟", title="斩龙者")
    lines = render_battle_round(ctx).split("\n")
    assert lines[0] == "Lv35.阿伟 -斩龙者-"
    assert lines[1] == "✅ 你施放火球术，造成 18 伤害（史莱姆 7/25）"
    assert not any("Lv35" in ln for ln in lines[1:])   # 前缀仅首行（【前缀】L34/L82）


def test_render_round_miss_via_round() -> None:
    """render_battle_round：未命中走 BREP-03；并行路钩子（M5-05/06）未落地优雅跳过。"""
    oc = _outcome(hit=False, raw_damage=0, final_damage=0, target_hp=25)
    text = render_battle_round(_report(oc))
    assert text == "❌ 未命中：史莱姆 闪过了你的攻击（史莱姆 25/25）"


def test_render_round_hint_when_max_known() -> None:
    """BREP-09（M5-04 render_action_hint）：round_result 携带最大 HP/目标名 → 末行提示行。"""
    oc = _enriched(_outcome(action_type="skill"), action_name="施放火球术", target_max_hp=25)
    tr = _report(oc, player=21, enemy=7)
    ctx = SimpleNamespace(**tr.__dict__, player_max_hp=30, enemy_max_hp=25,
                          enemy_name="史莱姆", level=35, name="阿伟", title="斩龙者")
    lines = render_battle_round(ctx).split("\n")
    assert lines[-1] == "你 21/30 | 史莱姆 7/25 → /攻击[技能] /道具 /防御 /逃跑"


# ---------------------------------------------------------------------------
# emoji 纪律（TC-04/05：仅 ✅/❌ + 排版符号，零装饰 emoji）
# ---------------------------------------------------------------------------

def test_no_banned_emoji_in_all_templates() -> None:
    """本路全部模板输出零装饰 emoji；行首功能性标记仅 ✅/❌（D-01）。"""
    samples = [
        _render_player_hit(_outcome(crit="high"), action_phrase="施放火球术", target_max_hp=25),
        _render_player_miss(_outcome(hit=False, target_hp=25), action_phrase="攻击"),
        _render_player_defend(_outcome(action_type="guard")),
        _render_player_defend_hit(_outcome(target_hp=19), attacker_name="史莱姆",
                                  action_phrase="撞击", player_max_hp=30),
        render_battle_round(_report(_outcome())),
    ]
    for text in samples:
        _assert_no_banned_emoji(text)
        assert text[0] in ALLOWED_MARKERS   # 行首功能性标记 ✅/❌
