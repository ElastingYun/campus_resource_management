# B 资源管理：可信账号与未知写入生命周期修复

关联 #51、#19、C接入 #34。独立增量基于D/B已整合的 `490e4f6`，不包含B预约新功能栈或后端审计v2分支；不改C/D入口或后端。

## 问题与结果

旧资源页的uncertain属于当前表单，关闭/重开或销毁组件后会丢失阻止新写入的状态；账号变化也没有清理查询。新 `createResourceSession(gateway, identity)` 由应用外壳创建一次，按可信主体保留编辑/结果和待核对目标。

- `identity.currentActorId()` 与 `identity.canManage()` 必须来自和gateway请求包装器相同的C可信会话；不读取客户端身份头/角色名，不存储token。
- live视图必须传 `resourceSession`，且session.gateway与props.gateway为同一对象。缺长期session、主体或配置不匹配时真实读取/写入关闭，旧allowManage=true不能单独启用live。
- 管理能力每次操作前复核；这是UI门控，后端仍负责read/manage/create与房间scope的最终检查。未知角色/生产权限名称不在B自行决定。
- 保留未提交草稿、原目标/版本、保存状态和确认结果；旧flow不能被新账号提交。写入冻结原内容，禁止双击；返回资源必须匹配原ID（编辑时）、编号、字段与所属教室，否则未知。
- 明确无副作用拒绝可改输入；超时、网络、坏响应、身份变化或未分类异常保持未知，不显示成功、不自动重放。
- 未知时“关闭表单并核对列表”只隐藏编辑器；pending与原目标保留，新写入继续关闭，只能读取列表核对或联系管理员。clearSettled不会清理unknown、在途操作或未提交表单。

当前资源写入没有稳定操作ID/幂等恢复协议。即使列表看起来符合输入，也不能自动证明是哪次写入；本轮没有新增“强制重试/清除未知”按钮或猜测解决状态。后续可由B/C明确可信结果查询后再做自动解除；现在不拿刷新、关闭表单或新建session冒充恢复。

## 宿主接线与视图行为

在路由组件外创建一次ResourceSession，传入 `ResourceWorkspace` 的resourceSession与同一gateway。安装 `protectResourceSession(session)`，应用销毁时调用其清理函数；视图不存在时beforeunload仍保护所有主体pending。资源视图也发出resourcePending布尔事件供宿主汇总提示，但不能用布尔值重建flow。

组件卸载只取消本视图只读查询，不中断宿主写入。无视图时成功结果可完成并在返回后显示；未知仍保留。账号或管理能力变化会清空查询、取消请求、递增代次；旧响应即使A→B→A后返回也不能覆盖当前结果。B账号不显示A草稿/未知目标；A返回同一session恢复自己的状态。权限撤回时隐藏编辑器并阻止提交。

有长期session可在内部hash导航后返回；外部离开和完整刷新有pending提示。内存无法跨真正刷新/关闭进程持久恢复；宿主不得为切页/账号切换重建session。合成原型本地session仍明确标注，刷新重置；不回退真实模式假数据。

## 实际验证

本机Node24.19.0，独立基线全量前端 `npm run test` **93 passed**（新增16），typecheck/build通过。基线较B-06不同，不能把93说成从212减少测试；本增量只包含原资源/搜索工作区。

新增9项session、7项真实组件生命周期测试：未知关闭后仍阻止新写入、冻结内容与双击、主体隔离、账号变化前后响应、权限撤回、坏确认结果、清理保留pending、视图不存在时unload，以及mount→unmount→mount与无视图在途保存完成。原25项资源测试保留通过。

负对照仅隔离副本：关闭编辑器时清掉uncertain → 定向1 failed（clearSettled丢失原flow/目标）；逐字节恢复后1 passed。破坏版未提交。沿用依赖和Node22工程门禁，CI证据在PR补齐。

**NOT RUN**：C真实身份/管理范围到本新session的浏览器接线、D共享路由组合、真实学校身份及生产部署。Vue合成gateway不计真实C集成；C #34的真实后端审计验证不能替代本UI生命周期验收。请C/D非作者Review，最终由人决定合并。
