"""批39 · 合成 / 炼金 / 打造 三条启用路径矩阵（qbot_rpg/core/craft_paths.py）。

文件名：qbot_rpg/core/craft_paths.py
创建时间：2026-09-19
作者：主 agent（批39 · 「合成」提升为打造与炼金的公用系统）

功能描述：**「合成」是打造与炼金的公用系统**——三条启用路径互相独立、包声明驱动：

    ┌ 合成（公用层：装备 / 药剂 / 材料 皆可走；极度简化的投料产出）
    │   ├─ 炼金 → 深度炼金（职业专属 → 大师解锁）
    │   └─ 打造 → 深度打造（走公用合成 + 打造深度层）
    └ ① 只启用合成　② 合成 + 炼金　③ 合成 + 打造（也可三者全开）

  本模块是**三态 mode 语义的唯一权威推导点**（对齐 `core/fishing_mode.py` 既有范式）：
  「炼金 / 打造专属层是否可用」由**同一声明**推导，而不是另开三段硬编码 switch：

  - `settings.alchemy.mode` ∈ {full, simple, off}（枚举单一事实源 =
    `content.alchemy_settings.MODE_VALUES`，本模块复用不重列）：
      · `off`    → 合成/炼金/深度炼金**全关**；
      · `simple` → **只启用合成**（合成开；炼金层/深度炼金关）；
      · `full`   → 合成 + 炼金 + 深度炼金（缺省档 = 现状）。
  - `settings.deep_craft.enabled`（obj + enabled，**默认关**，与批38 `settings.
    equipment_offhand` 同风格）：**打造路径**独立开关；仅当公用合成层可用时才有意义
    （打造只做深度层，基础合成走公用层）。**缺省 = 现状**：不配置 → 打造关，
    `alchemy.mode` 缺省 full → 合成 + 炼金，与今天逐字段一致。

  对外 API（供指令壳门禁 / 编辑器说明 / 批40 打造深度层消费）：
  - `alchemy_mode(settings)` → 归一 mode；
  - `forge_enabled(settings)` → 打造路径声明开关；
  - `mode_matrix()` / `path_matrix()` → 权威行为矩阵（测试与文档断言用）；
  - `resolve_paths(settings)` → 四路径 + mode 展开；
  - `path_enabled(settings, path)` → 单路径判定；
  - `layer_denied_message(settings, path)` → 指令壳统一拒绝文案（None = 放行）。

依据：
  - `docs/深度打造_决策记录.md` §六（用户 2026-09-19 二次拍板：合成提升为公用系统 +
    三条启用路径 + 红线「只启用合成 = 现有 alchemy.mode=simple 逐字段等价」）。
  - `docs/审查参考/RPG回合制框架设计文档.md` :2719（可裁剪模块 `mode` 三态）/:2720
    （炼金 `alchemy.mode`：full 三层漏斗 / simple 仅合成层 / off 关闭）。
  - `docs/审查参考/炼金系统设计定稿.md` :10/:410（mode 三态，默认 full）。
  - 范式参考：`qbot_rpg/core/fishing_mode.py`（三态 mode → 行为/可达性矩阵）。

铁律：零 NoneBot import；纯函数确定性零 IO；不硬编码内容包业务名；同一 mode 声明
      不复制成多套 switch（新增路径只需在 `mode_matrix` 加一列）。
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

from qbot_rpg.content.alchemy_settings import MODE_VALUES

__all__ = [
    # mode 常量
    "MODE_FULL", "MODE_SIMPLE", "MODE_OFF", "MODE_LABELS",
    # 路径常量
    "PATH_SYNTHESIS", "PATH_ALCHEMY", "PATH_DEEP_ALCHEMY", "PATH_FORGE",
    "CRAFT_PATHS", "MATRIX_KEYS", "FORGE_CONFIG_KEY",
    # 拒绝文案
    "MODE_OFF_MESSAGE", "ALCHEMY_LAYER_DISABLED_MESSAGE", "DEEP_ALCHEMY_LAYER_DISABLED_MESSAGE",
    # 归一 / 声明读取
    "alchemy_mode", "forge_enabled",
    # 矩阵 / 推导
    "mode_matrix", "path_matrix", "resolve_paths", "path_enabled",
    "synthesis_enabled", "alchemy_enabled", "deep_alchemy_enabled", "forge_path_enabled",
    "layer_denied_message",
]

# =====================================================================================
# mode 常量（三态枚举单一事实源 = content.alchemy_settings.MODE_VALUES，复用不重列）
# =====================================================================================
MODE_FULL: str = "full"      # 三层漏斗：合成 + 炼金 + 深度炼金（缺省）
MODE_SIMPLE: str = "simple"  # 只启用合成层（无炼金层 / 深度炼金 / 职业等级 / 特性 / 能量条）
MODE_OFF: str = "off"        # 关闭：合成层亦拒绝

MODE_LABELS: Dict[str, str] = {
    MODE_FULL: "三层漏斗（合成 + 炼金）",
    MODE_SIMPLE: "仅合成层（公用）",
    MODE_OFF: "关闭",
}

# 三路径键（公用合成层 / 炼金层 / 深度炼金层 / 打造路径）
PATH_SYNTHESIS: str = "synthesis"        # 第 1 层【合成】（打造与炼金共用）
PATH_ALCHEMY: str = "alchemy"            # 第 2 层【炼金】（职业专属）
PATH_DEEP_ALCHEMY: str = "deep_alchemy"  # 第 3 层【深度炼金】（大师解锁）
PATH_FORGE: str = "forge"                # 深度打造（本方案；基础合成走公用层）

CRAFT_PATHS: Tuple[str, ...] = (PATH_SYNTHESIS, PATH_ALCHEMY, PATH_DEEP_ALCHEMY, PATH_FORGE)

# 矩阵行键序（mode_matrix / path_matrix 每行键序，供测试断言与文档引用）
MATRIX_KEYS: Tuple[str, ...] = ("path",) + CRAFT_PATHS

# 打造路径声明键（obj + enabled，默认关，与批38 settings.equipment_offhand 同风格；
# 键名刻意避开既有 M9 锻造配置段 settings.forge，防语义混淆）。
FORGE_CONFIG_KEY: str = "deep_craft"

# =====================================================================================
# 拒绝文案（指令壳统一引用；off 文案与 core/synthesis.py GU-01 逐字一致——回归红线）
# =====================================================================================
MODE_OFF_MESSAGE: str = "❌ 炼金系统已关闭"
ALCHEMY_LAYER_DISABLED_MESSAGE: str = "❌ 炼金层未启用\n本服当前仅开放合成层"
DEEP_ALCHEMY_LAYER_DISABLED_MESSAGE: str = "❌ 深度炼金层未启用\n本服当前开放到合成层"


# =====================================================================================
# 声明归一（纯函数确定性：非法/缺失回落 full / false，对齐运行期容错口径）
# =====================================================================================
def _settings_of(settings: Any) -> Mapping[str, Any]:
    return settings if isinstance(settings, Mapping) else {}


def alchemy_mode(settings: Any) -> str:
    """`settings.alchemy.mode` 归一（full / simple / off）。

    入参：settings 全量 dict（或等价 Mapping）。
    出参：MODE_VALUES 三态之一；缺失 / 非法 / 非 str → `full` 兜底（与
    `core/synthesis.py::check_eligible` GU-01 运行期容错同口径；非法枚举的**红拦**
    归校验器 ALC-01，读段不拦）。
    纯函数确定性零 IO。
    """
    alchemy = _settings_of(settings).get("alchemy")
    if isinstance(alchemy, Mapping):
        mode = alchemy.get("mode")
        if isinstance(mode, str) and mode in MODE_VALUES:
            return mode
    return MODE_FULL


def forge_enabled(settings: Any) -> bool:
    """打造路径声明开关（`settings.deep_craft.enabled`，**默认 false**）。

    与批38 `settings.equipment_offhand` 同风格：obj + enabled，默认关；缺省不配置 →
    打造路径关闭（= 本系统引入前行为）。仅显式 `true` 视为启用（与
    `core/equipment.normalize_offhand_config` 的 `is True` 口径一致）。
    """
    cfg = _settings_of(settings).get(FORGE_CONFIG_KEY)
    if isinstance(cfg, Mapping):
        return cfg.get("enabled") is True
    return False


# =====================================================================================
# 行为矩阵（唯一权威表；供测试与文档断言）
# =====================================================================================
def mode_matrix() -> Dict[str, Dict[str, Any]]:
    """mode 三态 → 公用层/炼金/深度炼金可用性（总纲 :2720 唯一权威矩阵）。

    full:   三层漏斗——合成 + 炼金 + 深度炼金全开（缺省档，= 现状）；
    simple: **只启用合成**——合成开；炼金层/深度炼金关（无职业等级/特性/能量条）；
    off:    全关——合成层亦拒绝（`core/synthesis.py` GU-01 既有口径）。

    每行键 = (`path`, `synthesis`, `alchemy`, `deep_alchemy`, `forge`)；`forge` 列由
    `path_matrix()` 按打造开关展开（本函数固定 False，仅表 mode 语义）。
    纯函数确定性零 IO。
    """
    return {
        MODE_FULL: {
            "path": "合成 → 炼金 → 深度炼金（三层漏斗）",
            PATH_SYNTHESIS: True,
            PATH_ALCHEMY: True,
            PATH_DEEP_ALCHEMY: True,
            PATH_FORGE: False,  # 打造独立声明，见 path_matrix()
        },
        MODE_SIMPLE: {
            "path": "合成（公用层，单层）",
            PATH_SYNTHESIS: True,
            PATH_ALCHEMY: False,
            PATH_DEEP_ALCHEMY: False,
            PATH_FORGE: False,
        },
        MODE_OFF: {
            "path": "全关（合成层亦拒绝）",
            PATH_SYNTHESIS: False,
            PATH_ALCHEMY: False,
            PATH_DEEP_ALCHEMY: False,
            PATH_FORGE: False,
        },
    }


def path_matrix() -> Dict[Tuple[str, bool], Dict[str, Any]]:
    """（mode × 打造开关）→ 四路径可用性全表。

    键 = (mode, forge_enabled)；打造路径（`forge`）**仅当公用合成层可用**时才有意义
    （打造只做深度层，基础合成走公用层）——故 `mode=off` 下打造恒 False。
    每行键 = MATRIX_KEYS。纯函数确定性零 IO。
    """
    out: Dict[Tuple[str, bool], Dict[str, Any]] = {}
    for mode, row in mode_matrix().items():
        for forge_on in (False, True):
            merged = dict(row)
            merged[PATH_FORGE] = bool(row[PATH_SYNTHESIS] and forge_on)
            out[(mode, forge_on)] = merged
    return out


# =====================================================================================
# 推导（包声明 → 四路径）
# =====================================================================================
def resolve_paths(settings: Any) -> Dict[str, Any]:
    """包声明 → 四路径展开（唯一推导入口）。

    出参：{mode, forge_switch, synthesis, alchemy, deep_alchemy, forge}——
    `mode` 为归一后的 alchemy.mode，`forge_switch` 为 `settings.deep_craft.enabled`
    原始声明，四路径布尔见 `path_matrix()`。纯函数确定性零 IO。
    """
    mode = alchemy_mode(settings)
    forge_switch = forge_enabled(settings)
    row = path_matrix()[(mode, forge_switch)]
    return {
        "mode": mode,
        "forge_switch": forge_switch,
        PATH_SYNTHESIS: bool(row[PATH_SYNTHESIS]),
        PATH_ALCHEMY: bool(row[PATH_ALCHEMY]),
        PATH_DEEP_ALCHEMY: bool(row[PATH_DEEP_ALCHEMY]),
        PATH_FORGE: bool(row[PATH_FORGE]),
    }


def path_enabled(settings: Any, path: str) -> bool:
    """单路径可用性（未知 path → False 保守拒绝）。"""
    if path not in CRAFT_PATHS:
        return False
    return bool(resolve_paths(settings).get(path, False))


def synthesis_enabled(settings: Any) -> bool:
    """公用合成层是否可用（`mode != off`）。"""
    return path_enabled(settings, PATH_SYNTHESIS)


def alchemy_enabled(settings: Any) -> bool:
    """炼金层是否可用（`mode == full`）。"""
    return path_enabled(settings, PATH_ALCHEMY)


def deep_alchemy_enabled(settings: Any) -> bool:
    """深度炼金层是否可用（`mode == full`）。"""
    return path_enabled(settings, PATH_DEEP_ALCHEMY)


def forge_path_enabled(settings: Any) -> bool:
    """打造路径是否可用（合成层可用 **且** `settings.deep_craft.enabled = true`）。"""
    return path_enabled(settings, PATH_FORGE)


def layer_denied_message(settings: Any, path: str) -> Optional[str]:
    """指令壳统一门禁：路径可用 → None（放行）；否则返回拒绝文案。

    - `alchemy.mode = off` → `MODE_OFF_MESSAGE`（与合成引擎 GU-01 逐字一致，回归）；
    - 深度炼金层未启用 → `DEEP_ALCHEMY_LAYER_DISABLED_MESSAGE`；
    - 炼金层未启用（simple）→ `ALCHEMY_LAYER_DISABLED_MESSAGE`。
    纯函数确定性零 IO。
    """
    if path_enabled(settings, path):
        return None
    if alchemy_mode(settings) == MODE_OFF:
        return MODE_OFF_MESSAGE
    if path == PATH_DEEP_ALCHEMY:
        return DEEP_ALCHEMY_LAYER_DISABLED_MESSAGE
    return ALCHEMY_LAYER_DISABLED_MESSAGE


# =====================================================================================
# 模块自检：mode 常量与枚举单一事实源一致（防两处各写一套）
# =====================================================================================
assert MODE_VALUES == (MODE_FULL, MODE_SIMPLE, MODE_OFF), (
    "craft_paths 三态常量必须与 content.alchemy_settings.MODE_VALUES 单一事实源一致"
)
