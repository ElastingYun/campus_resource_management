# C-v1：M2 前端与公共身份接口交付

负责人：C / Wuyh11，提交身份 wuyihao。关联 [工程接入 #14](https://github.com/ElastingYun/campus_resource_management/issues/14) 和 [前端对齐 #10](https://github.com/ElastingYun/campus_resource_management/issues/10)。
本文描述当前代码实际提供的接口，供 D 对接；生产业务政策、B 的资源模型和 A 的占用契约仍需相关 owner 确认。合成示例不代表真实账号或已批准的审批政策。
机器契约见 [OpenAPI](c-v1-openapi.json)，部署与迁移见[运行说明](c-member-backend.md)。

## 1. C-01：能力、路径与分页

所有业务路径以 `/api/v1` 开始。开发 Vite 与容器 Nginx 的 `/api` 代理转发到统一后端，同源浏览器使用这些相对路径。

| 能力 | 方法与路径 | 返回 |
| --- | --- | --- |
| 登录 | `POST /auth/sessions` | `access_token`、`token_type=bearer`、`expires_at` |
| 当前身份 | `GET /auth/me` | 用户 UUID、院系、角色、权限和教室管理范围 |
| 退出 | `DELETE /auth/sessions/current` | 204；旧会话后续请求 401 |
| 申请提交 | `POST /m2/applications` | 201，完整申请视图 |
| 授权列表 | `GET /m2/applications?limit=50&offset=0` | 申请数组；当前不提供 total、排序参数或状态筛选 |
| 详情 | `GET /m2/applications/{id}` | 完整申请视图 |
| 当前审批待办 | `GET /m2/review-tasks?limit=50&offset=0` | 当前节点、权限与资源范围内的申请数组 |
| 节点决定 | `POST /m2/applications/{id}/decisions` | 更新后的申请视图 |
| 可执行操作 | `GET /m2/applications/{id}/actions` | 申请 ID、当前版本、allowed_actions |
| 节点历史 | `GET /m2/applications/{id}/history` | 节点决定数组 |
| 撤销 | `POST /m2/applications/{id}/revocations` | 更新后的申请视图；须显式配置允许并有权限 |
| 审计查询 | `GET /audit/events?limit=50&offset=0` | 受权限和范围约束的审计数组 |
| 账号授权管理 | `PUT /auth/users/{id}/access` | 角色/范围/启停结果；未配置管理策略时关闭 |

列表 limit 为 1～100，offset 非负。空结果返回 `[]`。列表授权由后端限定，客户端不能指定任意 applicant_id 切换用户。
第一轮申请、本人列表/详情、审批待办及通过/驳回能力均已提供；真实教室选择须 B 的接口接入。只有允许的撤销入口会显示有效操作。

## 2. C-02：申请字段、ID 与时间

| 字段 | 类型 | 当前校验 |
| --- | --- | --- |
| room_id | 非空字符串，最多 128 字符 | 作为 B 的不透明稳定标识；提交时读取真实主数据并校验引用、启用和资格 |
| starts_at / ends_at | 带时区的 ISO 8601 字符串 | 结束严格晚于开始；内部统一 UTC |
| purpose | 字符串，去首尾空白后 1～2000 字符 | 不接受控制字符；用途仅在获授权业务查询中公开 |

请求不包含申请人、角色、院系、状态或审批流程，额外字段返回 422。
申请和用户 ID 为 UUID 字符串；room_id 当前是字符串。B 若确认其他标识格式，需要通过接口评审统一，不能自行把 JSON 数字当成当前已支持格式。
M2 时长、提前量、时间粒度和业务时区来自显式配置，不默认继承 M1 的整点/4 小时政策。示例中未限制时长的配置不构成生产承诺。

合成请求：

```http
POST /api/v1/m2/applications
Authorization: Bearer <access_token>
Idempotency-Key: synthetic-application-001
Content-Type: application/json

{
  "room_id": "room-demo-01",
  "starts_at": "2030-01-02T09:00:00+08:00",
  "ends_at": "2030-01-02T11:00:00+08:00",
  "purpose": "合成课程活动申请"
}
```

合法时间格式示例不代表教室、申请资格或该时段实际可用；后端仍依配置和资源接口判断。
主要响应字段包括 id、applicant_id、room_id、starts_at、ends_at、purpose、review_status、integration_status、step_index、step_count、deadline、version、revoked、effective、created_at、updated_at。
step_index 从 0 开始；step_count 来自提交时流程快照。deadline 是审批节点截止时间，当前只对待审批状态执行超时关闭。

成功提交的合成 201 响应如下；本人列表为此类对象的数组，详情返回同一视图。示例 UUID 和时间只用于说明结构：

```json
{
  "id": "00000000-0000-4000-8000-000000000010",
  "applicant_id": "00000000-0000-4000-8000-000000000001",
  "room_id": "room-demo-01",
  "starts_at": "2030-01-02T01:00:00Z",
  "ends_at": "2030-01-02T03:00:00Z",
  "purpose": "合成课程活动申请",
  "review_status": "REVIEWING",
  "integration_status": "NONE",
  "step_index": 0,
  "step_count": 2,
  "deadline": "2030-01-01T01:10:00Z",
  "version": 1,
  "revoked": false,
  "effective": false,
  "created_at": "2030-01-01T01:00:00Z",
  "updated_at": "2030-01-01T01:00:00Z"
}
```

对这个响应，actions 可能为 `[]`（申请人无审批/撤销权）；对具备当前节点权限和范围的审批人可能为 `["APPROVE","REJECT","REVOKE"]`，以实际查询为准。

## 3. C-03：身份、许可与数据范围

登录请求为 username/password JSON；密码只经请求体提交。后续请求使用 `Authorization: Bearer <access_token>`。
服务端使用可撤销会话，读取当前账号启用状态、角色和范围；退出/过期后返回 401，账号停用撤销已有会话。当前无刷新令牌。
前端建议在内存保存会话，收到 401 后重新登录；服务间凭据只存在后端环境中。

合成登录请求 `{"username":"synthetic-student","password":"<operator-provided-synthetic-password>"}`；200 响应结构为 `{"access_token":"<opaque-session-token>","token_type":"bearer","expires_at":"2030-01-01T01:10:00Z"}`。占位值不可直接用于实际登录；账号由受信初始化命令创建。

合成当前身份响应：

```json
{
  "subject_id": "00000000-0000-4000-8000-000000000001",
  "department_id": "department-demo",
  "roles": ["synthetic-first-reviewer"],
  "permissions": ["audit.read", "m2.read_all", "m2.review", "m2.revoke", "review.first"],
  "data_scopes": {"room_ids": ["room-demo-01"], "all_rooms": false}
}
```

- 提交需 m2.submit，并通过服务端资源/资格/时段规则。
- 本人可查看自己的申请；当前节点的获授权审批人可看对应申请；其他管理读取需 m2.read_all 和资源范围。
- 审批同时需要 m2.review、流程快照的节点权限、资源范围、自审规则及有效期限。
- 撤销需 m2.revoke、资源范围、流程许可及合法状态。
- 审计需 audit.read；账号管理需 auth.manage、非越权委派和显式账号管理范围策略。

前端调用 actions 获取当前服务器允许的动作，例如：

```json
{
  "application_id": "00000000-0000-4000-8000-000000000010",
  "version": 1,
  "allowed_actions": ["APPROVE", "REJECT", "REVOKE"]
}
```

该结果是查询时快照，写操作仍重新授权和校验版本。页面无需复制节点权限判断；角色名称本身不构成许可。

## 4. C-04：状态与操作

| 事件 | 审批结果 | 集成结果 | 页面含义 |
| --- | --- | --- | --- |
| 成功提交/中间节点通过 | REVIEWING | NONE | 等待当前节点处理 |
| 当前节点驳回 | REJECTED | NONE | 审批关闭，保留决定历史 |
| 待审批截止条件满足 | TIMED_OUT | NONE | 后台关闭；无需页面在线 |
| 所有节点通过 | PASSED | APPLY_PENDING | 正在确认整教室占用 |
| M1 写入结果未知 | PASSED | APPLY_UNKNOWN | 保留处理中，查询或同键恢复 |
| M1 明确确认占用 | PASSED | APPLIED | 当 revoked=false 时 effective=true |
| M1 明确冲突 | PASSED | APPLY_CONFLICT | 显示占用冲突，后续业务去向待决策 |
| 获准撤销且已有占用意图 | 保留历史审批结果 | RELEASE_PENDING / RELEASE_UNKNOWN | revoked=true，等待来源释放确认 |
| M1 确认释放 | 保留历史审批结果 | RELEASED | 本申请来源已释放 |

只有 effective=true 才展示预约已生效；资源是否可再次预约由 M1 汇总剩余来源判定。
后台扫描只处理未撤销的 REVIEWING 申请。审批完成后的自动到期撤销、申请人自由撤回、终态重开当前未启用。
几级审批、期限、自审、驳回理由和撤销许可均来自显式流程配置；合成示例的两级审批不是全平台规则。

通过/驳回请求：

```json
{"decision": "APPROVE", "comment": "合成审批意见", "expected_version": 1}
```

驳回使用 REJECT；配置要求理由时 comment 不能为空。重复决定同一节点、跳级、截止后决定及旧版本操作均被后端拒绝。
撤销请求为 `{"expected_version": 3}`。所有申请写操作都要求 Idempotency-Key。

## 5. C-05：错误、幂等与未知结果

所有 C 错误携带服务端 request_id，响应头含 X-Request-ID；校验错误只返回字段位置和类型，不回显原输入。

| 状态码 | 常见代码 | 前端处理 |
| --- | --- | --- |
| 401 | AUTHENTICATION_REQUIRED / INVALID_SESSION / INVALID_CREDENTIALS | 登录或重新登录 |
| 403 | FORBIDDEN / OUT_OF_SCOPE / WRONG_REVIEWER / DEPARTMENT_DENIED | 显示权限拒绝，刷新身份/动作 |
| 404 | NOT_FOUND / ROOM_NOT_FOUND | 对象不存在或不可见，不推断他人数据 |
| 409 | STALE_VERSION / INVALID_STATE / REVIEW_EXPIRED / IDEMPOTENCY_CONFLICT / ROOM_UNAVAILABLE | 查询最新状态并提示具体冲突 |
| 422 | INVALID_INPUT / REASON_REQUIRED / INVALID_INTERVAL / TIME_GRANULARITY / DURATION_EXCEEDED | 按字段或业务错误修正 |
| 429 | LOGIN_RATE_LIMIT | 暂停重复登录，按配置窗口后再试 |
| 503 | DATABASE_UNAVAILABLE / AUDIT_UNAVAILABLE / RESOURCE_UNAVAILABLE | 明确依赖不可用，保留输入并按幂等约定恢复 |

示例错误：

```json
{
  "error": {"code": "STALE_VERSION", "message": "申请已更新，请刷新后重试"},
  "request_id": "00000000-0000-4000-8000-000000000099"
}
```

幂等键使用 1～128 位 `[A-Za-z0-9_.:-]`，按操作者、动作和目标隔离；同键同规范化内容返回首次结果，同键不同内容返回 409。
申请提交的 HTTP 响应丢失时，使用原键和原内容重试以找回申请 ID；得到 ID 后 GET 最新状态。重放结果保留首次状态，后续后台进度以查询为准。
决定/撤销响应丢失时同样保留键与 expected_version；查询当前申请或重放原请求，不用新键猜测重复执行。

## 6. C-06：可见字段与审计

获授权申请视图提供申请人 UUID、用途、时段和进度；历史提供节点、处理人 UUID、意见、决定与时间。当前不返回真实姓名、联系方式、密码散列或会话秘密。
申请人、当前节点审批人及获授相应资源管理读取权限的人按同一后端对象范围查看；若需更细的用途/意见脱敏，须先确认隐私政策再调整字段契约。
写操作由后端记录成功审计；拒绝事件独立记录。前端调用业务接口即可，无需另发“操作成功”审计来拼接事务。
审计查询单独授权；当前只实现本地接入，跨实例审计接收/投递仍待服务拓扑确定。

## 7. 本轮可联调条件与剩余依赖

统一入口支持显式开启 C；先执行 Alembic、配置 C 策略和服务凭据，再通过受信账号初始化命令建立合成用户。默认 bootstrap 模式保留现有健康探针。
前端通过 `/api/v1` 同源代理访问。实际资源查询需要 B 的实现；真实占用、释放及乱序终态保护需要 A 的实现；通知投递需要 E 的契约。
C 的角色和流程名称由显式配置给出；没有为真实成员或学生自动授权。前端原型数据与真实 API 接入须明确切换。
当前公开 OpenAPI、代码与本地/CI 结果仅证明 C 的实现和契约测试，真实 A/B/E 联调结果单独记录。
截至 2026-10-28，对方实现已出现于 A 的整合 Draft PR #18 和 B 的 Draft PR #20；它们尚不等于主线可调用服务。A 的来源限制协议与 C 的 operation_id/generation 协议有差异，B 的校园级 nullable department_id 及普通用户可见范围仍待共同对齐，不能只改 URL 就宣称接通。
