# 本地开发与工程验收

本说明覆盖 D-02 的 bootstrap 工程：Vue 基础首页、FastAPI 工程探针、PostgreSQL 连接与 Alembic 基础版本。M1/M2/M3 业务、登录和最终服务拓扑尚未接入。工程提案见 [D-01 PR #5](https://github.com/ElastingYun/campus_resource_management/pull/5)；D-02 对应 [Issue #6](https://github.com/ElastingYun/campus_resource_management/issues/6)。

## 前置条件与配置

使用 Node 22（至少 22.12）、npm、Python 3.13。容器方式需要 Docker Engine/Desktop 和 Compose v2。镜像在 Dockerfile/Compose 中按 digest 锁定，依赖的实际版本见 frontend/package-lock.json、backend/requirements.txt 与 requirements-dev.txt。

在仓库根目录复制示例文件，并在本地 .env 中替换示例密码；不要提交 .env。密码以独立环境变量传递，特殊字符不需要拼接成数据库 URL。所有命令中的数据库均应是隔离的开发库。

```sh
cp .env.example .env
```

变量为 CAMPUS_DB_HOST、CAMPUS_DB_PORT、CAMPUS_DB_NAME、CAMPUS_DB_USER、CAMPUS_DB_PASSWORD。缺少 host 或 password 时，进程可以存活但 readiness 返回 503；非法端口等配置直接拒绝启动。客户端只收到固定的工程状态，不暴露连接信息。

## 用容器启动全部工程服务

以下命令在仓库根目录执行。首次运行会下载基础镜像并构建应用；Compose 等待数据库就绪、执行一次迁移，再启动后端和前端。

```sh
docker compose --env-file .env -f infra/compose.yaml up --build -d --wait
curl --fail http://127.0.0.1:8000/health/live
curl --fail http://127.0.0.1:8000/health/ready
curl --fail http://127.0.0.1:8080/health/ready
```

浏览器打开 http://127.0.0.1:8080。数据库、后端和前端端口仅绑定本机。开发用数据库账号具有初始化权限；生产的最小权限账号和迁移角色另行设计。

```sh
docker compose --env-file .env -f infra/compose.yaml logs --tail=100
docker compose --env-file .env -f infra/compose.yaml down
```

down 保留数据库卷，不在普通清理命令中添加 -v。已有卷的密码不会随 .env 修改自动更新；如遇认证失败，应先确认使用的开发库和配置，不能删除数据来掩盖问题。

## 本机运行后端

需要可连接的真实 PostgreSQL 17。可以只启动 Compose 中的数据库，或使用自己准备的隔离数据库；启动数据库不等于迁移完成。

```sh
docker compose --env-file .env -f infra/compose.yaml up -d db --wait
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/alembic upgrade head
.venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Windows 使用 .venv/Scripts 中对应命令。应用从根 .env 读取配置，环境变量优先。若本机 Python 的 CA 链未配置完整，使用操作系统的有效 CA bundle（例如 macOS 上 pip 的 --cert /etc/ssl/cert.pem）；不要关闭 TLS 验证。

数据库未配置时也可启动后端，/health/live 返回 200，/health/ready 返回 503。配置后数据库不可达，同样返回 503，不能用 SQLite 或固定成功响应替代。readiness 只检查数据库连接，不检查所有业务表或最终服务拓扑。

## 本机运行前端

另开终端，在 frontend 目录执行：

```sh
npm ci
npm run dev
```

浏览器打开 http://127.0.0.1:5173；Vite 将 /health 代理到本机 8000。容器方式前端使用 Nginx 代理。页面不含真实业务记录，各模块均标记未接入；状态失败时可以重新检查。后端端口变化时应同步修改开发代理配置。

## 检查与自动化测试

```sh
cd backend
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m pytest -m 'not integration'
```

配置和 HTTP 测试覆盖：非法端口、密码脱敏、特殊字符、无数据库配置、数据库不可达、存活与就绪分离，以及未实现的业务路由返回 404。测试数据库失败使用本机不可用端口，不 Mock 被测路由。

以下命令只针对已准备的隔离 PostgreSQL 测试库；先在环境中设置连接变量，避免误指向共享或生产数据。集成测试通过环境变量读取数据库配置，不从 .env 读取；本机可在 shell 中显式设置与开发配置一致的 CAMPUS_DB_* 值。

```sh
.venv/bin/alembic upgrade head
.venv/bin/alembic upgrade head
CAMPUS_TEST_POSTGRES=1 .venv/bin/python -m pytest -m integration
```

重复 upgrade 验证已应用版本不会重复执行。初始迁移只建立 0001_bootstrap 版本历史，不包含用户、资源或审批业务表。业务迁移由各 owner 提交，不覆盖已合并版本；出现多个 head 时先协调迁移顺序。

前端检查在 frontend 中执行：

```sh
npm ci
npm run typecheck
npm run build
```

Vue 页面行为测试随 D-04 加入；类型检查和构建不能证明申请/审批流程正确。D-03 的 Engineering CI 提供真实 PostgreSQL 和容器检查，分支保护仍需仓库管理员设置。

## 依赖更新与模块接入

前端以 package-lock.json 为准，不删除锁文件规避兼容问题。初始化发现 TypeScript 7 与当前 vue-tsc 不兼容，因此使用经实际构建验证的 TypeScript 5.9.3；升级时同时验证 Vue 工具链。

Python 运行依赖在 requirements.in，开发依赖在 requirements-dev.in，锁文件包含传递依赖。重新生成需安装 pip-tools 7.6.2，在 backend 中执行：

```sh
.venv/bin/pip-compile --strip-extras --no-emit-index-url --output-file requirements.txt requirements.in
.venv/bin/pip-compile --strip-extras --no-emit-index-url --constraint requirements.txt --output-file requirements-dev.txt requirements-dev.in
```

A/C/E 在自己的业务目录实现服务，B/C/E 分别维护主数据、认证审计、通知。bootstrap 不自动挂载业务路由；接入前确认版本化 API、身份权限、共享模型和独立运行边界，最终跨模块演示须走真实网络。D-04 先与 C 对齐 M2/身份契约，与 B 对齐资源数据，M2→M1 写回与 A/C 对齐。

## 验证记录

D-02 PR 列出本机实际执行的命令与结果。本机最初未安装 Docker/PostgreSQL，容器及真实数据库验收由 D-03 runner 提供，不能提前标为通过。未配置的业务、生产发布和回滚不属于初始化完成范围。

## GitHub Actions 检查

[D-03 Issue #7](https://github.com/ElastingYun/campus_resource_management/issues/7) 对应 .github/workflows/ci.yml。push 和 pull_request 触发三个独立 job：

- Frontend typecheck and build：npm ci、vue-tsc 和生产构建。
- Backend checks and PostgreSQL：Ruff、6 个基础测试、真实 PostgreSQL 17 空库迁移/重复迁移、数据库与迁移 head 集成测试。
- Compose build and recovery：实际构建镜像，等待迁移及服务就绪，检查静态资源/后端/代理；停止数据库验证 503 与存活分离，恢复后验证 readiness。

infra/scripts/ci-smoke.sh 仅允许在带 GITHUB_RUN_ID 的隔离 CI 环境运行。它清理自己命名的临时项目及卷；开发者日常停止服务仍使用前文的普通 down，不删卷。

工作流仅请求 contents: read，checkout 不保留推送凭据；没有生产 secrets、自动合并或部署。检查状态名称固定，管理员在 main 保护规则中要求这些检查和非作者审核后才构成强制门禁。

D-03 PR 基于 D-02 分支，仅评审 CI 增量。先由人工评审并合并 D-02，再将 D-03 的目标分支改为 main 并重新检查后合并；不以依赖 PR 绕过审核。实测记录见 [D03 工程验证记录](testing/d03-quality-verification.md)。
