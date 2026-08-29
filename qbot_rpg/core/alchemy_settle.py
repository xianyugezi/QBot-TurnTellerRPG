"""炼金 /确认 品质结算引擎（M8 批5·路2）——全量复核/品质聚合+系数/上限叠加/刻度降级/触媒消耗/
产出入包/熟练经验/终态幂等 + /放弃。

文件：qbot_rpg/core/alchemy_settle.py
创建：2026-08-29
作者：Hermes 子agent-5-2（并发同仓：仅新建本文件 + tests/unit/test_alchemy_settle.py；
      兄弟路 1 在写 core/trait_inherit.py + 改 commands/alchemy_commands.py，本文件零 import 之，
      只读勿探查）

功能描述：SettleEngine —— /确认（F-05）与 /放弃（F-05）品质结算核心（纯逻辑零 IO 零 NoneBot，
  经 ctx hook 就地改写背包/产出，存储与事务由壳层完成）。承载 9 步结算管线：
  ① 全量复核（GU-19/FEED-10：材料链+触媒在背包，不足全拒+差异「缺 X×N」，防过期快照）→
  ② 品质聚合（QLT-06：投料材料品质分均值四舍五入）→ ③ 品质上限叠加（QLT-08：SP 品质上限
  +10×N + 核心/挑战可配 extra_cap，≤100）→ ④ 刻度未达标降级（QLT-10：check_element_req 差
  N 档降 N 档，最低普通封底不吞材料）→ ⑤ 档位+系数（QLT-02/04：score_to_tier + effect_value
  只放大数值）→ ⑥ 触媒消耗（CAT-04：catalyst_consume=true 扣 1 个，同事务）→ ⑦ 产出入包
  （成品 add_item，quality=tier 键 + traits 从快照写入 ItemInstance）→ ⑧ 熟练经验=配方等级×1
  （CASC-01/EXP-03，source='craft'）→ ⑨ 终态幂等（message_id 时封装 session_mgr.settle_alchemy
  (qid, mid, 'confirm', view)，§10 铁律 3 调用方不得嵌套 repo.tx()）。

依据：
  - docs/m8_contract_指令契约.md §5（/确认 GU-19/F-05/M-05；重复确认「已结算」）、§10 铁律 3
    （终态幂等 command="settle:{kind}"，调用方不得嵌套 repo.tx()）
  - docs/m8_contract_核心机制.md §四（QLT-06 均值/QLT-08 上限叠加 ≤100/QLT-10 未达标降级最低普通
    不吞材料/QLT-04 档位系数只放大数值）、§六 6.3（BATCH 原子性）、§7.2（version 幂等/终态结算
    模式）、§10.3（catalyst_consume 默认 true）
  - docs/细化/细化_2c4f_投料触媒与能量条.md CAT-04（触媒消耗默认 true，/确认 同事务扣减）、
    BATCH-05（全量才执行否则全拒+差异）
  - docs/细化/细化_2c4e_品质与特性.md 五（TC-02/03/05/08/09/15/20）
  - 已落地：core/alchemy_core.py（AlchemyCore.verify_snapshot/check_element_req/_find_*）、
    core/quality.py（QualitySystem.aggregate_quality/score_to_tier/cap_quality/degrade_quality/
    coef_for/effect_value）、core/proficiency.py（ProficiencyEngine.unlock_count/gain_prof_exp）、
    world/session.py（SessionManager.settle_alchemy 幂等）
  - 模式参考：core/reward.py（ctx hook：count_item/remove_item/add_item 就地操作）、
    core/quality.py（构造注入+缺省默认值兜底）

【工程补白 · 显式标注】（定稿/细化未给口径处，本引擎最小必要推导，不得新增定稿外行为）：
  Q-S1  材料品质分默认值：items 无 quality 字段的材料按 0 分兜底（对齐 quality.aggregate_quality
        空投料 0 分口径 Q-1；保守不凭空加分）。
  Q-S2  材料品质分 tier 键口径：items.quality 为档位键（common/uncommon/rare/legendary）时，
        取档位区间中点 (lo+hi)//2 折算数值分（全物入料成品带 tier 键品质的折算口径）。
  Q-S3  聚合输入口径：品质均值按材料链每条记录计 1 份（TC-02「投 3 份材料 70/70/80」），
        不按 count 加权；材料链为空 → aggregate_quality([])=0。
  Q-S4  未达标降级档数口径（QLT-10）：每元素 levels_missing 全量求和（check_element_req 输出
        差 N 档语义；单元素多档阶梯求和，TC-09「刻度差 2 档降 2 档」）。
  Q-S5  品质上限 hard_max 口径（QLT-08）：配方 quality_cap 字段（可配，缺省 100=品质分绝对上限）；
        extra_cap 只放宽可达上限，仍 ≤100（quality.cap_quality Q-2 忠实语义）。
  Q-S6  档位系数语义（QLT-04）：系数只放大成品效果数值（effect_value），不改品质分本体——
        指令契约 F-05「品质=材料品质×档位系数」为叙述简写，以核心机制 QLT-04「只放大效果数值」
        为准（与 M-05「品质 72·史诗」一致：72 为材料均值，史诗=档位名，拍板②）。
  Q-S7  终态幂等 gate 时序（§10 铁律 3 / ATO-04）：settle_alchemy 作为幂等 gate 置于全量复核
        **之前**——重复确认（材料已消耗/会话已删）必返回「已结算」而非「材料不足」（ATO-04 /
        M-05 重复确认语义）；首次返回 True 后继续复核+业务写。业务写与终态落键
        （delete_session+write_idem_key）的单事务原子性由批6B 壳层编排（调用方不得嵌套 repo.tx()）。
  Q-S8  扣料口径：材料按 item_id 去重汇总后逐项 remove_item（verify 已保证足量）；触媒消耗时序 =
        复核通过 →（幂等 gate 已过）→ 扣触媒 → 扣材料 → 产出入包 → 熟练（同事务）。
  Q-S9  traits 读取：鸭子类型读快照 snap["traits"]（兄弟路 trait_inherit 写入口径；list/tuple
        归一为 str 列表，缺失/非法 → []，标准版无特性恒空，LAY-04a）。
  Q-S10 成品效果数值放大（QLT-04）：对配方 output 物品 base_effects 中数值叶递归 ×coef
        （只放大数值不改效果结构）；输出物 effects 结构原样保留。

铁律：零 NoneBot import；纯函数（同刻同参必同值，ctx 只读注册表 + 经 hook 就地改写背包）；
      不抛异常（防御降级返回 dict）；每条规则注释标注出处（QLT/GU/F/CAT/EXP 编号 + 定稿/细化
      行号）；不得新增定稿外机制行为。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Mapping, MutableMapping, Optional

from qbot_rpg.core.alchemy_core import ALCHEMY_JOB_ID, AlchemyCore
from qbot_rpg.core.quality import ABSOLUTE_QUALITY_MAX, QualitySystem

if TYPE_CHECKING:  # 仅类型注解（proficiency 已落地，保持零运行时耦合）
    from qbot_rpg.core.proficiency import ProficiencyEngine

__all__ = [
    "SETTLE_CONFIRM",
    "SETTLE_ABANDON",
    "SP_QUALITY_CAP_10",
    "DEFAULT_CATALYST_CONSUME",
    "SettleEngine",
]

# 终态结算类型（并入幂等键 command="settle:{kind}"，§10 铁律 3 / ATO-04）
SETTLE_CONFIRM: str = "confirm"    # /确认 品质结算
SETTLE_ABANDON: str = "abandon"    # /放弃 会话退出终态

# SP 面板「品质上限+10」项 id（test_demo proficiency.json sp_panel[0]；QLT-08①）
SP_QUALITY_CAP_10: str = "quality_cap_10"

# 触媒消耗默认（CAT-04：每次调合确认结算消耗触媒 1 个；settings.alchemy.catalyst_consume 可配）
DEFAULT_CATALYST_CONSUME: bool = True


class SettleEngine:
    """炼金 /确认 /放弃 品质结算引擎（F-05，纯逻辑零 IO 零 NoneBot）。

    构造器配置注入（quality 品质引擎 + prof 熟练引擎 + settings）+ 缺省默认值兜底
    （对齐 quality.py / levelup.py 模式）。纯函数：同刻同参必同值；ctx 只读注册表
    （items/traits/recipe/count_item），背包/产出经 ctx 的 remove_item/add_item hook 就地
    改写（对齐 reward.py 模式），存储与事务由壳层完成。
    """

    def __init__(
        self,
        quality: Optional[QualitySystem] = None,
        prof: Optional["ProficiencyEngine"] = None,
        settings: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """构造结算引擎（配置注入 + 缺省默认值兜底）。

        入参：
          - quality：QualitySystem 实例（可选注入；缺省默认四档模板兜底）。
          - prof：ProficiencyEngine 实例（可选注入；用于 SP 品质上限计数与熟练经验入账，
            缺省不注入则两处均跳过——纯结算路径）。
          - settings：settings dict（读 alchemy.catalyst_consume / recipe 等）；None → 默认。
        """
        self._quality: QualitySystem = (
            quality if isinstance(quality, QualitySystem) else QualitySystem()
        )
        self._prof: Optional["ProficiencyEngine"] = prof
        self._settings: Mapping[str, Any] = settings if isinstance(settings, Mapping) else {}
        # 复核/刻度复用 AlchemyCore（verify_snapshot/check_element_req/_find_*，批4A 已落地）
        self._core = AlchemyCore(prof=prof, settings=self._settings)

    # ------------------------------------------------------------------
    # 配置读取（缺省默认值兜底）
    # ------------------------------------------------------------------
    def _alchemy_settings(self) -> Mapping[str, Any]:
        """settings.alchemy 段（缺省空 Mapping，调用方各自兜底）。"""
        alch = self._settings.get("alchemy")
        return alch if isinstance(alch, Mapping) else {}

    def _catalyst_consume(self) -> bool:
        """触媒是否消耗（CAT-04：settings.alchemy.catalyst_consume，默认 true）。"""
        v = self._alchemy_settings().get("catalyst_consume", DEFAULT_CATALYST_CONSUME)
        return bool(v)

    # ------------------------------------------------------------------
    # 注册表查找（复用 AlchemyCore._find_*，鸭子同一 ctx 口径）
    # ------------------------------------------------------------------
    def _find_item(self, key: Any, ctx: Mapping[str, Any]) -> Optional[dict]:
        """按 id 或 name 查 items.json def（ctx["items"] 注册表 / ctx["resolve_item"]）。"""
        return self._core._find_item(key, ctx)  # noqa: SLF001  # 复用同层引擎私有查找

    def _find_recipe(self, key: Any, ctx: Mapping[str, Any]) -> Optional[dict]:
        """按 id 查 recipe.json def（ctx["recipe"] 注册表 / ctx["resolve_recipe"]）。"""
        return self._core._find_recipe(key, ctx)  # noqa: SLF001

    # ------------------------------------------------------------------
    # 材料品质分（QLT-06 聚合输入；Q-S1/Q-S2）
    # ------------------------------------------------------------------
    def quality_of(self, item_def: Any) -> int:
        """材料品质分读取（QLT-06 聚合输入口径）。

        入参：item_def（items.json def 或快照材料记录，均含 .get("quality")）。
        出参：品质分 int（0-100 口径）。
        核心逻辑：
          - quality 为 int → 直接裁剪到 [0,100]；
          - quality 为档位键（common/uncommon/rare/legendary）→ 档位区间中点 (lo+hi)//2
            【工程补白 Q-S2】；
          - 无 quality 字段 / 非法 → 0【工程补白 Q-S1：无 quality 材料按 0 分兜底，
            对齐 quality.aggregate_quality 空投料 0 分口径】。
        """
        if not isinstance(item_def, Mapping):
            return 0
        q = item_def.get("quality")
        if isinstance(q, bool) or q is None:
            return 0
        if isinstance(q, int):
            return max(0, min(ABSOLUTE_QUALITY_MAX, q))
        if isinstance(q, str) and q:
            rng = self._quality.tiers.get(q)
            if rng is not None:
                return (int(rng[0]) + int(rng[1])) // 2  # Q-S2 档位中点
        return 0

    def _material_scores(self, ctx: Mapping[str, Any], snap: Mapping[str, Any]) -> List[int]:
        """材料链品质分列表（QLT-06 聚合输入；Q-S3 每记录 1 份，不按 count 加权）。

        记录自带 quality（快照冗余）优先，缺省回落 items def 查询（快照形态对齐
        alchemy_core._resolve_material 的 quality 字段）。
        """
        scores: List[int] = []
        for rec in snap.get("materials") or []:
            if not isinstance(rec, Mapping):
                continue
            if "quality" in rec:
                scores.append(self.quality_of(rec))
            else:
                idef = self._find_item(rec.get("item"), ctx)
                scores.append(self.quality_of(idef))
        return scores

    # ------------------------------------------------------------------
    # 品质上限叠加（QLT-08；Q-S5）
    # ------------------------------------------------------------------
    def _extra_cap(self, ctx: Mapping[str, Any], snap: Mapping[str, Any]) -> int:
        """品质上限三处叠加（QLT-08，TC-05）。

        ① SP「品质上限+10」（可多次）：prof.unlock_count(player, alchemy, "quality_cap_10")×10；
        ② 核心镶嵌「品质上限+X」（大师）：快照 core_cap / extra_cap 字段；
        ③ 挑战成功「品质上限+10」（可配）：快照 challenge_cap 字段。
        只放宽可达上限，品质分仍 ≤100（cap_quality Q-2 忠实语义）。
        """
        extra = 0
        prof = self._prof
        if prof is not None and callable(getattr(prof, "unlock_count", None)):
            player = ctx.get("player")
            try:
                n = max(0, int(prof.unlock_count(player, ALCHEMY_JOB_ID, SP_QUALITY_CAP_10)))
            except Exception:
                n = 0
            extra += n * 10  # QLT-08①
        for key in ("extra_cap", "core_cap", "challenge_cap"):
            v = snap.get(key)
            if isinstance(v, bool) or v is None:
                continue
            try:
                extra += max(0, int(v))  # QLT-08②③
            except (TypeError, ValueError):
                pass
        return extra

    @staticmethod
    def _recipe_hard_max(recipe: Mapping[str, Any]) -> int:
        """配方原品质上限（QLT-08；Q-S5）：recipe.quality_cap 可配，缺省 100。"""
        v = recipe.get("quality_cap")
        if isinstance(v, bool) or v is None:
            return ABSOLUTE_QUALITY_MAX
        try:
            n = int(v)
            return n if n >= 0 else ABSOLUTE_QUALITY_MAX
        except (TypeError, ValueError):
            return ABSOLUTE_QUALITY_MAX

    # ------------------------------------------------------------------
    # 触媒 / 快照 traits 读取（鸭子类型；Q-S9）
    # ------------------------------------------------------------------
    def _catalyst_id(self, snap: Mapping[str, Any], ctx: Mapping[str, Any]) -> Optional[str]:
        """快照触媒 → 物品 id（CAT-04 扣减用）。

        快照 catalyst 为 Mapping（def）→ id/item；为 str（名或 ID）→ 查注册表取 id
        （type=触媒 校验，非法/未注册回落原串——verify_snapshot 已保证持有）。
        """
        catalyst = snap.get("catalyst")
        if isinstance(catalyst, Mapping):
            return catalyst.get("id") or catalyst.get("item")
        if isinstance(catalyst, str) and catalyst:
            idef = self._find_item(catalyst, ctx)
            if idef is not None and idef.get("type") == "触媒":
                return str(idef.get("id") or catalyst)
            return catalyst
        return None

    @staticmethod
    def _snap_traits(snap: Mapping[str, Any]) -> List[str]:
        """快照继承特性读取（Q-S9 鸭子类型读 snap["traits"]）。

        list/tuple → 归一 str 列表；dict（{ids|traits: [...]}）防御兼容；缺失/非法 → []。
        """
        raw = snap.get("traits")
        if isinstance(raw, (list, tuple)):
            return [str(t) for t in raw if t]
        if isinstance(raw, Mapping):
            ids = raw.get("ids") or raw.get("traits") or []
            if isinstance(ids, (list, tuple)):
                return [str(t) for t in ids if t]
        return []

    # ------------------------------------------------------------------
    # ctx hook 调用（对齐 reward.py 模式；Q-S8）
    # ------------------------------------------------------------------
    @staticmethod
    def _hook_ok(result: Any) -> bool:
        """ctx hook 返回值成功判定（False → 失败；Mapping 取 ok 键；None/True → 成功）。"""
        if result is False:
            return False
        if isinstance(result, Mapping):
            return bool(result.get("ok", True))
        return True

    def _consume_materials(self, ctx: Mapping[str, Any], snap: Mapping[str, Any]) -> bool:
        """扣材料（Q-S8：按 item_id 去重汇总逐项 remove_item；verify 已保证足量）。

        remove_item hook 缺失 → False（引擎不静默跳过扣料——原子防双扣）。
        """
        remove_item = ctx.get("remove_item")
        if not callable(remove_item):
            return False
        need: Dict[str, int] = {}
        for rec in snap.get("materials") or []:
            if not isinstance(rec, Mapping):
                continue
            iid = rec.get("item")
            if not isinstance(iid, str) or not iid:
                continue
            try:
                need[iid] = need.get(iid, 0) + max(1, int(rec.get("count", 1)))
            except (TypeError, ValueError):
                need[iid] = need.get(iid, 0) + 1
        for iid, cnt in need.items():
            if not self._hook_ok(remove_item(iid, cnt)):
                return False
        return True

    @staticmethod
    def _scale_effects(effects: Any, coef: float) -> Any:
        """成品效果数值放大（QLT-04 只放大数值不改效果结构；Q-S10）。

        对 base_effects 中数值叶递归 ×coef；字符串（效果 ID）/结构原样保留。
        """
        if isinstance(effects, Mapping):
            return {str(k): SettleEngine._scale_effects(v, coef) for k, v in effects.items()}
        if isinstance(effects, (list, tuple)):
            return [SettleEngine._scale_effects(v, coef) for v in effects]
        if isinstance(effects, (int, float)) and not isinstance(effects, bool):
            return float(effects) * coef
        return effects

    def _produce(
        self,
        ctx: Mapping[str, Any],
        recipe: Mapping[str, Any],
        snap: Mapping[str, Any],
        tier: str,
        coef: float,
    ) -> Optional[dict]:
        """产出入包（F-05 ⑦ / STO-01）。

        ctx["add_item"](item_id, count, bound=True, quality=tier, traits=tuple(traits))
        由壳层实现为构造 ItemInstance（quality=tier 键 + traits 冻结元组）入包；返回
        {ok,...} 或 False。产出信息 {item_id, name, count, quality, tier, tier_label,
        traits, effects, scaled_effects}；add_item hook 缺失/失败 → None。
        """
        add_item = ctx.get("add_item")
        if not callable(add_item):
            return None
        out = recipe.get("output")
        if isinstance(out, Mapping):
            item_id = out.get("item") or recipe.get("id")
            count_raw = out.get("count", 1)
        else:
            item_id = recipe.get("id")
            count_raw = 1
        if not isinstance(item_id, str) or not item_id:
            return None
        try:
            count = max(1, int(count_raw))
        except (TypeError, ValueError):
            count = 1
        traits = self._snap_traits(snap)  # Q-S9：traits 从快照写入 ItemInstance
        result = add_item(item_id, count, True, quality=tier, traits=tuple(traits))
        if not self._hook_ok(result):
            return None
        idef = self._find_item(item_id, ctx)
        effects = idef.get("base_effects") if isinstance(idef, Mapping) else None
        scaled = self._scale_effects(effects, coef) if effects is not None else None
        name = str(idef.get("name") or item_id) if isinstance(idef, Mapping) else item_id
        return {
            "item_id": item_id,
            "name": name,
            "count": count,
            "quality": tier,
            "tier": tier,
            "tier_label": self._quality.tier_label(tier),
            "traits": traits,
            "effects": effects,
            "scaled_effects": scaled,
        }

    def _gain_exp(self, ctx: Mapping[str, Any], recipe: Mapping[str, Any]) -> int:
        """熟练经验入账（F-05 ⑧ / CASC-01 / EXP-03：熟练经验=配方等级×1，source='craft'）。

        prof 注入 + ctx["player"] 才生效；缺任一 → 0（由壳层另行入账）。
        """
        prof = self._prof
        if prof is None or not callable(getattr(prof, "gain_prof_exp", None)):
            return 0
        player = ctx.get("player")
        if not isinstance(player, MutableMapping):
            return 0
        try:
            level = max(0, int(recipe.get("level", 0)))
        except (TypeError, ValueError):
            level = 0
        result = prof.gain_prof_exp(player, ALCHEMY_JOB_ID, level, source="craft")
        if isinstance(result, Mapping) and result.get("ok"):
            try:
                return max(0, int(result.get("exp_gained", 0)))
            except (TypeError, ValueError):
                return 0
        return 0

    # ------------------------------------------------------------------
    # 终态幂等 gate（§10 铁律 3 / ATO-04；Q-S7）
    # ------------------------------------------------------------------
    @staticmethod
    def settle_key(kind: str) -> str:
        """终态幂等 command 键（command=f"settle:{kind}"，§10 铁律 3）。

        入参：kind（"confirm"/"abandon" 等）。出参："settle:<kind>"。
        """
        return f"settle:{kind}"

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    async def confirm(
        self,
        ctx: Mapping[str, Any],
        snap: Optional[Mapping[str, Any]],
        *,
        qid: str,
        job_tier_index: Any = None,
        message_id: Optional[str] = None,
        session_view: Any = None,
    ) -> dict:
        """F-05 /确认 品质结算主入口（9 步管线 + 终态幂等 gate）。

        入参：
          - ctx：结算上下文（items/recipe 注册表 + count_item/remove_item/add_item hook +
            player + session_mgr，就地改写背包）。
          - snap：调合会话快照（None → 无会话拒绝）。
          - qid：玩家 QQ 号（终态幂等键要素）。
          - job_tier_index：职业档位索引（记录进结果，批8 深度/挑战消费预留）。
          - message_id：QQ 消息 id（提供时走终态幂等 gate：session_mgr.settle_alchemy）。
          - session_view：会话视图（发起群 group_id 来源，settle_alchemy 透传）。
        出参：
          - 成功：{ok, message, produced:{item_id,name,count,quality,tier,traits,...},
            quality_score, tier, coef, exp_gained, degraded_levels, catalyst_consumed,
            settled, idempotent:False}。
          - 拒绝：{ok:False, reason, message}；已结算：{ok:False, reason:"already_settled",
            message:"已结算", idempotent:True}。
        核心逻辑（管线顺序）：终态幂等 gate（Q-S7 gate 在复核前，防重复确认「材料不足」误报）→
          ① 全量复核（GU-19）→ ② 品质聚合（QLT-06）→ ③ 上限叠加（QLT-08）→
          ④ 刻度降级（QLT-10）→ ⑤ 档位+系数（QLT-02/04）→ ⑥ 触媒消耗（CAT-04）→
          扣材料（Q-S8）→ ⑦ 产出入包（F-05）→ ⑧ 熟练经验（CASC-01）。
        """
        if not isinstance(ctx, Mapping):
            return {"ok": False, "reason": "invalid_ctx", "message": "结算上下文非法"}
        if not isinstance(snap, Mapping):
            # GU-17/无会话防御（状态机批3 已判定，此处引擎侧兜底，零抛异常）
            return {
                "ok": False,
                "reason": "no_snapshot",
                "message": "当前没有调合会话，先 /炼金 <配方> 开始",
            }
        # ⑨ 终态幂等 gate（Q-S7：重复确认/重投递 → 直接「已结算」零业务写）
        settled = False
        if message_id:
            sm = ctx.get("session_mgr")
            if sm is not None and callable(getattr(sm, "settle_alchemy", None)):
                ok_gate = await sm.settle_alchemy(
                    qid, str(message_id), SETTLE_CONFIRM, session_view
                )
                if not ok_gate:
                    return {
                        "ok": False,
                        "reason": "already_settled",
                        "message": "已结算",
                        "idempotent": True,
                    }
                settled = True
            # message_id 给了但无 session_mgr → 跳过终态落键（由壳层负责，防御）

        # ① 全量复核（GU-19/FEED-10：材料链+触媒仍在背包，不足全拒+差异，防过期快照）
        verify = self._core.verify_snapshot(ctx, snap)
        if not verify.get("ok"):
            return {
                "ok": False,
                "reason": verify.get("reason", "materials_insufficient"),
                "message": verify.get("message", "材料不足，无法确认"),
                "shortfall": list(verify.get("shortfall") or []),
            }
        recipe = self._find_recipe(snap.get("recipe_id"), ctx)
        if recipe is None:
            return {"ok": False, "reason": "recipe_not_found", "message": "配方不存在"}

        # ② 品质聚合（QLT-06：材料品质均值四舍五入，TC-02）
        mean = self._quality.aggregate_quality(self._material_scores(ctx, snap))

        # ③ 品质上限叠加（QLT-08：SP×10 + 核心/挑战 extra_cap，≤100，TC-05）
        extra_cap = self._extra_cap(ctx, snap)
        capped = self._quality.cap_quality(
            mean, extra_cap=extra_cap, hard_max=self._recipe_hard_max(recipe)
        )

        # ④ 刻度未达标降级（QLT-10：check_element_req 差 N 档降 N 档，最低普通封底，TC-08/09）
        element_scores = snap.get("element_scores")
        element_scores = element_scores if isinstance(element_scores, Mapping) else {}
        req_status = self._core.check_element_req(recipe, element_scores)
        levels_missing = 0
        for st in req_status.values():
            try:
                levels_missing += max(0, int(st.get("levels_missing", 0)))
            except (TypeError, ValueError):
                pass
        degraded_levels = 0
        score = capped
        if levels_missing > 0:
            _, score = self._quality.degrade_quality(capped, levels_missing)
            degraded_levels = levels_missing

        # ⑤ 档位+系数（QLT-02/04：score_to_tier + coef 只放大数值，TC-03）
        tier = self._quality.score_to_tier(score)
        coef = self._quality.coef_for(tier)
        tier_label = self._quality.tier_label(tier)

        # ⑥ 触媒消耗（CAT-04：catalyst_consume=true 扣 1 个，同事务；false 不扣仅方向修饰）
        catalyst_id = self._catalyst_id(snap, ctx)
        catalyst_consumed = False
        if catalyst_id and self._catalyst_consume():
            remove_item = ctx.get("remove_item")
            if not callable(remove_item):
                return {
                "ok": False,
                "reason": "remove_item_hook_missing",
                "message": "缺少扣料 hook",
            }
            if not self._hook_ok(remove_item(catalyst_id, 1)):
                return {
                    "ok": False,
                    "reason": "catalyst_remove_failed",
                    "message": f"触媒 {catalyst_id} 扣除失败",
                }
            catalyst_consumed = True

        # 扣材料（Q-S8：按 item_id 去重汇总，verify 已保证足量）
        if not self._consume_materials(ctx, snap):
            return {"ok": False, "reason": "materials_remove_failed", "message": "材料扣除失败"}

        # ⑦ 产出入包（成品 add_item，quality=tier 键 + traits 从快照写入 ItemInstance）
        produced = self._produce(ctx, recipe, snap, tier, coef)
        if produced is None:
            return {"ok": False, "reason": "add_item_failed", "message": "成品入包失败"}

        # ⑧ 熟练经验=配方等级×1（CASC-01/EXP-03，source='craft'）
        exp_gained = self._gain_exp(ctx, recipe)

        name = produced["name"]
        return {
            "ok": True,
            "message": f"确认成功：{name}（品质 {score}·{tier_label}）",
            "produced": produced,
            "quality_score": score,
            "tier": tier,
            "tier_label": tier_label,
            "coef": coef,
            "degraded_levels": degraded_levels,
            "catalyst_consumed": catalyst_consumed,
            "exp_gained": exp_gained,
            "settled": settled,
            "idempotent": False,
        }

    async def abandon(
        self,
        ctx: Mapping[str, Any],
        snap: Optional[Mapping[str, Any]],
        *,
        qid: str,
        message_id: Optional[str] = None,
        session_view: Any = None,
    ) -> dict:
        """F-05 /放弃（补白 Q-A1）：材料不结算、会话退出终态。

        入参：ctx（本方法零背包改写——材料在 /确认 前始终留包，放弃不扣不还）；
          snap（会话快照，仅校验 ctx 合法兜底）；qid；message_id（可选，终态落键）；
          session_view（settle_alchemy 透传）。
        出参：{ok, message:"已放弃", settled, idempotent:False}；
          重复放弃：{ok:False, reason:"already_settled", message:"已放弃", idempotent:True}。
        核心逻辑：材料不结算（F-05：不扣料不产入——投料仅记录材料链，/确认 才消耗）→
          终态结算 settle_alchemy 'abandon'（delete_session+write_idem_key，§10 铁律 3）。
        """
        if not isinstance(ctx, Mapping):
            return {"ok": False, "reason": "invalid_ctx", "message": "结算上下文非法"}
        settled = False
        if message_id:
            sm = ctx.get("session_mgr")
            if sm is not None and callable(getattr(sm, "settle_alchemy", None)):
                ok_gate = await sm.settle_alchemy(
                    qid, str(message_id), SETTLE_ABANDON, session_view
                )
                if not ok_gate:
                    return {
                        "ok": False,
                        "reason": "already_settled",
                        "message": "已放弃",
                        "idempotent": True,
                    }
                settled = True
            # message_id 给了但无 session_mgr → 跳过终态落键（由壳层负责，防御）
        return {"ok": True, "message": "已放弃", "settled": settled, "idempotent": False}
