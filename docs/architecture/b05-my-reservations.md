# B-05：本人预约、签到与违约记录候选接入

状态：实现草稿，关联 #33；依赖 #30、#32。A PR #18 /758a231 的接口是候选输入，并已对比最新 c520e41 的 router/schema/checkin/reservations/identity 增量（B 消费的路径、字段和签到语义保持兼容），尚非已完成的 A/C/D 真实集成。

## 用户行为与边界

B 的查询工作区增加“我的预约与签到”页签，保留查询组件和预约恢复状态，不修改共享 App.vue。显示本人预约的教室、座位、起止时间、状态、签到/取消时间；状态筛选与上一页/下一页由服务端 limit/offset 驱动。接口没有 total，不虚构总数；满页后允许继续查询，下一页可能为空。

签到输入用户在教室现场看到的码，不请求管理员 `/rooms/{id}/checkin-code`。服务端决定身份、教室、时段和码的有效性；前端只校验非空、长度不超过32。没有取消操作，不新增资格、处罚、积分或申诉政策。违约记录仅显示服务端结果，未知原因用通用文案，不泄露原始内部错误。

## 候选 HTTP 契约

| 操作            | 路径 / 数据                                                                                                                   |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| 本人列表        | GET `/api/v1/m1/reservations/me?limit=20&offset=0&status=booked`；status 可省略，四种状态 booked/checked_in/cancelled/no_show |
| 本人详情 / 核对 | GET `/api/v1/m1/reservations/{id}`；必须与原ID、座位、教室和时段匹配                                                          |
| 签到            | POST `/api/v1/m1/reservations/{id}/check-in`，JSON `{code}`；只接受200、完整且合法的 ReservationOut                           |
| 本人违约        | GET `/api/v1/m1/violations/me`；数组 id/reservation_id/reason/occurred_at                                                     |

列表响应 `{items,limit,offset}` 必须匹配查询、ID不重复、数量不超limit、状态符合筛选。ReservationOut解析提取到 B 自有 booking/receipt.ts，预约创建仍额外匹配原意图，保留旧行为测试。安全整数或十进制字符串ID不丢精度；非法时间、未知状态、错误分页与矛盾记录不显示成功。

HTTP gateway 需要宿主提供可信 getSession 返回配对 subjectId/accessToken；只用同源 Bearer，不使用开发头或自行赋予权限。请求有超时、取消、无缓存、拒绝重定向；无自动重试、无假数据回退。生产部署、真实授权和共享入口接线由 A/C/D 完成后再验收。

## 签到结果恢复与生命周期

A 当前签到接口没有幂等键。首次操作冻结原预约ID与账号；提交期间禁止重复写入，现场码提交后清空，不保存到状态、日志或浏览器存储。

- 已知无副作用拒绝（错误码、未开放、窗口关闭、鉴权拒绝等）显示反馈，允许修正输入。
- POST成功后查询同一预约核实；超时、5xx、坏响应、already_checked_in或未知拒绝也转为查询核对。
- GET checked_in 确认成功；cancelled/no_show显示终态，不宣称签到成功。
- GET booked 不能证明之前的POST未发生，因此保持unknown。查询失败或返回其他预约也保持unknown。
- unknown只允许继续GET，不能关闭后重新POST。未提供人工解除未知状态的接口；必要时联系管理员。

`createCheckinSession(recordsGateway)` 必须由应用外壳创建一次、跨路由保留，按主体缓存flow。传给 SeatSearchWorkspace 的 checkinSession 与 recordsGateway 必须来自同一后端和身份源；模式或主体不一致时隐藏flow/关闭写入。live未传长期session时只允许读，签到按钮不可用。

`protectCheckinSession(session)` 在应用外壳安装beforeunload并在应用销毁时清理；即使视图不存在仍保护pending。宿主应合并 BookingSession 与 CheckinSession 的pending作为退出提示，不能只重建布尔值。组件卸载只取消只读查询，不中断或丢弃宿主签到flow。账号切换清空列表、违约、输入，丢弃陈旧响应，返回原账号继续查询原ID。clearSettled只清理非pending状态。

仅内存恢复：完整刷新/关闭进程仍会丢失状态，不能声称跨刷新恢复。切换B内部页签保留session；外部路由依赖D持有同一对象，B不修改共享入口。

## 明确的合成演示

默认 `#seat-search-prototype` 使用同一Map连接预约和历史/签到：先创建演示预约，再在新页签输入 DEMO。合成演示不校验真实时间窗口，不代表A签到规则。没有用户身份或真实数据；刷新重置。注入外部bookingGateway/session时不自动连接另一份合成历史，必须显式提供对应recordsGateway。

## 实际验证

本机 Node24.19.0，沿用锁定依赖；前端 `npm run test` **185 passed**、`npm run build` 类型检查和生产构建实际通过；CI链接见PR。覆盖 HTTP DTO/错误/超时、分页/空态、账号切换/陈旧响应、重复签到、未知GET-only恢复、真实组件卸载返回和无视图时在途写入完成。真实浏览器已完成“查询→合成预约→我的预约→DEMO签到→已签到”，截图留在本机 `/private/tmp/gcll-b05-checkin.jpg`。

独立副本将 booked 核对分支错误视作已解决 → 定向测试1 failed（期望unknown，实际resolved）；恢复实现后1 passed。仓库未提交破坏版本。

真实 A/C 身份与签到HTTP、数据库写回、D共享入口跨路由组合、真实通知和生产部署：**NOT RUN**。不修改后端、迁移、权限、AGENTS、README或依赖，不将合成/Mock测试当作网络验收。请A/C/D非作者评审并由人决定合并。
