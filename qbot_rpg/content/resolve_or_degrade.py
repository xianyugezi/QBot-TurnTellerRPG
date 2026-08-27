"""删除配置统一降级入口（WIR-14 / 细化_3e2 OLD-4 / 细化_M6_热重载接线 §1.2 WIR-14）。

依据：
  - 细化_M6_热重载接线（D3）WIR-14：删除配置语义二分——配置加载期 R-4 红拦回退
    （删除不生效）；运行期（旧局）resolve→None → 按「无效果/无链/无印」降级不抛异常
  - 细化_3e2_热重载契约 OLD-4（旧会话快照引用已删配置 → resolve→None 降级）
  - 【规则】L177（旧局旧配置：进行中对局持旧快照按旧配置结算，删除配置按无效果降级）

本模块提供统一降级入口 `resolve_or_degrade(registry, id, kind) -> (Def|None, degraded)`，
degraded=True 表「旧局引用已删配置」（供降级提示 / 日志），消费方按「无效果/无链/无印」
降级不抛异常。

消费点登记（WIR-14）：核心消费点 effects 已复用（core/effects._make_resolver）；
reward / marks / combo / quest 登记如下（各自现状已按 None 降级，不悬空报错）：
  - marks：core/marks._make_resolver 镜像实现——def 查无 → 按「无印记」降级（§九）已具备
  - reward：ctx["items"]/resolve_item 存在性检查——item_not_found → 该条 skip（§4 第 4 条）
  - combo：default_resolver 扁平 defs 映射——缺链/缺技 → 查无即降级
  - quest：以 registry 引用解析，查无按「无效果」降级
  （上述消费点与本入口语义一致；如需统一接线可后续批次迁移到本入口，本批仅登记。）
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

__all__ = ["resolve_or_degrade", "resolve_many"]


def resolve_or_degrade(
    registry: Any,
    id: str,
    kind: str,
) -> Tuple[Optional[object], bool]:
    """统一降级入口（WIR-14）：按 kind 解析配置，返回 (Def|None, degraded)。

    - 解析命中 → (Def, False)：正常运行；
    - 查无（配置已被删除 / registry 缺失）→ (None, True)：旧局引用已删配置，
      消费方按「无效果/无链/无印」降级不抛异常（OLD-4 / 规则 L177）；
    - registry 为 None 或不可解析 → (None, True)（降级兜底）。

    :param registry: Registry（.resolve(id, kind)）或 Mapping（kind → {id: Def}）
                     或 callable(id, kind) -> Def|None（对齐 effects._make_resolver 归一化）
    :param kind: 注册表 kind（如 "effect"/"status"/"mark"/"skill_chain"/"skill"）
    :return: (Def|None, degraded)
    """
    if registry is None:
        return None, True
    if callable(registry):
        defn = registry(id, kind)
    else:
        resolve = getattr(registry, "resolve", None)
        if callable(resolve):
            defn = resolve(id, kind)
        elif isinstance(registry, Mapping):
            defn = (registry.get(kind) or {}).get(id)  # type: ignore[union-attr]
        else:
            return None, True
    if defn is not None:
        return defn, False
    return None, True


def resolve_many(
    registry: Any,
    ids: Tuple[str, ...],
    kind: str,
) -> Tuple[Tuple[Optional[object], ...], bool]:
    """批量解析（同 resolve_or_degrade 语义；任一查无 → degraded=True）。"""
    degraded = False
    out: list = []
    for did in ids:
        defn, deg = resolve_or_degrade(registry, did, kind)
        out.append(defn)
        degraded = degraded or deg
    return tuple(out), degraded
