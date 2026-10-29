# B-78 已审核增量的上游整合

关联 #78、#15、#19、#24。负责人授权 B 整合；本次只合入原有审核提交并补充这份记录，不增加业务政策或修改共享入口。

## 原因与结果

父 PR #28/#30/#52 先进入 D #15，子 PR #48/#32/#46/#50/#70 随后才合入各自已关闭的父分支。Git 的合并记录不会随源分支后来更新而传播，因此“子 PR 已 merged”不能证明上游已包含功能。

本次固定基线为 D #15 `718620156a831c6258127d17dc9551c0d03fbf25`（已同步 main `3b5898b`）。用三个普通、无冲突的本地 merge 保留原提交：

| 来源 | 原审核提交 | 补齐内容 |
| --- | --- | --- |
| #48 | `4ee2fe5b2b221d7b5e24cd7f94ede1022a8353f3` | 普通教室目录、独立资格端口及过滤分页测试 |
| #50，含 #32/#46 | `1cdbda19f7cb8b23712373b6c285d3621775fc3c` | 预约长期 session、本人预约/签到/违约、只读运营与授权教室码 |
| #70 | `4e3419d6a5ae7ca04ad47aea7819bce3b569bbad` | 资源可信会话工厂、独立新建权限与 opt-in HTTP 验收 |

原业务/测试/说明共 **38 文件**，每个整合后 blob 与其原审核来源相同；另增本记录，净差异共 39 文件。#32 `b266a5f` 与 #46 `5da9fee` 的原提交也都是整合分支祖先。全部由 Git 自动合并完成，保留原作者与原测试。

可以在本分支复核来源和字节（Python 只调用只读 Git 命令）：

```sh
python - <<'PY'
import subprocess
base = '718620156a831c6258127d17dc9551c0d03fbf25'
sources = [
    '4ee2fe5b2b221d7b5e24cd7f94ede1022a8353f3',
    '1cdbda19f7cb8b23712373b6c285d3621775fc3c',
    '4e3419d6a5ae7ca04ad47aea7819bce3b569bbad',
]
verified = set()
for source in sources:
    subprocess.run(['git', 'merge-base', '--is-ancestor', source, 'HEAD'], check=True)
    names = subprocess.check_output(
        ['git', 'diff', '--name-only', base + '...' + source], text=True
    ).splitlines()
    for name in names:
        subprocess.run(['git', 'diff', '--exit-code', source, 'HEAD', '--', name], check=True)
        verified.add(name)
assert len(verified) == 38
print('Verified 38 original source files and all three source tips')
PY
```

## 实际验证

本机 Node24.19.0 / Python3.12.14：

- `cd frontend && npm test`：**249 passed / 6 skipped**，18 文件通过、1 文件跳过。6 项是 opt-in 网络套件，默认跳过不计网络通过。
- `cd frontend && npm run build`：类型检查与 Vite 构建通过。
- `cd backend && ruff check .`、`ruff format --check .`：通过，68 文件格式通过。
- `cd backend && python -m pytest -m 'not integration' -q`：**88 passed / 93 deselected**；保留已有 httpx TestClient 与 Alembic 配置弃用 warning，没有为本次整合修改他人依赖/配置。
- `git diff --check <base> HEAD`、`git fsck --connectivity-only --no-dangling`：通过。只读来源检查 38 文件全部匹配；原测试原字节保留，不增加只断言文件存在的空测试。各功能的破坏/恢复证明保留在原审核说明中。

真实网络验收沿用 #70 的固定、字节验证后端：C #57 `51b65bfedd87c85cd9295fdeb01b92e9460e7c5c`、B #48 `4ee2fe5b2b221d7b5e24cd7f94ede1022a8353f3`，前端为本次整合后的当前源码。运行方式见 [B 会话接入说明](../architecture/b-resource-session-access.md)：

```sh
python backend/tests/resources/run_frontend_acceptance.py \
  --combined-source /absolute/path/to/pinned-combined-source \
  --frontend /absolute/path/to/this-checkout/frontend
```

临时 PostgreSQL16.2、真实 C/B HTTP、合成账号和 Vue 组件/客户端 **6 passed**：教室/座位创建编辑并重读、BIGINT、只读拒绝、范围拒绝/伪造前端全域403、退出401、真实提交后响应丢失且重挂载仍仅一次POST。进程/测试库自动清理。此次已补上 #70 当时受审批超时/沙箱缓存权限限制的最终前端复跑；原历史说明保持原字节，不将旧记录改写成当时已通过。

本轮不改业务源码，所有验证后的产品文件仍与原审核提交相同；后续只补本说明和 PR 验证链接。远端最终提交的 CI 另在 PR 中按实际 head 记录，不能用此前提交的绿灯替代。

## 仍需接线与后续顺序

- 本 PR 应先进入 D #15 分支，再由人决定 #15 到主线的合并。若 #15 已先合主线，应先确认该主线包含基线，再把本整合 PR 的 base 改为 main，避免重复“合入已关闭父分支”遗漏。
- D #17/#45 等已有下游分支仍要显式同步新的上游。B 不替 D 解决冲突，也不宣称下游已自动获得本次增量。
- 共享 `App.vue` 保持基线原字节；正式资源管理必须由 D 使用同一响应式 C 会话长期持有工厂/session，全局未确认写入保护也需宿主安装。组件实测不等于共享浏览器接线完成。
- M1 正式身份仍待 A/C；预约/签到/运营真实模式不因本次整合开放。M3 报修资格与目录权限待 E/C/F 确认，M2 目录不自动授予报修资格。
- **NOT RUN（本机）**：当前完整主线 Alembic/PG17 集成、共享路由真实浏览器、M1 正式身份和生产部署。本地 PG16 包缺 `btree_gist`，保留原迁移及所有集成断言，由远端 PG17 工程 CI 检查当前分支；本次 C/B 私有夹具不代表 C/E/M1 全图合流。

不改 README、AGENTS、共享配置、旧迁移、依赖锁、生产角色或 A/C/D/E/F 产品代码。请 D/C 非作者 Review；AI辅助合并和真实验证，最终批准/远端合并由人决定。
