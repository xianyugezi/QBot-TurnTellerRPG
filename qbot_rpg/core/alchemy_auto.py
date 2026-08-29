"""一键投料自动配平 + 批量引擎（M8 批4·路2）——配平/原子拒绝/平均品质/数量上限提示。

文件：qbot_rpg/core/alchemy_auto.py
创建：2026-08-29
作者：Hermes 子agent-2（路2）
功能：M8 炼金一键投料与单批量纯函数引擎——一键投料触发（AUTO-01：固定子词 自动，指令壳解析）、
      自动配平（AUTO-02：优先 element_req 达标组合、其次配方基础材料）、配平失败原子拒绝
      （AUTO-03：全拒 + 差异「缺 火药×1」，不部分入料）、批量平均品质（BATCH-02：复用
      QualitySystem.aggregate_quality/batch_tier 均值口径，丢特性由会话/指令层处理）、
      数量上限超限提示不拦截（BATCH-04 拍板⑤：默认 2147483647，超限标记由指令壳截断）、
      配平/复核差异（plan_shortfall：原子口径对齐 TC-11/TC-13）。

依据：
  - docs/细化/细化_2c4f_投料触媒与能量条.md 1.2（AUTO-01~03）/ 1.3（BATCH-01~05）/
    五（TC-10~14）
  - docs/m8_contract_核心机制.md 6.2（AUTO-01~03）/ 6.3（BATCH-01~05）
  - 批0 落地数据 content/test_demo/recipe.json（materials [{id,count}...] / element_req
    {元素: [{threshold, effect}]}）、items.json（elements {元素: 贡献值}）、settings.json
    alchemy 段（max_qty）
  - 模式参考 qbot_rpg/core/quality.py（QualitySystem 复用：aggregate_quality/batch_tier）；
    qbot_rpg/core/shop.py（ctx hook：count_item / items 注册表 / resolve_item）

【工程补白 · 显式标注】（定稿未给口径处，本引擎最小必要推导，不得新增定稿外机制行为）：
  A-1  配平优先级精确算法（AUTO-02）：① element_req 达标组合——以「每元素缺口」为目标
       （need = element_req 各元素阈值最大值，多阈值渐进效果取最高阈值即全达标），候选 = 背包
       持有且带 elements 贡献的物品，贪心「按缺口最大元素优先、同贡献按 item_id 升序（确定性）
       取材料，每次取 min(剩余持有, 补齐该缺口所需数量)」，全部缺口归零 = 达标；② 若元素缺口
       无法全达标（含无 element_req 配方）→ 回落配方基础材料（recipe.materials 逐项校验）。
  A-2  材料持有封顶规则：配平计划任何条目数量 ≤ 背包持有（count_item 逐项校验）；
       element_req 阶段贪心天然不超持有；基础材料阶段 held < 需求 → 记差异并全拒（AUTO-03，
       不部分入料）。
  A-3  plan 形态 = [(item_id, count)] 有序元组列表（确定性排序）；差异条目 = {item, name,
       need}；消息模板「缺 火药×1」（多条目以「 + 」连接，对齐 L115 同款口径）。
  A-4  数量上限（BATCH-04）：默认 2147483647（拍板⑤，覆盖【分隔符】L33 ≤99 默认）；引擎侧
       check_quantity 只标记 over_limit + 提示「最多一次使用 N 个」，不拦截、不截断——截断由
       指令壳/调用方按配置口径执行（TC-14「执行或按配置上限截断，以内容包配置为准」）。
  A-5  batch_quality 空投料防御：material_scores 空/全非法 → 复用 QualitySystem 空列表
       aggregate 返回 0、档位 common（基础调合 100% 成功不吞材料，QLT-06 口径）。

铁律：零 NoneBot import；纯函数（同刻同参必同值）；count_item/items 经 ctx 注入；工程补白
      显式标注；不抛异常（配置缺省兜底、方法防御降级）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from qbot_rpg.core.quality import QualitySystem

__all__ = [
    "DEFAULT_MAX_QTY",
    "AutoFeed",
]

# 数量上限默认（BATCH-04 拍板⑤：int32 max 2147483647，覆盖【分隔符】L33 ≤99 默认）
DEFAULT_MAX_QTY: int = 2147483647


class AutoFeed:
    """一键投料自动配平 + 批量引擎（AUTO-01~03 / BATCH-02/04）。

    构造器配置注入（settings / quality_system）+ 缺省默认值兜底；背包持有经 ctx["count_item"]
    hook 或 ctx["inventory"] 读取（对齐 shop 模式），物品注册表经 ctx["items"] /
    ctx["resolve_item"]；纯函数零 IO 零 NoneBot，不抛异常。供批4B 指令壳
    /炼金 <配方> 自动 与批量 /炼金 <配方>*<N> 消费。
    """

    def __init__(
        self,
        settings: Optional[Mapping[str, Any]] = None,
        quality_system: Optional[QualitySystem] = None,
    ) -> None:
        """构造自动配平引擎（配置注入 + 缺省默认值兜底）。

        - settings：settings dict（取 alchemy 段 max_qty）；None → 默认上限。
        - quality_system：品质引擎（BATCH-02 平均品质复用）；None → 默认 QualitySystem()。
        """
        self._settings: Mapping[str, Any] = settings if isinstance(settings, Mapping) else {}
        alchemy = self._settings.get("alchemy")
        self._alchemy: Mapping[str, Any] = alchemy if isinstance(alchemy, Mapping) else {}
        self._quality = (
            quality_system if isinstance(quality_system, QualitySystem) else QualitySystem()
        )
        try:
            mq = int(self._alchemy.get("max_qty", DEFAULT_MAX_QTY) or DEFAULT_MAX_QTY)
        except (TypeError, ValueError):
            mq = DEFAULT_MAX_QTY
        self._max_qty = mq if mq >= 1 else DEFAULT_MAX_QTY

    # ------------------------------------------------------------------
    # ctx 访问工具（对齐 shop.py：count_item hook / inventory / items / resolve_item）
    # ------------------------------------------------------------------
    @staticmethod
    def _count_item(ctx: Mapping[str, Any], item_id: str) -> int:
        """背包持有数：ctx["count_item"](id) hook 优先，其次 ctx["inventory"]；缺省 0。"""
        fn = ctx.get("count_item")
        if callable(fn):
            try:
                v = fn(item_id)
            except Exception:
                v = None
            if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                return v
            return 0
        inv = ctx.get("inventory")
        if isinstance(inv, Mapping):
            v = inv.get(item_id)
            if isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                return v
        return 0

    @staticmethod
    def _resolve_item(ctx: Mapping[str, Any], item_id: str) -> Optional[Mapping[str, Any]]:
        """物品注册表解析：ctx["items"] dict 或 ctx["resolve_item"] 解析器；查无 → None。"""
        items = ctx.get("items")
        if isinstance(items, Mapping):
            hit = items.get(item_id)
            if isinstance(hit, Mapping):
                return hit
        resolver = ctx.get("resolve_item")
        if callable(resolver):
            try:
                hit = resolver(item_id)
            except Exception:
                hit = None
            if isinstance(hit, Mapping):
                return hit
        return None

    @classmethod
    def _item_name(cls, ctx: Mapping[str, Any], item_id: str) -> str:
        """物品中文名（items.name 优先，缺省原 id）。"""
        item = cls._resolve_item(ctx, item_id)
        if item is not None:
            name = item.get("name")
            if isinstance(name, str) and name:
                return name
        return item_id

    # ------------------------------------------------------------------
    # 输入归一（recipe.materials / recipe.element_req）
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_materials(materials: Any) -> List[Tuple[str, int]]:
        """recipe.materials → [(item_id, count)...]：{id,count} 或 str（count=1）。"""
        out: List[Tuple[str, int]] = []
        if isinstance(materials, (list, tuple)):
            for m in materials:
                if isinstance(m, str) and m:
                    out.append((m, 1))
                elif isinstance(m, Mapping):
                    mid = m.get("id")
                    if isinstance(mid, str) and mid:
                        cnt = m.get("count", 1)
                        try:
                            ci = int(cnt)
                        except (TypeError, ValueError):
                            ci = 1
                        out.append((mid, max(1, ci)))
        return out

    @staticmethod
    def _normalize_element_req(element_req: Any) -> List[Tuple[str, int]]:
        """recipe.element_req → [(元素, 需求值)...]：需求值 = 阈值列表最大值（A-1 全达标口径）。"""
        out: List[Tuple[str, int]] = []
        if not isinstance(element_req, Mapping):
            return out
        for elem, spec in element_req.items():
            need = 0
            if isinstance(spec, (list, tuple)) and spec:
                threshs: List[int] = []
                for t in spec:
                    if isinstance(t, Mapping):
                        tv = t.get("threshold")
                        if tv is not None:
                            try:
                                threshs.append(int(tv))
                            except (TypeError, ValueError):
                                pass
                if threshs:
                    need = max(threshs)
            elif isinstance(spec, (int, str, float)) and not isinstance(spec, bool):
                try:
                    need = int(spec)
                except (TypeError, ValueError):
                    need = 0
            if need > 0:
                out.append((str(elem), need))
        return out

    # ------------------------------------------------------------------
    # 自动配平（AUTO-02/03，工程补白 A-1/A-2/A-3）
    # ------------------------------------------------------------------
    def _plan_element_combo(
        self, ctx: Mapping[str, Any], element_req: List[Tuple[str, int]],
        *, job_tier_index: Optional[int] = None
    ) -> Tuple[List[Tuple[str, int]], bool]:
        """element_req 达标组合贪心（A-1）：按元素缺口选材料。

        入参：ctx（背包/注册表）；element_req 归一后的 [(元素, 需求值)...]；
             job_tier_index（M8 批13 审查收口 P1-A：非专家 <3 时候选仅限 type=material，
             排除成品/装备——否则配平结果被 apply_feed expert_required 拒，UX 断裂）。
        出参：(plan, ok)；ok=True 表示全部元素缺口已归零（达标）。
        核心：候选 = 持有 >0 且带 elements 贡献的物品；贪心「缺口最大元素优先、同贡献按
              item_id 升序」，每次取 min(剩余持有, 补齐缺口所需)；计划数量 ≤ 持有（A-2 封顶）。
        """
        needs: Dict[str, int] = {elem: need for elem, need in element_req}
        candidates: List[Tuple[str, int, Dict[str, int]]] = []
        items = ctx.get("items")
        ids: List[str] = []
        if isinstance(items, Mapping):
            ids = [k for k in items if isinstance(k, str)]
        else:
            raw_ids = ctx.get("item_ids")
            if isinstance(raw_ids, (list, tuple)):
                ids = [k for k in raw_ids if isinstance(k, str)]
        # M8 批13 审查收口（P1-A）：专家门槛=档位索引 3（settings 职业等级口径 0-6，
        # 对齐 ProficiencyEngine tier 索引；无需查配置——专家固定第 4 档，定稿 2c4a CASC-07）
        non_expert = job_tier_index is not None and int(job_tier_index) < 3
        for item_id in ids:
            held = self._count_item(ctx, item_id)
            if held <= 0:
                continue
            item = self._resolve_item(ctx, item_id)
            if not isinstance(item, Mapping):
                continue
            # P1-A：非专家候选仅限材料（type=material）——成品/装备带 elements 也排除
            if non_expert and str(item.get("type") or "material") != "material":
                continue
            elems = item.get("elements")
            if not isinstance(elems, Mapping):
                continue
            contrib: Dict[str, int] = {}
            for k, v in elems.items():
                if str(k) in needs:
                    try:
                        cv = int(v)
                    except (TypeError, ValueError):
                        cv = 0
                    if cv > 0:
                        contrib[str(k)] = cv
            if contrib:
                candidates.append((item_id, held, contrib))

        if not candidates:
            return [], False

        remaining: Dict[str, int] = {cid: held for cid, held, _ in candidates}
        plan_counts: Dict[str, int] = {}
        progress = True
        while progress and any(n > 0 for n in needs.values()):
            progress = False
            # 缺口最大元素优先（确定性排序；needs 就地递减，快照序稳定）
            for elem, _need in sorted(needs.items(), key=lambda kv: -kv[1]):
                if needs[elem] <= 0:
                    continue
                pool = sorted(
                    (c for c in candidates if c[2].get(elem, 0) > 0 and remaining[c[0]] > 0),
                    key=lambda c: (-c[2][elem], c[0]),
                )
                for cid, _held, contrib in pool:
                    if needs[elem] <= 0:
                        break
                    take = min(remaining[cid], (needs[elem] + contrib[elem] - 1) // contrib[elem])
                    plan_counts[cid] = plan_counts.get(cid, 0) + take
                    remaining[cid] -= take
                    needs[elem] = max(0, needs[elem] - take * contrib[elem])
                    progress = True

        if any(n > 0 for n in needs.values()):
            return [], False
        plan = [(cid, plan_counts[cid]) for cid in sorted(plan_counts)]
        return plan, True

    def _plan_base_materials(
        self, ctx: Mapping[str, Any], materials: List[Tuple[str, int]]
    ) -> Tuple[List[Tuple[str, int]], List[dict]]:
        """配方基础材料配平（AUTO-02 其次）：逐项校验持有，不足记差异（A-2/A-3）。"""
        plan: List[Tuple[str, int]] = []
        shortfall: List[dict] = []
        for item_id, need in materials:
            held = self._count_item(ctx, item_id)
            if held < need:
                shortfall.append(
                    {
                        "item": item_id,
                        "name": self._item_name(ctx, item_id),
                        "need": need - held,
                    }
                )
                continue
            plan.append((item_id, need))
        return plan, shortfall

    @staticmethod
    def format_shortfall(shortfall: Any) -> str:
        """差异条目 → 提示串（A-3）：「缺 火药×1」（多条目以「 + 」连接，L115 同款口径）。"""
        if not shortfall:
            return ""
        parts: List[str] = []
        for s in shortfall:
            if isinstance(s, Mapping):
                name = s.get("name") or s.get("item") or "?"
                try:
                    need = int(s.get("need", 0) or 0)
                except (TypeError, ValueError):
                    need = 0
                parts.append(f"缺 {name}×{need}")
        return " + ".join(parts)

    def balance(self, ctx: Mapping[str, Any], recipe_def: Any,
                *, job_tier_index: Optional[int] = None) -> dict:
        """一键投料自动配平（AUTO-02/03）——纯逻辑，不扣背包（扣减由指令壳结算层执行）。

        入参：
          - ctx：玩家上下文（count_item / inventory / items / resolve_item / settings）。
          - recipe_def：配方定义 dict（materials [{id,count}...] / element_req
            {元素: [{threshold, effect}]}）。
          - job_tier_index：职业档位索引（M8 批13 审查收口 P1-A：非专家（<3）时配平
            候选仅限 type=material，排除成品/装备——否则一键投料配出成品随后被
            apply_feed「expert_required」拒绝，UX 断裂）。
        出参：
          - 成功：{ok:True, plan:[(item_id, count)...], mode:"element_req"|"materials",
            shortfall:[]}——plan 数量按持有封顶（A-2）。
          - 配平失败（AUTO-03）：{ok:False, reason:"shortfall", plan:None, mode:"materials",
            shortfall:[{item,name,need}...], message:"缺 火药×1"}——全拒 + 差异，不部分入料。
          - recipe 非法：{ok:False, reason:"invalid_recipe", shortfall:[]}。
        核心：① 优先 element_req 达标组合（贪心按元素缺口选材料，A-1）；达标 → 返回。
              ② 否则回落配方基础材料逐项校验（A-2）；任一不足 → 全拒原子拒绝（AUTO-03）。
              ③ 专家门槛：job_tier_index 非 None 且 < expert（3）时候选过滤 type=material。
        """
        if not isinstance(recipe_def, Mapping):
            return {"ok": False, "reason": "invalid_recipe", "shortfall": []}
        materials = self._normalize_materials(recipe_def.get("materials"))
        element_req = self._normalize_element_req(recipe_def.get("element_req"))

        # ① AUTO-02 优先：element_req 达标组合
        if element_req:
            plan, ok = self._plan_element_combo(ctx, element_req, job_tier_index=job_tier_index)
            if ok and plan:
                return {"ok": True, "plan": plan, "mode": "element_req", "shortfall": []}

        # ② AUTO-02 其次：配方基础材料（材料本身 type=material，天然过专家门槛）
        plan, shortfall = self._plan_base_materials(ctx, materials)
        if shortfall:
            return {
                "ok": False,
                "reason": "shortfall",
                "plan": None,
                "mode": "materials",
                "shortfall": shortfall,
                "message": self.format_shortfall(shortfall),
            }
        return {"ok": True, "plan": plan, "mode": "materials", "shortfall": []}

    def plan_shortfall(self, plan: Any, ctx: Mapping[str, Any]) -> dict:
        """配平/复核差异提示（AUTO-03 / FEED-10 / TC-11/TC-13 原子口径）。

        入参：plan = [(item_id, count)...] 或 [{"item"|"id", "count"}...]；
              ctx 玩家上下文（count_item 逐项校验当前持有）。
        出参：{ok, shortfall:[{item,name,need}...], message}；ok=False 时 shortfall 非空。
        核心：对计划每项按当前持有校验，缺量记差异（A-3）——用于 /确认 全量复核（防过期
              快照，FEED-10）与批量原子校验（BATCH-05 口径对齐）。
        """
        entries: List[dict] = []
        for p in plan or []:
            if isinstance(p, Mapping):
                mid = p.get("item") or p.get("id")
                try:
                    cnt = int(p.get("count", 1) or 1)
                except (TypeError, ValueError):
                    cnt = 1
            else:
                try:
                    mid, cnt = p[0], int(p[1])
                except (TypeError, IndexError, ValueError):
                    continue
            if not isinstance(mid, str) or not mid:
                continue
            held = self._count_item(ctx, mid)
            if held < cnt:
                entries.append(
                    {"item": mid, "name": self._item_name(ctx, mid), "need": cnt - held}
                )
        if entries:
            return {"ok": False, "shortfall": entries, "message": self.format_shortfall(entries)}
        return {"ok": True, "shortfall": [], "message": None}

    # ------------------------------------------------------------------
    # 批量（BATCH-02/04）
    # ------------------------------------------------------------------
    def batch_quality(self, material_scores: Any, quality: Optional[QualitySystem] = None) -> dict:
        """批量平均品质（BATCH-02）：复用 QualitySystem.aggregate_quality/batch_tier 均值口径。

        入参：material_scores 各材料品质分（Sequence[int]，空/非法元素剔除，A-5 防御）；
              quality 可注入品质引擎（缺省用构造注入）。
        出参：{score, tier}——score=均值四舍五入 int，tier=落档键（丢特性由会话/指令层处理，
              本引擎零特性接触）。
        """
        qs = quality if isinstance(quality, QualitySystem) else self._quality
        scores: List[int] = []
        for s in material_scores or []:
            if isinstance(s, int) and not isinstance(s, bool):
                scores.append(s)
        return {"score": qs.aggregate_quality(scores), "tier": qs.batch_tier(scores)}

    def check_quantity(self, count: Any, *, max_qty: Any = None) -> dict:
        """批量数量上限（BATCH-04 拍板⑤）：超限只提示不拦截（截断由指令壳/调用方）。

        入参：count 请求数量；max_qty 覆盖上限（缺省 settings.alchemy.max_qty，
              再缺省 2147483647）。
        出参：{ok:True（恒不拦截）, count, max_qty, over_limit, message}；
              over_limit=True 时 message="最多一次使用 N 个"（TC-14 只提示不拦截口径）。
        """
        try:
            n = int(count)
        except (TypeError, ValueError):
            n = 0
        if n < 0:
            n = 0
        cap = self._max_qty if max_qty is None else max_qty
        try:
            ci = int(cap)
        except (TypeError, ValueError):
            ci = self._max_qty
        if ci < 1:
            ci = self._max_qty
        over = n > ci
        return {
            "ok": True,  # BATCH-04：不拦截、不截断
            "count": n,
            "max_qty": ci,
            "over_limit": bool(over),
            "message": f"最多一次使用 {ci} 个" if over else None,
        }
