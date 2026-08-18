# 3f 可达性补丁包 m0_3f_patch（M0 时点的最小可验面）

依据：细化_3f_单机向体验 §3.6（R-16 校验器可达性检查）/ 细化_3e §2.2 Y-7（未注册键空间黄提示）。

本目录**不属于** `tests/fixtures/packs/` 四件套（TC-5d-13 限定四包），是本里程碑为 3f 契约层
单独搭建的最小补丁包，仅被 tests/contract/test_3f_reachability.py 使用。

- 破坏点/观察点：`hidden_elements.json` 两条隐藏要素的 `condition` 引用**未注册**条件键
  （`[图鉴完成度:怪物]` / `nostalgia_points`），其中 `nostalgia_points` 未在 stats 注册 ——
  校验器（Y-7 机制）应给出「未注册键空间」黄提示（R-16「条件永假检测」在 validator 层的最小落点）。
- 契约层前置：`hidden_elements` 为未知模块，按细化_3e §2.3 默认放行，**不红栏** ——
  即 3f 数据包在 M0 可加载（后续 M6 才由编辑器校验器做完整 R-16 V/W 分层检查）。
- 断言见 tests/contract/test_3f_reachability.py（细化_3f#TC-21 最小子集）。
