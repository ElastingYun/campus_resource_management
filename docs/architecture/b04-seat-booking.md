# B-04 预约确认、提交及未知结果恢复

B / hrzhao7；关联 [Issue #29](https://github.com/ElastingYun/campus_resource_management/issues/29)、B-UI-02。状态：第一阶段页面及候选适配，待 A/C/D Review；不宣称真实预约闭环完成。
后续[生命周期修复](b-booking-session-lifecycle.md)增加应用级BookingSession；最新版live写入必须注入该长期对象，原临时bookingGateway配置不再启用live。本文件其余内容记录初版契约及限制。

基于 D 集成分支 `490e4f6f`（含 B #20/#26）。与审计 PR #28 独立，未带入未合并的后端增量。代码仅在 `frontend/src/modules/m1-reservation/booking/`、B 的查询组件及测试；没有修改 App.vue、README、AGENTS、后端、依赖或共享配置。

## 1. 页面与入口

在 B 的座位查询结果选择可用座位，确认面板固定教室、座位及查询响应中的起止时刻。确认期间锁定查询条件，提交后读取服务端最新预约状态再展示；关闭确认、拒绝或已核对结果后清空旧查询，下一次预约重新查询。

- `/#seat-search-prototype`：明确标记的合成查询和内存预约。演示查询可用性仍为固定样例，不随预约计算；演示预约会拒绝自己内存中同座位的重叠预约。刷新清空，不调用真实写接口。
- `/#seat-search`：沿用未配置模式，查询/提交均关闭。
- 对已配置的 live 查询，未显式传入 bookingGateway 时提交仍关闭。查询与预约 gateway 模式不一致时关闭预约，禁止拿合成座位调用真实写接口。

真实能力由宿主给 SeatSearchWorkspace 注入 `bookingGateway`。本轮不修改 D 的共享入口，也不处理其 App.vue 合并冲突。签到、取消、完整历史和跨刷新恢复不在本轮。

## 2. 候选 HTTP 契约与身份

已读取 A PR #18 / `758a2315b917d362b612c14f7e0d1e6d2c63a0c8` 的 router、schemas、reservations、identity 和 errors；这是候选消费实现，仍需 A 确认：

| 方法 | 请求/响应 |
| --- | --- |
| POST `/api/v1/m1/reservations` | Idempotency-Key；JSON `{seat_id, start_at, hours}`；创建201或同键重放200 |
| GET `/api/v1/m1/reservations/{id}` | 200，当前用户获授权的预约详情 |

`start_at` 直接使用所选查询响应的带偏移时刻，hours 保持原值，不按浏览器时区重算。A 当前请求 seat_id 为 JSON 整数，只有能安全往返的正整数才转 Number；超出 JS 安全范围时在发送前拒绝，等待 A 的字符串表达约定。返回 ID 可为安全整数或十进制字符串，超大数字拒绝解析，字符串不转 Number。

预约响应校验 id、seat_id、room_id、位置名称、带时区起止/创建时间、状态及 nullable 签到/取消字段。座位、教室和起止必须与原意图一致；GET 的预约 ID 也必须匹配。只接受 booked、checked_in、cancelled、no_show，并检查关键状态/时间一致性。重放找到的预约可能已取消或违约，页面显示当前状态，不把它显示为有效预约。

`createHttpBookingGateway({getSession, request?, timeoutMs?})` 由外部内存会话管理器提供 `{subjectId, accessToken}` 或 null。该配对必须来自同一 Bearer 会话及对应的可信 me 响应；不从输入、角色名或自解 token 猜身份。每次请求读取当前会话，绑定原 subjectId；同账号会话更新可使用新 token，其他账号不能重放原请求或显示其结果。

使用同源凭据、禁止重定向、no-store、JSON 和默认10秒超时，不保存 token、不生成身份、不发送 X-Dev-*。C #22 已提供 Bearer 契约，D #17 正在整合会话；**A 当前正式认证尚未接入，不能只提供 Bearer 就认为 M1 可调用**。权限/资格判断由后端执行，本轮不授权角色或修改政策。

## 3. 请求意图和恢复

每次用户确认只生成一次 UUID 幂等键，并冻结操作者、座位、起止和时长。在途禁止重复确认、换座及关闭。状态为 confirming → submitting → checking → resolved；失败区分 rejected 与 unknown。

1. POST 尚未得到可验证的 ID：超时、网络错误、5xx、未识别错误或无效成功响应都保留 unknown，不自动重试。用户点击核对时用**原键及原内容**再次 POST。
2. 一旦得到已验证 ID，立即 GET 当前状态；GET 失败时保留该 ID，后续只 GET，不再 POST。
3. 恢复过程任何失败都保留原 unknown，即使这次收到401/403/409/422，也不能推断之前一定没写入。A 当前恢复前仍先读取规则，规则变化导致422时尤其需要核对，不能生成新键猜测重做。
4. 首次收到已识别业务拒绝或明确字段校验错误才展示 rejected，并允许返回后重新查询。未知错误不展示原始服务消息、SQL或网络异常。
5. 账号变化后隐藏确认/结果详情，禁止新账号恢复。需原账号返回再核对；晚到响应不跨账号显示，销毁后的响应也不覆盖当前状态。

所有恢复均由用户手动触发，不循环重试；没有“未知即失败/成功”或错误时回退合成成功。未确认结果前不能创建新的意图。

## 4. 离页与宿主接入

处理中或 unknown 时注册 beforeunload 提醒，并阻止组件内普通导航链接；恢复信息仅在当前组件内存中，刷新或强制销毁后不保留。

组件新增 `booking-pending` 事件：处理中/unknown 为 true，已核对或明确拒绝为 false。D 可通过此端口接入统一路由/会话保护，保留 B 座位入口及自己的 M2 会话，不必读取 B 私有状态。本轮没有修改共享路由。

**限制**：浏览器后退、直接改 hash、外部强制卸载不受组件内链接拦截保证；beforeunload 也不能保证拦截所有 SPA 路由。D 接入真实写入前必须处理这些路由及账号切换生命周期。当前不宣称有跨刷新持久恢复、已完成“我的预约”页面或全局离页保护。

## 5. 实际验证

2026-10-28，本机使用已有锁定依赖，Node24.19.0；项目 Node22 由既有 CI 验证，不修改 engines 或锁文件。

| 实际命令/场景 | 结果 |
| --- | --- |
| frontend `npm run test` | 130 passed（B-04新增53，原77保持通过） |
| frontend `npm run build` | vue-tsc 类型检查和 Vite 生产构建通过 |
| 缓存的 Prettier `--check`、`git diff --check` | 通过，无新增依赖 |
| 浏览器合成演示 | 查询 → 选择01号座位 → 确认 → 合成预约#1/待签到；确认时条件和其他选座按钮锁定 |
| 恢复有效性负对照 | 独立副本让已知ID的恢复再次POST，目标测试1 failed（期望1次create实际2次）；恢复后1 passed |

测试覆盖实际 adapter+flow 的原 POST 字节/键恢复、已知ID只GET、重复点击、账号变化、旧响应、超时、畸形/不匹配响应、明确拒绝、恢复拒绝仍未知、整数精度、终态显示、离页信号及模式隔离。HTTP 测试替换底层 fetch，页面测试替换 gateway 边界，不是 A/C 真实网络证据。合成预约不代表真实持久化。

后端无本轮修改，未额外在本机运行其测试；既有 CI 按本分支基线执行工程、数据库和容器检查，固定提交及实际链接见关联 PR。

**NOT RUN**：本机Node22、正式 A/C 身份及真实预约网络闭环、生产部署。下一阶段由 A 确认错误/幂等/ID契约并接入 C 可信身份，D 整合会话、入口、代理和路由保护，再执行真实预约、响应丢失恢复与跨模块限制验收。

后续本人预约与签到接入、未知签到结果仅查询恢复见 [B-05](b05-my-reservations.md)。
