# B-02 教室与座位管理：实现及接入边界

负责人 B / hrzhao7。状态：第一阶段代码，待 A/C/D 评审和真实接入。
后续审计端口与可信请求上下文升级见 [B 资源审计 v2](b-resource-audit-v2.md)；真实接入时应按最新版本更新事件字段及写入上下文依赖。
关联 [Issue #19](https://github.com/ElastingYun/campus_resource_management/issues/19)、[接口讨论 #10](https://github.com/ElastingYun/campus_resource_management/issues/10)、[C 接入 #14](https://github.com/ElastingYun/campus_resource_management/issues/14)、[A 整合 PR #18](https://github.com/ElastingYun/campus_resource_management/pull/18)。

本轮实现 B-UI-05、B-RES-01/02/06 中可独立测试的管理能力。共享模型、普通学生的数据范围、创建策略及正式认证尚未获其他 owner 确认；不能把本模块测试通过当作真实跨模块联调通过。

## 1. 代码与工程基线

- 前端：`frontend/src/modules/m1-reservation/resources/`；复用 D 的 [PR #15](https://github.com/ElastingYun/campus_resource_management/pull/15) 导航与锁定测试工具。
- 后端：`backend/app/modules/resources/`，不搬迁或修改 A 的 `common/resources` 占位模型。
- 测试：`backend/tests/resources/` 和前端模块内测试；不替换 D 的工程检查。
- 本增量以 `feat/m2-workspace-prototype` 为 PR base；#15 合并后需切换到 main 并重新检查差异、迁移及 CI。
- 不修改 README、AGENTS、依赖锁、全局后端入口或任何已提交迁移。

## 2. 已实现的能力与限制

前端提供教室列表/搜索/分页、新增和编辑，按教室管理座位并按插座筛选。表单校验长度和空值；保存中禁止重复提交；失败保留输入；写入结果未知时先要求核对，不自动重试；晚到的查询响应不覆盖新选择。

`/#resources-prototype` 使用明确标记的合成内存数据，刷新重置。示例准入和开放时间只供演示。`/#resources` 默认未配置、不能写入，也不会把接口故障回退为合成成功。

`createHttpResourceGateway` 是可注入 fetch 的真实接口适配器，验证返回结构后才报告成功，使用同源凭据和有限超时，不存储令牌或定义 C 的登录方法。`allowManage` 仅影响页面按钮，不能替代后端授权。

后端提供 router factory、请求校验、SQLAlchemy Core 数据访问、后端读写权限及资源范围检查、事务提交/回滚和陈旧编辑检测。默认应用没有挂载该 router，模块导入不连接数据库或建表。

本轮不提供删除、停用、移动座位、修改已有教室的准入/开放时间，也不改预约、审批或维修状态。`enabled` 仅是静态配置，API 不提供动态 availability。

## 3. 资源字段和兼容方案（待 owner 确认）

SQL 引用映射兼容 PR #18：数据库 `rooms.id`、`seats.id` 为 BIGINT，教室 code 唯一，座位 code 在 `(room_id, code)` 内唯一。教室 code/name/location 长度 32/100/200，座位 code 长度 32，插座为 none/fixed/rail。

这不是新迁移。`tables.metadata` 仅供查询和隔离测试，不应对应用数据库调用 `create_all`；共享表仍需 A/B/D 对齐并通过版本化迁移接入。测试在私有 schema 建表不等于共享迁移已经完成。

HTTP 的 BIGINT ID 使用十进制字符串，例如 `"9007199254740993"`，避免 JavaScript 丢失精度；数据库键不变。该 JSON 表达方案仍需 A/C/D 确认。`revision` 是对当前持久化记录计算的修订标记，不新增数据库版本列；修改必须携带原 revision，PostgreSQL 行锁保证检查与写入处于同一事务，陈旧请求返回 409。

## 4. 模块级 API

前缀 `/api/v1/resources`；API 是当前实现提案，尚未配置到统一应用。

| 方法与路径 | 请求 | 成功响应 |
| --- | --- | --- |
| GET `/rooms` | q 可选，limit 1～100（默认 20），offset ≥0 | `{items, total, limit, offset}` |
| GET `/rooms/{id}` | 稳定教室标识 | 教室对象 |
| POST `/rooms` | `{code, name, location}` | 201 教室对象 |
| PATCH `/rooms/{id}` | 至少一项 code/name/location，必填 expected_revision | 更新后的教室对象 |
| GET `/rooms/{id}/seats` | q、outlet_type 可选，limit、offset 同上 | 座位分页对象 |
| GET `/seats/{id}` | 稳定座位标识 | 座位对象 |
| POST `/rooms/{id}/seats` | `{code, outlet_type}` | 201 座位对象 |
| PATCH `/seats/{id}` | 至少一项 code/outlet_type，必填 expected_revision | 更新后的座位对象 |

教室对象包括 id/code/name/location/access_scope/department_id/open_time/close_time/enabled/revision；座位对象包括 id/room_id/code/outlet_type/enabled/revision。创建和更新拒绝未知字段、null、空白及超长内容，不接受客户端修改 enabled、room_id、准入或动态状态。

业务错误封装为 `{"detail":{"code":"...","message":"..."}}`。无权限 403；不存在或不可访问 404；编号冲突及陈旧修改 409；格式校验 422；接入缺失或存储/审计故障 503。前端使用固定安全消息，不原样展示内部异常。写入 5xx、超时或无效成功响应按结果未知处理，不认为一定未写入。

## 5. C/D 必须明确接入的依赖

`create_resources_router` 接受以下显式集成参数：

| 接入点 | 行为和责任 |
| --- | --- |
| actor_dependency | C 验证身份后构造 ResourceActor：subject、can_read、can_manage、can_create_rooms、room_ids。默认依赖返回 503，不解析 X-Dev-*、不提供默认管理员 |
| room_ids | 默认空集合，不授予资源；显式 None 才是全域。有限范围只能查询和修改集合内教室；不允许全域新增教室 |
| session_dependency | D 的请求级 SQLAlchemy Session。默认适配已有 app.state.engine，每次请求独立关闭；没有 engine 时返回 503 |
| new_room_settings | 已批准的服务端新建配置：开放时间、准入范围、院系及 enabled，全部显式给出；缺失则不创建教室。浏览器不能提交策略字段 |
| audit_sink | C 的同步审计适配器，收到同一个 Session 和 ResourceMutation，必须把审计写入该事务，不能自行提交。缺失或抛错时拒绝/回滚写入；同请求读写使用独立 Session，服务负责提交 |

有限权限之外的资源隐藏为 404，列表只查询授权范围。当前能力面向资源管理，不据此决定 M2 普通用户可看哪些教室；该可见范围及 CSRF/身份传递由 C 的正式适配决定。

接入时由 D 在批准的服务入口调用 `include_router(create_resources_router(...))`，复用生命周期 engine。A/B/D 先确认共享表及迁移，C 提供真实身份、数据范围、审计及新建配置来源，再配置前端真实 gateway。禁止用开发请求头、测试身份或 no-op 审计作为真实接入。

## 6. 后续验收

1. 在 #10 确认 ID、字段、路径和角色/资源范围；与 A 确认同教室座位编号唯一性及共享迁移衔接。
2. 在真实隔离 PostgreSQL 上应用批准迁移、配置 C 的依赖并挂载业务入口。
3. 浏览器通过真实身份创建、刷新读取、编辑教室和座位，审计与数据同时持久化。
4. 验证无权限、资源范围、重复编号、并发编辑、网络未知结果及审计故障回滚。
5. 再验证 M2 查询和 M1 动态可用性；不把静态启用当作可预约。

实际本机与 CI 证据见 [B02 验证记录](../testing/b02-resource-verification.md)。本轮实现和合并均不自动批准共享政策，不关闭完整接入任务。
