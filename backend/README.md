# Backend：M1 补充说明

环境准备、启动、检查和 CI 的通用说明见 D 的 [docs/development.md](../docs/development.md)。本文只补充 M1 特有的配置和命令。M1 的接口与对接方式见 [docs/a-m1-handbook.md](../docs/a-m1-handbook.md)。

## M1 配置

写在仓库根目录的 `.env` 里（示例见 `.env.example` 末尾），环境变量优先于 `.env`：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `CAMPUS_M1_TIMEZONE` | `Asia/Shanghai` | 业务时区，用于整点预约、开放时间和每日签到码 |
| `CAMPUS_M1_AUTH_MODE` | `disabled` | `disabled` 时所有受保护的 M1 接口返回 401；`dev-headers` 时用 `X-Dev-User-Id`、`X-Dev-Department`、`X-Dev-Permissions` 请求头扮演用户。后者**只能在本机开发时使用**，测试和生产环境不得开启 |
| `CAMPUS_M1_CHECKIN_CODE_SECRET` | 未设置 | 用于生成每日签到码。未设置时签到接口返回 503。请使用随机值，不要提交到仓库 |

数据库连接使用 D 的 `CAMPUS_DB_*`。未配置数据库时，M1 接口返回 503 `database_unavailable`。

## 命令

在 `backend/` 下执行：

```bash
alembic upgrade head                                   # 0001_bootstrap → 0006_m1_seat_restrictions
python -m scripts.seed                                 # 合成教室和座位，可重复执行
python -m app.modules.m1_reservation.jobs --loop 60    # 提醒与违约任务（常驻进程）
python -m pytest -m 'not integration'                  # 不需要数据库
CAMPUS_TEST_POSTGRES=1 python -m pytest -m integration # 需要 PostgreSQL，账号要有建库权限
```

- 种子脚本要用 `python -m scripts.seed` 运行。写成 `python scripts/seed.py` 时，Python 找不到 `app` 包。
- 集成测试会为每次运行新建一个 `crm_test_*` 数据库，从空库执行全部迁移，结束后删除。D 的就绪测试还要求 `CAMPUS_DB_NAME` 指向的库已经迁移到最新版本，所以要先执行 `alembic upgrade head`。
- 没有设置 `CAMPUS_TEST_POSTGRES=1` 时，数据库测试显示为 skipped（跳过），不会显示为通过。

## 目录

| 路径 | 内容 | 负责人 |
| --- | --- | --- |
| `app/main.py`、`app/config.py`、`app/database.py` | D 的应用工厂、配置和引擎；M1 挂载一行，共享 ORM `Base` | D |
| `app/common/resources/` | 教室和座位主数据的**占位模型**，M1 只读 | 待 A/B/D 决定 |
| `app/modules/m1_reservation/` | M1 全部业务代码 | A |
| `alembic/versions/` | `0001` 由 D 建立起点；`0002` 是主数据占位；`0003–0006` 属于 M1 | 各自 owner |
| `../database/seeds/` | 幂等的合成种子数据 | 待 B/D 决定 |
| `tests/m1/` 及 `tests/test_migrations.py`、`tests/test_seed.py` | M1 测试与迁移、种子测试 | A |
