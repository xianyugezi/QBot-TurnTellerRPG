"""M10 批4·路4A：codex 鱼册分册扩展 + 正式 fish_codex_update（qbot_rpg/core/fishing_codex.py）。

文件名：qbot_rpg/core/fishing_codex.py
创建时间：2026-08-31
作者：Hermes 子agent-4A（M10 钓鱼实现组批4·路4A：codex 鱼册 + 冠级标注 T13/T14）

功能描述（T13/T14 / 细化_2c1a §四 图鉴记录 + 细化_2c1c §二 图鉴记录）：
  - fish_codex_update(ctx, species_id, catch) -> dict：正式图鉴入册函数——七键更新
    （G-01~G-07）+ 首获 mark_seen 点亮（name/seen + log_codex_new/bump_event 容错）
    + 防整条目覆盖（保留 killed/lore_unlocked 存量键）；鱼综述段
    codex_state["fish"]["__meta__"] 含 king_victory_count（默认 0，供批5 补全判定
    R-07 读取）。
  - 独立模块落盘（批3 settle 的本地薄实现由主 agent 收口替换为 import 本模块）：
    防核心层循环依赖（codex.py 引擎 / fishing_settle.py 结算 / codex_commands 指令壳
    三方单向依赖本模块，本模块零依赖它们）。
  - 本模块为零 NoneBot、纯函数确定性零 IO 零定时器/零睡眠（纯状态改写）；rng 不
    涉及（纯记录）；展示/数据字段零 emoji。

依据：
  - docs/细化/细化_2c1a_鱼种数据与冠级.md §四（4.1 七键 G-01~G-07 字段表 L179-187 /
    4.2 首获创建并点亮 L206 / C-03 best_mask 展示模板 L61）/ §六 TC-15~17
  - docs/细化/细化_2c1c_鱼王与图鉴经济.md §二（2.1 E-01 鱼综述 king_victory_count
    L61 / 2.2 R-05 更新规则 / 2.3 R-06 展示格式 L71-75）/ §五 TC-05~08
  - docs/m10_shared_contract.md §二（IF-06 fish_codex_update）/ §四（R-05 图鉴更新
    规则 / R-06 展示格式）/ §五 铁律
  - docs/m10_接口摸底.md §三（codex mark_seen 覆盖陷阱 → 专用入册函数防覆盖；
    图鉴展示特判 render_fish_codex；鱼综述 king_victory_count 落点）
  - qbot_rpg/core/codex.py（mark_seen 整条目覆盖陷阱——本模块专用入册防覆盖）
模式参考：
  - qbot_rpg/core/fishing_settle.py（批3 路3A 本地薄实现 fish_codex_update/_mark_fish_seen，
    S-3/S-4——本模块为正式落盘版，收口替换后 settle 切 import）
  - qbot_rpg/core/fishing_crown.py（批3 路3B：CROWN_LABELS 六档中文名 / CROWN_PRIORITY
    语义——best_crown 存档键与展示中文名同源）

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查）：
  C-1  入参校验：species_id 空/非 str → 拒绝 reason=empty_species_id；catch 非
       Mapping → 拒绝 reason=invalid_catch（对齐批3 薄实现口径，防御兜底不炸）。
  C-2  catch 数值归一：size/weight 非数值（含 bool）→ 0.0；crown 非六档键（含
       reverse）/非 str → "normal" 保守处理（数据合法性由校验器硬拦，本函数只做
       读取容错）。
  C-3  best_crown 首获语义：无存量时当前 crown 直落（非 reverse 时）；reverse 不
       入链（2c1a §4.2：逆金冠是极值收藏不是等级，单独 reverse_crown_count）——
       best_crown 保持空串占位（渲染端 CROWN_LABELS 查无 → 中文名回落空）。
  C-4  鱼综述聚合段：codex_state["fish"]["__meta__"]（E-01 聚合段，键名 "__meta__"
       防与鱼种 id 撞名——鱼种 id 全英文小写蛇形，下划线前缀安全）——含
       king_victory_count（累计讨伐胜利次数，默认 0，供批5 图鉴补全判定 R-07
       读取；批4 路4B 负责 +1 写入，本模块只读不改）+ caught_count 聚合（展示用，
       批5 补全判定口径自取）。king_victory_count 计数归路4B 独占，本模块不碰。
  C-5  首获点亮走 mark_seen 等价逻辑（内置 _mark_fish_seen，不 import
       codex.mark_seen——防未知分册拒绝/整条目覆盖；语义与 codex.mark_seen 对齐：
       name/seen 写 + log_codex_new/bump_event 容错）。本模块落盘后 codex.py
       CATEGORIES 已含 "fish"，未来可平滑切换 codex.mark_seen（同键同语义）。
  C-6  防整条目覆盖：更新基于 dict(existing) 复制后 update 七键，killed/
       lore_unlocked/其它存量键全部保留（mark_seen 覆盖陷阱的根治法）。

铁律：零 NoneBot import；纯函数确定性零 IO 零定时器/零睡眠（时间戳不参与，纯状态
      改写）；rng 不涉及（纯记录）；文件头/docstring 不含计时器函数字面量（M43
      探针）；零 emoji；输出文案不走模板（渲染归 commands 层，本模块只落结构化
      数据）。
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping

from qbot_rpg.core.fishing_crown import CROWN_LABELS

__all__ = [
    "CODEX_CATEGORY_FISH",
    "CODEX_FISH_KEYS",
    "CODEX_META_KEY",
    "CROWN_PRIORITY",
    "KING_VICTORY_COUNT_KEY",
    "fish_codex_update",
    "fish_meta",
    "render_fish_entry_line",
]

# =====================================================================================
# 常量：分册名 / 七键 / 聚合段（细化 2c1a §4.1 G-01~G-07 + 2c1c §2.1 E-01）
# =====================================================================================

# 图鉴分册名（codex type=fish，摸底 §三；codex.CATEGORIES["fish"]=("fish",) 同键）
CODEX_CATEGORY_FISH: str = "fish"

# 图鉴条目七键（细化 2c1a §4.1 G-01~G-07；best_crown 存档英文键，中文名见 CROWN_LABELS）
CODEX_FISH_KEYS: tuple = (
    "caught_count",
    "best_crown",
    "best_size",
    "best_weight",
    "min_size",
    "min_weight",
    "reverse_crown_count",
)

# best_crown 优先级链（2c1a §4.2 L182：big_gold > gold > big_silver > silver > normal；
# 逆金冠不入链，单独 reverse_crown_count）
CROWN_PRIORITY: tuple = ("big_gold", "gold", "big_silver", "silver", "normal")

# 鱼综述聚合段键（工程补白 C-4：防与鱼种 id 撞名——鱼种 id 全英文小写蛇形）
CODEX_META_KEY: str = "__meta__"

# 鱼综述聚合段内鱼王胜利计数键（2c1c E-01 L61：默认 0，供批5 补全判定 R-07 读取；
# 计数 +1 归批4 路4B 鱼王事件独占，本模块只读不改）
KING_VICTORY_COUNT_KEY: str = "king_victory_count"


# =====================================================================================
# 工具：codex_state / fish 分册 / 鱼综述聚合段 定位（对齐 codex._state_of 口径）
# =====================================================================================
def _codex_state_of(ctx: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """codex_state 可变引用（ctx 直键，缺省建空 dict 挂回）。"""
    st = ctx.get("codex_state")
    if not isinstance(st, MutableMapping):
        st = {}
        ctx["codex_state"] = st
    return st


def _fish_state_of(ctx: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """fish 分册 state 可变引用（codex_state["fish"]，缺省建空 dict 挂回）。"""
    cat = _codex_state_of(ctx)
    fish = cat.get(CODEX_CATEGORY_FISH)
    if not isinstance(fish, MutableMapping):
        fish = {}
        cat[CODEX_CATEGORY_FISH] = fish
    return fish


def fish_meta(ctx: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """鱼综述聚合段可变引用（codex_state["fish"]["__meta__"]，缺省建空挂回）。

    含 king_victory_count（默认 0，2c1c E-01，供批5 图鉴补全判定 R-07 读取；批4
    路4B 鱼王胜利结算在此 +1）。纯状态读写，零 IO 零定时器/零睡眠。
    """
    fish = _fish_state_of(ctx)
    meta = fish.get(CODEX_META_KEY)
    if not isinstance(meta, MutableMapping):
        meta = {}
        fish[CODEX_META_KEY] = meta
    meta.setdefault(KING_VICTORY_COUNT_KEY, 0)
    return meta


# =====================================================================================
# 首获点亮（mark_seen 等价；防整条目覆盖，工程补白 C-5/C-6）
# =====================================================================================
def _mark_fish_seen(ctx: MutableMapping[str, Any], species_id: str, name: str) -> bool:
    """首获点亮：条目写 name/seen=true（killed/lore_unlocked 存量保留，不整条目覆盖）。

    首获时尝试冒险日志与事件（log_codex_new / bump_event，缺省模块异常静默跳过，
    对齐 codex.mark_seen 容错）。返回 first_seen（本次是否首获）。
    """
    fish = _fish_state_of(ctx)
    existing = fish.get(species_id)
    entry = existing if isinstance(existing, MutableMapping) else {}
    first_seen = not bool(entry.get("seen"))
    entry["name"] = str(name or species_id)
    entry["seen"] = True
    fish[species_id] = entry
    if first_seen:
        try:
            from qbot_rpg.core.adventure_log import log_codex_new

            log_codex_new(ctx, species_id)
        except Exception:
            pass
        try:
            from qbot_rpg.core.event_bus import bump_event

            bump_event(ctx, "[事件:图鉴新增]", instance={"tag": "codex_new", "target": species_id})
        except Exception:
            pass
    return first_seen


# =====================================================================================
# 正式入册：fish_codex_update（七键更新 + 首获点亮 + 防覆盖 + __meta__ 综述）
# =====================================================================================
def fish_codex_update(
    ctx: MutableMapping[str, Any],
    species_id: str,
    catch: Mapping[str, object],
    *,
    name: object = None,
) -> dict:
    """图鉴点亮入册（T13 / 2c1a §4.2：七键更新 + 首获点亮，防 mark_seen 覆盖）。

    入参：
      ctx        —— 结算/记录上下文（codex_state 就地改写即落档，_ps_init 形态）。
      species_id —— 鱼种 id（快照 target_species_id）。
      catch      —— 本次捕获记录 {size, weight, crown}（size/weight 数值，crown
                     六档键之一）；crown 缺失/非法 → "normal" 保守处理（C-2）。
      name       —— 首获时写入的展示名（审查 A4 P1-2：应传中文名，缺省回落
                     species_id——避免 name 键恒等于英文 id 顶掉中文展示）。
    更新规则（2c1a §4.2 / 2c1c R-05，确定性）：
      - caught_count += 1（G-01，每次捕获 +1）
      - best_crown：优先级链 big_gold > gold > big_silver > silver > normal 取最大
        （逆金冠不入链，G-02 / R-05 L66）；首获无存量 → 当前 crown（非逆金冠时，
        工程补白 C-3）
      - best_size / best_weight：与存量极值取 max（G-03/G-04）
      - min_size / min_weight：与存量极值取 min（G-05/G-06，∞语义首获直落）
      - reverse_crown_count：逆金冠出鱼 +1（G-07）
      - 首获：条目不存在 → 建默认七键条目 + 点亮（seen=true，2c1a §4.2 L206）
      - 防整条目覆盖：killed/lore_unlocked 等存量键保留（C-6）
      - 鱼综述聚合段 __meta__：king_victory_count 默认 0 就位（C-4，批4 路4B 才
        +1，本函数只读不改）
    出参：{ok, first_seen, species_id, caught_count, best_crown,
      reverse_crown_count}；条目写入 codex_state["fish"][species_id]（就地）。
    纯函数确定性零 IO 零定时器/零睡眠（纯状态改写）；rng 不涉及。
    """
    if not isinstance(species_id, str) or not species_id.strip():
        return {"ok": False, "reason": "empty_species_id", "first_seen": False}
    if not isinstance(catch, Mapping):
        return {"ok": False, "reason": "invalid_catch", "first_seen": False}

    fish = _fish_state_of(ctx)

    size = catch.get("size")
    weight = catch.get("weight")
    crown = catch.get("crown")
    if not isinstance(size, (int, float)) or isinstance(size, bool):
        size = 0.0
    if not isinstance(weight, (int, float)) or isinstance(weight, bool):
        weight = 0.0
    if not isinstance(crown, str) or crown not in CROWN_PRIORITY + ("reverse",):
        crown = "normal"

    existing = fish.get(species_id)
    entry = dict(existing) if isinstance(existing, Mapping) else {}
    first_seen = not bool(entry.get("seen"))

    caught = int(entry.get("caught_count", 0) or 0) + 1
    best_crown = str(entry.get("best_crown") or "")
    if crown in CROWN_PRIORITY and (
        best_crown not in CROWN_PRIORITY
        or CROWN_PRIORITY.index(crown) < CROWN_PRIORITY.index(best_crown)
    ):
        best_crown = crown
    # 逆金冠不入链（2c1a §4.2 / 2c1c R-05）：best_crown 保持存量链上值；首获即
    # 逆金冠 → 无链上值留空（渲染端 CROWN_LABELS 查无回落空，C-3）

    best_size = max(float(entry.get("best_size", 0.0) or 0.0), float(size))
    best_weight = max(float(entry.get("best_weight", 0.0) or 0.0), float(weight))
    # min 极值：∞语义——无存量（首获）直落当前值，否则取 min（G-05/G-06）
    if first_seen or "min_size" not in entry:
        min_size = float(size)
        min_weight = float(weight)
    else:
        min_size = min(float(entry.get("min_size", 0.0) or 0.0), float(size))
        min_weight = min(float(entry.get("min_weight", 0.0) or 0.0), float(weight))
    reverse_count = int(entry.get("reverse_crown_count", 0) or 0) + (1 if crown == "reverse" else 0)

    # 防 mark_seen 覆盖：基于存量副本 update 七键，killed/lore_unlocked 保留（C-6）
    entry.update(
        {
            "caught_count": caught,
            "best_crown": best_crown,
            "best_size": best_size,
            "best_weight": best_weight,
            "min_size": min_size,
            "min_weight": min_weight,
            "reverse_crown_count": reverse_count,
        }
    )
    fish[species_id] = entry

    # 首获点亮（mark_seen 等价，C-5）；已见则跳过（不重复日志/事件）。
    # A4 P1-2：展示名优先用传入 name（中文名），回落 species_id——避免英文 id 顶中文
    if first_seen:
        display_name = str(name) if name is not None and str(name).strip() else species_id
        _mark_fish_seen(ctx, species_id, display_name)

    # 鱼综述聚合段就位（C-4：king_victory_count 默认 0，批4 路4B 才 +1）
    fish_meta(ctx)

    return {
        "ok": True,
        "first_seen": first_seen,
        "species_id": species_id,
        "caught_count": caught,
        "best_crown": best_crown,
        "reverse_crown_count": reverse_count,
    }


# =====================================================================================
# 展示格式（2c1c R-06 / 2c1a C-03 best_mask；供 commands 层渲染复用）
# =====================================================================================
def render_fish_entry_line(
    name: str,
    best_size: object,
    best_weight: object,
    best_crown: str,
    reverse_crown_count: object,
    *,
    lv: object = 0,
) -> str:
    """单条鱼图鉴展示行（R-06：最优冠级 + 逆金冠单独标注 `逆金冠×N`）。

    模板（2c1a C-03 best_mask）：
      `{name} Lv{lv} · 最大 {best_size}cm/{best_weight}kg · {best_crown} ·
      逆金冠×{reverse_crown_count}`
    Lv 为职业熟练度等级占位（批5 熟练度接线后传入真实等级，本路默认 0——任务书
    明确「Lv 批5 熟练度接线，本路先占位 0」）。
    数值格式：best_size/best_weight 保留 1 位小数（对齐示例 45.2cm/3.8kg 展示口径，
    工程补白）；best_crown 中文名经 CROWN_LABELS 映射（存档英文键 → 中文档位名），
    查无回落空串（首获即逆金冠无链上值时）。
    纯函数确定性零 IO 零定时器/零睡眠。
    """
    size_fmt = f"{_to_float(best_size):.1f}" if _is_number(best_size) else "0.0"
    weight_fmt = f"{_to_float(best_weight):.1f}" if _is_number(best_weight) else "0.0"
    crown_cn = CROWN_LABELS.get(best_crown, "")
    rev = int(_to_float(reverse_crown_count)) if _is_number(reverse_crown_count) else 0
    lv_fmt = int(_to_float(lv)) if _is_number(lv) else 0
    return (
        f"{name} Lv{lv_fmt} · 最大 {size_fmt}cm/{weight_fmt}kg"
        f" · {crown_cn} · 逆金冠×{rev}"
    )


def _is_number(v: object) -> bool:
    """数值判定（int/float，排除 bool）。"""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _to_float(v: object) -> float:
    """数值安全转换（调用方保证 _is_number 已通过；仅收窄类型供静态检查）。

    注：float(Any) 在 mypy 下报 arg-type 误报（运行时安全，_is_number 已把关），
    显式 ignore 标注。
    """
    return float(v)  # type: ignore[arg-type]
