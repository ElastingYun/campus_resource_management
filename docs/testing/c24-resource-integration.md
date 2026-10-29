# C-24 资源身份/审计验证（2026-10-29）

关联 [#24](https://github.com/ElastingYun/campus_resource_management/issues/24)。实现与安装端口见 [C-24 说明](../architecture/c24-resource-auth-audit.md)。AI 辅助实现、测试和文档，业务规则、非作者 Review 与最终合并由人类成员决定。

## 1. 来源与复现

C 基于 #22 的9e019f4新增适配；B 固定为 #28 的45bcf2be8fbc7cee5f97b75aec4be7d061d5ff8a。准备脚本核对 B HEAD、逐文件 Git blob 与源码字节，只复制公开模块和对应测试；同时记录 C 当前实际源码 SHA256 清单。不复制依赖目录、凭据或 .env，不修改 B 的工作目录或合并其 PR。

```bash
python backend/tests/c_module/prepare_resource_acceptance.py \
  --source <固定 B 检出目录> --output <新的隔离输出目录>
cd <隔离输出目录>/backend
# 配置专用 CAMPUS_DB_* 测试库，全部账号/数据使用合成值。
alembic upgrade head
alembic upgrade head
CAMPUS_TEST_POSTGRES=1 CAMPUS_REQUIRE_RESOURCE_ACCEPTANCE=1 python -m pytest -q
```

所有 C 数据库用例使用独立随机 schema，结束只清理自己创建的 schema。B 自有用例继续使用其私有 schema；共享应用不 create_all。源清单 acceptance-source-manifest.json 位于隔离输出目录。

## 2. 可观察场景

- 真正 Bearer 登录和 B router；伪造开发身份头不生效；普通账号无默认资源权限。
- 有限范围不变成全域；BIGINT=9007199254740993 精确保留；授权更新和账号停用影响已有会话。
- 教室/座位创建更新持久化到实际 B 表，真实 C 审计记录准确 UUID、目标/所属教室、白名单变化和服务端请求 ID。
- 插入 C 审计后抛普通异常或真实主键约束异常：B 资源与成功审计同回滚，失败记录在回滚后独立保存；异常内部信息不出现在响应。
- 并发同版本修改只有一份成功资源审计，败者409/stale_revision且有拒绝审计。
- 缺新教室政策、重复挂载、C上下文不匹配、审计版本/元数据错误均拒绝；独立失败审计不可用返回503，不伪装成功。
- 独立 Uvicorn 子进程与 HTTPX 实际 TCP 完成登录→资源创建→刷新读取→审计查询→退出→旧会话401。没有将 TestClient 或 HTTP stub 作为该 TCP 验收的证据。

## 3. 实际结果

本地环境 macOS arm64 / Python3.13.11 / 私有 PostgreSQL16.2，统一 requirements-dev.txt；临时 Python3.11 工具环境仅负责启动 PostgreSQL。目标 Linux / PostgreSQL17 由新 C/B 工作流实际执行，结果在 PR Checks 记录。

| 命令 / 场景 | 实际结果 |
| --- | --- |
| 隔离组合目录 `python -m pytest -q` | **163 passed, 1 warning in 23.08s**；包含完整 C 与 B 回归、实际 C/B 集成9项及 TCP 子进程 |
| 原 C 目录 `python -m pytest backend -q` | **110 passed, 1 skipped, 1 warning in 18.62s**；B 未安装的组合模块明确跳过，专用工作流不允许这个跳过 |
| 原 C 目录 Ruff/格式 | All checks passed；42 files already formatted |
| 固定 C/B 组合 Ruff/格式 | All checks passed；50 files already formatted |
| compileall / pip check | 均退出0；No broken requirements found |
| 新工作流 YAML / diff | Ruby YAML 解析通过，git diff --check 通过 |
| 本地 Node / Docker | 本轮未改前端；本机 Docker **NOT RUN**，由远端原工程 CI 验证 |
| GitHub 目标环境 | 固定72c8291的C/B专用PR验收：**163 passed, 1 warning in31.40s**，Python3.13/PostgreSQL17；工程CI也成功，具体链接见下表 |

保留 TestClient/HTTPX 弃用警告，没有过滤。初次测试夹具误在应用生命周期启动前借用宿主池，出现 setup error；改用现有可信 bootstrap 独立初始化账号，应用仍按生命周期创建池。一次边界回归发现无效 request_id 的校验晚于 clock 调用，已将全部 UUID 验证提前到持久化参数构造之前；上述完整结果在修正后取得。

交付 [PR #34](https://github.com/ElastingYun/campus_resource_management/pull/34)，增量base为 #22。固定提交72c8291021cc3cbeb41c37ad259a57a27e7ed194的四轮工作流均已完成且success：

| 运行 | 实际结果 |
| --- | --- |
| [C/B push 40792773336](https://github.com/ElastingYun/campus_resource_management/actions/runs/40792773336) | 固定B-v2/C、真实PostgreSQL、事务与TCP验收成功 |
| [C/B PR 40792912628](https://github.com/ElastingYun/campus_resource_management/actions/runs/40792912628) | 163项通过，无skip；源字节校验、50文件格式检查和重复迁移成功 |
| [Engineering push 40792773288](https://github.com/ElastingYun/campus_resource_management/actions/runs/40792773288) | 前端、后端/PostgreSQL、Compose登录代理/断库恢复三项成功 |
| [Engineering PR 40792912662](https://github.com/ElastingYun/campus_resource_management/actions/runs/40792912662) | 同上三项成功 |

后续提交以各自Checks为准；本机Docker的NOT RUN记录保留，远端实际成功不替代生产和浏览器业务验收。

## 4. 测试有效性负对照

仅修改 `/private/tmp/c24-integration-round4` 中的 C 审计副本，把 `record_in_session` 改为另开独立连接提交成功审计；原仓库没有改变。
命令为 `python -m pytest backend/tests/c_module/test_resource_integration.py::test_audit_insert_then_failure_rolls_back_resource_and_success_audit[exception] -q`。

结果：原实现 **1 passed / 退出0** → 故意破坏 **1 failed / 退出1**（资源回滚但残留1份成功审计，断言要求0）→ 逐字节恢复后 **1 passed / 退出0**。没有改测试预期、删失败用例或提交破坏版本。原始输出保留在本机临时 `/private/tmp/c24-negative-control.log`。

## 5. 未完成的项目验收

当前不证明 M2 普通用户真实选教室或提交资格、校园 null 院系准入、生产角色权限、新建教室政策、共享资源迁移和 D 正式浏览器挂载已经完成。M1 #23、通知 #25 与远程审计边界未在本增量实现。#24 保持开放，等待相关 owner 确认并完成剩余链路。
