# D03 工程验证记录

日期：2026-10-28。负责人：D（jiadongchen666）。关联：[D-02 Issue #6](https://github.com/ElastingYun/campus_resource_management/issues/6)、[D-03 Issue #7](https://github.com/ElastingYun/campus_resource_management/issues/7)。

## 本机实际检查

环境：macOS arm64，Node 22.16.0、npm 10.9.2、Python 3.13.2。应用依赖由锁文件安装，本机没有 Docker 引擎和 PostgreSQL。

| 命令或检查 | 实际结果 |
| --- | --- |
| frontend 中 npm ci 与 npm run build | 通过，含 vue-tsc 类型检查和 Vite 生产构建 |
| backend Ruff check、format --check | 通过，11 个 Python 文件格式一致 |
| python -m pytest backend -m 'not integration' | 6 passed、1 deselected；真实 PostgreSQL 测试留给 runner |
| pip check | No broken requirements found |
| 真实 HTTP 与 Vite 代理 | /health/live 为 200；未配置数据库时后端与代理 /health/ready 均为 503 |
| 浏览器首页 | 基础布局与“数据库尚未就绪”提示已检查；业务模块明确未接入 |
| Compose YAML、服务依赖及文档链接 | 静态检查通过；不能替代容器运行 |

当前 Starlette TestClient 对 HTTPX 兼容层给出一条弃用提示，未过滤或屏蔽，测试通过。前端首次安装的 TypeScript 7 与 vue-tsc 不兼容，已固定为经实际构建验证的 5.9.3。

## 测试有效性演示

只在 /private/tmp 的后端副本修改 /health/live 响应，将 alive 改为 broken_for_test；执行 tests/test_health.py 后得到 1 failed、1 passed，失败断言准确指出状态差异。恢复副本后相同命令得到 2 passed。仓库工作分支没有包含破坏代码，完整后端基础测试另行通过。

## GitHub runner 实际结果

首次实现提交 `8dbf527fb86377b83900edcf785aa17f8b782fc2` 对应 [PR CI run 40629917925](https://github.com/ElastingYun/campus_resource_management/actions/runs/40629917925)，三个 job 均为 success：

| Job | 实际结果 |
| --- | --- |
| Frontend typecheck and build | 干净安装、类型检查和生产构建通过 |
| Backend checks and PostgreSQL | Ruff、6 个基础测试、真实 PostgreSQL 空库迁移和重复升级、1 个数据库/迁移版本集成测试通过 |
| Compose build and recovery | 镜像实际构建、迁移后启动、前端静态资源、后端/代理 readiness、数据库中断时 503 与存活分离、恢复后 readiness 均通过 |

这些结果来自 Linux GitHub runner，不表示本机已安装或运行 Docker/PostgreSQL。后续提交的最新检查状态以 PR 为准；本记录保留首次实现的固定提交与 run，避免把不同版本的结果混用。

## 人工验收与边界

PR #8 已由 ElastingYun 于 2026-10-28 批准，D-02/D-03 经该 PR 进入 main；[主线 CI run 40652887035](https://github.com/ElastingYun/campus_resource_management/actions/runs/40652887035) 成功。main 标记 protected，具体必过规则仍由管理员核对。最终业务拓扑/契约和生产部署尚待后续决策。框架验证不证明业务鉴权、并发预约、审批补偿或跨模块状态恢复正确；这些属于后续模块与集成任务。所有测试数据和 CI 密码均为隔离环境的合成值。
