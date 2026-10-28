# A：M1 后端 v1 验证记录

> 本文是 v1 的记录（2026-10-27），保留原样。之后的修改与验证另有记录：整间教室维修规则见 [a-m1-room-restrictions-20261028.md](a-m1-room-restrictions-20261028.md)，接入 D 的工程脚手架见 [a-m1-d-integration-20261028.md](a-m1-d-integration-20261028.md)。文中的 `TEST_DATABASE_URL`、迁移编号 0001–0005 等是当时的说法。

记录日期：2026-10-27。本文只记录**实际执行过**的检查；没有执行的写在第 6 节。

## 1. 环境

| 项目 | 版本 |
| --- | --- |
| Python | 3.12.11（独立 venv） |
| PostgreSQL | 16.15，Docker 镜像 `postgres:16-alpine`，仅监听 127.0.0.1 |
| 主要依赖 | FastAPI 0.115.14、SQLAlchemy 2.0.55、psycopg 3.2.13、Alembic 1.14.1、pytest 8.4.2（见 `backend/requirements*.txt`） |

## 2. 自动化测试

```bash
cd backend
export TEST_DATABASE_URL=postgresql+psycopg://m1:m1test@127.0.0.1:56432/m1
python -m pytest -q
# 85 passed
```

| 测试文件 | 用例数 | 覆盖 |
| --- | --- | --- |
| `tests/test_health.py` | 2 | 健康检查；数据库不可达时返回 503 |
| `tests/test_migrations.py` | 2 | ORM 模型与迁移后的库结构一致；完整降级到空库再升级 |
| `tests/test_seed.py` | 2 | 种子执行两次结果相同；插座座位标记 |
| `tests/m1/test_timeslots.py` | 14 | 整点、时长、时区换算、预约窗口、开放时间边界 |
| `tests/m1/test_availability_api.py` | 11 | 搜索、筛选、相邻/重叠/已取消预约、院系、开放时间、401/403 |
| `tests/m1/test_reservations_api.py` | 13 | 预约、冲突、同人重叠、规则校验不写库、参数生效、幂等、取消、越权、历史 |
| `tests/m1/test_concurrency.py` | 5 | 10 人抢同一座位、部分重叠竞争、同人抢两座、重复提交、30 轮死锁回归 |
| `tests/m1/test_checkin.py` | 9 | 签到码、签到窗口边界（09:45 可签、10:14:59 可签、10:15 不可签）、错码/他室码/昨日码、越权、重复、未配置密钥 |
| `tests/m1/test_jobs.py` | 8 | 三个时间点、重跑不重复、已签到/已取消不违约、任务延迟、签到与违约任务竞争、CLI |
| `tests/m1/test_restrictions.py` | 14 | M2 占用、M3 下架与验收恢复、多来源叠加、座位级限制、幂等、越权、参数校验、已有预约上报、追溯、违约豁免、预约与限制竞争 |
| `tests/m1/test_ops_and_settings.py` | 5 | 使用统计（无个人信息）、权限、追溯隐藏学生、参数修改与校验 |

测试使用真实 PostgreSQL：每次运行新建数据库并从空库执行全部迁移，所以每次运行本身就是一次“从空库重放”。并发测试用多个线程、各自独立的数据库会话，不使用 mock。

开发按 9 个步骤进行，每一步的代码都单独跑过测试：2 → 6 → 31 → 48 → 57 → 65 → 79 → 80 → 85 个用例，全部通过。

## 3. 真实 HTTP 冒烟

对一个全新的数据库执行 `alembic upgrade head`，再执行两次 `python scripts/seed.py`，然后用 `uvicorn app.main:create_app --factory` 启动服务并用 curl 调用：

| 操作 | 结果 |
| --- | --- |
| `GET /api/health` | `{"status":"ok","database":"ok"}` |
| 搜索 LIB-101 明天 10:00 起 2 小时的插座座位 | 6 个座位，全部可预约 |
| 预约座位 1（带 `Idempotency-Key`） | 201 |
| 同一个键重试 | 200，返回同一预约 |
| 另一学生预约同一座位同一时段 | 409 `seat_conflict` |
| 09:30 开始的预约 | 422 `not_whole_hour` |
| M3 对 LIB-101 写入维修限制 | 201，`affected_reservation_ids: [1]` |
| 维修期间搜索 | 座位不可用，原因 `m3_repair` / `WO-SMOKE` |
| M3 验收通过后解除 | 200，座位恢复可预约 |
| M2 账号尝试解除 M3 的限制 | 403 |
| 运营查看座位 1 追溯 | `m3_repair WO-SMOKE restriction_applied svc-m3`；`m1_reservation 1 reserved`，学生 ID 显示为 null |
| `python -m app.modules.m1_reservation.jobs` | 正常执行一轮 |

## 4. 故意破坏实现，确认测试会失败

每次只改一处，在仓库之外的副本上执行，跑完删除副本，仓库代码未被修改。

| # | 破坏方式 | 结果 | 发现它的测试（节选） |
| --- | --- | --- | --- |
| 1 | 整点校验失效，接受 09:30 | 4 failed | `test_non_whole_hour_start_is_rejected`、`test_rule_violations_are_rejected_without_writing` |
| 2 | 时长上限失效 | 6 failed | `test_duration_outside_one_to_max_hours_is_rejected`、`test_max_hours_setting_change_takes_effect` |
| 3 | 违约判断 `<=` 改为 `<`（第 15 分钟整不取消） | 5 failed | `test_no_show_at_fifteen_minutes_cancels_records_one_violation_and_notifies` |
| 4 | 去掉院系准入检查 | 2 failed | `test_department_room_is_restricted_to_its_department` |
| 5 | 任何签到码都通过 | 1 failed | `test_wrong_other_room_and_stale_codes_are_rejected` |
| 6 | 只保留“先查后插”：去掉座位锁和数据库排他约束 | 2 failed | `test_partially_overlapping_races_still_cannot_double_book`、`test_overlapping_races_never_deadlock` |
| 7 | 解除一个限制时把同教室所有限制都解除 | 1 failed | `test_releasing_one_source_keeps_blocks_from_the_others` |
| 8 | 去掉来源权限检查（M2 可解除 M3 的限制） | 1 failed | `test_callers_may_only_touch_their_own_source_type` |
| 9 | 去掉维修期间的违约豁免 | 1 failed | `test_no_violation_when_the_room_was_under_repair` |
| 10 | 学生可以取消他人预约 | 1 failed | `test_users_cannot_read_or_cancel_each_others_reservations` |

10 处破坏全部被发现。需要注意第 6 项：只跑一次的“10 人抢同一座位”测试**没有**发现它，是部分重叠竞争测试和 30 轮压力测试发现的。可见单次并发测试通过不能证明没有竞态问题。

## 5. 开发中发现的问题

以下问题都真实发生过，可以作为 AI 生成代码质量隐患的例子。

1. **并发预约会死锁（代码缺陷，已修复）。** 第一版只靠“应用层检查 + 数据库排他约束”防止重复预约。多个时段部分重叠的请求同时到达时，PostgreSQL 在检查排他约束时可能互相等待，报 `deadlock detected`。座位不会被重复预约，但用户会看到 500。这个问题只是偶发：已有的 4 个并发测试连跑 15 次都没出现，后来在开发其他功能时出现了一次。补写的 30 轮压力测试修复前 3/3 失败；修复方式是预约前先对座位加 advisory lock，让同一座位的请求排队，修复后 5/5 通过。修复单独成为一次提交。
2. **测试本身写错（测试缺陷，已修正）。** 第一次写“部分重叠竞争”测试时选的区间里有两个首尾相接、并不重叠，两笔预约本来就都应该成功，测试却断言只能成功一笔。修正为每两个区间都真正重叠，并直接断言数据库里不存在重叠的有效预约。
3. **测试没有测到它声称要测的东西（测试缺陷，已修正）。** “预约与限制竞争”测试最初每轮使用同一时段，第一轮之后旧的限制一直有效，后面几轮其实不存在竞争。改为每轮使用独立时段，并确认两种先后顺序都实际出现过。

## 6. 未执行（NOT RUN）

| 项目 | 原因 |
| --- | --- |
| CI 流水线、自动部署、生产发布与回滚 | 流水线由 D 负责，尚未建立 |
| 与 B 前端的联调 | 前端尚未实现 |
| 与 M2、M3 的真实网络联调 | 对方服务尚未实现；本文第 3 节是用 curl 模拟它们的调用 |
| 真实认证 | C 的认证尚未接入 |
| 压力测试 / 性能测试 | 未做；只做了正确性方面的并发测试 |
| 安全评审 | 未做 |
| 前端构建、代码格式检查 | 未配置相应工具 |

## 7. 仍需人工确认

- 审阅全部代码和迁移，特别是 `reservations.py` 的加锁顺序和 `restrictions.py` 的写回语义。
- 与团队确认[暂定决策](../requirements/a-m1-v1-baseline.md#3-v1-的暂定决策待确认)，尤其是 D-03、D-05、D-07、D-08。
- B 评审 `rooms`/`seats` 占位模型；D 评审临时脚手架；C、E 评审第 4 节写回契约。
- 在自己的环境中按 `backend/README.md` 复现一次测试，并在 PR 中写明实际结果。

## 8. AI 参与说明

本版代码、测试和文档由 AI 编程助手（Claude Code）在 A 的指示下编写，并在上述环境中实际运行验证。最终的验收、提交和评审责任由 A 承担。
