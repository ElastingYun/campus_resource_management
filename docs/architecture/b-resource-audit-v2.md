# B 资源审计端口 v2：元数据及可信上下文

负责人 B / hrzhao7；[子任务 #27](https://github.com/ElastingYun/campus_resource_management/issues/27)，配合 C 的 [#24](https://github.com/ElastingYun/campus_resource_management/issues/24)。状态：B 侧实现，待 C/D Review 与真实适配。本说明替代 [B-02](b02-resource-management.md) 中审计事件的 v1 字段约定，资源 HTTP 路径和 DTO 不变。

代码基于 D 集成分支 `490e4f6f`（含 B #20/#26），已读取 C #22 / `9e019f4` 的 `AuditService.record`、请求上下文中间件及 C-v1，也核对了 D 在 #10 的消费意见。A/C/D 的待定政策不因本 PR 获批；没有修改其模块或共享挂载。

## 1. 事件字段及兼容影响

回调仍为 `audit_sink(session, mutation)`，其中 session 是本次资源写入使用的同一个 SQLAlchemy Session。ResourceMutation 是不可变 dataclass，字段如下：

| 字段 | 类型 | 来源及语义 |
| --- | --- | --- |
| schema_version | Literal[2] | 标记此进程内端口版本，不是数据库 schema 版本 |
| actor_id | str | C/D 可信 ResourceActor.subject，不读取浏览器自报身份 |
| action | Literal | room.create / room.update / seat.create / seat.update |
| resource_id | int | 本次持久化资源 ID；类型与原端口一致 |
| request_id | str | 可信服务端上下文的规范小写 UUID，与 C 当前中间件对齐 |
| room_id | int | 教室事件为其自身 ID，座位事件为其实际所属教室 ID |
| before | str 或 None | 规范 JSON 对象字符串；创建时为 None，更新时为变化字段的原值 |
| after | str | 规范 JSON 对象字符串；创建时为白名单初始值，更新时为变化字段的新值 |

**调用方升级要求**：v2 新增必需事件字段，直接构造旧三字段 ResourceMutation 的代码需要更新；原 sink 的两个参数签名保持不变。所有写请求新增可信请求上下文条件。此变更面向尚未正式挂载的模块，不能在未更新适配器时按 v1 启用。

C 当前 `record` 的 before/after 参数及 AuditView 均为字符串，因此本端口使用 JSON 字符串，不将 Python dict 隐式转换成另一种格式。C 可直接传入这两个字符串；actor 的 UUID 转换、target 编码、审计时间与真实 SQL 适配仍由 C 实现并评审。resource_id/room_id 在 Python 内保持 int；转为 JSON 或 C 的字符串 ID 时用 `str(...)`，禁止经 JavaScript Number 中转。

## 2. 白名单与快照

- 教室创建：code、name、location、access_scope、department_id、open_time、close_time、enabled。
- 座位创建：code、outlet_type、enabled；所属教室单独通过事件 room_id 提供。
- 更新：仅记录上述白名单中持久化前后确实不同的字段；目前可编辑字段仍仅教室 code/name/location、座位 code/outlet_type。

快照取自同事务中实际读取的数据库行，保留去空白后的结果和服务端创建配置，不复制原始请求。开放时间使用字符串，nullable department_id 仍是 JSON null，不由审计模块解释准入资格。未包含 created_at、updated_at、revision、expected_revision、密码、会话或请求头。

JSON 键排序、紧凑编码；创建 before=None。对同值更新，原有请求仍执行更新时间写入并记录一次 update，业务字段 before/after 均为 `"{}"`，不虚构字段变化。修改使用已有行锁与 expected_revision；陈旧修改、越权、唯一约束拒绝不会产生成功审计。

例如某座位从固定插座改成轨道插座，before=`'{"outlet_type":"fixed"}'`，after=`'{"outlet_type":"rail"}'`。同一次事件包含真实 seat ID 和其 room ID，C 不需要查 B 私有表补所属关系。

## 3. 请求上下文与错误

`create_resources_router(..., request_id_dependency=...)` 新增可选依赖端口。默认 `get_resource_request_id(Request)` 只读取 `request.state.request_id`，对应 C 当前中间件每次请求调用 uuid4 的行为；不读取 X-Request-ID、查询参数或请求体，不自行生成第二个无关 ID。若宿主使用其他上下文位置，由可信适配器显式注入返回规范 UUID 字符串的依赖。

缺失、非字符串或非规范 UUID 时，获准写入返回 503 / audit_context_unconfigured，尚未产生资源写入或成功审计；只读请求保持原有权限及范围检查。没有可信 actor、审计 sink、新建策略等原有默认拒绝条件继续保留。依赖由服务端配置，不能让前端替自己注入信任。

回调异常（包含审计存储约束错误）统一为 503 / audit_unavailable，避免误报为资源编号冲突。资源自身唯一约束仍为 409。错误响应不回显内部 SQL、异常消息或输入；HTTP 错误封装仍为 `detail: {code, message}`。

## 4. 事务及真实接入责任

资源变更、读取持久化后状态、审计回调、最终 commit 在同一个 Session/事务中完成。回调可以执行审计 INSERT，但不得 commit、rollback、close 或另开连接提交。回调或提交失败时由 ResourceService 统一回滚。审计事件仅在资源事务成功后才算持久成功；回调被调用本身不代表提交完成。

B 没有实现 C 私有审计表映射，也没有调用 C 的独立事务 failure 方法拼接成功审计。拒绝/失败事件需要 C 在资源事务回滚后另行适配；当前 C 的 ServiceError handler 不自动等价于 B 的 ResourceError handler，这部分仍属 #24。公开字段只解决 B 的元数据缺口。

C/D 接入顺序：确认 v2 字段 → 可信 actor/请求上下文 → 同 Session 的真实 sink → D 挂载并配置服务端创建策略 → 验证真实会话创建/刷新/编辑、权限范围及资源与审计同回滚。读/写/创建的 permission 名称、学生可见和可申请范围、校园 null 院系语义仍待共同确认；本 PR 不给出默认授权或新的业务政策。

## 5. 实际验证记录

日期 2026-10-28。本机已有锁定依赖，Python 3.12.14 / Node 24.19.0；项目目标 Python 3.13 / Node 22 和 PostgreSQL 17 由现有 Engineering CI 检查，不以本机运行代替目标版本结果。

| 命令/场景 | 本机结果 |
| --- | --- |
| backend `ruff check .` | 通过 |
| backend `ruff format --check .` | 通过 |
| backend `python -m pytest -m 'not integration' -q` | 46 passed、5 deselected；B 资源共40项单元场景，本轮新增17项 |
| Python `pip check` | No broken requirements found；未修改依赖或锁文件 |
| frontend `npm run test` | 77 passed；前端代码未改 |
| frontend `npm run build` | 类型检查及生产构建通过 |
| Git diff 检查 | 空白和文件范围检查通过；无生成产物 |

保留 TestClient/HTTPX 原有一条弃用警告，未屏蔽。SQLite 仅为隔离单元测试，新增合成 `resource_audit_test_only` 表不进入应用 metadata 或迁移。

PostgreSQL 测试继续使用 UUID 私有 schema，审计表同样只在自己的 schema 内创建和清理。覆盖正常持久化、并发编辑只有胜者产生审计，以及审计插入后普通异常/真实主键约束异常导致资源和审计同回滚。这里使用合成审计存储，不证明 C 的真实实现已经接通。

测试有效性：仅在 `/private/tmp` 副本把审计失败路径的 rollback 改成 commit，事务回滚测试 **1 failed**（被拒绝的资源修改错误地保留）；恢复后同一测试 **1 passed**。仓库实现未被破坏。固定提交和 CI 链接在 PR 中记录。

**NOT RUN locally**：Python 3.13、Node 22、真实 PostgreSQL 与 Docker。**NOT RUN as integration**：C 正式身份和审计、D 挂载、浏览器真实持久化及生产部署。无数据库迁移、应用自动建表或共享配置变更；README、AGENTS 未改。
