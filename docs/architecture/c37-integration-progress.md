# C-37：整教室占用处理进度

负责人 C / Wuyh11，日期2026-10-29。关联 [#37](https://github.com/ElastingYun/campus_resource_management/issues/37)、真实M1依赖 [#23](https://github.com/ElastingYun/campus_resource_management/issues/23)。这是C已有持久操作的只读诊断，不批准外部冲突或人工重试政策。

## 1. 接口与可见范围

`GET /api/v1/m2/applications/{application_id}/integration` 使用C Bearer身份，复用申请详情的对象可见规则：本人、当前获授权审批人，或具备对应教室m2.read_all范围的人可读；匿名401，不存在或不可见404。
没有额外默认角色或全域权限。读取不会触发M1、重试、状态修改或新增成功业务审计。响应no-store，机器契约同步于[C-v1 OpenAPI](c-v1-openapi.json)。

合成响应：

```json
{
  "application_id": "00000000-0000-4000-8000-000000000010",
  "version": 4,
  "generation": 1,
  "integration_status": "APPLY_UNKNOWN",
  "effective": false,
  "operations": [{
    "id": "00000000-0000-4000-8000-000000000020",
    "generation": 1,
    "kind": "APPLY",
    "state": "ATTENTION",
    "attempts": 3,
    "error_code": "RETRY_LIMIT"
  }]
}
```

只有6项操作字段：id、generation、kind、state、attempts、error_code。没有payload、租约令牌、租约时间、服务凭据、源请求内容或远端异常消息。未产生M1意图时generation=0、operations为空数组；历史按generation/id排序。

## 2. 状态的解释

| 操作state | C本地事实 | 不可推断 |
| --- | --- | --- |
| PENDING | 等待后台领取 | 远端已生效 |
| RUNNING | 已被领取、可能在执行或等待租约恢复 | 远端一定收到或完成 |
| UNKNOWN | 结果未确认，后台按同一操作标识查询/恢复 | 失败未写入，或已成功 |
| DONE | 该操作得到匹配的占用/释放确认 | 其他不可用原因已消失 |
| CONFLICT | 占用操作得到明确冲突 | 已取消个人预约或决定后续业务去向 |
| ATTENTION | 重试预算耗尽，C自动重试已停止 | 可强制成功、无条件释放或重建操作 |

error_code当前为null、REMOTE_UNCONFIRMED或RETRY_LIMIT，仅是C保存的机器码。attempts是持久领取次数，含崩溃后恢复领取，不等于远端实际写入次数。
根generation表示当前业务意图，历史操作可能属于旧代次；不能拿旧APPLY的DONE覆盖新撤销意图。effective严格复用申请的规则，不因查询、UNKNOWN或ATTENTION变为true。

**version是申请版本，不是整个诊断视图的ETag。** 领取、重试和转ATTENTION可能不修改申请version；消费者每次刷新要实际GET本接口，不用“申请版本没变”跳过诊断请求。接口暂不提供人工重新入队或强制修改状态。

## 3. 一致性与审计

申请和操作通过同一条PostgreSQL SQL聚合读取，使用同一语句快照。并发撤销时只会得到原代次或新代次的完整事实，避免先读旧申请、后读到新操作的混合视图。版本检查仍按原写接口执行，此查询不提供锁定承诺。

重试耗尽的m1.attention审计从C自有申请取得真实room_id，沿用audit.read与教室范围过滤；其他教室或无审计权限者仍不可读。重复扫描不重复产生ATTENTION审计；诊断查询也不会补造审计。
该修复影响新产生的重试耗尽审计；历史room_id缺失的记录继续按原规则可见，不推断归属或回填历史数据。

没有迁移、新依赖、工作流改动或对A/B私有表的访问；原冻结SQL字节不变。新增接口为兼容的C-v1能力，既有申请响应保持原样，请D Review消费与展示语义。

## 4. 验证与证据

真实PostgreSQL新增9项用例：空操作且读取无副作用；PENDING/RUNNING/确认成功及冲突；UNKNOWN→ATTENTION且申请版本不变；重试耗尽审计范围；本人/审批人/范围外；匿名/未知ID；并发撤销和20次读取的代次一致性。公开OpenAPI与实际接口一起验证。
针对性命令 `python -m pytest backend/tests/c_module/test_integration_progress.py backend/tests/c_module/test_api_contract.py -q`：**10 passed, 1 warning in3.56s**。

完整固定B-v2/C回归 `python -m pytest -q`：**176 passed, 1 warning in25.73s**，本地Python3.13.11/PostgreSQL16.2；保留既有TestClient/HTTPX弃用警告。包含先前认证竞态修复、B/C事务审计与独立TCP回归，C和组合代码均通过Ruff/格式。

负对照仅修改 `/private/tmp/c37-combined` 的隔离C副本，临时绕过本端点的对象范围检查：`test_integration_progress_visibility[outsider-404]` 原实现1通过→破坏后1失败（200而非404）→逐字节恢复后1通过。原始记录为临时 `/private/tmp/c37-negative-control.log`；仓库未提交破坏实现。

目标Python3.13/PostgreSQL17及Engineering/C-B实际CI以本增量PR Checks为准，完成后补链接。M1为明确的测试契约依赖，真实A服务仍由#23验收；本接口不是实际M1网络联调的替代。AI辅助实现/测试，非作者Review与最终合并由人类决定。

交付 [PR #39](https://github.com/ElastingYun/campus_resource_management/pull/39)。固定1800570的 [C/B push40798264920](https://github.com/ElastingYun/campus_resource_management/actions/runs/40798264920)、[C/B PR40798373136](https://github.com/ElastingYun/campus_resource_management/actions/runs/40798373136)、[Engineering push40798265014](https://github.com/ElastingYun/campus_resource_management/actions/runs/40798265014)、[Engineering PR40798373122](https://github.com/ElastingYun/campus_resource_management/actions/runs/40798373122) 均success。后续提交按各自Checks核对。
