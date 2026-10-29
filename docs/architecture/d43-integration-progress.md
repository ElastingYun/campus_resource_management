# D43：M2 占用处理进度消费

负责人 D / jiadongchen666，2026-10-29；关联 #43、#16，基于 D PR #17。消费 C [#39](https://github.com/ElastingYun/campus_resource_management/pull/39) 只读契约，网络验收固定 C [#41](https://github.com/ElastingYun/campus_resource_management/pull/41) 提交 `185ec813da9262315c876fee57fbb366c25f55ed`，该历史包含 #36 登录竞态修复、#34 资源身份/审计及 #39 进度端口；不将旧 C 9e019f4 的登录验证视为包含此次安全修复。

## 用户行为

真实 M2 申请详情增加“占用处理进度”。只调用已授权的 `GET /api/v1/m2/applications/{id}/integration`，不新增权限、重试写入、重新入队或强制成功接口。手动刷新实际发送 no-store GET；页面整体重新载入时也再次查询，即使申请 ID/version 不变。

展示当前代次及各操作的占用/释放类别、代次、状态和持久领取次数。历史代次明确标记，旧 APPLY/DONE 不覆盖当前释放意图。ATTENTION 的当前操作提示“自动重试已停止，需人工核查”，不把 UNKNOWN 或 ATTENTION 显示为失败未写入、成功或可重新申请。领取次数不是远端写入次数，释放只针对本申请来源。

诊断码仅使用固定安全文案，未知合法机器码提示联系核查，不显示原始远端异常、payload、租约或凭据。进度数据按白名单解析；非法 ID、版本/代次/次数、未知状态、未来代次或重复操作 ID 拒绝展示。根 effective=true 只能伴随 APPLIED；申请详情仍使用原有审批/撤销/effective 校验。

详情与进度是独立 GET：若响应的申请 ID/version/integration_status/effective 与当前详情不符，显示重新载入提示，不拼接为一份业务事实。新查询前清空旧进度，失败时不继续显示旧的成功结果；旧申请的晚到响应不能覆盖新选择或已卸载页面。401 沿用对应令牌失效逻辑，不清除别的新会话。

## 工程与依赖边界

新增 D-owned M2 进度模型、解析器、组件、单元测试和 gateway GET；通用 JSON 请求增加 no-store。无新增依赖、数据库迁移、C/B/A 业务文件、审批政策或默认角色修改。

`.github/workflows/m2-c-v1.yml` 固定新 C 完整提交；现有真实 FastAPI/PostgreSQL17/Vite 网络用例增加未审批空进度、最终 PENDING、重复只读查询、匿名与已退出令牌拒绝。M1 关闭，最终审批 PASSED 必须 effective=false。

CI 资源依赖仍是明确的合成 HTTP 服务，本轮显式测试校园级 access_scope=campus、department_id=null 和 C 已实现的资格配置；只证明客户端与新 C API 兼容，不能记为真实 B/A/E 联调。没有改实际部署配置或批准其他业务政策。普通学生教室目录仍待 #24 的后端公开路径、可信身份、过滤分页确认；不从浏览器过滤替代后端资格，不把管理权限授给学生。B #32 的长期 BookingSession 可另外集成，本轮未合入其草稿或启用真实 M1 写入。

## 验证

- `npm run test --prefix frontend`：151 passed，11 files；本轮新增30项进度解析/gateway/页面测试，保留已有121项。
- `npm run build --prefix frontend`：浏览器/Node两组类型检查、生产构建成功。
- 定向负对照：仅在 `/private/tmp` 副本加入“有进度就跳过刷新”，同版本 UNKNOWN→ATTENTION 测试1 failed（应查询2次实际1次）；逐字节恢复后1 passed。仓库未提交破坏代码或放宽断言。
- `bash -n infra/scripts/ci-m2-c-v1.sh`、fixture Python AST、`git diff --check`：通过。
- 本机无 C/PostgreSQL，`npm run test:integration --prefix frontend`：1 skipped，NOT RUN；真实网络结果见下方固定提交 CI 证据。

人工需 Review：C 核对状态/代次与只读消费、D 负责人检查界面及异常提示；非作者 Review 后由人决定合并。AI 辅助实现、测试与文档，不代替业务决策、人工评审或生产发布。

## 固定提交证据

前端 `aad920ee9b7fedc1314737d79f1b0e68a42b34c1`，C 固定 `185ec813da9262315c876fee57fbb366c25f55ed`。四个工作流、共8项检查均成功：

- [真实 C 网络 PR 40811114388](https://github.com/ElastingYun/campus_resource_management/actions/runs/40811114388)、[push 40811047468](https://github.com/ElastingYun/campus_resource_management/actions/runs/40811047468)。真实 C/FastAPI/PostgreSQL17/Vite 下通过新增空操作、PENDING、重复查询和匿名/退出会话拒绝；保留原有真实持久化、响应丢失原键恢复与两级审批断言。
- [工程 PR 40811114121](https://github.com/ElastingYun/campus_resource_management/actions/runs/40811114121)、[push 40811047499](https://github.com/ElastingYun/campus_resource_management/actions/runs/40811047499)：前端、后端/PostgreSQL和Compose恢复全部成功。

浏览器使用临时、明确标记的合成进度宿主验证实际 Vue 组件：第2代释放 UNKNOWN 在申请版本4不变时刷新到 ATTENTION，页面显示需人工核查；第1代 DONE 仍为历史意图，没有改写当前占用结论。该宿主未发业务请求，临时文件与服务已清理，不把截图当成真实后端证据。

PR [#45](https://github.com/ElastingYun/campus_resource_management/pull/45) 基于 #17，尚未自动合并。后续仅证据文档提交也需以各自 Checks 为准。
