# C-54：目录身份、权限与网络验收

日期2026-10-29，关联 #54/#24/#47。配置与端口见[C-54接入说明](../architecture/c54-room-options-identity.md)。本增量从C `185ec81` 开始，固定B #48 `4ee2fe5b2b221d7b5e24cd7f94ede1022a8353f3`，包含先前B审计v2。

## 实际环境与命令

本地Python3.13.11、专用临时PostgreSQL16.2、统一依赖锁。准备脚本逐文件核对B Git blob，将当前C与B公开模块/测试投影到独立临时目录，生成SHA256 manifest；不把B代码合入C，不覆盖已有B版本。凭据只注入测试进程，不输出连接串。

```bash
python backend/tests/c_module/prepare_resource_acceptance.py \
  --source /private/tmp/c-room-options-b-source \
  --output /private/tmp/c54-combined-final
# 已注入隔离 PostgreSQL 配置，在组合 backend/ 运行。
alembic upgrade head
alembic upgrade head
CAMPUS_TEST_POSTGRES=1 CAMPUS_REQUIRE_RESOURCE_ACCEPTANCE=1 python -m pytest -q
```

首轮组合 `/private/tmp/c54-combined-round1` 连续迁移两次均成功，全量 **249 passed, 1 warning in39.10s**。随后补充可信院系异常与目录数据库故障场景，最终组合 `/private/tmp/c54-combined-final/backend` 全量 **253 passed, 1 warning in38.50s**，无skip。记录 `/private/tmp/c54-full-regression.log`、`/private/tmp/c54-final-regression.log`；警告是既有TestClient/HTTPX弃用提示，未弱化门禁或新增依赖绕过。

## 新增可观察场景

18项真实身份目录用例及1项默认关闭检查：

- 实际申请账号仅有m2.submit、空管理资源范围，目录返回campus/null和本院系；他院系/停用不计入total，过滤后分页，BIGINT保持字符串，超末页为空。
- 管理员、管理只读及普通无权身份均403；普通申请人仍不能读取管理列表/详情。伪造开发身份、权限、院系、角色和request_id不越权。
- 同一会话撤销申请能力即403但身份仍有效；停用、退出、到期后401；可信当前院系和教室enabled变动在下次读取生效。非法可信院系返回安全503，不推断资格。
- 字面搜索与最小4字段投影；成功读取没有业务/审计写入、申请或M1操作。真实B表故障在私有schema注入，安全503且独立C失败审计留存，无SQL异常回显。
- 独立Uvicorn进程经实际TCP完成登录→目录分页→管理列表拒绝→退出→目录401。应用使用真实C认证和B过滤，不是Mock认证或合成actor；不代表D浏览器或独立M1服务联调。

默认关闭检查使用B新目录实际实现；未传room_options_permission时503/identity_unconfigured，不因管理账号登录而开放。

## 兼容性、负对照与门禁

旧B审计v2 `45bcf2b` 另行在 `/private/tmp/c54-legacy-combined` 精确投影验证，准备器的固定版本仅在该独立Python调用中显式切换，未修改仓库固定新版本规则。真实登录/管理CRUD及同事务审计/撤权停用3项 **3 passed, 1 warning in1.57s**；记录 `/private/tmp/c54-legacy-regression.log`。实际旧B路由另验证未开启目录可安装、开启新能力时缺端口拒绝，且没有部分挂载或installed标记。该兼容测试不宣称旧B具备目录能力。

仅修改 `/private/tmp/c54-combined-final` 的隔离C副本，将can_choose计算改成恒真：管理/只读/无权三项真实PG用例 **3 passed → 3 failed**（错误200而非403）→逐字节恢复 **3 passed**。记录 `/private/tmp/c54-negative-control.log`，未改仓库源文件、测试预期或B过滤实现。

C独立分支在backend/运行 `CAMPUS_TEST_POSTGRES=1 python -m pytest -q`，不设置CAMPUS_REQUIRE_RESOURCE_ACCEPTANCE：**147 passed, 2 skipped, 1 warning in23.88s**。两个skip为B模块未安装时的C/B组合测试模块；专用组合CI要求B存在，不能静默跳过。记录 `/private/tmp/c54-standalone-regression.log`。

专用C/B工作流固定版本已同步4ee2fe5，请D Review单行依赖变更；目标Python3.13/PostgreSQL17、前端和Compose以本PR实际Checks为准。本机Docker NOT RUN，无Schema/迁移/运行依赖变更；原C冻结SQL和可选B未安装行为保持。

AI辅助实现/测试/文档，非作者Review及最终合并由人决定。D正式选择器/浏览器、A身份和占用#23、E通知#25、共享资源迁移与生产身份保持独立待办。
