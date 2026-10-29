# C-40：教室资格与真实 B 网络验证

业务决策见[版本记录](../decisions/c-20261029-m2-conflict-and-room-visibility.md)，配置与边界见[C-40 说明](../architecture/c40-approved-room-policy.md)。日期2026-10-29，关联 #40/#24/#23。

## 环境与来源

本地 Python3.13.11、专用 PostgreSQL16.2。统一锁文件没有变化。固定 B v2 `45bcf2be8fbc7cee5f97b75aec4be7d061d5ff8a` 的公开资源模块/测试，由 `backend/tests/c_module/prepare_resource_acceptance.py` 核对 Git blob 并复制到 `/private/tmp/c40-combined-round1`；C 来自当前增量工作树，manifest 保存逐文件 SHA256。没有把 B 产品代码或表带入 C 分支。

连接变量只注入隔离测试进程，不输出数据库连接串。C 各用例和 B/C 资源用例使用随机私有 schema；测试可以显式建资源夹具表，产品启动不建表或默认发权限。迁移仍为原有 0001→0002，冻结 SQL 未改。

## 实际执行

```bash
python backend/tests/c_module/prepare_resource_acceptance.py \
  --source /private/tmp/c24-b-source-45bcf2b \
  --output /private/tmp/c40-combined-round1
# 以下在组合目录运行，预先注入隔离 PostgreSQL 变量。
CAMPUS_REQUIRE_RESOURCE_ACCEPTANCE=1 python -m pytest \
  backend/tests/c_module/test_room_policy.py \
  backend/tests/c_module/test_resource_integration.py::test_two_process_approved_qualification_uses_real_b_http_without_student_admin_grant -q
# 在组合目录的 backend/ 中运行全量。
CAMPUS_REQUIRE_RESOURCE_ACCEPTANCE=1 CAMPUS_TEST_POSTGRES=1 python -m pytest -q
```

定向 **25 passed, 1 warning in4.22s**；固定 B/C 完整回归 **201 passed, 1 warning in30.63s**。警告为既有 TestClient/HTTPX 弃用提示，未新增依赖来绕过。日志保存在本机 `/private/tmp/c40-targeted.log`、`/private/tmp/c40-full-regression.log`。

24项新增资格用例覆盖campus/本院系/他院系/停用、非法或缺失元数据、campus显式null与缺字段区别、配置冲突、新键重新校验与原键恢复回执。HTTP边界用例的MockTransport只模拟公开资源响应，M2真实业务及数据库没有被Mock；独立网络用例另外使用实际B实现。

新增双进程用例启动独立 B 资源进程和 C 审批进程，由 C 的资源客户端实际跨 TCP GET B 的教室详情。验证大整数ID和campus null、本院系可提交；他院系403、停用409、缺失404；普通申请人直接读B管理列表403；教室停用后新键拒绝、原键恢复；后端服务会话退出后C返回503；最终只有两条申请、零M1操作。生产服务账号政策未由此测试批准。

## 测试有效性

仅修改隔离副本 `room_policy.py`，临时把准入判断变成所有enabled教室可提交。4项真实PG API用例原实现 **4 passed** → 破坏后 **1 failed, 3 passed**（他院系错误201而非403）→ 逐字节恢复 **4 passed**。本机记录 `/private/tmp/c40-negative-control.log`；仓库未提交破坏版本或弱化断言。

C独立分支在backend/执行 `CAMPUS_TEST_POSTGRES=1 python -m pytest -q`：**147 passed, 1 skipped, 1 warning in24.28s**，未设置CAMPUS_REQUIRE_RESOURCE_ACCEPTANCE，跳过项为未安装B模块；日志 `/private/tmp/c40-standalone-regression.log`。专用组合CI要求B存在，不能静默跳过。

Ruff、格式46文件和diff检查通过。目标Python3.13/PostgreSQL17、前端构建与Compose结果以本增量PR实际Checks为准，完成后补链接。本机Docker **NOT RUN**；普通选择列表、D浏览器、A实际占用冲突与E通知仍待各owner，不能用本次测试替代。AI辅助实现和验证，非作者Review/最终合并由人决定。
