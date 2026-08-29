"""炼金图鉴成长 + 教学目录 + 技能面板引擎（qbot_rpg/core/alchemy_meta.py · M8 批8-1 · 路B）。

文件名：qbot_rpg/core/alchemy_meta.py
创建时间：2026-08-29
作者：Hermes 子agent-8B（M8 批8-1 路B）
功能描述：AlchemyMeta 承载 /图鉴（F-19/GU-58）、/技能面板（F-19/GU-58）、/教学（F-23/GU-64）
 与升大师公告（L482）的纯规则侧：图鉴进度/成长奖励阶段判定/王称号条件（TTL-01）、
 SP 自选解锁透传（SP-02/04/05）、教学目录与机制教学、升大师 6 深度机制预览。
 操作对象 = ctx（图鉴 codex_state）+ player 状态 dict（SP/称号，经 ProficiencyEngine 就地改写）；
 返回 dict 结果、拒绝场景返回 {ok: False, reason: ...} 不抛异常；纯函数零 IO 零 NoneBot。

依据：
  - docs/m8_contract_指令契约.md §18 /图鉴 与 /技能面板（GU-58/F-19/M-19）、
    §22 /教学（GU-64/F-23/M-23）
  - docs/细化/细化_2c4d_炼金指令表.md §19（F-19 L210 点亮→成长奖励）、§23（F-23 教学/升大师 L482）、
    TC-11/TC-12/TC-13/TC-14/TC-16/TC-27/TC-31
  - docs/细化/细化_2c5a_职业等级与SP.md：TTL-01（王称号图鉴全亮、与等级解耦）、TTL-03（king 条目
    id=职业ID）、SP-01~08（每级 SP/自选解锁/双计）、§5.1 JSON 样例、§5.2 字段表
  - docs/审查参考/炼金系统设计定稿.md：§2.2 L63-75（SP 面板六类）、§2.3 L87-89（王称号）、
    §5.2#12 L210（图鉴成长：点亮 N 格→经验/新配方）、§十二 L480-485（新手引导/升大师公告）
  - qbot_rpg/core/codex.py（codex_progress/codex_state 图鉴点亮机制，接口已核实）
  - qbot_rpg/core/proficiency.py ProficiencyEngine（sp_available/sp_panel_defs/unlock_item/
    unlock_count/grant_king_title，接口已核实）
  - 模式参考 core/codex.py（codex_state 操作）、core/proficiency.py（构造器注入+dict 操作）

【工程补白 · 显式标注】（定稿/细化未显式定义处，全部按本清单落地）
  1) 图鉴类别与 codex_state 的对应：炼金图鉴独立分册 category="alchemy"，落
     ctx["codex_state"]["alchemy"]（与 codex.py 的 monster/weapon/item 三册并存、互不干扰）。
     分母 = registry kinds ("recipe","item")（配方+道具，对齐 F-19「各配方/道具点亮进度」；
     codex.py CATEGORIES 未含 alchemy → 本引擎自算，语义对齐 codex_progress：seen 仅计
     state 中 seen=true，total 仅计 registry 全量）。
  2) 成长奖励表配置键：settings.alchemy.codex_rewards = [{lit, exp, recipes}]（点亮 N 格 →
     经验/新配方，L210）；未配置 → 内置缺省表 _DEFAULT_CODEX_REWARDS（lit 5/10/15/20/25，
     exp 10/25/40/60/80，无配方——补白数值，内容包显式配 recipes 放开）。奖励按档位
     idempotent 结算（只领一次），已领档位记 codex_state[category]["_rewards"].claimed
     （复用 codex_state，零新存储；保留键 "_rewards" 不计入图鉴点亮数）。
  3) 教学文案表内置：tutorial_catalog/tutorial_show 读 settings.alchemy.tutorials =
     [{name, example, text}]（内容包可配，F-23 数据落点）；未配置 → 内置 _DEFAULT_TUTORIALS
     （覆盖基础炼金 + 大师 6 深度机制 + 宗师数项，M-23 示例文案同源）。
  4) 升大师 6 机制预览（L482）：6 深度机制 = 连锁奖励/核心镶嵌/分解回炉/量贩复制/图鉴成长/
     战斗即时调合（定稿 L59 大师行）；preview 取教学表 example（settings.alchemy.deep_mechanisms
     可配覆盖）；tier 索引 ≥4（大师，7 级默认 _DEFAULT_TIER_NAMES 第 5 项）→ 解锁公告。
  5) 王称号授予走 prof.grant_king_title（TTL-03：title_id=job_id 自动生成）；本引擎只做
     「图鉴全亮判定 + 透传」；prof 未注入 → engine_unavailable 拒绝（fail-safe，不越权）。

铁律：零 NoneBot import；纯函数（同刻同参必同值）；工程补白显式标注；不新增定稿外机制行为；
      只新建本文件，禁止改其它任何文件。
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional, Sequence, Tuple

from qbot_rpg.core.proficiency import ProficiencyEngine

__all__ = [
    "AlchemyMeta",
    "ALCHEMY_CATEGORY",
    "ALCHEMY_KINDS",
    "DEFAULT_TIER_NAMES",
]

# ---------------------------------------------------------------------------
# 常量与缺省默认值（工程补白 1/2/3/4）
# ---------------------------------------------------------------------------

# 炼金图鉴独立分册（补白 1：与 codex.py 三分册并存）
ALCHEMY_CATEGORY: str = "alchemy"

# 炼金图鉴分母 kinds（配方 + 道具，F-19「各配方/道具点亮进度」）
ALCHEMY_KINDS: Tuple[str, ...] = ("recipe", "item")

# codex_state 保留键（成长奖励已领档位，不计入图鉴点亮数，补白 2）
_RESERVED: str = "_rewards"

# 7 级称号默认名（升大师公告 tier 名渲染用；proficiency.json 可改名）
DEFAULT_TIER_NAMES: Tuple[str, ...] = ("见习", "正式", "精通", "专家", "大师", "宗师", "王")

# 大师 = 第 5 档（索引 4，7 级默认）
_MASTER_TIER_INDEX: int = 4

# 深度炼金 6 新机制（定稿 §2.3 大师行 L59，升大师公告 L482 预览）
_DEEP_MECHANISM_NAMES: Tuple[str, ...] = (
    "连锁奖励", "核心镶嵌", "分解回炉", "量贩复制", "图鉴成长", "战斗即时调合",
)

# 图鉴成长奖励内置缺省表（补白 2：定稿仅「点亮 N 格→经验/新配方」L210，无明细；数值为补白）
_DEFAULT_CODEX_REWARDS: Tuple[Mapping[str, Any], ...] = (
    {"lit": 5, "exp": 10, "recipes": ()},
    {"lit": 10, "exp": 25, "recipes": ()},
    {"lit": 15, "exp": 40, "recipes": ()},
    {"lit": 20, "exp": 60, "recipes": ()},
    {"lit": 25, "exp": 80, "recipes": ()},
)

# 教学文案表内置缺省（补白 3：覆盖基础 + 大师 6 深度 + 宗师数项；M-23 示例同源）
_DEFAULT_TUTORIALS: Tuple[Mapping[str, str], ...] = (
    {
        "name": "投料",
        "example": "投入材料 → 品质/连锁随投料策略变化，一键投料与单批量见深度面板",
        "text": ("炼金基础：投料决定成品品质与连锁段数。"
                 "连续同属性投料可叠连锁，品质随材料品质与策略提升。"),
    },
    {
        "name": "连锁奖励",
        "example": "连续投入同属性材料 ≥3 段触发连锁奖励，段数越高奖励效果等级越高",
        "text": ("链式投料达到 3 段及以上时触发连锁奖励，"
                 "段数映射效果等级上限（详见连锁映射表），零额外消耗。"),
    },
    {
        "name": "核心镶嵌",
        "example": "/镶核心 核心物品 → 品质上限+X/属性适配，可更换",
        "text": ("深度炼金：消耗核心物品嵌入，提升成品品质上限并适配属性；"
                 "可随时更换，核心消耗即生效。"),
    },
    {
        "name": "分解回炉",
        "example": "/分解 任意炼金成品 → 回收 40-60% 材料 + 产出宝石",
        "text": ("深度炼金：分解任意炼金成品回收 40-60% 材料（向下取整）并产出宝石，"
                 "是资源循环保底通道。"),
    },
    {
        "name": "量贩复制",
        "example": "先 /登记 配方 → /复制 批量量产标准版（无特性）",
        "text": "深度炼金：先 /登记 目标配方，再 /复制 消耗宝石+材料批量量产标准版成品。",
    },
    {
        "name": "图鉴成长",
        "example": "新条目自动点亮 → 点亮 N 格 → 经验/新配方成长奖励",
        "text": ("图鉴新条目自动点亮，点亮达到奖励档位即发放经验/新配方成长奖励；"
                 "图鉴全点亮 = 炼金王称号条件。"),
    },
    {
        "name": "战斗即时调合",
        "example": "战斗中 /即时调合 火焰弹 → 一步出结果，当场结算（限次可配）",
        "text": "深度炼金：战斗中无需会话，/即时调合 一步出结果当场结算；每场限次可配（默认 1）。",
    },
    {
        "name": "配方进化线",
        "example": "/进化 低阶配方炼金产出 N 次后解锁高阶，永久解锁",
        "text": ("宗师机制：低阶配方产出达 N 次（合成不计）可 /进化 解锁高阶配方，"
                 "继承槽位/投入次数/平均品质。"),
    },
    {
        "name": "挑战调合",
        "example": "/挑战 苛刻条件（连锁≥5 且刻度≥2，可配）→ 成功品质上限+10",
        "text": ("宗师机制：消耗双倍材料挑战苛刻条件；不满足 → 降级并退 50% 材料，"
                 "成功 → 品质上限+10（可配）。"),
    },
)


def _tutorial_entry(entry: Mapping[str, Any]) -> Mapping[str, str]:
    """教学条目归一：{name, example, text}（text 缺省 = example）。"""
    return {
        "name": str(entry.get("name") or ""),
        "example": str(entry.get("example") or ""),
        "text": str(entry.get("text") or entry.get("example") or ""),
    }


class AlchemyMeta:
    """图鉴成长 + 教学目录 + 技能面板引擎（F-19/F-23/GU-58/GU-64 · TTL-01/SP-02~05）。

    纯规则侧：图鉴进度读取（codex_state，对齐 codex.py codex_progress 语义）、成长奖励
    idempotent 结算、王称号全亮判定透传（proficiency.grant_king_title）、SP 面板查看与
    自选解锁透传（proficiency.sp_available/sp_panel_defs/unlock_item）、教学目录与机制教学、
    升大师公告。操作对象 = ctx + player dict，就地改写；拒绝返回 {ok: False, reason: ...}。
    """

    def __init__(
        self,
        prof: Optional[ProficiencyEngine] = None,
        settings: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """构造炼金图鉴/教学/技能面板引擎（配置注入，缺省默认值兜底）。

        入参：
          - prof：ProficiencyEngine 实例（SP 面板/王称号消费）；None → SP/称号接口
            返回 engine_unavailable（fail-safe，不越权）。
          - settings：settings dict；alchemy 段承载 codex_rewards / tutorials /
            deep_mechanisms（工程补白 2/3/4 配置键）；None → 内置缺省。
        """
        self._prof: Optional[ProficiencyEngine] = (
            prof if isinstance(prof, ProficiencyEngine) else None
        )
        self._settings: Mapping[str, Any] = settings if isinstance(settings, Mapping) else {}

    # ------------------------------------------------------------------
    # 工具：配置读取（缺省兜底）
    # ------------------------------------------------------------------
    def _alchemy_cfg(self) -> Mapping[str, Any]:
        """settings.alchemy 段（非 Mapping → 空 dict，兜底）。"""
        alchemy = self._settings.get("alchemy")
        return alchemy if isinstance(alchemy, Mapping) else {}

    def _reward_table(self) -> Sequence[Mapping[str, Any]]:
        """图鉴成长奖励表（补白 2：settings.alchemy.codex_rewards，未配 → 内置缺省；
        按 lit 升序）。"""
        cfg = self._alchemy_cfg().get("codex_rewards")
        if isinstance(cfg, (list, tuple)) and cfg:
            rows = [c for c in cfg if isinstance(c, Mapping) and c.get("lit") is not None]
            if rows:
                return sorted(rows, key=lambda r: int(r.get("lit", 0)))
        return _DEFAULT_CODEX_REWARDS

    def _tutorials(self) -> Sequence[Mapping[str, str]]:
        """教学文案表（补白 3：settings.alchemy.tutorials，未配 → 内置缺省）。"""
        cfg = self._alchemy_cfg().get("tutorials")
        if isinstance(cfg, (list, tuple)) and cfg:
            rows = [t for t in cfg if isinstance(t, Mapping) and t.get("name")]
            if rows:
                return [_tutorial_entry(r) for r in rows]
        return [_tutorial_entry(t) for t in _DEFAULT_TUTORIALS]

    def _deep_mechanisms(self) -> Sequence[Mapping[str, str]]:
        """升大师 6 深度机制预览（补白 4：settings.alchemy.deep_mechanisms 可配覆盖；
        未配 → 从教学表取 6 机制 example）。"""
        cfg = self._alchemy_cfg().get("deep_mechanisms")
        if isinstance(cfg, (list, tuple)) and cfg:
            out: list = []
            for m in cfg:
                if isinstance(m, Mapping) and m.get("name"):
                    out.append({"name": str(m["name"]),
                                "preview": str(m.get("preview") or "")})
            if out:
                return out
        table = {t["name"]: t for t in self._tutorials()}
        return [
            {"name": n, "preview": table.get(n, {}).get("example", "")}
            for n in _DEEP_MECHANISM_NAMES
        ]

    @staticmethod
    def _known_categories() -> Tuple[str, ...]:
        """已知分册 = 本引擎炼金分册 + codex.py 三分册（对齐 codex_progress 可查范围）。"""
        from qbot_rpg.core.codex import CATEGORIES  # 惰性 import（兄弟路已落地，只读）

        return (ALCHEMY_CATEGORY, *tuple(CATEGORIES))

    # ------------------------------------------------------------------
    # 图鉴进度（F-19 / GU-58，对齐 codex.py codex_progress 语义）
    # ------------------------------------------------------------------
    @staticmethod
    def _cat_of(ctx: Mapping[str, Any], category: str) -> Mapping[str, Any]:
        """分册 state（只读视图；缺失 → 空 dict）。"""
        st = ctx.get("codex_state")
        cat = st.get(category) if isinstance(st, Mapping) else None
        return cat if isinstance(cat, Mapping) else {}

    def _lit_of(self, ctx: Mapping[str, Any], category: str) -> int:
        """已点亮数（state 中 seen=true 且非保留键 _rewards 的条目数，语义对齐 codex_progress）。"""
        cat = self._cat_of(ctx, category)
        return sum(
            1
            for rid, e in cat.items()
            if rid != _RESERVED and isinstance(e, Mapping) and e.get("seen")
        )

    def _total_of(self, ctx: Mapping[str, Any], category: str) -> int:
        """图鉴分母（registry all_ids 全量；补白 1：alchemy 走 ("recipe","item") kinds；
        codex 已登记分册走 codex.CATEGORIES 映射；无 registry → 0，fail-safe）。"""
        reg: Any = ctx.get("registry")
        if reg is None or not hasattr(reg, "all_ids"):
            return 0
        from qbot_rpg.core.codex import CATEGORIES  # 惰性 import（对齐分册→kind 映射）

        kinds = CATEGORIES.get(category, ()) if category != ALCHEMY_CATEGORY else ALCHEMY_KINDS
        total = 0
        for kind in kinds:
            try:
                total += len(tuple(reg.all_ids(kind)))
            except Exception:
                continue
        return total

    def codex_summary(self, ctx: Mapping[str, Any], category: str = ALCHEMY_CATEGORY) -> dict:
        """图鉴进度（F-19 / GU-58）：{ok, category, lit, total, ratio, all_lit}。

        入参：ctx（codex_state/registry）；category：分册名（默认 alchemy 炼金图鉴）。
        出参 dict：lit 已点亮 / total 图鉴总条目 / ratio 完成度（未取整 0-1）/
          all_lit 全点亮（王称号条件 TTL-01）。未知分册 → {ok: False, reason: "unknown_category"}。
        核心逻辑：lit=state 中 seen 计数（保留键 _rewards 不计）；total=registry 分母；
          ratio=lit/total（total=0 → 0.0）；all_lit=total>0 且 lit≥total。
        """
        if category not in self._known_categories():
            return {"ok": False, "reason": "unknown_category", "category": category}
        lit = self._lit_of(ctx, category)
        total = self._total_of(ctx, category)
        ratio = (lit / total) if total else 0.0
        return {
            "ok": True,
            "category": category,
            "lit": lit,
            "total": total,
            "ratio": float(ratio),
            "all_lit": bool(total) and lit >= total,
        }

    # ------------------------------------------------------------------
    # 图鉴成长奖励（L210：点亮 N 格 → 经验/新配方）
    # ------------------------------------------------------------------
    def codex_reward(self, ctx: MutableMapping[str, Any], category: str = ALCHEMY_CATEGORY) -> dict:
        """图鉴成长奖励结算（F-19/L210，工程补白 2 奖励表配置键）。

        入参：ctx（可变，codex_state 就地记已领档位）；category：分册名。
        出参 dict: {ok, category, lit, total, granted, newly_claimed, reward:{exp, recipes}}；
          未知分册 → {ok: False, reason: "unknown_category"}。
        核心逻辑：对奖励表（按 lit 升序）逐档判定 lit≥档位 且未领 → 领取（exp 累加、recipes
          并集），记 codex_state[category]["_rewards"].claimed（保留键，零新存储，不计点亮数）；
          idempotent：重复调用已领档位不重发（D-07 幂等口径，TC-27）。
        """
        if category not in self._known_categories():
            return {"ok": False, "reason": "unknown_category", "category": category}
        summary = self.codex_summary(ctx, category)
        lit = summary["lit"]
        total = summary["total"]
        st = ctx.get("codex_state")
        if not isinstance(st, MutableMapping):
            st = {}
            ctx["codex_state"] = st
        cat = st.get(category)
        if not isinstance(cat, MutableMapping):
            cat = {}
            st[category] = cat
        raw = cat.get(_RESERVED)
        claimed_raw = raw.get("claimed") if isinstance(raw, Mapping) else None
        claimed: set = set()
        if isinstance(claimed_raw, (list, tuple)):
            for x in claimed_raw:
                try:
                    claimed.add(int(x))
                except (TypeError, ValueError):
                    continue
        newly: list = []
        exp = 0
        recipes: list = []
        for thr in self._reward_table():
            try:
                need = int(thr.get("lit", 0))
            except (TypeError, ValueError):
                continue
            if need <= 0 or need in claimed:
                continue
            if lit < need:
                continue
            claimed.add(need)
            newly.append(need)
            try:
                exp += int(thr.get("exp", 0))
            except (TypeError, ValueError):
                pass
            rs = thr.get("recipes")
            if isinstance(rs, (list, tuple)):
                recipes.extend(str(r) for r in rs)
        if newly:
            cat[_RESERVED] = {"claimed": sorted(claimed)}
        return {
            "ok": True,
            "category": category,
            "lit": lit,
            "total": total,
            "granted": bool(newly),
            "newly_claimed": newly,
            "reward": {"exp": exp, "recipes": recipes},
        }

    # ------------------------------------------------------------------
    # 王称号条件（TTL-01/03：图鉴全亮 → 授予，与等级解耦）
    # ------------------------------------------------------------------
    def king_eligible(
        self,
        player: MutableMapping[str, Any],
        ctx: Mapping[str, Any],
        job_id: str = ALCHEMY_CATEGORY,
    ) -> dict:
        """王称号授予判定（TTL-01/TC-11/TC-19/TC-20）：图鉴全亮 → prof.grant_king_title。

        入参：player（可变，title_state 就地改）、ctx（图鉴进度）、job_id（职业 ID，默认 alchemy）。
        出参 dict：{ok, granted, title_id, codex_all_lit}；图鉴未全亮 → {ok: False,
          reason: "codex_incomplete"}（等级到王区间也不授予，王条件与等级区间解耦，TC-11）；
          prof 未注入 → {ok: False, reason: "engine_unavailable"}。
        核心逻辑：codex_summary(category=job_id 对应炼金分册).all_lit → 透传
          prof.grant_king_title(player, job_id, codex_all_lit=...)；TTL-03 title_id=job_id。
        """
        summary = self.codex_summary(ctx, job_id)
        all_lit = bool(summary.get("all_lit"))
        if self._prof is None:
            return {"ok": False, "reason": "engine_unavailable", "codex_all_lit": all_lit}
        res = self._prof.grant_king_title(player, job_id, codex_all_lit=all_lit)
        out = dict(res)
        out["codex_all_lit"] = all_lit
        return out

    # ------------------------------------------------------------------
    # SP 技能面板（F-19 / SP-02~05，TC-12/13/14/16）
    # ------------------------------------------------------------------
    def skill_panel_view(self, player: Mapping[str, Any], job_id: str = ALCHEMY_CATEGORY) -> dict:
        """技能面板查看（F-19/M-19/TC-12）：SP 可用数 + 分支列表 + 已解锁次数。

        入参：player（读 proficiency.<job_id>）；job_id：职业 ID（默认 alchemy）。
        出参 dict：{ok, job_id, sp_available, items:[{id,name,cost,repeatable,max_repeat,desc,
          unlocked_count}], total_unlocked}；prof 未注入 → {ok: False,
          reason:"engine_unavailable"}。
        核心逻辑：sp_available=prof.sp_available（sp_earned-sp_used 双计）；分支=sp_panel_defs
          逐项附 unlock_count（未购买 = 0 → 不生效，TC-13 未购买不自动生效口径）。
        """
        if self._prof is None:
            return {"ok": False, "reason": "engine_unavailable", "job_id": job_id,
                    "sp_available": 0, "items": []}
        sp = self._prof.sp_available(player, job_id)
        items: list = []
        for d in self._prof.sp_panel_defs(job_id):
            cnt = self._prof.unlock_count(player, job_id, d["id"])
            items.append({**d, "unlocked_count": cnt})
        return {
            "ok": True,
            "job_id": job_id,
            "sp_available": sp,
            "items": items,
            "total_unlocked": sum(i["unlocked_count"] for i in items),
        }

    def skill_panel_unlock(
        self, player: MutableMapping[str, Any], job_id: str, panel_id: str
    ) -> dict:
        """SP 分支自选解锁（F-19/SP-04/05，TC-13/14/16）：prof.unlock_item 透传。

        入参：player（可变，sp_used/unlocks 就地改）、job_id、panel_id（sp_panel 项 id）。
        出参 dict：成功 {ok, message, sp_remaining, panel_id, unlock_count, sp_used_delta}；
          拒绝 {ok: False, reason, panel_id}（panel_not_found/sp_insufficient/not_repeatable/
          max_repeat_reached/invalid_player/engine_unavailable）。
        核心逻辑：prof.unlock_item 透传（SP-06 双计防重复扣点，TC-14）；成功后回读剩余 SP
          并组装 message（M-19 口径「已解锁「X」×N（剩余 SP Y）」）。
        """
        if self._prof is None:
            return {"ok": False, "reason": "engine_unavailable", "panel_id": panel_id}
        res = self._prof.unlock_item(player, job_id, panel_id)
        if not res.get("ok"):
            return {
                "ok": False,
                "reason": str(res.get("reason", "unknown")),
                "panel_id": panel_id,
            }
        remaining = self._prof.sp_available(player, job_id)
        name = str(res.get("panel_name") or panel_id)
        count = int(res.get("unlock_count", 1))
        message = f"已解锁「{name}」×{count}（剩余 SP {remaining}）"
        return {
            "ok": True,
            "message": message,
            "sp_remaining": remaining,
            "panel_id": panel_id,
            "unlock_count": count,
            "sp_used_delta": res.get("sp_used_delta"),
        }

    # ------------------------------------------------------------------
    # 教学目录 / 机制教学（F-23 / GU-64，M-23）
    # ------------------------------------------------------------------
    def tutorial_catalog(self) -> list:
        """教学目录（F-23/GU-64）：机制名 + 一句话示例列表。

        入参：无。出参：[{name, example}, ...]（教学文案表配置/内置缺省，补白 3）。
        """
        return [{"name": t["name"], "example": t["example"]} for t in self._tutorials()]

    def tutorial_show(self, mechanism_name: str) -> dict:
        """机制教学（F-23/M-23）：按名回看教学文案；未知名 → 教学目录。

        入参：mechanism_name（机制名，空 → 目录）。出参：{ok, name, example, text}；
          未知名 → {ok: False, reason: "unknown_mechanism", name, catalog}；
          空名 → {ok: False, reason: "empty_name", catalog}。
        """
        name = str(mechanism_name or "").strip()
        if not name:
            return {"ok": False, "reason": "empty_name", "catalog": self.tutorial_catalog()}
        for t in self._tutorials():
            if t["name"] == name:
                return {"ok": True, "name": name,
                        "example": t["example"], "text": t["text"]}
        return {"ok": False, "reason": "unknown_mechanism", "name": name,
                "catalog": self.tutorial_catalog()}

    # ------------------------------------------------------------------
    # 升大师公告（L482：6 深度机制一句话预览，tier ≥ 大师）
    # ------------------------------------------------------------------
    def master_announcement(self, job_tier_index: Any) -> dict:
        """升大师公告（L482/F-23）：6 深度机制一句话预览。

        入参：job_tier_index（职业档位索引 0~6，默认 7 级；≥4=大师解锁）。
        出参 dict：解锁 {ok: True, unlocked: True, tier_index, tier_name,
          mechanisms:[{name, preview}]}；未达大师 → {ok: False, reason:"not_master",
          unlocked: False, tier_index, tier_name, master_tier_index, mechanisms: []}。
        核心逻辑：tier 索引 ≥ _MASTER_TIER_INDEX(4) → 返回 6 深度机制预览（补白 4 配置键）；
          否则拒绝（不提前泄露深度内容）。
        """
        try:
            idx = int(job_tier_index)
        except (TypeError, ValueError):
            idx = 0
        idx = max(0, idx)
        tier_name = DEFAULT_TIER_NAMES[idx] if idx < len(DEFAULT_TIER_NAMES) else str(idx)
        if idx >= _MASTER_TIER_INDEX:
            return {
                "ok": True,
                "unlocked": True,
                "tier_index": idx,
                "tier_name": tier_name,
                "mechanisms": [dict(m) for m in self._deep_mechanisms()],
            }
        return {
            "ok": False,
            "reason": "not_master",
            "unlocked": False,
            "tier_index": idx,
            "tier_name": tier_name,
            "master_tier_index": _MASTER_TIER_INDEX,
            "mechanisms": [],
        }
