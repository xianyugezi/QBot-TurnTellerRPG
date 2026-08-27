"""战斗接线 + 消息合并单测（M5-08 · qbot_rpg/commands/battle_commands.py）。

依据：docs/m5_batch_plan.md M5-08（战斗接线 + 消息合并：引擎回合结果 → battle_render →
消息合并 → Sender 统一出口；前缀首行 M5-01 apply_message_prefix；无裸 send；验收：一轮
1 条/开始 1 条/结束 1 条）+ docs/m5_shared_contract.md §二/§五（铁律 2/7/9：一轮=1 条
（玩家行动+怪物反击合并）/ 战斗开始=1 条 / 战斗结束=1 条 / 单次操作 ≤1-2 条、发送走统一
出口 Sender、P2-8 不直接复用引擎 message）+ 细化_3d §3.1 承接表 + 细化_5e（军规1 前缀只加
首行 / 军规3 单回合单条 / 军规5 结算一次性：经验/掉落只在战斗结束消息输出一次）。

覆盖（M5-08 验收）：
  - 一轮 1 条（玩家行动+怪物反击合并；mock Sender 断言调用次数）
  - 战斗开始独立 1 条 / 战斗结束独立 1 条
  - 结束含汇总+掉落（BREP-20 掉落只在结束消息一次；BREP-24 汇总）
  - 前缀只加首行（M5-01 apply_message_prefix）
  - 无裸 send（所有战斗消息经统一出口；mock Sender.send 调用次数 = 合并消息数）
  - 战斗外指令不受影响（未进入战斗 → 1 条干净报错；非战斗指令路由/返回不受干扰）
  - /防御 /逃跑 /道具 管线 + 注册装配 + emoji 纪律

集成口径：驱动真实引擎 BattleEngine + 真实 Sender（注入记录回调），构造战斗 ctx
（M5-08 ctx 契约），断言消息合并/前缀/发送条数全链路。
"""

from __future__ import annotations

import unittest.mock
from types import SimpleNamespace

import pytest

import qbot_rpg.commands.battle_commands as bc
from qbot_rpg.core.message_format import battle_render as br
from qbot_rpg.commands.parsers import parse_command
from qbot_rpg.commands.prefix_wiring import (
    DEFAULT_MESSAGE_PREFIX_SETTINGS,
    apply_message_prefix,
)
from qbot_rpg.commands.router import (
    CommandSpec,
    ROUTE_COMMAND,
    Router,
    route_message,
)
from qbot_rpg.commands.sender import Sender
from qbot_rpg.core.battle import BattleEngine

# ---------------------------------------------------------------------------
# 确定性战斗双方（对齐 test_battle_engine.PLAYER/ENEMY 口径）
# ---------------------------------------------------------------------------

PLAYER = {"max_hp": 500, "hp": 500, "atk": 100, "dfn": 50, "mag": 50, "spd": 50,
          "foc": 100, "con": 50, "str": 100, "int": 80, "agi": 50, "spr": 50,
          "lck": 50, "elem_atk": 0, "name": "阿伟"}
ENEMY = {"max_hp": 400, "hp": 400, "atk": 80, "dfn": 40, "mag": 30, "spd": 40,
         "foc": 50, "con": 50, "str": 80, "int": 30, "agi": 40, "spr": 40,
         "lck": 10, "elem_atk": 0, "name": "史莱姆"}
# 一击必杀弱怪（结束流程：击杀+胜利+掉落 → 战斗结束汇总）
WEAK_ENEMY = dict(ENEMY, max_hp=30, hp=30, name="史莱姆")

LV, NAME, TITLE = 35, "阿伟", "斩龙者"
PREFIX = f"Lv{LV}.{NAME} -{TITLE}-"

# 3d §4.2 装饰性 emoji 禁用清单（TC-04 程序化扫描锚点；排版符号豁免 D-5B）
BANNED_EMOJI = "🔥🟢💥⚔️🛡️✨⭐🌟🎉🎊💎🏆❤️💖⚠️🚫📜🗡️🛒🧪⏰📅➡️🔹🔸▸"
_ALLOWED_SYMBOLS = set("✅❌｜→|/×（）「」【】·…、。—")


def _assert_no_banned_emoji(text: str) -> None:
    """TC-04/05：零装饰 emoji（仅 ✅/❌ 功能性标记 + 排版符号豁免 D-5B）。"""
    for ch in text:
        if ch in BANNED_EMOJI:
            raise AssertionError(f"战报出现禁用 emoji：{ch!r}（{text}）")
        if ch in _ALLOWED_SYMBOLS or ch.isascii():
            continue
        cp = ord(ch)
        if 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF:
            continue
        if 0x3000 <= cp <= 0x303F or 0xFF00 <= cp <= 0xFFEF:
            continue
        raise AssertionError(f"非法字符（疑似装饰 emoji）：{ch!r} in {text!r}")


# ---------------------------------------------------------------------------
# 夹具：记录型 Sender（注入 send_text 回调；calls = 实际发送段）+ 战斗 ctx
# ---------------------------------------------------------------------------

class RecordingSender(Sender):
    """记录型统一出口：send_text 回调收集实际发送段（cq_escape/分条/重试走真实路径）。"""

    def __init__(self) -> None:
        super().__init__(send_text=self._record)
        self.calls: list = []

    def _record(self, text: str, to=None) -> None:
        self.calls.append(text)


def make_ctx(sender: Sender, *, engine=None, **over) -> dict:
    """M5-08 战斗 ctx（模块头 ctx 契约；每场景新造避免互污染）。"""
    ctx = {
        "battle_engine": engine,
        "sender": sender,
        "to": "group1",
        "channel": "group",
        "level": LV,
        "name": NAME,
        "title": TITLE,
        "prefix_settings": DEFAULT_MESSAGE_PREFIX_SETTINGS,
        "skills": {"fireball": {"name": "火球术"}},
        "items": {"potion": {"name": "治疗药水", "actions": []}},
    }
    ctx.update(over)
    return ctx


def start_battle(player=PLAYER, enemy=ENEMY, seed: int = 42) -> BattleEngine:
    """真实引擎开战（确定性随机种子；每测试新造）。"""
    return BattleEngine().start(dict(player), dict(enemy), random_seed=seed)


# ---------------------------------------------------------------------------
# 一轮 1 条（玩家行动+怪物反击合并；mock Sender 断言调用次数）
# ---------------------------------------------------------------------------

def test_round_one_message_attack_merged() -> None:
    """/攻击 一轮 = 1 条：玩家行动 + 怪物反击合并进 render_battle_round 单条
    （军规3 / 铁律 2）；真实 Sender 仅 1 次调用。"""
    sender = RecordingSender()
    eng = start_battle()
    res = bc.cmd_battle_attack(parse_command("/攻击"), make_ctx(sender, engine=eng))
    assert res["ok"] is True
    assert len(res["sent"]) == 1
    assert len(sender.calls) == 1                     # 一轮 1 条
    text = sender.calls[0]
    _assert_no_banned_emoji(text)
    lines = text.split("\n")
    assert lines[0] == PREFIX                      # 前缀只加首行
    assert any("✅ 你攻击" in ln for ln in lines)   # 玩家行动行（BREP-02）
    assert any("史莱姆" in ln and "你受到" in ln for ln in lines) or \
        any("史莱姆的攻击" in ln for ln in lines)   # 怪物反击行（BREP-10/11）
    assert any("史莱姆 2" in ln for ln in lines) or any("→ /攻击" in ln for ln in lines)  # 提示行（BREP-09）


def test_round_one_message_mock_sender_call_count() -> None:
    """无裸 send：mock Sender 断言 send 调用次数 = 合并消息数（一轮 1 条）。"""
    mock = unittest.mock.Mock()
    mock.send.return_value = []                      # Mock.send 返回可迭代空列表（pipeline extend）
    eng = start_battle()
    pipeline = bc.BattlePipeline(mock, level=LV, name=NAME, title=TITLE, to="g1")
    report = eng.player_act("normal")
    delivered = bc.dispatch_round(eng, report, pipeline, make_ctx(mock, engine=eng))
    assert mock.send.call_count == 1                # 一轮恰 1 次 send
    assert len(delivered) == 0                      # mock 不产生真实段


def test_round_prefix_only_first_line() -> None:
    """前缀只加首行（铁律 1 / TC-01）：多行战报仅首行带前缀，其余行无前缀。"""
    sender = RecordingSender()
    eng = start_battle()
    bc.cmd_battle_attack(parse_command("/攻击"), make_ctx(sender, engine=eng))
    lines = sender.calls[0].split("\n")
    assert lines[0] == PREFIX
    for rest in lines[1:]:
        assert f"Lv{LV}" not in rest
        assert f"{NAME}" not in rest or rest.startswith("你 ")  # 正文行不重复前缀


def test_defend_round_one_message() -> None:
    """/防御 一轮 1 条：BREP-05 进入防御 + 怪物反击合并（×0.5 减伤由引擎）。"""
    sender = RecordingSender()
    eng = start_battle()
    res = bc.cmd_battle_defend(parse_command("/防御"), make_ctx(sender, engine=eng))
    assert res["ok"] is True
    assert len(sender.calls) == 1
    text = sender.calls[0]
    assert "✅ 你进入防御姿态" in text             # BREP-05
    assert "史莱姆" in text                         # 反击段合并
    assert text.split("\n")[0] == PREFIX


def test_item_round_one_message() -> None:
    """/道具 <物品> 一轮 1 条：道具使用行 + 怪物反击合并（工程补白 2，无 BREP 模板）。"""
    sender = RecordingSender()
    eng = start_battle()
    res = bc.cmd_battle_item(parse_command("/道具 治疗药水"), make_ctx(sender, engine=eng))
    assert res["ok"] is True
    assert len(sender.calls) == 1
    text = sender.calls[0]
    assert "✅ 你使用了治疗药水" in text
    assert "史莱姆" in text
    assert text.split("\n")[0] == PREFIX


# ---------------------------------------------------------------------------
# 战斗开始 1 条 / 战斗结束 1 条（含汇总+掉落）
# ---------------------------------------------------------------------------

def test_start_one_message_with_hint() -> None:
    """战斗开始独立 1 条（TC-24）：BREP-23 + 意图/弱点情报行；前缀首行。"""
    sender = RecordingSender()
    pipeline = bc.BattlePipeline(sender, level=LV, name=NAME, title=TITLE, to="g1")
    delivered = pipeline.send_start(SimpleNamespace(), SimpleNamespace(
        name="史莱姆", hp=25, max_hp=25), hint="弱点：火（×1.3）")
    assert len(delivered) == 1
    assert len(sender.calls) == 1
    lines = sender.calls[0].split("\n")
    assert lines == [PREFIX, "与史莱姆的战斗开始！史莱姆 25/25", "弱点：火（×1.3）"]
    _assert_no_banned_emoji(sender.calls[0])


def test_end_one_message_summary() -> None:
    """战斗结束独立 1 条（TC-25）：BREP-24 汇总含回合数与明细入口；前缀首行。"""
    sender = RecordingSender()
    pipeline = bc.BattlePipeline(sender, level=LV, name=NAME, title=TITLE, to="g1")
    delivered = pipeline.send_end(SimpleNamespace(), SimpleNamespace(name="史莱姆", turn=5), "win")
    assert len(delivered) == 1
    assert len(sender.calls) == 1
    assert sender.calls[0].split("\n") == [
        PREFIX,
        "战斗结束：胜利｜回合数 5｜输入 /战斗记录 查看明细",
    ]


def test_end_one_message_with_summary_block() -> None:
    """结束含汇总+明细块（BREP-24 + BREP-25）：summary 非 None → 木桩明细并入同一条。"""
    sender = RecordingSender()
    pipeline = bc.BattlePipeline(sender, level=LV, name=NAME, title=TITLE, to="g1")
    summary = {"total": 1220, "max_hit": 180, "crits": 4, "blocks": 2,
               "items": [("火球术", 520), ("普攻", 310)]}
    delivered = pipeline.send_end(
        SimpleNamespace(), SimpleNamespace(name="史莱姆", turn=5), "win", summary=summary,
    )
    assert len(sender.calls) == 1                     # 汇总+明细同一条
    text = sender.calls[0]
    assert "战斗结束：胜利｜回合数 5｜输入 /战斗记录 查看明细" in text
    assert "摘要：总伤害 1220" in text


def test_battle_end_flow_summary_and_drops() -> None:
    """/攻击 击杀弱怪：结束流程 ≤2 条——当轮消息（行动+击杀 BREP-15）+ 结束消息
    1 条（BREP-17 胜利 + BREP-20 掉落 + BREP-24 汇总，M5 裁决 P1-1 方案 A：同一消息
    含胜利+掉落+汇总，满足 5e TC-18）；掉落只在结束消息输出一次（军规5）。"""
    sender = RecordingSender()
    eng = start_battle(enemy=WEAK_ENEMY, seed=7)
    rewards = {"exp": 100, "gold": 50, "drops": [("史莱姆粘液", 2)]}
    res = bc.cmd_battle_attack(
        parse_command("/攻击"), make_ctx(sender, engine=eng, battle_rewards=rewards),
    )
    assert res["ok"] is True and res["message"] == "战斗结束（win）"
    assert len(sender.calls) == 2                     # 当轮 1 条 + 结束 1 条（≤2 条，铁律 2）
    round_msg, end_msg = sender.calls
    assert "✅ 你击败了史莱姆！" in round_msg          # BREP-15 击杀紧跟伤害行
    assert "✅ 战斗胜利！" not in round_msg
    assert "您对史莱姆造成了" in end_msg and "史莱姆已死亡。" in end_msg   # 叙事句（用户结算模板）
    assert "获得经验：100" in end_msg and "获得金币：50" in end_msg        # 经验/金币分行
    assert "1.史莱姆粘液×2" in end_msg                                     # 战利品列表
    assert "战斗结束：" not in end_msg               # win 无汇总行（用户模板，2026-08-27）
    assert end_msg.split("\n")[0] == PREFIX
    _assert_no_banned_emoji(round_msg)
    _assert_no_banned_emoji(end_msg)


# ---------------------------------------------------------------------------
# 逃跑 / 战斗外 / 前缀开关
# ---------------------------------------------------------------------------

def test_flee_two_messages() -> None:
    """/逃跑：逃跑结果 1 条 + 结束汇总 1 条（单次操作 ≤2 条；军规5 结算一次）。
    敌方 agi=0 → 敏捷比恒 1.0 必成功（数值层 L185 敏捷 = agi/(agi+敌agi)）。"""
    sender = RecordingSender()
    eng = start_battle(enemy=dict(ENEMY, agi=0))
    res = bc.cmd_battle_flee(parse_command("/逃跑"), make_ctx(sender, engine=eng))
    assert res["ok"] is True
    assert len(sender.calls) == 2
    assert "✅ 逃跑成功，脱离战斗" in sender.calls[0]
    assert "战斗结束：逃跑｜回合数 1｜输入 /战斗记录 查看明细" in sender.calls[1]


def test_flee_failed_one_message_merged() -> None:
    """/逃跑 失败：1 条合并（逃跑结果 + 怪物反击，铁律 2/军规3），战斗未结束。
    敌方高敏 → 敏捷比 < 1（数值层 L185 敏捷 = agi/(agi+敌agi)）。"""
    sender = RecordingSender()
    eng = start_battle(enemy=dict(ENEMY, agi=500))
    res = bc.cmd_battle_flee(parse_command("/逃跑"), make_ctx(sender, engine=eng))
    assert res["ok"] is True
    assert len(sender.calls) == 1
    assert "❌ 逃跑失败，战斗继续" in sender.calls[0]
    assert "史莱姆" in sender.calls[0]                    # 怪物反击合并进同一条
    assert sender.calls[0].split("\n")[0] == PREFIX


def test_no_battle_clean_error_not_affect_others() -> None:
    """战斗外指令不受影响：未进入战斗（engine=None）→ 1 条干净报错（铁律 2 单次 ≤1-2 条），
    不触碰引擎/其他指令；同一 Sender 只收到这 1 条。"""
    sender = RecordingSender()
    ctx = make_ctx(sender, engine=None)
    res = bc.cmd_battle_attack(parse_command("/攻击"), ctx)
    assert res["ok"] is False
    assert res["message"] == bc.TPL_NO_BATTLE
    assert len(sender.calls) == 1
    assert "❌ 当前没有进行中的战斗" in sender.calls[0]   # 玩家指令回复同样带前缀首行（铁律 1）
    # 非战斗指令（/角色）不受影响：注册战斗指令后路由仍命中，战斗 handler 未介入
    router = Router()
    bc.register_battle_commands(router, make_context=lambda parsed: ctx)
    router.register(CommandSpec("角色", handler=lambda p: "面板"))
    r = route_message("/角色", {"registry": router, "shortcuts": {}, "aliases": None,
                                "dialog_active": False, "battle_active": False,
                                "command_mode": "global_shortcut", "require_at": False})
    assert r.kind == ROUTE_COMMAND and r.command == "角色"
    assert len(sender.calls) == 1                     # 非战斗指令不产生战斗消息


def test_prefix_disabled_no_prefix() -> None:
    """enabled=false（M5-01 总开关）→ 战斗消息无前缀（【前缀】L42）。"""
    sender = RecordingSender()
    settings = dict(DEFAULT_MESSAGE_PREFIX_SETTINGS, enabled=False)
    eng = start_battle()
    bc.cmd_battle_attack(parse_command("/攻击"), make_ctx(sender, engine=eng,
                                                          prefix_settings=settings))
    assert sender.calls[0].split("\n")[0].startswith("✅ 你攻击")   # 无前缀首行


def test_register_battle_commands_routes_four() -> None:
    """register_battle_commands：/攻击 /防御 /逃跑 /道具 四条注册进 Router 且可路由命中。"""
    router = Router()
    bc.register_battle_commands(router, make_context=lambda parsed: {"sender": RecordingSender()})
    for cmd in ("攻击", "防御", "逃跑", "道具"):
        assert router.has(cmd)
        r = route_message(f"/{cmd}", {"registry": router, "shortcuts": {}, "aliases": None,
                                      "dialog_active": False, "battle_active": True,
                                      "command_mode": "combat_shortcut", "require_at": False})
        assert r.kind == ROUTE_COMMAND and r.command == cmd


# ---------------------------------------------------------------------------
# 渲染接线细节：展示名注入 / 状态差分行
# ---------------------------------------------------------------------------

def test_enrich_injects_display_names() -> None:
    """enrich_round_report 注入展示字段（M5-08 接线层）：玩家 outcome.target=怪物展示名、
    怪物 outcome.attacker_name=怪物展示名、最大 HP 注入（BREP-02/10 取数）。"""
    eng = start_battle()
    report = eng.player_act("normal")
    enriched = bc.enrich_round_report(
        report, enemy_name="史莱姆", player_max_hp=500, enemy_max_hp=400,
    )
    for oc in enriched.outcomes:
        if getattr(oc, "actor", "") == "player":
            assert getattr(oc, "target", "") == "史莱姆"          # 原为战斗侧 "enemy"
            assert getattr(oc, "target_max_hp", None) == 400
        elif getattr(oc, "actor", "") == "enemy":
            assert getattr(oc, "attacker_name", "") == "史莱姆"
            assert getattr(oc, "player_max_hp", None) == 500
    # 原样透传：非玩家/怪物 outcome 不注入
    assert getattr(enriched, "enemy_name", "") == "史莱姆"


def test_apply_battle_prefix_delegates_m5_01() -> None:
    """apply_battle_prefix = M5-01 apply_message_prefix 委托（铁律 1 前缀只加首行）。"""
    body = "✅ 你攻击，造成 10 伤害（史莱姆 390/400）\n你 500/500 | 史莱姆 390/400 → /攻击"
    res = apply_message_prefix(body, level=LV, name=NAME, title=TITLE,
                               settings=DEFAULT_MESSAGE_PREFIX_SETTINGS)
    assert res.text == f"{PREFIX}\n{body}"
    assert res.truncated is False and res.hint == ""


def test_battle_rewards_from_fn_and_ctx() -> None:
    """奖励/掉落解析（工程补白 3）：battle_reward_fn 注入优先；battle_rewards 直给兜底。"""
    eng = start_battle(enemy=WEAK_ENEMY)
    report = eng.player_act("normal")
    calls = []
    def reward_fn(engine, rep, ctx):
        calls.append(rep.turn)
        return {"exp": 10, "gold": 5, "drops": [("素材", 1)]}
    r1 = bc._battle_rewards(make_ctx(RecordingSender(), engine=eng, battle_reward_fn=reward_fn), eng, report)
    assert r1 == {"exp": 10, "gold": 5, "drops": (("素材", 1),)} and calls == [1]
    r2 = bc._battle_rewards(make_ctx(RecordingSender(), engine=eng, battle_rewards={"exp": 3, "gold": 2}), eng, report)
    assert r2 == {"exp": 3, "gold": 2, "drops": ()}
    r3 = bc._battle_rewards(make_ctx(RecordingSender(), engine=eng), eng, report)
    assert r3 == {"exp": 0, "gold": 0, "drops": ()}


# ---------------------------------------------------------------------------
# P1-3 连段段行生产可达（_build_segments + 注入 + render 段行）
# ---------------------------------------------------------------------------

def test_combo_segments_injection_renders_seg_lines() -> None:
    """P1-3：snap action_record >1 段 → 注入 segments → 战报含「第 N 段」段行。

    段号 = 收集器累计 index（action_record 位置，5e §5.1）；单段不注入（走聚合 BREP-02）。
    """
    snap = {
        "action_record": [
            {"turn": 1, "actor": "player", "action": "连斩", "target": "enemy",
             "rating": {"crit": "low", "blocked": False}, "damage": {"final": 5}},
            {"turn": 2, "actor": "player", "action": "连斩", "target": "enemy",
             "rating": {"crit": "mid", "blocked": False}, "damage": {"final": 6}},
            {"turn": 2, "actor": "player", "action": "连斩", "target": "enemy",
             "rating": {"crit": "low", "blocked": False}, "damage": {"final": 7}},
        ],
    }
    segs = bc._build_segments(snap, turn=2)
    assert len(segs) == 2                       # 本轮玩家两段 → 注入
    assert segs[0]["seg"] == 2 and segs[1]["seg"] == 3   # 收集器累计段号
    assert bc._build_segments(snap, turn=1) == []        # 单段 → 不注入

    report = SimpleNamespace(
        turn=2, phases=(), player=30, enemy=25, ended=False, status=None, log=(),
        outcomes=(SimpleNamespace(
            ok=True, seq=1, actor="player", action_type="连斩", target="enemy",
            hit=True, crit="low", blocked=False, raw_damage=12, final_damage=12,
            target_hp=18, side_effects=(), message="", battle_ended=False, status=None,
        ),),
    )
    enriched = bc.enrich_round_report(
        report, enemy_name="史莱姆", player_max_hp=30, enemy_max_hp=40, segments=segs,
    )
    text = br.render_battle_round(enriched)
    assert "第 2 段：连斩 造成 6 伤害" in text
    assert "第 3 段：连斩 造成 7 伤害" in text
    assert "（史莱姆 18/40）" in text          # target_hp 聚合末值近似 + 展示名
    assert "（会心·中阶 ×1.7）" in text       # 段内会心附注（第 2 段 crit=mid）
