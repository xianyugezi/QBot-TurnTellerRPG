"""M13 批10 路10A · 6c 季节技能组引擎单元测试（tests/unit/test_skill_season.py）。

文件名：test_skill_season.py
创建时间：2026-09-02
作者：Hermes 子agent-10A（M13 6c 季节技能组实现组批10路10A：并发同仓，仅新建
  本文件 + qbot_rpg/core/skill_season.py；不改动兄弟路文件）

依据：docs/细化/细化_6c_资源轴与职业机制.md：
  - §2.1 SE1（season 字段 schema：spring/summer/autumn/winter 四枚举，缺省
    =通用=全年可用【四时 L63】）；
  - §2.2 EFF-2（进战懒加载）/ EFF-5（行动校验唯一入口：技能 ∈ 当前季节组
    ∪ 通用组；不在 → 拒绝并提示「此术式与当前时节不合」；引用在回合开始
    懒重读时更新）；
  - §2.3 SC-2（引擎零新状态机：当前季节组引用回合开始懒重读更新）；
  - §0.3 D-05（换季待结算期按旧组校验——旧组即当前生效组口径）；
  - §六 TC-09（春季进战斗选择夏季技能 → 行动校验拒绝；春组/通用正常可用）。
测试目标：qbot_rpg.core.skill_season.{SEASONS, SEASON_ANY, DEFAULT_SEASON,
  SEASON_CTX_KEY, REJECT_SEASON_MISMATCH, parse_season, season_of,
  current_season, skill_in_season, validate_skill_action, SeasonSkillEngine}。

覆盖矩阵（17 用例 = A 解析 5 + B 判定 7 + C 行动校验 3 + D 引擎 2）：
  A 四季解析（SE1）：四枚举原样解析 / 缺省=通用 / 非字符串回落通用 /
    未知值回落通用 / 大小写敏感（P-5）
  B skill_in_season 判定（EFF-5）：当季技能可用 / 通用技能全年可用 /
    非当季不可用 / 通用环境全部可用（EFF-1 战斗外口径）/ 四季互斥
    （夏技春不可用）/ 缺省技能在任意季可用 / ctx 无季节回落通用全可用
  C 行动校验（EFF-5 唯一入口）：非当季 → 被拒不耗回合（结构化判定 +
    reason/code 语义键）/ 当季 → ok / 无 id 条目防御 ok（P-4）
  D SeasonSkillEngine 注入：season_now 注入挂 ctx（幂等）/ override 优先
    + check/usable 委托（EFF-5 引擎入口）

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠（docstring 不写
睡眠/定时器字样）；不引入随机；只写本文件。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from qbot_rpg.core.skill_season import (
    DEFAULT_SEASON,
    REJECT_SEASON_MISMATCH,
    SEASON_ANY,
    SEASON_CTX_KEY,
    SEASONS,
    SeasonSkillEngine,
    current_season,
    parse_season,
    season_of,
    skill_in_season,
    validate_skill_action,
)


# ---------------------------------------------------------------------------
# 夹具辅助
# ---------------------------------------------------------------------------
def _skill(sid: str, season: Optional[str] = None) -> Dict[str, Any]:
    """raw dict 技能条目（season 字段可选；缺省 = 通用，SE1）。"""
    entry: Dict[str, Any] = {"id": sid, "name": sid, "type": "active"}
    if season is not None:
        entry["season"] = season
    return entry


class _ProtoSkill:
    """协议对象技能（模拟 SkillDef 属性访问器形态；G0 注入）。"""

    def __init__(self, sid: str, season: Optional[str] = None) -> None:
        self._id = sid
        self._season = season

    @property
    def id(self) -> str:  # noqa: A003
        return self._id

    @property
    def season(self) -> Optional[str]:
        return self._season


# ===========================================================================
# A 四季解析（SE1：spring/summer/autumn/winter，缺省=通用）
# ===========================================================================
def test_parse_season_four_enum_values() -> None:
    """四枚举原样解析（SE1）。"""
    assert parse_season("spring") == "spring"
    assert parse_season("summer") == "summer"
    assert parse_season("autumn") == "autumn"
    assert parse_season("winter") == "winter"


def test_parse_season_missing_defaults_to_general() -> None:
    """缺省 = 通用（SE1：缺省=通用，全年可用【四时 L63】）。"""
    assert parse_season(None) == SEASON_ANY
    assert DEFAULT_SEASON == SEASON_ANY


def test_parse_season_non_string_falls_back_general() -> None:
    """非字符串值回落通用（防御读取）。"""
    assert parse_season(3) == SEASON_ANY
    assert parse_season(["spring"]) == SEASON_ANY
    assert parse_season({"season": "spring"}) == SEASON_ANY


def test_parse_season_unknown_value_falls_back_general() -> None:
    """未知枚举值回落通用（V9 枚举红拦归校验器，引擎层防御不报错）。"""
    assert parse_season("sumer") == SEASON_ANY
    assert parse_season("rainy") == SEASON_ANY


def test_parse_season_case_sensitive() -> None:
    """大小写敏感（D-06 精神）：大小写变体不属于四枚举 → 通用（P-5）。"""
    assert parse_season("Spring") == SEASON_ANY
    assert parse_season("SUMMER") == SEASON_ANY


def test_season_of_missing_field_is_general() -> None:
    """season 字段缺失 → 通用（SE1 缺省口径）。"""
    assert season_of({"id": "basic_attack"}) == SEASON_ANY
    assert season_of(_ProtoSkill("basic_attack")) == SEASON_ANY


def test_season_of_mapping_and_protocol() -> None:
    """Mapping 直取 + 协议对象属性取（G0 注入口径双形态）。"""
    assert season_of(_skill("spring_skill", "spring")) == "spring"
    assert season_of(_ProtoSkill("winter_skill", "winter")) == "winter"


# ===========================================================================
# B skill_in_season 判定（EFF-5：技能 ∈ 当前季节组 ∪ 通用组 → 可用）
# ===========================================================================
def test_in_season_skill_usable() -> None:
    """当季技能可用（春组在春季可用）。"""
    assert skill_in_season(_skill("春芽术", "spring"), "spring") is True


def test_general_skill_usable_in_any_season() -> None:
    """通用技能全年可用（缺省技能在四季均可用）。"""
    for season in SEASONS:
        assert skill_in_season(_skill("四时术"), season) is True
        assert skill_in_season(_skill("季节共鸣", "general"), season) is True


def test_out_of_season_skill_unusable() -> None:
    """非当季技能不可用（夏季技能在春季不可用）。"""
    assert skill_in_season(_skill("烈日灼烧", "summer"), "spring") is False


def test_general_environment_all_skills_usable() -> None:
    """通用环境（无季节组概念）全部技能可用（EFF-1 战斗外口径）。"""
    assert skill_in_season(_skill("烈日灼烧", "summer"), SEASON_ANY) is True
    assert skill_in_season(_skill("暴雪", "winter"), SEASON_ANY) is True


def test_season_mutual_exclusion() -> None:
    """四季互斥：任一季技能在其余三季均不可用。"""
    for own in SEASONS:
        for other in SEASONS:
            if own != other:
                assert skill_in_season(_skill("s", own), other) is False


def test_protocol_object_judgement() -> None:
    """协议对象技能判定（G0 注入形态）。"""
    assert skill_in_season(_ProtoSkill("烈日灼烧", "summer"), "summer") is True
    assert skill_in_season(_ProtoSkill("烈日灼烧", "summer"), "spring") is False
    assert skill_in_season(_ProtoSkill("四时术"), "autumn") is True


def test_current_season_from_ctx_and_fallback() -> None:
    """ctx 懒重读当前季节（EFF-2/EFF-5）；缺键回落通用（P-3）。"""
    assert current_season({SEASON_CTX_KEY: "spring"}) == "spring"
    assert current_season({}) == SEASON_ANY
    assert current_season({SEASON_CTX_KEY: "sumer"}) == SEASON_ANY
    assert current_season({SEASON_CTX_KEY: 3}) == SEASON_ANY


# ===========================================================================
# C 行动校验（EFF-5 唯一入口：非当季 → 被拒不耗回合）
# ===========================================================================
def test_validate_out_of_season_rejected_no_turn() -> None:
    """非当季 → 被拒不耗回合（TC-09：春季选夏季技能 → 行动校验拒绝）。

    复用 rejected 管道语义：不耗回合、连段不变、可反复尝试——本引擎只出
    结构化判定（ok=False + reason/code），不消耗任何状态（零副作用）。
    """
    result = validate_skill_action(_skill("烈日灼烧", "summer"), "spring")
    assert result["ok"] is False
    assert result["reason"] == REJECT_SEASON_MISMATCH
    assert result["code"] == REJECT_SEASON_MISMATCH
    assert result["skill_id"] == "烈日灼烧"
    assert result["season"] == "spring"
    # 可反复尝试：重复判定结果一致（不耗状态）
    again = validate_skill_action(_skill("烈日灼烧", "summer"), "spring")
    assert again == result


def test_validate_in_season_ok() -> None:
    """当季/通用技能 → ok 可施放（EFF-5 放行侧）。"""
    r1 = validate_skill_action(_skill("春芽术", "spring"), "spring")
    assert r1["ok"] is True and r1["reason"] == ""
    assert r1["code"] is None
    r2 = validate_skill_action(_skill("四时术"), "winter")
    assert r2["ok"] is True and r2["season"] == "winter"


def test_validate_missing_skill_id_defensive_ok() -> None:
    """无 id 条目防御放行（P-4：skill_id=None 仍正常判定季节）。"""
    result = validate_skill_action({"season": "winter"}, "spring")
    assert result["ok"] is False
    assert result["skill_id"] is None
    assert result["reason"] == REJECT_SEASON_MISMATCH
    ok = validate_skill_action({"season": "spring"}, "spring")
    assert ok["ok"] is True and ok["skill_id"] is None


# ===========================================================================
# D SeasonSkillEngine（构造器注入：season_now / season_override / audit）
# ===========================================================================
def test_engine_injects_season_now_into_ctx() -> None:
    """构造器 season_now 注入挂 ctx（幂等：不覆盖调用方显式注入）。"""
    eng = SeasonSkillEngine(season_now="summer")
    ctx: Dict[str, Any] = {}
    assert eng.current_season(ctx) == "summer"
    assert ctx.get(SEASON_CTX_KEY) == "summer"
    # 幂等：ctx 已显式注入时构造器不覆盖
    ctx2: Dict[str, Any] = {SEASON_CTX_KEY: "autumn"}
    eng2 = SeasonSkillEngine(season_now="summer")
    assert eng2.current_season(ctx2) == "autumn"
    assert ctx2[SEASON_CTX_KEY] == "autumn"


def test_engine_override_and_check_usable() -> None:
    """season_override 优先 + check/usable 委托（EFF-5 引擎入口）。"""
    eng = SeasonSkillEngine(season_override="spring")
    skill_summer = _skill("烈日灼烧", "summer")
    skill_general = _skill("四时术")
    # override 优先于 ctx
    r = eng.check({SEASON_CTX_KEY: "winter"}, skill_summer)
    assert r["ok"] is False and r["season"] == "spring"
    # 当季/通用放行
    assert eng.check({}, _skill("春芽术", "spring"))["ok"] is True
    assert eng.check({}, skill_general)["ok"] is True
    # usable 布尔快捷
    assert eng.usable({}, skill_summer) is False
    assert eng.usable({}, skill_general) is True
    # 默认引擎（无注入）读 ctx
    assert SeasonSkillEngine().check({SEASON_CTX_KEY: "summer"},
                                     skill_summer)["ok"] is True
