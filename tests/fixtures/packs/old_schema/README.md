# 旧 schema 包 old_schema

依据：细化_5d §5.1（TC-5d-13）/ §1.2 L3（旧 schema 包报「可读+可迁移」）/ 细化_3e §2.3 默认放行兜底 / MIG-1（缺补默认 / 多忽略）。

- 破坏点：`manifest.schema_version = 0`（新版为 1）+ 条目全部使用旧版最小字段：
  - `items[].old_potion` 缺 price/effects/slot —— **缺补默认**不红拦；
  - `items[].old_potion.x_future_field` 为未来版本未知字段 —— **多忽略**（§2.3 默认放行）；
  - `enemies[].old_slime` 只有 id+name，缺 hp/atk/def/traits/actions —— 按默认 0/空 挂载。
- 语义：旧配置按「无效果/无链/无印」降级可读，不抛异常（【规则】L302）；字段级迁移缺口由
  storage 层 row_to_player（MIG-1）与 registry 默认值共同兜底，测试见
  tests/unit/test_content.py::test_old_schema_pack_tolerated + tests/unit/test_storage.py（MIG-1）。
