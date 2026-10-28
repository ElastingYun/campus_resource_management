# Backend (FastAPI + PostgreSQL)

> **临时脚手架（作者：A）。** 统一后端工程由 D 负责；本目录是 A 为开发 M1 先搭的最小工程，依赖版本、目录和命令均待 D 评审后确认或替换。

## 本地运行

需要 Python 3.12 和一个 PostgreSQL 16（M1 使用排他约束和 advisory lock，SQLite 不能代替）。

```bash
cd backend
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt

# 一个只供本地使用的 PostgreSQL
docker run -d --name crm-pg -e POSTGRES_USER=campus -e POSTGRES_PASSWORD=campus \
    -e POSTGRES_DB=campus -p 127.0.0.1:5432:5432 postgres:16-alpine

cp .env.example .env            # 不要提交 .env
set -a && . ./.env && set +a

alembic upgrade head            # 从空库迁移到最新版本
python scripts/seed.py          # 合成教室/座位，可重复执行
uvicorn app.main:create_app --factory --reload
```

- 健康检查：`GET http://127.0.0.1:8000/api/health`
- 接口文档：`http://127.0.0.1:8000/docs`；契约见 [`docs/architecture/a-m1-api-v1.md`](../docs/architecture/a-m1-api-v1.md)
- 提醒/违约任务：`python -m app.modules.m1_reservation.jobs --loop 60`

`AUTH_MODE=dev-headers` 时，用 `X-Dev-User-Id`、`X-Dev-Department`、`X-Dev-Permissions` 请求头扮演用户。这只是 C 的认证接入前的开发手段，**测试/生产环境不得开启**；默认值 `disabled` 会拒绝所有受保护接口。

## 测试

```bash
docker run -d --name crm-test-pg -e POSTGRES_USER=m1 -e POSTGRES_PASSWORD=m1test \
    -p 127.0.0.1:56432:5432 postgres:16-alpine
export TEST_DATABASE_URL=postgresql+psycopg://m1:m1test@127.0.0.1:56432/m1
python -m pytest -q
```

测试会为每次运行新建一个 `crm_test_*` 数据库，从空库执行全部迁移，结束后删除。未设置 `TEST_DATABASE_URL` 时数据库测试会**失败**而不是跳过，避免“什么都没测却显示通过”。

## 目录

| 路径 | 内容 | 负责人 |
| --- | --- | --- |
| `app/main.py`、`app/config.py`、`app/db.py` | 应用工厂、配置、数据库会话（临时） | D 评审 |
| `app/common/resources/` | 教室/座位主数据**占位模型**，M1 只读 | B 评审/接管 |
| `app/modules/m1_reservation/` | M1 全部业务代码 | A |
| `alembic/versions/` | 版本化迁移：0001 主数据占位，0002–0005 M1 | 各自 owner |
| `../database/seeds/` | 幂等的合成种子数据 | B/D 评审 |
| `tests/` | 健康检查、迁移重放、种子幂等；`tests/m1/` 为 M1 | A |
