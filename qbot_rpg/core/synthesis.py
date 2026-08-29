"""第 1 层跨职业合成引擎（M8 批2·路2A · qbot_rpg/core/synthesis.py）——SynthesisEngine。

文件名：qbot_rpg/core/synthesis.py
创建时间：2026-08-29
作者：Hermes 子agent-2A（并发同仓：仅新建本文件 + qbot_rpg/commands/alchemy_commands.py +
  tests/unit/test_synthesis.py + tests/unit/test_synthesis_commands.py）

功能描述：SynthesisEngine 承载第 1 层【合成】（跨职业快捷生产，LAY-01）的全部业务逻辑——守卫
  （GU-01~03）/ 原子校验（GU-04）/ 标准版产出（LAY-04a）/ 熟练经验（CASC-01）/ 合成图鉴点亮 /
  数量上限（拍板⑤）/ 不耗能量（LAY-05）。纯函数零 IO 零 NoneBot；
  操作对象 = ctx 玩家表示（就地改写）；
  返回 dict 结果、拒绝场景 {ok: False, reason, message} 不抛异常。

依据：
  - docs/细化/细化_2c4a_炼金三层漏斗.md：LAY-01（跨职业无炼金职业门槛）/LAY-04a（标准版：品质固定、
    无特性/超特性/进化/核心类；标准珠固定 base_effects）/LAY-05（合成不耗能量）/CASC-01（合成每成品
    = 配方等级 ×1 熟练，制作来源）/CASC-02（job_tier_map 配方区间，
   配方 level 落在当前称号区间才可合成）/
    CASC-04（synth_allowed 默认 false 深度配方；true 提示不阻断）/
   JOB-03/JOB-04；验收 TC-01/02/07/08/
    09/15/16/23。
  - docs/m8_contract_指令契约.md §1 /合成（P-01 参数/GU-01~04 前置守卫/F-01 流程/M-01 消息模板；
    实现批次批2 路2A）与 §十 铁律（数量上限默认 2147483647=int32 max 可配 max_qty，超限提示不拦，
    对齐分隔符规范 L73）。
  - docs/m8_contract_核心机制.md §一（LAY/CASC 全文）+ §十 10.3 默认值速查（alchemy.mode=full /
    max_qty=2147483647 / synth_exp=配方等级×1）。
  - qbot_rpg/core/proficiency.py ProficiencyEngine（recipe_level_eligible 配方区间准入 /
    gain_prof_exp 熟练入账，批1 标注消费点即本批）+ content/test_demo/recipe.json + settings.json
    alchemy 段（真实数据形态：materials[{id,count}] / output{item,count} / cost{coins,gem} /
    synth_allowed / master_only）。
  - 模式参考 core/shop.py（ctx hook 模式：ctx["items"] 注册表或 resolve_item 解析器、
    ctx["add_item"](item_id, count, bound)->bool、ctx["remove_item"](item_id, count)->bool、
    ctx["count_item"](item_id)->int、ctx["currencies"] 玩家货币表就地扣减；快照-回滚原子性；
    按定稿模板
    合成 ✅/❌ 业务文案）+ core/levelup.py LevelUpEngine（构造器配置注入+缺省兜底）+ core/reward.py
    （ctx hook 消费）。

【工程补白 · 显式标注】（定稿/细化未显式定义处，全部按本清单落地；不得新增定稿外机制行为）：
  1) 操作对象 = ctx 玩家表示（可变 dict，就地改写，对齐 shop.py/reward.py 既有引擎：ctx 顶层即玩家
     状态——proficiency/currencies/inventory 均在 ctx 顶层）。配置来源 = 构造器注入 settings（缺省
     {} → 默认值兜底），不读 ctx["settings"]（构造器单源，确定性；
     指令壳注入 ctx settings 到构造器）。
  2) 配方解析（P-01 名称优先 → 序号兜底）：ctx["recipe"] 注册表 dict（id→recipe）或
     ctx["resolve_recipe"] 解析器 hook；匹配顺序 = id 精确 → name 精确 → 1 基序号（注册表插入序）。
  3) 候选制造/资源职业 = player["proficiency"] 中全部已解锁职业（proficiency 桶即生活职业熟练度，
     LAY-01「任一制造/资源职业」；战斗/其它职业不进桶由装配层保证，本引擎不额外过滤）。多职业同时
     达标取等级最高者（EXP-03 工程补白；等级 = 熟练引擎档位索引 0~6，
     对齐 ProficiencyEngine 存档口径）。
  4) 职业显示名：_JOB_NAME_FALLBACK 兜底表（炼金/钓鱼/锻造/采集），未命中 → 原 job_id。
  5) synth_allowed 缺省解析（CASC-04）：字段显式布尔取显式值；缺省 = not master_only——普通配方缺省
     可合成、深度配方（master_only=true）缺省 false 拦合成绕过（「深度配方默认 false」口径）。
  6) 数量超限（拍板⑤/ATO-07）：settings.alchemy.max_qty 缺省 2147483647；超限「最多一次使用 N 个」
     提示不拦截——按上限截断执行量（对齐 shop D-05/TC-03「先按上限截断执行量」），提示随结果携带。
  7) 原子校验（GU-04/ATO-01）：材料×n + cost 金币/宝石×n 全量满足才执行，否则全拒+差异提示
     「缺 水结晶×5 + 金币 30」（材料按配方序、货币 coins 后 gem；差异=需求-持有）。货币桶缺失且
     cost>0 → 「无法结算货币」（对齐 shop 校验链⑤）。
  8) 熟练经验（CASC-01/EXP-03）：amount = 配方 level × 成品总数（output.count×n），入账走
     prof.gain_prof_exp(source='craft')，入账到 check_eligible 选中的达标职业（等级最高者）；
     exp_gained 取入账倍率后实际值（proficiency 引擎 EXP-02 兜底 1.0）。
  9) 标准版产出（LAY-04a）：add_item(output_item, output.count×n, bound=False)——绑定态定稿未言，
     取 False（可交易普通商品，对齐商店购买入包 bound=False；
     【工程补白】显式标注，可被装配层覆盖）。
  10) 合成图鉴点亮：on_codex 回调为 synthesize 关键字参数（默认 None 跳过）；签名
     on_codex(player, recipe_id, count)，返回值忽略、异常吞掉（fire-and-forget，不阻断结算）。
  11) 不耗能量（LAY-05/ENG-07）：引擎全程不读不写能量桶（ctx 无 energy 键即天然满足；测试断言
     能量未变）。
  12) 配方等级非正整数（缺失/0/负）→ check_eligible 保守拒绝 level_insufficient（对齐
     ProficiencyEngine recipe_level_eligible 补白 6「配方 level 非正整数 → 保守拒绝」）。

铁律：零 NoneBot import；纯函数（同刻同参必同值）；工程补白显式标注；不新增定稿外机制行为。
"""
from __future__ import annotations

import copy
from typing import Any, Callable, List, Mapping, MutableMapping, Optional

from qbot_rpg.core.proficiency import ProficiencyEngine

__all__ = [
    "DEFAULT_MAX_QTY",
    "SynthesisEngine",
    "resolve_recipe",
]

# ---------------------------------------------------------------------------
# 常量（拍板⑤ / 细化_2c4a §六 数据落点）
# ---------------------------------------------------------------------------
# 数量上限默认 = int32 max（拍板⑤ / m8_contract_指令契约 §3.4 / ATO-07）
DEFAULT_MAX_QTY: int = 2147483647
# 职业显示名兜底表（工程补白 4；未命中 → 原 job_id）
_JOB_NAME_FALLBACK: Mapping[str, str] = {
    "alchemy": "炼金",
    "fishing": "钓鱼",
    "forging": "锻造",
    "gathering": "采集",
}
# 快照-回滚覆盖的可变 ctx 子结构（工程补白 1/7：对齐 shop.py 原子防双扣口径）
_SNAP_KEYS: tuple = ("currencies", "inventory")
# 模式三态（LAY-06）
_MODE_FULL = "full"
_MODE_OFF = "off"


# ---------------------------------------------------------------------------
# 基础工具（纯函数，镜像 shop.py 同款实现）
# ---------------------------------------------------------------------------
def _as_int(value: object) -> Optional[int]:
    """int 归一（bool 除外）；非 int/bool/可转数字串 → None（对齐 shop._as_int）。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if float(value).is_integer() else None
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _item_name(item_id: str, ctx: Mapping[str, Any]) -> str:
    """物品 id → 显示名（ctx["items"] 注册表或 resolve_item 解析器；缺省回退原 id）。"""
    if not isinstance(item_id, str):
        return str(item_id)
    items = ctx.get("items")
    if isinstance(items, Mapping):
        hit = items.get(item_id)
        if isinstance(hit, Mapping):
            name = hit.get("name")
            if isinstance(name, str) and name:
                return name
    resolver = ctx.get("resolve_item")
    if callable(resolver):
        try:
            hit = resolver(item_id)
        except Exception:
            hit = None
        if isinstance(hit, Mapping):
            name = hit.get("name")
            if isinstance(name, str) and name:
                return name
    return item_id


def _job_name(job_id: str, ctx: Mapping[str, Any]) -> str:
    """职业显示名（工程补白 4）：ctx["jobs"] 注册表 name → 兜底表 → 原 id。"""
    if isinstance(job_id, str):
        jobs = ctx.get("jobs")
        if isinstance(jobs, Mapping):
            hit = jobs.get(job_id)
            if isinstance(hit, Mapping):
                name = hit.get("name")
                if isinstance(name, str) and name:
                    return name
        return _JOB_NAME_FALLBACK.get(job_id, job_id)
    return str(job_id)


def _add_item(ctx: MutableMapping[str, Any], item_id: str, count: int, bound: bool) -> bool:
    """入包：优先 ctx["add_item"] hook；回退 ctx["inventory"] in-memory；均无 → False。"""
    hook = ctx.get("add_item")
    if callable(hook):
        try:
            return bool(hook(item_id, count, bound))
        except Exception:
            return False
    inv = ctx.get("inventory")
    if isinstance(inv, MutableMapping):
        inv[item_id] = int(inv.get(item_id, 0)) + count
        return True
    return False


def _remove_item(ctx: MutableMapping[str, Any], item_id: str, count: int) -> bool:
    """扣减（不部分扣减）：优先 ctx["remove_item"] hook；回退 ctx["inventory"] in-memory。"""
    hook = ctx.get("remove_item")
    if callable(hook):
        try:
            return bool(hook(item_id, count))
        except Exception:
            return False
    inv = ctx.get("inventory")
    if isinstance(inv, MutableMapping):
        cur = int(inv.get(item_id, 0))
        if cur < count:
            return False
        inv[item_id] = cur - count
        return True
    return False


def _count_item(ctx: Mapping[str, Any], item_id: str) -> int:
    """持有计数：优先 ctx["count_item"] hook；回退 ctx["inventory"] in-memory。"""
    hook = ctx.get("count_item")
    if callable(hook):
        try:
            return int(hook(item_id))
        except Exception:
            return 0
    inv = ctx.get("inventory")
    if isinstance(inv, Mapping):
        return int(inv.get(item_id, 0))
    return 0


def _snapshot(ctx: Mapping[str, Any]) -> dict:
    """快照（工程补白 7：事务内原子防双扣，对齐 shop._snapshot）。"""
    return {k: copy.deepcopy(ctx.get(k)) for k in _SNAP_KEYS}


def _restore(ctx: MutableMapping[str, Any], snap: dict) -> None:
    """回滚（对齐 shop._restore）。"""
    for k, v in snap.items():
        if v is None:
            ctx.pop(k, None)
        else:
            ctx[k] = v


class _Rollback(Exception):
    """结算阶段失败标记（进程内回滚触发，对齐 shop._Rollback）。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def resolve_recipe(ctx: Mapping[str, Any], ref: object) -> Optional[Mapping[str, Any]]:
    """配方解析（P-01：名称优先 → 序号兜底；工程补白 2）。

    匹配顺序 = id 精确 → name 精确 → 1 基序号（ctx["recipe"] 注册表插入序）；
    另支持 ctx["resolve_recipe"] 解析器 hook（镜像 shop.resolve_shop）。
    """
    if not isinstance(ref, str) or not ref.strip():
        return None
    recipes = ctx.get("recipe")
    if isinstance(recipes, Mapping):
        # id 精确
        if ref in recipes:
            hit = recipes[ref]
            if isinstance(hit, Mapping):
                return hit
        # name 精确
        for r in recipes.values():
            if isinstance(r, Mapping) and r.get("name") == ref:
                return r
        # 1 基序号
        if ref.isdigit():
            seq = int(ref)
            ids = [k for k in recipes if isinstance(recipes[k], Mapping)]
            if 1 <= seq <= len(ids):
                return recipes[ids[seq - 1]]
    resolver = ctx.get("resolve_recipe")
    if callable(resolver):
        try:
            hit = resolver(ref)
        except Exception:
            hit = None
        if isinstance(hit, Mapping):
            return hit
    return None


# ---------------------------------------------------------------------------
# SynthesisEngine
# ---------------------------------------------------------------------------
class SynthesisEngine:
    """第 1 层【合成】引擎（LAY-01/LAY-04a/LAY-05/CASC-01/02/04/JOB-03/04）。

    操作对象为 ctx 玩家表示（就地改写 proficiency/currencies/inventory）；返回 dict 结果、
    拒绝场景 {ok: False, reason, message} 不抛异常；纯函数零 IO 零 NoneBot。
    """

    def __init__(
        self,
        prof: Optional[ProficiencyEngine] = None,
        settings: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """构造合成引擎（构造器配置注入 + 缺省兜底，对齐 LevelUpEngine B-1 模式）。

        入参：
          - prof：ProficiencyEngine（recipe_level_eligible 区间准入 / gain_prof_exp 熟练入账）。
            None → 内部缺省构造 ProficiencyEngine(settings=settings)（工程补白 1：配置单源）。
          - settings：settings dict（alchemy 段：mode/max_qty/job_tier_map 等）；
            缺省 {} → 默认值兜底。
        """
        self._settings: Mapping[str, Any] = settings if isinstance(settings, Mapping) else {}
        if isinstance(prof, ProficiencyEngine):
            self._prof: ProficiencyEngine = prof
        else:
            self._prof = ProficiencyEngine(settings=self._settings)

    # ------------------------------------------------------------------
    # 配置读取（构造器单源 + 缺省兜底）
    # ------------------------------------------------------------------
    def _alchemy_cfg(self) -> Mapping[str, Any]:
        """settings.alchemy 段归一（缺省 {}）。"""
        alchemy = self._settings.get("alchemy")
        return alchemy if isinstance(alchemy, Mapping) else {}

    def _max_qty(self) -> int:
        """数量上限（拍板⑤：settings.alchemy.max_qty 缺省 2147483647）。"""
        v = _as_int(self._alchemy_cfg().get("max_qty"))
        return v if v is not None and v > 0 else DEFAULT_MAX_QTY

    def _synth_exp(self) -> Optional[int]:
        """合成熟练经验倍率（CASC-01「可配」；settings.alchemy.synth_exp
        数值或 '配方等级×1' 字符串）。

        缺省 = None → 配方等级×1（细化 2c4a CASC-01 基准；test_demo 配 '配方等级×1'）。
        """
        raw = self._alchemy_cfg().get("synth_exp")
        if isinstance(raw, str):
            # '配方等级×1' 字面量 → None（按 1.0 处理）；可配数值放 _synth_exp_mult 解析
            s = raw.replace(" ", "")
            if s in ("配方等级×1", "配方等级*1", "配方等级×1.0"):
                return None
            v = _as_int(s)
            if v is not None:
                return v
            return None
        v = _as_int(raw)
        return v if v is not None and v > 0 else None

    # ------------------------------------------------------------------
    # 守卫（GU-01~03：mode ≠ off → 配方存在 + 职业达标 → synth_allowed）
    # ------------------------------------------------------------------
    def check_eligible(self, ctx: MutableMapping[str, Any], recipe_id: object) -> dict:
        """`/合成` 前置守卫（GU-01~03，细化_2c4a LAY-01/CASC-02/CASC-04/JOB-03）。

        入参：ctx（玩家表示 + 配方/物品注册表 + settings 已注入构造器）、
          recipe_id（配方名/id/序号）。
        校验链（GU-01→GU-02→GU-03）：
          1) GU-01：settings.alchemy.mode ≠ off（缺省 full，LAY-06）。
          2) GU-02：配方存在（resolve_recipe）+ 任一制造/资源职业区间达标——遍历
             player["proficiency"] 已解锁职业调 prof.recipe_level_eligible；
             多职业同时达标取等级最高者
             （EXP-03 工程补白 3）；无任何职业达标 → 拒「等级不足」提示缺哪种职业（TC-01/02）。
          3) GU-03：synth_allowed 判定（CASC-04）——false → 拒「深度未解锁」（TC-07）；true 且
             master_only → 放行 + 提示「此深度配方可被合成，将绕过深度炼金玩法」不阻断（TC-08/09）。
        出参：{ok, recipe, recipe_level, job_id, synth_allowed, hint?, reason?, message?}；
          拒绝 {ok:False, reason, message, ...}。
        """
        # GU-01 模块三态（LAY-06）
        mode = str(self._alchemy_cfg().get("mode", _MODE_FULL) or _MODE_FULL)
        if mode == _MODE_OFF:
            return {"ok": False, "reason": "mode_off", "message": "❌ 炼金系统已关闭",
                    "recipe": None, "recipe_level": None, "job_id": None}
        # GU-02a 配方存在（P-01 名称优先 → 序号兜底）
        recipe = resolve_recipe(ctx, recipe_id)
        if recipe is None:
            return {"ok": False, "reason": "recipe_not_found", "message": "❌ 配方不存在",
                    "recipe": None, "recipe_level": None, "job_id": None}
        recipe_level = recipe.get("level")
        if isinstance(recipe_level, bool) or not isinstance(recipe_level, int) or recipe_level <= 0:
            # 工程补白 12：配方等级非正整数 → 保守拒绝（对齐 prof recipe_level_eligible 补白 6）
            return {"ok": False, "reason": "level_insufficient",
                    "message": "❌ 等级不足：配方等级非法",
                    "recipe": recipe, "recipe_level": None, "job_id": None}
        # GU-02b 任一制造/资源职业区间达标（LAY-01/CASC-02/JOB-03；TC-01/02）
        player_prof = ctx.get("proficiency")
        if not isinstance(player_prof, MutableMapping) or not player_prof:
            return {"ok": False, "reason": "level_insufficient",
                    "message": "❌ 等级不足：未习得任何制造/资源职业",
                    "recipe": recipe, "recipe_level": recipe_level, "job_id": None}
        candidates: List[tuple] = []
        for job_id, node in player_prof.items():
            if not isinstance(node, Mapping):
                continue
            candidates.append((job_id, _as_int(node.get("level")) or 0))
        candidates.sort(key=lambda t: t[1], reverse=True)  # 等级高者优先（EXP-03 工程补白 3）
        eligible = [jid for jid, _lv in candidates
                    if self._prof.recipe_level_eligible(ctx, jid, recipe_level)]
        if not eligible:
            best_id, best_lv = candidates[0]
            return {"ok": False, "reason": "level_insufficient",
                    "message": f"❌ 等级不足：{_job_name(best_id, ctx)}（职业等级 {best_lv}）不足，"
                               f"需要配方等级 {recipe_level}",
                    "recipe": recipe, "recipe_level": recipe_level, "job_id": best_id}
        job_id = eligible[0]
        # GU-03 synth_allowed（CASC-04 / TC-07/08/09）
        master_only = recipe.get("master_only") is True
        synth_allowed = bool(recipe.get("synth_allowed", not master_only))  # 工程补白 5
        if not synth_allowed:
            return {"ok": False, "reason": "synth_not_allowed",
                    "message": "❌ 深度未解锁：该配方为深度配方，不可通过合成获取",
                    "recipe": recipe, "recipe_level": recipe_level, "job_id": job_id}
        hint = None
        if master_only and synth_allowed:
            hint = "提示：此深度配方可被合成，将绕过深度炼金玩法"  # CASC-04 提示不阻断
        return {"ok": True, "recipe": recipe, "recipe_level": recipe_level,
                "job_id": job_id, "synth_allowed": synth_allowed, "hint": hint,
                "reason": None, "message": None}

    # ------------------------------------------------------------------
    # 原子校验 / 差异提示（GU-04 / ATO-01 / TC-23）
    # ------------------------------------------------------------------
    def _material_shortfall(
        self, ctx: MutableMapping[str, Any], recipe: Mapping[str, Any], n: int,
    ) -> Optional[dict]:
        """材料×n + cost 金币/宝石×n 全量差额；全满足 → None；
        否则 {items:[(名称, 缺额)], coins, gem}。

        材料按配方序（materials[{id,count}]）；货币 coins → gem（工程补白 7）。
        """
        short: dict = {"items": [], "coins": 0, "gem": 0}
        found = False
        materials = recipe.get("materials")
        if isinstance(materials, list):
            for m in materials:
                mid = m.get("id") if isinstance(m, Mapping) else None
                cnt = m.get("count") if isinstance(m, Mapping) else None
                if not isinstance(mid, str) or not mid:
                    continue
                need = (_as_int(cnt) or 0) * n
                if need <= 0:
                    continue
                have = _count_item(ctx, mid)
                if have < need:
                    short["items"].append((_item_name(mid, ctx), need - have))
                    found = True
        cost = recipe.get("cost")
        if isinstance(cost, Mapping):
            currencies = ctx.get("currencies")
            for key, attr in (("coins", "coins"), ("gem", "gem")):
                need = (_as_int(cost.get(key)) or 0) * n
                if need <= 0:
                    continue
                have = int(currencies.get(key, 0)) if isinstance(currencies, Mapping) else 0
                if have < need:
                    short[attr] = need - have
                    found = True
        return short if found else None

    @staticmethod
    def _format_shortfall(short: Mapping[str, Any]) -> str:
        """差异提示文案：「缺 水结晶×5 + 金币 30」（TC-23；材料×缺额 + 金币 缺额 + 宝石 缺额）。"""
        parts: List[str] = []
        for name, deficit in short.get("items", []):
            parts.append(f"{name}×{deficit}")
        if short.get("coins"):
            parts.append(f"金币 {short['coins']}")
        if short.get("gem"):
            parts.append(f"宝石 {short['gem']}")
        return " + ".join(parts)

    def _format_consume(self, ctx: Mapping[str, Any], recipe: Mapping[str, Any], n: int) -> str:
        """成功消息消耗段：「水结晶×20 + 草药×10 + 金币 100」（M-01）。"""
        parts: List[str] = []
        materials = recipe.get("materials")
        if isinstance(materials, list):
            for m in materials:
                mid = m.get("id") if isinstance(m, Mapping) else None
                cnt = m.get("count") if isinstance(m, Mapping) else None
                if isinstance(mid, str) and mid:
                    total = (_as_int(cnt) or 0) * n
                    if total > 0:
                        parts.append(f"{_item_name(mid, ctx)}×{total}")
        cost = recipe.get("cost")
        if isinstance(cost, Mapping):
            for key, label in (("coins", "金币"), ("gem", "宝石")):
                total = (_as_int(cost.get(key)) or 0) * n
                if total > 0:
                    parts.append(f"{label} {total}")
        return " + ".join(parts)

    # ------------------------------------------------------------------
    # 标准版产出（LAY-04a）
    # ------------------------------------------------------------------
    def standard_output(self, recipe: Mapping[str, Any],
                        ctx: Optional[Mapping[str, Any]] = None) -> dict:
        """标准版产出描述（LAY-04a/TC-15）：品质固定（标准）、无特性/超特性/进化/核心类。

        入参：recipe（配方 dict）；ctx 可选（解析成品名/base_effects；缺省跳过）。
        出参：{ok, item_id, item_name, count, quality_fixed, quality, traits, awaken, evolution,
          core, base_effects?, desc}。
        """
        raw_out = recipe.get("output")
        out: Mapping[str, Any] = raw_out if isinstance(raw_out, Mapping) else {}
        out_item = out.get("item")
        item_id = out_item if isinstance(out_item, str) else None
        out_count = _as_int(out.get("count"))
        count = out_count if out_count and out_count > 0 else 1
        item_name = _item_name(item_id, ctx) if (item_id and ctx is not None) else (item_id or "?")
        base_effects = None
        if item_id and ctx is not None:
            items = ctx.get("items")
            if isinstance(items, Mapping):
                hit = items.get(item_id)
                if isinstance(hit, Mapping):
                    be = hit.get("base_effects")
                    if isinstance(be, (list, tuple)):
                        base_effects = list(be)
        return {
            "ok": True,
            "item_id": item_id,
            "item_name": item_name,
            "count": count,
            "quality_fixed": True,
            "quality": "标准",
            "traits": [],
            "awaken": None,
            "evolution": None,
            "core": None,
            "base_effects": base_effects,
            "desc": "标准版：品质固定（标准）、无特性/超特性/进化/核心类；标准珠固定 base_effects"
                    "（LAY-04a）",
        }

    # ------------------------------------------------------------------
    # 主入口（F-01 流程：守卫 → 数量归一 → 原子校验 → 事务内扣料产标准版 →
    #         熟练经验 → 图鉴 → 不耗能量）
    # ------------------------------------------------------------------
    def synthesize(
        self,
        ctx: MutableMapping[str, Any],
        recipe_id: object,
        count: object = 1,
        *,
        on_codex: Optional[Callable[[MutableMapping[str, Any], str, int], Any]] = None,
    ) -> dict:
        """`/合成 <配方>*<数量>` 主入口（F-01/TC-01/07/08/09/15/16/23）。

        入参：
          - ctx：玩家表示（就地改写 proficiency/currencies/inventory）。
          - recipe_id：配方名/id/序号。
          - count：数量（缺省 1；int≥1；超 max_qty → 提示「最多一次使用 N 个」
            不拦、按上限截断，拍板⑤）。
          - on_codex：合成图鉴点亮回调 on_codex(player, recipe_id, count)，默认 None 跳过
            （工程补白 10；返回值忽略、异常吞掉）。
        流程（F-01）：check_eligible → 数量归一 → 原子校验（GU-04，缺材料/金币全拒+差异提示）→
          事务内扣材料+金币 → 产标准版（LAY-04a，直接 add_item）→ 熟练经验=配方等级×成品数×1 入账
          （CASC-01/EXP-03，source='craft'）→ 合成图鉴点亮（on_codex）→ 不耗能量（LAY-05）。
        出参：{ok, message, produced, exp_gained, job_id, advisory?, hint?, cost_paid?, ...}；
          拒绝 {ok:False, reason, message, produced:None, exp_gained:0}。
        """
        chk = self.check_eligible(ctx, recipe_id)
        if not chk.get("ok"):
            return {**chk, "produced": None, "exp_gained": 0, "advisory": None}
        recipe = chk["recipe"]
        recipe_level = int(chk["recipe_level"])
        job_id = chk["job_id"]

        # 数量归一 + 数量上限（拍板⑤/ATO-07：超限提示不拦、按上限截断，对齐 shop D-05/TC-03）
        n = _as_int(count)
        if n is None or n < 1:
            return {"ok": False, "reason": "invalid_count", "message": "❌ 数量无效",
                    "produced": None, "exp_gained": 0, "advisory": None}
        cap = self._max_qty()
        advisory = None
        if n > cap:
            advisory = f"最多一次使用 {cap} 个"
            n = cap

        # 货币桶检查（cost>0 时必须存在，工程补白 7 / 对齐 shop 校验链⑤）
        cost = recipe.get("cost") if isinstance(recipe.get("cost"), Mapping) else {}
        need_coins = (_as_int(cost.get("coins")) or 0) * n
        need_gem = (_as_int(cost.get("gem")) or 0) * n
        if (need_coins or need_gem) and not isinstance(ctx.get("currencies"), MutableMapping):
            return {"ok": False, "reason": "missing_bucket", "message": "❌ 无法结算货币",
                    "produced": None, "exp_gained": 0, "advisory": advisory}

        # 原子校验（GU-04/ATO-01：材料+金币全量满足才执行，否则全拒+差异提示）
        short = self._material_shortfall(ctx, recipe, n)
        if short is not None:
            diff = self._format_shortfall(short)
            return {"ok": False, "reason": "materials",
                    "message": f"❌ 材料不足：缺 {diff}",
                    "produced": None, "exp_gained": 0, "advisory": advisory,
                    "shortfall": short}

        # 入包通道检查（否则扣料无落点，原子性破坏前拒绝）
        if not callable(ctx.get("add_item")) and not isinstance(
            ctx.get("inventory"), MutableMapping
        ):
            return {"ok": False, "reason": "storage_missing",
                    "message": "❌ 无法入包（背包通道缺失）",
                    "produced": None, "exp_gained": 0, "advisory": advisory}

        # ---- 事务内：扣材料+金币 → 产标准版（快照-回滚，工程补白 7 / ATO-02 单事务语义）----
        snap = _snapshot(ctx)
        try:
            materials = recipe.get("materials")
            if isinstance(materials, list):
                for m in materials:
                    mid = m.get("id") if isinstance(m, Mapping) else None
                    cnt = m.get("count") if isinstance(m, Mapping) else None
                    if isinstance(mid, str) and mid:
                        total = (_as_int(cnt) or 0) * n
                        if total > 0 and not _remove_item(ctx, mid, total):
                            raise _Rollback("material_remove_failed")
            currencies = ctx.get("currencies")
            if not isinstance(currencies, MutableMapping):
                # 理论不可达：cost>0 时已由桶检查拒绝；仅收窄类型（mypy）
                raise _Rollback("missing_currency")
            if need_coins:
                currencies["coins"] = int(currencies.get("coins", 0)) - need_coins
            if need_gem:
                currencies["gem"] = int(currencies.get("gem", 0)) - need_gem
            output = recipe.get("output")
            if not isinstance(output, Mapping) or not isinstance(output.get("item"), str):
                raise _Rollback("no_output")
            out_item = output["item"]
            out_count = _as_int(output.get("count"))
            out_total = (out_count if out_count and out_count > 0 else 1) * n
            # 标准版入包（LAY-04a/TC-15：品质固定无特性，直接 add_item；
            # bound 默认 False，工程补白 9）
            if not _add_item(ctx, out_item, out_total, bound=False):
                raise _Rollback("item_add_failed")
        except _Rollback as exc:
            _restore(ctx, snap)
            return {"ok": False, "reason": exc.reason, "message": "❌ 结算失败，已回滚",
                    "produced": None, "exp_gained": 0, "advisory": advisory}

        # 熟练经验 = 配方等级 × 成品数 × 1（CASC-01/EXP-03；synth_exp 可配，工程补白 8）
        exp_gained = 0
        exp_mult = self._synth_exp()
        exp_amount = recipe_level * out_total * (exp_mult if exp_mult is not None else 1)
        prof_result = self._prof.gain_prof_exp(ctx, job_id, exp_amount, source="craft")
        if prof_result.get("ok"):
            exp_gained = int(prof_result.get("exp_gained", 0))

        # 合成图鉴点亮（注入回调可选，默认 None 跳过；异常吞掉不阻断结算，工程补白 10）
        if callable(on_codex):
            try:
                on_codex(ctx, str(recipe_id), n)
            except Exception:
                pass

        # 消息合成（M-01：✅ 魔力药水 ×10（消耗：…）；advisory/深度提示追加，拍板⑤/CASC-04）
        out_name = _item_name(out_item, ctx)
        consume = self._format_consume(ctx, recipe, n)
        msg = f"✅ {out_name} ×{out_total}（消耗：{consume}）"
        if advisory:
            msg += f"；{advisory}"
        hint = chk.get("hint")
        if hint:
            msg += f"\n{hint}"

        return {
            "ok": True,
            "message": msg,
            "produced": {"item_id": out_item, "name": out_name, "count": out_total},
            "exp_gained": exp_gained,
            "job_id": job_id,
            "recipe_id": recipe_id,
            "advisory": advisory,
            "hint": hint,
            "cost_paid": {"coins": need_coins, "gem": need_gem},
            "idempotent": False,
        }
