# A：M1 后端需求基线与暂定决策 v1

状态：**Draft / 待团队评审。** 第 2 节的需求来自课程任务书；第 3 节是第一版代码为能运行而选的**暂定**行为，团队确认或否决后，再按需求变更修改代码和测试。

关联：[接口契约](../architecture/a-m1-api-v1.md)、[验证记录](../testing/a-m1-v1-verification.md)、[A 的开发计划](../a-m1-development-guide.md)、[B 的需求草案](b01-m1-ui-and-resources.md)。

## 1. 范围

本版实现 M1 后端的搜索、预约、取消、签到、提醒与违约、历史、运营查询、参数管理，以及接收 M2/M3 写回的接口。不包含：前端（B）、认证和 RBAC 配置（C）、通知发送（E）、部署和 CI（D）、M2/M3 自身业务。

## 2. 需求追踪

“测试”列指 `backend/tests/` 下的文件。每条需求都在[验证记录](../testing/a-m1-v1-verification.md)第 4 节做过“故意破坏实现 → 测试失败”的检查，或在表中注明未做。

| 编号 | 需求（来源：任务书） | 实现 | 测试 | 状态 |
| --- | --- | --- | --- | --- |
| A-REQ-01 | 按整点小时预约 | `timeslots.make_slot` | `m1/test_timeslots.py`、`m1/test_reservations_api.py` | 已实现 |
| A-REQ-02 | 单次最多 4 小时，系统参数可调 | `settings.M1Settings.max_hours`、`PUT /settings` | `test_timeslots.py`、`test_ops_and_settings.py` | 已实现 |
| A-REQ-03 | 同一座位重叠时段不可重复预约，包括并发 | 应用层检查 + 座位 advisory lock + GiST 排他约束（迁移 0002） | `m1/test_concurrency.py` | 已实现 |
| A-REQ-04 | 签到：录入与教室关联、每天变化的编码（或扫二维码） | `checkin.py`：HMAC(密钥, 教室, 日期) 生成 6 位码 | `m1/test_checkin.py` | 已实现；二维码图片由前端生成 |
| A-REQ-05 | 开始前 15 分钟提醒 | `jobs._pre_start_reminders` → 通知出口 | `m1/test_jobs.py` | 已实现；实际发送依赖 E |
| A-REQ-06 | 开始后 10 分钟未签到再次提醒 | `jobs._late_reminders` | `test_jobs.py` | 已实现；实际发送依赖 E |
| A-REQ-07 | 开始后 15 分钟未签到：取消、释放座位、提醒、记一次违约 | `jobs._no_shows` | `test_jobs.py` | 已实现 |
| A-REQ-08 | 院系自习室只对本院系开放 | `availability.static_blockers` | `test_availability_api.py`、`test_reservations_api.py` | 已实现；院系身份来自 C |
| A-REQ-09 | 按条件搜索座位，插座座位可作为条件 | `GET /seats/availability`（`outlet_type`、`has_outlet`） | `test_availability_api.py` | 已实现 |
| A-REQ-10 | 查看历史预约并再次预约该座位 | `GET /reservations/me`；再次预约走普通创建并重新校验 | `test_reservations_api.py` | 已实现；“再次预约”入口在前端 |
| A-REQ-11 | 运营管理：查看预约情况 | `GET /ops/usage` | `test_ops_and_settings.py` | 已实现（仅汇总） |
| A-REQ-12 | M2 审批通过：该室预约时段全部座位不接受个人预约；驳回/撤销后回滚 | `restrictions.apply/release`（`m2_approval`） | `m1/test_restrictions.py` | M1 侧已实现；需与 C 联调 |
| A-REQ-13 | M3 维修中：该室全部座位下架；验收通过后恢复 | `restrictions.apply/release`（`m3_repair`） | `test_restrictions.py` | M1 侧已实现；需与 E 联调 |
| A-REQ-14 | 座位状态记录写入来源（M1/M2/M3），供追溯与验收 | `m1_seat_state_events`（迁移 0003），`GET /ops/seat-events` | `test_restrictions.py`、`test_ops_and_settings.py` | 已实现 |
| A-REQ-15 | 多个原因叠加时不误恢复 | 每个来源单独一行，解除只改这一行 | `test_restrictions.py` | 已实现 |
| A-REQ-16 | schema 以版本化迁移交付，可从空库重放 | `alembic/versions/0002–0006`，接在 D 的 `0001_bootstrap` 之后 | `test_migrations.py` | 已实现；已接入 D 的 CI（迁移执行两次，再跑集成测试） |
| A-REQ-17 | 种子数据脚本化、幂等、与业务数据分离 | `database/seeds/`、`python -m scripts.seed` | `test_seed.py`（包括以独立进程运行该命令） | 已实现（只有合成教室/座位）；还没进后端镜像 |

## 3. v1 的暂定决策（待确认）

以下规则任务书没有规定，但代码需要一个确定行为才能运行。全部可以改；标“影响公平/处罚”的，按 AGENTS.md 第 4.3 节须团队评估伦理影响后确认。

| 编号 | 决策点 | v1 暂定行为 | 理由 | 需确认 |
| --- | --- | --- | --- | --- |
| D-01 | 业务时区与时间格式 | `Asia/Shanghai`；无时区输入按本地时间解释 | 学校在上海；前端不必处理偏移 | A/B/D |
| D-02 | 可提前预约的范围 | 只能预约尚未开始的时段，最多提前 7 天（参数可调） | 防止长期占座 | A/F **（影响公平）** |
| D-03 | 同一学生同时段持有多个座位 | 不允许（`user_overlap`） | 一人不能同时坐两个座位；防止囤座 | A/C/F **（影响公平）** |
| D-04 | 跨日预约 | 不允许；必须在教室当天开放时间内 | 教室按天开放 | A/B |
| D-05 | 主动取消 | 只能在开始前取消待签到预约，不记违约 | 鼓励尽早释放 | A/C/F **（影响处罚）** |
| D-06 | 签到窗口 | 开始前 15 分钟到开始后 15 分钟（不含第 15 分钟整）；第 15 分钟整起由任务判为违约 | 与自动取消的时间点衔接，没有空档也没有重叠 | A/B/C |
| D-07 | 新审批/报修与已有个人预约重叠 | 不自动取消，只在 `affected_reservation_ids` 中返回给调用方 | 取消学生预约是政策决定，不应由代码默认 | A/C/E/F **（影响公平）** |
| D-08 | 维修或审批占用期间未签到 | 取消预约但**不记违约**（`cancel_reason=restricted`），条件是该限制在预约开始时仍有效 | 教室不能用时不应处罚学生 | A/C/E/F **（影响处罚）** |
| D-09 | 解除后又收到同一来源的写入（乱序） | 拒绝（`restriction_released`），要求换新业务 ID | 防止迟到的旧消息重新封锁教室 | A/C/E |
| D-10 | 解除先于写入到达 | 返回 404，由调用方重试或人工处理 | 简单；未实现“墓碑”记录 | A/C/E |
| D-11 | 签到码 | 6 位数字，按业务时区零点更换，不存储 | 无需同步；码不出现在任何学生端响应中 | A/B/C |
| D-12 | 运营可见的数据 | 只给汇总统计；追溯记录不显示学生 ID | 数据最小化 | A/C **（隐私）** |
| D-13 | 用户 ID 格式 | 不透明字符串，≤64 字符 | 等待 C 的身份方案 | C |

## 4. 尚未实现（明确记录，不从清单中消失）

| 项目 | 原因 / 依赖 |
| --- | --- |
| 真实认证与角色配置 | C 负责；目前只有开发用请求头身份 |
| 通知实际发送 | E 负责；M1 已写好通知出口，读取方式待定 |
| 写入公共审计（C） | 审计契约未定；M1 自己的状态追溯表已记录来源和操作者 |
| 违约申诉与更正 | 规则未定（谁能撤销、是否影响后续资格） |
| 违约累计后的处罚（如限制预约） | 政策未定，任务书未要求 |
| 签到码防暴力尝试（限流） | 待 D 决定网关/限流方案 |
| 搜索分页、排序 | B 的页面需求待评审 |
| 教室/座位停用、注销对已有预约的影响 | B-OPEN-02 未决 |
| 节假日、按日期变化的开放时间 | B 的开放时间模型未定 |
| 预约结束后的“已完成”状态 | 当前已签到的预约结束后仍显示 `checked_in`；统计不受影响 |
| 部署到测试/生产环境；M1 任务进程加入 Compose；种子数据进镜像 | D 负责。CI 已经在运行 M1 的 ruff、测试和迁移 |
| 与 M2、M3 的真实网络联调 | 对方服务尚未实现 |
