"""内容编辑器宿主层（编辑器重写批1 · 只读骨架）。

分层（细化_3a §1.4 依赖矩阵）：`web` 层允许依赖 {content, core, storage, data}，
且**不被任何层 import**（平台叶子层）。本包零 NoneBot import、零 FastAPI import：
HTTP 宿主在 `scripts/editor_host.py`，本包只出「元数据 → 界面 JSON」的纯读取逻辑。

对外入口见 `api.py`（内容包发现 / 模块层级 / 条目列表 / 条目全字段只读视图）。
"""

from qbot_rpg.web.api import (
    DEFAULT_GROUP,
    BadRequest,
    EditorError,
    NotFound,
    content_root,
    entry_detail,
    field_meta_table,
    list_entries,
    list_modules,
    list_packs,
    readonly_form,
    repo_root,
)

__all__ = [
    "DEFAULT_GROUP",
    "BadRequest",
    "EditorError",
    "NotFound",
    "content_root",
    "entry_detail",
    "field_meta_table",
    "list_entries",
    "list_modules",
    "list_packs",
    "readonly_form",
    "repo_root",
]
