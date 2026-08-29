"""继承指令壳单测（M8 批5 · qbot_rpg/commands/alchemy_commands.py 的 /继承 + /继承超）。

文件：tests/unit/test_inherit_commands.py
创建：2026-08-29
作者：Hermes 子agent-5A-1
功能：cmd_inherit（/继承 列表）+ cmd_inherit_super（/继承超 单金色）异步直测——
  真实引擎消费：AlchemyCore（开会话/投料）+ TraitInherit + async fake session_mgr。
  覆盖矩阵（每条正例 + 负例，断言精确文本/数值/快照字段；asyncio_mode=auto 直接 await）：
    /继承：无会话拒绝 / 战斗中拦截 / 非调合会话拒绝 / 缺参 TPL-12 /
      成功渲染（已继承+特性位+PP+快照落库）/ PP 不足 / 互斥组拒绝（组名）/ 未选候选清单拒绝 /
      见习无继承位拒绝
    /继承超：成功（第 4 位金色）/ 宗师拒绝 / 多项拒绝
    装配：register_alchemy_commands 注册 继承/继承超

依据：docs/m8_contract_指令契约.md §4 /继承 /继承超（GU-13~16/F-04/M-04）+
  docs/细化/细化_2c4e_品质与特性.md（INH-01/06/09/10/14 + TSC-11~13/TC-12~24）。
测试风格对齐 tests/unit/test_alchemy_commands.py（parse_command 直调 + 全字段 ctx +
  FakeSessions async fake）。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from qbot_rpg.commands.alchemy_commands import (
    INHERIT_CMD,
    INHERIT_SUPER_CMD,
    cmd_alchemy,
    cmd_feed,
    cmd_inherit,
    cmd_inherit_super,
    register_alchemy_commands,
)
from qbot_rpg.commands.parsers import parse_command
from qbot_rpg.commands.router import Router
from qbot_rpg.world.session import SessionConflictError

# ---------------------------------------------------------------------------
# 夹具：items/traits/recipe 注册表 + settings（对齐 content/test_demo 形态）
# ---------------------------------------------------------------------------

ITEMS: Dict[str, dict] = {
    "fire_crystal": {"id": "fire_crystal", "name": "火晶石", "type": "material",
                     "elements": {"fire": 4}, "traits": ["trait_burn_boost"]},
    "fire_ore": {"id": "fire_ore", "name": "火矿石", "type": "material",
                 "elements": {"fire": 1}, "traits": ["trait_burn_snap"]},
    "venom_sac": {"id": "venom_sac", "name": "毒囊", "type": "material",
                  "elements": {"wind": 1}, "traits": ["trait_poison_boost"]},
    "heal_herb": {"id": "heal_herb", "name": "回复草药", "type": "material",
                  "elements": {"water": 1}, "traits": ["trait_heal_boost"]},
    "gold_ember": {"id": "gold_ember", "name": "金色余烬", "type": "material",
                   "elements": {"fire": 2}, "traits": ["trait_fire_15"]},
    "mana_potion": {"id": "mana_potion", "name": "魔力药水", "type": "consumable"},
    "flame_bomb": {"id": "flame_bomb", "name": "火焰弹", "type": "consumable"},
}

TRAITS: Dict[str, dict] = {
    "trait_burn_boost": {"id": "trait_burn_boost", "name": "灼烧强化", "rarity": "normal",
                         "group": "fire_boost", "repeatable": False, "source": "素材"},
    "trait_burn_snap": {"id": "trait_burn_snap", "name": "灼烧爆燃", "rarity": "normal",
                        "group": "fire_boost", "repeatable": False, "source": "素材"},
    "trait_poison_boost": {"id": "trait_poison_boost", "name": "剧毒强化", "rarity": "normal",
                           "group": "venom_boost", "repeatable": False, "source": "素材"},
    "trait_heal_boost": {"id": "trait_heal_boost", "name": "回复强化", "rarity": "normal",
                         "group": "", "repeatable": True, "source": "成品"},
    "trait_fire_15": {"id": "trait_fire_15", "name": "灼烧强化·精", "rarity": "super",
                      "group": "fire_boost", "repeatable": False, "source": "金色素材"},
}

RECIPES: Dict[str, dict] = {
    "rcp_flame": {"id": "rcp_flame", "name": "火焰弹", "level": 5, "slots": 5,
                  "pp_budget": 5, "traits_inherit": 2,
                  "materials": [{"id": "fire_crystal", "count": 1}],
                  "element_req": {"fire": [{"threshold": 6, "effect": "范围爆炸"}]},
                  "cost": {"coins": 100, "gem": 0},
                  "output": {"item": "flame_bomb", "count": 1}},
    "rcp_low": {"id": "rcp_low", "name": "低耗药水", "level": 1, "slots": 5,
                "pp_budget": 1, "traits_inherit": 2,
                "materials": [{"id": "fire_crystal", "count": 1}],
                "cost": {"coins": 10, "gem": 0},
                "output": {"item": "mana_potion", "count": 1}},
}

SETTINGS: Dict[str, Any] = {
    "currencies": [{"id": "coins", "name": "金币"}, {"id": "gem", "name": "宝石"}],
    "alchemy": {
        "mode": "full",
        "energy_enabled": False,          # R-08 默认关
        "catalyst_unlock_tier": "expert",  # R-07 专家解锁
        "max_qty": 2147483647,            # 拍板⑤
        "quality_tiers": {"common": [0, 39], "uncommon": [40, 59],
                          "rare": [60, 79], "legendary": [80, 100]},
        "quality_coef": {"common": 0.8, "uncommon": 1.0, "rare": 1.2, "legendary": 1.5},
        "chain_map": {"1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6},
        "pp_cost": {"normal": 1, "super": 2},
        "gold_slot_exclusive": True,
        "job_tier_map": {
            "见习": [1, 5], "正式": [6, 15], "精通": [16, 25], "专家": [26, 35],
            "大师": [36, 45], "宗师": [46, 60], "王": [61, 99],
        },
    },
}


def _alchemy_node(level: int = 3) -> dict:
    """炼金职业节点（level = 档位索引 0~6；unlocks.trait_slot_1 = SP 特性位+1 次数）。"""
    return {"level": level, "exp": 0, "sp_earned": 0, "sp_used": 0,
            "unlocks": {"trait_slot_1": 0}}


class FakeSessions:
    """async 会话 fake：内存 dict 模拟 get_active/acquire/suspend/release（对齐
    test_alchemy_commands.FakeSessions）。"""

    def __init__(self) -> None:
        self.store: Dict[str, dict] = {}
        self.calls: list = []
        self.conflict_on_acquire: bool = False

    async def get_active(self, qid: str) -> Optional[dict]:
        self.calls.append(("get_active", qid))
        return self.store.get(qid)

    async def acquire(self, qid: str, session_type: str, payload: Any = None) -> dict:
        self.calls.append(("acquire", qid, session_type))
        if self.conflict_on_acquire or qid in self.store:
            raise SessionConflictError(f"玩家 {qid} 已有活跃会话，拒绝新建")
        self.store[qid] = {"session_type": session_type, "payload": payload, "version": 1}
        return self.store[qid]

    async def suspend(self, qid: str, snapshot: Any) -> None:
        self.calls.append(("suspend", qid))
        cur = self.store.get(qid, {})
        self.store[qid] = {
            "session_type": cur.get("session_type", "alchemy"),
            "payload": snapshot,
            "version": int(cur.get("version", 1)) + 1,
        }

    async def release(self, qid: str) -> None:
        self.calls.append(("release", qid))
        self.store.pop(qid, None)


def make_ctx(**over: Any) -> dict:
    """全字段炼金 ctx（player 字段在 ctx 顶层——_player_of 兜底口径，对齐 test_alchemy）。"""
    base: dict = {
        "qid": "u1",
        "proficiency": {"alchemy": _alchemy_node(3)},
        "currencies": {"coins": 1000, "gem": 0},
        "inventory": {"fire_crystal": 20, "fire_ore": 10, "venom_sac": 10,
                      "heal_herb": 10, "gold_ember": 5, "mana_potion": 5},
        "items": ITEMS,
        "traits": TRAITS,
        "recipe": RECIPES,
        "settings": SETTINGS,
        "session_mgr": FakeSessions(),
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# /继承：GU-13 无会话 / GU-10 战斗拦截 / 非调合会话
# ---------------------------------------------------------------------------
async def test_inherit_no_session_rejected() -> None:
    """GU-13 负例：无会话发 /继承 → 「当前没有调合会话，先 /炼金 <配方> 开始」（L175）。"""
    ctx = make_ctx()
    out = await cmd_inherit(parse_command("/继承 灼烧强化"), ctx)
    assert "当前没有调合会话，先 /炼金 <配方> 开始" in out


async def test_inherit_battle_intercept() -> None:
    """GU-10/MUT-04 负例：战斗中发 /继承 → 「战斗中使用 /即时调合 <配方>」（L295）。"""
    ctx = make_ctx(in_battle=True)
    ctx["session_mgr"].store["u1"] = {"session_type": "battle", "payload": {}, "version": 1}
    out = await cmd_inherit(parse_command("/继承 灼烧强化"), ctx)
    assert "战斗中使用 /即时调合 <配方>" in out


async def test_inherit_non_alchemy_session_rejected() -> None:
    """GU-13 负例：活跃会话非调合类（battle，非战斗场景）→ 无会话模板（P-6 防御）。"""
    ctx = make_ctx()
    ctx["session_mgr"].store["u1"] = {"session_type": "battle", "payload": {}, "version": 1}
    out = await cmd_inherit(parse_command("/继承 灼烧强化"), ctx)
    assert "当前没有调合会话，先 /炼金 <配方> 开始" in out


async def test_inherit_missing_arg_tpl12() -> None:
    """负例：/继承 缺参 → TPL-12（指令不正确）。"""
    ctx = make_ctx()
    out = await cmd_inherit(parse_command("/继承"), ctx)
    assert "指令不正确" in out


# ---------------------------------------------------------------------------
# /继承：F-04 成功渲染（M-04）
# ---------------------------------------------------------------------------
async def test_inherit_ok_render_and_snapshot() -> None:
    """F-04/M-04 正例：开会话+投料 火晶石 → /继承 灼烧强化 → 成功消息含 已继承/特性位/PP；
    快照落库（traits + pp + version 递增）。"""
    ctx = make_ctx()
    await cmd_alchemy(parse_command("/炼金 火焰弹"), ctx)
    await cmd_feed(parse_command("/投料 火晶石"), ctx)
    out = await cmd_inherit(parse_command("/继承 灼烧强化"), ctx)
    assert "已继承：灼烧强化" in out
    assert "特性位 1 普通" in out
    assert "PP 1/5" in out
    snap = ctx["session_mgr"].store["u1"]["payload"]
    assert snap["traits"] == ["trait_burn_boost"]
    assert snap["pp"]["used"] == 1
    # acquire1 → feed2 → inherit3（§7.1 行4：状态更新 version 递增）
    assert ctx["session_mgr"].store["u1"]["version"] == 3


async def test_inherit_two_traits_ok_pp2() -> None:
    """F-04 正例：/继承 灼烧强化,剧毒强化（2 项入席 PP 扣 2，指令契约 TC-09）。"""
    ctx = make_ctx()
    await cmd_alchemy(parse_command("/炼金 火焰弹"), ctx)
    await cmd_feed(parse_command("/投料 火晶石,毒囊"), ctx)
    out = await cmd_inherit(parse_command("/继承 灼烧强化,剧毒强化"), ctx)
    assert "已继承：灼烧强化 剧毒强化" in out
    assert "特性位 2 普通" in out
    assert "PP 2/5" in out
    snap = ctx["session_mgr"].store["u1"]["payload"]
    assert snap["traits"] == ["trait_burn_boost", "trait_poison_boost"]
    assert snap["pp"]["used"] == 2


# ---------------------------------------------------------------------------
# /继承：GU-14 PP 不足 / GU-15 位余量 / GU-16 互斥 + repeatable / INH-01 候选清单
# ---------------------------------------------------------------------------
async def test_inherit_pp_insufficient() -> None:
    """GU-14/INH-09 负例：pp_budget=1 配方选 2 特性 → 「PP 不足」。"""
    ctx = make_ctx()
    await cmd_alchemy(parse_command("/炼金 低耗药水"), ctx)
    await cmd_feed(parse_command("/投料 火晶石,毒囊"), ctx)
    out = await cmd_inherit(parse_command("/继承 灼烧强化,剧毒强化"), ctx)
    assert "PP 不足" in out
    snap = ctx["session_mgr"].store["u1"]["payload"]
    assert snap.get("traits") in (None, [])  # 原子拒绝零副作用


async def test_inherit_slot_overflow_with_recipe_cap() -> None:
    """GU-15/INH-06 负例：配方 traits_inherit=2（专家位 3 被配方声明钳到 2）→
    第 3 项 → 「继承超 2 项」。"""
    ctx = make_ctx()
    await cmd_alchemy(parse_command("/炼金 火焰弹"), ctx)  # traits_inherit=2
    await cmd_feed(parse_command("/投料 火晶石,毒囊,回复草药"), ctx)
    out = await cmd_inherit(parse_command("/继承 灼烧强化,剧毒强化,回复强化"), ctx)
    assert "继承超 2 项" in out
    assert ctx["session_mgr"].store["u1"]["payload"].get("traits") in (None, [])


async def test_inherit_group_conflict() -> None:
    """GU-16/INH-10 负例：同 group（fire_boost）两项 → 「互斥组内最多 1 项：fire_boost」。"""
    ctx = make_ctx()
    await cmd_alchemy(parse_command("/炼金 火焰弹"), ctx)
    await cmd_feed(parse_command("/投料 火晶石,火矿石"), ctx)
    out = await cmd_inherit(parse_command("/继承 灼烧强化,灼烧爆燃"), ctx)
    assert "互斥组内最多 1 项" in out and "fire_boost" in out


async def test_inherit_trait_not_in_candidate_pool() -> None:
    """INH-01 负例：未投料（候选清单外）特性 → 「特性须来自投料候选清单」。"""
    ctx = make_ctx()
    await cmd_alchemy(parse_command("/炼金 火焰弹"), ctx)
    await cmd_feed(parse_command("/投料 火晶石"), ctx)  # 池内仅 灼烧强化
    out = await cmd_inherit(parse_command("/继承 剧毒强化"), ctx)
    assert "特性须来自投料候选清单" in out


async def test_inherit_apprentice_no_slot() -> None:
    """INH-14 负例：见习（level 0）→ 「见习无继承位」。"""
    ctx = make_ctx(proficiency={"alchemy": _alchemy_node(0)})
    await cmd_alchemy(parse_command("/炼金 火焰弹"), ctx)
    await cmd_feed(parse_command("/投料 火晶石"), ctx)
    out = await cmd_inherit(parse_command("/继承 灼烧强化"), ctx)
    assert "见习无继承位" in out


# ---------------------------------------------------------------------------
# /继承超：F-04/TSC-11~13 第 4 位独占 + 宗师门槛
# ---------------------------------------------------------------------------
async def test_inherit_super_ok_4th_gold_slot() -> None:
    """TSC-11~13/M-04 正例：宗师投 金色余烬 → /继承超 灼烧强化·精 → 第 4 位金色，
    PP 2/5；快照 gold_slot 落库。"""
    ctx = make_ctx(proficiency={"alchemy": _alchemy_node(5)})  # 宗师
    await cmd_alchemy(parse_command("/炼金 火焰弹"), ctx)
    await cmd_feed(parse_command("/投料 金色余烬"), ctx)
    out = await cmd_inherit_super(parse_command("/继承超 灼烧强化·精"), ctx)
    assert "第 4 位金色（灼烧强化·精）" in out
    assert "PP 2/5" in out
    snap = ctx["session_mgr"].store["u1"]["payload"]
    assert snap["gold_slot"] == "trait_fire_15"
    assert snap["pp"]["used"] == 2
    assert ctx["session_mgr"].store["u1"]["version"] == 3


async def test_inherit_super_grandmaster_required() -> None:
    """TSC-11 负例：大师（tier4）→ 「超特性继承需宗师」。"""
    ctx = make_ctx(proficiency={"alchemy": _alchemy_node(4)})
    await cmd_alchemy(parse_command("/炼金 火焰弹"), ctx)
    await cmd_feed(parse_command("/投料 金色余烬"), ctx)
    out = await cmd_inherit_super(parse_command("/继承超 灼烧强化·精"), ctx)
    assert "超特性继承需宗师" in out
    assert ctx["session_mgr"].store["u1"]["payload"].get("gold_slot") is None


async def test_inherit_super_single_only() -> None:
    """P-04 负例：/继承超 传 2 个金色特性 → 「仅支持 1 个金色特性」。"""
    ctx = make_ctx(proficiency={"alchemy": _alchemy_node(5)})
    await cmd_alchemy(parse_command("/炼金 火焰弹"), ctx)
    await cmd_feed(parse_command("/投料 金色余烬"), ctx)
    out = await cmd_inherit_super(parse_command("/继承超 灼烧强化·精,灼烧强化·大师"), ctx)
    assert "仅支持 1 个金色特性" in out


# ---------------------------------------------------------------------------
# 装配：register_alchemy_commands 注册 继承/继承超
# ---------------------------------------------------------------------------
async def test_register_alchemy_commands_inherit() -> None:
    """装配：register_alchemy_commands 注册 继承/继承超（含既有 合成/炼金/投料）。"""
    router = Router()
    register_alchemy_commands(router, make_context=lambda p: make_ctx())
    assert router.has(INHERIT_CMD)
    assert router.has(INHERIT_SUPER_CMD)
    assert {INHERIT_CMD, INHERIT_SUPER_CMD} <= set(router.names())
    spec = router.get(INHERIT_CMD)
    assert spec is not None and spec.whitelisted


async def test_register_inherit_handler_injectable_ctx() -> None:
    """装配：/继承 handler 支持 k.get("ctx") 注入（async 处理器 await 执行）。"""
    router = Router()
    ctx = make_ctx()
    register_alchemy_commands(router, make_context=lambda p: {})
    spec = router.get(INHERIT_CMD)
    assert spec is not None and spec.handler is not None
    await cmd_alchemy(parse_command("/炼金 火焰弹"), ctx)
    await cmd_feed(parse_command("/投料 火晶石"), ctx)
    out = await spec.handler(parse_command("/继承 灼烧强化"), ctx=ctx)
    assert "已继承：灼烧强化" in out
