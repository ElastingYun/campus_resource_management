# B02 教室与座位管理验证记录

日期：2026-10-28。负责人 B / hrzhao7；关联 [Issue #19](https://github.com/ElastingYun/campus_resource_management/issues/19)，实现范围及接入限制见 [模块说明](../architecture/b02-resource-management.md)。

## 本机实际执行

macOS arm64。临时 Python 虚拟环境为 Python 3.12.14，前端使用 bundled Node 24.19.0，依赖均按仓库锁文件安装，未更改版本或新增依赖。这不是项目约定 Python 3.13 / Node 22 的本机验证；目标版本、PostgreSQL 和 Compose 由本 PR 原有 Engineering CI 实际检查。

| 命令/场景 | 本机结果 |
| --- | --- |
| frontend：npm ci | 安装通过，提示本机 Node 超出 engines 约定；保留提示，不修改 engines 绕过 |
| frontend：npm run test | 34 passed：D 原型 9 项，B 页面/HTTP 适配 25 项 |
| frontend：npm run build | vue-tsc 类型检查及 Vite 生产构建通过 |
| backend：ruff check . | 通过 |
| backend：ruff format --check . | 通过 |
| backend：python -m pytest -m 'not integration' -q | 29 passed、3 deselected：含 B 的 23 项单元场景；真实数据库测试未在本机运行 |
| 后端依赖一致性 | pip check：No broken requirements found |
| Git 差异和文档链接 | 提交前差异空白、相对链接及新增文件范围检查通过；无生成文件或凭据 |

保留当前 FastAPI/Starlette TestClient 对 HTTPX 的一条弃用警告，未屏蔽或削弱测试。尝试安装匹配运行时和 PostgreSQL 的下载未完成，已中止，不据此声称本机具备 PostgreSQL 或 Docker。

## 验证覆盖

- 后端：真实 HTTP 请求 → schema → 权限 → SQL 数据访问 → 跨请求读取；创建/编辑、修订检测、全局/限定资源范围、唯一约束、父教室引用、分页/字面量筛选、无效输入与禁止字段、BIGINT 无损序列化、缺失依赖拒绝、审计失败回滚及错误脱敏。
- SQLite 内存库仅用于隔离单元测试，不冒充 PostgreSQL 或 D 的 readiness。SQL 引用映射不在应用启动时建表。
- 前端：新增/编辑教室和座位、插座筛选、空态、表单校验、失败保留输入、在途重复提交、结果未知阻止重复写、旧座位响应不覆盖新教室、编辑时固定上下文、未配置模式禁用写入和未知错误脱敏。
- HTTP 测试 Mock 最底层 fetch/Response，不 Mock 被测 adapter；响应经字段校验后才可报成功，跨教室座位响应被拒绝，写入异常不自动重试。页面 gateway 替身是测试边界，不是真实业务联调证据。

## 测试有效性

只在 `/private/tmp` 后端副本关闭 revision 比较，执行 `tests/resources/test_resources.py::test_stale_update_and_immutable_fields`，得到 **1 failed**：期望 409，实际 200。恢复副本原文后同一命令 **1 passed**。仓库实现未被破坏。

## 浏览器检查

在本机 Vite `/#resources-prototype` 实际新增 `QA-101` 合成教室和 `QA-SEAT-01` 固定插座座位，页面显示保存成功和新记录。切到 `/#resources` 后显示服务未接入，新增按钮禁用、列表没有合成记录。此次浏览器操作只发生在明确的内存演示模式。

## 真实 PostgreSQL 与 CI

新增两个 integration 测试：数据库读写/约束/修订往返，以及两个并发 HTTP 编辑只有一个成功、另一个返回 409。它们仅在 `CAMPUS_TEST_POSTGRES=1` 且有显式数据库配置时执行，在 UUID 命名的私有 schema 内建表并清理自己的 schema，不改共享 rooms/seats 表。

现有 CI 使用 Python 3.13、Node 22、PostgreSQL 17，并保留 D 的健康检查、空库/重复迁移及 Compose 恢复检查。CI 实际 run/commit 和结果以本 PR Checks 为准；未跑完前不标记通过。测试私有 schema 的成功不证明 A 的共享迁移、C 的真实认证/审计、M1/M2 联调或生产部署已完成。

**NOT RUN / 待接入**：C 正式身份与权限映射、真实审计、共享资源表迁移/应用挂载、浏览器真实持久化、M1/M2 网络联调、生产部署与回滚。需要 A/C/D 的 owner 确认及非作者 Review。
