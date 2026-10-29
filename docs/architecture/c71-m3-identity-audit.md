# C-71：M3 可信身份与创建审计

关联 [Issue #71](https://github.com/ElastingYun/campus_resource_management/issues/71)，
依赖 E [PR #62](https://github.com/ElastingYun/campus_resource_management/pull/62)
固定提交 `d310c5610ae66341a767244e000d8babb1142b08`。

## 接入方式

C 新增 `app.common.auth.m3_adapter.install_m3_identity`，由宿主在安装 C 请求上下文后显式调用。
默认主应用没有调用它，也没有新增角色、用户、授权、表结构或生产配置。
宿主应先整合经人工评审的 E 模块及迁移，再选择是否挂载。

```python
from app.common.auth.m3_adapter import M3Permissions, install_m3_identity

install_m3_identity(
    application,
    auth=runtime.auth,
    audit=runtime.audit,
    permissions=M3Permissions(
        create="m3.ticket.create",
        read_own="m3.ticket.read_own",
    ),
    room_policy_factory=approved_room_policy_factory,
)
```

以上权限名是显式配置示例，不代表已批准生产角色。两个配置字段均必填，并限定为 `m3.` 名称空间，
不能用 `m2.submit` 作为 M3 资格。创建能力、本人读取能力分别从真实 C 会话当前权限计算；
停用、退出、会话过期或权限撤回按现有 C 认证执行。客户端自报身份头不参与构造 `TicketActor`。
E 自己执行本人记录过滤；本适配不增加跨用户读取或派单权限。

`approved_room_policy_factory(principal)` 接收本次请求通过 C 认证的完整 `Principal`，
返回 E `RoomPolicy`。它与 `TicketActor` 使用同一请求的身份快照，可读取可信院系、角色及房间范围。
工厂须自行绑定该身份，再按 B/E 已确认的公开端口及报修资格校验房间；C 不替宿主猜测 M3 规则。
没有提供工厂时，创建返回 E 的 `503 room_policy_unconfigured`，本人查询仍可按权限使用。
测试中的房间策略是明确的合成回调，不是实际 B 资格验收。

## 事务与审计字段

E 创建服务插入工单后、提交前调用 C `M3TicketAudit.record_created`：

| 字段 | 内容 |
| --- | --- |
| actor | 该请求通过 C 认证的主体 UUID，并与 E 回调主体核对 |
| action / result | `m3.ticket.create` / `SUCCESS` |
| target | E 新工单 UUID 字符串 |
| room_id | 规范正十进制 BIGINT 字符串，保留大于 JS 安全整数的 ID |
| changes | `before=None`、`after=REPORTED` |
| request_id / occurred_at | E 为这次实际创建生成的 UUID / 带时区创建时间 |

C HTTP `X-Request-ID` 与 E 创建事件的 `request_id` 是两个服务端生成的标识；
不把客户端请求头或幂等键当审计请求 ID。故障描述、密码、令牌均不进入创建审计。

适配仅调用 `AuditService.record_in_session`，加入 E 原有 PostgreSQL 事务，
不提交、回滚、关闭 Session，也不另开成功审计事务。E 拥有事务结果：
审计失败时工单一起回滚；同键相同内容重放返回原工单，不重复记录创建审计。
E 原有错误响应保持 `detail.code/message`，C 认证错误保持现有 `error` 包装。

## 迁移与验收边界

本任务不修改旧迁移，也不擅自解决 A/C/E 的迁移分支。
E `e02_m3_tickets` 从 A `0006` 分支，C 当前为 `0007_merge_m1_c`，正式同时整合仍需
D/C/E 决定汇合方案，验证完整空库、既有库及重复升级。

验收准备器读取固定 E Git 对象，投影真实模块，并把 E 原始迁移文件放到**测试目录**。
每个测试在随机 PostgreSQL schema 内先应用既有 C SQL，再通过 Alembic Operations 执行
原始 E `upgrade()` DDL；不会把第二个 head 添加到产品迁移目录。
因此本轮证明真实 E 路由/服务、C Bearer/审计和事务行为，不能替代全迁移图验收。

新增 `.github/workflows/c-m3-acceptance.yml` 使用与工程 CI 一致的固定 PostgreSQL 17、
Python 3.13 与依赖锁，要求 E 源码存在，缺失直接失败。原 Engineering 与 C/B 验收继续独立运行。
影响范围：C 适配/测试/文档及此新增 CI；E/B/A 产品文件、主应用挂载与旧迁移均未修改。
端口请 E 评审，CI 请 D 评审；技术评论和 AI 辅助验证不替代非作者人工批准。

## 已执行验证（2026-10-29）

- 本机 Python 3.13.11 / 独立 PostgreSQL 16.2：
  `pytest -q tests/c_module/test_m3_identity.py tests/c_module/test_identity.py tests/c_module/test_login_concurrency.py tests/c_module/test_principal_snapshot.py`
  **31 passed, 1 warning**，无跳过；其中新增 M3 7 项。
- 新增测试覆盖真实登录、创建及本人查询、他人 404、幂等重放仅一次审计、权限撤回/退出、
  M2 权限不授 M3、缺少/拒绝房间策略、BIGINT 原值、默认无路由/重复安装拒绝。
- PostgreSQL CHECK 故障使真实 C 审计写入失败：响应 503，工单和创建审计均为零；
  解除仅测试约束后，同键提交 201、各一条记录。
- 真实 TCP 通过 uvicorn/httpx 完成登录→创建→查询→退出→401；它是同宿主实际网络验证，
  不是独立服务间的 M1/M3 写回或 B 报修资格验证。
- 隔离副本故意省略成功审计：目标两项从通过变为 **2 failed**；恢复原字节后 **2 passed**。
- 当前独立 C 工程：`pytest -q -m 'not integration'` **98 passed, 3 skipped, 166 deselected**；
  三个跳过为未安装的 B 两个可选模块及 E 组合模块；固定组合工作流分别要求对应模块存在。
- 当前 C 与固定 C/E 组合 Ruff、格式检查均通过。保留现有 Starlette/httpx 弃用告警，未增依赖。
- 首轮准备器把双方相同的空 `.gitkeep` 当冲突，已改为允许原字节一致；
  首轮 5 passed / 2 failed 暴露安装标记与本机 SOCKS 环境问题，分别修正状态标记及
  仅本机 TCP 测试 `trust_env=False` 后重跑上述 31 项，保留原断言。

CI 的最终提交和实际运行链接在 PR 中核对；未跑的全迁移合流、B 资格接线、生产角色、
浏览器、派单/维修/验收/通知/M1 写回不列为已验收。
