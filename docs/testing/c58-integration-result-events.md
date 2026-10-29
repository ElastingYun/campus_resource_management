# C-58：占用结果事件验证

日期2026-10-29，关联 #58/#25；base为C #57/fc98160。行为说明见[C-58](../architecture/c58-integration-result-events.md)。本地Python3.13.11、专用临时PostgreSQL16.2，沿用统一锁。

## 实际测试

```bash
# 已注入隔离C_TEST_DATABASE_URL，在仓库运行。
python -m pytest backend/tests/c_module/test_integration_events.py \
  backend/tests/c_module/test_worker.py -q
```

结果 **15 passed, 1 warning in9.06s**，含6项新增结果事件用例和9项原worker回归；记录 `/private/tmp/c58-targeted-corrected.log`。首次新增测试误用了event_type/created_at，冻结表实际为type/occurred_at；当时6 failed/9 passed，已按原schema修正查询，未修改历史迁移或产品字段。

新增用例检查：

- APPLIED/CONFLICT各仅一条事件，审批仍PASSED，effective符合实际结果；原提交事件的4字段不变。
- 释放确认后仅本来源被移除，其他来源保留；重复处理没有第二条事件。
- 远端已处理但响应丢失时无确认事件，按原操作查询后只记录一次且不重复execute。
- 暂停旧APPLY成功响应，在实际数据库中提交撤销并确认RELEASE，再放回旧响应；只记录新释放事实，不产生迟到的当前成功事件。
- 仅在私有测试schema给审计表加真实CHECK约束注入失败；申请状态/版本、事件与操作回写全部回滚，已领取操作保留RUNNING。移除测试约束、租约到期后查询原操作恢复，只有一次结果事件与一次远端执行。

测试未Mock被测service/worker；等待只发生在明确的M1契约夹具响应边界，事务故障为真实PostgreSQL约束错误，不是伪造成功回执。

固定B #48/4ee2fe5公开模块和当前C仍由准备器逐文件核对后投影到 `/private/tmp/c58-combined`。在组合backend/运行 `CAMPUS_TEST_POSTGRES=1 CAMPUS_REQUIRE_RESOURCE_ACCEPTANCE=1 python -m pytest -q`：**266 passed, 1 warning in42.75s，无skip**，记录 `/private/tmp/c58-full-regression.log`。既有TestClient/HTTPX弃用提示保留。

仅在 `/private/tmp/c58-negative` 关闭worker的结果事件写入：成功/冲突两项 **2 passed → 2 failed**（事件0而非1）→逐字节恢复 **2 passed**，记录 `/private/tmp/c58-negative-control.log`。状态转换仍执行，故可证明测试确实检查事件持久化，未提交破坏实现或降低断言。

交付 [PR #59](https://github.com/ElastingYun/campus_resource_management/pull/59)。固定0a65222的 [Engineering push40828037008](https://github.com/ElastingYun/campus_resource_management/actions/runs/40828037008)、[Engineering PR40828121859](https://github.com/ElastingYun/campus_resource_management/actions/runs/40828121859)、[C/B push40828037058](https://github.com/ElastingYun/campus_resource_management/actions/runs/40828037058)、[C/B PR40828121857](https://github.com/ElastingYun/campus_resource_management/actions/runs/40828121857) 四轮共8项全部success，包含目标PG17回归、前端构建和Compose构建/断库恢复。后续提交按其实际Checks核对。

产品没有新增Schema/迁移、HTTP、运行依赖或工作流，原C冻结SQL不变。本机Docker NOT RUN；A实际网络、E通知和D页面仍分别验收。
