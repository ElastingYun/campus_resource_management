# E-03 派单基础接口与接入边界（Draft）

本增量叠加在 E-02 PR #62 上，只提供 `REPORTED → ASSIGNED` 的派单基础。主应用尚未挂载 M3 路由；真实身份、派单员权限、教室范围、维修人资格和审计适配均由已批准的外部契约提供。未配置时返回 503，不把测试替身当生产实现。

## API 与写入语义

`POST /api/v1/m3/tickets/{ticket_id}/assign` 使用可信 Bearer 主体构造的 `TicketActor(can_assign=True)`，请求头 `Operation-Id` 为 UUID；请求体为 `{"assignee_id":"维修人主体 ID","expected_version":0}`。成功返回 201，包含 `ticket_id`、`assignee_id`、`status=ASSIGNED`、`version=1`、`occurred_at`；相同操作标识及相同操作者、参数重放返回 200 和原结果。操作标识被其他参数或操作者复用返回 409；状态或版本不匹配返回 409 `ticket_changed`。缺失、格式不合法的输入返回 422；无派单能力或超出已批准范围返回 403。

`AssignmentPolicy.require_assignable(room_id, actor, assignee_id)` 必须由可信适配器校验教室范围及维修人资格，不得把浏览器提交的角色当真。`AssignmentAudit.record_assigned(session, *, actor, ticket_id, room_id, assignee_id, operation_id, before_status, after_status, now)` 在同一 SQLAlchemy Session 中写成功审计，不自行提交、回滚或关闭 Session，不记录故障描述。C/E 仍需确认正式动作名及字段白名单。审计失败返回 503，工单状态和 M3 操作历史一同回滚。

新迁移 `e03_m3_assignment` 暂接在 `e02_m3_tickets` 之后，为 M3 自有工单增加 `version`、`assignee_id` 和操作历史表。与 C/A 等分支汇合时，由 D/C/E 确定新的迁移汇合节点；不改写既有版本。两个派单请求同时持有旧版本时，条件更新只允许一个成功。

## 待决及不在本次范围

谁可以派单、可派哪个教室、维修人资格、自验收、验收不通过、开工与 M1 下架的先后及未知结果恢复尚未获业务批准。本次不实现开工、完工、验收、M1 写回、真实适配或主应用挂载，也不宣称完整报修流程可用。后续需要 C、B、A、D、F 按各自边界评审。
