# C-40：已批准的教室准入策略

业务依据为[负责人已确认的两项决策](../decisions/c-20261029-m2-conflict-and-room-visibility.md)，关联 #40、#24、#23。本增量实现 C 的提交资格与公开资源响应适配，不改 A/B 产品代码、表、接口路径或生产授权。

## 显式配置

在已审查的完整 C 配置中，submission 增加以下字段：

```json
{
  "room_access_policy": "campus_or_own_department",
  "allow_cross_department": false
}
```

这是 submission 的局部片段，须与已有 timezone、minimum_notice_seconds、time_granularity_seconds、max_duration_seconds 一起配置；不替其他未决的审批层级、时长、提前量或服务部署作决定。approved 模式与 allow_cross_department=true 不兼容，加载配置即失败。未指定新字段时为 legacy，继续旧配置的院系比较行为，不能作为已批准策略的验收配置。合成 runtime.synthetic.json 保持兼容，没有自动改环境配置。

资源仍通过显式 resources.base_url、room_path、token_env、timeout_seconds 读取。已验证 B v2 的 `/api/v1/resources/rooms/{room_id}`；BIGINT ID 按原契约使用十进制字符串（含大于 JS 安全整数的值），不转成浮点数。服务凭据仅在后端环境提供，申请人仍使用自己的 C 会话。

## 提交行为

| B 公开元数据 | C 行为 |
| --- | --- |
| enabled=true，access_scope=campus，department_id 明确为 null 或有效标识 | 有申请权限的主体可提交 |
| enabled=true，access_scope=department，department_id 等于认证所得院系 | 可提交 |
| enabled=true，department 范围为其他院系 | 403 DEPARTMENT_DENIED，不落申请/幂等回执 |
| enabled=false | 409 ROOM_UNAVAILABLE |
| 教室不存在 | 404 ROOM_NOT_FOUND |
| 缺失/非法 access_scope、缺失 department_id、department 范围的 null 院系，或资源服务认证/网络失败 | 503 RESOURCE_UNAVAILABLE，不猜测资格 |

enabled 必须为布尔值，非空院系标识为 1～64 字符且没有首尾空白。null 本身不等于校园级。可信院系来自 C 认证，不使用浏览器传入的角色或院系。原有 M2 权限、时段、流程和错误审计继续执行。

每次新幂等键提交重新读取 B 主数据。原幂等键/内容的重放恢复首次成功回执，即使教室随后停用或调整院系，也不会新建申请或重做业务动作；最新进度用 GET 查询。同键不同内容仍冲突。不追溯取消既有申请或预约，不因资格读取成功而宣告时段已占用。

## 普通教室列表与 M1 边界

批准的普通列表应由 B 后端过滤并分页，D 按已确认的普通身份/路径消费；#24 尚待 B/D 完成这些端口。现有资源管理读取权限不是学生目录权限，本增量没有新增普通列表 URL，也没有为申请人发放管理读权限。C 的后端服务只持有显式合成只读授权进行验收，未定义生产服务身份或令牌生命周期。

M1 遇到有效个人预约时须在同一事务/资源锁下拒绝整室来源写入；个人预约保持，不新增违约。C 已有匹配 operation_id 的 CONFLICT 映射为 APPLY_CONFLICT/effective=false，审批历史保持 PASSED。没有写 active 后补偿释放的新策略。A 当前端口、幂等和终态保护仍待 #23 真实联调，本增量没有绕过 A API 写其私有表。

## 验证

新增资格/元数据/配置与幂等用例，以及两个独立 Uvicorn 进程的实际 B HTTP 验收。测试入口受 CAMPUS_REQUIRE_RESOURCE_ACCEPTANCE=1 约束，不是部署入口；测试数据与资源表均在专用随机 schema，未给应用启动增加 create_all。

验证命令、实际结果与负对照见 [C-40 验证记录](../testing/c40-approved-room-policy.md)。无 Schema、迁移、依赖或工作流变更。AI 辅助实现与验证，B/D/A 非作者 Review 及最终合并由人类决定。
