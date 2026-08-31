"""M10 批4·路4A：/图鉴 鱼册特判渲染（qbot_rpg/commands/fishing_codex_commands.py）。

文件名：qbot_rpg/commands/fishing_codex_commands.py
创建时间：2026-08-31
作者：Hermes 子agent-4A（M10 钓鱼实现组批4·路4A：codex 鱼册 + 冠级标注 T14）

功能描述（T14 / 细化_2c1c §二 2.3 展示格式 R-06 + 细化_2c1a §四 4.2）：
  - render_fish_codex(ctx) -> str：/图鉴 鱼册特判渲染（对齐 render_alchemy_codex
    模式——由 codex_commands 在 /图鉴 fish 分支单向 import 调用，防双注册/循环）：
      · 列出全部已捕获鱼种（codex_state["fish"] 条目，seen=true）+ 冠级标注
        （best_crown 中文档位 + 逆金冠×N 单独标注，R-06）；
      · 未捕获不显示且不泄露名称（对齐 codex_view「???」口径——不列未捕获条目）；
      · 鱼综述行：捕获总数 / 鱼王讨伐胜利数 king_victory_count（2c1c E-01，
        供批5 补全判定 R-07 读取展示）；
      · 不写判定公式/阈值（R-06 铁律：图鉴不教攻略，5/85/95 不可见）。
  - 纯展示层：只读 codex_state["fish"]，零改写零 IO 零定时器/零睡眠；渲染零
    emoji（仅功能性标记与排版符号）。

依据：
  - docs/细化/细化_2c1c_鱼王与图鉴经济.md §二（2.1 E-01 鱼综述 king_victory_count /
    2.3 R-06 展示格式 L71-75）/ §五 TC-07（best_mask 逐字段一致；无判定公式词汇）
  - docs/细化/细化_2c1a_鱼种数据与冠级.md §四（4.2 首获点亮 / C-03 best_mask
    展示模板）/ §六 TC-17
  - docs/m10_shared_contract.md §四（R-06 展示格式）/ §五 铁律
  - docs/m10_接口摸底.md §三（图鉴展示特判：codex_commands 对 fish 特判调
    render_fish_codex——M8 alchemy 分册先例；鱼综述 king_victory_count 落点）
  - qbot_rpg/core/codex.py（CATEGORIES["fish"] / _CATEGORY_LABELS["fish"]）
  - qbot_rpg/core/fishing_codex.py（fish_codex_update 入册 / render_fish_entry_line
    条目行 / fish_meta 综述段）
  - qbot_rpg/core/fishing_crown.py（CROWN_LABELS 六档中文名）
模式参考：
  - qbot_rpg/commands/alchemy_commands.py render_alchemy_codex（/图鉴 特判渲染先例：
    单向 import 防环，返回正文 str）

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查）：
  D-1  只列已捕获：codex_state["fish"] 中 seen=true 的条目（__meta__ 聚合段除外）
       全部列出；未捕获无条目 → 不列不泄露（对齐 codex_view 未收集「???」不提示
       原则 R-19 的鱼册等价口径）。排序按条目名（中文名，确定性字典序）。
  D-2  渲染格式：页头「【鱼图鉴】」+ 鱼综述行「已捕获 N 种 · 鱼王讨伐胜利 K 次」
       + 逐条 best_mask 模板行（render_fish_entry_line：{name} Lv{lv} · 最大
       {best_size}cm/{best_weight}kg · {best_crown} · 逆金冠×{reverse_crown_count}，
       2c1a C-03）+ 空态「（还没有捕获记录）」。Lv 批5 熟练度接线，本路占位 0。
  D-3  不教攻略：渲染不含任何阈值词汇（5%/85%/95%/逆金冠判定条件等）——R-06
       铁律，TC-07/TC-17 检索空断言。
  D-4  无 registry 依赖：鱼册分母由内容包 fishing.json 全量决定，渲染不读
       registry（fishing 顶层 obj 非条目表，摸底 §三）；捕获总数 = seen=true 条目
       数（与总览 codex_progress 的 seen 口径一致）。
  D-5  模板化占位：页头/综述/空态文案走 tpl_of(ctx, "fish_codex_*", {...}) 优先、
       本地 fallback 兜底（对齐 fishing_commands F-6 模式——批6 fishing_tpl 分区
       接管前本地常量兜底，TODO 标注批6 迁移）。

铁律：零 NoneBot import；纯函数确定性零 IO 零定时器/零睡眠（只读展示）；rng 不
      涉及；文件头/docstring 不含计时器函数字面量（M43 探针）；渲染零 emoji（仅
      功能性标记与排版符号）；不写判定公式/阈值（R-06）。
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping

from qbot_rpg.core.fishing_codex import (
    CODEX_CATEGORY_FISH,
    CODEX_META_KEY,
    KING_VICTORY_COUNT_KEY,
    fish_meta,
    render_fish_entry_line,
)
from qbot_rpg.core.templates import tpl_of  # 消息模板配置化（批6 fishing_tpl 分区接管）

__all__ = ["render_fish_codex"]

# ---------------------------------------------------------------------------
# 本地 fallback 文案（D-5：tpl_of 无 fish_codex_* 分区 key 返回空串 → 本地兜底；
# TODO 批6：fishing_tpl 分区接管后删除 fallback，统一走 tpl_of）
# ---------------------------------------------------------------------------
_DEF_FISH_CODEX_HEADER: str = "【鱼图鉴】"
_DEF_FISH_CODEX_SUMMARY: str = "已捕获 {caught} 种 · 鱼王讨伐胜利 {king} 次"
_DEF_FISH_CODEX_EMPTY: str = "（还没有捕获记录）"


def _render(ctx: Mapping[str, Any], key: str, fallback: str, data: Mapping[str, Any]) -> str:
    """模板渲染：tpl_of 优先（批6 fishing_tpl 分区覆盖）；空串 → 本地 fallback 兜底。

    tpl_of 对无分区 key 返回空串（render_template 缺失 key → ""），此时回退本地
    fallback（D-5）。fallback 内含 {占位符}，用 data format_map 填充；占位符缺键 →
    原样保留不崩（防御兜底，对齐 fishing_commands._render 口径）。
    """
    rendered = tpl_of(ctx, key, data)
    if rendered:
        return rendered
    try:
        return fallback.format_map(data)
    except (KeyError, ValueError):
        return fallback


def _fish_entries_of(ctx: Mapping[str, Any]) -> list:
    """已捕获鱼种条目列表（codex_state["fish"] 中 seen=true，__meta__ 除外）。

    确定性排序：按条目 name（中文名，字典序）；无 name 的条目按 id 兜底。零改写。
    """
    st = ctx.get("codex_state")
    fish = st.get(CODEX_CATEGORY_FISH) if isinstance(st, Mapping) else None
    fish = fish if isinstance(fish, Mapping) else {}
    entries: list = []
    for rid, raw in fish.items():
        if rid == CODEX_META_KEY:
            continue  # 聚合段非条目（D-1）
        if isinstance(raw, Mapping) and raw.get("seen"):
            entries.append({"species_id": str(rid), "entry": raw})
    entries.sort(key=lambda e: str(
        (e["entry"].get("name")
         if isinstance(e["entry"].get("name"), str) and e["entry"].get("name")
         else "") or e["species_id"]
    ))
    return entries


def render_fish_codex(ctx: MutableMapping[str, Any]) -> str:
    """/图鉴 鱼册特判渲染（T14 / 2c1c R-06：冠级标注，不教攻略）。

    入参：ctx（codex_state["fish"] 条目数据源；templates 可选）。出参：回复正文 str。
    渲染结构（D-2）：
      【鱼图鉴】
      已捕获 N 种 · 鱼王讨伐胜利 K 次
      {name} Lv0 · 最大 {best_size}cm/{best_weight}kg · {best_crown} · 逆金冠×{n}
      ...
    规则：
      - 只列已捕获（seen=true）条目（D-1）；未捕获不列不泄露（对齐 R-19）；
      - 冠级标注：best_crown 中文档位（CROWN_LABELS）+ 逆金冠×N 单独标注（R-06）；
      - 鱼综述行：捕获总数 / king_victory_count（2c1c E-01，批5 补全判定 R-07 读取）；
      - 不写判定公式/阈值（R-06 铁律：5/85/95 不可见，TC-07/TC-17 检索空）。
    纯函数确定性零 IO 零定时器/零睡眠（只读展示）；渲染零 emoji。
    """
    meta = fish_meta(ctx)
    entries = _fish_entries_of(ctx)
    king = int(meta.get(KING_VICTORY_COUNT_KEY, 0) or 0)

    lines = [_render(ctx, "fish_codex_header", _DEF_FISH_CODEX_HEADER, {})]
    lines.append(_render(ctx, "fish_codex_summary", _DEF_FISH_CODEX_SUMMARY,
                         {"caught": len(entries), "king": king}))
    if not entries:
        lines.append(_render(ctx, "fish_codex_empty", _DEF_FISH_CODEX_EMPTY, {}))
    else:
        for item in entries:
            entry = item["entry"]
            name = str(entry.get("name") or item["species_id"])
            lines.append(render_fish_entry_line(
                name,
                entry.get("best_size", 0.0),
                entry.get("best_weight", 0.0),
                str(entry.get("best_crown") or ""),
                entry.get("reverse_crown_count", 0),
            ))
    return "\n".join(lines)
