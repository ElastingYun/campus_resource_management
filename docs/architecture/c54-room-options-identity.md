# C-54：普通教室目录的真实身份接入

关联 #54、#24、B #47/[PR #48](https://github.com/ElastingYun/campus_resource_management/pull/48)、D #16。消费 B 固定 `4ee2fe5b2b221d7b5e24cd7f94ede1022a8353f3` 的独立目录端口；业务依据为[2026-10-29 批准规则](../decisions/c-20261029-m2-conflict-and-room-visibility.md)。

## 安装与权限

在现有 C 请求上下文和 B 资源路由安装处，显式增加配置：

```python
configuration = ResourceManagementConfiguration(
    permissions=ResourcePermissions(
        read="synthetic.resource.read",
        manage="synthetic.resource.manage",
        create_rooms="synthetic.resource.create",
    ),
    room_options_permission="m2.submit",
)
install_resource_management(
    application, auth=component.auth, audit=component.audit,
    configuration=configuration,
)
```

这是合成权限名称的安装示例；管理权限仍使用宿主已批准的显式配置。`room_options_permission` 默认 None，目录不开放；当前只允许显式值 `m2.submit`，对应已有申请能力，不接受把管理 read 配置成目录许可。此配置不创建或授予角色，不重挂第二份 router，不自动修改 App 工厂或生产环境。

开启时，安装器要求 B 的 RoomOptionsActor(subject, can_choose, department_id) 与 room_options_actor_dependency 端口存在，否则启动拒绝，不以管理身份回退。未开启时不传新依赖参数，保留旧 B 审计v2管理端口兼容；旧 B 没有目录路径，新 B 的默认目录身份返回503关闭。

## 每请求可信映射

目录每次调用真实 AuthService.authenticate，读取当前账号、角色能力、院系和会话状态，生成服务端 actor_id。subject 为认证 UUID 字符串；can_choose 仅来自当前 m2.submit；department_id 来自当前持久身份。请求参数、开发头、角色名称和浏览器提供的院系不能覆盖它们。

普通目录与管理资源身份独立：管理read、all_rooms或room_ids不会隐式授予选择权；已获申请能力且room_ids为空的普通主体可按已批准的校园级/本院系规则选择，不把管理范围变成全域授权。目录成功也不会授予管理列表/详情读取或写入权限。

注销、会话到期、账号停用立即令后续目录请求401；撤销m2.submit后同一有效会话403，登录状态本身仍可查询。可信院系变化在下一次请求生效。当前C身份要求非空规范院系；无效持久院系安全返回503/RESOURCE_IDENTITY_UNAVAILABLE，不推断校园级资格，不暴露原始值。此处没有新增院系维护API或统一学校登录。

## D 可消费的路径与错误

`GET /api/v1/resources/room-options?q=...&limit=20&offset=0`，使用同一 C Bearer。响应 `{items:[{id,code,name,location}],total,limit,offset}`；id为十进制字符串，不经JS Number。limit1..100，offset>=0；q最多100字符的字面包含搜索。

B在数据库按enabled与campus/可信本院系过滤后计数和分页，按ID升序；空页items=[]，total不包含其他院系/停用资源。响应只投影4个字段，不提供院系、管理revision、开放时段或动态可预约承诺；分页期间数据仍可能变化，提交须继续走C-40后端重读资格，最终占用由M1确认。

| 场景 | 响应 |
| --- | --- |
| 未开启目录，使用支持目录的B | 503，B detail.code=identity_unconfigured |
| 开启后无会话、无效/终止会话 | 401，C error.code；与原C认证错误一致 |
| 当前会话没有m2.submit | 403，B detail.code=forbidden |
| 查询参数非法 | 422，沿用既有参数验证 |
| 可信目录身份数据非法 | 503，C error.code=RESOURCE_IDENTITY_UNAVAILABLE |
| B读取失败 | 503，B detail.code=resource_unavailable |
| 拒绝审计不可用 | 503，B detail.code=audit_unavailable |

沿用服务端 request_id/X-Request-ID 和 Cache-Control:no-store；D应按C error或B detail封装识别错误，不从原始异常猜成功。B拒绝/读取故障通过已有独立失败审计记录，成功只读不生成虚构业务操作或审计写入。

## 验证与未完成项

验证见[C-54测试记录](../testing/c54-room-options-identity.md)。固定B公开模块/测试只投影到隔离目录，不合入C产品分支；专用验收工作流的B固定版本同步更新，请D Review。无Schema、迁移、依赖或A/B产品改动，原C SQL与公开C OpenAPI保持。

D需Review后在宿主显式安装本配置，再实现真实分页选择器与浏览器验收；本增量不直接改D页面。B目录的真实C身份与HTTP已由本增量测试，不代表A/M1 #23、E通知#25、共享迁移、生产身份或最终拓扑已完成。AI辅助实现/测试/文档，非作者Review与最终合并仍由人决定。
