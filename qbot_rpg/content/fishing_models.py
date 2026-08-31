"""M10 钓鱼数据层 · 独立模块（路 0C）：fishing.json 数据模型 Def 类 + 专项校验器。

文件名：fishing_models.py
创建时间：2026-08-31
作者：Hermes 子agent-0C（M10 钓鱼实现组路0C：并发同仓，仅新建本文件 +
tests/unit/test_fishing_models.py，独占 loader.py/field_meta.py 登记行）

功能描述：
  - FishDef / KingEventDef 两个 frozen dataclass（ID/名称冗余铁律：继承 BaseDef
    承载 id+name 冗余镜像 raw；from_entry 解析；字段访问器逐字段暴露）。
  - validate_fishing(modules, report) 纯函数（(modules, report) 鸭子类型）：
    V1~V6 硬校验（失败写红=加载失败）+ W1 黄提示（simple/off 模式 king 数据
    不生效，不阻断）。规则全表见共享契约 §三 + 细化 2c1a §五。
  - fishing_module_meta() 返回 ModuleMeta（entry_type="object"——fishing.json
    顶层是 obj 非 list，对齐 forge 形态；fields={} 空表防泛型误拦，专项全权）。
  - fishing_settings_meta() 返回 settings.fishing 段 FieldMeta（自包含定义，
    防 field_meta↔fishing 循环依赖——对齐 forge_settings 自包含口径）。

依据：
  - docs/m10_shared_contract.md（批0 接口权威）：§一 settings.fishing 段 9 键 /
    §二 fishing.json Fish 行 F-01~F-14 / §三 校验器 V1-V4 硬+W1 黄（V5/V6 扩展）/
    §四 路分工（本路=路0C 独占 loader/field_meta）。
  - docs/细化/细化_2c1a_鱼种数据与冠级.md（§一 字段 schema / §三 鱼王 K-01~K-07 /
    §五 校验器规则 V1-V6 硬+W1 黄 / §六 验收 TC-18~22b）。
  - 模式参考：qbot_rpg/content/forge_models.py（validate_forge + _emit 三形态
    收集器 + forge_module_meta）；qbot_rpg/content/dungeon_models.py
    （validate_dungeons 宽松引用模式：maps 模块缺失 → 引用检查宽松跳过）；
    qbot_rpg/content/field_meta.py（forge_module_meta/forge_settings_meta 登记口径）。

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查，不冒充契约行号）：
  1. fishing.json 顶层是 obj 非 list（共享契约 §〇）。validate_fishing 读取
     modules["fishing"] 为 Mapping：species 数组 + 可选 king 数组。非 Mapping
     （缺失/形态异常）→ 跳过不硬拦（对齐既有校验器「模块未接线默认放行」惯例）。
  2. settings.fishing 读取（V2/V3/V4 依赖）：modules["settings"]["fishing"] 段
     缺失/空 → 按共享契约 §一「加载容错」用默认值兜底：mode="full"、
     crown_thresholds={reverse:5,silver:85,gold:95}、bait_ids=空（→ V3 正向
     引用检查宽松跳过，不误拦）。段存在时逐键校验。
  3. V5 防空池：细化 1.0 D-02 称「species 全空 → V1 硬错（防空池）」，共享契约
     §三 V1 仅定义区间规则、TC-22b 将「species 空数组」归 V5/V6 扩展校验——
     按接口权威（共享契约）走 V5 硬错（rule=species_empty），偏差见 contract_deviations。
  4. V5 含 king[].species_id 解析：细化 V5 明示「含 king[].species_id 解析」——
     king 表行 species_id 指向的鱼种必须存在于 species 池，否则 V5 硬错
     （rule=king_species_missing）。
  5. V6 hours 校验口径：hours 为 str[] 钟点区间（如 "00:00-24:00"），非枚举——
     按正则 `HH:MM-HH:MM` 校验格式合法（默认值 ["00:00-24:00"] 通过），
     格式不符 → V6 硬错（rule=hours_format）。
  6. V6 spots 引用存在性采用宽松引用（对齐 dungeon_models）：maps 模块缺失或
     无任何 gather_points 采集点 → 引用存在性检查宽松跳过（零红不误拦）；maps
     存在且含采集点 id 时，spot 不在其中 → V6 硬错（rule=spot_ref_missing）。
     legal 包 maps.json 现无 gather_points → spots 引用跳过，legal 包零红。
  7. report 收集器三形态：report.error/warning 方法 → report._err/_warn 方法 →
     {"errors":[],"warnings":[]} dict（_emit 兜底，任务强制，同 forge_models）。

铁律：零 NoneBot import；frozen dataclass；完整类型标注（typing 3.9 兼容）；
纯函数；确定性；零定时器/零睡眠（不引入实时计时调用）；不引入随机；不 git commit。
仅依赖 qbot_rpg.content.models（BaseDef/FieldMeta/ModuleMeta）与标准库。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Set, Tuple

from qbot_rpg.content.models import BaseDef, FieldMeta, ModuleMeta

# =====================================================================================
# 常量 / 枚举注册表（共享契约 §二 + 细化 2c1a §一 / §三）
# =====================================================================================

# 三态模式（V4 硬枚举；共享契约 §一 mode）
FISH_MODES: Tuple[str, ...] = ("full", "simple", "off")

# 基础稀有度（F-03 / V6；对齐 70/25/5 体系）
FISH_RARITIES: Tuple[str, ...] = ("normal", "rare", "gold")

# 季节偏好枚举（F-08 / V6；空=全年不限）
FISH_SEASONS: Tuple[str, ...] = ("spring", "summer", "autumn", "winter")

# 五时段偏好枚举（F-09 / V6；空=全天不限）
FISH_PERIODS: Tuple[str, ...] = ("dawn", "noon", "dusk", "night", "midnight")

# 钟点区间格式（F-10 / V6；如 "00:00-24:00"，宽松：小时 1-2 位 / 分钟 2 位）
HOURS_RANGE_RE = re.compile(r"^\d{1,2}:\d{2}-\d{1,2}:\d{2}$")

# settings.fishing 段缺省默认值（共享契约 §一 逐键默认；bait_ids 5 档由内容包配置，
# 本层缺省为空 → V3 引用检查宽松跳过不误拦）
DEFAULT_FISH_MODE: str = "full"
DEFAULT_CROWN_THRESHOLDS: Dict[str, int] = {"reverse": 5, "silver": 85, "gold": 95}


# =====================================================================================
# Def 类型（ID/名称冗余铁律：FishDef/KingEventDef 继承 BaseDef 冗余镜像 raw）
# =====================================================================================


@dataclass(frozen=True)
class FishDef(BaseDef):
    """fishing.json species[] 一条鱼种（共享契约 §二 F-01~F-14）。

    id/name 由 BaseDef 承载（from_entry 冗余镜像 raw）；其余字段访问器见下。
    """

    def _num(self, key: str) -> Optional[float]:
        v = self.raw.get(key)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def _str(self, key: str) -> Optional[str]:
        v = self.raw.get(key)
        return v if isinstance(v, str) else None

    def _str_list(self, key: str) -> Tuple[str, ...]:
        v = self.raw.get(key)
        return tuple(x for x in v if isinstance(x, str)) if isinstance(v, list) else ()

    def _mapping(self, key: str) -> Mapping[str, object]:
        v = self.raw.get(key)
        return v if isinstance(v, Mapping) else {}

    @property
    def rarity(self) -> Optional[str]:
        """基础稀有度 normal/rare/gold（F-03）。"""
        return self._str("rarity")

    @property
    def size_min(self) -> Optional[float]:
        """大小下限 cm（F-04）。"""
        return self._num("size_min")

    @property
    def size_max(self) -> Optional[float]:
        """大小上限 cm（F-05；须 ≥ size_min，V1）。"""
        return self._num("size_max")

    @property
    def weight_min(self) -> Optional[float]:
        """重量下限 kg（F-06）。"""
        return self._num("weight_min")

    @property
    def weight_max(self) -> Optional[float]:
        """重量上限 kg（F-07；须 ≥ weight_min，V1）。"""
        return self._num("weight_max")

    @property
    def seasons(self) -> Tuple[str, ...]:
        """季节偏好（F-08；空=全年不限）。"""
        return self._str_list("seasons")

    @property
    def periods(self) -> Tuple[str, ...]:
        """五时段偏好（F-09；空=全天不限）。"""
        return self._str_list("periods")

    @property
    def hours(self) -> Tuple[str, ...]:
        """现实钟点区间（F-10；默认全天 "00:00-24:00"）。"""
        return self._str_list("hours")

    @property
    def spots(self) -> Tuple[str, ...]:
        """钓点 id 列表，引用 maps.json 采集点（F-11；≥1，V6）。"""
        return self._str_list("spots")

    @property
    def preferred_bait(self) -> Tuple[str, ...]:
        """对口饵 id 列表，引用 settings.fishing.bait_ids（F-12；V3）。"""
        return self._str_list("preferred_bait")

    @property
    def codex_text(self) -> Mapping[str, object]:
        """图鉴文案对象（F-13；C-01~03）。"""
        return self._mapping("codex_text")

    @property
    def king(self) -> object:
        """该鱼鱼王行级配置（F-14；null=无鱼王；批4 用）。"""
        return self.raw.get("king")


@dataclass(frozen=True)
class KingEventDef(BaseDef):
    """fishing.json king[] 一条鱼王事件（细化 2c1a §三 K-01~K-07）。

    id/name 由 BaseDef 承载；species_id/enemy_id 等访问器见下。批0 只定义 schema
    形态，鱼王 BOSS 战接线归批4。
    """

    def _str(self, key: str) -> Optional[str]:
        v = self.raw.get(key)
        return v if isinstance(v, str) else None

    def _num(self, key: str) -> Optional[float]:
        v = self.raw.get(key)
        return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

    def _bool(self, key: str) -> Optional[bool]:
        v = self.raw.get(key)
        return v if isinstance(v, bool) else None

    @property
    def species_id(self) -> Optional[str]:
        """关联鱼种 fishing.json.species[].id（K-02；V5 存在性解析）。"""
        return self._str("species_id")

    @property
    def enemy_id(self) -> Optional[str]:
        """鱼王 BOSS 引用 enemies.json（K-03）。"""
        return self._str("enemy_id")

    @property
    def hint(self) -> Optional[str]:
        """金闪标记文案（K-04；默认 "金闪"）。"""
        return self._str("hint")

    @property
    def window_daily(self) -> Optional[float]:
        """每日讨伐窗口次数（K-05；默认 2）。"""
        return self._num("window_daily")

    @property
    def chance(self) -> Optional[float]:
        """单次触发概率（K-06；默认 0.3）。"""
        return self._num("chance")

    @property
    def enabled(self) -> Optional[bool]:
        """事件总开关（K-07；默认 true）。"""
        return self._bool("enabled")


# =====================================================================================
# 收集器鸭子类型（三形态：report.error/warning 方法 → report._err/_warn 方法 →
# {"errors":[],"warnings":[]} dict；照 forge_models._emit 模式，任务强制）
# =====================================================================================
def _emit(report: object, method: str, *args: object, **kwargs: object) -> None:
    """收集器鸭子类型适配，兼容三形态（任务强制）：

    1) report.error(...)/report.warning(...) 方法（如 validator 校验器注入形态）；
    2) report._err(...)/report._warn(...) 方法（validator._Checker）；
    3) report 为 dict {"errors":[], "warnings":[]}（JSON 收集器兜底）。
    """
    fn = getattr(report, method, None)
    if not callable(fn):
        _MAP = {"error": "_err", "warning": "_warn", "note": "_note"}
        fn = getattr(report, _MAP.get(method, "_" + method), None)
    if callable(fn):
        fn(*args, **kwargs)
        return
    # dict 形态兜底：{"errors": [], "warnings": []}
    if isinstance(report, dict):
        key = {"error": "errors", "warning": "warnings", "note": "notes"}.get(method)
        lst = report.get(key)
        if isinstance(lst, list):
            lst.append({"method": method, "args": args, "kwargs": dict(kwargs)})


def _err(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "error", "fishing", field, kind, **detail)


def _warn(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "warning", "fishing", field, kind, **detail)


# =====================================================================================
# 引用靶收集（settings.fishing 段 / maps gather_points；缺失 → None 宽松跳过）
# =====================================================================================
def _fishing_settings(modules: Mapping[str, object]) -> Mapping[str, object]:
    """读取 settings.fishing 段；settings 缺失/无 fishing 段 → 空映射（默认兜底）。"""
    settings = modules.get("settings")
    if isinstance(settings, Mapping):
        seg = settings.get("fishing")
        if isinstance(seg, Mapping):
            return seg
    return {}


def _bait_ids(fseg: Mapping[str, object]) -> Optional[Set[str]]:
    """settings.fishing.bait_ids → id 集合；缺失/非 list/空 → None（V3 正向宽松跳过）。"""
    v = fseg.get("bait_ids")
    if not isinstance(v, list) or not v:
        return None
    ids = {x for x in v if isinstance(x, str) and x}
    return ids if ids else None


def _crown_thresholds(fseg: Mapping[str, object]) -> Dict[str, int]:
    """settings.fishing.crown_thresholds → 三键 int；段缺失 → 默认 5/85/95 兜底。"""
    v = fseg.get("crown_thresholds")
    if not isinstance(v, Mapping):
        return dict(DEFAULT_CROWN_THRESHOLDS)
    out: Dict[str, int] = {}
    for key, default in DEFAULT_CROWN_THRESHOLDS.items():
        val = v.get(key)
        if isinstance(val, int) and not isinstance(val, bool):
            out[key] = val
        else:
            out[key] = default
    return out


def _mode(fseg: Mapping[str, object]) -> str:
    """settings.fishing.mode → str；缺失 → 默认 "full"。"""
    v = fseg.get("mode")
    return v if isinstance(v, str) else DEFAULT_FISH_MODE


def _collect_gather_point_ids(modules: Mapping[str, object]) -> Optional[Set[str]]:
    """收集 maps 模块全部采集点 id；模块缺失/无 gather_points → None（宽松跳过）。

    对齐 dungeon_models._collect_map_ids 宽松引用口径：maps.json 含 gather_points
    数组（test_demo 现有 gp_moon_grass 等）；list 形态逐条取。maps 存在但没有任何
    采集点 id → None（引用存在性检查跳过，零红不误拦——legal 包 maps 现无采集点）。
    """
    maps_data = modules.get("maps")
    if isinstance(maps_data, list):
        ids: Set[str] = set()
        for e in maps_data:
            if not isinstance(e, Mapping):
                continue
            gps = e.get("gather_points")
            if isinstance(gps, list):
                for g in gps:
                    if isinstance(g, Mapping):
                        gid = g.get("id")
                        if isinstance(gid, str) and gid:
                            ids.add(gid)
        return ids if ids else None
    return None


def _fish_ids(fishing: Mapping[str, object]) -> Set[str]:
    """species 池全部鱼种 id（V5/V3 反向解析靶）。"""
    species = fishing.get("species")
    if not isinstance(species, list):
        return set()
    return {str(e.get("id")) for e in species
            if isinstance(e, Mapping) and e.get("id") is not None}


def _king_rows(fishing: Mapping[str, object]) -> Tuple[Mapping[str, object], ...]:
    """fishing.king 数组 → 行元组；缺失/非 list → 空。"""
    v = fishing.get("king")
    if not isinstance(v, list):
        return ()
    return tuple(e for e in v if isinstance(e, Mapping))


# =====================================================================================
# validate_fishing：fishing 模块专项校验（共享契约 §三 V1-V4 硬 + W1 黄 +
# V5/V6 扩展，针对 species/king）
# =====================================================================================
# 级别：红拦=error（加载失败）/ 黄=warning（不阻断）。
# 规则速览：
#   V1 硬：size_min ≤ size_max 且 weight_min ≤ weight_max（逐鱼，报字段路径）。
#   V2 硬：冠级阈值 0 < reverse < silver < gold < 100（读 settings.fishing）。
#   V3 硬：preferred_bait[] 每个 id ∈ settings.fishing.bait_ids；
#          任一 recipe 含 fish_target 语义 → 指向鱼种存在（反向）。
#   V4 硬：mode 三态 full/simple/off（非枚举硬错不静默）。
#   V5 硬：species 非空 + 鱼种 id 全局唯一 + king[].species_id 指向存在（扩展）。
#   V6 硬：seasons/periods/hours/rarity 枚举合法 + spots 引用 maps 采集点存在且非空。
#   W1 黄：simple/off 模式存在 king 数据（king 表或 species.king 非空）→
#          「simple 不生效」提示，不阻断。
def validate_fishing(modules: Mapping[str, object], report: object) -> None:
    """fishing 模块专项校验（共享契约 §三 V1-V6 + W1）。

    入参：
      modules: 模块名（无 .json 后缀）→ parsed JSON（含 "fishing" 与可选
               "settings"/"maps"/"recipe"；fishing 顶层是 obj 非 list——
               species/king 两段）。
      report:  鸭子类型收集器：error/warning 方法 或 _err/_warn 方法 或
               {"errors":[],"warnings":[]} dict（_emit 三形态兜底）。
    出参：None；红拦（error=加载失败）/ 黄提示（warning=不阻断）经 report 追加
    （一次给全量）。fishing 模块缺失/非 Mapping → 跳过（模块未接线默认放行）。
    """
    fishing = modules.get("fishing")
    if not isinstance(fishing, Mapping):
        return

    fseg = _fishing_settings(modules)
    mode = _mode(fseg)
    bait_ids = _bait_ids(fseg)
    crowns = _crown_thresholds(fseg)
    gather_ids = _collect_gather_point_ids(modules)
    species_ids = _fish_ids(fishing)

    # ---- V4 硬：mode 三态枚举（非枚举硬错不静默）----
    if mode not in FISH_MODES:
        _err(report, "settings.fishing.mode", "V4", rule="mode_invalid",
             value=mode, expect=list(FISH_MODES))

    # ---- V2 硬：冠级阈值 0 < reverse < silver < gold < 100 ----
    r, s, g = crowns["reverse"], crowns["silver"], crowns["gold"]
    if not (0 < r < s < g < 100):
        _err(report, "settings.fishing.crown_thresholds", "V2",
             rule="crown_thresholds_order", value=crowns,
             expect="0 < reverse < silver < gold < 100")

    # ---- V5 硬：species 非空（防空池，TC-22b）+ id 唯一 + king species_id 解析 ----
    species = fishing.get("species")
    if not isinstance(species, list):
        _err(report, "fishing.species", "V5", rule="species_not_list",
             got=type(species).__name__)
        species = []
    if not species:
        _err(report, "fishing.species", "V5", rule="species_empty",
             note="鱼种池 ≥1（细化 1.0 D-02 防空池）")
        return  # 空池后续逐鱼校验无意义
    seen: Set[str] = set()
    for i, entry in enumerate(species):
        if not isinstance(entry, Mapping):
            _err(report, f"fishing.species.{i}", "V5", rule="fish_not_object",
                 got=type(entry).__name__)
            continue
        eid = entry.get("id")
        if not isinstance(eid, str) or not eid:
            _err(report, f"fishing.species.{i}.id", "V5", rule="fish_id_required",
                 got=type(eid).__name__)
        elif eid in seen:
            _err(report, f"fishing.species.{i}.id", "V5", rule="fish_id_duplicate",
                 id=eid)
        else:
            seen.add(eid)
        _check_fish_entry(report, i, entry, bait_ids, gather_ids, mode)

    # king[].species_id 指向鱼种存在（V5 解析）
    for ki, row in enumerate(_king_rows(fishing)):
        sid = row.get("species_id")
        if not isinstance(sid, str) or not sid:
            _err(report, f"fishing.king.{ki}.species_id", "V5",
                 rule="king_species_required", got=type(sid).__name__)
        elif sid not in species_ids:
            _err(report, f"fishing.king.{ki}.species_id", "V5",
                 rule="king_species_missing", ref=sid,
                 expect="fishing.species[].id")

    # ---- V3 反向：recipe 含 fish_target 语义 → 指向鱼种存在（无语义则跳过不误报）----
    _check_recipe_fish_target(modules, report, species_ids)

    # ---- W1 黄：simple/off 模式存在 king 数据 → 提示「simple 不生效」不阻断 ----
    if mode in ("simple", "off"):
        king_rows = _king_rows(fishing)
        if king_rows:
            _warn(report, "fishing.king", "W1", rule="simple_king_ignored",
                  mode=mode, note="simple/off 模式鱼王路径不可达，king 表不生效")
        for i, entry in enumerate(species):
            if isinstance(entry, Mapping) and entry.get("king") is not None:
                _warn(report, f"fishing.species.{i}.king", "W1",
                      rule="simple_king_ignored", mode=mode,
                      note="simple/off 模式鱼王路径不可达，行级 king 不生效")


def _check_fish_entry(
    report: object,
    i: int,
    entry: Mapping[str, object],
    bait_ids: Optional[Set[str]],
    gather_ids: Optional[Set[str]],
    mode: str,
) -> None:
    """单条鱼种校验（V1 区间 / V3 正向饵 / V6 枚举与 spots 引用 / W1 行级 king）。"""
    base = f"fishing.species.{i}"

    # ---- V1 硬：区间 size_min ≤ size_max 且 weight_min ≤ weight_max（逐鱼定位字段）----
    smin = entry.get("size_min")
    smax = entry.get("size_max")
    wmin = entry.get("weight_min")
    wmax = entry.get("weight_max")
    if isinstance(smin, (int, float)) and not isinstance(smin, bool) \
            and isinstance(smax, (int, float)) and not isinstance(smax, bool):
        if smin > smax:
            _err(report, f"{base}.size_min", "V1", rule="size_range_reversed",
                 size_min=smin, size_max=smax, expect="size_min <= size_max")
    if isinstance(wmin, (int, float)) and not isinstance(wmin, bool) \
            and isinstance(wmax, (int, float)) and not isinstance(wmax, bool):
        if wmin > wmax:
            _err(report, f"{base}.weight_min", "V1", rule="weight_range_reversed",
                 weight_min=wmin, weight_max=wmax, expect="weight_min <= weight_max")

    # ---- V3 正向：preferred_bait[] 每个 id ∈ settings.fishing.bait_ids ----
    pb = entry.get("preferred_bait")
    if isinstance(pb, list):
        for bi, b in enumerate(pb):
            if not isinstance(b, str) or not b:
                _err(report, f"{base}.preferred_bait.{bi}", "V3",
                     rule="bait_not_str", got=type(b).__name__)
            elif bait_ids is not None and b not in bait_ids:
                _err(report, f"{base}.preferred_bait.{bi}", "V3",
                     rule="bait_ref_missing", ref=b,
                     expect="settings.fishing.bait_ids")

    # ---- V6 硬：枚举成员合法 ----
    rarity = entry.get("rarity")
    if rarity is not None and rarity not in FISH_RARITIES:
        _err(report, f"{base}.rarity", "V6", rule="rarity_invalid",
             value=rarity, expect=list(FISH_RARITIES))
    seasons = entry.get("seasons")
    if isinstance(seasons, list):
        for si, s in enumerate(seasons):
            if not isinstance(s, str) or s not in FISH_SEASONS:
                _err(report, f"{base}.seasons.{si}", "V6", rule="season_invalid",
                     value=s, expect=list(FISH_SEASONS))
    periods = entry.get("periods")
    if isinstance(periods, list):
        for pi, p in enumerate(periods):
            if not isinstance(p, str) or p not in FISH_PERIODS:
                _err(report, f"{base}.periods.{pi}", "V6", rule="period_invalid",
                     value=p, expect=list(FISH_PERIODS))
    hours = entry.get("hours")
    if isinstance(hours, list):
        for hi, h in enumerate(hours):
            if not isinstance(h, str) or not HOURS_RANGE_RE.match(h):
                _err(report, f"{base}.hours.{hi}", "V6", rule="hours_format",
                     value=h, expect="HH:MM-HH:MM")

    # ---- V6 硬：spots 引用 maps 采集点存在且非空 ----
    spots = entry.get("spots")
    if not isinstance(spots, list) or not spots:
        _err(report, f"{base}.spots", "V6", rule="spots_empty",
             got=type(spots).__name__, note="spots 必填且 ≥1（F-11）")
    else:
        for si, spot in enumerate(spots):
            if not isinstance(spot, str) or not spot:
                _err(report, f"{base}.spots.{si}", "V6", rule="spot_not_str",
                     got=type(spot).__name__)
            elif gather_ids is not None and spot not in gather_ids:
                _err(report, f"{base}.spots.{si}", "V6", rule="spot_ref_missing",
                     ref=spot, expect="maps.json gather_points 采集点 id")

    # ---- W1 黄：行级 king（mode 由外层已判，本处仅报告路径）----
    # （简单场景：行级 king 存在由 validate_fishing 外层统一扫，这里不重复报）


def _check_recipe_fish_target(
    modules: Mapping[str, object],
    report: object,
    species_ids: Set[str],
) -> None:
    """V3 反向：recipe 行含 fish_target 语义 → 指向鱼种必须存在（2c1a §五 V3）。

    recipe.json 无 fish_target 语义（test_demo 现有 10 条 recipe 均无此键）→
    跳过不误报（契约明示）。仅当 recipe 模块存在且某行显式写 fish_target 才检查。
    """
    recipe = modules.get("recipe")
    if not isinstance(recipe, list):
        return
    has_target = False
    for i, entry in enumerate(recipe):
        if not isinstance(entry, Mapping):
            continue
        ft = entry.get("fish_target")
        if isinstance(ft, str) and ft:
            has_target = True
            if ft not in species_ids:
                _err(report, f"recipe.{i}.fish_target", "V3",
                     rule="fish_target_missing", ref=ft,
                     expect="fishing.species[].id")
    # 无任何 fish_target 语义 → 契约明示跳过不误报（无需额外动作，has_target 仅文档）
    del has_target


# =====================================================================================
# field_meta 登记（共享契约 §三 + 接口摸底 §八-2；自包含防循环依赖）
# =====================================================================================

# settings.fishing 段 FieldMeta（共享契约 §一 9 键；自包含持有，防 field_meta
# ↔ fishing 循环依赖——对齐 forge_settings 自包含口径）
FISHING_SETTINGS_FIELD_DEFS: Dict[str, FieldMeta] = {
    # mode 三态枚举（V4 硬由 validate_fishing 拦；读段默认 full 兜底不报错）
    "mode": FieldMeta(type="str", default=DEFAULT_FISH_MODE),
    # bait_ids 5 档饵引用炼金 recipe id
    "bait_ids": FieldMeta(type="list", element=FieldMeta(type="str")),
    # 对口饵加成百分数
    "bait_bonus": FieldMeta(type="obj"),
    # 满力收杆 roll 加成百分数
    "rod_full_bonus": FieldMeta(type="obj"),
    # 冠级阈值 {reverse,silver,gold}（V2 序校验）
    "crown_thresholds": FieldMeta(type="obj"),
    # 等待区间秒 {min,max}；0=即收
    "wait_sec": FieldMeta(type="obj"),
    # 每日次数
    "daily_limit": FieldMeta(type="int", range_min=0, default=20),
    # 能量条开关
    "energy": FieldMeta(type="obj"),
    # 鱼王事件 {enabled, window_daily, chance}
    "king_event": FieldMeta(type="obj"),
}


def fishing_module_meta() -> ModuleMeta:
    """fishing 模块 ModuleMeta（entry_type=object——fishing.json 顶层是 obj 非 list）。

    对齐 forge_module_meta 口径：fields={} 空表防泛型误拦（spots 空数组等结构语义
    会被泛型 R-1 误伤）——深结构校验由 validate_fishing 专项全权（V1-V6/W1）。
    FISHING_SETTINGS_FIELD_DEFS 保留导出，供 M12 编辑器元数据驱动复用。
    """
    return ModuleMeta(entry_type="object", fields={}, kind="fish")


def fishing_settings_meta() -> FieldMeta:
    """settings.fishing 段 FieldMeta（type=obj + 全字段 children；合并进 SETTINGS_FIELDS）。"""
    return FieldMeta(type="obj", children=FISHING_SETTINGS_FIELD_DEFS)
