"""M13 批10 路10A · 6c 季节技能组引擎（qbot_rpg/core/skill_season.py）。

文件名：qbot_rpg/core/skill_season.py
创建时间：2026-09-02
作者：Hermes 子agent-10A（M13 6c 季节技能组实现组批10路10A：并发同仓，仅新建
  本文件 + tests/unit/test_skill_season.py；不碰兄弟文件——10B 独占展示过滤
  + 换季边界（worldtime 联动）、10C 独占条件键+事件）

功能描述：6c 季节技能组引擎核心（细化_6c §2 机制 M5 / EFF-5 行动校验）——
  1) 四季常量与 season 字段解析（SE1：spring/summer/autumn/winter 四枚举，
     缺省 = 通用 = 全年可用【四时 L63】；枚举校验归校验器 V9，引擎层防御
     解析未知值回落通用口径）：
     - SEASONS 四季元组（顺序即换季循环序：spring → summer → autumn →
       winter → spring）；
     - DEFAULT_SEASON = 通用（缺省值）；
     - season_of() 从技能条目读取 season 字段（Mapping 直取 / 协议对象
       hasattr 属性取，G0 注入口径，与 resource_axis._segment_of 同款）；
       非 str / 非四枚举值 → 回落通用（防御读取，V9 红拦归校验器）。
  2) skill_in_season(skill, season) 判定（EFF-5 核心）：技能 season ∈
     {当前季, 通用} → 可用；其余 → 不可用。
  3) 行动校验（EFF-5 唯一入口）：validate_skill_action() 施放前检查——
     非当季技能 → 被拒不耗回合（复用 rejected 管道语义：能量/怒气不变、
     连段不变、可反复尝试【狂战士 L76-77】），返回结构化判定
     {ok, reason, code, skill_id, season}；当前季/通用技能 → ok。
     reason 语义键 season_mismatch + code REJECT_SEASON_MISMATCH，供接线
     方（battle 层）映射「此术式与当前时节不合」提示文案（EFF-3/EFF-5
     文案由展示层模板输出，本引擎零模板输出，对齐 resource_axis B-8）。
  4) SeasonSkillEngine 引擎注入模式（对齐 fishing.py / transform.py /
     ResourceAxisEngine 构造器注入先例）：
     - 构造器注入 season_now（当前世界季节 str，缺省读 ctx["season_now"]）
       与 season_override（显式季节覆盖，测试/装配注入用；非 None 优先）；
     - 方法委托模块级纯函数，不引入可变全局状态；
     - 幂等注入：构造器注入挂 ctx 仅缺省键不覆盖调用方显式注入。
  5) 懒重读支持（EFF-2/EFF-5 引用语义）：current_season(ctx) 从 ctx 读取
     当前季节（战斗会话内每回合开始懒重读，worldtime.season_now 由装配层
     注入 ctx["season_now"]），ctx 缺键 → 回落通用（无季节环境 = 全部技能
     可用，确定性兜底，零空窗）。

依据：
  - docs/细化/细化_6c_资源轴与职业机制.md（497 行 v1.0）：
    §2.1（SE1 season 字段 schema：spring/summer/autumn/winter 四枚举，
    缺省=通用【四时 L63】）；
    §2.2 EFF-2（进战懒加载）/ EFF-5（行动校验唯一入口：技能 ∈ 当前季节组
    ∪ 通用组，不在 → 拒绝并提示；引用在回合开始懒重读时更新）；
    §2.3 SC-2（引擎零新状态机：当前季节组引用回合开始懒重读更新）；
    §0.3 D-05（换季待结算期按旧组校验——旧组校验即「当前生效组」口径，
    本引擎只做当季判定，待结算标记/切换归 10B 换季边界）；
    §六 TC-09（春季选夏季技能 → 行动校验拒绝）。
  - docs/m13_6c摸底.md：M5 缺口（skills 库无 season 字段载体——批9 已在
    skills_fields 登记 season 键）、EFF-5 无实现、§八 批9 路9A（进战斗懒
    加载季节组）。
  - 批9 已落盘：qbot_rpg/content/skill_models.py（skills_fields 含 season
    键登记，SE1 枚举注释）；worldtime.py SEASONS 四季恒定枚举（L91，季节
    数据源，本文件不 import，仅消费 ctx["season_now"]）。
  - 模式参考：qbot_rpg/core/resource_axis.py（_segment_of 段读取 +
    ResourceAxisEngine 构造器注入 + 结构化事件返回）、qbot_rpg/core/
    skill_slots.py（SlotKind 协议 + raw 条目轻量访问器 + G0 零 import
    content）、qbot_rpg/core/transform.py（TransformEngine 钩子注入）。

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查，不冒充契约行号）：
  P-1  通用季节表示 = 常量 SEASON_ANY = "general"（内部规范名，不入四枚举）：
       skill_in_season 判定 skill.season ∈ {当前季, SEASON_ANY}；season_of
       对缺省/未知值统一回落 SEASON_ANY。展示层对「通用」的文案渲染（如
       「全年」）由消费方映射，本引擎只出语义键。
  P-2  引擎零状态机（SC-2）：本文件不持有任何可变状态、不缓存季节——
       current_season 每次从 ctx 现读（懒重读语义由装配层在回合开始刷新
       ctx["season_now"] 实现，worldtime 联动归 10B）；纯函数确定性。
  P-3  ctx 缺季节键 → 回落 SEASON_ANY：无季节环境（未注入 worldtime）时
       全部技能可用（EFF-5 的「缺省=通用」精神延伸到环境侧，确定性兜底
       不误伤技能，零空窗）。
  P-4  判定结果形态：validate_skill_action 返回 {ok, reason, code,
       skill_id, season}；reason = "season_mismatch"（语义键，不含文案），
       code = REJECT_SEASON_MISMATCH（对齐 rejected 管道可机读码）；
       ok=True 时 reason/code 为空串/None。skill_id 缺失（无 id 条目）→
       直接 ok（防御读取，与 skill_slots 无 id 跳过口径一致）。
  P-5  season 大小写敏感（对齐 6c D-06「任何键大小写敏感」）："Spring"
       等大小写变体不属于四枚举 → 回落通用（V9 枚举校验归校验器红拦，
       引擎层不拦截不报错）。

铁律：零 NoneBot import（G0 门禁）；core 层只依赖 data（季节经 ctx 注入，
零 import content）；纯函数确定性（同刻同参必同值）；完整类型标注（typing
3.9 兼容）；零定时器/零睡眠（本文件不含任何 sleep/定时器字面量——引擎零
定时器零睡眠，无时间依赖）；不引入随机；不 git commit；只写本文件 + 自己
的测试。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, MutableMapping, Optional, Tuple

# =====================================================================================
# 常量（细化_6c §2.1 SE1 契约口径）
# =====================================================================================

# 四季枚举（SE1；顺序即换季循环序：spring → summer → autumn → winter）
SEASONS: Tuple[str, ...] = ("spring", "summer", "autumn", "winter")

# 通用季节（缺省 = 通用 = 全年可用【四时 L63】；P-1 内部规范名，不入四枚举）
SEASON_ANY: str = "general"

# season 字段缺省（缺省 = 通用）
DEFAULT_SEASON: str = SEASON_ANY

# ctx 当前季节键（worldtime.season_now 由装配层注入；P-2 懒重读数据源）
SEASON_CTX_KEY: str = "season_now"

# 拒绝语义码（EFF-5：非当季 → 被拒不耗回合；对齐 rejected 管道可机读码）
REJECT_SEASON_MISMATCH: str = "season_mismatch"

# 判定结果键（结构化返回形态，P-4）
_RESULT_KEYS: Tuple[str, ...] = ("ok", "reason", "code", "skill_id", "season")


# =====================================================================================
# season 字段解析（SE1：四枚举 + 缺省通用；防御读取 P-1/P-5）
# =====================================================================================


def _segment_of(skill: Any, key: str) -> Any:
    """技能条目段读取：Mapping 直取；协议对象（hasattr）属性取；缺省 None。

    与 resource_axis._segment_of 同款 G0 注入口径（core 层不 import content，
    技能定义对象经 ctx 注入：SkillDef / 任意同协议对象 / raw dict 均可）。
    """
    if isinstance(skill, Mapping):
        return skill.get(key)
    if skill is not None and hasattr(skill, key):
        v = getattr(skill, key)
        return v() if callable(v) else v
    return None


def parse_season(value: Any) -> str:
    """season 字段值解析（SE1）：四枚举原样返回；其余回落通用（P-1/P-5）。

    入参：value —— 任意（season 字段原始值）。
    出参：str —— "spring"/"summer"/"autumn"/"winter" 之一，或 SEASON_ANY
      （缺省/非字符串/未知值/大小写变体，防御回落；枚举校验 V9 红拦归
      校验器，引擎层不拦截）。
    """
    if isinstance(value, str) and value in SEASONS:
        return value
    return SEASON_ANY


def season_of(skill: Any) -> str:
    """读取技能条目的 season 字段（SE1：缺省 = 通用）。

    入参：skill —— 技能条目（Mapping / 协议对象，G0 注入；None 安全）。
    出参：str —— 四枚举之一或 SEASON_ANY（字段缺失/非法 → 通用，防御）。
    """
    return parse_season(_segment_of(skill, "season"))


# =====================================================================================
# 当前季节读取（EFF-2/EFF-5 懒重读；P-2/P-3）
# =====================================================================================


def current_season(ctx: Mapping[str, Any]) -> str:
    """从 ctx 读取当前世界季节（战斗会话内每回合开始懒重读，EFF-2/EFF-5）。

    入参：ctx —— 运行上下文 Mapping（读取 ctx[SEASON_CTX_KEY]，即
      ctx["season_now"]，worldtime.season_now 由装配层注入）。
    出参：str —— 当前季节（四枚举之一）；ctx 缺键/非字符串/未知值 → 回落
      通用 SEASON_ANY（P-3：无季节环境 = 全部技能可用，确定性兜底）。
    """
    return parse_season(ctx.get(SEASON_CTX_KEY))


# =====================================================================================
# skill_in_season 判定（EFF-5 核心：技能 ∈ 当前季节组 ∪ 通用组）
# =====================================================================================


def skill_in_season(skill: Any, season: str) -> bool:
    """季节技能组判定（EFF-5 核心）：技能 ∈ 当前季节组 ∪ 通用组 → 可用。

    入参：
      skill  —— 技能条目（Mapping / 协议对象，season 段经 season_of 读取）；
      season —— 当前季节（四枚举之一；SEASON_ANY 传入时全部技能可用——
                通用环境无季节组概念，EFF-1 战斗外口径）。
    出参：bool —— True = 可用（技能 season ∈ {当前季, 通用}）；False = 非当季。
    """
    if season == SEASON_ANY:
        return True
    return season_of(skill) in (season, SEASON_ANY)


# =====================================================================================
# 行动校验（EFF-5 唯一入口：施放前检查，非当季 → 被拒不耗回合）
# =====================================================================================


def validate_skill_action(skill: Any, season: str) -> Dict[str, Any]:
    """技能行动施放前季节校验（EFF-5 唯一入口）。

    入参：
      skill  —— 技能条目（Mapping / 协议对象，G0 注入）；
      season —— 当前季节（四枚举之一或 SEASON_ANY）。
    出参：判定 dict {ok, reason, code, skill_id, season}（P-4）：
      - ok=True：技能 ∈ 当前季节组 ∪ 通用组，可正常施放（reason/code 空）；
      - ok=False：非当季 → 被拒不耗回合（reason="season_mismatch"，
        code=REJECT_SEASON_MISMATCH）；接线方（battle 层）复用 rejected
        管道语义：不耗回合、连段不变、可反复尝试，并映射「此术式与当前
        时节不合」提示文案（EFF-3/EFF-5 文案归展示层模板，本引擎零模板）。
    """
    sid = _skill_id(skill)
    if not skill_in_season(skill, season):
        return {
            "ok": False,
            "reason": REJECT_SEASON_MISMATCH,
            "code": REJECT_SEASON_MISMATCH,
            "skill_id": sid,
            "season": season,
        }
    return {
        "ok": True,
        "reason": "",
        "code": None,
        "skill_id": sid,
        "season": season,
    }


def _skill_id(skill: Any) -> Optional[str]:
    """技能条目 id（F01；非字符串/空 → None，防御读取 P-4）。"""
    v = _segment_of(skill, "id")
    return v if isinstance(v, str) and v else None


# =====================================================================================
# SeasonSkillEngine（引擎注入模式：构造器注入 season_now/season_override，缺省 ctx 兜底）
# =====================================================================================


class SeasonSkillEngine:
    """季节技能组引擎（对齐 ResourceAxisEngine / fishing.py 构造器注入模式）。

    注入项（均可缺省，缺省 = 运行时读 ctx，确定性保持）：
      season_now:      Optional[str] —— 当前世界季节（四枚举之一；缺省读
                       ctx[SEASON_CTX_KEY]）。
      season_override: Optional[str] —— 显式季节覆盖（测试/装配注入用；
                       非 None 优先于 season_now 与 ctx，确定性）。
      audit:           Optional[Callable[[str], None]] —— 审计观察口。

    方法委托模块级纯函数（校验前将注入挂 ctx），不引入可变全局状态（P-2）：
      current_season(ctx)      —— 当前季节（override > 注入 > ctx 兜底）；
      check(ctx, skill, side)  —— 行动校验（EFF-5：非当季 → 被拒不耗回合）；
      usable(ctx, skill, side) —— 布尔快捷（check ok）。
    """

    def __init__(
        self,
        season_now: Optional[str] = None,
        season_override: Optional[str] = None,
        audit: Optional[Any] = None,
    ) -> None:
        self._season_now: Optional[str] = season_now
        self._season_override: Optional[str] = season_override
        self._audit: Optional[Any] = audit

    def _inject(self, ctx: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
        """把构造器注入挂 ctx（仅缺省键不覆盖调用方显式注入，幂等）。"""
        if self._season_now is not None:
            ctx.setdefault(SEASON_CTX_KEY, self._season_now)
        return ctx

    def current_season(self, ctx: MutableMapping[str, Any]) -> str:
        """当前世界季节（season_override > 构造器 season_now > ctx，P-2）。"""
        if self._season_override is not None:
            return parse_season(self._season_override)
        return current_season(self._inject(ctx))

    def check(
        self,
        ctx: MutableMapping[str, Any],
        skill: Any,
        side: str = "player",
    ) -> Dict[str, Any]:
        """技能行动施放前季节校验（EFF-5 唯一入口；非当季 → 被拒不耗回合）。

        入参：
          ctx   —— 运行上下文 MutableMapping（缺季节键时构造器注入兜底）；
          skill —— 技能条目（Mapping / 协议对象，G0 注入）；
          side  —— 施放侧（"player"/"enemy"；当前仅透传审计，判定与侧无关）。
        出参：validate_skill_action 判定 dict（P-4）。
        """
        season = self.current_season(ctx)
        result = validate_skill_action(skill, season)
        if self._audit is not None:
            self._audit(
                "season_check: ok=%s skill=%s season=%s" % (
                    result.get("ok"), result.get("skill_id"), season,
                )
            )
        return result

    def usable(self, ctx: MutableMapping[str, Any], skill: Any, side: str = "player") -> bool:
        """布尔快捷判定（EFF-5：技能 ∈ 当前季节组 ∪ 通用组 → True）。"""
        return bool(self.check(ctx, skill, side=side).get("ok"))


__all__ = [
    # 常量
    "SEASONS",
    "SEASON_ANY",
    "DEFAULT_SEASON",
    "SEASON_CTX_KEY",
    "REJECT_SEASON_MISMATCH",
    # 解析
    "parse_season",
    "season_of",
    # 读取/判定
    "current_season",
    "skill_in_season",
    # 行动校验（EFF-5）
    "validate_skill_action",
    # 引擎
    "SeasonSkillEngine",
]
