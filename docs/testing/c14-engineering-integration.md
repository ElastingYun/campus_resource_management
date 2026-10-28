# C-14：统一工程接入验证（2026-10-28）

关联 [#14](https://github.com/ElastingYun/campus_resource_management/issues/14)、[前端对齐 #10](https://github.com/ElastingYun/campus_resource_management/issues/10)。执行者身份 wuyihao；AI 辅助实现与验证。人工业务确认、同行 Review 与合并尚待完成。

## 1. 本次验证边界

基于 D 已合入 main 的工程提交 a038472，接入 C 的认证/RBAC、审计、M2、宿主连接池、后台扫描和 Alembic。所有账号、资源、口令及业务记录均为合成测试数据；未操作真实学校账号、生产库或生产部署。
旧的 `001_c_foundation.sql` 与首次提交 80d68c9 逐字节一致。新增 0002 使用冻结校验和；不改写已应用历史，不自动执行破坏性降级。

## 2. 本地实际结果

| 项目 | 环境 / 命令 | 结果 |
| --- | --- | --- |
| 完整后端 | macOS arm64，Python 3.13.11，独立 PostgreSQL 16.2；`python -m pytest backend -q` | **86 passed, 1 warning in 15.49s**，退出 0；包含下述 CI 竞态回归修正 |
| 统一迁移 | 专用本地 PostgreSQL；在 backend 执行 `alembic upgrade head` 两次 | 均退出 0；head 为 0002_c_identity_approval |
| Ruff | `ruff check backend`；`ruff format --check backend` | All checks passed；37 files already formatted |
| 编译 / 依赖 | `python -m compileall -q backend/app backend/alembic`；`python -m pip --no-cache-dir check` | 均退出 0；No broken requirements found |
| 前端 | Node 22.23.4，锁文件原样；`npm ci`、`npm run build` | 安装成功，0 vulnerabilities；vue-tsc 和 Vite 8.3.5 构建通过 |
| Shell / diff | `bash -n infra/scripts/ci-smoke.sh`；`git diff --check` | 均退出 0 |
| 文档 / 冻结契约 | 临时文档检查脚本 | 8 份文档、34 个本地链接/锚点、14 项需求、20 项场景、原 SQL 与 OpenAPI 检查通过 |
| 本地 Compose | 本机无 Docker | **NOT RUN**；由远端 GitHub CI 验证，不能用语法检查替代 |
| 真实 A/B/E 联调 | 对方正式挂载与跨模块契约未验收 | **NOT RUN**；契约模拟不算真实服务写回 |

后端使用独立且确认 sys.prefix 与 sys.base_prefix 不同的 Python 3.13 临时环境，按统一 requirements-dev.txt 安装。PostgreSQL 由独立 Python 3.11 工具环境启动，测试进程实际使用 Python 3.13；每个 C 数据库用例创建并只清理自己的随机 schema。

复现时先配置专用测试数据库，设置 CAMPUS_DB_* 和 CAMPUS_TEST_POSTGRES=1；C 用例也接受 C_TEST_DATABASE_URL。示例命令不包含实际连接串：

```bash
cd backend
alembic upgrade head
alembic upgrade head
CAMPUS_TEST_POSTGRES=1 python -m pytest -q
ruff check .
ruff format --check .
```

本地 npm 全局镜像曾将官方 tarball 请求改写到镜像并返回 400。核对原锁文件指向的官方 tarball 完整性后，仅在执行命令上指定官方 registry 与临时 cache，再运行安装/构建；没有修改锁文件版本或全局 npm 设置。
保留 Starlette TestClient 关于 HTTPX 的 1 项弃用警告；没有过滤警告、弱化断言或删除旧测试。

## 3. 重点覆盖

- 登录、退出、过期、停用、实时权限、范围隔离、限流、授权非越权委派和审计隐私。
- 申请、多级审批、重复/并发决定、截止边界、自审策略、幂等冲突、服务端 actions 与审计事务。
- 持久 M1 操作、未知结果查询、租约/版本隔离、释放补偿、重试上限；独立进程 HTTP 契约测试仍明确使用模拟服务。
- 宿主 SQLAlchemy 连接池开启 pre_ping；C 事务归还连接后 SQLAlchemy 标量查询及原健康检查正常，重复启动/停止不泄露连接。
- 统一应用缺 C schema 时 ready=503、live=200；后台无需页面请求即可关闭到期申请，并处理持久 M1 工作。
- 空 schema / 旧 C 基线迁移、重复升级与账号数据保留；缺表或账本校验和不一致则失败且不覆盖用户，不留下部分迁移 stamp。
- 账号引导重复执行幂等，配置冲突拒绝，口令不输出；缺策略、非法布尔值、跨主机路径、异常凭据及过短租约拒绝。
- 发布的 OpenAPI 与真实路由、schema、Bearer、必需幂等头和错误结构一致。

## 4. 负对照：证明权限测试能发现破坏

命令：`python -m pytest backend/tests/c_module/test_approval.py::test_cross_scope_read_is_hidden -q`。

1. 原实现：1 passed，退出 0。
2. 临时将 Principal.covers 的真实资源范围判定替换为恒真：1 failed，退出 1；越权读取被测试发现。
3. 恢复原文件：1 passed，退出 0；当时完整回归 85 passed。补充下述竞态回归后最新完整结果为 86 passed。

测试本身与预期均未修改，破坏版本未提交。三个阶段的原始输出位于执行机器临时文件 `/private/tmp/c14-negative-control.log`，不作为长期仓库产物。

## 5. 远端 CI 与剩余验收

固定提交 2ff74573f05bae6fd67c2d285fef265af9a360e8 的 [GitHub run 40679996646](https://github.com/ElastingYun/campus_resource_management/actions/runs/40679996646) 已完成且三项均 success：Frontend typecheck and build、Backend checks and PostgreSQL、Compose build and recovery。此为 PR #22 分支的 push 运行，后续提交以各自 Checks 为准。
后续固定提交 cb6db61fd79ffdb512d86c2b2e649e66138e6cb1 的 [run 40680618016](https://github.com/ElastingYun/campus_resource_management/actions/runs/40680618016) 也三项 success：32 单元测试、53 PostgreSQL integration（均保留 1 项弃用警告）、前端构建、Compose 资产/登录/身份/授权列表代理和数据库中断/恢复。
远端实际执行 Linux / Python 3.13 / PostgreSQL 17 的检查、迁移及测试，以及镜像构建、Nginx 同源代理与断库恢复；本地的 Compose NOT RUN 记录保留。
Compose smoke 显式开启合成 C 配置，运行统一迁移及账号引导，分别经后端和前端代理检查登录、身份、授权列表，再执行数据库中断/恢复。它不调用真实 B/M1，不证明全链路预约生效。

仍须相关 owner Review 共享入口、依赖、迁移和代理；A/B/C/D/E 确认身份、资源可见范围、占用冲突、通知、远程审计及生产策略后再组织真实网络联调。main 合并与最终验收由人类成员完成。

PR 为 [#22](https://github.com/ElastingYun/campus_resource_management/pull/22)。main 合入 D 的 #12 后，仅 docs/development.md 出现文字冲突；负责人于当前会话明确确认“采用 main 的实际合并记录并保留 C 容器验证说明”。已在 44f28a0 同步 main e5e95e3 并落实该策略，代码/迁移没有冲突。此确认只针对冲突处理，不替代非作者 Review。
剩余交付分别在 [#23](https://github.com/ElastingYun/campus_resource_management/issues/23)（M1 协议/真实网络验收）、[#24](https://github.com/ElastingYun/campus_resource_management/issues/24)（资源可信身份/事务审计）、[#25](https://github.com/ElastingYun/campus_resource_management/issues/25)（通知投递）跟踪；C-01～C-06 已在 #10 回复。

## 6. CI 发现的扫描竞态测试修正

同一 f6e3b9b：PR [run 40681783241](https://github.com/ElastingYun/campus_resource_management/actions/runs/40681783241) 三项成功；push [run 40681773755](https://github.com/ElastingYun/campus_resource_management/actions/runs/40681773755) 的 PostgreSQL lane 为 52 passed、1 failed。没有以通过的另一轮掩盖失败。
失败为 test_approval_at_deadline_cannot_win_timeout 误要求首次超时扫描必处理 1 条。真实实现使用 FOR UPDATE SKIP LOCKED，审批事务持锁时扫描可合法跳过该行；审批因截止被拒绝、锁释放后应在下一轮恰好关闭一次。

保留截止后审批不得成功的断言，改为断言并发扫描与事务结束后再扫描总计恰好 1 次，并检查最终 TIMED_OUT/version=2、零决定、零 M1 操作、一次超时审计。另新增真实 PostgreSQL 持锁用例：持锁时必须跳过，释放后第一次扫描处理 1 条，之后 0 条，并核对业务事件也恰好一次。
不是只接受首次扫描 0 或 1 后结束；最终状态与副作用必须收敛，业务实现未改动。两个针对性用例连续运行 12 轮，共 24 次通过，随后全量 86 passed / 1 warning。

复现针对性命令（先配置专用真实测试库）：

```bash
python -m pytest backend/tests/c_module/test_approval.py::test_approval_at_deadline_cannot_win_timeout backend/tests/c_module/test_approval.py::test_deadline_scan_skips_locked_row_then_closes_it_once -q
```

最终提交的 push 与 PR 两轮 CI 均需检查，不能仅重跑碰运气或忽略失败检查。
