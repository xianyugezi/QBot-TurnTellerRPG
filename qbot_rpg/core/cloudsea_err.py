# -*- coding: utf-8 -*-
"""云海错误文案分区与 $C.* 字面替换 helper（九期批次 233 · G5）。

文件名：qbot_rpg/core/cloudsea_err.py
（cloudsea-pack 合并适配：原 templates/cloudsea_err_tpl.py——作者终态
    templates/ 目录仅剩加载器 + base + 全量表，无 *_tpl.py 分区文件；本模块
    实为 helper + 键清单，迁入 core/ 与 cloudsea_* 模块群同址，键清单与
    expand_consts 语义零改。）
依据：设计稿 08_错误文案表.md（§M8.12 七条＋§M8.13 六条＋§M8.15 八条＝21 条，逐字零改写，
    注入通道＝content/cloudsea/templates.json）；生产排期_适配期_九期 G5 233 任务书。

功能：
  - CLOUDSEA_ERR_KEYS：21 键清单（供校验/帮助/断言对账）；
  - expand_consts(text, consts)：文案内 ``$C.DOMAIN.KEY`` 字面替换——consts 为
    「键路径 → 值」映射（调用方注入：208 对账管线 fragments 或 235H 落包 settings）；
    查不到的键保留字面（fail-safe，不抛错不吞文案）。

红线：零引擎 hook（纯字符串处理）；不改既有模板分区（base.py 等）；
    ``$C.*`` 替换只在显式调用本 helper 的渲染口生效，框架默认渲染零影响。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Mapping

# 21 键（与 content/cloudsea/templates.json 一一对应；场景序沿 08_错误文案表.md）
CLOUDSEA_ERR_KEYS: Dict[str, str] = {
    # §M8.12 七条
    "err_unknown_subword": "指令不存在",
    "err_wind_lack": "风缆不足",
    "err_ult_not_full": "绝技未满",
    "err_long_sleep_frozen": "长眠冻结",
    "err_not_your_turn": "非你回合",
    "err_delegate_busy": "托管中抢答",
    "err_bound_slot": "束缚锁位",
    # §M8.13 六条
    "err_recipe_locked": "配方未获得",
    "err_recipe_unknown": "序号/名称不存在",
    "err_material_lack": "材料不足",
    "err_mix_not_turn": "非你回合调和",
    "err_mix_delegated": "托管中调和",
    "err_deep_gate_or_material": "深度门槛未达/加倍缺料",
    # §M8.15 八条
    "err_synth_in_battle": "战斗中禁用合成",
    "err_deep_gate_material_ok": "深度门槛未达（材料足）",
    "err_mix_recipe_missing": "调和配方未获得",
    "err_mix_already": "本回合已调和",
    "err_deep_not_mixable": "深度产物误发调和",
    "err_name_ambiguous": "名称歧义多命中",
    "err_delegate_alchemy": "托管中发炼金指令",
    "err_deep_list_empty": "深度一览为空",
}

_CONST_RE = re.compile(r"\$C\.[A-Za-z0-9_.]+")


def expand_consts(text: str, consts: Mapping[str, Any]) -> str:
    """``$C.DOMAIN.KEY`` 字面替换（九期 233）。

    consts：键路径（如 ``"ALCHEMY.DEEP_COST_MULT"``，带不带 ``C.`` 前缀均可）→ 值。
    查不到的键**保留字面**（fail-safe：不抛错、不吞文案、不产生空串）。
    """
    if not isinstance(text, str) or "$C." not in text:
        return text

    def _sub(m: "re.Match[str]") -> str:
        path = m.group(0)[3:]  # 剥 "$C."
        for cand in (path, "C." + path):
            if cand in consts:
                return str(consts[cand])
        return m.group(0)  # 保留字面

    return _CONST_RE.sub(_sub, text)


__all__ = ["CLOUDSEA_ERR_KEYS", "expand_consts"]
