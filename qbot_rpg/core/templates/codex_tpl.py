"""
模板分区：codex_tpl（图鉴指令（codex_commands）；2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

2026-09-12 消息模板重构（批9·路C）：
- 本分区全部 14 键（总览 codex_overview_header / codex_progress_line / codex_total_progress /
  codex_next_tier / codex_tier_maxed / codex_overview_hint、分册 codex_unknown_category /
  codex_category_header / codex_category_empty / codex_entry_line / codex_killed_mark /
  codex_rumor_mark / codex_unknown_name / codex_tail_tip）全部迁入全量表
  `qbot_rpg/core/templates/template_table.json`，按手机QQ 14 全角新规范重写
  （段头【图鉴】+副题、进度/里程碑拆两行（大数值独立行）、提示行免斜杠「发 图鉴 怪物 2」、
  错误行 ❌ + 原因 + 下一步）；本分区默认表与占位符白名单清空
  （白名单由表自动派生，见 core/templates/__init__.py）。
- 本路字形锚点保留：「（已击杀）」/「（传闻）」/「???」为引擎语义标记（R-19/R-20 不泄露、
  R-24/F-16 传闻标记消费），非可重排文案；条目行结构模板保留「标记 + 名称 + 状态后缀紧贴」
  形态（跨模块锚点 test_environment_lore「蚀月之狼（传闻）」按无空格拼接断言）。
- 本路无死键（14 键均有 tpl_of 调用点或引擎字形锚点）。
- 渲染链 = 新表（全量默认）→ 内容包 templates.json（覆盖）→ tpl_of（接口不变）。

历史铁律：字符串 = /图鉴 指令（/图鉴 总览 + /图鉴 分册[页码]）渲染文案，key 命名 codex_<用途>；
占位符白名单与渲染处 tpl_of(ctx, "codex_*", {...}) 一致；渲染零 emoji
（仅 ✅/❌ 功能性标记 + 排版符号 ｜ → × /「」【】）。

本空壳文件待批18 死键清扫时随其余已迁分区一并删除（过渡期保留 import 兼容）。
"""
from __future__ import annotations

from typing import Any, Dict

# 已清空：14 键已迁全量模板表；白名单由表自动派生（见 core/templates/__init__.py）。
DEFAULT_TEMPLATES: Dict[str, Any] = {}

PLACEHOLDER_WHITELIST: Dict[str, set] = {}
