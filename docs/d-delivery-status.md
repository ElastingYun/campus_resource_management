# D 交付与验收说明

负责人：D / jiadongchen666；更新日期：2026-10-29。本文汇总 D 已实际交付的能力、证据和剩余主责；职责与后续顺序见 [D 开发计划](d-development-plan.md)。这是固定核对快照，不替代 GitHub 当前状态。

## 已交付能力

| 范围                | D 的实际成果                                                                                           | 证据入口                                                                                                                                 |
| ------------------- | ------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| 统一工程            | Vue/FastAPI入口、依赖锁、配置、存活/就绪探针、迁移框架、Dockerfiles/Compose、同源代理与运行说明        | [工程提案](architecture/d01-engineering-initialization-proposal.md)、[基础运行说明](development.md)、PR #8                               |
| CI与工程验收        | 前端测试/类型/构建、后端检查、PostgreSQL空库/重复迁移、容器构建、断库与恢复                            | [D03验证记录](testing/d03-quality-verification.md)、PR #9/#12                                                                            |
| M2前端              | 原型与真实模式分开；C-v1登录/身份/退出、授权列表、详情/history/actions、审批/撤销、原幂等键恢复        | [D04接入说明](architecture/d04-m2-integration-readiness.md)、[D04网络证据](testing/d04-c-v1-network.md)、PR #15/#17                      |
| 占用进度            | 审批/占用/effective分离，当前/历史代次、领取次数、安全诊断、ATTENTION核查提示、同版本重新GET           | [D43进度说明](architecture/d43-integration-progress.md)、PR #45                                                                          |
| 普通教室选择        | 同一C身份读取B普通目录，搜索、每页20条、总数、超大ID；查询/翻页/账号变化清除旧选择，服务端重读提交资格 | [D63目录说明](architecture/d63-room-options.md)、PR #64                                                                                  |
| D工程宿主与真实验收 | 显式调用C的公开资源安装器；固定C/B源码并校验，实际迁移、HTTP与桌面/移动浏览器流程                      | [运行宿主](../infra/runtime/m2_resources.py)、[验收脚本](../infra/scripts/ci-m2-c-v1.sh)、[网络工作流](../.github/workflows/m2-c-v1.yml) |

表中的 B 资源过滤、C 认证/审批/审计和 A 迁移/业务均由对应成员实现；D交付的是前端消费、工程接线及本人范围的验证，不把依赖源码或其他成员的测试计为本人实现。

## 最新固定验收版本

| 项目             | 固定版本/实际结果                                                                          |
| ---------------- | ------------------------------------------------------------------------------------------ |
| D前端与工程接线  | `4870b58a2255c3309c7ed0d05bbb9487b39f98d7`，PR #64                                         |
| C后端依赖        | `51b65bfedd87c85cd9295fdeb01b92e9460e7c5c`，含目录真实身份、登录/主体快照修复和A/C迁移汇合 |
| B公开资源依赖    | `4ee2fe5b2b221d7b5e24cd7f94ede1022a8353f3`，普通目录与审计v2                               |
| 前端本机测试     | `npm run test --prefix frontend`：186 passed / 13 files                                    |
| 类型与构建       | `npm run build --prefix frontend`：浏览器/Node测试类型检查及Vite构建成功                   |
| 真实网络和浏览器 | GitHub真实B/C/PostgreSQL17/Vite，Node网络用例及Chromium桌面/移动两项流程成功               |
| Review与主线     | PR #64 当前核对为OPEN、MERGEABLE/CLEAN、无非作者Review；不等于已合main或已部署             |

186是当前交付分支的前端全套数量，包含保留的既有模块回归，不是D个人独立编写的测试数量。网络/浏览器使用真实B/C实现和SQL，账号/教室是合成数据；没有使用资源HTTP替身，也没有接真实学校身份或宣称全系统验收。

最终固定版本的实际成功检查：

- [真实网络与浏览器 PR 40837546633](https://github.com/ElastingYun/campus_resource_management/actions/runs/40837546633)、[push 40837537820](https://github.com/ElastingYun/campus_resource_management/actions/runs/40837537820)。
- [工程 PR 40837546622](https://github.com/ElastingYun/campus_resource_management/actions/runs/40837546622)、[push 40837537822](https://github.com/ElastingYun/campus_resource_management/actions/runs/40837537822)。

这四轮工作流共8项检查成功。后续提交仍须核对自己的Checks，不能沿用旧版本结果。

## 已验证场景及实际限制

实际网络验证包括：普通用户登录、后端目录资格过滤、121间授权教室分页、其他院系/停用教室隐藏、管理列表403、大整数ID提交、真实持久化、响应丢失后同键同内容恢复、无权审批拒绝、两级审批、处理进度、退出令牌401。浏览器执行登录→翻到第7页→搜索清除旧选择→本院系教室选择→实际201→详情/进度→退出。

C/B在显式统一宿主中运行，浏览器访问及C读取B详情均实际走HTTP；这不等于独立A/M1服务验收。M1占用仍未配置，最终审批PASSED保持effective=false；D没有把“审批通过”显示成“占用已经生效”。A/C写回、M3、通知及全项目集成由对应owner推进，D只记录这些对本人前端/运行的依赖。

本机没有运行PostgreSQL或B/C服务，因此本机真实网络与两项浏览器用例为NOT RUN/skip，成功证据来自上述隔离CI。`test:integration`和`test:e2e`在CI缺真实origin时会失败；本机skip不能记为通过。trace/video关闭，只保留无密码/令牌的合成界面截图。

## 运行与验证入口

| 使用场景     | 入口与前置条件                                                                                                                                                                  |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 基础工程     | 参考 [development.md](development.md) 的初始化/探针/Compose说明；该文主要记录bootstrap阶段，不据此判断M2已经挂载                                                                |
| M2前端       | `npm ci --prefix frontend`、`npm run dev --prefix frontend`；实际登录和申请需要匹配的C/B后端、数据库及显式策略配置；`/#m2-prototype`仅合成演示                                  |
| 真实目录宿主 | [D63说明](architecture/d63-room-options.md) 的 `CAMPUS_RESOURCE_HOST_CONFIG` 与 `m2_resources:create_app`；先安装匹配C/B公开实现，默认不开启资源适配                            |
| 固定组合CI   | [m2-c-v1.yml](../.github/workflows/m2-c-v1.yml) 检出固定C/B，校验源码并创建临时组合目录；[ci-m2-c-v1.sh](../infra/scripts/ci-m2-c-v1.sh) 仅用于专用隔离CI，不是普通开发种子命令 |
| 本机前端检查 | `npm run test --prefix frontend`、`npm run build --prefix frontend`；使用锁文件和Node22                                                                                         |

当前D前端PR链为#15→#17→#45→#64，业务依赖尚未因此自动进入main。不能将“固定组合CI能运行”写成“组员仅克隆当前分支即可启动全部业务”。开发/部署时须按实际合入版本安装依赖，缺配置时如实关闭或报错。

## 失败、修正与AI协作证据

D63首次真实网络 [40836438020](https://github.com/ElastingYun/campus_resource_management/actions/runs/40836438020) 失败，随后修正初始化脚本对组合后端的PYTHONPATH，增加安全阶段错误注释；cf59689及最终4870b58均真实通过，未删除失败记录或放宽原业务断言。详情见 [D63](architecture/d63-room-options.md)。

负对照只在临时副本进行：去掉翻页清除选择，目标测试失败；逐字节恢复后通过。D43也验证了“申请版本不变时跳过进度查询”会导致测试失败。破坏代码未进入产品分支，命令和实际结果保留在对应验证文档。AI辅助实现、定位、验证与写文档，技术评论不等于非作者人工批准。

工程伦理方面，D实现了可观察的边界：不从角色名猜操作权限；不把目录可选当作时段可用；未知写入不新建键重复提交；历史DONE不覆盖当前释放意图；浏览器不存持久令牌/密码；自动重试耗尽提示核查而不强制成功。这些是本人前端与工程取舍，不替代团队业务政策或他人模块验收。

## 剩余明确主责

1. 处理D自己的M2评审意见并维护回归证据，完成主线整合后的本人页面/工程验证；非作者Review由其他成员完成。
2. 完善统一运行与部署说明，明确已合main、开发分支、固定验收环境的差异，并使选定业务版本可复现启动。
3. 推进D-06测试环境部署、镜像版本定位、健康检查及兼容范围内应用回滚演练；目标环境、凭据和发布授权明确后执行实际变更。
4. 持续维护D计划、运行和验收文档；数据库降级及业务迁移兼容性须依据owner说明，不自行改写其他模块迁移历史。

本轮文档更新只修改D的两份说明，不修改产品代码、AGENTS、README或其他成员文档；本机业务测试不重复运行，执行格式、相对链接和差异检查，自动触发的CI另按实际Checks记录。
