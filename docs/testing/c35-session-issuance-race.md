# C-35：登录与账号变更的并发修复

日期2026-10-29，负责人C / Wuyh11，提交身份wuyihao。关联 [#35](https://github.com/ElastingYun/campus_resource_management/issues/35)、认证基础 [#22](https://github.com/ElastingYun/campus_resource_management/pull/22) 和资源适配 [#34](https://github.com/ElastingYun/campus_resource_management/pull/34)。

## 问题与行为变化

原 login 在Argon2校验前读取c_users，然后依据这一旧快照的enabled/password_hash创建会话。校验期间若另一个事务已停用账号，仍会产生未撤销的新会话；账号重新启用后该会话又可认证。凭据在此期间更新，也可能根据旧校验结果签发。

修复在真实密码校验成功后，用同一登录事务的FOR SHARE重新读取账号；当前启用状态和密码散列必须仍匹配已验证的版本。锁保持到会话与成功审计一起提交，账号管理的FOR UPDATE与之串行化。哈希计算阶段不持有账号行锁。
变更在保护区之前提交则拒绝签发，按现有401/INVALID_CREDENTIALS记录失败；变更在签发提交之后执行，停用流程会撤销刚提交的会话。失败尝试计数和登录审计仍提交，不因抛出错误而丢失。

不改API、权限/期限政策、已有迁移或Schema，不新增密码重置接口。测试中的密码散列维护只是私有schema的安全夹具；这里不定义将来密码重置对所有既有会话的产品政策。

## 真实回归与证据

新增 test_login_concurrency.py，在真实PostgreSQL事务中只控制Argon2返回与审计提交的时机，不Mock login或伪造密码验证成功。

| 场景 | 可观察结果 |
| --- | --- |
| 密码校验期间停用账号 | 原校验结果不能签发会话，重新启用后没有可复活的竞争会话 |
| 密码校验期间换为另一有效散列 | 返回INVALID_CREDENTIALS，无会话写入，失败计数/审计保留 |
| 密码校验期间散列变为无效UTF8文本 | 同样安全拒绝，不因字符串比较抛内部异常 |
| 会话和成功审计正在提交时并发停用 | 两个真实事务完成后，新会话被撤销，重新启用也不恢复 |

实际命令：

```bash
python -m pytest backend/tests/c_module/test_login_concurrency.py -q
# 修复前最初两项竞争场景：2 failed, 1 passed。
# 修复后含无效散列边界共4项；连续8轮，共32次通过。

# 固定B #28 / 45bcf2b与当前C源码的隔离组合工作区：
python -m pytest -q
# 167 passed, 1 warning in25.64s。
```

本地Python3.13.11/PostgreSQL16.2，统一依赖，合成账号/随机私有schema。保留TestClient对HTTPX的一项弃用警告。完整组合包含C既有认证、M2和B资源、真实C审计、独立TCP子进程回归；没有把合成配置当成学校身份或生产规则。

## 负对照与源代码恢复

只在 `/private/tmp/c35-combined` 的隔离C副本中移除最后的账号状态/散列复核，保持4项测试不变：原实现4通过→移除保护3失败/1通过→逐字节恢复后4通过。失败输出仅记录安全状态标记，确认session_reactivated=True，不输出会话令牌。
原始日志位于临时 `/private/tmp/c35-negative-control.log`，最初复现日志为 `/private/tmp/c-login-race-before.log`，8轮输出为 `/private/tmp/c-login-race-repeat.log`。仓库未提交破坏实现。

目标Python3.13/PostgreSQL17及Engineering/C-B验收，以本修复PR的实际Checks为准，完成后补运行链接。工作流、依赖和B文件未改；生产部署、M1 #23及通知 #25不在本修复验收范围。AI辅助分析/实现/验证，非作者Review与最终合并由人类决定。
