# D63：真实教室目录与 M2 申请接入

D / jiadongchen666，2026-10-29；关联 #63、#16、#24；增量基于 D PR #45。负责人已授权继续本轮 D 页面/工程开发。源码固定：C #57 `51b65bfedd87c85cd9295fdeb01b92e9460e7c5c`（含 #55 目录身份、#36/#57 认证修复、A/C 主线汇合）；B #48 `4ee2fe5b2b221d7b5e24cd7f94ede1022a8353f3`（含审计v2和后端普通目录）。

## 页面与客户端

真实 M2 新建表单使用 `/api/v1/resources/room-options?q=...&limit=20&offset=...`，不调用管理列表。目录由 B 后端按 C 可信身份、启用状态和既定可见范围过滤后计数/分页。前端只展示 id/code/name/location，不按角色、院系null或静态enabled猜资格，不承诺时段可用。ID始终保持十进制字符串，支持大于JS安全整数的BIGINT，不经Number中转。

每页20条，搜索从第1页开始，翻页使用已经提交的搜索条件。查询/翻页立即清除选择，失败没有旧选项或合成回退；晚到查询不覆盖新查询，账号/令牌变化后旧目录不能用于提交。成功选择仅授权当前页面内存中该主体最近一次目录页；最终提交权限、当前资格与时段仍由C服务端重新检查。

`canSubmit` 表示已知身份可打开申请表单，不代表可以不选教室提交。只有最近一次当前会话目录中的选择才能通过gateway的提交前检查；UI无选择时禁用提交。申请列表读取与目录查询分开，目录失败不阻止申请记录查询。用途/时段草稿在目录搜索时保留；选择被清除后必须重新选择。

客户端校验查询参数、响应分页回显/总数、字段/ID与重复项，保留C error和B detail的安全机器码，只用固定提示。401沿用对应令牌失效，不清掉另一新会话；503/403不回退管理端或演示数据。旧`loadRooms`注入仅保留给既有隔离单元测试，正式App未使用，真实验收也没有注入它。

## 显式宿主安装

`infra/runtime/m2_resources.py` 消费 C 的 `ResourceManagementConfiguration` / `install_resource_management`；不复制或修改 C/B/A 业务源码、表或迁移。没有 `CAMPUS_RESOURCE_HOST_CONFIG` 时不安装资源适配，已有启动方式不自动启用新接口。开启时要求真实 C runtime 与 B公开模块已安装；未合并的依赖在CI隔离目录投影并逐文件校验，不能认为本前端分支已经包含它们。

在依赖经Review整合后，宿主显式设置C原配置与资源配置路径：

```sh
export CAMPUS_RESOURCE_HOST_CONFIG=/absolute/path/resource-host.json
PYTHONPATH="$PWD/infra/runtime:$PWD/backend" python -m uvicorn m2_resources:create_app --factory --host 127.0.0.1 --port 8000
```

资源配置示例（权限名必须换成团队实际批准的显式配置，不授予角色）：

```json
{
  "permissions": {
    "read": "example.resource.read",
    "manage": "example.resource.manage",
    "create_rooms": "example.resource.create"
  },
  "room_options_permission": "m2.submit"
}
```

普通目录权限与管理权限独立，未提供new_room策略，创建仍关闭。C读取B详情的服务会话只留在服务端，申请人继续用自己的Bearer；不放到VITE变量、浏览器存储或日志。正常启动不运行种子，不create_all，不更改生产角色。

## 真实验收

现有M2网络工作流固定检出C/B，并调用C已交付准备器逐文件校验B源码、生成临时组合目录和manifest。运行真实A/C迁移链两次，创建独立CI账号及合成资源：120间校园教室、1间本院系超大ID教室、1间他院系、1间停用教室。目录实际返回121间，超出100条；服务端只读会话由C真实登录获得，普通申请人管理列表必须403。

资源不再使用先前合成HTTP替身。D浏览器→C身份/B目录及C提交→B详情均为实际HTTP、真实SQL与持久化；C/B在显式统一宿主中安装，这不等于完成独立A/M1或E服务联调。M1保持未配置，最终PASSED仍effective=false。初始化脚本严格要求CI标志、GITHUB_RUN_ID和专用数据库名campus_m2_live，仅初始化合成测试数据。

Node网络验收保留响应丢失原键恢复、实际持久化、越权、两级审批、诊断及退出401，增加真实目录过滤/分页和大ID提交。[Playwright](https://playwright.dev/docs/ci-intro) 1.64.1 只作为开发测试依赖，用Chromium桌面与移动视口测试实际登录、翻到第7页、搜索空结果/本院系、选择超大ID、真实201提交、详情/进度和退出。trace/video关闭，仅保存提交后无密码/令牌的合成界面截图。

## 验证记录

- Node22：`npm run test --prefix frontend` **186 passed / 13 files**；目录与选择新增35项，保留原有进度/会话/恢复测试。
- `npm run build --prefix frontend`：浏览器和Node测试类型检查、生产构建通过。新增Playwright精确依赖及锁文件，npm安装审计0漏洞；生产包不引入Playwright。
- 本机无C/PostgreSQL，网络测试NOT RUN；Playwright本机2 skipped，NOT RUN。CI缺origin直接失败，不静默跳过。
- 隔离副本去掉翻页清空选择，定向1 failed（旧选择残留）；恢复原字节后1 passed。未改仓库为破坏版本或弱化断言。
- 初次本地回归的旧canSubmit断言仍假设管理列表预加载，已按“可打开表单但未选教室不可发POST”更新，并保留目录403/不发送POST断言。另一个新增测试误点CSS最后子元素，已改为按实际“下一页教室”按钮选择，原分页断言保留。
- infra宿主/初始化脚本Ruff与格式、AST、bash语法及diff检查通过。实际远程网络/浏览器证据见下方；后续提交以各自Checks为准。

非作者Review需B/C核对契约/显式安装，负责人检查界面。当前没有改main、合并依赖PR或发布生产。A真实身份与占用#23、E/M3迁移汇合和通知保持独立，不能用本轮目录与申请证据代替它们。AI辅助实现、验证和记录，最终决策/Review/合并由人完成。

## 实际 CI 与修正证据

首次0912184的真实目录run40836438020失败，而工程CI通过。检查发现绝对路径启动的初始化脚本未显式加入组合后端PYTHONPATH；本机路径探针也复现当前工作目录不自动加入脚本模块路径。cf59689修正该导入路径，增加仅含阶段/异常类别的错误注释，保留原业务断言与两组浏览器验收。原失败没有隐藏或删除。

固定D `cf59689c7c6323ee1f1f74229f9638d5225f6f34` 的 [真实B/C网络与浏览器push40836989287](https://github.com/ElastingYun/campus_resource_management/actions/runs/40836989287)、[PR40836993812](https://github.com/ElastingYun/campus_resource_management/actions/runs/40836993812)，以及[工程push40836989215](https://github.com/ElastingYun/campus_resource_management/actions/runs/40836989215)、[PR40836993861](https://github.com/ElastingYun/campus_resource_management/actions/runs/40836993861) 四轮均success。缺少真实origin时CI不能skip；固定源执行了真实客户端网络用例与Chromium桌面/移动两项完整流程，截图产物m2-room-options-browser已保存并取回检查。

补充第35项单元回归验证非法新查询会清除先前目录授权，同主体令牌更换也拒绝旧缓存；本机186项及构建通过。增加无申请权限的表单提示，以及浏览器翻页选择后搜索清空的断言与目录截图。最终提交的远端结果在PR中逐一核对，不沿用旧提交的绿灯。
