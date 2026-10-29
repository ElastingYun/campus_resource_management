# E-01：M3 报修 API 与跨模块契约草案

状态：**Draft / 候选路径和字段，未批准、未实现。** 关联 [Issue #44](https://github.com/ElastingYun/campus_resource_management/issues/44)、[需求与状态机](../requirements/e01-m3-repair-baseline.md)、[验收清单](../testing/e01-m3-acceptance-plan.md)。本文件不替代 A/B/C/D/F 的版本化契约或决定工单业务政策。

## 1. 当前代码基线与契约差异

`main`（本草案起草时为 `e5e95e3`）已有 FastAPI、SQLAlchemy、Alembic、pytest、Vue 和工程 CI；`backend/app/modules/m3_repair/` 及 `backend/app/common/notifications/` 仍只有占位文件。M1 业务见未合并 [PR #18](https://github.com/ElastingYun/campus_resource_management/pull/18)，C 的认证/M2 见未合并 [PR #22](https://github.com/ElastingYun/campus_resource_management/pull/22) 及后续依赖 PR；B 资源也在独立 PR。下表为**观察到的候选实现**，不是主线已经可调用的接口。

| 对口 | 当前候选实现 | M3 接入前要解决 |
| --- | --- | --- |
| A / M1 | `PUT/GET /api/v1/m1/restrictions/m3_repair/{source_id}`、`POST .../release`；整数 `room_id`，`end_at=null`，验收解除 `reason=accepted`，来源权限 `m1:restriction:m3_repair` | 与 B 的教室 ID 表达、服务身份、响应及错误格式共同评审；M3 不写 A 的表 |
| B / 资源 | 教室静态属性由 B 持有；其候选公开 JSON ID 是十进制字符串 | 确定 M3 用哪个可信读取接口、ID 规范及教室停用/注销的处理 |
| C / 身份审计 | C 候选后端使用 Bearer 会话、权限及教室范围；M2 另持久记录远端操作并恢复未知结果 | C 为 M3 提供可信主体/服务账号与审计入口；M3 不信任前端自报角色或房间范围 |
| D / 工程 | `main` 提供基础入口、数据库连接与迁移，业务 router 尚未统一挂载 | D 在契约评审后接入路由、后台任务、配置、迁移顺序和运行拓扑 |
| F / 页面 | M3 页面仍待真实接口 | 确认列表/详情、错误提示、待核实状态与验收评价的数据需要 |

特别注意：C 的 M2 HTTP 网关当前期待含 `operation_id`、`result` 的远端回执，A 的 M1 候选限制接口返回的是来源限制记录；两者尚未完全对齐。M3 可以借鉴 C 的持久操作思路，**不能复制其未对齐的线协议**。

## 2. M3 面向页面的候选接口

路径统一以 `/api/v1/m3` 开始；具体字段、分页、错误封装和状态码由 E/C/F 与 D 一起定稿。写操作中的主体来自服务端可信会话，不接受请求体内的任意 `actor_id`、权限或工单状态作为授权依据。返回只包含调用方有权查看的字段，读写响应禁缓存。

| 方法与候选路径 | 意图及候选输入 | 候选输出/关键拒绝 | 待确认 |
| --- | --- | --- | --- |
| `POST /tickets` | `room_id`、故障类别、描述；`Idempotency-Key` | 201 工单视图；重复同内容返回原工单；无效教室/越权/同键不同内容拒绝 | 谁可报修、字段、附件 |
| `GET /tickets?limit=&offset=` | 本人或授权范围内工单列表 | 200 分页列表；服务端限制范围 | 管理范围、排序及筛选 |
| `GET /tickets/{ticket_id}` | 工单详情及 M1 限制执行状态 | 200 授权视图；不存在或不可见的错误策略一致 | 可见字段、评价权限 |
| `POST /tickets/{ticket_id}/assignments` | 派单给获授权维修人员，带预期版本/操作 ID | 更新后的工单；旧版本、越权、非法转换拒绝 | 派单与转派规则 |
| `POST /tickets/{ticket_id}/work-starts` | 标记开始维修 | 工单与下架处理状态分别返回；未知远端结果显示待核实 | 下架必须确认的业务时点 |
| `POST /tickets/{ticket_id}/completions` | 维修完工，附最小必要说明 | 进入待验收；不触发 M1 解除 | 完工证据 |
| `POST /tickets/{ticket_id}/acceptances` | 验收通过或不通过，带预期版本/操作 ID | 通过时发起本来源解除；失败返修按已批准状态机 | 验收人、自验收及返修 |
| `GET /tickets/{ticket_id}/integration` | 查看下架/解除操作进度 | 当前意图、已确认/未知/待人工处理；无凭据或内部错误 | 哪些角色可读 |

评价可在验收后另开小任务；本轮不为未决定的评价资格和修改期限承诺写接口。`Idempotency-Key` 的长度、作用域、保留期及同键不同内容的错误码在实施前确认；上表的行为是候选原则。状态转换需要服务端检查当前状态与版本，避免两名操作者覆盖彼此的决定。

## 3. M3 → M1 候选写回与未知结果恢复

以下路径和字段来自 A 的 [PR #18 契约草案](https://github.com/ElastingYun/campus_resource_management/blob/feat/m1-d-bootstrap-integration/docs/architecture/a-m1-api-v1.md)，只用作对接讨论。M3 的稳定工单 ID 作为 `source_id`；若采用 UUID，需确认它符合 A 目前的 1～64 位来源 ID 规则。示例教室 ID、时间及凭据都是合成占位值。

```http
PUT /api/v1/m1/restrictions/m3_repair/WO-17
Authorization: Bearer <M3-service-token>
Content-Type: application/json

{"room_id":1,"seat_id":null,"start_at":"2030-01-02T09:00:00+08:00","end_at":null,"note":"repair"}
```

A 的候选行为：首次创建 201；同来源、同参数重试 200；同来源、不同参数 409；已解除来源不能重新生效；响应列出受影响的现有预约 ID。**M3 必须保存首次尝试的规范参数**，重试时不能用“当前时间”重新生成 `start_at`，否则相同工单会变成参数冲突。维修前已有的预约不能由 M3 直接取消或判违约。

```http
POST /api/v1/m1/restrictions/m3_repair/WO-17/release
Authorization: Bearer <M3-service-token>
Content-Type: application/json

{"reason":"accepted"}
```

仅验收通过后发起解除。A 的候选接口对重复解除返回 200，对不存在来源返回 404；`completed`、`cancelled` 等原因不能解除。解除只处理 `WO-17`，其他工单和 M2 占用仍然有效。

候选恢复过程：

1. 在 M3 自己的数据库事务内写入工单状态与一条唯一的下架/解除意图，固定工单 ID、参数、操作代次和创建时间。网络调用在提交之后由后台处理，不在数据库事务中等待远端。
2. 后台向 M1 发送请求，核对来源、房间、状态与响应。连接断开、超时、响应格式不符、服务重启均视为**结果未知**，不推断远端失败。
3. 用同一来源 ID 调用 A 的候选 `GET /restrictions/m3_repair/{source_id}` 核对；匹配预期则确认。若不存在且业务意图仍有效，按原参数重试；若返回状态或房间不匹配，停止自动处理并标记待人工核查。
4. 每次恢复只处理当前业务意图。过期的“下架”重试不能在新一代“验收解除”后重新生效；具体代次、并发与重试上限由 A/E/D 评审。重试耗尽保留待人工处理记录，不提供未经批准的强制成功按钮。

对外将工单业务状态与 `restriction_status` 分开，例如候选值 `PENDING`、`UNKNOWN`、`CONFIRMED`、`ATTENTION`。这些名字仅为草案。`ACCEPTED + UNKNOWN` 表示验收已通过、M1 解除尚待核实；页面不能显示教室已经可预约。M1 最终可用性始终由 A 计算。

## 4. 身份、数据、通知与运行边界

| 事项 | 提案及需确认处 |
| --- | --- |
| 用户认证 | 复用 C 的可信 Bearer 会话和权限/教室范围；M3 后端逐次校验。具体 `m3:*` 权限名和角色由 C/E/F 定稿 |
| 服务认证 | M3→M1 使用仅有 `m1:restriction:m3_repair` 的服务身份；不可把浏览器 token、开发头或工单创建者身份直接当服务凭据 |
| 数据所有权 | E 持有工单、状态历史、操作意图及 M3 迁移；A/B/C 各自持有座位、主数据、身份审计。共享外键、ID 格式与迁移顺序需 A/B/C/D/E 评审 |
| 通知 | 工单升级和状态变化可产生事件，但本轮不实现发送。E 的通知接收、回执查询、去重与 C 的 [#25](https://github.com/ElastingYun/campus_resource_management/issues/25) 单独形成契约；不把本地事件记为送达 |
| 配置 | 复用现有 `CAMPUS_DB_*` 数据库变量；M1 基址、M3 服务凭据、HTTP 超时、后台轮询开关与重试参数见下方候选清单。缺少可信身份或服务配置时，依赖 M1 的操作保持关闭 |
| 健康 | 基础 `/health/live` 只反映进程；数据库 `/health/ready` 按现有工程返回。是否另提供 M1 连通性/后台积压诊断，由 D/E 决定，不能让 M1 暂时不可达伪装成工单写回成功 |
| 部署 | 复用当前 FastAPI/SQLAlchemy/Alembic 工程；D 负责正式挂载和迁移接线。独立服务实例及真实网络调用须有团队 ADR，不用同进程函数调用充当最终联调 |

审计至少记录可信操作者、工单、动作、前后状态、时间、结果与请求关联标识；敏感描述、附件和凭据不得进入公开日志。实际字段、可见范围和保留期限见[待决项](../requirements/e01-m3-repair-baseline.md#4-需要团队明确的决策)。

### 最小运行配置清单（候选，未进入 `.env.example`）

| 候选变量名 | 何时必需 | 安全示例或说明 |
| --- | --- | --- |
| `CAMPUS_DB_HOST`、`CAMPUS_DB_PORT`、`CAMPUS_DB_NAME`、`CAMPUS_DB_USER`、`CAMPUS_DB_PASSWORD` | 所有持久工单接口 | 沿用 D 的现有连接配置；密码由本地环境提供，不写入文档 |
| `CAMPUS_M3_M1_BASE_URL` | 启用下架/解除后台任务时 | `http://m1:8000` 为合成容器地址；实际拓扑由 ADR 决定 |
| `CAMPUS_M3_M1_SERVICE_TOKEN` | 启用下架/解除后台任务时 | 只列变量名；值由受控环境注入，不能放在仓库或浏览器 |
| `CAMPUS_M3_M1_TIMEOUT_SECONDS` | 启用 M1 网络调用时 | 正数，候选 `3`；与重试预算一同评审 |
| `CAMPUS_M3_WORKER_ENABLED` | 运行后台任务时 | 候选 `false`；只有 D 完成接线、身份和配置均有效才可开启 |
| `CAMPUS_M3_RETRY_DELAY_SECONDS`、`CAMPUS_M3_MAX_ATTEMPTS` | 运行后台任务时 | 正数；具体默认值、告警及人工处置条件待批准 |

工单 API 必须依赖数据库和 C 提供的可信身份。后台 M1 写回还依赖服务凭据及目标地址；升级/通知任务另外依赖批准的阈值和接收契约。`/health/live` 不依赖数据库或 M1；现有 `/health/ready` 检查数据库，不证明远端限制已生效。若需观测 M1 连通性和待处理任务，应提供单独的诊断，避免把外部短暂不可达与进程存活混成一个状态。
