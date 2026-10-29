# C 主线整合验证（2026-10-29）

关联 PR #22、#15、#53、#62、#69、#77、#79。负责人本轮明确授权对就绪 PR 提交实际 Approve 与常规合并；作者账号不能审批自己的 PR，不使用管理员绕过检查。

## 整合基线与冲突决策

C 基础原提交 `a7cfdf000772be04fb72a36472bcbed9e3036c08`，同步的 main 为
`1e663e92d582241efcab764cd3ae60011563a092`，已包含 D 完整前端、B 遗漏增量及 E 创建/派单/开工基础。

三处文字冲突均由负责人逐项确认后处理：

- README 开头采用 main 的项目介绍，保留其余 C 链接和内容。
- Vite 保留 D 的 `CAMPUS_DEV_BACKEND_URL` 和默认本机地址，`/health`、`/api` 使用同一变量。
- Nginx 保留 C 的 API 读取超时 15 秒，其余位置沿用 main。

D 计划文档的独立冲突已在 D 链按负责人方案处理，再随 #15 进入 main；本次不再次选择策略。

## 迁移

新增无 DDL 的 `0008_merge_c_m3`，parents 为 `0007_merge_m1_c` 与 `e03_m3_assignment`。
保留全部 A/C/E 旧迁移及 C 冻结 SQL 原字节；只连接已有历史，不改角色、表字段或数据。

原组合测试扩为七种起点：空库、A0006、C0002、原 C0007 汇合库、E02、E03、旧 C SQL 库。
各自升级至最新、重复升级，验证同一 head、表结构、既有教室/C 用户/账本及 E 工单保留。
原坏校验和/缺表的整体回滚、组合降级拒绝及表保留断言继续执行，没有删除或放宽测试。

跨 owner 的额外改动只有 B 验收启动器的 import 分组：C 模块真正存在后 Ruff 将其识别为
first-party，原排序不再通过；只移动 sqlalchemy 导入位置，不改启动器逻辑。请 B/D 复核。

## 本机实际结果

- `ruff check .`：通过；`ruff format --check .`：110 文件通过。
- `python -m pytest -q -m 'not integration'`：**130 passed, 160 deselected, 1 warning**。
- `python -m alembic heads`：仅 `0008_merge_c_m3 (head)`。
- `python -m compileall -q backend/app backend/alembic`：通过。
- 本机 PostgreSQL 16 缺 M1 既有 `btree_gist`，完整迁移/数据库矩阵本机 **NOT RUN**。
  由当前提交的工程 PostgreSQL 17 CI 执行，不删除扩展或改断言绕过。
- 本机浏览器/Compose 未重复运行；当前提交的工程和固定 C/B 网络工作流另行核对。

最终提交及实际远端检查链接记录于 PR #22。旧 head 的绿色检查不能替代这次组合结果。

## 剩余边界

C #34/#36/#39/#41/#55/#57/#59 仍是后续依赖，基础合流不等于它们已进入 main。
正式启用应一并包含登录签发和角色/范围一致性修复；本次不改变 C 默认关闭的配置。
真实 M1 身份/原子冲突/终态、M3 资格和实际通知仍分别跟踪，不能用合并或本地事件替代联调验收。
