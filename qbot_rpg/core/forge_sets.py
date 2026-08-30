"""M9 锻造·批7·路7A：套装结构服务（qbot_rpg/core/forge_sets.py）——forge_sets 结构解析/
校验/可组成查询/技能契约。

文件名：qbot_rpg/core/forge_sets.py
创建时间：2026-08-30
作者：Hermes 子agent-7A（M9 锻造实现组批7·路7A：并发同仓，仅新建本文件 +
  tests/unit/test_forge_sets.py；不改动批0 forge_models.py 等既有文件、fixtures）

功能描述：P1 套装（forge_sets）结构层四服务，供 /套装 指令、编辑器套装页、M12 编辑器复用：
  1) parse_sets(modules)：forge.json sets 段解析 → ForgeSet 列表（alpha 全字段 /
     beta 引用 variant：beta 缺 skills 时继承同族 alpha 档位，VAR-01「两记录 skills
     默认共享」；对齐批0 ForgeSet/SetSkill Def 解析，返回批0 ForgeSet）。
  2) validate_sets(modules)：套装校验 → dict {ok, errors, warnings, rule_counts}：
     硬 V1 集合查重 (family_id,variant) / V2 件数范围（pieces 1~5）/ V3 技能引用存在
     （skills≥1、skill 非空、piece_count∈{2,3,5}、level∈{1,2,3}）；黄 W1 件数不足建议 /
     W2 技能描述缺（effect_ref 空=占位）/ W3 无套装数（段空但 sets_enabled=true）/
     W4 同族单记录（缺 α 或 β 对照）——V1~V3 委托/包装批0 validate_forge 的 2c2d
     sets 段（trees 合法时含节点引用/部位/αβ 孔位交叉校验），本路仅补纯结构兜底
     （无树也可验）与 W1~W4 结构黄（批0 未覆盖项）。
  3) set_lookup(player, sets)：玩家当前装配可激活套装查询（P1 预留：只查已有装配件
     可组成哪几套；标 {set_id, family_id, pieces_have, pieces_total, ready}；
     ready=False 不激活；族级合并件数按 VAR-03 α/β 混穿口径）。
  4) set_effects_contract(set)：套装技能契约（SetSkill 展开：skill_id/描述/触发段；
     仅数据契约不含执行——激活/结算归 M12 编辑器或后续）。
  纯函数确定性（同刻同参必同值），零 IO 零 NoneBot；构造器配置注入 + 缺省兜底。

依据：
  - docs/细化/细化_2c2d_锻造套装与客制.md：§一（SET-01~08 + SK-01~04 字段表、§1.2.1）、
    §1.3（ACT-01~06：2/3/5 档位判定/无 4 档/多技能并行/混搭）、§1.4（VAR-01~03：
    一记录一 variant / 差异落节点 / αβ 混穿归族计数）、§五（校验器 V1~V8 硬 + W1~W4 黄）、
    §1.5（/套装 指令面板数据源）、§四 接缝表（4b EQP-03 set_tracker / INS-07 set_tag 消费方）。
  - docs/m9_shared_contract.md：§四（Set 字段表 SET-01~08 + SetSkill SK-01~04）、
    §六（2c2d 校验 V1-V8/W1-W4）、§七（validate_forge(modules, report) 接口签名）。
  - qbot_rpg/content/forge_models.py（批0）：ForgeSet/SetSkill Def 类 + validate_forge
    已含 2c2d V1~V8/W1~W4——本文件复用校验器，不重写其语义。
  - 边界声明：本路仅「结构 + 校验 + 查询 + 契约」，套装技能激活/结算执行归 M12
    编辑器或后续批次（ACT-05 动态重算 / ACT-06 混搭进 equip_snapshot 不在本路）。

【工程补白 · 显式标注】（契约/细化未显式定义处的实现口径，标 F-x；不得新增定稿外机制行为）：
  F-1  beta 引用 alpha：VAR-01「两条记录 skills 档位默认共享」→ parse_sets 对 variant=
      beta 且缺 skills 的记录，从同族 alpha 记录继承 skills（档位共享），并在 raw 附
      `_skills_inherited_from`（非 schema 补白键）供追溯；alpha 无记录/无 skills 则
      beta 保持缺省（交 V3 红拦，防隐式空档）。
  F-2  validate_sets 委托策略：V1~V3 硬校验以批0 validate_forge 的 sets 段结果为主
      （source=batch0；trees 合法时含 V2 节点引用/部位 + W1 孔位对照等交叉校验）；
      当 forge 无 trees（批0 短路直接 return）时本路纯结构 V1~V3 兜底（source=route7a）。
      结果按 (rule, field) 去重合并，避免同一条双报。
  F-3  W1~W4 为本路补充结构黄（批0 2c2d W1~W4 语义不同：αβ 孔位/trace/settings 关/
      level 超封顶——委托结果以 source=batch0 保留编号，不与之混编）：W1 pieces<5 件数
      不足建议（SET-04 ≤5 可配，ACT-02 需 5 件满配档）/ W2 skill 行 effect_ref 空=占位
      （SK-04：占位技能只显示不结算）/ W3 sets 段空但 settings.sets_enabled=true 配置
      意图存疑（对仗批0 客制 V8 空段提示）/ W4 同族仅单记录缺变体对照（VAR-01 两条）。
  F-4  set_lookup 装配源：player["set_tracker"]（4b EQP-03，族id→件数）优先；否则从
      player["equipped"]/["equip_nodes"]/["equip_snapshot"] 提取装配节点 id（str 或
      含 node_id/id 键的条目）求与 pieces 交集。ready=族级件数≥2（ACT-02 最低 2 件，
      VAR-03 混穿合并）；P1 不读技能库，只做件数级可组成查询。
  F-5  set_effects_contract 描述来源：SetSkill 无 desc 字段（SK-01~04 无 desc 键），
      desc 取 effect_ref 效果接线（非空）或占位文案；skill 中文名需 6a 技能库，
      P1 无技能库依赖 → skill_id 即展示键（文档 SK-02 对齐 6a 契约，接线归后续）。
  F-6  输入形态：set_lookup/set_effects_contract 的 set 接受 ForgeSet（批0）或 raw
      dict 双形态（对齐 forge_progress F-6 归一惯例）；player 缺省非 Mapping → 空装配。
  F-7  validate_sets 委托基于「解析后有效视图」：先 parse_sets（beta 继承 alpha skills
      补全），把解析后 sets 回填 modules 再委托批0 validate_forge——VAR-01 允许 beta
      缺 skills 继承共享档位，若按原始 raw 校验会把合法 beta 继承误红拦（V3）。

铁律：零 NoneBot import；纯函数确定性（同刻同参必同值）；不写定时器/睡眠调用
      （M43 零定时器探针）；平台无关；不引入随机；每功能可追溯（文件头标注依据）。
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence, Tuple, cast

from qbot_rpg.content.forge_models import (
    ForgeSet,
    SET_LEVEL_MAX,
    SET_PIECE_COUNTS,
    validate_forge,
)

__all__ = [
    "MIN_ACTIVATE_PIECES",
    "FULL_SET_PIECES",
    "parse_sets",
    "validate_sets",
    "set_lookup",
    "set_effects_contract",
]

# ACT-02：2 件最低档激活（SET-04 / 2c2d §1.3）
MIN_ACTIVATE_PIECES: int = 2
# SET-04：5 件满配（ACT-02 5 件→Lv3 满配档）
FULL_SET_PIECES: int = 5

# set_lookup 装配读取键（F-4：set_tracker 优先，其次装配节点集）
_EQUIPPED_KEYS: Tuple[str, ...] = ("equipped", "equip_nodes", "equip_snapshot")
_NODE_REF_KEYS: Tuple[str, ...] = ("node_id", "id")


# =====================================================================================
# 输入归一（F-6：set 双形态 → ForgeSet）
# =====================================================================================
def _coerce_set(set_obj: object) -> Optional[ForgeSet]:
    """set 归一：ForgeSet（批0）原样 / raw Mapping → ForgeSet.from_entry / 其它 → None。"""
    if isinstance(set_obj, ForgeSet):
        return set_obj
    if isinstance(set_obj, Mapping):
        return cast(ForgeSet, ForgeSet.from_entry(set_obj))
    return None


def _is_mapping_seq(value: object) -> bool:
    """list/tuple（非 str）判定（条目序列形态）。"""
    return isinstance(value, (list, tuple)) and not isinstance(value, (str, bytes))


# =====================================================================================
# parse_sets：forge.json sets 段解析（alpha 全字段 / beta 引用 variant；F-1）
# =====================================================================================
def _raw_sets(modules: Mapping[str, object]) -> List[Mapping[str, object]]:
    """从 modules 提取 forge.sets 条目序列（缺失/非 list → 空，无 sets 段合法）。"""
    forge = modules.get("forge")
    if not isinstance(forge, Mapping):
        return []
    raw = forge.get("sets")
    if not _is_mapping_seq(raw):
        return []
    return [e for e in cast(Sequence[object], raw) if isinstance(e, Mapping)]


def _alpha_skills_by_family(
    parsed: Sequence[ForgeSet],
) -> Dict[str, List[Mapping[str, object]]]:
    """族 id → 同族 alpha 记录的 skills 原始行（beta 继承源；VAR-01 档位共享）。"""
    out: Dict[str, List[Mapping[str, object]]] = {}
    for s in parsed:
        if s.variant != "alpha":
            continue
        raw_skills = s.raw.get("skills")
        rows: List[Mapping[str, object]] = []
        if isinstance(raw_skills, list):
            for e in raw_skills:
                if isinstance(e, Mapping):
                    rows.append(e)
        if rows:
            out.setdefault(s.id, rows)
    return out


def parse_sets(modules: Mapping[str, object]) -> List[ForgeSet]:
    """forge.json sets 段解析 → 批0 ForgeSet 列表（alpha 全字段 / beta 引用 variant）。

    入参 modules: dict（含 "forge" 键，forge 顶层是 obj 非 list——trees/sets/settings 段）。
    出参 list[ForgeSet]: 每条记录一个 ForgeSet；variant=beta 且缺 skills 的记录从同族
      alpha 继承 skills 档位（F-1，VAR-01），raw 附 `_skills_inherited_from` 追溯键；
      sets 段缺失/空/非 list → []（无 sets 段是合法空集，不报错）。
    核心逻辑: 先 ForgeSet.from_entry 逐条解析（对齐批0 Def），再按族补 beta 继承。
    """
    raw = _raw_sets(modules)
    if not raw:
        return []
    parsed = [cast(ForgeSet, ForgeSet.from_entry(e)) for e in raw]
    alpha_by_family = _alpha_skills_by_family(parsed)
    out: List[ForgeSet] = []
    for s in parsed:
        if s.variant == "beta" and not s.raw.get("skills") and s.id in alpha_by_family:
            new_raw: Dict[str, object] = dict(s.raw)
            new_raw["skills"] = list(alpha_by_family[s.id])
            new_raw["_skills_inherited_from"] = "%s:alpha" % s.id
            out.append(cast(ForgeSet, ForgeSet.from_entry(new_raw)))
        else:
            out.append(s)
    return out


# =====================================================================================
# validate_sets：套装校验（V1~V3 硬 + W1~W4 黄；委托批0 + 本路结构兜底）
# =====================================================================================
def _collector_item_kind(item: Mapping[str, object]) -> str:
    """dict 形态收集器条目取 kind：args=(module, field, kind)。"""
    args = item.get("args")
    if isinstance(args, (list, tuple)) and len(args) >= 3:
        return str(args[2])
    return ""


def _collector_item_field(item: Mapping[str, object]) -> str:
    """dict 形态收集器条目取 field（args 第 2 位）。"""
    args = item.get("args")
    if isinstance(args, (list, tuple)) and len(args) >= 3:
        return str(args[1])
    return ""


def _norm_collector_item(item: Mapping[str, object], source: str) -> Dict[str, object]:
    """收集器条目 → 结构化 {level, rule, field, msg, detail, source}。"""
    kwargs = item.get("kwargs")
    detail = dict(kwargs) if isinstance(kwargs, Mapping) else {}
    rule = str(detail.get("rule", ""))
    msg = str(detail.get("msg", ""))
    field = _collector_item_field(item)
    kind = _collector_item_kind(item)
    # 批0 2c2d 编号映射到本路 V/W 语义（sets 段专属；F-2 保留 source 区分）
    level = _map_batch0_level(rule, kind)
    return {
        "level": level,
        "rule": rule,
        "field": field,
        "msg": msg,
        "detail": detail,
        "source": source,
        "kind": kind,
    }


def _map_batch0_level(rule: str, kind: str) -> str:
    """批0 sets 段 rule/kind → 本路 V/W 语义标签（V1 查重 / V2 件数 / V3 技能引用）。"""
    if rule in ("set_id_required", "set_variant_invalid", "set_variant_duplicate"):
        return "V1"
    if rule.startswith("set_piece") or rule in (
            "set_pieces_required", "set_pieces_too_many", "set_not_object",
            "sets_not_list"):
        return "V2"
    if rule.startswith("set_skill") or rule in ("set_skills_required",):
        return "V3"
    # 委托黄（批0 2c2d W 语义：αβ 孔位 / settings 关 / level 超封顶）
    if kind in ("2c2d-W1", "2c2d-W4", "W3"):
        return "W"
    return kind if kind else "V2"


def _family_list(sets: Sequence[ForgeSet]) -> List[str]:
    """族 id 有序去重列表。"""
    seen: List[str] = []
    for s in sets:
        if s.id and s.id not in seen:
            seen.append(s.id)
    return seen


def _resolved_modules(
    modules: Mapping[str, object],
    sets: Sequence[ForgeSet],
) -> Mapping[str, object]:
    """解析后视图：forge.sets 段替换为 parse_sets 输出（beta 继承 alpha skills 生效）的 raw。

    VAR-01「α/β 两记录 skills 档位默认共享」是合法特性，beta 缺 skills 经 parse_sets 继承
    补全后才构成有效数据——批0 validate_forge 校验的应是「有效数据」而非原始 raw，否则
    beta 缺 skills 会被批0 V3 误红拦。本函数返回 modules 浅拷贝（forge.sets 替换为
    解析后各记录 raw，含 `_skills_inherited_from` 补白键，对批0 校验无害）。
    """
    if not isinstance(modules, Mapping):
        return modules
    forge = modules.get("forge")
    if not isinstance(forge, Mapping):
        return modules
    new_forge: Dict[str, object] = dict(forge)
    new_forge["sets"] = [dict(s.raw) for s in sets]
    new_modules: Dict[str, object] = dict(modules)
    new_modules["forge"] = new_forge
    return new_modules


def _configured_piece_counts(modules: Mapping[str, object]) -> Tuple[int, ...]:
    """配置档位集合（P1-1 裁决 2026-08-30 配置化）：读 settings.forge.set_piece_counts
    正整数列表去重升序；缺省/非合法 → SET_PIECE_COUNTS 默认 (2, 3, 5)。"""
    settings_v = modules.get("settings")
    if isinstance(settings_v, Mapping):
        forge_v = settings_v.get("forge")
        if isinstance(forge_v, Mapping):
            spc = forge_v.get("set_piece_counts")
            if isinstance(spc, (list, tuple)):
                cleaned = tuple(sorted({
                    x for x in spc
                    if isinstance(x, int) and not isinstance(x, bool) and x >= 1
                }))
                if cleaned:
                    return cleaned
    return SET_PIECE_COUNTS


def _check_structure_v(
    modules: Mapping[str, object], sets: Sequence[ForgeSet]
) -> List[Dict[str, object]]:
    """本路纯结构 V1~V3 兜底（F-2：无树时批0 短路，本路保证 sets 可独立验）。

    V1 集合查重 (family_id,variant) / V2 件数范围（pieces 1~5，每件非空 str）/
    V3 技能引用存在（skills≥1、skill 非空、piece_count∈配置档位集合（缺省 {2,3,5}）、
    level∈{1,2,3}）。档位集合读 settings.forge.set_piece_counts（P1-1 裁决配置化）。
    """
    allowed_pc: Tuple[int, ...] = _configured_piece_counts(modules)
    errors: List[Dict[str, object]] = []
    seen_combo: set = set()
    for si, s in enumerate(sets):
        base = "forge.sets.%d" % si
        combo = (s.id, s.variant)
        if combo in seen_combo:
            errors.append({
                "level": "V1", "rule": "set_variant_duplicate",
                "field": "%s.variant" % base,
                "msg": "(id, variant)=%r 组合重复（V1）" % (combo,),
                "detail": {"id": s.id, "variant": s.variant}, "source": "route7a",
            })
        else:
            seen_combo.add(combo)
        pieces = s.pieces
        if not pieces:
            errors.append({
                "level": "V2", "rule": "set_pieces_required",
                "field": "%s.pieces" % base,
                "msg": "pieces 必填（≥1 个 forge 树节点 id，V2）",
                "detail": {}, "source": "route7a",
            })
        elif len(pieces) > FULL_SET_PIECES:
            errors.append({
                "level": "V2", "rule": "set_pieces_too_many",
                "field": "%s.pieces" % base,
                "msg": "pieces ≤%d 项（V2）" % FULL_SET_PIECES,
                "detail": {"count": len(pieces)}, "source": "route7a",
            })
        skill_defs = s.skill_defs()
        if not skill_defs:
            errors.append({
                "level": "V3", "rule": "set_skills_required",
                "field": "%s.skills" % base,
                "msg": "skills 必填 ≥1 行（V3）",
                "detail": {}, "source": "route7a",
            })
        for ki, sk in enumerate(skill_defs):
            kbase = "%s.skills.%d" % (base, ki)
            if not isinstance(sk.skill, str) or not sk.skill:
                errors.append({
                    "level": "V3", "rule": "set_skill_id_required",
                    "field": "%s.skill" % kbase,
                    "msg": "skill 必填（6a 技能库 id，V3）",
                    "detail": {}, "source": "route7a",
                })
            if sk.piece_count not in allowed_pc:
                errors.append({
                    "level": "V3", "rule": "set_skill_piece_count_invalid",
                    "field": "%s.piece_count" % kbase,
                    "msg": ("piece_count %r 不在配置档位集合 %s（V3）"
                            % (sk.piece_count, list(allowed_pc))),
                    "detail": {"piece_count": sk.piece_count}, "source": "route7a",
                })
            if not isinstance(sk.level, int) or sk.level < 1 or sk.level > SET_LEVEL_MAX:
                errors.append({
                    "level": "V3", "rule": "set_skill_level_invalid",
                    "field": "%s.level" % kbase,
                    "msg": "level ∈ {1,2,3}（默认封顶，V3 硬）" % (),
                    "detail": {"level": sk.level}, "source": "route7a",
                })
    return errors


def _check_supplement_w(
    modules: Mapping[str, object],
    sets: Sequence[ForgeSet],
) -> List[Dict[str, object]]:
    """本路补充结构黄 W1~W4（F-3：批0 未覆盖的 sets 结构层建议）。

    W1 件数不足建议（pieces<5 无法达成 5 件满配档）/ W2 技能描述缺（effect_ref 空=占位）/
    W3 无套装数（段空但 sets_enabled=true 配置意图存疑）/ W4 同族单记录（缺 α/β 对照）。
    """
    warnings: List[Dict[str, object]] = []
    forge = modules.get("forge")
    settings = forge.get("settings") if isinstance(forge, Mapping) else None
    sets_enabled = True
    if isinstance(settings, Mapping) and isinstance(settings.get("sets_enabled"), bool):
        sets_enabled = cast(bool, settings["sets_enabled"])

    # W3 无套装数：段缺失/空 且 settings 开
    if sets_enabled and not sets:
        warnings.append({
            "level": "W3", "rule": "sets_empty",
            "field": "forge.sets",
            "msg": "无套装数据（sets 段缺失/空但 sets_enabled=true，配置意图存疑；"
                   "若有意关闭请设 sets_enabled=false，W3 黄）",
            "detail": {}, "source": "route7a",
        })

    # W4 同族单记录 + W1 件数不足 + W2 技能描述缺（逐套）
    family_variants: Dict[str, set] = {}
    for s in sets:
        family_variants.setdefault(s.id, set()).add(s.variant or "")
    for s in sets:
        base = "forge.sets.%s" % s.id
        # W4：同族仅单记录（VAR-01：同一套装族 = 同 id 两条记录）
        fam = family_variants.get(s.id, set())
        if len(fam) < 2:
            warnings.append({
                "level": "W4", "rule": "set_family_single_variant",
                "field": base,
                "msg": "套装族 %r 仅单变体 %r，缺 α/β 对照记录（VAR-01，W4 黄）"
                       % (s.id, s.variant),
                "detail": {"id": s.id, "variant": s.variant}, "source": "route7a",
            })
        # W1：件数不足建议（pieces<5 无法达成 5 件满配档，ACT-02）
        if s.pieces and len(s.pieces) < FULL_SET_PIECES:
            warnings.append({
                "level": "W1", "rule": "set_pieces_under_5",
                "field": "%s.pieces" % base,
                "msg": "套装 %r 仅 %d 件，无法达成 %d 件满配档（Lv3）；建议补齐（W1 黄）"
                       % (s.id, len(s.pieces), FULL_SET_PIECES),
                "detail": {"id": s.id, "count": len(s.pieces)}, "source": "route7a",
            })
        # W2：技能描述缺（effect_ref 空=占位技能只显示不结算，SK-04）
        for ki, sk in enumerate(s.skill_defs()):
            if not isinstance(sk.effect_ref, str) or not sk.effect_ref:
                warnings.append({
                    "level": "W2", "rule": "set_skill_effect_ref_missing",
                    "field": "%s.skills.%d.effect_ref" % (base, ki),
                    "msg": "skill %r 无效果接线（effect_ref 空=占位技能，只显示不结算，W2 黄）"
                           % (sk.skill,),
                    "detail": {"skill": sk.skill, "piece_count": sk.piece_count},
                    "source": "route7a",
                })
    return warnings


def validate_sets(
    modules: Mapping[str, object],
    report: Optional[object] = None,
) -> Dict[str, object]:
    """套装校验（V1 集合查重 / V2 件数范围 / V3 技能引用存在；W1 件数不足建议 /
    W2 技能描述缺 / W3 无套装数 / W4 同族单记录）→ dict。

    入参 modules: dict（含 "forge" 键；可选 "items"/"enemies" 供批0 交叉校验）。
    出参 dict: {ok, sets_count, families, errors, warnings, rule_counts}。
      - errors:  硬错误列表（V1/V2/V3），source=batch0（委托批0 validate_forge 2c2d
        sets 段）或 route7a（本路纯结构兜底，F-2）；(rule, field) 去重合并。
      - warnings: 黄提示列表（委托批0 sets 黄 + 本路 W1~W4）。
      - ok:       errors 为空。
    委托说明: 批0 validate_forge(modules, report) 以 dict 形态收集器调用，筛 field
      前缀 forge.sets 的 sets 段结果（含 trees 合法时的节点引用/部位/αβ 孔位交叉校验）；
      forge 无 trees 时批0 短路，本路 _check_structure_v 兜底保证 V1~V3 仍可验。
    report 可选: 传入 report（error/warning 鸭子类型或 dict 收集器）时同步追加结果
      （对齐批0 收集器形态），缺省 None 仅返回 dict。
    """
    collector: Dict[str, List[Mapping[str, object]]] = {"errors": [], "warnings": [], "notes": []}
    sets = parse_sets(modules)  # 先解析（beta 继承 alpha skills 生效，VAR-01）
    # 委托批0：基于「解析后有效数据」（F-2/F-7：beta 缺 skills 由 parse_sets 继承补全后
    # 才构成有效配置，raw 校验会把合法 beta 继承误红拦——见 _resolved_modules）
    validated_modules = _resolved_modules(modules, sets)
    validate_forge(validated_modules, collector)  # 委托批0（2c2d sets 段全量校验）

    errors: List[Dict[str, object]] = []
    warnings: List[Dict[str, object]] = []

    # 批0 委托结果：筛 forge.sets 前缀
    for e in collector["errors"]:
        if _collector_item_field(e).startswith("forge.sets"):
            errors.append(_norm_collector_item(e, "batch0"))
    for w in collector["warnings"]:
        if _collector_item_field(w).startswith("forge.sets"):
            warnings.append(_norm_collector_item(w, "batch0"))

    # 本路纯结构 V1~V3 兜底（F-2）+ W1~W4 补充（F-3）
    errors.extend(_check_structure_v(modules, sets))
    warnings.extend(_check_supplement_w(modules, sets))

    # (rule, field) 去重（委托与本路兜底可能双报同一缺陷）
    errors = _dedup_items(errors)
    warnings = _dedup_items(warnings)

    rule_counts: Dict[str, int] = {}
    for it in errors + warnings:
        rule = str(it.get("rule", ""))
        rule_counts[rule] = rule_counts.get(rule, 0) + 1

    result: Dict[str, object] = {
        "ok": not errors,
        "sets_count": len(sets),
        "families": _family_list(sets),
        "errors": errors,
        "warnings": warnings,
        "rule_counts": rule_counts,
    }
    if report is not None:
        _forward(report, errors, warnings)
    return result


def _dedup_items(items: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    """按 (rule, field) 去重（保持首次出现序）。"""
    seen: set = set()
    out: List[Dict[str, object]] = []
    for it in items:
        key = (str(it.get("rule", "")), str(it.get("field", "")))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def _forward(report: object, errors: Sequence[Dict[str, object]],
             warnings: Sequence[Dict[str, object]]) -> None:
    """结果同步追加到外部收集器（鸭子类型：error/warning 方法 或 dict 三形态）。"""
    for it in errors:
        _emit_like(report, "error", str(it.get("field", "")), "route7a",
                   rule=it.get("rule"), msg=it.get("msg"))
    for it in warnings:
        _emit_like(report, "warning", str(it.get("field", "")), "route7a",
                   rule=it.get("rule"), msg=it.get("msg"))


def _emit_like(report: object, method: str, field: str, kind: str, **detail: object) -> None:
    """外部收集器追加（对齐批0 _emit 三形态：方法 → _err/_warn → dict 兜底）。"""
    fn = getattr(report, method, None)
    if not callable(fn):
        _MAP = {"error": "_err", "warning": "_warn", "note": "_note"}
        fn = getattr(report, _MAP.get(method, "_" + method), None)
    if callable(fn):
        fn("forge", field, kind, **detail)
        return
    if isinstance(report, dict):
        key = {"error": "errors", "warning": "warnings", "note": "notes"}.get(method)
        lst = report.get(key)
        if isinstance(lst, list):
            lst.append({"method": method, "args": ("forge", field, kind),
                        "kwargs": dict(detail)})


# =====================================================================================
# set_lookup：玩家当前装配可激活套装查询（P1 预留；F-4）
# =====================================================================================
def _equipped_node_ids(player: Mapping[str, object]) -> set:
    """装配节点 id 集（F-4：equipped/equip_nodes/equip_snapshot，str 或含 node_id/id 条目）。"""
    out: set = set()
    for key in _EQUIPPED_KEYS:
        v = player.get(key)
        if not _is_mapping_seq(v):
            continue
        for e in cast(Sequence[object], v):
            if isinstance(e, str) and e:
                out.add(e)
            elif isinstance(e, Mapping):
                for ref_key in _NODE_REF_KEYS:
                    x = e.get(ref_key)
                    if isinstance(x, str) and x:
                        out.add(x)
    return out


def _set_tracker(player: Mapping[str, object]) -> Dict[str, int]:
    """4b EQP-03 set_tracker（族 id → 件数）读取（优先装配源）。"""
    t = player.get("set_tracker")
    if not isinstance(t, Mapping):
        return {}
    out: Dict[str, int] = {}
    for k, v in t.items():
        if isinstance(k, str) and k and isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = int(v)
    return out


def set_lookup(player: object, sets: Sequence[object]) -> List[Dict[str, object]]:
    """玩家当前装配可激活套装查询（P1 预留：只查已有装配件可组成哪几套，不激活）。

    入参 player: 玩家状态（Mapping：set_tracker 优先，回退 equipped/equip_nodes/
      equip_snapshot 装配节点集；非 Mapping → 空装配确定性兜底）；
             sets: 套装列表（ForgeSet 或 raw dict 双形态，F-6）。
    出参 list[dict]: 每条套装记录一个查询结果——
      {set_id, family_id, pieces_have, pieces_total, ready, variant, name,
       family_pieces_have, family_pieces_total}。
      - pieces_have / pieces_total: 记录级（仅本 variant 装配件数 / 该记录件数）。
      - family_pieces_have / family_pieces_total: 族级（VAR-03 α/β 混穿合并计数）。
      - ready: 族级件数 ≥2（ACT-02 最低 2 件激活档；ready=False 不激活，激活执行归后续）。
    核心逻辑: 记录级件数 = |pieces ∩ 装配节点|（或 set_tracker[族id]）；族级件数 =
      同族全部记录 pieces 并集 ∩ 装配节点（混穿合并）。P1 不做技能结算（ACT-05 归后续）。
    """
    if not isinstance(player, Mapping):
        player = {}
    p = cast(Mapping[str, object], player)
    equipped = _equipped_node_ids(p)
    tracker = _set_tracker(p)

    fam_pieces: Dict[str, set] = {}
    for s in sets:
        fs = _coerce_set(s)
        if fs is None:
            continue
        fam_pieces.setdefault(fs.id, set()).update(fs.pieces)

    out: List[Dict[str, object]] = []
    for s in sets:
        fs = _coerce_set(s)
        if fs is None or not fs.id:
            continue
        if fs.id in tracker:
            rec_have = tracker[fs.id]
            fam_have = tracker[fs.id]
        else:
            rec_have = len(set(fs.pieces) & equipped)
            fam_have = len(fam_pieces.get(fs.id, set()) & equipped)
        out.append({
            "set_id": fs.id,
            "family_id": fs.id,
            "variant": fs.variant,
            "name": fs.name,
            "pieces_have": rec_have,
            "pieces_total": len(fs.pieces),
            "family_pieces_have": fam_have,
            "family_pieces_total": len(fam_pieces.get(fs.id, set())),
            "ready": bool(fam_have >= MIN_ACTIVATE_PIECES),
        })
    return out


# =====================================================================================
# set_effects_contract：套装技能契约（SetSkill 展开；F-5）
# =====================================================================================
def set_effects_contract(set_obj: object) -> Dict[str, object]:
    """套装技能契约（SetSkill 展开：skill_id/描述/触发段——仅数据契约不含执行）。

    入参 set_obj: 单条套装（ForgeSet 或 raw dict，F-6）。
    出参 dict: {set_id, family_id, variant, name, codex_group, enabled, pieces_total,
      skills, ok}；skills 每条 {skill_id, piece_count, level, effect_ref, trigger, desc}。
      - trigger: 触发段描述（ACT-02：穿 piece_count 件激活该 skill Lv level）。
      - desc:    技能描述（effect_ref 效果接线非空 → 接线文本；空 → 占位技能文案 SK-04）。
    不含执行: 不读取玩家装配、不判激活状态、不结算效果（激活/结算归 M12 或后续）。
    """
    s = _coerce_set(set_obj)
    if s is None or not s.id:
        return {"ok": False, "reason": "invalid_set", "skills": [], "set_id": "",
                "family_id": "", "variant": None, "name": "", "codex_group": "",
                "enabled": True, "pieces_total": 0}
    skills: List[Dict[str, object]] = []
    for sk in s.skill_defs():
        sid = sk.skill or ""
        pc = sk.piece_count
        lv = sk.level
        er = sk.effect_ref or ""
        desc = "效果接线：%s" % er if er else "占位技能（仅登记，只显示不结算）"
        trigger = "穿 %s 件激活 %s Lv%s" % (pc, sid, lv)
        skills.append({
            "skill_id": sid,
            "piece_count": pc,
            "level": lv,
            "effect_ref": er,
            "trigger": trigger,
            "desc": desc,
        })
    return {
        "set_id": s.id,
        "family_id": s.id,
        "variant": s.variant,
        "name": s.name,
        "codex_group": s.codex_group or s.id,
        "enabled": s.enabled if s.enabled is not None else True,
        "pieces_total": len(s.pieces),
        "skills": skills,
        "ok": True,
    }
