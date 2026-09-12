"""M13 /转职 模板分区（qbot_rpg/core/templates/job_tpl.py · 批14 路14A）。

占位符白名单：job/list/rec。

2026-09-12 消息模板重构（批11·路A）：
- 本分区全部 8 键（job_list / job_list_tip / job_not_found / job_switch_success /
  job_detail_usage / job_detail_header / job_detail_rec / job_detail_line）全部迁入全量表
  `qbot_rpg/core/templates/template_table.json`，按手机QQ 14 全角新规范重写
  （列表段头独立行、尾段 Tip 两条动作各占一行、错误行 ❌ + 原因 + 可用清单、
  转职成功拆两行、用法行免斜杠去 ｜）；本分区默认表与占位符白名单清空
  （白名单由表自动派生，见 core/templates/__init__.py）。
- 本路结构模板/字形锚点保留：job_list「段头 + \n{list}」（壳层按空 list 取标题行）、
  job_detail_header「【{name}】」、job_detail_rec「（推荐新手）」角标（M5 裁决纯文本角标）、
  job_detail_line「{k}：{v}」字段行。
- 本路无死键（8 键均有 tpl_of 调用点：job_commands._job_list_render / _job_detail_text /
  cmd_job）。
- 渲染链 = 新表（全量默认）→ 内容包 templates.json（覆盖）→ tpl_of（接口不变）。

历史铁律：字符串 = /转职 指令（无参列表 + <序号|名称> 转职 + 职业详情）渲染文案，
key 命名 job_<用途>；占位符白名单与渲染处 tpl_of(ctx, "job_*", {...}) 一致。

本空壳文件待批18 死键清扫时随其余已迁分区一并删除（过渡期保留 import 兼容）。
"""
from __future__ import annotations

from typing import Any, Dict

# 已清空：8 键已迁全量模板表；白名单由表自动派生（见 core/templates/__init__.py）。
DEFAULT_TEMPLATES: Dict[str, Any] = {}

PLACEHOLDER_WHITELIST: Dict[str, set] = {}
