# 成员 C 后端：统一工程接入与运行

C 负责 M2 审批、公共认证/RBAC 和本地操作审计。当前实现已接入 D 的 Python 3.13、统一依赖锁、连接池、Alembic、应用生命周期与前端 API 代理。
任务见 [#14](https://github.com/ElastingYun/campus_resource_management/issues/14)，前端接口对齐见 [#10](https://github.com/ElastingYun/campus_resource_management/issues/10)。
生产审批政策与 A/B/E 网络契约仍须相关 owner 确认；合成配置不构成生产需求基线。

## 1. 已实现范围

| 位置 | 能力 |
| --- | --- |
| `backend/app/common/auth/` | Argon2、随机 Bearer 会话摘要、退出/过期/停用、实时权限和资源范围、登录限流、幂等账号引导、受策略约束的授权管理 |
| `backend/app/common/auth/bootstrap.py` | 独立、显式的受信账号初始化；密码通过交互或环境读取 |
| `backend/app/common/audit/` | 成功审计同事务，拒绝审计独立事务；受权范围查询及字段白名单 |
| `backend/app/modules/m2_approval/service.py` | 申请、流程快照、顺序多级决定、历史、超时、可配置撤销、服务端动作/集成进度查询、幂等与业务事件 |
| `backend/app/modules/m2_approval/api.py` | 严格输入、公开响应模型、Bearer 与错误 OpenAPI、请求关联标识 |
| `backend/app/modules/m2_approval/runtime.py` | 复用宿主连接池、显式策略、后台扫描/M1 处理、启停恢复和组件就绪检查 |
| `backend/app/modules/m2_approval/clients.py` | 资源读取及 M1 占用/释放/结果查询 HTTP 适配器，服务路径与凭据显式配置 |
| `backend/app/modules/m2_approval/worker.py` | 持久工作、并发领取、租约隔离、未知结果确认、有限重试和 ATTENTION |
| `backend/alembic/versions/0002_c_identity_approval.py` | C 自有 schema 及旧 C 基线的无损接入 |

未完成：真实学校统一登录、真实前端业务联调、A/B/E 服务联调、远程审计接收与投递、通知发送、生产部署。
业务事件已保存，通知投递尚无已批准的接收契约。重试耗尽后保留 ATTENTION，可通过[C-37只读进度接口](c37-integration-progress.md)查看；目前没有告警或人工重新入队 API。
占用成功/冲突/释放确认现也有同事务业务事件，重试与旧代次返回不重复记录；见[C-58](c58-integration-result-events.md)。它们仍是本地事实，E实际通知投递待#25对接。

## 2. 依赖、迁移与测试

在 `backend/` 使用统一 Python 3.13 和锁文件：

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m pytest -m 'not integration'
```

C 目录下原 requirements 文件现在只引用统一清单；运行依赖包括 Argon2 和 HTTPX，直接与传递版本均由根锁文件固定。
C 的数据库用例自动归入 integration，使用真正 PostgreSQL。CI 使用已配置的 PostgreSQL 17；本地可配置专用测试数据库：

```bash
# 先在本地环境配置 CAMPUS_DB_*，目标必须是隔离开发/测试库。
.venv/bin/alembic upgrade head
.venv/bin/alembic upgrade head
CAMPUS_TEST_POSTGRES=1 .venv/bin/python -m pytest -m integration
```

也支持 `C_TEST_DATABASE_URL`。每例创建自己的随机 schema，只清理该 schema。CPython 3.13 不依赖没有兼容 wheel 的 pgserver；缺少真实数据库时明确跳过，不计为通过。
本轮实际环境和命令记录见[工程接入验证](../testing/c14-engineering-integration.md)。

## 3. 显式开启与策略配置

统一入口默认为 bootstrap 模式。已有 `/health/live` 和 `/health/ready` 行为保持；C 业务通过环境配置开启：

```text
CAMPUS_C_ENABLED=true
CAMPUS_C_CONFIG_FILE=<已审查的 C 配置文件路径>
CAMPUS_RESOURCES_SERVICE_TOKEN=<仅保存在后端环境或本地 .env>
CAMPUS_M1_SERVICE_TOKEN=<配置 M1 时提供>
```

资源/M1 的标准 SecretStr 字段支持环境变量和根 `.env`；自定义 token_env 名称需显式导出到进程环境。日志和配置 repr 不显示实际凭据。
配置文件的结构示例位于 `backend/app/modules/m2_approval/examples/runtime.synthetic.json`，名称和内容明确为合成示例，须按批准政策和实际服务修改。
所有审批层级/期限、自审、驳回理由、撤销许可、院系准入、提前量、时长和时间粒度显式给出。布尔字符串、URL 内嵌凭据、跨主机路径和不合法租约均拒绝。
2026-10-29 已批准的校园级/本院系准入通过 `submission.room_access_policy="campus_or_own_department"` 显式启用，且 `allow_cross_department=false`。配置示例、B v2 元数据和兼容边界见 [C-40 说明](c40-approved-room-policy.md)。旧合成示例保留 legacy 行为，不代表满足新规则。
`m1=null` 允许先对接身份与审批；最终审批后保持占用待确认。只有 M1 确认后 effective 才为 true。
`access_management=null` 关闭账号授权管理；启用后还须 auth.manage、原/新范围校验及非越权委派。

配置后启动：

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

开启 C 时，readiness 额外检查 C 表、基线校验和与后台任务；失败返回 503，liveness 仍表示 HTTP 进程存活。就绪只证明 C 本地运行条件，不代替外部服务联调。
连接池由宿主 lifespan 创建和释放。C 每个事务独立借出连接，异常回滚，并在归还前恢复 row factory；HTTP 请求在事务外执行。
后台扫描与 M1 领取在停止时等待当前工作结束，再关闭客户端和连接池；进程崩溃后凭持久状态与租约恢复。

## 4. 显式账号初始化

应用启动不会自动建账号或迁移。执行统一迁移后，由可信操作人员调用：

```bash
.venv/bin/python -m app.common.auth.bootstrap \
  --username synthetic-student --department-id synthetic-department \
  --roles-file app/modules/m2_approval/examples/roles.synthetic.json \
  --role synthetic-student --room room-demo-01
```

默认交互输入并确认 12～1024 字符密码，输出仅用户 UUID；自动化可通过 `--password-env CAMPUS_BOOTSTRAP_PASSWORD` 读取环境，不能把密码作为参数值。
角色文件仅定义能力，`--role` 显式选择授予的角色；`--all-rooms` 必须显式指定。示例角色只用于合成演示，不代表真实成员或学生授权。
重复相同账号配置返回同一 UUID；密码、角色定义或原配置冲突会失败，不覆盖现有权限。角色与账号创建有同事务审计。

## 5. API 与前端接入

完整的字段、权限、状态、错误及合成示例见 [C-v1 前端契约](c-v1-frontend-contract.md) 和 [OpenAPI](c-v1-openapi.json)。
业务统一前缀 `/api/v1`；Vite 与 Nginx 的 `/api` 代理转发到后端。登录后使用 Bearer 会话，前端通过 actions 查询当前允许的决定/撤销动作，写入仍重新授权与校验版本。
认证主体的启用、院系、资源范围与角色权限使用同一SQL语句快照，防止并发授权变更拼接旧范围/新权限；[C-56真实并发验证](../testing/c56-principal-snapshot.md)记录复现、修复与负对照。整合旧C分支时须纳入该修复，不能只凭旧CI成功判断身份一致性已覆盖。
列表为带 limit/offset 的数组；详情有 step_index、step_count、审批与集成两类状态及 effective。输入错误不回显凭据或完整请求体。
C 所有申请写入都要求 Idempotency-Key；同键同内容返回首次结果，最新状态通过 GET 查询。同键不同内容、旧版本或非法状态返回 409。
主数据静态启用由 B 提供；最终动态占用由 M1 原子判断。C 不直接访问其他模块私有表。
普通申请目录使用 B #48 的独立 room-options，C按当前Bearer、m2.submit和可信院系显式注入，默认关闭；安装、分页和错误约定见[C-54](c54-room-options-identity.md)。管理读取和普通选择权限独立，D须在宿主完成安装及浏览器接入。

## 6. M1 恢复与运行边界

M1 的 base_url、apply_path、release_path、query_path、token_env、I/O 超时、租约、重试延迟和次数显式配置；查询路径带 operation_id。
操作携带 source=M2、source_id、room_id、起止时间、generation、kind 和稳定 operation_id。响应须回传相同操作标识和 APPLIED/RELEASED/CONFLICT/PENDING/NOT_FOUND。
损坏响应、重定向、错误标识和网络中断保留未知结果。查询或重发使用同一操作与内容，不生成新标识猜测执行结果。
M1 需要持久幂等与版本/终态保护；本地 generation/租约隔离不能代替远端防止“释放先到、旧创建后到”复活占用。
释放只撤销该申请来源；M1 仍须考虑其他个人预约、审批或维修。重试耗尽进入 ATTENTION，保持业务事实并等待受控处理。
已批准的个人预约冲突规则是 M1 原子拒绝整室占用、保留个人预约；C 保留 PASSED 审批事实，以 APPLY_CONFLICT 和 effective=false 表示未生效。A 的原子拒绝实现与真实网络验收仍在 #23，不能先写 active 来源再补偿释放。
本地幂等及操作记录尚无自动清理任务，不能删掉历史键后继续接受重放。

## 7. 迁移与合成演示

统一 Alembic 链为 0001_bootstrap → 0002_c_identity_approval。0002 只执行冻结的 001_c_foundation.sql；已存在 C 基线时校验账本、校验和与表，保留账号及业务数据。
SQL 历史没有改写。后续结构必须新增 Alembic revision；破坏性 downgrade 当前拒绝执行，恢复计划需单独批准。
独立 `migrate()` 保留给旧合成演示兼容，不用于宿主应用启动。

旧的 `python -m app.modules.m2_approval.demo` 仍可在显式 C_DEMO_MODE、专用演示数据库和演示密码下运行。它有合成教室与两级一分钟流程，不连接 M1。
推荐统一工程验证使用本文件的 opt-in 配置、迁移和账号命令。生产拓扑、学校统一登录与真实 A/B/E 联调另行验收。
