# M2 C-v1 真实接入与联调边界

负责人 D（jiadongchen666），关联 [#16](https://github.com/ElastingYun/campus_resource_management/issues/16)、[接口讨论 #10](https://github.com/ElastingYun/campus_resource_management/issues/10)、[前端 PR #17](https://github.com/ElastingYun/campus_resource_management/pull/17)。C 在 PR #22 发布了 [C-v1 契约](https://github.com/ElastingYun/campus_resource_management/blob/9e019f429cf20de0a14e6f89524c6766509cce5b/docs/architecture/c-v1-frontend-contract.md) 和对应 OpenAPI；本轮按固定提交 9e019f4 消费接口，不代批生产业务政策。

## 本轮实现

`/#m2` 使用 C-v1 登录、当前身份、退出、授权申请列表、详情/历史/actions、节点通过/驳回与撤销。`/#m2-prototype` 继续单独使用明确标注的合成数据。B 的资源入口和模块保持原状。

Bearer、身份和有效期仅存于页面内存；密码在登录尝试结束后清空，不写 localStorage、sessionStorage、URL 或日志。401 只失效产生该请求的同一个会话，旧请求不能清除新的登录状态。退出立即清除本页会话，服务端退出无法确认时如实提示。

列表使用 C 的数组与 limit/offset，不编造 total、后端筛选或 applicant_id 参数。页面标题为授权范围内的申请记录；审批待办使用独立 review-tasks。详情、actions 的 ID 与 version 必须对应，允许动作只取后端结果，写入仍由后端重新授权。

审批结果、占用结果与 effective 分开显示。PASSED + APPLY_PENDING/UNKNOWN 不是占用已生效；只有后端一致返回 PASSED、APPLIED、未撤销且 effective=true 才显示已确认。未知状态不推断为可用。

## 教室服务与权限依赖

真实教室选择读取 B 的 `/api/v1/resources/rooms`，保留字符串 ID，不经 Number 转换。只呈现服务端已授权返回的静态启用教室；不从院系 null、角色名或 enabled 推导申请资格，也不自行计算可预约性。

B #20 已合入前端集成分支。C 的 [#24](https://github.com/ElastingYun/campus_resource_management/issues/24) 仍负责真实身份、普通用户可见范围和同事务审计；B/A 的共享表及 nullable 院系语义仍需相关 owner 确认。本轮不挂载无身份的资源 router，不给学生管理读取权。

资源无权限、未挂载、数据不合法或当前未取得完整列表时，保留申请查询与详情，但禁用新建并提示原因；不使用占位教室或合成数据替代。当前选择器只接受一次完整的最多 100 条教室结果，更大列表需后续接入分页选择器。

## 未知结果与恢复

每次写入生成独立 Idempotency-Key，并保存原路径、原内容和操作者。未知结果时禁止发起新写入；用户通过“恢复上次操作结果”使用原键/内容重放，取得 ID 后只 GET 最新申请。决定/撤销同样保留原 expected_version，不生成新键猜测重做。

明确的初次 4xx 拒绝允许修正后重新发起；一旦结果未知，恢复错误不清除原操作。恢复记录按 UUID 身份隔离，切换账号不会显示或重放他人的记录。记录仅保存在本页内存，跨刷新恢复尚未实现；存在待恢复操作时启用离页提示，并提示先核对再刷新。

HTTP 传输仍限制同源路径与重定向，清理超时/取消监听；只提取符合格式的 C error.code 进行固定安全提示，不渲染原始错误正文或凭据。空/不合法成功响应不能生成业务成功记录。

## 运行与代理

后端需要 PR #22 的 C 实现、批准迁移和显式配置。当前前端分支不复制 C 源码，原 bootstrap 后端不因设置环境变量就自动获得 C API。C 的配置、账号引导见其运行说明。

本机可分别检出 C 后端和本前端。在 frontend 中设置 `CAMPUS_DEV_BACKEND_URL=http://127.0.0.1:8000` 后执行 npm run dev；Vite 的 /api 与 /health 同源代理到该后端。容器 Nginx 也提供 /api 代理。后端服务凭据只留在服务端，不传入前端环境。

运行 `npm ci`、`npm run test`、`npm run build`。Node 22 类型仅作为集成测试开发依赖，浏览器与 Node 测试分别执行类型检查。

## 真实网络验证

新增 `.github/workflows/m2-c-v1.yml`，固定检出 C 的 9e019f429cf20de0a14e6f89524c6766509cce5b，启动真实 FastAPI 与 PostgreSQL 17，再通过 Vite 代理执行前端 client。验证合成账号真实登录、服务端身份、实际申请持久化、已提交响应丢失后的同键恢复、权限拒绝、两级节点决定、重新登录后查询和会话撤销。

教室引用验证使用显式标注的 CI 合成资源 HTTP 服务，M1 关闭。测试必须验证最终审批通过仍 effective=false；该结果只计为 D↔C 接入，不计为真实 B/A/E 联调。CI 不允许因缺少服务 origin 而静默跳过。本机缺少 C 服务/PostgreSQL 时该用例为 NOT RUN，不能记为通过。

真实网络 run 40691014657 与工程 CI 40691014677 已在前端 670bec2 通过；失败、修正及后续刷新回归证据见 [D04 验证记录](../testing/d04-c-v1-network.md)。本轮没有修改 C/B/A 业务代码、schema 或权限配置，没有生产发布。后续仍需 #24 的真实资源接入、[#23](https://github.com/ElastingYun/campus_resource_management/issues/23) 的 A/C 来源协议与网络验收，以及相关 owner 的非作者 Review。
