"""M13 /转职 模板分区（qbot_rpg/core/templates/job_tpl.py · 批14 路14A）。

占位符白名单：job/list/rec。
"""

from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, str] = {
    "job_list": "当前可转职业：{list}",
    "job_not_found": "❌ 没有『{job}』这个职业，可用：{list}",
    "job_switch_success": "✅ 转职成功！当前职业：{job}{rec}",
    # 2026-09-05 职业详情（职业详情 <序号|名称>）
    "job_detail_usage": "职业详情：发 职业详情 <序号|名称>（如 职业详情 1 / 职业详情 脊剑士）",
    "job_detail_header": "【{name}】",
    "job_detail_rec": "（推荐新手）",
    "job_detail_line": "{k}：{v}",
}

PLACEHOLDER_WHITELIST: Dict[str, set] = {
    "job_list": {"list"},
    "job_not_found": {"job", "list"},
    "job_switch_success": {"job", "rec"},
    "job_detail_usage": set(),
    "job_detail_header": {"name"},
    "job_detail_rec": set(),
    "job_detail_line": {"k", "v"},
}


def default_templates() -> Dict[str, Any]:
    return dict(DEFAULT_TEMPLATES)
