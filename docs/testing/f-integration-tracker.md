# F 的跨模块集成跟踪表

## 当前恢复快照（2026-10-29）

首轮恢复直接读取 GitHub：32 个开放 Issue、24 个开放 PR；100 条上限未触及，分支游标读取到空页结束。逐项获取 PR base/head、正式 Review 及当前 head 的 PR 触发工作流。24 个 head 返回的工作流均 completed/success；接口只返回 PR 触发运行的第一页，不能声称覆盖全部 push 历史、全部 Checks 或完整集成。

已有若干明确标记 AI 辅助的 COMMENTED 技术反馈，返回的 Review 中没有 APPROVED，不登记为人工批准。以下为当前事实；后半部分的历史快照仅解释前一会话状态。

- `origin/main=04159d378fcb79a0e5664cd7c15665a37640c329`；M1 #18 已合入 main（合并点 `6531430`），正式身份和 A/C/E 写回仍待验收。
- F 连接账号为 `Rankyer`，E PR 作者为 `zhengzheyu126`。插件实际创建 Issue/分支均 403；本机明确指定 Rankyer 的推送 dry-run 已成功，同账号 REST 已创建 [F-01 #75](https://github.com/ElastingYun/campus_resource_management/issues/75) 和 [F-02 #76](https://github.com/ElastingYun/campus_resource_management/issues/76)，两条通道分开记录。
- F 起点为本地 `docs/f01-autonomous-workflow` / `22aa271`，原提交保留。heartbeat `f-github` 已注册 ACTIVE，首次定时触发与手动检查分开验收。
- F 原分支已完整推送，文档 [PR #77](https://github.com/ElastingYun/campus_resource_management/pull/77) 已建立并请求 D/E Review；已在 #69/#15 发布具体接口/基线问题。此后创建的 #75/#76/#77 不计入上方调查开始时的 32/24 快照。

| 跟踪项 | 固定 head / base 与实际事实 | 未完成与 F 动作 |
| --- | --- | --- |
| [#15](https://github.com/ElastingYun/campus_resource_management/pull/15) 前端基线 | `7e76ba4`，base=main；已含 B 页面增量；当前 PR 工作流成功 | 与 D 确认 M3 固定基线、共享入口和会话接线 |
| [#64](https://github.com/ElastingYun/campus_resource_management/pull/64) 真实目录 | `4870b58`，base=#45；固定 C `51b65bf`、B `4ee2fe5`；工程与网络/浏览器工作流成功 | 普通 M2 目录不能默认用于 M3；B/C 的 AI COMMENT 不替代人工批准 |
| [#22](https://github.com/ElastingYun/campus_resource_management/pull/22) C 基础 | `a7cfdf0`，base=main；已同步 M1、新增 A/C 汇合 0007；工程工作流成功 | 共享工程/迁移由 owner Review，路由共存不等于 M1 已接受 C 身份 |
| [#59](https://github.com/ElastingYun/campus_resource_management/pull/59) 事件/M3 适配 | `11ed320`，base=#57；#72 已合入此开发分支；工程、C/B、C/E 工作流成功 | 真实 B 报修资格、生产角色、派单能力、主挂载、全迁移图、M1 写回未验收 |
| [#53](https://github.com/ElastingYun/campus_resource_management/pull/53) E 草案 | `b361b72`，base=main；Draft、工程工作流成功 | 角色、自验收、冲突、隐私等仍待决，F 页面范围见[F-02](../requirements/f02-m3-page-acceptance.md) |
| [#62](https://github.com/ElastingYun/campus_resource_management/pull/62) 创建/本人查询 | `d310c56`，base=main；Draft；创建、同键重放与创建审计端口；工程工作流成功 | 主应用未挂载；C 固定源码适配不等于正式组合完成 |
| [#69](https://github.com/ElastingYun/campus_resource_management/pull/69) 派单 | `f5802f5`，base=#62；Draft；版本竞争、操作 ID、同事务历史/审计；工程工作流成功 | 处理人读取版本/能力和正式角色仍需确认，不从状态猜版本或权限 |
| [#74](https://github.com/ElastingYun/campus_resource_management/pull/74) 开工 | `9869ad0`，base=#69；Draft；受派维修人确认同工单/同教室整室下架后开工；工程工作流成功 | 确认默认503，真实 M1 写入/恢复待接入；前端不伪报开工成功 |
| [#70](https://github.com/ElastingYun/campus_resource_management/pull/70) B 管理会话 | `4e3419d`，base=#52；Draft；可信会话工厂和独立新建权限；工程工作流成功 | 管理会话不等于普通报修目录，正式入口浏览器仍需整合 |

当前叠加链：C #22 → #34 → #36 → #39 → #41 → #55 → #57 → #59；E #62 → #69 → #74；D #15 → #17 → #45 → #64。后项以先项开发分支为 base，不表示进入 main。#53 为独立文档草案，#67 是基于 #64 的 D 文档。

| 固定 head | 本轮读取的实际 PR 工作流 |
| --- | --- |
| E #62 `d310c56` | [Engineering 40836391368](https://github.com/ElastingYun/campus_resource_management/actions/runs/40836391368)：success |
| E #69 `f5802f5` | [Engineering 40842399056](https://github.com/ElastingYun/campus_resource_management/actions/runs/40842399056)：success |
| E #74 `9869ad0` | [Engineering 40845417790](https://github.com/ElastingYun/campus_resource_management/actions/runs/40845417790)：success |
| C #59 `11ed320` | [工程 40844836522](https://github.com/ElastingYun/campus_resource_management/actions/runs/40844836522)、[C/B 40844836644](https://github.com/ElastingYun/campus_resource_management/actions/runs/40844836644)、[C/E 40844836898](https://github.com/ElastingYun/campus_resource_management/actions/runs/40844836898)：均 success |
| D #64 `4870b58` | [工程 40837546622](https://github.com/ElastingYun/campus_resource_management/actions/runs/40837546622)、[网络/浏览器 40837546633](https://github.com/ElastingYun/campus_resource_management/actions/runs/40837546633)：均 success |

这些是远端结果，F 本轮未在本机重跑业务、迁移、浏览器或 M3 网络验收。C/E 随机 schema 和 TCP 不等于独立 M3→M1 写回；同时整合 A/C/E 时需 D/C/E 批准新增迁移汇合，不改旧历史。

当前独立依赖仍包括 #23 的冲突原子性/服务身份/operation_id/generation/释放终态、#25 的通知线协议及实际送达、#44 的报修资格/验收/隐私政策。M2 已批准的校园/本院系目录和个人预约冲突策略不自动用于 M3。F 可以继续本人创建/查询验收草案，并就具体接口差异向 owner 提问。

## 前一会话快照（以下仅为历史）

前次曾查到 16 个开放 Issue、11 个开放 PR，彼时正式 Review 列表为空。此历史不能代替上方当前调查。

## 主要依赖

| 跟踪项 | 已观察事实 | 未完成/依赖 | F 的动作 |
| --- | --- | --- | --- |
| [#15](https://github.com/ElastingYun/campus_resource_management/pull/15) 前端基础 | 开放，base=main；含 Vitest 与最小导航 | 非作者 Review、主线整合 | 与 D 确认 M3 开发基线和入口接入 |
| [#17](https://github.com/ElastingYun/campus_resource_management/pull/17) M2 真实前端 | 开放，base=#15 分支；有 D↔C 网络验收 | 资源使用 CI 合成服务、M1 关闭，不代表完整 B/A/E 联调 | 参考会话、错误与恢复交互；不复制 M2 私有业务 |
| [#18](https://github.com/ElastingYun/campus_resource_management/pull/18) M1 | Draft，base=main；正文列出 8 个工程冲突；已有维修限制实现 | 工程整合、正式认证、最新统一工程验证和真实网络验收 | 跟踪 M3 接收端契约，不擅自处理 A 冲突 |
| [#20](https://github.com/ElastingYun/campus_resource_management/pull/20)、[#26](https://github.com/ElastingYun/campus_resource_management/pull/26) B 页面 | 已合入 #15 的开发分支 | 尚未进入 main，不等于完整真实接入 | 追踪最终主线路径，避免重复造页面基础 |
| [#22](https://github.com/ElastingYun/campus_resource_management/pull/22) C 基础 | 开放，base=main；提供身份、M2、审计与契约 | 非作者 Review、整体接入 | 与 C 确认 M3 身份及权限需要 |
| [#23](https://github.com/ElastingYun/campus_resource_management/issues/23) A/C 网络集成 | 精确记录来源 API 与 operation_id/generation 差异、未知释放保护和服务身份缺口 | A/C 协议确认及独立服务验收 | 汇总验收依赖；不把 URL 配置当作接通 |
| [#24](https://github.com/ElastingYun/campus_resource_management/issues/24) 资源身份和范围 | B v2 与 C 同事务审计已有组合验收 | 普通目录路径/过滤分页、共享迁移、正式挂载及浏览器验收 | 与 B/C/D 对齐 M3 空间选择所需能力 |
| [#25](https://github.com/ElastingYun/campus_resource_management/issues/25) 通知 | C 保存业务事件；Issue 指明 E 通知契约待交付 | 接收/查询、可信身份、幂等投递和实际发送 | 与 E 确认契约和联调范围，不把事件入库当通知成功 |
| [#28](https://github.com/ElastingYun/campus_resource_management/pull/28)、[#30](https://github.com/ElastingYun/campus_resource_management/pull/30)、[#32](https://github.com/ElastingYun/campus_resource_management/pull/32) B 增量 | 审计与预约/生命周期实现均为 Draft | 各 owner Review、接入与真实验收 | 跟踪跨页面会话和未知结果的共性要求 |

## 叠加 PR 链

C 当前依赖链为 #22 → #34 → #36 → #39 → #41。箭头表示后项以先前分支为基线，不表示已经合并。整合时依次复核 base/head、差异、迁移和 CI，不直接把最后一项当作 main 的独立小改动。

- [#34](https://github.com/ElastingYun/campus_resource_management/pull/34)：资源真实身份、范围和同事务审计，消费固定 B v2 验收代码。
- [#36](https://github.com/ElastingYun/campus_resource_management/pull/36)：登录签发与停用/凭据变更的竞态修复。
- [#39](https://github.com/ElastingYun/campus_resource_management/pull/39)：占用处理进度；申请 version 不变也须重新查询诊断。
- [#41](https://github.com/ElastingYun/campus_resource_management/pull/41)：当前 head=185ec81；显式准入策略，后端 C→B 实际 HTTP 验收不等于普通浏览器目录完成。

## 已记录的业务决策及范围

[#40](https://github.com/ElastingYun/campus_resource_management/issues/40) 与 #23/#24 最新讨论记录：整教室审批遇到重叠个人预约时拒绝整室占用，保留个人预约；普通申请人仅选择已启用的校园级或本院系教室。

这些是 M2 讨论中记录的决策。F 不把它们延伸为 M3 对已有预约的默认处置政策；M3 相关政策仍需 E/A/C 与负责人确认。

## F 自身待落实

- 建立真实 F/M3 Issue，补关联页面需求和验收标准；本地 F-01 等计划编号不冒充 Issue 编号。
- 核实 E 的 M3 后端、状态流转、接口与交付位置。
- 确认 F 的实际 GitHub 账号、前端基线与调度写权限。
- 逐条建立需求 → Issue → PR → 固定提交/测试证据的追踪，不批量把计划标为通过。
- 记录真实风险：误恢复座位、工单隐私、维修影响已有预约、权限边界和 AI 责任。

本表没有创建或关闭远端任务、发布评论、提交人工 Review 或合并 PR。
