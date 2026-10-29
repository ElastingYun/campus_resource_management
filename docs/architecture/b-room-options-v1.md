# B 普通申请人教室目录 v1（候选接入）

关联 #47、#24、#28；B实现草稿，基于B审计v2 `45bcf2b`。可见性依据C固定`185ec81`的 `docs/decisions/c-20261029-m2-conflict-and-room-visibility.md` 已记录规则；路径与可信身份映射仍请C/D Review，不代表生产授权或整体集成已经批准。

## 可观察接口

`GET /api/v1/resources/room-options?q=示例&limit=20&offset=0`

- q可省略，最多100字符，去首尾空白，对code/name/location做不区分大小写的字面包含搜索；`%`、`_`不作为通配符。
- limit为1..100，默认20；offset>=0，默认0；按稳定id升序，先资格/搜索过滤，再count和分页。
- 响应200：`{items:[{id:"1",code:"A101",name:"示例教室",location:"示例一层"}],total:1,limit:20,offset:0}`。ID为十进制字符串，包括大于JS安全整数范围的BIGINT。
- 空结果/超末页返回items=[]；total仍为本次符合资格和搜索条件的数量，不泄露未授权行数。不提供越权详情端点。
- 只投影id/code/name/location，不返回院系、准入/开放时间、管理revision或动态可用性。目录不是提交资格或占用保证；提交仍由C重读，最终占用由A处理。
- 错误沿用B `{detail:{code,message}}`：缺可信目录身份503/identity_unconfigured；无选择权限403/forbidden；参数无效422；数据库失败503/resource_unavailable，无原始SQL或假数据回退。

## 可信身份与安装端口

B新增 `app.modules.resources.catalog.RoomOptionsActor(subject, can_choose=False, department_id=None)`，冻结dataclass。subject必须是可信非空字符串；can_choose严格bool且默认false；院系可为None，否则为1..64字符的非空规范字符串。

`create_resources_router(..., room_options_actor_dependency=...)` 接收C构造此actor的独立依赖。默认依赖直接503关闭，**现有管理ResourceActor、全域scope或X-Dev头不会开放目录**。管理router原有调用保持兼容；C现有 #34 安装没有传新依赖时，新增目录仍503。

C应每次从真实Bearer会话认证，按已确认申请/选择权限映射can_choose，并传可信当前院系，不从浏览器参数/角色名推断。具体权限名称和生产角色由C/负责人确认。C更新其安装器时显式传新依赖，不重复挂载现有router；D按实际配置挂载后才能启用选择器。B未修改C或共享App代码。

## 后端过滤规则

只有can_choose=true可查询。数据库查询固定满足：

`enabled = true AND (access_scope = 'campus' OR (access_scope = 'department' AND department_id = trusted_department))`

没有可信院系时只显示campus；campus允许nullable院系，且即使带院系也按明确campus语义处理。不能以department_id=null本身推断资格。停用资源、其他院系、未知准入标记不进入投影/总数；每次查询重读，不缓存旧资格。客户端传department_id/role/开发头不会影响可信actor或过滤。

只读、无业务commit、无新表/迁移/生产默认值；沿用B资源SQL映射。共享表所有权和正式迁移仍由A/B/C/D Review。

## 验证与限制

本机Python3.12.14/PostgreSQL16.2，统一锁定依赖；临时独立server/随机私有schema，测试结束停止并清理，不访问共享数据库。

- `pytest -q -m 'not integration'`：65 passed、19 deselected。
- 两次空库Alembic升级后，开启真实PostgreSQL的 `pytest -q`：84 passed、无skip。新增33项包括14组SQLite/PG相同行为和5项默认关闭/actor边界。
- 覆盖院系/停用过滤、过滤先于总数分页、campus/null、无院系、服务端资格变化、字面搜索、恶意头/参数不越权、权限与管理读分离、BIGINT及真实数据库错误。初次故障夹具只drop父表受PG外键保护；修正为按依赖顺序移除私有测试表后断言正常通过，未弱化错误处理要求。
- 隔离副本移除enabled过滤，定向1 failed（停用教室泄露）；逐字节恢复后1 passed。破坏版未写入仓库。
- Ruff检查/格式通过；本分支前端沿用独立基线，77测试与typecheck/build通过。CI目标Python3.13/PostgreSQL17，结果在PR留证。

**NOT RUN**：C真实普通主体到本新端口的Bearer映射、D选择器浏览器、真实学校身份和生产挂载。这里的PG/HTTP测试使用明确合成可信actor，只证明B过滤端口；不把它当作C身份集成。需C/D非作者Review后整合。
