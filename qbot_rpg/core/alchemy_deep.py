"""深度炼金引擎（M8 批8-1·路A）——深度会话快照/进化条件+永久解锁/镶核心品质上限/加成限次/
挑战苛刻条件判定+降级退料。

文件名：qbot_rpg/core/alchemy_deep.py
创建时间：2026-08-29
作者：Hermes 子agent-8-1A（并发同仓：仅新建本文件 + tests/unit/test_alchemy_deep.py；
      兄弟路 8-1B 在写 core/alchemy_meta.py（图鉴/教学/技能面板），本文件零 import 之，只读勿探查）

功能描述：DeepEngine —— 深度炼金引擎（纯逻辑零 IO 零 NoneBot，构造器注入 settings: Optional[
  Mapping]=None、quality: Optional[QualitySystem]=None 兜底缺省）。承载批8 路8A 全部核心逻辑：
  - 深度会话快照（F-06/GU-20~22）：deep_snapshot 构造深度会话面板快照（配方ID/材料链/连锁/特性/
    触媒/PP/步骤/version + 深度专属 核心槽 core_slot/进化线 evolve_line/6 槽；challenge_alchemy
    会话类型）+ deep_eligible 大师解锁守卫（精通拒绝「深度未解锁」，TC-14）。
  - 进化（GU-23~25/F-07/CASC-05/ATO-05）：evolve_eligible 宗师门槛 + 低阶配方炼金产出 N 次
    （合成不计，produce_counts 由调用方传入 {recipe_id: 炼金产出次数}，多级链逐级计次）→
    {ok, count, need}；evolve_unlock 扣材料+宝石 → 永久解锁下一级配方（写 ctx["upgrade_unlocks"]
    对齐批2 UpgradeEngine，U-F2 同表）→ 已解锁幂等 ATO-05 → 返回「✅ 继承 2 额外槽（6 槽）」。
  - 镶核心（COR-01~03/GU-26~27/TC-16）：mount_core 深度会话中+大师 → 核心物品消耗入装 → 快照
    core_slot=核心 def（品质上限+X/属性适配，写快照 core_cap 对齐 SettleEngine._extra_cap②）→
    可换（旧核心按配置销毁/拆回，工程补白 COR-2A）→ 核心不匹配 →
    {ok:False, reason:"core_mismatch"}。
  - 加成（GU-28/F-08/QLT-09/TC-16）：buff 宗师+加成道具 限 1 次/调合（快照 buff_used 标记，已用
    → 拒绝「限 1 次」）→ 品质大幅提升/改属性（写快照 buff_bonus/buff_element，批6A 结算消费）。
  - 挑战（GU-47~49/F-16/ATO-06/TC-23）：challenge_check 苛刻条件判定——连锁≥5 且 刻度≥2
    （settings.alchemy.challenge 可配 且/或）→ {ok, met}；challenge_settle 满足 → 品质上限+10
    （快照 quality_cap_bonus/challenge_cap）；不满足 → 品质降级（degrade_quality）+ 退 50% 材料
    （按配方各退 50% 向下取整，只退一次 ATO-06，快照 challenge_refunded/challenge_settled 幂等）。

依据：
  - docs/m8_contract_指令契约.md §6（/深度炼金 GU-20~22/F-06/M-06/TC-14）、§7（/进化
    GU-23~25/F-07/M-07/CASC-05/ATO-05/TC-15）、§8（/镶核心 /加成 GU-26~28/F-08/M-08/TC-16）、
    §15（/挑战 GU-47~49/F-16/M-16/TC-23）、§四 MUT-07（深度/炼金会话类型分离）、§五 ATO-05/06。
  - docs/m8_contract_核心机制.md QLT-08（品质上限三处叠加：核心/挑战 extra_cap，SettleEngine
    _extra_cap 读快照 core_cap/challenge_cap）、QLT-09（加成道具：品质均值结算后施加，宗师限 1
    次/调合，例 贤者之石 品质+30）、CASC-05（进化计数防跳：合成不计）、CASC-07（指令门槛防跳）。
  - docs/m8_contract_数据与校验.md §一（recipe.json：master_only/evolve_to{id, condition:{count,
    source}}/slots/quality_cap/materials/cost{coins,gem}）、§2c4c COR-01~03（核心表并入 traits.json
    效果表，核心不匹配模板，核心可换）、REC-09/10（evolve_to 引用存在/进化线无环，校验器保证）。
  - docs/细化/细化_2c4d_炼金指令表.md §16（/挑战 F-16：苛刻条件连锁≥5 且刻度≥2 可配且/或、
    失败降级+退50%材料按配方各退50%向下取整、成功品质上限+10）、细化_2c4c §1.5（COR-01~03）。
  - 已落地：qbot_rpg/core/alchemy_core.py（AlchemyCore：new_snapshot 基础快照/compute_chain/
    compute_element_scores/check_element_req/_find_recipe，批4A）、qbot_rpg/core/quality.py
    （QualitySystem：cap_quality/degrade_quality，批1B）、qbot_rpg/core/alchemy_session.py
    （CHALLENGE_SESSION="challenge_alchemy" 会话类型，批3B）、qbot_rpg/core/alchemy_settle.py
    （SettleEngine._extra_cap 读快照 core_cap/challenge_cap，批5-2）、qbot_rpg/core/upgrade.py
    （UpgradeEngine ctx["upgrade_unlocks"] 玩家级解锁表 U-F2，批2B）。
  - 模式参考：qbot_rpg/core/alchemy_settle.py（构造注入+ctx hook：count_item/remove_item/add_item
    就地改写背包，纯逻辑零 IO）、qbot_rpg/core/reward.py（ctx hook 模式）、qbot_rpg/core/quality.py
    （构造器配置注入 + 缺省默认值兜底）。

【工程补白 · 显式标注】（定稿/细化未给口径处，本引擎最小必要推导，不得新增定稿外机制行为）：
  D-1  核心物品标记（COR-03：核心效果并入 traits.json 效果表，不另建核心表）：items.json 条目
       type=="核心" 即核心物品；品质上限 X = 条目 `core.cap_bonus`（或顶层 `cap_bonus`，int ≥0）；
       属性适配元素 = 条目 `element` 字段或 `elements` 主元素（复用 AlchemyCore._main_element）。
  D-2  核心适配判定（GU-27 与配方适配）：配方有 element_req 时，核心元素必须命中配方 element_req
       键集（不中 → 核心不匹配）；配方无 element_req 时任意核心放行（无约束）。无元素核心在配方
       有刻度要求时视为不匹配（无「属性适配」可言）。【最小必要推导：定稿仅言「与配方适配」未给
       判定口径】。
  D-3  旧核心处置（COR-02「被替换核心处置未定义」）：默认旧核心随替换销毁；settings.alchemy.core.
       replace_mode="return" 时无损拆回（经 ctx add_item 回包）。配置键为工程补白键。
  D-4  加成道具标记（QLT-09）：items.json 条目 type=="加成" 即加成道具；品质提升幅度 =
       `boost.quality`（或顶层 `boost_quality`，int ≥0），缺省回落 settings.alchemy.boost_quality
       （默认 30，对齐 M-08「✅ 品质+30」）；改属性元素 = `boost.element`（或顶层 `element`）。
  D-5  挑战苛刻条件配置键（F-16 可配「且/或」+ 阈值 + 品质上限可配）：settings.alchemy.challenge
       = {chain_segments:5, element_hits:2, operator:"and"|"or", quality_cap_bonus:10,
       degrade_levels:1}（缺省按 F-16 默认值兜底）。
  D-6  挑战降级档数（F-16「品质降级」未给档数）：默认降 1 档，可配 settings.alchemy.challenge.
       degrade_levels（≥1）；对快照暂存品质分 quality_score 就地降级（无暂存分 → 写
       challenge_degraded=True 标记供批6A 结算消费）。【最小必要推导】
  D-7  进化宝石费（F-07「消耗材料+宝石」未给费率）：取 recipe.cost.gem（per-recipe 数据驱动，
       对齐 upgrade 配方 cost.gem 形态），缺省 0（未配置则无宝石消耗；配置 >0 时触发「宝石不足」
       拒绝路径）。【最小必要推导】
  D-8  进化解锁表落点（F-07 永久解锁 / 数据落点「玩家级配方解锁表」）：写 ctx["upgrade_unlocks"]
       dict（对齐批2 UpgradeEngine U-F2：键=已解锁配方 id，值={source, gem_cost, ...}），与
       /配方合成 共用同一张表；引擎零 IO 不碰 SQLite（持久化归指令壳）。
  D-9  进化「继承」语义（F-07：继承槽位余量+投入次数+平均品质；特性不继承）：引擎在解锁记录
       inherit 元数据落 extra_slots/slots/traits_inherited=False（槽位继承显式落账，特性不继承
       显式标注）；「投入次数/平均品质」为深度产出时的生产态继承，由批6A 深度结算消费快照实现，
       引擎不越权推导数值。
  D-10 深度面板槽位（F-06 深度面板 6 槽/核心槽/3 普通+1 金）：slots 取 recipe.slots（深度配方
       test_demo rcp_deep_star=6，缺省 6）；3 普通+1 金 落 traits_inherit（普通位，缺省 3）+
       gold_slot_exclusive=True（第 4 位金色独占，对齐 TSC-13 超特性第 4 位独占）。
  D-11 进化计数来源（数据落点「产出计数 = 炼金会话结算次数（长线计数）」）：produce_counts 由
       调用方传入 {recipe_id: 炼金产出次数}（批6A /确认 炼金结算时递增；/合成 不计数——CASC-05
       合成不计由调用方保证只计炼金产出）；本引擎纯校验，不持有长线计数。
  D-12 挑战退料幂等（ATO-06：只退一次）：快照 challenge_refunded=True 置位后不再退料；且
       challenge_settled=True 终态标记（重复结算 → idempotent 直返不重复施加降级/上限）。

铁律：零 NoneBot import；纯函数（同刻同参必同值，ctx 只读注册表 + 经 hook 就地改写背包）；
      不抛异常（防御降级返回 dict）；每条规则注释标注出处（GU/F/COR/ATO/CASC/QLT 编号 + 定稿/
      细化行号）；不得新增定稿外机制行为。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping, Optional

from qbot_rpg.core.alchemy_core import (
    ALCHEMY_JOB_ID,
    ELEMENT_NAMES_CN,
    MASTER_TIER_INDEX,
    AlchemyCore,
)
from qbot_rpg.core.alchemy_session import CHALLENGE_SESSION
from qbot_rpg.core.quality import ABSOLUTE_QUALITY_MAX, QualitySystem

__all__ = [
    "GRANDMASTER_TIER_INDEX",
    "DEFAULT_DEEP_SLOTS",
    "DEFAULT_CHAIN_MIN",
    "DEFAULT_ELEMENT_MIN",
    "DEFAULT_CHALLENGE_OPERATOR",
    "DEFAULT_CHALLENGE_CAP_BONUS",
    "DEFAULT_CHALLENGE_DEGRADE_LEVELS",
    "DEFAULT_BOOST_QUALITY",
    "EVOLVE_UNLOCK_SOURCE",
    "CORE_ITEM_TYPE",
    "BOOST_ITEM_TYPE",
    "DeepEngine",
]

# ---------------------------------------------------------------------------
# 常量（对齐 alchemy_core 档位锚点：大师4/宗师5/王6；会话类型 CHALLENGE_SESSION 批3B 已落地）
# ---------------------------------------------------------------------------
GRANDMASTER_TIER_INDEX: int = 5      # 宗师：/进化 /加成 /挑战 门槛（GU-23/28/47，L86/L214）
DEFAULT_DEEP_SLOTS: int = 6           # 深度面板槽位（F-06：6 槽；recipe.slots 缺省 6，D-10）

# 挑战苛刻条件默认（F-16/L214：连锁≥5 且 刻度≥2，可配且/或；D-5）
DEFAULT_CHAIN_MIN: int = 5            # 苛刻条件 连锁 ≥5
DEFAULT_ELEMENT_MIN: int = 2          # 苛刻条件 刻度 ≥2（命中 element_req 阈值数）
DEFAULT_CHALLENGE_OPERATOR: str = "and"  # 苛刻条件组合算子（可配 and/or）
DEFAULT_CHALLENGE_CAP_BONUS: int = 10    # 挑战成功品质上限+10（可配，F-16）
DEFAULT_CHALLENGE_DEGRADE_LEVELS: int = 1  # 挑战失败降级档数（F-16「品质降级」，D-6）

# 加成道具品质提升默认（QLT-09/M-08：例 贤者之石 品质+30；D-4）
DEFAULT_BOOST_QUALITY: int = 30

# 进化解锁来源标记（D-8：对齐 UpgradeEngine _UNLOCK_SOURCE_FORMULA 同表惯例）
EVOLVE_UNLOCK_SOURCE: str = "evolve"

# 物品标记（工程补白 D-1/D-4：核心/加成道具 = items.json type 标记）
CORE_ITEM_TYPE: str = "核心"
BOOST_ITEM_TYPE: str = "加成"

# 错误 reason 常量（对齐指令契约错误模板全集 L344）
_REASON_TIER_TOO_LOW: str = "tier_too_low"
_REASON_COUNT_NOT_MET: str = "count_not_met"
_REASON_CORE_MISMATCH: str = "core_mismatch"
_REASON_BUFF_LIMIT: str = "buff_limit"
_REASON_NO_DEEP: str = "no_deep_session"
_REASON_ALREADY_UNLOCKED: str = "already_unlocked"


def _clamp_int(value: Any, default: int = 0, *, lo: int = 0, hi: Optional[int] = None) -> int:
    """防御取整（bool 排除）；越界钳制。"""
    if isinstance(value, bool):
        return default
    try:
        ival = int(value)
    except (TypeError, ValueError):
        return default
    if ival < lo:
        ival = lo
    if hi is not None and ival > hi:
        ival = hi
    return ival


def _hook_ok(result: Any) -> bool:
    """ctx hook 返回值成功判定（False → 失败；Mapping 取 ok 键；None/True → 成功）。"""
    if result is False:
        return False
    if isinstance(result, Mapping):
        return bool(result.get("ok", True))
    return True


class DeepEngine:
    """深度炼金引擎（批8 路8A，纯逻辑零 IO 零 NoneBot）。

    构造器配置注入（settings + quality）+ 缺省默认值兜底（对齐 quality.py / settle.py 模式）。
    纯函数：同刻同参必同值；ctx 只读注册表（items/recipe），背包/货币/解锁表经 ctx 的
    remove_item/add_item/count_item/currencies/upgrade_unlocks 就地改写（对齐 reward.py /
    settle.py 模式），存储与事务由壳层完成。
    """

    def __init__(
        self,
        settings: Optional[Mapping[str, Any]] = None,
        quality: Optional[QualitySystem] = None,
    ) -> None:
        """构造深度炼金引擎（配置注入 + 缺省默认值兜底）。

        入参：
          - settings：settings dict（读 alchemy.challenge 挑战配置 / boost_quality / core
            replace_mode）；None/缺 alchemy 段 → 默认模板兜底（D-5/D-4/D-3）。
          - quality：QualitySystem 实例（可选注入；用于挑战失败 degrade_quality）；
            None/非 QualitySystem → 缺省默认四档模板兜底。
        """
        self._quality: QualitySystem = (
            quality if isinstance(quality, QualitySystem) else QualitySystem()
        )
        self._settings: Mapping[str, Any] = settings if isinstance(settings, Mapping) else {}
        # 复用 AlchemyCore（new_snapshot 基础快照 / _find_recipe / _find_item，批4A 已落地）
        self._core = AlchemyCore(settings=self._settings)

    # ------------------------------------------------------------------
    # 配置读取（缺省默认值兜底）
    # ------------------------------------------------------------------
    def _alchemy_settings(self) -> Mapping[str, Any]:
        """settings.alchemy 段（缺省空 Mapping，调用方各自兜底）。"""
        alch = self._settings.get("alchemy")
        return alch if isinstance(alch, Mapping) else {}

    def _challenge_cfg(self) -> Dict[str, Any]:
        """挑战苛刻条件配置（F-16/L214 可配且/或；工程补白 D-5）。

        settings.alchemy.challenge = {chain_segments, element_hits, operator,
        quality_cap_bonus, degrade_levels}；缺省 5/2/"and"/10/1 兜底。
        """
        raw = self._alchemy_settings().get("challenge")
        cfg: Dict[str, Any] = {}
        if isinstance(raw, Mapping):
            for key, default in (
                ("chain_segments", DEFAULT_CHAIN_MIN),
                ("element_hits", DEFAULT_ELEMENT_MIN),
                ("quality_cap_bonus", DEFAULT_CHALLENGE_CAP_BONUS),
                ("degrade_levels", DEFAULT_CHALLENGE_DEGRADE_LEVELS),
            ):
                # quality_cap_bonus 允许 0（可配关闭上限加成）；其余阈值 ≥1
                cfg[key] = _clamp_int(
                    raw.get(key), default, lo=(0 if key == "quality_cap_bonus" else 1)
                )
            op = raw.get("operator")
            cfg["operator"] = op if op in ("and", "or") else DEFAULT_CHALLENGE_OPERATOR
        else:
            cfg = {
                "chain_segments": DEFAULT_CHAIN_MIN,
                "element_hits": DEFAULT_ELEMENT_MIN,
                "operator": DEFAULT_CHALLENGE_OPERATOR,
                "quality_cap_bonus": DEFAULT_CHALLENGE_CAP_BONUS,
                "degrade_levels": DEFAULT_CHALLENGE_DEGRADE_LEVELS,
            }
        return cfg

    def _boost_quality_default(self) -> int:
        """加成道具品质提升缺省（QLT-09/M-08：默认 30；settings.alchemy.boost_quality 可配，
        D-4）。"""
        v = self._alchemy_settings().get("boost_quality")
        n = _clamp_int(v, DEFAULT_BOOST_QUALITY, lo=0)
        return n if n > 0 else DEFAULT_BOOST_QUALITY

    def _core_replace_mode(self) -> str:
        """旧核心处置模式（COR-02 工程补白 D-3：默认 destroy，settings.alchemy.core.
        replace_mode="return" 无损拆回）。"""
        core_cfg = self._alchemy_settings().get("core")
        if isinstance(core_cfg, Mapping):
            mode = core_cfg.get("replace_mode")
            if mode in ("destroy", "return"):
                return str(mode)
        return "destroy"

    def _evolve_gem_cost(self, recipe_def: Mapping[str, Any]) -> int:
        """进化宝石费（F-07「消耗材料+宝石」未给费率；工程补白 D-7：取 recipe.cost.gem）。"""
        cost = recipe_def.get("cost")
        if isinstance(cost, Mapping):
            return max(0, _clamp_int(cost.get("gem"), 0, lo=0))
        return 0

    # ------------------------------------------------------------------
    # 工具：档位 / 注册表 / 持有（对齐 alchemy_core / settle 口径）
    # ------------------------------------------------------------------
    @staticmethod
    def _tier_index(player: Any, job_id: str) -> int:
        """职业档位索引（0~6，与 7 级称号一一对应；对齐 ProficiencyEngine.tier_index_for_level
        的 min(level, len-1) 口径）。

        读 player.proficiency.<job_id>.level（level 0=见习 起）；非法/缺档 → 0（见习兜底）。
        """
        if not isinstance(player, Mapping):
            return 0
        prof = player.get("proficiency")
        if not isinstance(prof, Mapping):
            return 0
        node = prof.get(job_id)
        if not isinstance(node, Mapping):
            return 0
        try:
            level = max(0, int(node.get("level", 0)))
        except (TypeError, ValueError):
            return 0
        return min(level, 6)

    def _find_recipe(self, key: Any, ctx: Mapping[str, Any]) -> Optional[dict]:
        """按 id 查 recipe.json def（ctx["recipe"] 注册表 / ctx["resolve_recipe"]）。"""
        return self._core._find_recipe(key, ctx)  # noqa: SLF001  # 复用同层引擎私有查找

    def _find_item(self, key: Any, ctx: Mapping[str, Any]) -> Optional[dict]:
        """按 id 或 name 查 items.json def（ctx["items"] 注册表 / ctx["resolve_item"]）。"""
        return self._core._find_item(key, ctx)  # noqa: SLF001

    @staticmethod
    def _ctx_have(ctx: Mapping[str, Any], item_id: str) -> int:
        """背包持有数（ctx["count_item"](id)->int 优先；ctx["inventory"] dict 兜底）。"""
        count_item = ctx.get("count_item")
        if callable(count_item):
            try:
                return max(0, int(count_item(item_id)))
            except Exception:
                return 0
        inv = ctx.get("inventory")
        if isinstance(inv, Mapping):
            try:
                return max(0, int(inv.get(item_id, 0)))
            except (TypeError, ValueError):
                return 0
        return 0

    @staticmethod
    def _currencies(ctx: Mapping[str, Any]) -> Optional[MutableMapping]:
        """玩家货币表：ctx["currencies"]（就地扣减，对齐 upgrade/reward hook 模式）。"""
        cur = ctx.get("currencies")
        return cur if isinstance(cur, MutableMapping) else None

    @staticmethod
    def _normalize_materials(recipe_def: Mapping[str, Any]) -> List[Dict[str, Any]]:
        """配方材料清单归一（data 契约 §1：materials=[{id|item, count}] → [{item, count}]）。"""
        out: List[Dict[str, Any]] = []
        raw = recipe_def.get("materials")
        if not isinstance(raw, (list, tuple)):
            return out
        for e in raw:
            if not isinstance(e, Mapping):
                continue
            iid = e.get("item") or e.get("id")
            if not isinstance(iid, str) or not iid:
                continue
            out.append({"item": iid, "count": max(1, _clamp_int(e.get("count"), 1, lo=1))})
        return out

    # ------------------------------------------------------------------
    # 深度会话（F-06/GU-20~22；TC-14）
    # ------------------------------------------------------------------
    def deep_eligible(self, player: Any, job_id: str, recipe_def: Any) -> dict:
        """深度炼金解锁守卫（GU-20：炼金职业 ≥ 大师 → 「深度未解锁」拒绝；TC-14）。

        入参：player（读 proficiency.<job_id>.level 取档位）；job_id（炼金职业 ID）；
              recipe_def（配方 def，master_only=True 为深度配方标记，F-06 数据落点）。
        出参：{ok, tier_index} 或 {ok:False, reason:"tier_too_low"|"not_deep_recipe",
              message:"深度未解锁"|...}。
        核心：① 配方须 master_only=True（深度配方标记，非深度配方拒绝）；
              ② 档位索引 ≥ MASTER_TIER_INDEX(4)（GU-20/L25/L192）。
        """
        if not isinstance(recipe_def, Mapping):
            return {"ok": False, "reason": "not_deep_recipe", "message": "非深度配方"}
        if recipe_def.get("master_only") is not True:
            return {"ok": False, "reason": "not_deep_recipe", "message": "非深度配方"}
        tier = self._tier_index(player, job_id)
        if tier < MASTER_TIER_INDEX:
            return {
                "ok": False,
                "reason": _REASON_TIER_TOO_LOW,
                "message": "深度未解锁",
                "tier_index": tier,
            }
        return {"ok": True, "tier_index": tier}

    def deep_snapshot(self, recipe_def: Any, *, job_tier_index: Any) -> dict:
        """新建深度会话快照（F-06：深度面板 6 槽/核心槽/3 普通+1 金/刻度/进化线；MUT-07 深度与
        /炼金 会话分离——session_type=challenge_alchemy）。

        入参：
          - recipe_def：recipe.json 配方 def（master_only/slots/element_req/evolve_to/
            traits_inherit/quality_cap）。
          - job_tier_index：职业档位索引（记录进快照，供深度操作门槛防御判定）。
        出参：快照 dict——基础字段继承 AlchemyCore.new_snapshot（§7.1：recipe_id/materials/
          chain/element_scores/pool/catalyst/pp/step/version/job_tier_index），叠加深度专属：
          {session_type:"challenge_alchemy", slots(6), core_slot:None, core_cap:0,
           evolve_line:{target_id,count,source} 或 None, buff_used:False, buff_bonus:0,
           quality_cap_bonus:0, challenge:False, challenge_refunded:False,
           challenge_settled:False, traits_inherit(3), gold_slot_exclusive:True,
           quality_cap(配方原上限,缺省100)}。
        注：本方法为纯快照构造（不判大师门槛）；/深度炼金 守卫由 deep_eligible 承载（壳层先
          判门槛再开会话，TC-14）。
        """
        if not isinstance(recipe_def, Mapping):
            return {"ok": False, "reason": "invalid_recipe", "message": "配方不存在"}
        base = self._core.new_snapshot(recipe_def, job_tier=job_tier_index)
        snap: Dict[str, Any] = dict(base)
        snap["session_type"] = CHALLENGE_SESSION           # F-06/GU-22/MUT-07 深度会话类型
        snap["slots"] = max(2, _clamp_int(recipe_def.get("slots"), DEFAULT_DEEP_SLOTS, lo=2))
        snap["core_slot"] = None                            # 核心槽（COR-01，初始空）
        snap["core_cap"] = 0                                # 核心品质上限+X（QLT-08②，settle 消费）
        evolve = recipe_def.get("evolve_to")
        evolve_line: Optional[Dict[str, Any]] = None
        if isinstance(evolve, Mapping):
            cond = evolve.get("condition")
            need = 0
            src = None
            if isinstance(cond, Mapping):
                need = max(1, _clamp_int(cond.get("count"), 1, lo=1))
                s = cond.get("source")
                src = str(s) if isinstance(s, str) else None
            tid = evolve.get("id")
            evolve_line = {
                "target_id": str(tid) if isinstance(tid, str) else None,
                "count": need,
                "source": src,
            }
        snap["evolve_line"] = evolve_line                   # 进化线（F-06 深度面板 / 7 落点）
        snap["buff_used"] = False                           # 加成限 1 次/调合 标记（GU-28）
        snap["buff_bonus"] = 0                              # 加成品质提升（QLT-09 结算后施加）
        snap["quality_cap_bonus"] = 0                       # 挑战成功品质上限+10（F-16）
        snap["challenge"] = False                           # 挑战会话子态标记（F-16/GU-48）
        snap["challenge_refunded"] = False                  # ATO-06 退料幂等标记
        snap["challenge_settled"] = False                   # 挑战结算终态标记（幂等防御）
        snap["traits_inherit"] = max(1, _clamp_int(recipe_def.get("traits_inherit"), 3, lo=1))
        snap["gold_slot_exclusive"] = True                  # 3 普通+1 金（TSC-13/D-10）
        snap["quality_cap"] = max(
            0, _clamp_int(recipe_def.get("quality_cap"), ABSOLUTE_QUALITY_MAX, lo=0)
        )
        return snap

    # ------------------------------------------------------------------
    # 进化（GU-23~25/F-07/CASC-05/ATO-05；TC-15）
    # ------------------------------------------------------------------
    def evolve_eligible(self, player: Any, job_id: str, recipe_def: Any,
                        produce_counts: Any) -> dict:
        """进化条件判定（GU-23 宗师 / GU-24 低阶配方炼金产出 N 次 合成不计；TC-15）。

        入参：
          - player：玩家 dict（读 proficiency.<job_id>.level 取档位，宗师=档位索引 ≥5）。
          - job_id：炼金职业 ID。
          - recipe_def：低阶配方 def（须含 evolve_to{id, condition:{count, source}}）。
          - produce_counts：调用方传入的炼金产出计数 {recipe_id: int}（**合成不计**——CASC-05
            由调用方只计炼金层产出、不含 /合成；多级链逐级计次 = 各级配方各自计数入此 dict）。
        出参：{ok, count, need, target_id, tier_index} 或
          {ok:False, reason:"tier_too_low"|"no_evolve_target"|"count_not_met", ...}。
        核心：① 宗师门槛（GU-23，L86）；② 存在 evolve_to 目标（GU-24/P-07）；
              ③ count = produce_counts[recipe_id] ≥ condition.count（不足拒绝，CASC-05）。
        """
        tier = self._tier_index(player, job_id)
        if tier < GRANDMASTER_TIER_INDEX:
            return {"ok": False, "reason": _REASON_TIER_TOO_LOW, "tier_index": tier}
        if not isinstance(recipe_def, Mapping):
            return {"ok": False, "reason": "no_evolve_target"}
        evolve = recipe_def.get("evolve_to")
        if not isinstance(evolve, Mapping):
            return {"ok": False, "reason": "no_evolve_target"}
        cond = evolve.get("condition")
        need = 1
        if isinstance(cond, Mapping):
            need = max(1, _clamp_int(cond.get("count"), 1, lo=1))
        tid = evolve.get("id")
        target_id = str(tid) if isinstance(tid, str) else None
        recipe_id = str(recipe_def.get("id") or "")
        count = 0
        if isinstance(produce_counts, Mapping):
            raw = produce_counts.get(recipe_id)
            count = max(0, _clamp_int(raw, 0, lo=0))
        elif isinstance(produce_counts, (list, tuple)):
            # 防御兼容 list 形态 [{recipe_id, count}]
            for e in produce_counts:
                if not isinstance(e, Mapping):
                    continue
                if str(e.get("recipe_id") or e.get("id") or "") == recipe_id:
                    count = max(0, _clamp_int(e.get("count"), 0, lo=0))
                    break
        if count < need:
            return {
                "ok": False,
                "reason": _REASON_COUNT_NOT_MET,
                "count": count,
                "need": need,
                "target_id": target_id,
                "tier_index": tier,
            }
        return {
            "ok": True,
            "count": count,
            "need": need,
            "target_id": target_id,
            "tier_index": tier,
        }

    def evolve_unlock(self, player: Any, ctx: Mapping[str, Any], recipe_def: Any,
                      counts: Any) -> dict:
        """进化：永久解锁下一级配方（F-07：扣材料+宝石 → 永久解锁 → 「✅ 继承 2 额外槽（6 槽）」；
        ATO-05 已解锁幂等；TC-15）。

        入参：
          - player：玩家 dict（宗师门槛经 evolve_eligible 判定）。
          - ctx：上下文（recipe 注册表 + count_item/remove_item hook + currencies +
            upgrade_unlocks 解锁表）。
          - recipe_def：低阶配方 def（evolve_to/evolve_to 目标/materials/cost{coins,gem}）。
          - counts：炼金产出计数 {recipe_id: int}（合成不计，CASC-05）。
        出参：成功 {ok, message:"✅ 继承 N 额外槽（M 槽）", unlocked:目标配方id, extra_slots,
          target_slots, gem_cost, source_id, idempotent:False}；拒绝 {ok:False, reason,
          message}；已解锁幂等 {ok:False, reason:"already_unlocked", message:"已解锁",
          idempotent:True}（不重复扣料，ATO-05）。
        核心管线：
          ① evolve_eligible 校验（宗师+产出 N 次）→ ② ATO-05 幂等（目标已解锁 → 已解锁零扣）
          → ③ GU-25/ATO-01 材料+宝石全量校验（全拒+差异，零副作用）→ ④ 扣材料+宝石（同事务
          由壳层包裹）→ ⑤ 永久解锁写 ctx["upgrade_unlocks"][target_id]（D-8 对齐 U-F2）。
        """
        el = self.evolve_eligible(player, ALCHEMY_JOB_ID, recipe_def, counts)
        if not el.get("ok"):
            return {
                "ok": False,
                "reason": el.get("reason", _REASON_TIER_TOO_LOW),
                "message": self._evolve_reject_message(el),
            }
        recipe_id = str(recipe_def.get("id") or "")
        target_id = el.get("target_id")
        if not isinstance(target_id, str) or not target_id:
            return {"ok": False, "reason": "no_evolve_target", "message": "配方无进化目标"}
        # ② ATO-05 幂等：已解锁 → 「已解锁」不重复扣料/宝石
        unlocks = ctx.get("upgrade_unlocks")
        if not isinstance(unlocks, MutableMapping):
            return {"ok": False, "reason": "unlock_table_missing", "message": "解锁表缺失"}
        if target_id in unlocks:
            return {
                "ok": False,
                "reason": _REASON_ALREADY_UNLOCKED,
                "message": "已解锁",
                "idempotent": True,
            }
        # ③ GU-25/ATO-01 材料+宝石全量校验（零副作用）
        need = self._normalize_materials(recipe_def)
        shortfall: List[dict] = []
        for m in need:
            have = self._ctx_have(ctx, m["item"])
            if have < m["count"]:
                shortfall.append({"item": m["item"], "count": m["count"], "have": have})
        if shortfall:
            return {
                "ok": False,
                "reason": "materials_insufficient",
                "message": "材料不足",
                "shortfall": shortfall,
            }
        gem_cost = self._evolve_gem_cost(recipe_def)
        cur = self._currencies(ctx)
        if gem_cost > 0:
            if cur is None or _clamp_int(cur.get("gem", 0), 0, lo=0) < gem_cost:
                return {
                    "ok": False,
                    "reason": "gem_insufficient",
                    "message": f"宝石不足（需 {gem_cost}）",
                    "gem_need": gem_cost,
                }
        cost_coins = 0
        cost = recipe_def.get("cost")
        if isinstance(cost, Mapping):
            cost_coins = max(0, _clamp_int(cost.get("coins"), 0, lo=0))
        if cost_coins > 0:
            if cur is None or _clamp_int(cur.get("coins", 0), 0, lo=0) < cost_coins:
                return {
                    "ok": False,
                    "reason": "coins_insufficient",
                    "message": f"金币不足（需 {cost_coins}）",
                }
        # ④ 扣材料+宝石（hook 缺失 → 拒绝零副作用）
        remove_item = ctx.get("remove_item")
        if not callable(remove_item):
            return {"ok": False, "reason": "remove_item_hook_missing", "message": "缺少扣料 hook"}
        for m in need:
            if not _hook_ok(remove_item(m["item"], m["count"])):
                return {"ok": False, "reason": "materials_remove_failed", "message": "材料扣除失败"}
        if gem_cost > 0 and cur is not None:
            cur["gem"] = max(0, _clamp_int(cur.get("gem", 0), 0, lo=0) - gem_cost)
        if cost_coins > 0 and cur is not None:
            cur["coins"] = max(0, _clamp_int(cur.get("coins", 0), 0, lo=0) - cost_coins)
        # ⑤ 永久解锁写 ctx["upgrade_unlocks"]（D-8 对齐批2 UpgradeEngine U-F2 同表）
        source_slots = max(2, _clamp_int(recipe_def.get("slots"), 4, lo=2))
        target_recipe = self._find_recipe(target_id, ctx)
        target_slots = (
            max(2, _clamp_int(target_recipe.get("slots"), DEFAULT_DEEP_SLOTS, lo=2))
            if target_recipe is not None else DEFAULT_DEEP_SLOTS
        )
        extra_slots = max(0, target_slots - source_slots)
        inherit = {
            "extra_slots": extra_slots,
            "slots": target_slots,
            "traits_inherited": False,  # F-07 特性不继承（TSC-18/REC-09）
        }
        unlocks[target_id] = {
            "source": EVOLVE_UNLOCK_SOURCE,
            "gem_cost": gem_cost,
            "source_id": recipe_id,
            "inherit": inherit,
        }
        return {
            "ok": True,
            "message": f"✅ 继承 {extra_slots} 额外槽（{target_slots} 槽）",
            "unlocked": target_id,
            "extra_slots": extra_slots,
            "target_slots": target_slots,
            "gem_cost": gem_cost,
            "source_id": recipe_id,
            "idempotent": False,
        }

    @staticmethod
    def _evolve_reject_message(el: dict) -> str:
        """进化拒绝消息（对齐 M-07 失败模板：等级不足/条件不满足）。"""
        reason = el.get("reason")
        if reason == _REASON_TIER_TOO_LOW:
            return "等级不足"
        if reason == _REASON_COUNT_NOT_MET:
            return f"条件不满足（炼金产出 {el.get('count', 0)}/{el.get('need', 0)}）"
        return "配方无进化目标"

    # ------------------------------------------------------------------
    # 镶核心（COR-01~03/GU-26~27；TC-16）
    # ------------------------------------------------------------------
    @staticmethod
    def _is_deep_snap(snap: Mapping[str, Any]) -> bool:
        """深度会话快照判定（F-06/MUT-07：session_type==challenge_alchemy 或带 core_slot 键）。"""
        return snap.get("session_type") == CHALLENGE_SESSION or "core_slot" in snap

    @staticmethod
    def _core_cap_bonus(core_def: Mapping[str, Any]) -> int:
        """核心品质上限 X（工程补白 D-1：core.cap_bonus 或顶层 cap_bonus，int ≥0）。"""
        core_cfg = core_def.get("core")
        if isinstance(core_cfg, Mapping):
            return max(0, _clamp_int(core_cfg.get("cap_bonus"), 0, lo=0))
        return max(0, _clamp_int(core_def.get("cap_bonus"), 0, lo=0))

    def _core_element(self, core_def: Mapping[str, Any]) -> Optional[str]:
        """核心属性适配元素（工程补白 D-1：element 字段或 elements 主元素；无 → None）。"""
        elem = core_def.get("element")
        if isinstance(elem, str) and elem:
            return elem
        elements = core_def.get("elements")
        if isinstance(elements, Mapping):
            return self._core._main_element(elements)  # noqa: SLF001  # 复用主元素判定
        return None

    def _core_compatible(self, core_def: Mapping[str, Any], snap: Mapping[str, Any],
                         ctx: Mapping[str, Any]) -> bool:
        """核心与配方适配判定（GU-27；工程补白 D-2：配方有 element_req 时核心元素须命中键集）。"""
        elem = self._core_element(core_def)
        recipe = self._find_recipe(snap.get("recipe_id"), ctx)
        req = recipe.get("element_req") if recipe is not None else None
        if isinstance(req, Mapping) and req:
            return elem is not None and str(elem) in req
        return True

    def mount_core(self, player: Any, snap: Any, core_item_def: Any, ctx: Mapping[str, Any]
                   ) -> dict:
        """镶核心（COR-01~03/GU-26~27/F-08：大师 + 深度会话中 + 核心与配方适配 → 消耗入装 →
        快照 core_slot=核心 def（品质上限+X/属性适配）→ 可换；TC-16）。

        入参：
          - player：玩家 dict（大师=档位索引 ≥4，COR-01 解锁）。
          - snap：深度会话快照（session_type=challenge_alchemy；None/非深度 → 拒绝）。
          - core_item_def：核心物品 def（type=="核心"，D-1；携带 cap_bonus/element）。
          - ctx：items/recipe 注册表 + remove_item/add_item hook。
        出参：成功 {ok, message:"✅ 品质上限+X、火适配", snap:快照2, core:core_slot,
          replaced:bool}；拒绝 {ok:False, reason, message}——**全部失败统一 message="核心不匹配"
          （TC-26/L344 错误模板）**，reason 区分 no_deep_session/tier_too_low/not_core_item/
          core_mismatch。
        核心管线：① 深度会话中（GU-26）→ ② 大师（COR-01）→ ③ 核心物品（type 校验）→
          ④ 与配方适配（GU-27，D-2）→ ⑤ 消耗核心 1 个（F-08/COR-02）→ ⑥ 旧核心处置
          （COR-02 可换；D-3 destroy/return）→ ⑦ 快照 core_slot 写入 + core_cap（QLT-08②，
          SettleEngine._extra_cap 消费）。
        """
        if not isinstance(snap, Mapping) or not self._is_deep_snap(snap):
            return {"ok": False, "reason": _REASON_NO_DEEP, "message": "核心不匹配"}
        tier = _clamp_int(snap.get("job_tier_index"), 0, lo=0) or self._tier_index(
            player, ALCHEMY_JOB_ID
        )
        if tier < MASTER_TIER_INDEX:
            return {"ok": False, "reason": _REASON_TIER_TOO_LOW, "message": "核心不匹配"}
        if not isinstance(core_item_def, Mapping) or core_item_def.get("type") != CORE_ITEM_TYPE:
            return {"ok": False, "reason": "not_core_item", "message": "核心不匹配"}
        core_id = str(core_item_def.get("id") or "")
        if not core_id:
            return {"ok": False, "reason": "not_core_item", "message": "核心不匹配"}
        if not self._core_compatible(core_item_def, snap, ctx):
            return {"ok": False, "reason": _REASON_CORE_MISMATCH, "message": "核心不匹配"}
        # ⑤ 消耗核心（F-08/COR-02：核心物品当场消耗入装）
        remove_item = ctx.get("remove_item")
        if not callable(remove_item):
            return {"ok": False, "reason": "remove_item_hook_missing", "message": "核心不匹配"}
        if not _hook_ok(remove_item(core_id, 1)):
            return {"ok": False, "reason": "core_remove_failed", "message": "核心不匹配"}
        # ⑥ 旧核心处置（COR-02 可换；工程补白 D-3：默认销毁，replace_mode="return" 无损拆回）
        replaced = False
        old = snap.get("core_slot")
        if isinstance(old, Mapping):
            replaced = True
            old_id = old.get("core_id")
            if self._core_replace_mode() == "return" and isinstance(old_id, str) and old_id:
                add_item = ctx.get("add_item")
                if callable(add_item):
                    _hook_ok(add_item(old_id, 1, True))
                # 无 add_item hook → 静默按销毁处置（回包失败不阻断替换，D-3）
        # ⑦ 快照写入（core_slot + core_cap 对齐 SettleEngine._extra_cap②）
        cap = self._core_cap_bonus(core_item_def)
        elem = self._core_element(core_item_def)
        snap2 = dict(snap)
        snap2["core_slot"] = {
            "core_id": core_id,
            "name": str(core_item_def.get("name") or core_id),
            "cap_bonus": cap,
            "element": elem,
        }
        snap2["core_cap"] = cap
        snap2["version"] = self._core.snapshot_version(snap2) + 1
        cn = ELEMENT_NAMES_CN.get(str(elem), str(elem)) if elem else ""
        message = f"✅ 品质上限+{cap}、{cn}适配" if elem else f"✅ 品质上限+{cap}"
        return {
            "ok": True,
            "message": message,
            "snap": snap2,
            "core": snap2["core_slot"],
            "replaced": replaced,
            "idempotent": False,
        }

    # ------------------------------------------------------------------
    # 加成（GU-28/F-08/QLT-09；TC-16）
    # ------------------------------------------------------------------
    @staticmethod
    def _boost_quality_of(buff_def: Mapping[str, Any]) -> Optional[int]:
        """加成道具品质提升幅度（工程补白 D-4：boost.quality 或顶层 boost_quality；无 → None）。"""
        boost = buff_def.get("boost")
        if isinstance(boost, Mapping):
            v = boost.get("quality")
            if v is not None:
                return max(0, _clamp_int(v, 0, lo=0))
        v = buff_def.get("boost_quality")
        if v is not None:
            return max(0, _clamp_int(v, 0, lo=0))
        return None

    @staticmethod
    def _boost_element(buff_def: Mapping[str, Any]) -> Optional[str]:
        """加成改属性元素（工程补白 D-4：boost.element 或顶层 element；无 → None）。"""
        boost = buff_def.get("boost")
        if isinstance(boost, Mapping):
            e = boost.get("element")
            if isinstance(e, str) and e:
                return e
        e = buff_def.get("element")
        return e if isinstance(e, str) and e else None

    def buff(self, player: Any, snap: Any, buff_item_def: Any, ctx: Mapping[str, Any]) -> dict:
        """加成（GU-28/F-08/QLT-09：宗师 + 加成道具 限 1 次/调合 → 品质大幅提升/改属性；TC-16）。

        入参：
          - player：玩家 dict（宗师=档位索引 ≥5，GU-28）。
          - snap：深度会话快照（buff_used 标记：限 1 次/调合）。
          - buff_item_def：加成道具 def（type=="加成"，D-4；携带 quality 提升幅度）。
          - ctx：remove_item hook。
        出参：成功 {ok, message:"✅ 品质+30"(+改属性), snap:快照2, buff_bonus, buff_element}；
          拒绝 {ok:False, reason, message}——已用 → {ok:False, reason:"buff_limit",
          message:"限 1 次"}（GU-28）。
        核心管线：① 深度会话中 → ② 宗师（GU-28）→ ③ 加成道具（type 校验）→ ④ 限 1 次/调合
          （buff_used 标记，已用拒绝）→ ⑤ 消耗道具 1 个（F-08）→ ⑥ 快照 buff_used/buff_bonus/
          buff_element 写入（QLT-09 品质均值结算后施加，批6A 结算消费）。
        """
        if not isinstance(snap, Mapping) or not self._is_deep_snap(snap):
            return {"ok": False, "reason": _REASON_NO_DEEP, "message": "当前没有深度炼金会话"}
        tier = _clamp_int(snap.get("job_tier_index"), 0, lo=0) or self._tier_index(
            player, ALCHEMY_JOB_ID
        )
        if tier < GRANDMASTER_TIER_INDEX:
            return {"ok": False, "reason": _REASON_TIER_TOO_LOW, "message": "等级不足"}
        if not isinstance(buff_item_def, Mapping) or buff_item_def.get("type") != BOOST_ITEM_TYPE:
            return {"ok": False, "reason": "not_boost_item", "message": "非加成道具"}
        buff_id = str(buff_item_def.get("id") or "")
        if not buff_id:
            return {"ok": False, "reason": "not_boost_item", "message": "非加成道具"}
        if bool(snap.get("buff_used")):
            # GU-28 限 1 次/调合：已用拒绝（快照 buff_used 标记）
            return {"ok": False, "reason": _REASON_BUFF_LIMIT, "message": "限 1 次"}
        # ⑤ 消耗道具（F-08：加成道具 1 个）
        remove_item = ctx.get("remove_item")
        if not callable(remove_item):
            return {"ok": False, "reason": "remove_item_hook_missing", "message": "缺少扣料 hook"}
        if not _hook_ok(remove_item(buff_id, 1)):
            return {"ok": False, "reason": "boost_remove_failed", "message": "道具扣除失败"}
        # ⑥ 快照写入（buff_used 标记 + buff_bonus 品质提升 + buff_element 改属性）
        bonus = self._boost_quality_of(buff_item_def)
        if bonus is None:
            bonus = self._boost_quality_default()  # 缺省回落 30（QLT-09/M-08，D-4）
        elem = self._boost_element(buff_item_def)
        snap2 = dict(snap)
        snap2["buff_used"] = True
        snap2["buff_bonus"] = bonus
        snap2["buff_element"] = elem
        snap2["version"] = self._core.snapshot_version(snap2) + 1
        message = f"✅ 品质+{bonus}"
        if elem:
            cn = ELEMENT_NAMES_CN.get(elem, elem)
            message = f"{message}、{cn}属性"
        return {
            "ok": True,
            "message": message,
            "snap": snap2,
            "buff_bonus": bonus,
            "buff_element": elem,
            "idempotent": False,
        }

    # ------------------------------------------------------------------
    # 挑战（GU-47~49/F-16/ATO-06；TC-23）
    # ------------------------------------------------------------------
    def challenge_check(self, player: Any, snap: Any, *, chain_segments: Any,
                        element_hits: Any) -> dict:
        """挑战苛刻条件判定（F-16/L214：连锁 ≥5 且 刻度 ≥2，可配且/或 → {ok, met}；TC-23）。

        入参：
          - player：玩家 dict（宗师门槛，GU-47 防御）。
          - snap：深度会话快照（GU-48：挑战会话从深度会话发起；非深度 → 拒绝）。
          - chain_segments：连锁段数（AlchemyCore.compute_chain().segments 由调用方传入）。
          - element_hits：刻度达标数（命中的 element_req 阈值数，由调用方统计传入）。
        出参：{ok, met, chain_segments, element_hits, need_chain, need_element, operator,
          chain_ok, element_ok}；{ok:False, reason:"tier_too_low"|"no_deep_session"}。
        核心：met = (chain_segments≥need_chain) op (element_hits≥need_element)，op 可配
          and/or（D-5）；"且" 缺省（F-16）。
        """
        tier = self._tier_index(player, ALCHEMY_JOB_ID)
        if tier < GRANDMASTER_TIER_INDEX:
            return {"ok": False, "reason": _REASON_TIER_TOO_LOW, "tier_index": tier}
        if not isinstance(snap, Mapping) or not self._is_deep_snap(snap):
            return {"ok": False, "reason": _REASON_NO_DEEP, "message": "当前没有深度炼金会话"}
        cfg = self._challenge_cfg()
        chain = max(0, _clamp_int(chain_segments, 0, lo=0))
        elem_hits = max(0, _clamp_int(element_hits, 0, lo=0))
        need_chain = cfg["chain_segments"]
        need_element = cfg["element_hits"]
        chain_ok = chain >= need_chain
        element_ok = elem_hits >= need_element
        met = (chain_ok and element_ok) if cfg["operator"] == "and" else (
            chain_ok or element_ok
        )
        return {
            "ok": True,
            "met": met,
            "chain_segments": chain,
            "element_hits": elem_hits,
            "need_chain": need_chain,
            "need_element": need_element,
            "operator": cfg["operator"],
            "chain_ok": chain_ok,
            "element_ok": element_ok,
        }

    @staticmethod
    def _normalize_paid(material_paid: Any) -> List[Dict[str, Any]]:
        """已付材料归一（GU-49 材料×2；list [{item|id, count}] 或 dict {item: count}）。"""
        out: List[Dict[str, Any]] = []
        if isinstance(material_paid, Mapping):
            for k, v in material_paid.items():
                if not isinstance(k, str) or not k:
                    continue
                out.append({"item": k, "count": max(1, _clamp_int(v, 1, lo=1))})
        elif isinstance(material_paid, (list, tuple)):
            for e in material_paid:
                if not isinstance(e, Mapping):
                    continue
                iid = e.get("item") or e.get("id")
                if not isinstance(iid, str) or not iid:
                    continue
                out.append({"item": iid, "count": max(1, _clamp_int(e.get("count"), 1, lo=1))})
        return out

    def challenge_settle(self, player: Any, ctx: Mapping[str, Any], snap: Any, *,
                         met: bool, material_paid: Any) -> dict:
        """挑战结算（F-16/ATO-06：满足 → 品质上限+10；不满足 → 品质降级 + 退 50% 材料只退一次；
        TC-23）。

        入参：
          - player：玩家 dict（宗师门槛防御，GU-47）。
          - ctx：add_item hook（退料回包）+ recipe 注册表。
          - snap：深度会话快照（challenge 子态；quality_score 可选暂存品质分）。
          - met：苛刻条件是否达标（challenge_check 判定结果）。
          - material_paid：挑战已付材料（配方×2，GU-49；用于退 50% 计算）。
        出参：达标 {ok, message:"🏆 挑战成功！品质上限 +10", quality_cap_bonus, cap_bonus,
          snap}；未达标 {ok, message:"❌ 挑战失败：条件未达标，品质降级，退还 50% 材料",
          reason:"challenge_failed", refund:[{item,count}], degraded, snap}；已结算幂等
          {ok:True, idempotent:True, message:"挑战已结算"}。
        核心管线：
          达标：快照 quality_cap_bonus += 挑战上限（F-16 可配，默认 10）+ challenge_cap
            （QLT-08③，SettleEngine._extra_cap 消费）。
          未达标：① 品质降级（D-6：快照 quality_score 就地 degrade_quality；无暂存分 → 写
            challenge_degraded 标记）→ ② 退 50% 材料（按已付各退 50% 向下取整 floor(count*0.5)，
            只退一次 ATO-06，challenge_refunded 置位）→ ③ 终态 challenge_settled 幂等。
        """
        if not isinstance(snap, Mapping) or not self._is_deep_snap(snap):
            return {"ok": False, "reason": _REASON_NO_DEEP, "message": "当前没有深度炼金会话"}
        if self._tier_index(player, ALCHEMY_JOB_ID) < GRANDMASTER_TIER_INDEX:
            return {"ok": False, "reason": _REASON_TIER_TOO_LOW, "message": "等级不足"}
        snap2 = dict(snap)
        # 终态幂等防御（ATO-04/06 语义：挑战结算随 /确认 终态一次完成，重复直返不重复施加）
        if bool(snap2.get("challenge_settled")):
            return {
                "ok": True,
                "idempotent": True,
                "message": "挑战已结算",
                "snap": snap2,
            }
        if met:
            cfg = self._challenge_cfg()
            cap = cfg["quality_cap_bonus"]
            total = max(0, _clamp_int(snap2.get("quality_cap_bonus"), 0, lo=0)) + cap
            snap2["quality_cap_bonus"] = total
            snap2["challenge_cap"] = cap            # QLT-08③：SettleEngine._extra_cap 消费
            snap2["challenge_settled"] = True
            snap2["version"] = self._core.snapshot_version(snap2) + 1
            return {
                "ok": True,
                "message": f"挑战成功！品质上限 +{cap}",
                "quality_cap_bonus": total,
                "cap_bonus": cap,
                "snap": snap2,
                "idempotent": False,
            }
        # 未达标（F-16：品质降级 + 退 50% 材料，只退一次 ATO-06）
        # ① 品质降级（D-6：快照 quality_score 就地降级；无暂存分 → challenge_degraded 标记）
        degraded: Any = True
        q = snap2.get("quality_score")
        if isinstance(q, int) and not isinstance(q, bool):
            levels = self._challenge_cfg()["degrade_levels"]
            tier, new_score = self._quality.degrade_quality(q, levels)
            snap2["quality_score"] = new_score
            degraded = {"from": q, "to": new_score, "tier": tier, "levels": levels}
        snap2["challenge_degraded"] = degraded
        # ② 退 50% 材料（按已付各退 50% 向下取整；ATO-06 只退一次 challenge_refunded 置位）
        refund: List[Dict[str, int]] = []
        refund_skipped = bool(snap2.get("challenge_refunded"))
        if not refund_skipped:
            add_item = ctx.get("add_item")
            if not callable(add_item):
                return {
                    "ok": False,
                    "reason": "add_item_hook_missing",
                    "message": "缺少退料 hook",
                }
            for m in self._normalize_paid(material_paid):
                back = int(m["count"] * 0.5)  # F-16：按配方各退 50% 向下取整
                if back <= 0:
                    continue
                _hook_ok(add_item(m["item"], back, True))
                refund.append({"item": m["item"], "count": back})
            snap2["challenge_refunded"] = True
        snap2["challenge_settled"] = True
        snap2["version"] = self._core.snapshot_version(snap2) + 1
        return {
            "ok": True,
            "reason": "challenge_failed",
            "message": "❌ 挑战失败：条件未达标，品质降级，退还 50% 材料",
            "refund": refund,
            "refund_skipped": refund_skipped,
            "degraded": degraded,
            "snap": snap2,
            "idempotent": False,
        }
