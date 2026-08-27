# 空白包 demo_blank（M6 五档数据包 · 第 1 档）

依据：D4《细化_M6_内容包冒烟》§五（PCK-02/05/06，F-08）+【框架】§4.3 空白包 + §15 content/demo_blank。

- 档位：空白包（无等级区间；最小可玩模块集）。
- 模块集【工程补白】= manifest/settings/stats/formula + 必需最小表 effects/items
  （PCK-05：demo_blank=最小可玩模块集；effects/items 为可玩性必需的最小表，heal_small→potion 闭环）。
- 内容基线 = tests/fixtures/packs/legal 数据子集（PCK-11，不独立编造数值）。
- 无怪物 → 不跑战斗（PCK-06），只跑 validator 全绿 + registry 装配成功。
- 断言见 tests/unit/test_pack_fixtures_matrix.py::TC-PCK-02/04/06。
