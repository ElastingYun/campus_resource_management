# 成员 C 后端：运行与接入说明

当前交付包含 C 的代码、版本化 SQL、测试和文档，不包含任务划分、GitHub 操作或生产部署。
生产审批政策与对外网络契约仍需团队确认；代码要求显式配置，演示规则和测试夹具不构成需求基线。

## 1. 实现范围

| 位置 | 已实现能力 |
| --- | --- |
| `backend/app/common/auth/` | Argon2 密码散列、仅存摘要的随机 Bearer 会话、退出/过期/账号停用、实时角色权限与资源范围、登录限流、幂等账号引导、受策略约束的角色分配 |
| `backend/app/common/audit/` | 同事务成功审计、独立事务拒绝审计、按资源范围查询；仅接收白名单元数据 |
| `backend/app/modules/m2_approval/service.py` | 申请与授权查询、服务端流程快照、顺序多级审批、驳回、截止扫描、按配置开放撤销、业务事件与幂等结果 |
| `backend/app/modules/m2_approval/api.py` | 可挂载路由与应用工厂、严格输入校验、公开响应模型、统一安全错误与请求关联标识 |
| `backend/app/modules/m2_approval/clients.py` | 主数据 HTTP 读取、M1 占用/释放/查询客户端；路径、凭据和超时由接入方显式提供 |
| `backend/app/modules/m2_approval/worker.py` | PostgreSQL 持久操作、并发领取、重启恢复、租约令牌隔离、未知结果查询、有限重试与人工待处理状态 |
| `backend/app/modules/m2_approval/demo.py` | 显式开启的合成本地演示、健康检查、后台截止扫描；不伪造 M1 成功 |

未实现：真实学校统一登录、前端页面、A 的 M1 服务、E 的通知发送、跨实例审计接收与投递、统一部署/CI、生产数据迁移接入。
`c_business_events` 只保存本模块业务事件，目前没有发送通知或远端审计的守护进程。

## 2. 安装与测试

从仓库根目录执行。Python 3.11，测试使用真正的 PostgreSQL，不用 SQLite 替代事务和并发验证。

```bash
python3 -m venv /tmp/c-member-env
/tmp/c-member-env/bin/python -m pip install -r backend/tests/c_module/requirements.txt
/tmp/c-member-env/bin/python -m pytest backend/tests/c_module -q
/tmp/c-member-env/bin/ruff check --isolated --select E4,E7,E9,F,I,B backend/app/common/auth backend/app/common/audit backend/app/modules/m2_approval backend/tests/c_module
/tmp/c-member-env/bin/ruff format --check backend/app/common/auth backend/app/common/audit backend/app/modules/m2_approval backend/tests/c_module
```

不安装测试依赖时，运行依赖单独位于 `backend/app/modules/m2_approval/requirements.txt`；当前直接依赖固定版本，不声称已锁定全部传递依赖。
这些文件只服务于 C 组件，不替换项目将来统一的依赖清单。FastAPI 是已确定框架；psycopg 提供 PostgreSQL 事务，HTTPX 提供网络客户端，Argon2 库处理密码；Uvicorn 用于启动本地演示。

测试默认由 `pgserver` 启动临时数据库、每例创建独立随机 schema，结束后只清理该 schema 和临时实例。
也可通过 `C_TEST_DATABASE_URL` 指向**专用测试库**；该用户需要创建 schema 的权限，测试不会清空其他 schema。
缺少两种 PostgreSQL 来源时明确跳过数据库用例，不能把跳过算成通过。`pgserver` 只属于测试依赖；平台没有可用 wheel 时改用专用测试库并安装其余测试依赖。

## 3. 本地合成演示

使用单独的演示 PostgreSQL 库，运行依赖安装后设置以下环境变量，再从仓库根目录启动：

```bash
export C_DEMO_MODE=1
# 由本地环境提供以下变量，不写入或提交真实值：
# C_DEMO_DATABASE_URL：专用演示 PostgreSQL 连接串
# C_DEMO_PASSWORD：至少 12 字符的演示密码
PYTHONPATH=backend /tmp/c-member-env/bin/python -m app.modules.m2_approval.demo
```

服务只监听 `127.0.0.1:8082`；访问 `/health` 与 `/docs`。没有显式模式、数据库或合格密码时拒绝启动。
启动会显式执行 C 的迁移和幂等合成账号初始化；不会启动时偷偷创建真实学校账号。

合成账号为 `demo-student`、`demo-reviewer-1`、`demo-reviewer-2`，密码均来自环境；合成教室 `demo-room`、院系 `demo-department`。
演示流程为两级，每级一分钟，禁止自审、要求驳回理由、允许拥有撤销权限的对应范围人员撤销。
这些数值和角色**仅用于演示**，不代表团队已确定真实政策。账号管理策略默认未配置，演示账号也未获 `auth.manage`。

后台每秒扫描到期的待审批申请，关闭浏览器不影响扫描。健康检查同时检查数据库和扫描任务；扫描数据库故障有结构化错误，恢复后继续处理持久截止时间。
最终审批后保持 `PASSED / APPLY_PENDING`，因为演示不连接 M1；`effective=false`，不会展示成资源已占用。
重启不覆盖已有账号的权限或密码；配置冲突会失败，避免用初始化脚本悄悄改权限。

## 4. 挂载到统一 FastAPI 工程

已有工程可调用 `api.install(app, auth=..., approval=..., audit=...)`；独立验证可用 `api.create_app(...)`。
安装操作会注册路由、请求关联与错误处理，需由宿主明确调用一次；不会在导入时创建连接、迁移、后台任务或账号。
宿主已有 middleware/错误处理器时先协调接入，不能重复注册来覆盖其他模块的处理逻辑。

构造依赖的实际入口：

1. `Database(dsn)`、`AuditService(database)`。
2. `AuthService(database, audit, AuthSettings(session_ttl, attempt_window, max_attempts), access_policy=...)`。
3. `ApprovalService(database, audit, resources, workflow_for, validate_submission)`。
4. 可选构造 `HttpM1Gateway(...)` 和 `OperationWorker(database, audit, gateway, RetrySettings(...))`。

`AuthSettings` 的尝试窗口限制账号和客户端地址两个桶内的**全部登录尝试**，不是只计错误密码；数值必须显式给出。
反向代理后的可信客户端地址解析由统一工程处理，不能直接信任浏览器提供的转发头；否则共享代理地址会共用客户端限流桶。
会话为绝对期限，无空闲续期或刷新令牌。角色/范围在下一请求读取当前值，不能保证并发请求中已开始的操作立即中止。

`workflow_for(principal, room)` 返回 `Workflow`，明确提供：版本、非空 `Step(permission, timeout)` 序列、自审许可、截止等号归属、驳回理由要求和撤销许可。
`validate_submission(principal, room, starts_at, ends_at, now)` 是可信服务端资格/时段校验回调：通过时返回，拒绝时抛 `ServiceError`。必须实现真实业务规则，不能直接复用演示的通过条件。
资源适配器返回 `Room`；服务端验证引用和静态启用，但不会把它当作最终动态可预约性。M1 在最终写入点检查个人预约、维修和其他占用竞争。

账号授权接口同时需要 `auth.manage` 和显式 `access_policy(actor, target, desired)` 返回 `True`；未配置就拒绝。
策略必须校验目标账号原范围和请求的新范围、院系及全局范围授权；只能分配已存在角色，不能授予操作者自身没有的操作权限。
修改账号权限有同事务审计；停用会撤销已有会话，重新启用不会复活旧会话。角色定义及初始账号只允许受信引导入口操作，没有普通用户自助提权入口。

`Database.transaction()` 使用 psycopg 连接上下文保证成功提交、异常回滚并关闭连接；网络操作在数据库事务外执行。[事务行为参考](https://www.psycopg.org/psycopg3/docs/basic/transactions.html)
当前采用直接驱动与 C 自有 SQL，避免未经确认创建全局 ORM 基类或统一 Alembic 工程；以后接入统一工程时保留事务与迁移语义。

## 5. 当前公开 API

| 方法与路径 | 说明 |
| --- | --- |
| `POST /api/v1/auth/sessions` | 用户名/密码登录，返回随机 Bearer 会话与过期时刻 |
| `DELETE /api/v1/auth/sessions/current` | 撤销当前会话；已无有效身份的重复调用返回 401 |
| `GET /api/v1/auth/me` | 当前用户、角色、权限、显式教室范围 |
| `PUT /api/v1/auth/users/{id}/access` | 有策略约束的角色/范围/启停管理 |
| `POST /api/v1/m2/applications` | 提交本人申请 |
| `GET /api/v1/m2/applications` | 本人、当前审批待办或获授权管理范围内的列表 |
| `GET /api/v1/m2/applications/{id}` | 授权详情；对不可见对象统一返回 404 |
| `GET /api/v1/m2/review-tasks` | 当前节点、权限和资源范围内的审批待办 |
| `GET /api/v1/m2/applications/{id}/history` | 获授权的逐节点决定历史，不是全量审计查询 |
| `POST /api/v1/m2/applications/{id}/decisions` | `APPROVE` / `REJECT`、意见和预期版本 |
| `POST /api/v1/m2/applications/{id}/revocations` | 仅持有权限且流程允许时撤销，使用预期版本 |
| `GET /api/v1/audit/events` | 需 `audit.read`；非全局范围只能查询明确教室内的审计 |

所有申请写接口要求 `Idempotency-Key`，字符集 `[A-Za-z0-9_.:-]`，长度 1～128；键按操作者、动作及目标隔离。
同键不同规范化内容返回 409。同键重放返回首次结果，当前申请进度请 GET 查询；重放也不能绕过当前操作许可和资源范围。
审批/撤销提交 `expected_version` 正整数，旧版本返回 409；工作进程确认结果也可能更新版本，操作前应刷新。
列表分页 `limit=1..100`、非负 `offset`；未授权或不可见对象不会通过列表泄露。
时间必须带时区，内部转为 UTC；无效起止、未知字段或伪造身份字段被拒绝。服务端不把 M1 的四小时上限套给 M2。

错误返回 `error.code`、安全消息或字段位置，以及服务端生成的 `request_id`；校验错误不回显输入的密码或请求体。
401 带 Bearer 认证提示；响应不缓存。拒绝审计不可用时返回 503，不伪报记录成功；数据库错误不公开 SQL 或连接信息。
本地成功业务审计写入失败则业务回滚。这是当前组件明确选择的事务行为；远程审计失败策略尚未实现。

## 6. 截止扫描、M1 操作与恢复

宿主周期性调用 `approval.expire_due(limit=...)`；除合成演示外，组件不自行选择生产调度进程。
扫描只关闭未撤销且处于 `REVIEWING` 的申请；不把 HTTP 超时、已生效申请或时段结束混成同一个撤销条件。
当前方案在最后一级通过后才生成占用意图，因此待审批驳回/超时无需伪造释放操作。

宿主配置工作进程周期性调用 `worker.run_once()`，True 表示处理/标记了一条操作，False 表示当前没有到期可领取操作。
领取使用 PostgreSQL `FOR UPDATE SKIP LOCKED`，用于并发工作队列；租约令牌防止已被重新领取的旧工作进程覆盖结果。[锁与 SKIP LOCKED 参考](https://www.postgresql.org/docs/current/sql-select.html)
租约应大于网络请求上限并留余量。程序异常退出后，操作保留至租约到期；未知结果先查原操作，必要时用相同标识与内容重发。

超过 `RetrySettings.max_attempts` 后进入 `ATTENTION`，保留未知业务状态和 `RETRY_LIMIT`，不当作已取消或成功；该上限计算领取/恢复尝试，包括结果查询。
当前没有自动告警或重新入队管理接口。运维需先查询远端真实结果并按确认流程处理；不能生成新操作标识直接盲重试。
本地幂等记录和操作记录尚无自动清理任务，不能随意删除后继续接受历史键重试。

### 6.1 M1 适配器协议

`HttpM1Gateway` 的 `apply_path`、`release_path`、含 `{operation_id}` 的 `query_path`、服务凭据和超时是必填配置，没有假定 A 已实现某个路径。
写请求使用 `operation_id`、`source=M2`、`source_id`、教室、起止、`generation` 和 `kind=APPLY/RELEASE`，同时发送相同的幂等头。
响应必须回传相同操作标识和明确的 `APPLIED`、`RELEASED`、`CONFLICT`、`PENDING` 或 `NOT_FOUND`。
200/201 才可承载完成确认；202 只接受处理中或未找到；409 只接受明确冲突。查询的未找到使用有结构的结果，裸 404 仍视为无法确认。
HTTP 断连、重定向、错误码、损坏 JSON、错配标识与未知枚举均不能当成成功。

M1 必须持久去重、拒绝同键不同内容，并按来源和版本保护终态，防止“释放先到、旧创建后到”复活占用。
M2 自身只保护本地状态不被旧版本覆盖，**不能代替 M1 实现远端终态保护**。该能力未获 A 的真实服务验证。
释放只针对本申请来源，剩余个人预约、审批或维修原因由 M1 继续判断；`RELEASED` 不等于全室可预约。

## 7. 迁移、配置与验证边界

`migrate(Database(...))` 显式应用 `migrations/001_c_foundation.sql`，只建立 `c_` 前缀的 C 自有表与迁移账本；不引用其他模块私有表。
迁移有全事务、并发锁和校验和；已应用文件变化时拒绝执行，后续结构变更应新增版本。
统一迁移工具尚未建立，因此这里没有伪造 Alembic revision。未来纳入统一迁移时先核对账本与存量 schema，避免重复建表；不改已应用 SQL 来掩盖差异。
角色和账号引导是可信维护入口，重复相同配置不重复创建，冲突不覆盖；生产调用须另有已批准的配置和运维授权。

测试结果、实际命令和故意破坏验证见[验收记录](../testing/c01-acceptance-plan.md#6-证据记录与当前结果)。
独立进程 HTTP 用例使用测试自建契约服务，只验证真实套接字、客户端及本地状态流转；不代表 A/E 的真实跨模块链路已验收。
API/代码由 AI 辅助实现，业务政策、公开契约和最终运行环境仍由项目成员检查验收；本轮没有虚构人工 Review、CI 或部署成功。
