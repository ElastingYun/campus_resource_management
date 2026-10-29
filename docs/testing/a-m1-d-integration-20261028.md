# A：M1 接入 D 工程脚手架的验证记录

记录日期：2026-10-28。本文只记录**实际执行过**的检查；没有执行的写在第 7 节。

## 1. 背景与决策

PR #18 是在 D 的脚手架合入 `main`（PR #8、#9、#12）之前开出来的，与 `main` 有 8 个文件冲突。即使没有冲突，它也过不了 D 的 CI：

- ruff 报 193 处问题，23 个文件需要重新格式化；
- M1 的测试都需要数据库，而 CI 的单元测试阶段没有数据库；
- 存在两条互不相连的迁移链；
- 配置方式与 D 不一致。

负责人 A 于 2026-10-28 选择方案 A：在 PR #18 的分支上合并 `main`，冲突文件一律采用 D 的版本，M1 在后续提交中适配。全部改动都追加在已推送的 `758a231` 之后，不改写已推送的历史。

## 2. 提交与每一步的结果

| # | 提交 | 本步测试 |
| --- | --- | --- |
| 1 | `style(m1): apply the team's ruff rules to M1 code` | 90 passed（合并前，分支原有依赖，PostgreSQL 16）；ruff 通过 |
| 2 | `Merge branch 'main' into feat/m1-d-bootstrap-integration` | 预期中的失败：`tests/conftest.py` 导入已被删除的临时 `AppConfig`，测试无法运行 |
| 3 | `refactor(m1): run M1 on D's app factory, settings and migration chain` | 102 passed，1 skipped（D 的集成测试需要 `CAMPUS_TEST_POSTGRES=1`）；ruff 通过 |
| 4 | `test(m1): mark PostgreSQL tests as integration for D's CI stages` | 单元阶段 29 passed；集成阶段 74 passed |
| 5 | `fix(m1): stop using Result.tuples(), deprecated in SQLAlchemy 2.1` | 103 passed；警告从 374 条降到 7 条 |
| 6 | `fix(m1): run the seed script as a module` | 104 passed |
| 7 | `docs(m1): update M1 docs for D's scaffold and record verification`（本文） | 仅文档 |

第 2 步合并时，以下冲突文件全部采用 D 的版本，内容与 `main` 逐字节一致：`backend/alembic.ini`、`backend/alembic/env.py`、`backend/alembic/script.py.mako`、`backend/app/config.py`、`backend/app/main.py`、`backend/requirements.txt`、`backend/requirements-dev.txt`、`backend/tests/test_health.py`。

## 3. 环境

| 用途 | 环境 |
| --- | --- |
| 逐步开发 | Python 3.12.11，用 D 的 `requirements-dev.txt` 安装依赖（FastAPI 0.162.0、SQLAlchemy 2.1.6、psycopg 3.3.6、Alembic 1.20.1、pytest 9.2.0、ruff 0.17.3）；PostgreSQL 16.15 |
| 与 CI 一致的复现 | D 在 Dockerfile 中锁定 digest 的 `python:3.13-slim-bookworm`（Python 3.13.18），以及 D 的 CI 中锁定 digest 的 `postgres:17-bookworm`（17.11）；依赖由 `requirements-dev.txt` 安装 |

仓库以只读方式挂进容器，所有命令都在容器内的副本上运行，不会写回仓库。

## 4. 复现 D 的 CI 后端 job

在最终提交上，按 `.github/workflows/ci.yml` 中 “Backend checks and PostgreSQL” 的步骤顺序执行，数据库为全新的 `campus_ci`，所有步骤都带着 CI 设置的 `CAMPUS_DB_*` 变量：

| 步骤 | 结果 |
| --- | --- |
| `ruff check .` | All checks passed，exit 0 |
| `ruff format --check .` | 57 files already formatted，exit 0 |
| `python -m pytest -m 'not integration'` | 29 passed，75 deselected，exit 0 |
| `alembic upgrade head`（第一次） | exit 0 |
| `alembic upgrade head`（第二次） | exit 0 |
| `alembic current` | `0006_m1_seat_restrictions (head)` |
| `CAMPUS_TEST_POSTGRES=1 python -m pytest -m integration` | 75 passed，29 deselected，exit 0 |

第 5 步之后，同样的步骤在 Python 3.12 + PostgreSQL 16 上也全部通过（当时集成测试为 74 个；第 6 步新增了种子命令测试）。

## 5. 容器烟测

在空库 `campus_smoke` 上执行 `alembic upgrade head` 和 `python -m scripts.seed`，然后用 D 的 Dockerfile 中的启动命令 `python -m uvicorn app.main:app` 启动服务，再通过真实 HTTP 调用：

| 配置 | 请求 | 结果 |
| --- | --- | --- |
| 默认配置（与 D 的 Compose 目前一致） | `GET /health/ready` | 200 `ready` / `connected` |
| 同上 | `GET /api/v1/m1/settings`（带开发请求头） | 401 `unauthenticated`：认证未接入，不接受任何身份 |
| `dev-headers` + 签到码密钥 | `GET /api/v1/m1/settings` | 200，`max_hours` 为 4 |
| 同上 | 搜索 LIB-101 带插座的可用座位 | 200，返回座位列表 |
| 同上 | 带 `Idempotency-Key` 预约 | 201 |
| 同上 | M3 写入整间教室维修限制 | 201 |
| 同上 | M3 以 `reason="completed"` 解除 | 422 `repair_acceptance_required` |
| 同上 | M3 以 `reason="accepted"` 解除 | 200 `released` |
| — | `python -m app.modules.m1_reservation.jobs` | 正常执行一轮 |

## 6. 测试有效性与开发中发现的问题

每次只破坏一处实现，确认对应测试失败，恢复后确认文件逐字节一致、测试重新通过：

| 破坏方式 | 结果 |
| --- | --- |
| 删掉 `app/main.py` 中挂载 M1 的那一行 | `test_wiring.py` 3 failed |
| 删掉“未配置数据库时返回 503”的检查 | `test_wiring.py` 1 failed |
| 让种子命令测试改用旧的 `python scripts/seed.py` | `test_seed.py` 1 failed |

开发中发现并处理的问题：

1. **`backend/pytest.ini` 会让 D 的测试配置失效。** pytest 发现 `pytest.ini` 后，就不再读取 `pyproject.toml` 中的 `[tool.pytest.ini_options]`，D 注册的 `integration` 标记和 `pythonpath` 设置都会被忽略，而且不报任何错误。这个文件是我之前的临时脚手架留下的，已在第 3 步删除。
2. **种子命令失效（我在第 3 步引入，容器烟测发现）。** 种子脚本改为读取 D 的 `Settings` 后需要导入 `app`，按文件路径运行时 Python 找不到这个包。原有测试是直接导入函数调用的，覆盖不到真实命令。第 6 步改为 `python -m scripts.seed`，并新增一个以独立进程运行该命令的测试。
3. **任务 CLI 的测试只检查输出文本。** 原测试只断言输出以 `JobReport(` 开头。现在改为先写入一条 20 分钟前开始、未签到的预约，再断言运行 CLI 后它确实变成了违约（no_show）。
4. **线程竞争测试会吞掉线程内的异常。** 第 1 步改用共享的 `run_together` 辅助函数后，竞争中的任一操作抛出异常都会让测试失败。这次没有为这三个竞争测试重做“故意破坏”检查，它们的有效性依据仍是 v1 记录中的检查。

## 7. 未执行（NOT RUN）

| 项目 | 原因 |
| --- | --- |
| GitHub Actions 的真实运行 | 本机不能推送；推送后以 PR #18 上的检查结果为准 |
| D 的 Compose 冒烟（`infra/scripts/ci-smoke.sh`） | 该脚本只允许在带 `GITHUB_RUN_ID` 的 CI 环境中运行；本机没有构建 Compose 镜像。第 5 节只是在 D 的 Python 镜像中直接运行同一条启动命令，不等同于 Compose 冒烟 |
| 前端 job | M1 这次没有改动前端 |
| 多实例任务进程并发、性能与连接池压测 | 未做 |
| 与 M2、M3 的真实网络联调 | 对方服务尚未接入 |

## 8. 需要其他成员确认

- **D**：
  - 评审我对 D 文件的四处改动：`app/main.py`、`app/database.py`、`alembic/env.py`、`.env.example`；
  - 决定 M1 任务进程是否加入 Compose；
  - 决定种子数据如何进入镜像；
  - 评估连接池 5 + 2、取连接最多等 3 秒，在抢座高峰期是否够用；
  - 参考：`alembic.ini` 缺少 `path_separator` 设置，会产生一条弃用警告。
- **B**：`rooms`/`seats` 的迁移目前只有 `0002_resources_placeholder` 在建，归属请 A/B/D 一起决定。
- **所有人**：M1 的迁移编号改过。本地已经执行过旧编号的开发库请删掉重建，不要手工修改 `alembic_version`。

## 9. AI 参与说明

本轮的代码修改、测试执行和本记录由 AI 编程助手（Claude Code）完成。方案 A 和冲突处理原则由负责人 A 决定。合并 PR 前还需要非作者成员进行人工 Review。
