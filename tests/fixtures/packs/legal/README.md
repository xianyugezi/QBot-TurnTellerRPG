# 合法包 legal

依据：细化_5d_测试体系总纲 §5.1（TC-5d-13，四件套之一）/ 细化_3e §5.2 / 细化_3e TC-30。

- 目的：`load_pack` 全绿基线 —— validator 全绿（0 errors，0 warnings）+ registry 全量注册且 ID 唯一。
- 破坏点：**无**（故意构造为完全合法的对照基线）。
- 内容（manifest 声明 8 模块，与磁盘文件一一对应，无缺失无未声明）：
  - `effects.json`：heal_small / power_slash / rage_up（rage_up.apply_status 引用 statuses.berserk）
  - `statuses.json`：regen（effects→heal_small / on_tick→heal_small）、berserk
  - `marks.json`：fire_mark（type=mark）
  - `items.json`：potion / hi_potion（effects 引用 effects 家族）
  - `equipment.json`：iron_sword / iron_shield（slot=weapon/shield；excludes 单向互斥无环）
  - `enemies.json`：slime / forest_wolf / oak_golem
  - `stats.json`：九预置键空间（resource: hp/mp；combat: str/int/con/spr/foc/agi/lck）
  - `formula.json`：damage_base / heal_rate（无黑名单词，合法公式）
- 断言见 tests/unit/test_content.py::test_legal_pack_full_green（细化_3e#TC-30 / 3a#TC-09/22）。
