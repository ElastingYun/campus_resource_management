# F-03 / #80：M3 本人报修客户端与原键恢复

关联 [Issue #80](https://github.com/ElastingYun/campus_resource_management/issues/80)，前置讨论 [#76](https://github.com/ElastingYun/campus_resource_management/issues/76)。F / Rankyer，AI 辅助实现与验证。

## 固定基线和交付边界

- 前端固定 D #15 `ee89020bf81fec90799ee25ef758b46d1afb0648`，复用原 Vue 3、TypeScript 和 Vitest；不新增依赖或修改锁文件。它是本独立消费模块的候选基线，不代表 D 已确认正式页面挂载或全项目合流。
- 后端消费 main `40a9977d29db5f2c5fea112ceceec567b9f527f2` 的 E 公开创建、本人列表、本人详情契约；不读取后端私有表，不增加推测的版本/actions 接口。
- 仅新增 F 模块 `models.ts`、`ticket-access.ts`、对应测试和本文。没有修改共享 App、登录、目录、代理、其他模块、Schema、权限、依赖或工作流。
- 本次交付客户端与恢复核心，**没有新增可访问的报修页面或主应用入口**。宿主真实 C/E 接线、报修目录资格及处理面板仍待相关 owner；单元 HTTP 替身不代表真实后端/浏览器联调。

## 宿主接入要求

`createM3TicketAccess` 接收 `getSession()`，返回同一可信会话的 `subjectId/accessToken/canCreate/canReadOwn`，无会话时返回 null。两项能力必须由宿主按已确认的 M3 契约显式映射，不能由角色名、M2 权限、客户端自报身份或目录是否出现某个教室推断。浏览器门控不能替代后端最终授权与房间资格。

宿主在页面组件之外长期持有一个 access 实例，页面重挂载时继续使用该实例；不要在每次渲染、登录刷新或切换页面时新建并丢弃未知请求。当前实例仅保存内存，不使用 localStorage/sessionStorage，不承诺浏览器刷新、进程重启或多标签页间恢复。接入页面仍需为未确认提交提供离页提示。

可选 `onUnauthorized(subjectId, accessToken)` 只在响应仍属于同一当前会话时调用。宿主仍须比对自己的最新会话后清理；旧账号/旧 token 的迟到401不会触发该回调。没有默认登录、默认生产角色或直接消费 M2 会话实现。

## 公开方法与结果

| 方法 | 行为 |
| --- | --- |
| `listOwn(limit=20, offset=0)` | GET `/api/v1/m3/tickets`；只接受安全整数分页，校验 limit/offset 回显与唯一工单 ID，不编造 total |
| `getOwn(id)` | GET `/api/v1/m3/tickets/{uuid}`；校验响应工单 ID 与请求匹配，403/404不解释为工单已撤销 |
| `submit(draft)` | POST 已验证的 room_id/description 与新的 Idempotency-Key；201或同键200且字段核对通过才确认成功 |
| `recover()` | 仅当前原主体用原键/原内容重放 POST；需要当前 canCreate，不自动换键或自动重试；已有未知记录不能通过新 submit 覆盖 |
| `getPending()` | 仅返回当前主体的不可变恢复快照，不含 token；其他主体的原记录保持隔离 |
| `hasUnresolvedReports()` | 提供离页保护所需的布尔值；不暴露其他主体的描述或身份 |

room_id 全程为规范正十进制字符串，最大9223372036854775807，不经 JavaScript Number。描述按 E 边界去首尾空白、1～2000个 Unicode 字符，拒绝控制字符；不静默删除描述中的换行。状态作为服务端字符串消费，不猜测版本、允许动作或座位是否已恢复。

## 失败、时限与会话变化

- HTTP状态、有限格式的错误码与安全提示通过 `M3ClientError` 返回，兼容 E `detail.code` 与 C `error.code`；不保留原始服务端消息、故障描述或网络异常中的秘密。
- 网络错误、超时、408/5xx、无效成功响应及提交后会话变化都保留未知结果。首次请求收到明确4xx拒绝可结束该次尝试；但原记录已未知时，即便后续恢复收到403/409等明确拒绝，也不能据此证明最初未保存，仍保留原记录。
- 每主体最多一个在途提交；未知记录存在时只允许显式恢复。同一主体重新登录且仍有创建能力时，可用新 token 重放原键；其他主体不能读取或恢复该记录。
- 请求只走固定同源路径，使用 Bearer、same-origin credentials、redirect=error、no-store。默认8秒时限覆盖响应体读取，超时会终止信号，即使运输层忽略取消也不会把迟到响应交给调用方或触发旧401清理。
- 身份、token或能力在读取期间变化时丢弃旧结果；key工厂在发送前导致会话变化也不发请求。客户端没有修改 M1/B 的能力，不能用它绕过服务端报修资格或拼接跨模块事务。

## 实际验证（2026-10-29）

本机 Windows，独立 managed worktree；从 Node 官方索引取得 Node22.23.4 ZIP并核对官方SHA256，npm10.9.9执行原锁文件 `npm ci`。安装170包，审计0漏洞；原开发依赖有弃用提示，未修改依赖来隐藏它们。

| 命令 | 实际结果 |
| --- | --- |
| `npm test -- src/modules/m3-repair/ticket-access.test.ts` | 64 passed；正常/边界、HTTP拒绝、非法响应、未知结果、同键恢复、重复在途、会话隔离、超时及隐私快照 |
| `npm test` | 319 passed / 19 files，全量默认前端测试，无跳过 |
| `npm run build` | vue-tsc、独立集成TS类型检查与 Vite生产构建通过；未挂载的 F 模块由TS和测试消费，不声称生产入口已展示 |
| 迟到读取保护负对照 | 原实现3 passed → 临时禁用单个会话保护3 failed → finally恢复原字节3 passed；其余61项是定向筛选未执行，不计负对照通过 |
| Git/文档边界检查 | 仅预期 F 文件，依赖/锁文件无差异，`git diff --cached --check`与文档检查按实际提交留证 |

真实C/E运行挂载、真实M3 HTTP/PostgreSQL、完整迁移图、浏览器、M3→M1网络、失效账号/限流故障注入：本机 **NOT RUN**。本轮不改后端，未重跑后端业务测试；PR工程CI按当前head另行核对，不拿旧绿灯代替。所有最终Review、挂载与合并由人负责，不自动Approve或合并。

## PR 与整合路径

[PR #82](https://github.com/ElastingYun/campus_resource_management/pull/82) 原叠加 D #15；D #15 与 B #79 进入 main 后，GitHub compare确认固定 `ee89020` 为 main 祖先（behind_by=0、merge_base=ee89020），已把 #82 目标改为 main。工作分支保留原历史，没有自行合并或解决其他owner冲突。

原始实现提交 `cfebda927ff15c60babe5d52211c420e5e6e6dbb` 因 Git HTTPS连接失败，经GitHub Git数据API核对树/作者/父节点和提交SHA完全一致后发布；不是重建不同历史。该提交的工程/网络工作流4项成功。改目标后的新提交与新main组合CI另以PR当前head核对，旧结果不冒充新组合验收。

## Unicode 规范化修正

最终契约复核发现JavaScript `trim()` 与E的Pydantic-core/Rust Unicode White_Space不同：U+0085会被E去除，U+FEFF则保留。原客户端可能因此误判成功回执或拒绝合法文本。新增3项回归在旧实现下实际3 failed；改为Unicode White_Space规范化后，完整64项M3与319项前端回归、类型/构建通过，原断言均保留。

只在Git忽略缓存安装E已锁定Pydantic2.14.1/core2.50.1，用Python `-I -S`隔离加载实际TicketCreate，3个Unicode样例全部与F新实现一致；宿主Pydantic仍2.12.5。该探针只验证输入schema，不冒充后端工单/HTTP/数据库验收。[校验器实现依据](https://raw.githubusercontent.com/pydantic/pydantic-core/main/src/validators/string.rs)。安装器曾扫描到宿主其他包的兼容性警告，隔离导入未加载它们，未更改全局环境。
