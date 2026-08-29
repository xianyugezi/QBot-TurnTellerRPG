"""即时调合指令壳单测（M8 批9 路9B · qbot_rpg/commands/alchemy_commands.py 的 cmd_instant）。

文件：tests/unit/test_instant_commands.py
创建：2026-08-29
作者：Hermes 子agent-9B
功能：cmd_instant（/即时调合 <配方>）战斗内一步出结果子流程异步直测。构造 fake 战斗快照 dict
  （ctx["battle_snapshot"]）+ 真实引擎鸭子（FakeBattleAlchemyEngine 按兄弟路 core/alchemy_battle.py
  契约方法签名实现：instant_eligible/carry_ok/resolve/intensity/cooldown_of/consume_energy——
  其中 carry_ok 真查 ctx.inventory、consume_energy 委托真实 EnergyBar、resolve 真扣素材+调用
  use_fn）+ fake use_fn（ctx["use_battle_item"]）。

覆盖矩阵（每条正例 + 负例，断言精确文本/数值/快照字段/引擎调用记录；asyncio_mode=auto 直接 await）：
  TC-24 正例：战斗中+大师+素材齐 → 一步出结果：resolve 收到 battle_alchemy_used=0/cooldown=3
    （炸弹 3 回合）→ use_fn 被调（auto_use=true）→ 渲染 M-17 伤害行「火焰弹！造成 58 伤害」
    （M5 无 emoji 纯文本）→ battle_alchemy_used 写回 1
  TC-24 负例：素材不足 → carry_ok 全拒差异「❌ 材料不足：缺 月光草×2」+ 快照不写
  TC-25 负例：同场第 2 次（battle_alchemy_used=1）→ 「本场战斗已使用过即时调合（限 1 次/场）」
  TC-25 正例：新场次（快照无该键）→ 清零可再用，battle_alchemy_used 置 1
  非战斗拒绝（GU-50）／非大师拒绝（GU-51）／能量不足（enabled 时，GU-52）／能量关闭直通（R-08）
  auto_use=false 入包（BA-07：use_fn 不被调，渲染「已入包」）／use_fn 缺失 → auto_use 回退入包
  配方不存在／缺参 TPL-12／装配注册 INSTANT_CMD

依据：docs/m8_contract_指令契约.md §16 /即时调合（GU-50~54/F-17/M-17，TC-24/25）+
  docs/m8_contract_战斗资源.md §三 战斗即时调合（BA-01~11，IF-B03/B04 落点）。
测试风格对齐 tests/unit/test_alchemy_commands.py（parse_command 直调 + 全字段 ctx）。
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, MutableMapping, Optional

from qbot_rpg.commands.alchemy_commands import (
    INSTANT_CMD,
    cmd_instant,
    register_alchemy_commands,
)
from qbot_rpg.commands.parsers import DEFAULT_WHITELIST, parse_command as _parse_raw
from qbot_rpg.commands.router import Router
from qbot_rpg.core.energy_bar import EnergyBar

# 注入白名单 W 的 parse 包装（DEFAULT_WHITELIST 未含 即时调合，批11A 装配补齐 IF-34）
def _pc(raw: str):
    return _parse_raw(raw, whitelist=W)

# 即时调合 白名单（DEFAULT_WHITELIST 未含；批11 路11A 装配补齐——本测试注入同款）
W = DEFAULT_WHITELIST | {"即时调合"}

# ---------------------------------------------------------------------------
# 夹具：items/recipe 注册表 + settings（对齐 test_alchemy_commands 形态 + 战斗即时调合配置）
# ---------------------------------------------------------------------------

ITEMS: Dict[str, dict] = {
    "moon_grass": {"id": "moon_grass", "name": "月光草", "type": "material"},
    "flame_bomb": {"id": "flame_bomb", "name": "火焰弹", "type": "consumable"},
    "mana_potion": {"id": "mana_potion", "name": "魔力药水", "type": "consumable"},
}

RECIPES: Dict[str, dict] = {
    "rcp_flame": {"id": "rcp_flame", "name": "火焰弹", "level": 5,
                  "materials": [{"id": "moon_grass", "count": 2}],
                  "cost": {"coins": 100, "gem": 0},
                  "output": {"item": "flame_bomb", "count": 1}},
    "rcp_mana": {"id": "rcp_mana", "name": "魔力药水", "level": 3,
                 "materials": [{"id": "moon_grass", "count": 1}],
                 "cost": {"coins": 50, "gem": 0},
                 "output": {"item": "mana_potion", "count": 1}},
}

# 战斗即时调合配置（settings.alchemy.战斗即时调合，L425：
# auto_use 默认 true / per_battle_limit 默认 1）
SETTINGS: Dict[str, Any] = {
    "currencies": [{"id": "coins", "name": "金币"}, {"id": "gem", "name": "宝石"}],
    "alchemy": {
        "mode": "full",
        "energy_enabled": False,          # R-08 默认关
        "max_qty": 2147483647,
        "战斗即时调合": {"auto_use": True, "per_battle_limit": 1},
    },
}


def _alchemy_node(level: int = 4) -> dict:
    """炼金职业节点（level = 档位索引 0~6；4=大师，GU-51 门槛）。"""
    return {"level": level, "exp": 0, "sp_earned": 0, "sp_used": 0, "unlocks": {}}


class FakeBattleAlchemyEngine:
    """兄弟路 core/alchemy_battle.py BattleAlchemyEngine 鸭子（契约方法签名对齐，壳层测试直替）。

    - carry_ok：真查 ctx["inventory"] 对 recipe.materials 全量持有（不足全拒+shortfall 差异）；
    - consume_energy：委托真实 EnergyBar.consume(player, 1)（energy_enabled 关闭 → bypassed 直通）；
    - cooldown_of：炸弹 3 回合（BA-06），返回 self.cooldown（默认 3）；
    - resolve：真扣素材 → auto_use+use_fn → 调 use_fn 返回 ActionOutcome 同型 dict；
      auto_use=false 或 use_fn 缺失 → 入包（ctx["inventory"] 加产出）返回包行数据。
    调用记录 self.calls 供断言（GU-53/54/F-17 时序）。
    """

    def __init__(self) -> None:
        self.cooldown: int = 3
        self.calls: list = []
        self.resolve_result: Optional[dict] = None  # None = 默认成功路径
        self.use_fn_called: int = 0

    # --- 契约方法（兄弟路签名；本壳只消费其中 carry_ok/resolve/cooldown_of/consume_energy） ---
    def instant_eligible(self, player: Any, job_id: Any, *,
                         in_battle: bool, battle_alchemy_used: int) -> dict:
        self.calls.append(("instant_eligible", in_battle, battle_alchemy_used))
        return {"ok": True}

    def carry_ok(self, ctx: Mapping[str, Any], recipe_def: Mapping[str, Any]) -> dict:
        self.calls.append(("carry_ok", recipe_def.get("id")))
        inv = ctx.get("inventory")
        inv = inv if isinstance(inv, Mapping) else {}
        shortfall: list = []
        for m in recipe_def.get("materials") or []:
            mid = m.get("id") if isinstance(m, Mapping) else m
            cnt = m.get("count", 1) if isinstance(m, Mapping) else 1
            try:
                ci = max(1, int(cnt))
            except (TypeError, ValueError):
                ci = 1
            have = 0
            if isinstance(mid, str):
                try:
                    have = max(0, int(inv.get(mid, 0)))
                except (TypeError, ValueError):
                    have = 0
            if have < ci:
                shortfall.append({"item": mid, "count": ci, "have": have})
        if shortfall:
            return {"ok": False, "shortfall": shortfall}
        return {"ok": True}

    def resolve(self, ctx: MutableMapping[str, Any], recipe_def: Mapping[str, Any], *,
                battle_alchemy_used: int, auto_use: Optional[bool] = None,
                cooldown: int = 0, use_fn: Any = None) -> dict:
        self.calls.append(("resolve", battle_alchemy_used, auto_use, cooldown))
        inv = ctx.get("inventory")
        inv = inv if isinstance(inv, MutableMapping) else {}
        # 一步出结果：真扣素材（BA-08 原子扣减，壳层直替版）
        for m in recipe_def.get("materials") or []:
            mid = m.get("id") if isinstance(m, Mapping) else m
            cnt = m.get("count", 1) if isinstance(m, Mapping) else 1
            if isinstance(mid, str) and isinstance(inv, MutableMapping):
                try:
                    ci = max(1, int(cnt))
                except (TypeError, ValueError):
                    ci = 1
                inv[mid] = max(0, int(inv.get(mid, 0)) - ci)
        output = recipe_def.get("output")
        out_id = output.get("item") if isinstance(output, Mapping) else None
        name = out_id if isinstance(out_id, str) else "产物"
        if self.resolve_result is not None:
            return self.resolve_result
        # auto_use=true + use_fn → 当场自动使用（BA-07：走战斗道具行动入口）
        if auto_use and use_fn is not None:
            self.use_fn_called += 1
            use_fn({"item": out_id, "count": 1})
            return {"ok": True, "item_name": "火焰弹", "final_damage": 58,
                    "raw_damage": 58, "action_type": "item"}
        # 入包（BA-07：auto_use=false 或 use_fn 缺失 → 产出入包，本场不可再用）
        if isinstance(out_id, str) and isinstance(inv, MutableMapping):
            inv[out_id] = int(inv.get(out_id, 0)) + 1
        return {"ok": True, "item_name": name, "added": 1}

    def intensity(self, recipe_def: Mapping[str, Any], *, cooldown: int) -> float:
        self.calls.append(("intensity", recipe_def.get("id"), cooldown))
        return 58.0

    def cooldown_of(self, recipe_def: Mapping[str, Any]) -> int:
        self.calls.append(("cooldown_of", recipe_def.get("id")))
        return self.cooldown

    def consume_energy(self, player: Any, ctx: Mapping[str, Any]) -> dict:
        self.calls.append(("consume_energy",))
        settings = ctx.get("settings")
        energy = EnergyBar(settings=settings if isinstance(settings, Mapping) else None)
        return energy.consume(player, 1)


def make_ctx(**over: Any) -> dict:
    """全字段即时调合 ctx（player 字段在 ctx 顶层——_player_of 兜底口径，
    对齐 test_alchemy_commands）。

    战斗三件套：in_battle=True / battle_snapshot={}（战斗快照 dict 鸭子，battle_alchemy_used
    顶层键读写）/ battle_alchemy_engine=FakeBattleAlchemyEngine()（引擎鸭子）+ 可选
    use_battle_item（fake use_fn）。
    """
    base: dict = {
        "qid": "u1",
        "proficiency": {"alchemy": _alchemy_node(4)},   # 大师（GU-51）
        "currencies": {"coins": 1000, "gem": 0},
        "inventory": {"moon_grass": 5},
        "items": ITEMS,
        "recipe": RECIPES,
        "settings": SETTINGS,
        "in_battle": True,
        "battle_snapshot": {},
        "battle_alchemy_engine": FakeBattleAlchemyEngine(),
    }
    base.update(over)
    return base


def make_use_fn() -> tuple:
    """fake use_fn（战斗道具行动入口，BA-07）：记录调用，返回 ActionOutcome 同型 dict。"""
    calls: list = []

    def use_fn(action: Any = None, **kw: Any) -> dict:
        calls.append((action, kw))
        return {"ok": True, "action_type": "item", "final_damage": 58}

    return use_fn, calls


def engine_used_calls(used_calls: list) -> bool:
    """use_fn 调用断言辅助（非空 → use_fn 确被调，BA-07 当场自动使用）。"""
    return bool(used_calls)


# ---------------------------------------------------------------------------
# TC-24 正例：战斗中+大师+素材 → 一步出结果（auto_use=true）
# ---------------------------------------------------------------------------
async def test_instant_one_step_auto_use_true() -> None:
    """TC-24/F-17/BA-07 正例：auto_use=true + use_fn → resolve 收到 battle_alchemy_used=0/
    cooldown=3 → use_fn 被调 → M-17 伤害行渲染 → battle_alchemy_used 写回 1。"""
    engine = FakeBattleAlchemyEngine()
    use_fn, used_calls = make_use_fn()
    ctx = make_ctx(battle_alchemy_engine=engine, use_battle_item=use_fn)
    out = await cmd_instant(_pc("/即时调合 火焰弹"), ctx)
    # M-17 一行（M5 无 emoji 纯文本）：「火焰弹！造成 58 伤害」
    assert out == "火焰弹！造成 58 伤害"
    assert "🔥" not in out
    # resolve 调用签名：battle_alchemy_used=0（首用）、auto_use=True、cooldown=3（炸弹 3 回合）
    resolve_call = engine.calls[-1]
    assert resolve_call[0] == "resolve" and resolve_call[1] == 0
    assert resolve_call[2] is True and resolve_call[3] == 3
    # use_fn 被调（当场自动使用，BA-07）
    assert engine.use_fn_called == 1 and len(used_calls) == 1
    # battle_alchemy_used 写回注入战斗快照顶层键（BA-02）
    assert ctx["battle_snapshot"].get("battle_alchemy_used") == 1
    # 素材真扣（BA-08 原子扣减，直替版）：月光草 5 → 3
    assert ctx["inventory"]["moon_grass"] == 3


async def test_instant_material_shortfall_rejected() -> None:
    """TC-24/GU-53 负例：素材不足 → carry_ok 全拒+差异（ATO-01），快照不写、素材不扣。"""
    ctx = make_ctx(inventory={})  # 配方需 月光草×2，持有 0
    out = await cmd_instant(_pc("/即时调合 火焰弹"), ctx)
    assert out == "❌ 材料不足：缺 月光草×2"
    assert ctx["battle_snapshot"].get("battle_alchemy_used") is None
    assert ctx["inventory"].get("moon_grass", 0) == 0  # 全拒零扣


# ---------------------------------------------------------------------------
# TC-25：限次（GU-54）——同场第 2 次拒绝 / 新场次清零可再用
# ---------------------------------------------------------------------------
async def test_instant_second_use_same_battle_rejected() -> None:
    """TC-25/GU-54 负例：battle_alchemy_used=1 ≥ per_battle_limit=1 → 「限 1 次/场」拒绝。"""
    engine = FakeBattleAlchemyEngine()
    ctx = make_ctx(battle_alchemy_engine=engine, battle_snapshot={"battle_alchemy_used": 1})
    out = await cmd_instant(_pc("/即时调合 火焰弹"), ctx)
    assert out == "本场战斗已使用过即时调合（限 1 次/场）"
    # 限次拒绝（GU-54 合同末位守卫）：素材校验已过（GU-53 先于 GU-54），但 resolve 不进入
    assert not any(c[0] == "resolve" for c in engine.calls)
    assert ctx["battle_snapshot"].get("battle_alchemy_used") == 1  # 不变


async def test_instant_new_battle_cleared_ok() -> None:
    """TC-25/GU-54 正例：新场次（快照无 battle_alchemy_used 键，中断恢复不清零口径下缺省 0）
    → 清零可再用 → 写回 1。"""
    use_fn, used_calls = make_use_fn()
    ctx = make_ctx(use_battle_item=use_fn)  # battle_snapshot={}，新场次
    out = await cmd_instant(_pc("/即时调合 火焰弹"), ctx)
    assert "造成 58 伤害" in out
    assert ctx["battle_snapshot"].get("battle_alchemy_used") == 1
    assert engine_used_calls(used_calls)


# ---------------------------------------------------------------------------
# GU-50 战斗中 / GU-51 大师
# ---------------------------------------------------------------------------
async def test_instant_not_in_battle_rejected() -> None:
    """GU-50 负例：非战斗 → 「即时调合仅限战斗中」；不触引擎、不写快照。"""
    engine = FakeBattleAlchemyEngine()
    ctx = make_ctx(battle_alchemy_engine=engine, in_battle=False)
    out = await cmd_instant(_pc("/即时调合 火焰弹"), ctx)
    assert out == "即时调合仅限战斗中"
    assert not engine.calls
    assert not ctx["battle_snapshot"]


async def test_instant_not_master_rejected() -> None:
    """GU-51 负例：精通（level 2 < 大师 4）→ 「❌ 等级不足」。"""
    ctx = make_ctx(proficiency={"alchemy": _alchemy_node(2)})
    out = await cmd_instant(_pc("/即时调合 火焰弹"), ctx)
    assert out == "❌ 等级不足"
    assert not ctx["battle_snapshot"]


# ---------------------------------------------------------------------------
# GU-52 能量（R-08：默认关直通 / 开启时不足拒）
# ---------------------------------------------------------------------------
async def test_instant_energy_insufficient_rejected() -> None:
    """GU-52/R-08 负例：energy_enabled=true 且能量 0 → consume_energy 不足拒（真实 EnergyBar
    文案）；快照不写、不进入 resolve。"""
    engine = FakeBattleAlchemyEngine()
    settings = {"alchemy": dict(SETTINGS["alchemy"], energy_enabled=True)}
    ctx = make_ctx(battle_alchemy_engine=engine, settings=settings,
                   persistent_state={"energy_current": 0, "energy_last_regen_ts": 10 ** 12})
    out = await cmd_instant(_pc("/即时调合 火焰弹"), ctx)
    assert "能量" in out and "等 30 分钟回 1 格" in out
    assert not ctx["battle_snapshot"]
    # 能量不足在 resolve 之前拦截（调用记录无 resolve）
    assert not any(c[0] == "resolve" for c in engine.calls)


async def test_instant_energy_off_bypass() -> None:
    """GU-52/R-08 正例：energy_enabled=false（默认关）→ 能量 0 直通，不扣不拒。"""
    use_fn, used_calls = make_use_fn()
    ctx = make_ctx(use_battle_item=use_fn,
                   persistent_state={"energy_current": 0, "energy_last_regen_ts": 10 ** 12})
    out = await cmd_instant(_pc("/即时调合 火焰弹"), ctx)
    assert "造成 58 伤害" in out
    assert ctx["battle_snapshot"].get("battle_alchemy_used") == 1
    assert engine_used_calls(used_calls)


async def test_instant_energy_consumed_one_when_enabled() -> None:
    """GU-52 正例：energy_enabled=true 且能量 5 → consume_energy 扣 1 格（5→4）。"""
    use_fn, used_calls = make_use_fn()
    settings = {"alchemy": dict(SETTINGS["alchemy"], energy_enabled=True)}
    ctx = make_ctx(settings=settings, use_battle_item=use_fn,
                   persistent_state={"energy_current": 5, "energy_last_regen_ts": 10 ** 12})
    out = await cmd_instant(_pc("/即时调合 火焰弹"), ctx)
    assert "造成 58 伤害" in out
    assert ctx["persistent_state"]["energy_current"] == 4
    assert engine_used_calls(used_calls)


# ---------------------------------------------------------------------------
# BA-07：auto_use=false 入包 / use_fn 缺失回退入包
# ---------------------------------------------------------------------------
async def test_instant_auto_use_false_bag() -> None:
    """BA-07 负例：auto_use=false（settings 战斗即时调合.auto_use=false）→ 产出入包
    （use_fn 不被调）渲染「已入包」→ battle_alchemy_used 仍置 1（限 1 次/场口径）。"""
    engine = FakeBattleAlchemyEngine()
    use_fn, used_calls = make_use_fn()
    settings = {"alchemy": dict(SETTINGS["alchemy"],
                                **{"战斗即时调合": {"auto_use": False, "per_battle_limit": 1}})}
    ctx = make_ctx(battle_alchemy_engine=engine, settings=settings, use_battle_item=use_fn)
    out = await cmd_instant(_pc("/即时调合 火焰弹"), ctx)
    assert "已入包" in out and "本场战斗内不可再使用" in out
    assert engine.use_fn_called == 0 and not used_calls  # use_fn 不被调
    assert ctx["inventory"].get("flame_bomb", 0) == 1  # 产出真入包
    assert ctx["battle_snapshot"].get("battle_alchemy_used") == 1


async def test_instant_use_fn_missing_fallback_bag() -> None:
    """【工程补白】use_fn 缺失（ctx 无 use_battle_item）→ auto_use 回退入包，不报错。"""
    engine = FakeBattleAlchemyEngine()
    ctx = make_ctx(battle_alchemy_engine=engine)  # 无 use_battle_item
    out = await cmd_instant(_pc("/即时调合 火焰弹"), ctx)
    assert "已入包" in out
    assert engine.use_fn_called == 0
    assert ctx["battle_snapshot"].get("battle_alchemy_used") == 1


# ---------------------------------------------------------------------------
# 其它：配方不存在 / 缺参 TPL-12 / 装配注册
# ---------------------------------------------------------------------------
async def test_instant_recipe_not_found() -> None:
    """配方不存在 → 「❌ 配方不存在：{目标}」。"""
    ctx = make_ctx()
    out = await cmd_instant(_pc("/即时调合 不存在的配方"), ctx)
    assert out == "❌ 配方不存在：不存在的配方"
    assert not ctx["battle_snapshot"]


async def test_instant_missing_arg_tpl12() -> None:
    """缺参 → TPL-12（指令不正确模板）。"""
    ctx = make_ctx()
    out = await cmd_instant(_pc("/即时调合"), ctx)
    assert "指令不正确" in out and "即时调合" in out


async def test_register_includes_instant() -> None:
    """装配：register_alchemy_commands 注册 INSTANT_CMD（whitelisted，ctx 注入 handler）。"""
    router = Router()
    register_alchemy_commands(router, make_context=lambda p: make_ctx())
    assert router.has(INSTANT_CMD)
    assert INSTANT_CMD in set(router.names())
    spec = router.get(INSTANT_CMD)
    assert spec is not None and spec.whitelisted and spec.handler is not None
