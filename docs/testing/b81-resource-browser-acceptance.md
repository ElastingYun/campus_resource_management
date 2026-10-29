# B-81 资源管理真实浏览器验收

关联 #81、#19、#24、#65、#79。基于 main `1e663e92d582241efcab764cd3ae60011563a092`；只增加 B 测试页面/配置/用例、扩展 B 启动器及本记录。

## 测试页面与权限边界

入口为 `frontend/src/modules/m1-reservation/resources/browser/index.html`。正常 App 没有导入它；测试 main 同时要求显式 `VITE_B_RESOURCE_BROWSER_ACCEPTANCE=1` 和主机 `127.0.0.1`，缺任一条件就抛错，不启用真实读写。该页面不是 D 共享生产入口或部署能力。

`BrowserFixture.vue` 复用 D 已交付的 `createCSession` 公共登录客户端，再把同一响应式 state 的 subject/token/permissions/data_scopes 映射给 B `createAuthenticatedResourceAccess`。工厂只在宿主创建一次，页面切换仅卸载资源组件；全局 `protectResourceSession` 保护宿主所有未知写入。401 按原请求 token 使对应 C 会话失效，不清掉另一个已更新会话。

页面只接受启动器准备的 b-manager/b-reader/b-scoped 合成账号。权限名 `synthetic.resource.*` 明确对应 C 私有测试宿主；没有生产默认角色、新登录实现或凭据持久化。登录结束清空密码，截图时不显示登录表单；trace/video关闭，只主动保存合成业务结果截图。

## 可复现命令

先按 [B 会话接入说明](../architecture/b-resource-session-access.md) 准备带 manifest 的固定 C/B 源码。当前组合固定 C #57 `51b65bfedd87c85cd9295fdeb01b92e9460e7c5c`、B #48 `4ee2fe5b2b221d7b5e24cd7f94ede1022a8353f3`。B 后端源码及角色/建表夹具没有更改；Python 环境需已有组合依赖和可选本地测试工具 pgserver 0.1.4。

本分支前端先 `npm ci`，沿用主线已锁定的 Playwright1.64.1/Vite/Vue，不新增依赖或修改锁文件。Node/npm 需在 PATH 中，然后在仓库根运行：

```sh
python backend/tests/resources/run_frontend_acceptance.py \
  --combined-source /absolute/path/to/pinned-combined-source \
  --browser
```

默认使用 Playwright 管理的 Chromium，需要先用现有锁定 CLI 安装其浏览器。也可显式 `--browser --browser-channel chrome` 使用本机已安装的 Chrome；Playwright 创建全新临时浏览器上下文，不读取个人 profile。`--browser-channel` 单独使用会报错。

启动器先跑原有6项组件/HTTP验收；失败立即返回非零，不启动浏览器。成功后以自身临时库/端口启动 Vite，显式代理 `/api` 到临时 C/B 服务，运行 B 自有 Playwright配置。仅环回地址；缺 origin、依赖、浏览器或服务条件均失败，没有静默skip或数据替身回退。原来不带 `--browser` 的用法保持只执行6项HTTP。

`playwright.config.mts` 为 Node 配置，和浏览器 TS 类型环境分开；不修改 D 的 tsconfig。单独类型检查：

```sh
cd frontend
./node_modules/.bin/tsc --noEmit --types node --module ESNext \
  --moduleResolution Bundler --target ES2022 --skipLibCheck \
  src/modules/m1-reservation/resources/browser/playwright.config.mts
```

所有子进程（Vite、C/B）和 pgserver 在 finally 清理；只使用自己创建的临时数据库。截图在 Git 忽略的 `frontend/test-results/b-resources/`，不会提交进仓库。Vite/Uvicorn私有日志只留临时目录，不打印令牌或原始登录响应。

## 实际行为与证据

本机 Node24.19.0、Python3.12.14、PG16.2、Playwright1.64.1、Chrome156.0.8078.48（chromium引擎、chrome channel）：

| 每个视口的用例 | 可观察断言 |
| --- | --- |
| 创建、编辑、刷新、BIGINT | C登录/me→真实POST201/PATCH200；教室名和座位插座编辑后全页刷新、重新登录仍可读；真实URL保留9007199254740993，所属教室原字符串 |
| 只读与限定范围 | reader列表只有授权教室且写按钮禁用；退出后资源视图清空/密码为空；scoped仍可编辑、创建本教室座位，新增教室禁用 |
| 成功响应丢失与生命周期 | route.fetch实际得到201后abort浏览器响应；关闭表单/卸载组件后仍全局拦截刷新；取消离开后返回保持unknown；reader不见manager未知目标，manager重新登录仍保留；仅一次POST，列表查询只有一条 |

桌面 Desktop Chrome 与移动 Pixel7 视口各3项，真实浏览器 **6 passed**；原组件/实际HTTP **6 passed**。这是 Chromium 桌面/移动视口测试，不声称为实体手机、Safari或D共享App验收。

- 默认 `npm test`：**358 passed / 6 skipped**（26文件通过、原opt-in HTTP文件跳过）；B Playwright `.spec.ts` 不被 Vitest 当作单元测试，不能把默认CI说成执行了本浏览器套件。
- `npm run build`：Vue/应用与主线 integration 类型检查、生产构建通过；上面的Node配置单独tsc通过。
- 后端 `ruff check .`、`ruff format --check .`：通过，81文件；`python -m pytest -m 'not integration' -q`：**104 passed / 97 deselected**，保留已有依赖弃用warning。
- 隔离副本移除宿主 `protectResourceSession`，浏览器 **4 passed / 2 failed**（桌面/移动都在“卸载后仍应拦截刷新”失败）。恢复原字节并核对5个夹具文件与仓库一致，最终Node配置下重跑HTTP6项和浏览器6项均通过；破坏版未提交。
- 首次类型检查将Node配置当作浏览器TS，报node:process/node:path缺类型；拆为明确Node配置 `.mts` 后，应用构建和Node配置各自类型检查均通过。没有修改共享类型环境或删除断言。
- 六幅结果截图均在凭据表单隐藏后保存；人工视觉抽查桌面持久化与移动unknown页面，移动按钮、警告和列表可读。远端最终提交CI在PR按实际head补充，不沿用旧绿灯。

## 后续交接与 NOT RUN

请 C 核对复用CSession到B工厂的身份映射，D 核对 Vite代理/长期宿主接线和将本独立套件纳入工程CI的方式。本 PR 不改 D 共享 App、CI、Vite配置、依赖锁，也不修改 C/A/E/F 产品源码、README、AGENTS或迁移。

**NOT RUN**：D共享入口资源管理浏览器、B浏览器专用远端CI、全 A/C/E Alembic 图、M1正式身份与生产部署。这里是固定C/B私有测试宿主的真实HTTP/数据库/浏览器，不能把它当全项目集成。PG16本地包没有btree_gist，完整主线迁移依赖PG17工程CI，未删扩展或削弱迁移断言。

M3目录/报修资格仍待E/C/F批准，当前M2目录权限不自动扩展；未知写入仍无可信自动解除/重放协议。本轮提供可复现实测及宿主示范，正式入口与业务决策仍由各owner及人工Review完成。
