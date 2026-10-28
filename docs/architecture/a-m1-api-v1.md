# A：M1 公开接口契约 v1（草案，已有实现）

状态：**Draft v1 / 已在分支 `feat/m1-reservation-v1` 实现并通过测试，待 B、C、D、E、F 评审。**
评审通过前，路径、字段和错误码都可以改；改动时同步更新本文和对应测试。

关联：[M1 需求基线与暂定决策](../requirements/a-m1-v1-baseline.md)、[验证记录](../testing/a-m1-v1-verification.md)、[B 的资源接口草案](b01-resource-api-draft.md)。

## 1. 通用约定

| 项目 | 约定 |
| --- | --- |
| 前缀 | `/api/v1/m1`；运行时的完整列表见 `/openapi.json` |
| 时间 | ISO 8601。**不带时区的输入按业务时区 `Asia/Shanghai` 解释**；带偏移的输入按偏移换算。响应一律带 `+08:00`。查询串中的 `+` 要编码为 `%2B` |
| 区间 | 半开区间 `[start_at, end_at)`：10:00 结束和 10:00 开始不冲突 |
| 错误 | 业务错误：`{"error": {"code", "message", "details"?}}`，`code` 是稳定的机器可读值；请求格式错误沿用 FastAPI 默认的 `422 {"detail": [...]}` |
| 身份 | 只依赖 `CurrentUser(id, department_id, permissions)`。C 接入认证前，`AUTH_MODE=dev-headers` 读取 `X-Dev-User-Id`、`X-Dev-Department`、`X-Dev-Permissions`（逗号分隔）；**仅限本地开发和测试** |
| 幂等 | 创建预约可带 `Idempotency-Key`（≤128 字符，按用户隔离）；限制的写入和解除天然幂等（见第 4 节） |

### 权限

| 权限 | 典型角色 | 用途 |
| --- | --- | --- |
| `m1:reservation:use` | 学生 | 搜索、预约、取消、签到、本人历史与违约 |
| `m1:checkin_code:view` | 教室屏幕终端、教室管理员 | 读取教室当日签到码 |
| `m1:ops:view` | 运营管理员 | 使用统计、座位状态追溯 |
| `m1:settings:manage` | 系统管理员 | 修改 M1 系统参数 |
| `m1:restriction:m2_approval` | M2 服务账号 | 写入/解除整教室审批占用 |
| `m1:restriction:m3_repair` | M3 服务账号 | 写入/解除报修下架 |

角色到权限的映射属于 C 的 RBAC，M1 只检查权限字符串。

## 2. 学生端接口

| 方法与路径 | 说明 | 成功 | 主要错误码 |
| --- | --- | --- | --- |
| `GET /seats/availability` | 查询某时段座位可用性。参数：`start_at`、`hours`，可选 `room_id`、`outlet_type`（`none`/`fixed`/`rail`）、`has_outlet`、`only_available` | 200 | `not_whole_hour`、`invalid_duration`、`start_not_in_future`、`beyond_booking_horizon`（均为 422） |
| `POST /reservations` | 预约。体：`{seat_id, start_at, hours}`；可带 `Idempotency-Key` | 201；同键重放返回 200 和原预约 | 上述 422；`outside_opening_hours` 422；`department_restricted` 403；`seat_not_found` 404；`seat_conflict`、`seat_restricted`、`seat_disabled`、`room_disabled`、`user_overlap`、`idempotency_key_reused` 409 |
| `GET /reservations/me` | 本人预约历史，按开始时间倒序。可选 `status`、`limit`（≤200）、`offset` | 200 | — |
| `GET /reservations/{id}` | 本人某个预约 | 200 | `reservation_not_found` 404（他人的预约同样返回 404） |
| `POST /reservations/{id}/cancel` | 开始前取消待签到预约 | 200 | 404；`not_cancellable`、`cancel_window_closed` 409 |
| `POST /reservations/{id}/check-in` | 体：`{code}`，签到码取自教室屏幕 | 200 | 404；`checkin_not_open`、`checkin_closed`、`already_checked_in`、`not_checkinable` 409；`invalid_checkin_code` 422；`checkin_not_configured` 503 |
| `GET /violations/me` | 本人违约记录 | 200 | — |
| `GET /settings` | 读取当前参数（前端据此显示最长预约时长等） | 200 | 401 |

可用性结果中每个座位都带 `reasons`，列出**所有**不可用原因，例如：

```json
{"seat_id": 5, "seat_code": "LIB-101-05", "available": false,
 "reasons": [{"code": "reserved"},
             {"code": "m3_repair", "source_type": "m3_repair", "source_id": "WO-17"}]}
```

`reasons` 的 `code` 取值：`room_disabled`、`seat_disabled`、`department_restricted`、`outside_opening_hours`、`reserved`、`m2_approval`、`m3_repair`。`reserved` 不透露是谁预约的。

预约响应**不包含签到码**：学生必须到现场读屏幕上的码才能签到。

## 3. 管理端接口

| 方法与路径 | 权限 | 说明 |
| --- | --- | --- |
| `GET /rooms/{room_id}/checkin-code` | `m1:checkin_code:view` | 返回 `{room_id, date, code, valid_until}`。码为 6 位数字，按业务时区每天零点更换；二维码可以直接编码这串数字 |
| `GET /ops/usage?date=YYYY-MM-DD` | `m1:ops:view` | 按教室汇总：各状态预约数、已签到座位小时、容量座位小时、利用率。**只有汇总，没有学生个人信息** |
| `GET /ops/seat-events?room_id=&seat_id=&limit=` | `m1:ops:view` | 座位状态追溯：每条写入的来源（`m1_reservation`/`m2_approval`/`m3_repair`）、来源 ID、动作、时间。服务账号和系统任务显示 `actor_id`，学生显示为 `null` |
| `PUT /settings` | `m1:settings:manage` | 部分更新参数，越界或未知键返回 422 |

## 4. M2/M3 写回契约（跨模块）

M2 和 M3 **只能**通过以下接口影响 M1 的座位可用性，不得读写 M1 的表。

### 4.1 写入限制

```
PUT /api/v1/m1/restrictions/{source_type}/{source_id}
source_type: m2_approval | m3_repair
source_id:   来源模块的业务 ID（审批单号/工单号），1–64 位 [A-Za-z0-9_.:-]
```

```json
{"room_id": 1, "seat_id": null, "start_at": "2026-11-03T10:00", "end_at": "2026-11-03T12:00", "note": "学术报告"}
```

- `seat_id` 省略表示整间教室。`end_at` 省略表示“直到解除”，**只允许 `m3_repair`**；M2 审批必须给出结束时间。
- 首次写入返回 **201**；用同一来源、相同参数重复调用返回 **200** 和原记录，因此超时后可以放心重试。
- 同一来源但参数不同返回 409 `restriction_conflict`；已解除的来源不能再次生效，返回 409 `restriction_released`，需要换新的业务 ID。
- 响应中的 `affected_reservation_ids` 列出与该限制重叠、仍然有效的个人预约。**M1 不会自动取消它们**：如何处理（拒绝审批、协调、取消并通知）尚待团队决定，见[暂定决策](../requirements/a-m1-v1-baseline.md#3-v1-的暂定决策待确认) D-07。
- 与正在进行的个人预约竞争时，M1 保证二者必居其一：要么预约被拒（`seat_restricted`），要么预约出现在 `affected_reservation_ids` 里。

### 4.2 解除限制

```
POST /api/v1/m1/restrictions/{source_type}/{source_id}/release
{"reason": "accepted"}
```

- M2 在驳回、撤销或超时撤销时调用，M3 在**验收通过**时调用（维修完成但未验收时不要调用）。
- 重复解除返回 200，不会重复记录；未知来源返回 404 `restriction_not_found`。
- 解除只影响这一个来源。同一教室上还有其他审批、其他工单或个人预约时，座位仍然不可预约。

### 4.3 查询与权限

- `GET /api/v1/m1/restrictions/{source_type}/{source_id}`：写入或解除超时后，先查询结果再决定是否重试。
- 每个服务只能操作自己的来源类型：持 `m1:restriction:m2_approval` 的调用方对 `m3_repair` 的任何操作都返回 403，反之亦然。

## 5. 给 E 的通知出口（暂定）

M1 不直接发送通知，而是把待发通知写入 M1 自己的 `m1_notification_outbox` 表：

| `kind` | 触发 |
| --- | --- |
| `reminder_before_start` | 开始前 15 分钟（可配置） |
| `reminder_not_checked_in` | 开始后 10 分钟仍未签到 |
| `no_show_cancelled` | 开始后 15 分钟未签到，已取消并记违约 |
| `cancelled_restricted` | 维修或审批占用期间未签到，已取消、不记违约 |

每个 `(reservation_id, kind)` 最多一条，任务重跑不会重复通知。`payload` 只有预约 ID、教室、座位和时间，收件人由 `user_id` 交给 E 解析。E 如何读取（M1 提供拉取接口，还是 M1 主动调用 E 的接口）待 E 和 D 确认；在此之前 `dispatched_at` 始终为空。

## 6. 数据所有权

| 表 | 所有者 | 其他模块 |
| --- | --- | --- |
| `m1_reservations`、`m1_seat_restrictions`、`m1_seat_state_events`、`m1_violations`、`m1_notification_outbox`、`m1_settings` | A | 只能通过本文接口访问 |
| `rooms`、`seats` | B（目前是 A 写的占位） | M1 只读 |
