# C-56：并发授权变更中的身份快照

日期2026-10-29，关联 #56；增量base为C #55/8e73b51。问题在AuthService._principal，影响所有消费C主体权限/资源范围的调用方，并非只影响目录。AI辅助复现、修复、测试和文档；非作者Review/最终合并仍由人决定。

## 真实问题

旧实现先SELECT账号enabled/department_id/room_ids/all_rooms，再SELECT角色和权限。默认PostgreSQL READ COMMITTED下，即使位于同一事务，不同SQL仍可看到不同快照；并发change_access虽原子更新，也不能阻止读者将两个版本拼接。

| 主体版本 | 资源范围 | 能力 | 是否能读R1的他人申请 |
| --- | --- | --- | --- |
| 变更前 | 全域或R1 | 只有m2.submit | 否，无读取许可 |
| 变更后 | 仅R2 | first角色，含m2.read_all和审批许可 | 否，不在资源范围 |
| 旧实现竞态拼接 | 旧全域/R1 | 新first权限 | 错误允许 |

真实PostgreSQL与公开API复现：查询账号后暂停该读取，使用真实管理Bearer调用PUT /api/v1/auth/users/{id}/access提交角色/范围变更，再恢复原GET。申请详情、actions、integration三个接口，各覆盖全域收窄与显式教室范围变更，共6例均出现 **[变更前404，竞态200，变更后404]**；旧实现结果 **6 failed, 1 passed**，并非前端展示或Mock授权推断。

测试边界包装器只转发真实SQL并在查询execute完成后用Event暂停，不修改游标结果、不Mock authenticate/_principal或管理/读取业务。管理策略、账号和教室均为专用随机schema内合成夹具，不批准生产授权政策。

## 修复与边界

账号enabled、院系、范围和角色/权限以同一SELECT读取，角色用相关子查询JSONB聚合，空角色显式空数组；Python继续转成原Principal的角色和权限frozenset。一个SQL语句内使用同一MVCC快照，避免返回从未被授予的权限与范围组合。

没有新增账号锁、事务隔离级别、全局状态、缓存、角色、权限、API字段或Schema；不改C-35密码校验/最终复核，不改角色管理和审计规则。不是追溯中止已在途请求的能力；本次只保证一个主体视图的字段一致。后续请求仍重新验证会话与当前主体，旧权限不能缓存为长期授权依据。

## 已执行验证

本地Python3.13.11、临时PostgreSQL16.2，沿用统一锁。固定B #48/4ee2fe5公开模块与当前C逐文件验证后投影到 `/private/tmp/c56-combined-final`；C独立树未安装B。所有数据库变更只在测试私有schema，未触及共享或生产数据。

```bash
# 已注入专用C_TEST_DATABASE_URL，在仓库运行。
python -m pytest backend/tests/c_module/test_principal_snapshot.py -q
# 在固定组合目录backend/运行，已注入专用CAMPUS_DB_*。
CAMPUS_TEST_POSTGRES=1 CAMPUS_REQUIRE_RESOURCE_ACCEPTANCE=1 python -m pytest -q
```

- 最终定向 **7 passed, 1 warning in4.03s**：6个公开API竞态场景与空/多角色权限并集；重复8轮，**56项全部通过**。记录 `/private/tmp/c56-targeted-corrected.log`、`/private/tmp/c56-repeated-final.log`。
- 固定B/C完整回归 **260 passed, 1 warning in49.04s，无skip**，包含C目录真实身份/TCP、B过滤、事务审计、M2状态与先前登录签发竞态。记录 `/private/tmp/c56-final-full-regression.log`。
- 修复后首次新增测试末尾错误地按顶层room_ids或scope访问/me；实际已有字段是data_scopes。该KeyError也导致首轮组合6 failed/254 passed；已按既有契约修正测试字段，未改产品API、404断言或授权场景，最终全量重新通过。旧实现的越权失败及最终负对照都检查原始404/200行为，不以KeyError充当缺陷复现。

负对照仅在 `/private/tmp/c56-negative` 隔离副本恢复8e73b51旧AuthService：**7 passed → 6 failed, 1 passed**（竞态200而非404）→逐字节恢复修复后 **7 passed**。测试使用最终data_scopes断言，原始记录 `/private/tmp/c56-negative-control.log`；仓库未写入破坏版本或削弱权限断言。

C独立分支在backend/运行 `CAMPUS_TEST_POSTGRES=1 python -m pytest -q`，未设置CAMPUS_REQUIRE_RESOURCE_ACCEPTANCE：**154 passed, 2 skipped, 1 warning in29.44s**。两个skip为B未安装的组合模块，专用验收要求B存在；记录 `/private/tmp/c56-standalone-regression.log`。

本地C Ruff/格式48文件、组合58文件、编译、依赖一致性和diff检查通过。远端Python3.13/PostgreSQL17及前端/Compose以本增量PR实际Checks为准，完成后补链接。保留既有TestClient/HTTPX弃用警告，不为此增加依赖或削弱测试。原C SQL和OpenAPI保持，无迁移、工作流或其他owner代码改动。本机Docker NOT RUN，真实A/M1 #23、E通知#25、D选择器和非作者Review仍是独立待办。
