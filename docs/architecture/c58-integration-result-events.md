# C-58：占用结果的本地业务事件

关联 #58、#25。审批过程已有application.submitted/approve/reject/timed_out/revoked事件，但M1确认结果原先只有申请状态和操作审计。本增量补齐C本地业务事件，供后续通知投递读取；不新增通知平台、接收端或收件政策。

## 记录时点

| 内部事件类型 | 触发事实 | 不代表 |
| --- | --- | --- |
| application.occupancy_confirmed | 当前代次的APPLY被确认，申请转APPLIED | 仅审批通过或远端请求已发出 |
| application.occupancy_conflict | 当前代次APPLY得到明确CONFLICT，申请转APPLY_CONFLICT | 个人预约被取消、审批历史被驳回 |
| application.occupancy_released | 当前代次RELEASE被确认，申请转RELEASED | 其他审批、个人预约或维修限制已经消失 |

事件只在真实本地状态转换时写入c_business_events，与申请版本更新、操作结果及审计同事务。事件使用更新后的申请version，保存操作标识及generation；重复扫描/查询、租约旧返回或旧业务代次都不重复记录当前结果。

UNKNOWN、PENDING和重试次数变化不产生确认事件。响应丢失后，沿原operation_id查询确认才记录一次。若本地事务失败，申请/操作结果/事件/审计一起回滚；领取记录仍可按原租约恢复，同操作查询后重建唯一已提交事件，不重新生成远端操作。

## 存储与兼容

沿用既有表：id、application_id、type、payload、occurred_at。抽出C模块内record_business_event供service与worker共用，原服务事件的类型与4个payload字段保持原样。新结果事件payload为：

```json
{
  "application_id": "00000000-0000-4000-8000-000000000001",
  "version": 4,
  "review_status": "PASSED",
  "integration_status": "APPLIED",
  "operation_id": "00000000-0000-4000-8000-000000000002",
  "generation": 1
}
```

不复制用途、审批意见、身份联系方式、服务凭据或远端错误。没有修改冻结迁移、表、公开HTTP、角色/权限、运行依赖、工作流或其他模块代码。事件类型是C内部事实，不是已获E批准的通知线协议，也不是“已发送”回执。

## 验收与后续

真实PostgreSQL测试覆盖成功/冲突、来源释放、丢响应查询恢复、释放先完成而旧成功响应晚到、真实审计约束错误导致的整体回滚和租约后恢复。M1依赖是明确的契约夹具，真实A服务仍在#23验收；E接收/查询、收件规则和实际通知发送仍在#25，不把本地事件当作已送达。

具体结果见[C-58验证记录](../testing/c58-integration-result-events.md)。AI辅助实现和验证，按课程小组项目范围推进；正常非作者Review后由人决定合并。
