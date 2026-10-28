# D04 C-v1 客户端验证记录

日期：2026-10-28；负责人 D / jiadongchen666。关联 #16、PR #17；AI 辅助实现与验证，不替代非作者人工 Review。

## 固定版本与真实网络证据

客户端 `670bec28001a0af56c05d55a712f2406954fb6df` 消费 C PR #22 的固定提交 `9e019f429cf20de0a14e6f89524c6766509cce5b`。

- [真实 C-v1 网络验收 40691014657](https://github.com/ElastingYun/campus_resource_management/actions/runs/40691014657)：成功。独立 FastAPI、PostgreSQL 17、Vite 代理，通过前端 client 发起真实 HTTP。
- [同版本工程 CI 40691014677](https://github.com/ElastingYun/campus_resource_management/actions/runs/40691014677)：前端、后端/PostgreSQL、容器检查均成功。
- 验收覆盖：真实登录/me、申请提交及持久化、真实 201 响应到达后在客户端故意丢弃、保留原键和内容恢复到同一申请 ID、学生越权拒绝、两级审批、历史、退出后旧令牌 401、重新登录查询持久记录。
- M1 关闭；最终审批 PASSED 必须仍为 APPLY_PENDING、effective=false。不能把审批通过写成占用已经生效。

教室引用校验使用 CI 专用合成资源 HTTP 服务，账号/角色/审批政策均为显式合成配置。因此这些结果仅证明 D↔C 接入，不证明真实 B 主数据、A 占用或 E 通知联调，不批准生产政策。工作流固定 C 源码并要求有效服务 origin，CI 不允许静默跳过。

## 真实失败与修正

首次 [40689051227](https://github.com/ElastingYun/campus_resource_management/actions/runs/40689051227) 失败：验收脚本未记录被主动丢弃的响应，201 断言实际读到 undefined。670bec2 补记真实响应状态及申请 ID；保留 201、同 ID、同键、同内容和持久化断言，没有放宽门禁。

随后新增页面回归：申请 ID/version 未改变，但服务端撤回 allowed_actions 时，点击刷新必须重新查询并移除过期审批按钮。修复前定向命令 `npm run test --prefix frontend -- -t 'requeries allowed actions'` 为 1 failed（调用 1 次，期望 2 次）；修复后全套 `npm run test --prefix frontend` 为 **74 passed**。实现补充同 ID/version 的主动详情刷新，并监听版本变化。

## 本机验证与限制

- Node 22.16.0；`npm run build --prefix frontend`：浏览器与 Node 集成测试类型检查、Vite 生产构建均成功。
- 浏览器检查：真实 M2 入口展示登录；本机无后端时登录如实失败，密码被清空；B 已有资源演示入口正常显示。
- 本机没有运行 C 服务/PostgreSQL，`test:integration` 在本机为 1 skipped（NOT RUN），不计通过；真实网络证据来自以上 GitHub Actions。
- 恢复记录与会话仅保存在内存；资源选择器当前仅接受最多 100 条完整授权列表。跨刷新恢复、资源分页选择器与真实学校登录尚未完成。
- B #26 随后合入 PR #15 基线，在共享 App.vue 与 D 入口产生预检冲突。负责人随后明确确认“保留 B 座位查询入口，同时保留 D 的 M2 登录、会话与未确认操作离页提示”。本次按该方案同步基线，保留双方入口与 D 的会话/gateway 单例及 beforeunload 生命周期；B 业务模块按原提交合入，不改其实现。

后续验证结果按 PR #17 新提交的 Checks 追踪。真实资源身份/范围/同事务审计由 #24 跟踪，A/C 来源协议与占用验收由 #23 跟踪；#16 保持打开。

## 经负责人确认后的基线同步

同步 PR #15 基线 `490e4f6f31e111f5664eb6da5f3c47c56c771108`（含 B #26）。App.vue 模板冲突按负责人明确批准的方案解决，保留 B 座位查询及资源入口、D M2 登录/会话单例和全局待恢复写入离页保护。B 的模块与 EngineeringHome 对比该基线无差异。

新增 App.test.ts 的四项入口回归：B 座位真实/演示模式隔离、跨模块返回后 M2 会话/gateway 不变、B 资源入口保留、在 B 页面保留待恢复写入提示并在卸载时移除监听。首次运行有 3 项失败，原因为新增测试替身未声明组件名称，无法按名称查找；补全测试替身名称后原断言保留。

实际命令：`npm run test --prefix frontend` 为 **9 files / 121 passed**（包含新合入的 B 测试与四项入口回归）；`npm run build --prefix frontend` 的两组类型检查及生产构建成功。`git diff --check` 及未解决冲突检查通过。合并只同步开发分支，不执行 GitHub PR 合并；新提交 CI 结果继续留在 PR #17。
