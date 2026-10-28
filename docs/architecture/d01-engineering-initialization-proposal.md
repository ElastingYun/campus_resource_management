# D 工程初始化提案

负责人：D（`jiadongchen666`）。日期：2026-10-28。关联：[Issue #4](https://github.com/ElastingYun/campus_resource_management/issues/4)、[个人开发计划](../d-development-plan.md)。

状态：工程提案，待团队评审。D-02/D-03 已获任务负责人授权，可先实现健康检查、构建、迁移基础与 CI；本提案中的业务拓扑、公共接口和共享数据模型仍须相关 owner 确认。合并本文只表示收录提案。

目标是让六位成员共用可复现的开发底座，保留模块所有权，并支持最终真实的跨模块网络演示。核心栈沿用 Vue 3、Python/FastAPI、PostgreSQL。范围不包含业务审批政策、云资源或生产部署。

实施进展分别见 [D-02 PR #8](https://github.com/ElastingYun/campus_resource_management/pull/8) 与 [D-03 PR #9](https://github.com/ElastingYun/campus_resource_management/pull/9)，具体检查与合并状态以对应 PR 为准。

## 当前基线与初始化边界

仓库已有模块目录、README、AGENTS 和 B-01 草案，尚无运行应用和 CI。B 的[需求](../requirements/b01-m1-ui-and-resources.md)、[资源接口](b01-resource-api-draft.md)、[验收计划](../testing/b01-acceptance-plan.md)是待评审输入。A 的计划位于 [PR #3](https://github.com/ElastingYun/campus_resource_management/pull/3)，不能当成已批准契约。

D 的本机检查结果为 Node 22.16.0、npm 10.9.2、Python 3.13.2，未发现 Docker、PostgreSQL 或 uv 命令。这是本机状态，不是团队环境约定；D-02/D-03 需用实际安装与 CI 验证候选基线。

## 工具与版本策略

| 项目 | 候选基线 | 选择理由与实施要求 |
| --- | --- | --- |
| Node 与包管理 | Node 22.x、npm | 与已有本机工具接近；实施时采用受支持分支的安全补丁，前端声明 engines，提交 package-lock.json，CI 使用 npm ci |
| 前端 | Vue 3、TypeScript、Vite、官方 Vue 插件 | 保持既定框架和类型检查；D-02 解析兼容版本并锁定，不额外引入 UI/状态管理框架 |
| Python | Python 3.13.x、venv/pip | 与本机主次版本一致；使用兼容安全补丁，隔离依赖；锁定直接与传递依赖 |
| 后端 | FastAPI、Uvicorn、Pydantic Settings | HTTP 服务、统一配置和输入验证；精确版本由 D-02 安装与测试后写入锁文件 |
| 数据库访问 | SQLAlchemy 2.x、psycopg 3.x、Alembic 1.x | 明确连接/事务生命周期与版本化迁移；初始化优先同步访问，降低统一底座复杂度 |
| 数据库 | PostgreSQL 17.x | 候选受支持主版本；容器锁定具体补丁版本或 digest，不使用 latest |
| 检查与测试 | pytest、HTTPX、Ruff；vue-tsc 与 Vite build | 验证 HTTP 行为、后端格式/静态检查和前端可构建性；页面行为测试随 D-04 接入 |
| 容器与 CI | Docker Compose v2、GitHub Actions | 本地服务编排与 PR 检查；D-03 验证实际工作流和容器启动 |

Node 22 仍列于官方 LTS 清单；Python 3.13 已进入安全维护；PostgreSQL 17 仍受支持。版本选择依据：[Node 发布状态](https://nodejs.org/en/about/previous-releases)、[Python 支持状态](https://devguide.python.org/versions/)、[PostgreSQL 版本政策](https://www.postgresql.org/support/versioning/)。状态会变化，实施及后续依赖升级时重新核对。

D-01 不承诺尚未解析的补丁号。D-02 的验收需包含实际版本、锁文件重装和兼容性结果；变更依赖必须连同锁文件更新，不由每位成员各选框架。

## 目标目录与文件影响

以下为 D-02/D-03 候选结构，新文件在实施 PR 中确认；现有 A/B/C/E/F 的业务目录保持其所有权。

```text
frontend/
  package.json, package-lock.json, tsconfig*.json, vite.config.ts
  src/main.ts, App.vue
  src/shared/                 # 通用 API Client 与基础组件
  src/modules/{m1-reservation,m2-approval,m3-repair}/
backend/
  requirements*.in, requirements*.txt
  app/main.py, config.py, database.py
  app/api/health.py
  app/common/                 # B/C/E 维护各自公共能力
  app/modules/                # A/C/E 维护各自业务
  alembic.ini, alembic/env.py, alembic/versions/
  tests/                      # 工程测试，业务测试按模块归属组织
infra/
  compose.yaml, backend.Dockerfile, frontend.Dockerfile
.env.example
.github/workflows/ci.yml
docs/development.md
```

根 README 的运行说明由实施 PR 更新为实际可复现步骤。初始化只建立无业务路由的应用入口和前端基础页面，不自动挂载未确认的业务 API。共享 API Client、鉴权、路由命名与时间格式须对齐后接入。

## 后端服务拓扑备选

| 方案 | 收益 | 成本和限制 |
| --- | --- | --- |
| 单进程模块化应用 | 启动简单、统一调试 | 不能单独满足最终真实跨模块网络调用要求；若过渡使用，必须另定服务拆分与网络验收任务 |
| 三个业务服务加公共服务 | M1/M2/M3 各自运行，资源/认证/审计/通知有统一服务边界 | 需确认公共服务归属、故障传播、身份传递及配置，不能把公共层全交给 D |
| 三个业务服务并分别承载公共能力 | 进程数较少，所有者与业务组接近 | 公共能力部署边界与代码归属易混淆，需明确哪些能力经网络暴露，避免跨服务直接读表 |

建议团队评审第二种方案：单仓库复用工程代码，业务通过 HTTP 交互，公共服务由 B/C/E 共同按所有权维护。服务数及公共能力放置由 A/B/C/E 与 D/F 确认后记录 ADR；本任务不创建四套后端框架，不引入消息队列或 Kubernetes。

在 ADR 确认前，D-02 只提供一个无业务路由的 bootstrap 应用用于健康检查、数据库连接和工程验证。这个入口不定义最终部署拓扑，也不能充当跨模块演示证据。后续服务可以复用同一配置与 app factory，运行实例仍须独立验证。

## 数据库连接与迁移

连接从环境变量读取，不提交真实 .env。SQLAlchemy 连接池由应用生命周期创建和释放，业务 session 每次请求独立；事务由业务服务明确提交/回滚，不在全局共享可变 session。数据库错误对客户端返回固定信息，避免泄露连接字符串。

D-02 建立 Alembic 环境和可从空库重放的基础迁移入口，不预建用户、教室、座位、申请或工单共享表；具体 schema 由 owner 提交评审。候选策略是单个 PostgreSQL 实例、版本化迁移统一集成；各服务的数据权限、schema 划分与迁移顺序在拓扑 ADR 中确定。

迁移作为独立命令执行，不在多个应用副本启动时竞争执行。已合并迁移不改写历史；并行成员新增迁移产生多个 head 时先协调合并迁移，不用覆盖别人的迁移解决。种子数据由业务 owner 维护，使用合成数据并验证幂等。

回滚应用前须核对数据库向后兼容性。禁止把自动降级 schema 或删除卷当成一般回滚方案，破坏性迁移需单独人工决策。

## 开发容器与基础接口

Compose 候选服务为 PostgreSQL、bootstrap 后端和前端；数据库持久卷只用于本地开发，端口默认绑定本机。配置示例不含真实凭据；开发环境启动所需的本地密码由使用者配置。数据库 ready 后运行一次迁移，再启动依赖它的应用。

候选基础接口：`GET /health/live` 表示 HTTP 进程存活；`GET /health/ready` 实际检查 PostgreSQL，连接失败返回 503，不伪装成功。它们只反映工程状态，不证明 M1/M2/M3 已可用。浏览器首页明确区分工程状态和未接入的业务功能。

前端经 Vite 开发代理或容器反向代理访问后端，浏览器不接触数据库凭据。后端受控 CORS，不能用任意来源和宽松权限冒充认证；认证由 C 接入。健康检查不返回 DSN、堆栈、身份信息或密钥。

## 计划中的运行与测试命令

以下是待 D-02 实现并验证的命令契约，当前 D-01 不能直接运行；文件名和参数以实施后 docs/development.md 为准。

| 目的 | 候选命令与目录 |
| --- | --- |
| 前端安装与开发 | frontend 中 `npm ci`、`npm run dev` |
| 前端检查与构建 | frontend 中 `npm run typecheck`、`npm run build` |
| 后端环境与安装 | backend 中 `python3 -m venv .venv`，随后使用 .venv 内 pip 安装锁定依赖 |
| 后端启动 | backend 中 `.venv/bin/python -m uvicorn app.main:app --reload` |
| 后端检查与测试 | backend 中 `.venv/bin/ruff check .`、`.venv/bin/ruff format --check .`、`.venv/bin/python -m pytest` |
| 迁移 | backend 中 `.venv/bin/alembic upgrade head`，数据库连接由环境提供 |
| 容器运行 | 根目录中 `docker compose --env-file .env -f infra/compose.yaml up --build` |
| 停止开发环境 | 同一 Compose 配置执行 down，保留数据卷；不把 down -v 放入常规步骤 |

## 基础 CI 与验收矩阵

D-03 在 PR 和分支推送上运行必要检查，使用 contents: read 权限，不接入生产密钥；避免使用具有额外权限的 pull_request_target 运行不可信代码。工作流的必要 action 锁定可核对的版本或提交，依赖按锁文件安装。CI 本身不等于 main 分支已配置保护。

| 检查 | 正常路径 | 失败或边界 | 完成证据 |
| --- | --- | --- | --- |
| 前端 | 干净 npm ci、类型检查、生产构建 | 非法类型或无法解析的导入导致失败 | 实际本机命令与 CI job |
| 后端 | 存活探针和真实 HTTP 响应 | 缺失/非法配置、未知路由、数据库不可达 | HTTP 层测试及错误脱敏断言 |
| PostgreSQL | 真实连接、空库迁移、重复 upgrade | 数据库不可用时 readiness 为 503；不能悄悄换 SQLite | PostgreSQL CI service 和迁移输出 |
| 容器 | 构建镜像、迁移后启动、代理及探针可访问 | 服务未就绪时检查失败；空必需配置被拒绝 | Compose smoke job 与实际日志摘要 |
| 测试有效性 | 恢复后的完整测试通过 | 隔离副本故意破坏一条健康检查行为，相关测试应失败 | 真实失败与恢复结果，不提交破坏代码 |

D-02/D-03 完成时写明本机与 CI 各自验证范围。本机未装 Docker 时，不能宣称本机容器已运行；可以由真实 GitHub runner 验证容器，并保留 run 链接。业务鉴权、并发预约和跨模块恢复由业务成员测试，不以基础检查代替。

## 待决事项与评审责任

| 编号 | 需要确定的事项 | 相关成员 | 对后续开发的影响 |
| --- | --- | --- | --- |
| D-OPEN-01 | 最终服务拓扑、公共能力归属、服务间认证 | A/B/C/E，D 提案，F 协调 | 业务服务实例与真实网络联调前必须形成 ADR |
| D-OPEN-02 | /api/v1 前缀、错误结构、标识类型、时间表示、幂等与重试 | A/B/C/E/D | 业务 API 和共享 Client 接入前确认；B 的候选路径不算定案 |
| D-OPEN-03 | 用户身份、角色、院系、CORS 来源和数据可见范围 | C，B/D/F 参与 | D-04 和主数据权限测试前确认 |
| D-OPEN-04 | M2 表单、审批层级、状态、撤销/超时与错误响应 | C/D，F 协调 | D-04 页面范围与真实契约确认后实现 |
| D-OPEN-05 | 已有预约冲突、M2 占用写回、维修叠加和失败补偿 | A/C/E，B/D/F 参与 | D-05 集成前确认，前端不自行处理事务 |
| D-OPEN-06 | schema 归属、共享引用、迁移命名及并行 head 协调 | A/B/C/E/D | 业务模型迁移前确认 |
| D-OPEN-07 | 云资源、测试/生产环境、域名、发布审批及回滚责任 | 全组和仓库管理员 | D-06 前确认；D-03 不部署生产 |

D 协调相关 owner 评审本提案，确认以真实人员、日期和结论记录在 Issue/ADR；不提前写成已一致通过。至少一名非作者完成文档 Review。实现任务分别关联 Issue 和 PR，保留 AI 参与、测试与人工验收记录。流程参考 [GitHub flow](https://docs.github.com/en/get-started/using-github/github-flow)。

## D01 验证范围

本 PR 只新增文档，计划执行本地链接、Markdown 结构和 git diff 空白检查。应用测试、前端构建、数据库迁移、容器、CI、部署均为 **NOT RUN**；实际执行结果随 D-01 PR 记录。没有 API、schema、权限或生产配置变更。
