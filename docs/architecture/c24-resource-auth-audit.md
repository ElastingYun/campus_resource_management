# C-24：资源身份与同事务审计适配

负责人 C / Wuyh11，Git 提交身份 wuyihao。关联 [#24](https://github.com/ElastingYun/campus_resource_management/issues/24)、B 审计 v2 [#28](https://github.com/ElastingYun/campus_resource_management/pull/28)、C 基础交付 [#22](https://github.com/ElastingYun/campus_resource_management/pull/22)。日期 2026-10-29。

本增量交付 C 的适配器与真实 C/B 验证，不修改 B 的资源实现，不自动挂载资源接口、创建共享表或授予生产角色。后续负责人已批准普通申请人的校园级/本院系范围，C 的 nullable 院系适配与显式提交策略见 [C-40](c40-approved-room-policy.md)；普通列表端口、生产身份和 D 正式挂载仍待 B/D，#24 保持开放。

## 1. 对外端口及显式安装

`app.common.auth.resource_adapter.install_resource_management(application, auth, audit, configuration)` 接收 C 已有的 AuthService、AuditService 与显式配置。必须在同一应用已安装 C 的请求上下文/异常处理、B 审计 v2 模块可用之后调用；缺失、版本不符、服务实例不匹配或路由重复时拒绝安装。
安装行为供 D Review 后接入，不修改统一 create_app 的默认行为。没有 B 模块时，现有 C 应用仍可导入和运行；显式调用此安装入口会失败，不使用合成替代。

以下只是合成演示的安装结构，实际值必须来自批准的服务端配置：

```python
from datetime import time
from app.common.auth.resource_adapter import (
    NewRoomPolicy, ResourceManagementConfiguration, ResourcePermissions,
    install_resource_management,
)

component = application.state.c_runtime  # application 已显式开启 C
configuration = ResourceManagementConfiguration(
    permissions=ResourcePermissions(
        read="synthetic.resource.read",
        manage="synthetic.resource.manage",
        create_rooms="synthetic.resource.create",
    ),
    new_room=NewRoomPolicy(
        open_time=time(8), close_time=time(22), access_scope="campus",
        department_id=None, enabled=True,
    ),
)
install_resource_management(
    application, auth=component.auth, audit=component.audit,
    configuration=configuration,
)
```

`permissions` 三项全部必填；不使用角色名称或前端按钮作为授权。`new_room=None` 保持教室创建关闭；启用时开放时间、准入、院系（含显式 None）和 enabled 全部明确给出。合成校园教室的 null 不代表学生具有申请资格。

## 2. 身份与范围

- 只接受 C 的真实 Bearer 会话；每次调用 authenticate 重新读取账号启用、角色和范围，退出/过期/停用立即影响后续请求。
- 将配置的 read/manage/create_rooms permission 分别映射到 B ResourceActor。B 继续校验读权限、管理权限和创建所需的全域范围；不自动补齐缺失权限。
- all_rooms=True 才映射为 B 的 None；空 room_ids 仍为空集合。有限范围只接受规范正十进制字符串，最大 9223372036854775807；前导零、负数、浮点、非 ASCII 数字和越界值返回403，不扩大范围。
- UUID 身份直接转字符串，资源 BIGINT 直接 int/str 转换，不经过浮点或 JavaScript Number。X-Dev-*、客户端 X-Request-ID 均不参与可信身份或请求上下文。

本适配器用于同一批准应用中的公共认证接入，不提供跨实例 token introspection 或服务账号认证。M2 通过 HTTP 读取 B 的资格与服务身份问题仍单独待决，不直接查询 B 私有表来绕过接口。

## 3. 成功审计与事务

消费 B 的 ResourceMutation v2：actor_id/request_id 为规范 UUID，resource_id/room_id 为 Python 正 BIGINT，四类 action、schema_version=2、白名单 before/after JSON 字符串。C 再验证类型、版本、范围关联和快照白名单；不接受任意嵌套数据或密码等额外字段。

`AuditService.record_in_session(session, **fields)` 要求调用方已有 PostgreSQL/psycopg 事务，用该 Session 的当前连接执行 C 的已有审计 INSERT。复用同一 record 实现，不另开数据库连接，不 commit、rollback 或 close；最终事务仍由 B ResourceService 决定。成功审计不是“回调已调用”，必须随资源一起提交。

| B 字段 | C 审计字段 |
| --- | --- |
| actor_id | 可信 UUID actor_id |
| action | resources.room.create / room.update / seat.create / seat.update（均带 resources. 前缀） |
| resource_id | target=room:{id} 或 seat:{id} |
| room_id | 不失真的十进制字符串，供 C 的审计范围过滤 |
| request_id | 同一服务端 UUID，响应 X-Request-ID 与查询可关联 |
| before / after | 原白名单 JSON 字符串，保存于 changes，不复制请求体、token 或 revision |

C 不读取 B 的 rooms/seats 表来补元数据。教室事件必须 room_id=resource_id，座位所属教室由 B 已授权读写取得。普通异常、审计约束错误或最后提交失败时，B 回滚资源与 C 成功审计；有限审计读取继续按 room_id 过滤。

## 4. 拒绝、故障和错误兼容

B ResourceError 在业务回滚后独立调用 C failure 记录 request.denied，result=resources.{code}；读取权限、范围、陈旧修改和审计失败均可追踪，不产生成功资源审计。失败元数据不带请求体或秘密；room_id 未获可信确认时不推断归属，此类记录按现有规则只对全域审计权限可见。

B 错误保留 `detail: {code, message}`，附 request_id；C 认证/输入错误仍使用 C-v1 的 error 包装。两者均保留 X-Request-ID 和 no-store；不回显 SQL 或内部异常。如果独立失败审计也不可用，返回503/audit_unavailable，不假报审计成功。

## 5. 验证来源与部署边界

新增 C/B 验收工作流固定读取 B #28 的 `45bcf2be8fbc7cee5f97b75aec4be7d061d5ff8a`，逐文件核对 Git blob 与实际源码字节，只在隔离目录投影公开资源模块/测试；C 来源为当前 PR 的实际检出，清单记录两侧版本及 SHA256。没有把未合并的 B PR 并入当前分支或改写对方文件。
如果未来当前分支已包含 B 的对应目录，仅在文件集合和字节与固定版本完全一致时使用；不覆盖已有实现。B 升级时须显式更新固定依赖并重新验证，不能静默混用不同版本。
普通 Engineering CI 不具备 B 时明确跳过组合模块验收；专用工作流设置必需标记，缺 B 源码直接失败。它使用 PostgreSQL17、当前 C 迁移、B/C 全套回归及独立 Uvicorn 子进程的真实 TCP 登录/资源写入/审计/退出验证。

测试只在随机私有 schema 中建立 B 的测试表，C 表来自冻结迁移；应用启动不建表。此结果证明固定 B v2 与 C 的模块/HTTP/事务兼容，不等于共享资源迁移已合入、D 正式浏览器链路或生产政策已验收。具体结果见 [C-24 验证记录](../testing/c24-resource-integration.md)。
