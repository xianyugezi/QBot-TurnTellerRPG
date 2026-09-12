"""
模板分区：fishing_tpl（钓鱼指令 fishing_commands / fishing_reel_commands /
fishing_codex_commands；2026-09-01 模板配置化分区，批6 路6A 主 agent 收口）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

2026-09-12 消息模板重构：
- 批9·路B：本分区全部 15 键（钓点列举 fish_off / fish_spot_list_header /
  fish_spot_line / fish_spot_empty / fish_intent_ref，鱼讯 fish_bite_idle /
  fish_bite_waiting / fish_bite_triggered，收杆 fish_reel_bad_choice /
  fish_reel_timeout / fish_reel_stop / fish_reel_success，鱼图鉴
  fish_codex_header / fish_codex_summary / fish_codex_empty）全部迁入全量表
  qbot_rpg/core/templates/template_table.json，按手机QQ 14 全角新规范重写
  （每行一字段拆行、免斜杠指令写法、去 ｜ 挤宽、错误行 ❌+原因）；
  咬钩/等待/跑鱼三类氛围叙事句登记 meta.prose_keys 允许自然折行；
  本分区默认表与占位符白名单清空。
  本路无死键清除（15 键全仓均有渲染调用点）。

渲染链 = 新表（全量默认）→ 内容包 templates.json（覆盖）→ tpl_of（接口不变）；
渲染零装饰 emoji（仅 ✅/❌ 功能性标记 + 【】｜→ 等排版符号）。

本空壳文件待批18 死键清扫时随其余已迁分区一并删除（过渡期保留 import 兼容）。
"""
from __future__ import annotations

from typing import Any, Dict

# 已清空：键已迁全量模板表；白名单由表自动派生（见 core/templates/__init__.py）。
DEFAULT_TEMPLATES: Dict[str, Any] = {}
PLACEHOLDER_WHITELIST: Dict[str, set] = {}
