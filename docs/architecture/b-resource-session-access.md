# B 资源管理可信会话接入与 HTTP 验收

关联 #65、#19、#24；基于 #52 `e60e083`，本增量供 C/D 宿主 Review。

## 接线契约

`resources/access.ts` 的 `createAuthenticatedResourceAccess` 一次生成同一个网关和长期 `ResourceSession`。宿主在路由组件外创建一次，向 `ResourceWorkspace` 传入返回的 `gateway` 和 `session`（prop 名为 `resourceSession`）。不要因切页、退出或换账号重建它，未知写入需要按原主体保留。应用级 `protectResourceSession(session)` 的安装/清理方式沿用 [生命周期说明](b-resource-session-lifecycle.md)。

宿主的同步 `getSession()` 必须读取 **Vue 响应式** 的 C 会话源；无登录、失效或退出时返回 null。C 登录和 `/api/v1/auth/me` 配对后，内存中的字段映射为：

| 工厂输入 | C 公开接口来源 |
| --- | --- |
| `subjectId` | `me.subject_id`，原字符串 |
| `accessToken` | 同一登录会话的 `access_token` |
| `permissions` | `me.permissions`，不从角色名猜测 |
| `dataScopes.allRooms` | `me.data_scopes.all_rooms`，明确布尔值 |
| `dataScopes.roomIds` | `me.data_scopes.room_ids`，B 数字 ID 字符串数组 |

宿主显式传入 `permissions: { read, manage, createRooms }`，名称必须与 C 安装器 `ResourcePermissions` 配置一致。没有生产默认名称、客户端授予角色或新的登录实现。测试中的 `synthetic.resource.*` 只属于合成夹具。

- 读取要求 read；管理要求 read + manage；**新建教室**另要求 createRooms 和明确的 `allRooms === true`。已有教室编辑和座位管理仍由服务端逐个检查房间范围。
- 会话缺失、字段无效、配置权限缺失时关闭操作。缺少可信范围不会回退全域。旧手动配对的 live session 必须显式提供 `canCreateRooms()`；没有该回调只关闭新建教室。prototype 保持原演示行为。
- 每个请求捕获自己的主体、令牌、权限和范围；使用固定同源 `/api/v1/resources`、Bearer、无缓存、拒绝重定向、原有超时与 JSON 校验。没有 token 存储或日志。
- 请求前拒绝是确定未发送；请求后的会话变化会丢弃旧读取，已发送写入保留未知。同主体换 token、权限或范围也使旧缓存失效，组件清空列表并重新查询。版本号只为内存计数，不公开 token。
- 401/403/404/409/422 等明确服务端拒绝沿用原错误分类，不自动重试；丢失响应、坏确认、写入 5xx/408 继续保留未知。宿主负责 C 会话到期/401 的清理和重新认证；本模块不自动刷新令牌。
- 新建权限撤回时冻结已打开草稿，可取消；未获得新建权限不能打开/提交新建表单。未知操作即使关闭、销毁再挂载仍阻止新的写入，列表读取可用于人工核对，但不会仅凭相同内容自动解除未知。

前端检查只减少误操作；C/B 服务端身份、权限、范围及同事务审计始终是最终边界。真实 HTTP 验收故意伪造合成客户端的全域标志，服务端仍返回 403。

## 可复现验证

常规命令：在 `frontend` 运行 `npm test`、`npm run build`。本机 Node24.19.0：**114 passed、6 skipped**；跳过的 6 项是明确 opt-in 的真实网络验收，不算常规 CI 网络通过。类型检查与构建通过。后端 `ruff check .`、`ruff format --check .` 通过；`python -m pytest -m 'not integration' -q` 为 29 passed、3 deselected（本分支未改变后端产品逻辑）。相对 #52 新增 21 项默认回归，覆盖配置缺失、未发送拒绝、独立新建能力、并行请求身份捕获、同主体 token/范围/权限更新、旧响应、已发送未知与真实组件状态。

真实网络组合固定为 C #57 `51b65bfedd87c85cd9295fdeb01b92e9460e7c5c` 与 B #48 `4ee2fe5b2b221d7b5e24cd7f94ede1022a8353f3`，无依赖源码复制进本产品分支。准备方式：

1. 在仓库外准备这两个固定提交的独立 checkout；不改变自己的工作区或未提交文件。
2. 使用 C 提交已有的 `backend/tests/c_module/prepare_resource_acceptance.py --source <B-checkout> --output <全新临时组合目录>`。该脚本从文件自身所在 C checkout 取源码，验证 B 字节并生成 `acceptance-source-manifest.json`。本次本机从 GitHub 固定提交 tarball 取 C，按同一 B 固定提交逐字节投影并生成校验 manifest；没有改 C 源码。
3. 用安装了组合后端锁定依赖、C 的 requirements 和可选本地测试工具 `pgserver==0.1.4` 的 Python 执行：

```sh
python backend/tests/resources/run_frontend_acceptance.py \
  --combined-source /absolute/path/to/disposable-combined-source
```

需要 Node/npm 在 PATH 中，前端已安装锁定依赖。启动器核对固定版本和 manifest，创建自己的临时 PostgreSQL、本机环回 C/B HTTP 服务与合成账号；不接受现有数据库地址，结束会停止子进程和清理测试库。缺源码/工具/服务就失败，不回退 mock 或静默跳过。`--frontend` 可显式指定本次前端 checkout，默认当前启动器所属仓库的 frontend。

只由启动器向 Vitest 提供 `VITE_B_RESOURCE_ACCEPTANCE_ORIGIN`，目标必须是 `http://127.0.0.1:<port>`；不要指向手动或真实业务服务。所有密码是公开合成夹具，真实临时会话 token 不输出、不进入截图/trace。

本机 Python3.12.14 / PostgreSQL16.2 实跑 **6 passed**：

- 挂载真实 Vue 组件，经实际 TCP 创建/编辑教室及座位，重新查询持久化字段和 revision。
- 大于 JavaScript 安全整数的 `9007199254740993` 全程保留字符串。
- 只读账号查询成功，写入在发送前拒绝，UI 管理按钮关闭。
- 限定范围管理员可建本范围座位、不能建教室；访问范围外房间 404；伪造客户端全域标志仍被后端 403 拒绝。
- C 公开退出接口生效，旧 token 的写入得到 401、不会伪造成功。
- 实际 POST 已成功提交后人为丢弃响应；关闭并卸载/重挂载组件仍保留未知，只发送一次 POST，实际数据库中仅有一条资源。

负对照在隔离前端副本移除全域范围检查，目标回归 **1 failed**；原字节恢复后 **1 passed**。原断言保留，破坏版未提交。初次启动器错用 `/health` 导致 readiness 超时，改为现有 `/health/ready` 后重跑通过；一次新增组件测试选择器错误也已修正并回归。

网络 6 项通过后，仅进一步补充了新建权限撤回时的冻结/取消展示和 2 项默认组件回归，工厂与网络用例原字节未变。最终再次网络复跑未完成：自动权限审批两次超时，沙箱内 PostgreSQL 全局缓存锁文件权限被拒；不能把前一轮通过声称为最终提交新网络通过。最终默认 114 项与 build 已重新通过。

## 范围与待办

本 PR 不改共享 App、C/D/E 源码、README、AGENTS、依赖锁或迁移；只新增 B 工厂、B 回归和 opt-in 启动器。数据库初始化只在全新隔离夹具中采用 C 冻结 SQL 与 B 测试 metadata，不在应用启动创建表。

**NOT RUN**：本工厂到 D 共享路由的真实浏览器接线、全 A/C/E Alembic 图、M1 正式身份、真实学校账号和生产部署。本机 PG16 包缺 `btree_gist`，完整共享迁移由 owner 的 PG17 CI 验证；这里不删扩展或缩减迁移。6 项验收是 jsdom 下实际组件/客户端到实际 HTTP 服务，不冒充真实浏览器。D #64 的目录浏览器验收也不能代替本工厂的宿主接线。

请 C 核对 me/权限/范围映射、D 核对应用长期会话接线；沿用非作者人工 Review 与人工合并。未知写入的可信自动恢复仍需另行设计稳定操作 ID / 查询协议，本轮没有解除或重放入口。
