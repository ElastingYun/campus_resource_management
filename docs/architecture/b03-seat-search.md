# B-03 学生座位查询：实现与接入说明

负责人 B / hrzhao7。关联 [Issue #21](https://github.com/ElastingYun/campus_resource_management/issues/21)，覆盖 B-UI-01。基线为 D 集成分支 `85d71ede`（含 B-02 PR #20）；本轮只读，不创建预约，不变更数据库、认证、业务规则或依赖。
后续预约确认与恢复增量见 [B-04](b04-seat-booking.md)；本文记录 B-03 原始只读交付范围，真实模式仍需显式接入。

## 页面与边界

- `/#seat-search-prototype`：固定合成数据演示。时段可以输入，但示例可用性不按时段计算；页面持续标记演示，不冒充真实查询。演示时区 Asia/Shanghai、4 小时和 7 天只用于合成示例。
- `/#seat-search`：默认未配置，所有查询条件及提交按钮禁用，不加载合成座位。
- `frontend/src/modules/m1-reservation/seat-search/`：模型、只读 gateway、合成适配器、页面和行为测试。
- App 与工程首页仅增加两个页面入口，请 D 评审；README、AGENTS、后端及共享配置未改。

输入日期、开始整点、时长、插座和仅可用条件后查询。教室选项来自当前用户查询所返回的教室，不额外读取管理员资源接口，也不据此制定普通用户可见范围。首次选择全部教室后才有具体教室选项；筛选到空结果时可以回到全部教室重新查询。

规则先加载成功才允许查询，时长上限使用服务值，不在真实模式假定 4 小时。日期合法性、整点和整数时长在浏览器校验；是否未来、预约窗口、开放时间、院系准入和动态冲突仍由 A/C 校验。页面不会从静态 enabled 推算可预约性。

## 候选 HTTP 适配（待 A/C/D 确认）

依据 A [PR #18](https://github.com/ElastingYun/campus_resource_management/pull/18) 的 `758a2315b917d362b612c14f7e0d1e6d2c63a0c8` 实现读取，未宣称该草稿已获批准：

| 请求 | 本轮使用字段 |
| --- | --- |
| GET `/api/v1/m1/settings` | `max_hours`、`booking_horizon_days`；必须为正安全整数 |
| GET `/api/v1/m1/seats/availability` | `start_at`、`hours`、`only_available`；可选 `room_id`、`outlet_type` |
| 查询响应 | `start_at`、`end_at`（带时区）、`hours`、`seats` |
| 座位响应 | `seat_id`、`seat_code`、`room_id`、`room_code`、`room_name`、`outlet_type`、`available`、`reasons[].code` |

`createHttpSeatSearchGateway({ businessTimeZone, getAccessToken, request?, timeoutMs? })` 要求明确业务时区，无浏览器时区回退。依 A 当前 `timeslots.py`，`start_at` 发送业务当地的无偏移整点字符串；响应必须带偏移，校验其业务时间与请求完全对应、结束时间减开始时间等于所选小时数，再按同一业务时区显示起止日期和时间。A/C/D 若修改无偏移输入语义或公开时区字段，应同步调整此适配器再启用入口。

ID 在页面内统一十进制字符串。A 当前数字 ID 仅接受安全正整数；也兼容字符串 BIGINT；超过 JS 安全范围的数字拒绝读取，请 A 将超大 ID 输出为字符串。重复座位 ID、同一教室标签矛盾、请求教室/插座与响应不符、不完整字段或不匹配时段拒绝展示。

仅当 `available=true` 且 reasons 为空时显示可用。已知不可用原因包括教室停用、座位停用、院系受限、非开放时间、已有预约、M2 审批占用、M3 维修；所有原因并列显示。未知原因、true 附带限制、false 没有原因都显示状态未知，不作为可预约依据。不公开 source_id 或服务内部异常。

已根据 C 新交付 [PR #22](https://github.com/ElastingYun/campus_resource_management/pull/22) 的 C-v1 契约（核对至 head `f6e3b9bb`）增加 `getAccessToken` 接入点。每次请求读取外部内存会话并发送 Authorization: Bearer；退出后回调返回 null 则停止发送请求。不提供登录表单、不持久化令牌、不发送服务间密钥或开发权限头。A 仍需正式接入 C 的身份，本适配并不证明 A 已接受 Bearer 会话。

使用 same-origin GET、同源凭据、禁止重定向、no-store 和默认 10 秒超时；取消/超时/错误均不自动重试。固定展示 401、403、422、网络和服务故障信息，不生成身份，不执行 POST/PATCH，不将故障回退成演示成功。

条件改变立即清除旧结果并取消请求。请求序号使不遵守 AbortSignal 的晚到响应也不能覆盖新结果；加载中防重复提交。失败清除结果及教室选项，不残留先前成功状态。页面只显示实际响应的时段。

## 正式接入依赖

1. A 确认上述 API/字段/原因、BIGINT 输出、settings 读取权限及无偏移时间语义；只读适配不代表 B 接管 A 的业务政策。
2. C 的 #22 已公开登录/身份契约；A/C 确认 M1 的可信身份适配与查询范围。页面接收外部登录管理器的内存会话，用户切换或注销时须卸载旧工作台以清除页面内数据；服务器执行所有准入与权限判断。B-02 资源身份/审计另由 C 的 [#24](https://github.com/ElastingYun/campus_resource_management/issues/24) 协作，不重复实现。
3. D 将 C #22 的 `/api` 代理整合到批准的入口，在 App 注入 live gateway、外部会话和与 A 一致的业务时区；当前 B 基线 Vite 仅代理 health，本 PR 不擅自修改共享代理。C #22 尚未合入主线、A #18 仍有冲突，须由 owner 决定整合策略并通过最终提交的 Checks。
4. A/C/D 完成真实环境后再执行登录、查询、越权、窗口临界点、审批/维修叠加等网络联调。预约提交、签到和历史属于后续 B-04/B-05；本 PR 不创建这些写入。

## 验证记录

2026-10-28，本机使用已有锁定依赖，Node 24.19.0（项目目标 Node 22，目标版本由既有 CI 验证）；不修改 engines 或锁文件。

| 实际命令/场景 | 结果 |
| --- | --- |
| frontend `npm run test` | 77 passed，其中新增 B-03 43 项，原有 34 项保持通过 |
| frontend `npm run build` | vue-tsc 类型检查及 Vite 生产构建通过 |
| `git diff --check` | 通过 |
| 浏览器合成查询 | 4 个座位、1 个可用，审批+维修原因同时显示，未知状态单独提示 |
| 浏览器未配置入口 | 查询表单/按钮禁用，没有合成结果 |

测试覆盖合法参数、动态时长、ID 精度、畸形/矛盾响应、多重限制与内部字段隔离、时区/时段不匹配、重复 ID、非法日期、401/403/422/503、超时无重试、规则刷新失败、外部会话更新/退出/非法头拒绝、空态、表单验证、旧响应、重复提交和未配置模式。HTTP 测试替换最底层 fetch/Response；页面测试替换 gateway 边界，这些不是 A/C 真实网络联调证据。

测试有效性在 `/private/tmp` 独立副本验证：将 `known && consistent` 故意替换为 `true`，4 个未知/矛盾状态场景失败；恢复原文后同一组 4 项通过。仓库实现未被破坏。

**NOT RUN**：本机 Node 22、A/C 正式认证与真实业务 HTTP 联调、预约提交、生产部署；CI 链接与实际结果见关联 PR。没有数据库迁移或后端改动，不以本页面完成代替这些验收。
