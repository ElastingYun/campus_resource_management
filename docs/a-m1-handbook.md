# M1 后端说明书（给 B、C、D、E、F）

> 作者：A（M1 后端）。适用于分支 `feat/m1-reservation-v1` 上的 M1 v1。
> 本文说明 M1 后端提供了什么、你需要怎样对接、哪些地方需要你评审或接管，以及如何在此基础上继续开发（§5）。接口细节以[接口契约](architecture/a-m1-api-v1.md)为准，两者不一致时请指出，我会修正。

## 0. 一页概览

- M1 v1 已实现：座位搜索、整点预约、取消、每日签到码签到、提醒与违约任务、本人历史、运营汇总、参数管理，以及接收 M2/M3 写回的接口。
- 85 个自动化测试在真实 PostgreSQL 上通过；10 处故意破坏的实现全部被测试发现。见[验证记录](testing/a-m1-v1-verification.md)。
- **未完成的部分要靠你们**：认证（C）、通知发送（E）、前端（B）、流水线与部署（D）、M2/M3 的真实联调（C、E、F）。
- **有 13 条规则是暂定的**，需要团队确认，见[需求基线第 3 节](requirements/a-m1-v1-baseline.md#3-v1-的暂定决策待确认)。

建议阅读顺序：本文 → [接口契约](architecture/a-m1-api-v1.md) → [需求基线](requirements/a-m1-v1-baseline.md) → [`backend/README.md`](../backend/README.md)。

## 1. 跑起来

```bash
cd backend
python3.12 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt
docker run -d --name crm-pg -e POSTGRES_USER=campus -e POSTGRES_PASSWORD=campus \
    -e POSTGRES_DB=campus -p 127.0.0.1:5432:5432 postgres:16-alpine
cp .env.example .env && set -a && . ./.env && set +a
alembic upgrade head && python scripts/seed.py
uvicorn app.main:create_app --factory --reload     # http://127.0.0.1:8000/docs
```

本地用请求头扮演身份（只在 `AUTH_MODE=dev-headers` 时生效）：

```bash
curl -H "X-Dev-User-Id: stu-001" -H "X-Dev-Department: cs" \
     -H "X-Dev-Permissions: m1:reservation:use" \
     "http://127.0.0.1:8000/api/v1/m1/seats/availability?start_at=2026-11-03T10:00&hours=2"
```

种子数据是 3 间合成教室（`LIB-101`、`A-201`、计算机学院专属的 `CS-305`），每间 12 个座位，01–04 号靠固定插座，05–06 号靠导轨插座。

## 2. 代码地图

| 路径 | 作用 |
| --- | --- |
| `backend/app/main.py`、`config.py`、`db.py` | 应用工厂、环境变量配置、数据库会话（**临时，D 评审**） |
| `backend/app/common/resources/models.py` | `rooms`、`seats` 表（**占位，B 接管**） |
| `backend/app/modules/m1_reservation/router.py` | 全部 M1 路由；只做参数解析和鉴权 |
| `.../timeslots.py`、`availability.py` | 时段规则；“座位为什么不可用”的唯一判定（搜索和预约共用） |
| `.../reservations.py`、`checkin.py` | 预约/取消、签到；加锁与并发保护在这里 |
| `.../restrictions.py` | M2/M3 写回 |
| `.../jobs.py` | 提醒与违约任务（独立进程运行） |
| `.../ops.py`、`settings.py` | 运营汇总、追溯、系统参数 |
| `.../identity.py` | `CurrentUser` 与权限检查；**C 的认证从这里接入** |
| `.../models.py`、`backend/alembic/versions/0002–0005` | M1 的表与迁移 |
| `backend/tests/m1/` | M1 测试 |

## 3. 我动了你们负责的地方

为了让 M1 能运行和测试，我先写了下面这些。它们都标了“临时/占位”，**不代表替你们做了决定**，请评审，可以改，也可以整体替换。

| 负责人 | 我写的内容 | 请你做的 |
| --- | --- | --- |
| D | `backend/` 下的依赖锁定、应用工厂、配置加载、Alembic 环境、pytest 夹具、`scripts/seed.py` | 评审或替换为统一脚手架。替换时请保留：`create_app(config)` 工厂、`app.state.sessionmaker` / `clock`、迁移链 |
| B | `rooms`/`seats` 模型和迁移 `0001`、种子数据 `database/seeds/0001_dev_resources.sql` | 接管这两张表。字段按你的 b01 草案取名；如果要改名或改结构，请先告诉我，因为 M1 会读取它们（见 §4.1） |

C、E 的目录我没有改动。

## 4. 按角色

### 4.1 B（M1 前端、教室与座位主数据）

**页面与接口对照**

| 你的需求 | 调用 |
| --- | --- |
| B-UI-01 座位搜索 | `GET /api/v1/m1/seats/availability?start_at=&hours=&room_id=&outlet_type=&has_outlet=&only_available=` |
| B-UI-02 预约 | `POST /api/v1/m1/reservations`，体为 `{seat_id, start_at, hours}`。**打开确认框时生成一个 UUID 作为 `Idempotency-Key`，重试时沿用**：超时后重发不会产生第二笔预约（重放返回 200） |
| B-UI-03 签到 | `POST /api/v1/m1/reservations/{id}/check-in`，体为 `{code}` |
| B-UI-03 签到码展示子页 | `GET /api/v1/m1/rooms/{room_id}/checkin-code`（需要 `m1:checkin_code:view`）；二维码直接编码返回的 6 位数字即可，`valid_until` 之后刷新 |
| B-UI-04 历史与再次预约 | `GET /api/v1/m1/reservations/me`；再次预约时用历史中的 `seat_id` 重新搜索并提交，后端会重新校验 |
| B-UI-06 运营查看 | `GET /api/v1/m1/ops/usage?date=` |
| 时间选择器的上限 | `GET /api/v1/m1/settings` 的 `max_hours`、`booking_horizon_days`，不要在前端写死 4 |
| 我的违约 | `GET /api/v1/m1/violations/me` |

**显示约定**

- 不可用原因看 `reasons[].code`：`room_disabled`、`seat_disabled`、`department_restricted`、`outside_opening_hours`、`reserved`、`m2_approval`（整间已被审批占用）、`m3_repair`（维修中）。一个座位可能同时有多个原因。
- 错误响应的 `error.message` 是可以直接显示的中文；需要按情况做特殊交互时看 `error.code`。
- 时间：发送时可以不带时区（按北京时间解释）；返回值一律带 `+08:00`。放进 URL 查询串时，`+` 要写成 `%2B`。

**主数据接管时要保持的字段**：M1 读取 `rooms.id/code/name/access_scope/department_id/open_time/close_time/enabled` 和 `seats.id/room_id/code/outlet_type/enabled`。M1 自己的表对 `rooms.id`、`seats.id` 有外键。

### 4.2 C（认证、RBAC、审计，以及 M2）

**认证接入**：M1 只依赖 `identity.py` 里的这个数据结构：

```python
CurrentUser(id: str, department_id: str | None, permissions: frozenset[str])
```

你提供一个“从请求得到 `CurrentUser`、失败抛 401”的函数后，我把 `identity.get_current_user` 改为调用它，M1 业务代码不用动。在此之前，部署环境只能用 `AUTH_MODE=disabled`，即所有受保护接口都返回 401。

**需要在 RBAC 中登记的权限**：`m1:reservation:use`、`m1:checkin_code:view`、`m1:ops:view`、`m1:settings:manage`、`m1:restriction:m2_approval`、`m1:restriction:m3_repair`。哪些角色拥有它们由你和团队决定。

**M2 写回**（完整说明见[契约第 4 节](architecture/a-m1-api-v1.md#4-m2m3-写回契约跨模块)）：

```
审批通过       → PUT  /api/v1/m1/restrictions/m2_approval/{审批单号}   {room_id, start_at, end_at}
驳回/撤销/超时 → POST /api/v1/m1/restrictions/m2_approval/{审批单号}/release  {reason}
超时后不确定   → GET  /api/v1/m1/restrictions/m2_approval/{审批单号}，确认结果后再重试
```

- PUT 和 release 都可以安全重试。
- PUT 的响应 `affected_reservation_ids` 是被这次占用覆盖的个人预约。M1 不会自动取消它们；怎么处理是 D-07 的待决问题，需要你参与决定。
- M2 用服务账号调用，账号只能持有 `m1:restriction:m2_approval`；它无法操作 M3 的限制。

**审计**：M1 已把每次座位状态变化写入 `m1_seat_state_events`（来源、来源 ID、动作、操作者、时间）。是否再写入你的公共审计、用什么格式，请给出契约。

### 4.3 D（工程、部署、流水线）

- **测试需要真实 PostgreSQL**（用到排他约束和 advisory lock）。在 CI 中启动 `postgres:16` 服务，设置 `TEST_DATABASE_URL`，然后执行 `cd backend && python -m pytest -q`。测试账号需要 `CREATEDB` 权限，因为每次运行都会新建一个测试库。
- **迁移**：`alembic upgrade head`。`btree_gist` 扩展由迁移 `0002` 创建；它是受信任扩展，数据库 owner 即可创建。迁移是单链，目前的 head 是 `0005_m1_seat_restrictions`。其他模块新增迁移时 `down_revision` 要接在当前 head 上，建议在 CI 里检查 `alembic heads` 只有一个。
- **进程**：除 API 进程外，还要一个常驻任务进程 `python -m app.modules.m1_reservation.jobs --loop 60`。按设计可以多实例并行（`SKIP LOCKED` 加唯一约束），但**尚未做过多实例并发测试**，建议先只部署一个。
- **配置**：
  - `DATABASE_URL`。
  - `BUSINESS_TIMEZONE`，默认 `Asia/Shanghai`。
  - `M1_CHECKIN_CODE_SECRET`：放进密钥管理；为空时签到返回 503。
  - `AUTH_MODE`：测试和生产环境必须是 `disabled`，直到 C 的认证接入。
- **种子**：`python scripts/seed.py` 可以重复执行，只写合成教室和座位。
- **服务拆分**：期末要演示真实的跨模块网络调用。M1 的写回接口本身就是 HTTP，拆成独立服务不需要改代码；拆分方案请在 ADR 中决定。

### 4.4 E（通知，以及 M3）

**通知**：M1 把要发的通知写进自己的 `m1_notification_outbox` 表：`kind`、`user_id`、`payload`（预约 ID、教室、座位、时间）、`dispatched_at`。四种 `kind` 见[契约第 5 节](architecture/a-m1-api-v1.md#5-给-e-的通知出口暂定)。每个预约的每种通知最多一条。请和我确定读取方式：由 M1 提供“拉取未发送通知 + 标记已发送”的接口，还是由 M1 调用你的发送接口。确定之前，这张表只写不发。

**M3 写回**：

```
工单进入“维修中” → PUT  /api/v1/m1/restrictions/m3_repair/{工单号}   {room_id, start_at}   （不传 end_at 表示直到解除）
验收通过         → POST /api/v1/m1/restrictions/m3_repair/{工单号}/release  {"reason": "accepted"}
```

- 只有**验收通过**才解除；“维修完成”或“工单取消”不能解除，非 `accepted` 原因会被 M1 拒绝。M3 负责核实验收事实。
- 按负责人 2026-10-28 确认的整室下架策略，即使只坏一个座位，也下架该教室全部座位。不要传 `seat_id` 或 `end_at`，否则返回 422；维修限制不会按时间自动解除。
- 同一教室的多张工单互不影响，只有全部解除后座位才会恢复。
- 维修期间学生没来签到，M1 暂定**不记违约**（D-08），请参与确认。

### 4.5 F（集成与验收）

- **跨模块演示**：[验证记录第 3 节](testing/a-m1-v1-verification.md#3-真实-http-冒烟)的 curl 序列就是一条可演示的 M3 → M1 链路，M2 → M1 同理。要做到真实网络调用，需要 M2/M3 作为独立服务调用 M1。
- **验收追踪**：[需求基线第 2 节](requirements/a-m1-v1-baseline.md#2-需求追踪)按 需求 → 实现 → 测试 列出了 17 条，可以直接接到 Issue。
- **风险与伦理**：以下事项建议记入 `docs/risks.md`：
  - 囤座：D-03 禁止一人同时持有多个座位。
  - 错误违约：D-08 维修期间不记违约；违约申诉与更正尚未实现。
  - 管理员看到的数据范围：D-12 只给汇总。
  - 开发用身份误用于部署环境：`AUTH_MODE`。
  - 签到码被暴力尝试：尚未限流。
- **需要开会决定**：D-02、D-03、D-05、D-07、D-08 涉及公平和处罚，按 AGENTS.md 第 4.3 节须团队确认。

## 5. 在此基础上继续开发

### 5.1 开始之前

```bash
git switch main && git pull --ff-only
git switch -c feat/<模块>-<主题>          # 例如 feat/m2-approval-flow
cd backend && python -m pytest -q          # 先确认基线是 85 passed，再开始改
```

测试需要 `TEST_DATABASE_URL`，做法见 §1 和 `backend/README.md`。基线测试不通过时，先查环境，不要在失败的基线上继续开发。

### 5.2 新模块按 M1 的结构接入

M2（C）、M3（E）可以照 `app/modules/m1_reservation/` 的分层来组织：

| 文件 | 内容 |
| --- | --- |
| `router.py` | `APIRouter(prefix="/api/v1/m2")`，再提供 `register(app)`：在其中 `include_router`，并注册本模块的错误处理 |
| `schemas.py` | 请求和响应模型 |
| `models.py` | 本模块的表，表名加模块前缀（`m2_`、`m3_`），继承 `app.db.Base` |
| 业务文件 | 一个用例一个函数，接收 `session`、`CurrentUser`、`now`，并在函数内自己提交事务 |

接入应用时在 `app/main.py` 加一行 `m2_router.register(app)`。这个文件属于 D，请在 PR 里说明。

建议直接沿用 M1 已经用上的约定，这样前端只需处理一种格式：

- 错误体统一为 `{"error": {"code", "message", "details"?}}`。
- 时间一律通过可注入的时钟（`app.state.clock`）获取，测试才能控制“现在”。
- 身份只依赖 `CurrentUser`。

这三样目前都写在 M1 内部（`errors.py`、`clock.py`、`identity.py`），**请不要直接 import M1 的内部模块**。可以先按同样的格式各自实现；更好的做法是由 D 把它们提升到 `app/common/` 供大家共用，我会配合修改 M1。

### 5.3 写迁移

1. 复制一个现有迁移，例如 `backend/alembic/versions/0005_m1_seat_restrictions.py`，作为模板。
2. `revision` 按 `NNNN_<模块>_<主题>` 命名，例如 `0006_m2_approvals`；`down_revision` 填当前的 head（用 `alembic heads` 查看）。两个人同时新增迁移时会出现两个 head，合并前要先协调好先后顺序。
3. 一定要写 `downgrade()`。
4. 在 `alembic/env.py` 和 `tests/test_migrations.py` 中 import 你的 `models`，否则 drift 测试检查不到你的表。
5. 运行 `python -m pytest -q tests/test_migrations.py`。它会检查 ORM 模型与迁移是否一致，并验证从空库升级、完整降级、再升级都能成功。

不要修改已经合并的迁移文件。需要改结构时，新增一个迁移。

### 5.4 写测试

- 直接复用 `tests/conftest.py` 中的夹具：`database_url`、`engine`、`clean_db`、`app`、`client`。每个测试开始前，`app` 会清空所有业务表。
- 把测试放在 `tests/m2/`、`tests/m3/` 下，身份用 §1 中的请求头。
- 需要控制时间时，参考 `tests/m1/conftest.py` 中的 `FixedClock` 和 `clock` 夹具。
- 断言要检查可观察的结果：响应内容和数据库状态。提交前做一次“故意改坏实现 → 确认测试失败 → 恢复”，做法参考[验证记录第 4 节](testing/a-m1-v1-verification.md#4-故意破坏实现确认测试会失败)。

### 5.5 从 M2/M3 调用 M1

- **必须走 HTTP**，例如 `httpx.put(f"{M1_BASE_URL}/api/v1/m1/restrictions/m2_approval/{id}", ...)`。不要 import M1 的函数，也不要读写 `m1_*` 表：期末要演示真实的跨模块网络调用。`httpx` 目前只是测试依赖，要作为运行依赖加入时请和 D 确认。
- 设置超时。超时后先 `GET` 同一个来源确认结果，再决定是否重试；重试时使用同一个 `source_id`，M1 会按幂等处理。
- M2/M3 的单元测试可以用测试替身代替对 M1 的 HTTP 调用，因为 M1 对你们来说是外部依赖；但集成测试和演示必须在独立运行的服务之间真实调用。

### 5.6 需要改 M1 时

- M1 的代码、测试和迁移归 A 负责。需要新接口或修改现有行为时，先提 Issue，或者提一个只修改[接口契约](architecture/a-m1-api-v1.md)的 PR 并 @A，我来修改实现和测试。
- 发现 M1 的 bug 时，最好附一个能复现问题的失败测试。

## 6. 所有人都要遵守

1. 不要读写任何 `m1_*` 表，只通过接口访问 M1。M1 也只读 `rooms`/`seats`，不写。
2. 不要在部署环境开启 `AUTH_MODE=dev-headers`。
3. 不要在测试数据里使用真实学生信息。种子和测试里全是合成数据。
4. 需要改 M1 的接口时，请提 PR 修改[接口契约](architecture/a-m1-api-v1.md)，并 @A 评审；我会同步修改代码和测试。

## 7. 已知限制

完整列表见[需求基线第 4 节](requirements/a-m1-v1-baseline.md#4-尚未实现明确记录不从清单中消失)。对你们影响最大的几项：

- 认证尚未接入，所以部署环境里 M1 目前不能真正使用。
- 通知只入库、不发送。
- 搜索没有分页。
- 教室或座位停用后，已有预约的处理规则（B-OPEN-02）尚未决定。
