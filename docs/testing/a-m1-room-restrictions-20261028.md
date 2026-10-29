# A：整室下架规则修正与验证

## 决策和变更

负责人于 2026-10-28 选择“整间教室下架”。我据此将 M3 写回范围统一为整室，并遵循项目 README / AGENTS.md 的现有约束：验收通过后才解除；其他来源的限制仍然生效。M2 整教室审批同样不接受单座位范围。

- 传入具体 `seat_id`：422 `room_scope_required`。
- M3 指定 `end_at`：422 `repair_end_forbidden`，避免未经验收按时间自动恢复。
- M3 解除原因不是 `accepted`：422 `repair_acceptance_required`；不写入解除事件。
- M3 仍负责核实真实验收事实。M1 检查来源权限及解除原因；当前开发身份不是正式服务认证。
- 既有预约的协调方式和违约豁免等暂定政策没有因此获得批准。

此次只修改接口校验、相关测试和文档，不改写已有数据库迁移。旧开发数据库如存在单座位或定时维修限制，需要单独核对和处理历史数据；本次验证只操作专门创建的临时数据库。

## 本次实际执行

本机：macOS arm64、Python 3.14.5、PostgreSQL 17.11。使用隔离 venv 和 D 主线 `a038472` 的 `requirements-dev.txt` 锁定依赖；数据库仅监听本机回环地址。此结果不是 Python 3.13 GitHub CI 的替代证据。

从 `backend/` 执行，`TEST_DATABASE_URL` 指向有建库权限的临时 PostgreSQL：

```sh
python -m pytest -q tests/m1/test_timeslots.py
# 14 passed
python -m pytest -q
# 90 passed, 373 warnings in 10.96s
```

警告涉及来源代码的 SQLAlchemy `Result.tuples()` 弃用、Alembic 路径配置和上游 Starlette TestClient 对 httpx 的弃用提示。没有通过屏蔽断言或删除失败测试来通过检查。整合 D 工程之后需重新执行完整验证。

## 测试有效性验证

临时禁用 `restrictions.apply` 中拒绝具体 `seat_id` 的判断，执行：

```sh
python -m pytest -q tests/m1/test_restrictions.py -k seat_level
# 2 failed, 17 deselected
```

两个失败分别对应 M2、M3 单座位请求被错误接受。恢复原文件后执行相同命令：`2 passed, 17 deselected`；已确认文件与变异前逐字节相同。故意破坏的实现不提交。

原测试 `test_seat_level_restriction_blocks_only_that_seat` 验证的是已经被负责人否决的业务行为，现替换为参数化的拒绝测试，同时检查没有产生下架副作用。另增加拒绝定时维修、拒绝未验收解除、跨教室隔离和同室多个座位预约均被阻止的检查。

## 参与和限制

代码修正、测试执行与记录由 Codex 辅助完成；业务选择来自负责人。原 11 个交接阶段保留为独立提交，这次修正另行提交，使用实际提交时间。

尚未完成：与 D 脚手架整合后的回归、GitHub CI、正式身份接入、B 的资源模型确认、M2/M3 独立服务之间的真实网络联调，以及非作者人工 Review。
