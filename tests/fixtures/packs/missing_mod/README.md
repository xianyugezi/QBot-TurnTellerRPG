# 缺模块包 missing_mod

依据：细化_5d §5.1（TC-5d-13）/ 细化_3e §1.2（Y-6 声明缺失=黄提示继续）/ 3a#TC-12 / 细化_3e#TC-09/TC-17。

- 破坏点（软性，不红拦）：
  1. **声明缺失**：manifest 声明 `statuses`，但磁盘**无 statuses.json** → Y-6 黄提示
     「没找到 statuses.json…旧包照常玩」，包仍可挂载（状态系统不启用）；
  2. **未声明文件不加载**：磁盘有 `npc.json`（合法数据）但 manifest **未声明** → 不加载，
     registry 无任何 npc 条目（防误启用）。
- 断言见 tests/unit/test_content.py::test_missing_mod_pack_y6（细化_3e#TC-17 / 3a#TC-12）。
