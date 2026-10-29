# Campus Resource Management

> 校园资源服务平台 · 软件过程管理与工程伦理课程实践项目（2026–2027 秋季学期）

本仓库由 6 名成员共同维护，以自习座位预约为核心，覆盖整教室预约审批与物业报修工单，并建设身份权限、空间资源、通知与审计等公共能力。

本项目的交付目标不仅是可运行的软件，还包括**可追踪的需求、可审查的 AI 协作过程、可验证的业务行为，以及可复现的构建、部署与回滚**。项目规则和工程过程记录与代码一同接受版本管理。

## 当前开发状态

以下状态以 2026-10-29 的 [`main` 提交 `1e663e9`](https://github.com/ElastingYun/campus_resource_management/commit/1e663e92d582241efcab764cd3ae60011563a092) 为准。**代码或 PR 已合并，不等于主应用已挂载该模块，更不等于跨模块网络联调已完成。**

| 区域 | 当前已进入 `main` 的内容 | 尚未完成的接入 |
| --- | --- | --- |
| 工程与测试 | Vue 3 / TypeScript / Vite、FastAPI、PostgreSQL 17、Alembic、Compose；前端 Vitest、后端 pytest、Ruff 和 GitHub Actions 已运行 | 自动部署、生产发布与回滚尚未启用 |
| A / M1 后端 | [PR #18](https://github.com/ElastingYun/campus_resource_management/pull/18) 已合并：搜索、预约、签到、提醒/违约任务、历史、运营与整室限制接口；`app.main` 已挂载 M1 路由 | 正式身份、通知发送、后台任务部署及 M2/M3 的真实网络写回仍待对接；默认受保护接口不接受开发请求头 |
| B / 资源与 M1 前端 | 资源接口、教室/座位管理、座位查询、预约/本人记录/运营组件代码已入仓；主前端入口可打开资源管理与座位查询，也可查看合成原型 | 资源后端尚未挂到主应用；预约、本人记录与运营组件尚未接入主入口；真实会话与 A 接口联调待验收 |
| C/D / M2 与身份 | M2 前端工作台及独立的 C-v1 网络验收工作流已入仓；后者使用固定 C/B 服务源码 | 当前 `app.main` 未挂载 M2/正式认证；C 的[统一工程 PR #22](https://github.com/ElastingYun/campus_resource_management/pull/22)及[M2→M1 联调 #23](https://github.com/ElastingYun/campus_resource_management/issues/23)仍在进行 |
| E/F / M3 | 工单创建/本人查询、派单及开工前确认整室下架的代码和迁移已入仓；[F 的页面规划](https://github.com/ElastingYun/campus_resource_management/pull/77)已合并 | M3 路由尚未挂到主应用；真实 M1 写回/验收恢复与 F 的[本人报修客户端 PR #82](https://github.com/ElastingYun/campus_resource_management/pull/82)仍待接入 |

[`main` 的 Engineering CI](https://github.com/ElastingYun/campus_resource_management/actions/runs/40857820890) 在上述提交上完成前端测试与构建、后端 PostgreSQL 检查、Compose 构建与恢复；[C-v1 网络验收工作流](https://github.com/ElastingYun/campus_resource_management/actions/runs/40857821061)使用固定的外部 C/B 代码运行，不能作为主应用已挂载 C 服务的证据。有关未决接口和状态，以各模块 Issue、PR 及[集成跟踪表](docs/testing/f-integration-tracker.md)为准。

## 1. 项目范围

| 模块 | 业务边界 | 核心功能 |
| --- | --- | --- |
| **M1 — 自习座位预约** | 学生座位使用与状态管理 | 教室/座位筛选、分时预约、冲突检查、签到、提醒与违约、预约历史、运营查询 |
| **M2 — 整教室预约与审批** | 整教室申请及审批 | 申请提交、身份/角色门槛、多级审批、通过/驳回、超时撤销、预约占用协调 |
| **M3 — 物业报修工单** | 空间故障及维修流程 | 故障上报、派单、维修状态、超时升级、完工验收、评价与座位下架协调 |
| **D — 公共服务层** | 跨模块基础能力 | 认证与 RBAC 权限、教室/座位主数据、通知、操作审计 |

### 1.1 M1 的重要业务约束

课程任务书规定，M1 需要支持按整点小时预约，单次默认最多 **4 小时**（参数可调）；签到使用与教室关联的动态编码或二维码；预约前 **15 分钟**提醒，开始后 **10 分钟**未签到再次提醒，开始后 **15 分钟**仍未签到则自动取消、释放座位并记录违约。还需支持院系自习室准入限制、插座标记、预约历史与运营管理。

> 上述为需求边界；已交付的 M1 后端行为及尚未接入的链路见“当前开发状态”。更细的行为、异常场景和验收标准以 `docs/requirements/` 及团队确认的决策为准。

### 1.2 必须完成的跨模块链路

| 链路 | 触发事件 | M1 应产生的效果 |
| --- | --- | --- |
| **M2 → M1** | 整教室申请审批通过 | 对应时段内该室全部座位不可接受个人预约；驳回或超时撤销时按规则回滚占用 |
| **M3 → M1** | 自习室存在“维修中”工单 | 该室全部座位从可预约列表下架；工单**验收通过**后恢复可用性 |
| **M1 状态追溯** | 任一座位占用/下架/释放 | 可追溯变更来源：M1 自身预约、M2 审批占用、M3 报修下架 |

跨模块更改必须遵循**公开接口契约**，不允许某个模块绕过接口直接修改另一个模块拥有的数据。恢复座位时也必须重新检查是否存在其他有效占用或下架原因，避免错误释放。具体冲突优先级、幂等性和失败补偿规则应由团队确认。M2 遇到已有个人预约时拒绝整室占用的政策已明确，但 A/C 的原子处理、可信服务身份与终态保护仍在 [Issue #23](https://github.com/ElastingYun/campus_resource_management/issues/23) 中对齐。

课程期末要求展示**真实的跨模块网络调用**，因此服务的运行边界必须能够支持该演示；后端最终拆分为几个运行服务，需由架构决策记录（ADR）确定。单仓库不等于必须单进程。

## 2. 技术栈

| 层次 | 技术 | 状态 |
| --- | --- | --- |
| 前端 | **Vue 3** | 已确认 |
| 后端 | **Python + FastAPI** | 已确认 |
| 数据库 | **PostgreSQL** | 已确认 |
| 前端工程化 | TypeScript + Vite | 已锁定版本并接入主前端工程 |
| Python ORM / 数据迁移 | SQLAlchemy + Alembic | 主线已有 D、M1、M3 的版本化迁移；C 汇合迁移待接入 |
| 自动化测试 | pytest、Vitest；另有 Playwright 验收用例 | 主线 CI 执行前端测试、后端测试与数据库迁移；浏览器验收按对应工作流核对 |
| 容器化 | Docker + Docker Compose | 开发配置与 CI 冒烟已接入 |
| CI/CD | GitHub Actions | 工程与 C-v1 网络检查已配置；生产部署未启用 |
| 运行环境 | 华为云 ECS（课程代金券） | 拟采用，资源规格及环境隔离方案待确认 |

**开发原则：** 保持 Monorepo（单仓库）；按业务模块明确代码所有权；尽量共享经过评审的工程约定，而不是由 6 个 AI Agent 各自创建一套框架。

## 3. 六人分工与代码所有权

本项目共 6 人，分为 3 个模块组，每组 2 人。A–F 是本仓库沿用的课程分工标记；具体任务负责人以对应 Issue / PR 为准。

| 成员 | 主要职责 | 主要负责目录 | 跨模块/公共职责 |
| --- | --- | --- | --- |
| **A（M1 后端）** | 座位搜索与预约接口、冲突检查、签到、违约/状态来源 | `backend/app/modules/m1_reservation/` | 参与 M1 对外状态接口设计 |
| **B（M1 前端）** | 座位搜索、预约、签到、历史及管理页面 | `frontend/src/modules/m1-reservation/` | `backend/app/common/resources/`：教室/座位等主数据 |
| **C（M2 后端）** | 整教室申请、多级审批、超时撤销 | `backend/app/modules/m2_approval/` | `backend/app/common/auth/`、`audit/`：认证、RBAC、审计 |
| **D（M2 前端/DevOps）** | 教室申请/审批页面；统一项目初始化 | `frontend/src/modules/m2-approval/`、`infra/` | `.github/workflows/`：CI/CD、部署、发布与回滚 |
| **E（M3 后端）** | 报修、派单、维修、升级、验收接口 | `backend/app/modules/m3_repair/` | `backend/app/common/notifications/`：公共通知及发送记录 |
| **F（M3 前端/集成）** | 报修、工单、验收评价页面 | `frontend/src/modules/m3-repair/`、`docs/` | 组织需求追踪、跨模块联调、风险清单与 Review |

**重要约定：** “负责人”负责组织、实现和验收，并不意味着其他成员不能贡献。每位成员都要编写/验证自己负责代码的测试，维护相关需求和开发记录。各模块负责其数据库迁移脚本，D 负责接入统一迁移流水线。**A、C、E** 共同确认跨模块接口，**F** 组织集成验证。公共层拆分方案及权责权衡，必须形成书面 ADR。

## 4. 仓库组织（目录骨架）

> 以下为 `main` 的主要目录摘要；有代码的模块不一定已经挂到主应用，仍为空的目录继续用 `.gitkeep` 占位。最终服务拓扑与跨模块接口须经相关负责人评审。

```text
campus_resource_management/
├── frontend/                         # Vue 3 前端
│   └── src/
│       ├── modules/
│       │   ├── m1-reservation/        # B：资源、查询、预约、本人记录、运营组件
│       │   ├── m2-approval/           # D：申请/审批工作台与状态展示
│       │   └── m3-repair/             # F：页面仍待接入
│       └── shared/                   # 通用组件、API 客户端、类型
├── backend/                          # FastAPI 后端
│   ├── app/
│   │   ├── modules/
│   │   │   ├── m1_reservation/        # A：业务路由已挂载
│   │   │   ├── m2_approval/           # C：主线仍为空目录
│   │   │   ├── m3_repair/             # E：工单/派单/开工代码，路由未挂载
│   │   │   └── resources/             # B：资源接口代码，路由未挂载
│   │   └── common/
│   │       ├── resources/             # B
│   │       ├── auth/                  # C
│   │       ├── audit/                 # C
│   │       └── notifications/         # E
│   ├── alembic/                      # D/M1/M3 迁移；C 汇合仍待接入
│   └── tests/                        # 单元/接口/跨模块集成测试
├── database/                         # 种子数据与数据库说明
├── infra/                            # Docker、运行环境及部署脚本（D）
├── docs/
│   ├── requirements/                 # M1、M2、M3、D 需求基线
│   ├── architecture/                 # 模块边界、系统拓扑、API 契约
│   ├── decisions/                    # ADR：技术/公共层/关键业务决策
│   ├── testing/                      # 测试策略与验收证据
│   └── risks.md                      # 规划中，尚未创建：风险及工程伦理跟踪
├── .github/
│   └── workflows/                    # 工程 CI 与独立 C-v1 网络验收
├── README.md
├── AGENTS.md                         # 全部 Coding Agent 的项目级规则
└── .gitignore
```

目录树省略了占位用的 `.gitkeep` 文件。`backend/alembic/versions/` 已含 `0001_bootstrap`、M1 的 `0002–0006` 及 M3 的 `e02/e03`；C 的共享迁移接入仍由 [Issue #61](https://github.com/ElastingYun/campus_resource_management/issues/61) 跟踪。`.github/workflows/ci.yml` 执行构建、测试、真实数据库与容器检查；自动部署、生产发布尚未启用。`.gitignore` 排除本地环境文件、依赖、缓存与构建产物，允许提交只含安全示例的 `.env.example`。

共享目录和跨模块文件的修改必须通知对应负责人；涉及公共层、schema 或 API 契约的 PR，须安排受影响模块成员参与 Review。

## 5. 开发方式：AI 编码，人类负责决策与验收

六位成员均可使用 Claude Code、Codex 等 AI Coding Agent 编写代码；**AI 生成的代码必须由人负责验收**。统一遵循根目录 [`AGENTS.md`](AGENTS.md)。

**跨工具加载约定**：Codex 会读取适用的 `AGENTS.md`；较新版本的 Claude Code 在项目中没有其他项目级 `CLAUDE.md` 时也可读取 `AGENTS.md`。若组员使用的 Claude Code 版本或设置无法自动加载，需在仓库根目录创建仅包含 `@AGENTS.md` 的 `CLAUDE.md` 作为兼容入口（不得维护两份互相冲突的规则）。每位成员开始开发前应确认工具确实载入了规则。

每项任务的标准闭环：

1. **需求与 Issue**：写清任务范围、输入/输出、前置依赖、验收标准及负责人。
2. **AI 提案**：Agent 先读取项目规范和相关需求，提交实现计划；负责人确认后才动手。
3. **独立分支实现**：小批量编码，连同测试、必要迁移和文档提交。
4. **人工验证**：负责人运行相关测试、检查 `git diff`、手工检查关键业务行为，并识别 AI 生成代码的风险。
5. **Pull Request**：关联 Issue，记录方案与关键取舍、变更、测试命令和结果。
6. **同行评审与合并**：至少一名**非作者**评审者通过后再合并；冲突由人决策，不由 Agent 擅自合并。

建议分支名 `feat/m1-seat-search`、`feat/m2-approval-flow`、`fix/m3-ticket-state`、`docs/team-roles`；提交说明采用 `feat(m1): ...`、`fix(m2): ...`、`test(m3): ...`、`docs: ...` 等清晰格式。

仓库管理员应设置 `main` 分支规则：通过 PR 合并、要求审核、在 CI 可用后将必要检查设为必过；功能开发不得直接推送 `main`。

### 新成员开始开发

```bash
# 将仓库克隆到本地（需先安装 Git）
git clone https://github.com/ElastingYun/campus_resource_management.git
cd campus_resource_management

# 更新基线并新建功能分支
git switch main
git pull --ff-only
git switch -c feat/m1-seat-search
```

按自己领取的 Issue 选择分支名称。完成修改并人工验证后，执行 `git add`、`git commit`、`git push -u origin <branch>`，再在 GitHub 创建 PR。**不要把以上示例分支名当作所有人共享的开发分支。**

### 运行与测试

D-02 的工程启动方式仍适用；主线已挂载 M1 后端，资源/M2/M3 的实现状态见本文开头的状态表。工程探针成功只表示基础服务和数据库可用，不代表业务接口或跨模块链路通过验收。工程配置和启动步骤见 [本地开发与工程验收](docs/development.md)，M1 的专用配置、种子与任务命令见 [后端补充说明](backend/README.md)。`docs/development.md` 保留 D-02 初始化时的业务状态描述，当前交付状态以本页为准。

安装 Docker 和 Compose v2 后，可在仓库根目录运行（先替换 .env 中的本地示例密码）：

```sh
cp .env.example .env
docker compose --env-file .env -f infra/compose.yaml up --build -d --wait
```

浏览器打开 http://127.0.0.1:8080。首页可进入座位查询、资源管理及 M2 工作台；`#seat-search-prototype`、`#resources-prototype`、`#m2-prototype` 使用合成数据。默认真实前端适配器尚未全部接线；M1 受保护接口默认拒绝开发请求头，不能把页面演示当作正式业务联调。也可按开发说明用 Node 22、Python 3.13 在本机分别运行前后端。数据库未配置/不可达时 readiness 返回 503，存活探针仍可验证进程。实际 CI 证据见上方运行记录；生产发布与回滚尚未启用。

## 6. 第一次 Review：范围与完成判据

课程首次 Review 侧重**过程规范和第一轮可运行成果**，而非全部功能完成。需能够展示：

| 必备内容 | 推荐证据 |
| --- | --- |
| 项目启动、模块认领、公共层归属 | 团队分工文件；公共层 ADR 及一致性决策记录 |
| **需求基线** | 各模块需求、验收标准及需求→Issue→PR→测试的追踪关系 |
| **任务拆分与依赖** | GitHub Issues/Project、负责人、任务依赖 |
| **架构与第一轮功能** | 架构说明、API 契约、可以现场运行的最小业务流程 |
| **AI 协作规范** | `AGENTS.md`、代表性任务的 AI 提案与人工验收记录 |
| **风险识别** | `docs/risks.md`：业务、质量、安全、伦理及进度风险 |
| **版本管理过程** | 分阶段 Commit、可审查 PR、Review 与真实测试结果 |

第二次 Review 的重点将进一步包括主功能和跨模块链路、完整集成测试、自动 schema 迁移及从提交到部署的可演示流水线。期末需能展示从干净环境部署、自动构建测试、数据库演进、生产发布与回滚、真实跨模块网络调用。

## 7. 质量、安全与工程伦理

- **业务正确性**：并发抢座不可双重占用；审批/维修不得绕过座位限制；恢复状态不能误释放其他有效占用。
- **可验证性**：测试必须验证真实行为，不允许仅断言常量、空分支或 Mock 掉被测逻辑；必要时通过故意破坏实现来验证测试能失败。
- **数据演进**：schema 只能通过有版本的迁移脚本变更；从空库能够重放到最新版；种子数据幂等并与业务数据分离；禁止人工修改线上表结构。
- **安全与隐私**：遵循最小权限；不得向仓库提交密钥、凭证、`.env`、生产数据、真实学生个人信息或 SSH 私钥；演示只使用合成或脱敏数据。
- **透明与责任**：在 PR 中记载 AI 的参与范围、人工检查结果、已知限制及风险，保留真正做过的测试证据，不伪造结果。
- **伦理跟踪**：持续记录学生隐私、公平预约、自动违约处理、管理员权力边界、故障处理责任和 AI 代码责任等实际问题，供个人课程论文引用。

## 8. 决策状态与后续工作

**已经落地**：六人三组的职责方向；Vue 3 / FastAPI / PostgreSQL 的工程与 CI；M1 后端、资源与部分前端、M2 前端、M3 工单基础代码和迁移。具体可运行边界以本文“当前开发状态”为准。

**仍需实现或确认**：C 的主线认证/M2 接入与 A/C 迁移汇合；M2→M1、M3→M1 的可信网络写回和失败恢复；资源所有权与通知实际发送；M3 前端入口；正式服务拓扑、生产环境隔离与发布回滚。部分政策已在 Issue 中作出决定，但相应代码及跨模块验收仍需完成。

下一轮优先对齐 [#23 M2→M1 占用协议](https://github.com/ElastingYun/campus_resource_management/issues/23)、[#61 A/C 迁移汇合](https://github.com/ElastingYun/campus_resource_management/issues/61) 与 [#73 M3 整室维修限制确认](https://github.com/ElastingYun/campus_resource_management/issues/73)；B/D/E/F 按各自 Issue 继续推进前端、主数据、部署与网络验收。

> **附加项说明**：课程提供了“自然语言会话驱动的业务代理”作为附加项目，建议在核心业务、接口和工程验收稳定后再规划；如实现，应通过各模块公开 API 操作真实业务，不得直接读取或修改其他模块内部数据。
