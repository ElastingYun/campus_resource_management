# B-88：资源管理共享会话入口与主线验收

关联 Issue #88、#24、#65；基于 main `600c659`。本轮将已交付的 B 资源工厂接到真正的 `/#resources`，并沿用 D 的 CSession。没有新增业务角色、默认资源权限、数据库结构或迁移。

## 共享入口

`App.vue` 只创建一次 CSession、M2 gateway 和 B resource access/session。资源会话与全局 `protectResourceSession` 的生命周期属于 App；切换首页、M2 和资源页面不会重建它。退出后原主体未知操作保留在内存，其他主体看不到；原主体返回后仍须核对，不自动重放。刷新会丢失内存，因此未确认写入在页面卸载期间仍有全局提示。

D 原 `M2SessionWorkspace` 的登录/退出界面提取到 `shared/CSessionFrame.vue`，M2 继续使用原文案和同一公开会话 API；资源页复用它。没有另写登录协议、保存令牌或读取浏览器持久存储。资源 401 使用该请求捕获的令牌调用 CSession.invalidate，晚到的旧 401 不会清理新登录。

## 显式配置与启动

前端 **构建或启动 Vite 前**设置 `VITE_RESOURCE_PERMISSIONS`，JSON 的键与 C 的 `ResourceManagementConfiguration.permissions` 一致：`read`、`manage`、`create_rooms`。它只声明前端应该检查哪些权限名，不授予权限，禁止放入令牌或密码。缺失、非法 JSON、额外键或非法权限名均保持资源入口未配置；M2 和原型不受影响。

以下仅为独立合成验收的示例，实际部署应使用 C/负责人批准的值：

```sh
export VITE_RESOURCE_PERMISSIONS='{"read":"synthetic.resource.read","manage":"synthetic.resource.manage","create_rooms":"synthetic.resource.create"}'
npm run dev --prefix frontend
```

读、管理和新建教室分别受同一 `/auth/me` 的权限约束；新建教室还要求明确全域范围。限定范围管理员仍可管理获授权教室中的座位。后端继续执行最终权限/范围/修订检查，BIGINT 不转 Number。缺少服务端 `new_room` 策略时，后端仍拒绝创建教室，前端配置不替代该策略。

后端消费 D 已有的 `infra/runtime/m2_resources.py`，需要已有数据库配置、C 策略和显式资源宿主配置：

```sh
export CAMPUS_C_ENABLED=true
export CAMPUS_C_CONFIG_FILE=/absolute/path/to/approved-c-policy.json
export CAMPUS_RESOURCE_HOST_CONFIG=/absolute/path/to/approved-resource-policy.json
PYTHONPATH="$PWD/backend:$PWD/infra/runtime" python -m uvicorn m2_resources:create_app --factory --host 127.0.0.1 --port 8000
```

账号、角色、服务身份与创建策略仍由 C/负责人显式准备，不在 App 启动时种入账号。策略格式及公共安装端口见 [C 资源接入](c24-resource-auth-audit.md)和 [B 会话工厂](b-resource-session-access.md)。当前 Compose 默认仍运行 bootstrap 入口；本次没有替换部署拓扑、默认启用 C 或修改 Docker/Compose。镜像部署需要 D 将相同公开宿主与构建配置接入其部署方案。

## 当前提交的独立 CI

新增 `.github/workflows/b-resource-host.yml`，仅检出当前提交，沿用已锁定 Python/Node/Playwright。启动 PostgreSQL17 后，`backend/tests/resources/run_shared_host_acceptance.py`：

1. 仅接受专用 CI 标记、环回地址与固定父数据库名；只创建/写入/删除随机 `b_host_test_*` 子库，不清空配置的父库。
2. 在子库执行当前完整 Alembic `upgrade head` 两次；此路径不执行 C standalone migrate 或 metadata.create_all。
3. 在迁移后的实际表中准备合成教室、manager/reader/scoped 与只读服务账号；服务端使用真实 C 会话，不把服务令牌传入前端配置。
4. 启动当前源码的 D 工程宿主（不改依赖、不替换认证或业务函数），先跑 B 组件/真实 HTTP 6 项，再运行共享 App 浏览器。
5. 桌面/移动各 4 项：实际创建/编辑/刷新持久化和同一登录跨 M2 导航；reader/scoped/超大 ID；提交已实际201但响应丢失后的首页卸载/取消刷新/账号返回且一次POST；服务端实际退出后资源401使共享会话失效。
6. finally 停止 Uvicorn/Vite、释放连接并删除本次子库。缺依赖、浏览器、服务或就绪条件直接失败，不降级为 skip 或假数据。

trace/video/自动失败截图关闭；只主动保存登录表单隐藏后的合成结果截图，保留7天。真实请求异常使用固定安全消息，避免在浏览器调用日志中暴露请求令牌。具体远端结果以 PR 当前 head 的新工作流 Checks 为准；默认 Vitest 的 skip 不算此套件通过。

## 本机实际证据

Node22.23.4 / Python3.12.14：前端 **437 passed / 6 skipped**（原 opt-in HTTP 默认跳过），类型/构建与 Node-only 浏览器配置 tsc 通过；后端非集成 **173 passed / 228 deselected**，Ruff 与127文件格式检查通过。应用构建不包含测试账号密码、隔离夹具入口或服务令牌。

本机缺完整 PostgreSQL17/既有 btree_gist，使用保留的 C #57 `51b65bf` / B #48 `4ee2fe5` 校验夹具，验证**当前共享 App**：真实 HTTP **6 passed**，Chrome 桌面/移动 **8 passed**。这证明当前共享前端的行为，不能代替上述“当前完整主线后端与全迁移”的专用 CI。

本机命令（会创建并清理私有临时 PostgreSQL 和全新浏览器上下文）：

```sh
python backend/tests/resources/run_frontend_acceptance.py \
  --combined-source /absolute/path/to/verified-pinned-combined-source \
  --browser --shared-host --browser-channel chrome
```

旧 `--browser` 仍运行 #85 隔离宿主套件；其登录/保存辅助函数与新套件共用，旧业务断言保留。固定组合准备方式见 [B-81](../testing/b81-resource-browser-acceptance.md)。

负对照仅在独立临时副本移除 App 的全局资源保护：真实 mount→未知写入→首页卸载用例在 `beforeunload` 未阻止处 **1 failed**；逐字节恢复后 **1 passed**。没有弱化断言或提交破坏版。另已查看桌面持久化和移动未知状态截图，登录表单隐藏，导航/提示可见。

## Review 与边界

共享 App、会话框架提取和新 CI 涉及 D；C 负责确认同一身份、三项权限映射和服务端策略。请 C/D 非作者 Review。README、AGENTS、依赖锁、C/A/E/F 产品代码和全部旧迁移未改。

M1 正式身份/座位预约闭环、M2→M1 写回、M3 报修资格/工单恢复及生产部署保持独立任务，不因本次资源入口开启而宣告完成。资源停用、删除和开放规则修改仍未开放；资源未知写入没有自动幂等恢复协议。AI 辅助实现和正反验证；最终批准与合并由人完成。
