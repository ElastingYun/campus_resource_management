# C-61：同步M1主线与A/C迁移汇合

日期2026-10-29，关联 #61、C基础PR #22/#14及后续C增量。负责人在当前项目会话明确批准：保留M1/C配置和运行入口，新增汇合迁移，不修改旧迁移历史。main固定为A #18合入后的6531430。

## 实施范围

- .env.example并存M1和C示例配置；app/main.py保留M1路由及C显式开启、生命周期，与原宿主engine共存。
- alembic/env.py保留主线Base、资源/M1模型注册和提供connection的测试入口。
- 新增0007_merge_m1_c，parents为0006_m1_seat_restrictions、0002_c_identity_approval。单head为0007_merge_m1_c，base仍0001_bootstrap；旧A/C迁移文件与冻结SQL逐字节核对不变。
- 保留A独立迁移链的完整downgrade/replay测试；组合C基线继续拒绝破坏性降级。A ORM结构比较只排除C已列名的SQL表，并独立校验C表存在与冻结账本；未知表及A漂移仍会报告。M1测试清库不再清空c_schema_migrations。
- C原0002采用/拒绝测试固定其原revision；新增完整head的空库、A库、C库、旧C库重复升级、数据保留、C降级拒绝、坏旧C账本/缺表导致的整体回滚，共7项。
- 将同一基线顺序带入后续C分支，不自动合并PR。C/B固定源投影增加database/公开种子夹具，保证新增M1 seed测试可以实际运行，不靠排除测试通过。

## 实际验证

本地Python3.13.11与专用PG16.2：

- 在backend/运行 `python -m pytest -m 'not integration' -q`：**55 passed, 135 deselected, 1 warning**。
- C基础组件（不含新的完整head矩阵）真实PG回归：**79 passed, 1 warning in14.55s**，包括原C0002采用/拒绝、生命周期与M1路由保留断言。
- Ruff/格式85文件、编译、单head/原A-C迁移字节与冻结SQL检查通过。根目录先运行unit时未加载backend配置而产生额外marker warning，已在backend/按项目命令重跑，结果仅保留既有TestClient提示。
- 本地PG16缺M1既有btree_gist扩展；官方16.2源码下载经SHA256核验，编译因本机没有开发工具未执行。完整M1/汇合迁移本地 **NOT RUN**；没有新增应用依赖、删除扩展或跳过CI中的启用用例。

基础同步提交a7cfdf0（parents=9e019f4与6531430）已通过 [Engineering push40831595606](https://github.com/ElastingYun/campus_resource_management/actions/runs/40831595606)、[PR40831600420](https://github.com/ElastingYun/campus_resource_management/actions/runs/40831600420)，共6项success。目标Python3.13/PG17日志：**unit55 passed/135 deselected；integration135 passed/55 deselected**，无skip。包括实际扩展、全部M1/C功能、新迁移矩阵和真实容器构建/断库恢复。

后续增量按各自最终head的CI核对，不用旧绿灯代替新组合验证。同步证明工程/迁移共存，不表示C Bearer已接入A、M2→M1真实写回完成或E通知已发送；#23/#24/#25继续。AI辅助实现与验证，提交身份wuyihao，A/B/D非作者Review及最终PR合并由人决定。
