# F 的跨模块集成跟踪表

快照日期：2026-10-29。来源为本次直接查询 GitHub Issue、PR、关键讨论、正式 Review 和对应 head 的 Check runs。此表是检查时快照，后续执行必须重新读取远端，不能当作永久状态。

本次查到 16 个开放 Issue、11 个开放 PR；这些开放 PR 的正式 Review 列表均为空。除 #18 未返回 Check runs 外，其余开放 PR 的当前 head 返回的检查均为 completed/success。没有据此批准合并或声称全链路完成。

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
