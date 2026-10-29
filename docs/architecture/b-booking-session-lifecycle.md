# B 预约会话生命周期：跨 SPA 视图恢复

B / hrzhao7。修复 D 在 #30 指出的组件销毁丢恢复状态问题；基于 B-04 `702a97a`，真实 A/C 接入仍未完成。本增量不改共享 App、后端、依赖、README 或 AGENTS，不提供跨浏览器刷新持久化。

## 所有权与端口

`createBookingSession(bookingGateway, makeKey?)` 必须由 D 的应用外壳创建一次，生命周期长于条件组件/key/hash视图。所有恢复状态仍是内存，token不被该对象保存或序列化。

| 端口 | 语义 |
| --- | --- |
| mode | 固定 gateway 模式；必须与查询模式相同 |
| currentActorId | 读取 gateway 的当前可信主体；空/异常时为null |
| current | 仅返回当前主体的持有flow，登录退出时为null，不公开其他主体的索引 |
| pending | 所有持有主体是否存在在途/未知请求；用于全局离页保护，不包含身份详情 |
| interruptPending() | 显式中断在途调用，但保留原意图/键/knownId与unknown，供原账号恢复 |
| clearSettled() | 只清理非pending记录，不能丢弃未知请求 |

每个flow的gateway还绑定其原主体；保留的旧引用不能在另一账号下重新open或recover。A退出、B登录时B获得自己的flow；A回来仍得到原flow/键/knownId。没有在浏览器持久存储身份、键或预约资料，不读取其他模块私有状态。

## 组件消费

SeatSearchWorkspace新增 `bookingSession` prop。只有模式匹配、由宿主持有的session才能启用live预约；旧的 `bookingGateway` 临时prop仅保留合成演示用途，直接给live gateway不再打开写入。这是对尚未正式启用的接入条件收紧，D必须按新版端口更新后再启用。

组件卸载只清理其查询/事件监听及本地演示flow，不dispose宿主session。有限超时内的写入可在组件不在场时完成并核对；失败保留unknown。返回组件后直接显示原确认/未知/核对结果，knownId仍只GET，不因重新挂载生成新键。

可信账号改变时清空查询结果、教室选项和规则并取消旧查询，切换到对应主体flow，不把A的详情留给B。身份getter需读取Vue响应式会话（或宿主在身份改变时重建视图），不能从输入/角色猜身份。gateway和session的配置应稳定；未核对前不能用创建新session替代恢复。

`booking-pending` 在提供session时报告其全局pending，未提供时维持原组件语义；布尔事件仅用于提示，真正恢复状态由session保留。有retained session时允许组件内hash链接，普通外部导航仍提醒。

## 全局离页保护

应用外壳创建session后调用 `protectBookingSession(session)`，得到移除监听的函数。该beforeunload监听独立于查询组件，即使切到M2等视图也能提醒尚有未核对请求；不能只依赖已卸载视图的事件。

D需在共享入口持有并注入同一对象，路由key可更换视图但不能重建该session。账号切换也保留原主体的pending，仅原主体重新登录可恢复。卸载整个应用/刷新仍会丢失内存，浏览器提示无法保证阻止所有强制离开；本轮不声称提供持久恢复或学校真实身份联调。

## 验证

本机Node24.19.0，既有锁文件。`npm run test` **143 passed**（新增13），类型检查及生产构建通过，CI固定提交见PR。新增测试实际mount→unmount→mount验证unknown原键恢复、knownId只GET、无视图时响应完成、账号切换清理查询、原账号恢复；另验证旧flow不能绑定新账号、清理不丢pending、全局beforeunload及live/prototype隔离。

负对照仅在独立副本取消已有flow查找：返回视图取到新的idle状态，定向测试1 failed；恢复查找后同一测试1 passed。仓库实现未被破坏。

Vue组件测试及合成gateway是生命周期边界验证，不是D共享入口已接线或A/C真实网络验收。真实模式仍关闭；D集成、C/A正式身份与生产部署NOT RUN。
