# C-14：统一工程接入验证（2026-10-28）

关联 [#14](https://github.com/ElastingYun/campus_resource_management/issues/14)、[前端对齐 #10](https://github.com/ElastingYun/campus_resource_management/issues/10)。执行者身份 wuyihao；AI 辅助实现与验证。人工业务确认、同行 Review 与合并尚待完成。

## 1. 本次验证边界

基于 D 已合入 main 的工程提交 a038472，接入 C 的认证/RBAC、审计、M2、宿主连接池、后台扫描和 Alembic。所有账号、资源、口令及业务记录均为合成测试数据；未操作真实学校账号、生产库或生产部署。
旧的 `001_c_foundation.sql` 与首次提交 80d68c9 逐字节一致。新增 0002 使用冻结校验和；不改写已应用历史，不自动执行破坏性降级。

## 2. 本地实际结果

| 项目 | 环境 / 命令 | 结果 |
| --- | --- | --- |
| 完整后端 | macOS arm64，Python 3.13.11，独立 PostgreSQL 16.2；`python -m pytest backend -q` | **85 passed, 1 warning in 18.48s**，退出 0 |
| 统一迁移 | 专用本地 PostgreSQL；在 backend 执行 `alembic upgrade head` 两次 | 均退出 0；head 为 0002_c_identity_approval |
| Ruff | `ruff check backend`；`ruff format --check backend` | All checks passed；37 files already formatted |
| 编译 / 依赖 | `python -m compileall -q backend/app backend/alembic`；`python -m pip --no-cache-dir check` | 均退出 0；No broken requirements found |
| 前端 | Node 22.23.4，锁文件原样；`npm ci`、`npm run build` | 安装成功，0 vulnerabilities；vue-tsc 和 Vite 8.3.5 构建通过 |
| Shell / diff | `bash -n infra/scripts/ci-smoke.sh`；`git diff --check` | 均退出 0 |
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
3. 恢复原文件：1 passed，退出 0；随后完整回归 85 passed。

测试本身与预期均未修改，破坏版本未提交。三个阶段的原始输出位于执行机器临时文件 `/private/tmp/c14-negative-control.log`，不作为长期仓库产物。

## 5. 远端 CI 与剩余验收

PR 创建后记录 GitHub 的实际运行链接及结果。当前本地结果不能代替 Linux / PostgreSQL 17、镜像构建、Nginx 同源代理与断库恢复证据。
Compose smoke 显式开启合成 C 配置，运行统一迁移及账号引导，分别经后端和前端代理检查登录、身份、授权列表，再执行数据库中断/恢复。它不调用真实 B/M1，不证明全链路预约生效。

仍须相关 owner Review 共享入口、依赖、迁移和代理；A/B/C/D/E 确认身份、资源可见范围、占用冲突、通知、远程审计及生产策略后再组织真实网络联调。main 合并与最终验收由人类成员完成。
