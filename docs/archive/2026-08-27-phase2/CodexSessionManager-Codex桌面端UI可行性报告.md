# CodexSessionManager 在 Codex 桌面端呈现 UI 的可行性报告

> 报告日期：2026-08-27
> 分析对象：`Aiyawoc/CodexSessionManager`
> 参考文档：OpenAI《Build a custom UI for your ChatGPT app》及相关 Plugins / MCP Apps 文档

## 一、结论

**整体可行，但需要明确“直接呈现”的技术边界。**

CodexSessionManager 可以新增一套基于 **MCP Apps 的 Web UI**，在支持该标准的 ChatGPT / Codex 桌面端对话中，以内嵌卡片、交互组件或全屏视图的形式呈现审查界面；但不能把现有 PySide6 / Qt 窗口原样嵌入 Codex，也不能借此向 Codex 原生界面增加永久侧边栏、固定页签或常驻窗口。

截至 2026 年 8 月 27 日，OpenAI 官方文档已经明确：

- 插件可以用于 ChatGPT 桌面端中的 Codex；
- 插件中的 Connector / MCP Server 可以包含自定义 UI；
- ChatGPT 已实现 MCP Apps UI 标准；
- 但官方尚未单独承诺所有 Codex 对话 surface 都完整渲染 MCP Apps iframe，因此仍需通过最小实机 Spike 验证。

建议将目标定义为：

> 在支持 MCP Apps UI 的宿主中直接呈现审查界面；在不支持 UI 的 Codex、CLI 或其他客户端中，自动退化为结构化结果，并继续保留“打开本地 CodexSessionManager GUI”的入口。

---

## 二、CodexSessionManager 仓库当前状态

### 2.1 代码与发布状态

当前仓库为公开 MIT 项目，默认分支为 `main`。

当前可确认的最新提交为：

```text
3e82ce274504e8f7565cc31b52ae921a73475a0e
docs: 增加v1.1.0正式发布前人工验收Runbook
2026-08-18
```

此前已经依次完成：

- `v1.1.0` 首次交付验收收口；
- 可恢复的记忆管理 MVP；
- 待处理计划 GUI；
- 待处理计划安全检查；
- MCP 编排工具与 HTTP 服务；
- 自动验收框架。

仓库源码目前定位为 **`v1.1.0` 首次交付候选**，但 GitHub Release 仍只有 `v1.0.0` 测试版，正式的 `v1.1.0` 安装包尚未发布。

还需注意：当前 `main` 最新提交未看到对应的公开 GitHub Actions 成功状态。最近可见 CI 是针对更早提交的失败运行。这不能证明当前源码仍失败，但意味着仓库暂时缺少“最新 HEAD 已由公开 CI 验证通过”的直接证据。

### 2.2 当前桌面 UI 结构

现有 UI 是 PySide6 / Qt 原生桌面窗口，主界面为 `UnifiedMainWindow`，包含：

- 对话清理；
- 上下文优化；
- 记忆管理；
- 待处理计划；
- 备份与恢复。

窗口使用左侧导航与 `QStackedWidget` 切换页面，默认尺寸为 `1600 × 900`。其界面安全原则已经明确：

> LLM 只提供建议，最终写入必须经过本地计划复核。

这套 Qt UI 无法直接作为 MCP Apps UI 使用，因为 OpenAI 的自定义组件运行在宿主提供的 Web iframe 中，资源形态必须是 HTML、JavaScript 和 CSS，而不是本地 Qt Widget。

### 2.3 当前 MCP 服务结构

现有 MCP 服务已经具备较好的基础：

- Streamable HTTP；
- `/mcp` 与 `/healthz`；
- Bearer Token；
- Origin 白名单；
- JSON Schema 输入校验；
- `structuredContent`；
- 只读盘点与建议准备；
- 密封审查请求；
- 打开本地审查 GUI；
- 查询审查请求状态。

当前注册的主要工具包括：

```text
inspect_conversation_inventory
prepare_cleanup_suggestions
open_cleanup_review

prepare_context_suggestions
open_context_review

inspect_memory_source
prepare_memory_suggestions
open_memory_review

get_pending_review_status
open_review_demo
```

服务明确不暴露归档、永久删除、上下文应用或记忆写入执行器，这与当前项目安全模型一致。

但它目前仍是一个 **仅工具型 MCP Server**：

- `initialize` 只声明了 `tools` capability；
- 主要实现 `tools/list`、`tools/call` 等方法；
- Tool Descriptor 没有 `_meta.ui.resourceUri`；
- 没有 UI Resource 注册与读取能力；
- 返回 `structuredContent`，但工具描述尚未系统声明对应 `outputSchema`；
- Tool Result 尚未承载组件专用 `_meta` 数据。

因此，当前服务可以被 Codex 当作普通 MCP 工具使用，但还不能让宿主发现并渲染 MCP Apps UI。

仓库开发计划也仍将“真实 ChatGPT 连接器、固定 Tunnel 和已安装应用端到端联调”列为未完成项。

---

## 三、“直接在 Codex 桌面端呈现”具体能做到什么

### 3.1 可以做到

通过 MCP Apps UI，可以在一次工具调用的结果位置显示：

- 内嵌卡片；
- 可交互列表；
- 表格与筛选器；
- 勾选、排除和批量调整；
- 摘要编辑；
- Diff 预览；
- 确认界面；
- 支持宿主时的全屏审查视图；
- UI 内再次调用 MCP 工具。

组件运行于 iframe，并通过 `postMessage` 上的 `ui/*` JSON-RPC 与宿主通信。组件可以接收工具输入和工具结果，也可以通过 `tools/call` 发起新的 MCP 调用。

这非常适合 CodexSessionManager 的核心交互：

- 审查候选；
- 比较内容；
- 编辑建议；
- 勾选最终目标；
- 查看计划状态。

### 3.2 不能做到

该机制不能：

- 原样嵌入 PySide6 窗口；
- 直接调用 Qt 对象或复用 Qt 控件；
- 修改 Codex 原生窗口布局；
- 给 Codex 增加永久左侧导航；
- 添加始终存在的原生 Tab；
- 在没有工具调用的情况下常驻整个 Codex 界面；
- 假设所有宿主都提供相同的宿主 API。

官方支持的呈现形态，本质上仍是与工具调用结果关联的组件，例如 inline、carousel、fullscreen 或 picture-in-picture，而不是原生桌面扩展点。

因此，不应尝试把现有五页面统一主窗口一比一搬入 Codex。更适合的交互模式是：

```text
用户提出任务
    ↓
模型调用数据工具
    ↓
模型调用对应的 Render 工具
    ↓
只显示本次任务所需的审查组件
```

---

## 四、可行性分项判断

| 目标 | 可行性 | 判断 |
|---|---:|---|
| 在 Codex 桌面端调用现有 CSM MCP 工具 | 高 | 插件、Connector 与 MCP 工具已具备明确支持路径 |
| 在 ChatGPT Chat / Work 中呈现自定义 UI | 高 | 官方已实现 MCP Apps iframe |
| 在 Codex 对话 surface 中呈现同一 UI | 中高，待实测 | 插件可用，但仍应验证 Codex surface 的 UI Host 支持情况 |
| 原样复用现有 PySide6 GUI | 极低 | 必须改写为 HTML / JavaScript Web UI |
| 复用现有业务逻辑、模型与安全门禁 | 高 | MCP Bridge、ReviewRequest、指纹与计划模型均可继续使用 |
| 完全替代本地 CSM 桌面 App | 低且不推荐 | 本地文件、备份、恢复、永久删除和诊断仍更适合原生程序 |
| 构建“Codex 内审查 + 本地安全执行”双前端 | 很高 | 与当前架构及 OpenAI MCP Apps 模式最匹配 |

Codex CLI 没有 iframe 图形界面，应走 headless 退化路径；其他不支持 MCP Apps UI 的客户端也应保持文本和结构化结果可用。

---

## 五、推荐的最终架构

```text
ChatGPT / Codex Desktop
        │
        ├── 现有数据工具
        │     ├── inspect_conversation_inventory
        │     ├── prepare_cleanup_suggestions
        │     ├── inspect_memory_source
        │     └── get_pending_review_status
        │
        ├── 新增 Render 工具
        │     ├── render_cleanup_review
        │     ├── render_context_review
        │     ├── render_memory_review
        │     └── render_pending_review
        │
        ▼
MCP Apps Web UI
        │
        ├── ui/initialize
        ├── ui/notifications/tool-result
        ├── tools/call
        └── 可选 ui/update-model-context
        │
        ▼
CodexSessionManager 核心服务
        │
        ├── ReviewRequest / SuggestionBundle
        ├── 指纹与过期校验
        ├── 服务端分页
        ├── 草稿审查状态
        ├── 不可变计划
        └── 审计记录
        │
        ├── 低风险安全操作：后续逐步开放
        └── 高风险操作：继续转入本地 PySide6 App
```

OpenAI 推荐将数据工具和渲染工具拆开：数据工具只处理业务并返回结构化数据，只有专门的 Render 工具携带 `_meta.ui.resourceUri`，避免每次数据调用都重新挂载 iframe。这与 CSM 现有工具结构高度匹配。

例如：

```text
inspect_conversation_inventory
    ↓ 返回候选 ID 与摘要
render_cleanup_review
    ↓ _meta.ui.resourceUri = ui://csm/cleanup-review-v1.html
清理审查组件
    ↓ 用户调整选择
save_cleanup_review_draft
    ↓
seal_cleanup_review
```

---

## 六、仓库需要进行的具体改造

### 6.1 MCP 协议层

应扩展当前 `McpTool` 描述模型，至少增加：

```text
output_schema
meta
security_schemes
```

工具描述需要支持类似：

```json
{
  "_meta": {
    "ui": {
      "resourceUri": "ui://csm/cleanup-review-v1.html"
    }
  }
}
```

同时建议完成：

- 为所有返回 `structuredContent` 的工具补充准确的 `outputSchema`；
- 增加 MCP Resource capability；
- 增加 UI Resource 注册与读取；
- 使用版本化 `ui://` URI；
- 返回 `text/html;profile=mcp-app` MIME；
- 支持 Tool Result `_meta`；
- 增加 UI 专用 Tool visibility；
- 为组件声明 CSP 与资源访问范围；
- 设置独立、受控的组件域名和静态资源策略。

不建议继续无限扩大手写 JSON-RPC 分发器的职责。更稳妥的方式是保留现有业务 Handler，在其外层增加标准 MCP SDK / MCP Apps 适配层，避免重写已经验收过的安全逻辑。

### 6.2 新增 Web UI 工程

建议新增：

```text
plugin-ui/
  web/
    src/
      bridge/
      components/
      cleanup/
      context/
      memory/
      pending/
    dist/
      csm-ui.js
```

开发阶段可以使用 React + TypeScript，发布时将构建后的静态资源随 Python 包或服务端一起携带，最终用户无需安装 Node.js。

### 6.3 数据与状态划分

CSM 现有安全模型非常适合 MCP Apps 的状态原则：

- **权威业务数据**：始终由 CSM 服务持有；
- **临时 UI 状态**：当前勾选、展开项、排序、筛选条件；
- **持久审查状态**：由 CSM 保存为草稿或不可变请求；
- **最终计划**：重新读取当前状态、复核指纹后生成。

浏览器中的复选框状态不能直接当作最终写入授权。

### 6.4 敏感数据隔离

不应把完整对话和记忆正文全部塞入 `structuredContent`，因为它们可能进入模型可见结果和对话记录。

更适合的设计是：

```text
structuredContent
  request_id
  总数
  分类统计
  有限候选摘要

Tool Result _meta
  UI 首屏数据
  UI 专用游标
  组件专用草稿令牌
```

详细正文通过 UI 按需调用分页工具加载。

这仍然意味着数据会经过 MCP 宿主传输，只是不进入模型上下文。因此，特别敏感或要求纯本地处理的完整内容，仍应保留在原生桌面 GUI 中。

---

## 七、各页面迁移优先级

### 7.1 第一优先级：审查状态与待处理计划

这是最简单、最安全的首个 UI：

- 当前请求状态；
- 过期时间；
- 已选择数量；
- 是否需要重新验证；
- “继续审查”入口。

适合先实现为内嵌卡片。

### 7.2 第二优先级：对话清理候选

非常适合全屏 Web UI：

- 按项目分组；
- 搜索与筛选；
- 建议理由；
- 置信度；
- 选择与排除；
- 派生后代数量；
- 计划摘要。

初版只保存审查结果，不直接执行归档。

### 7.3 第三优先级：上下文优化

可以迁移，但必须采用：

- 服务端分页；
- 虚拟滚动；
- 限制单次返回正文；
- 硬保护项不可由 UI 绕过；
- 摘要编辑后服务端再次验证。

不建议一次把整个长对话放入单次 Tool Result。

### 7.4 第四优先级：记忆管理

可以显示：

- 已登记来源；
- 分段列表；
- Keep / Delete / Replace / Protect；
- Diff；
- 版本状态。

真正的文件写入和恢复，初期仍建议留在本地 App。

### 7.5 继续保留原生界面的能力

以下能力不建议首批迁入 Codex iframe：

- age 口令输入；
- 操作系统文件选择；
- 大型备份导入；
- 逻辑恢复；
- 永久删除；
- 协议诊断；
- 本地日志与安装修复；
- 需要稳定长时间运行的任务。

---

## 八、建议的最小验证 Spike

仓库已经有 `open_review_demo`，可以在此基础上增加一个完全无敏感数据、无写入的测试链路：

```text
get_review_demo_data
render_review_demo
ui://csm/review-demo-v1.html
```

建议验证：

1. `tools/list` 能看到 Render 工具及 `_meta.ui.resourceUri`；
2. 宿主能读取 `text/html;profile=mcp-app` 资源；
3. ChatGPT 桌面端 Chat / Work 能挂载组件；
4. 组件能收到 `ui/notifications/tool-result`；
5. 组件按钮能通过 `tools/call` 调用 `get_pending_review_status`；
6. 组件中不包含 Bearer Token，也不直接访问 `/mcp`；
7. 在不渲染 UI 的客户端仍能获得完整文本和结构化结果；
8. 分别记录 ChatGPT Desktop Chat、Work、Codex 与 Codex CLI 的实际行为。

最关键的验收结果是：

```text
Codex in ChatGPT Desktop
    ├── 能渲染组件：进入正式 Web UI 开发
    └── 不能渲染组件：保持文本结果 + 唤起本地 GUI
```

所有带 UI 的工具都应保留无 UI 时仍可完成工作流的能力，并按实际能力进行特性检测，而不是仅根据客户端产品名称硬编码分支。

---

## 九、实施建议

建议采用 **“双前端、同一安全核心”** 的方案：

- **PySide6 App**：完整本地管理、高风险确认、备份恢复和故障诊断；
- **MCP Apps UI**：Codex / ChatGPT 中的轻量审查、选择、编辑和状态查看；
- **MCP 数据工具**：两套 UI 共用；
- **无 UI 客户端**：保留结构化结果和本地 GUI 退化入口。

不要将目标表述为：

> 把现有 CodexSessionManager Qt 主窗口嵌入 Codex。

更准确的目标应为：

> 为 CodexSessionManager 增加标准 MCP Apps 审查前端，在支持 MCP Apps 的 Codex / ChatGPT 桌面宿主中以内嵌或全屏组件呈现；宿主不支持时无缝退化为结构化结果和本地安全 GUI。

按当前仓库基础判断，核心服务与安全模型的复用率很高。主要新增工作集中在：

- Web 表现层；
- MCP UI Resource 协议；
- Render Tool；
- UI 与服务端状态同步；
- 宿主兼容性验证；
- 敏感数据边界与降级路径。

因此，这不是对整个项目的重写，而是为既有安全核心新增一个 Web 审查前端。

---

## 十、参考资料

### OpenAI 官方文档

- Build a custom UI for your ChatGPT app
  https://developers.openai.com/plugins/build/chatgpt-ui
- Plugins concepts
  https://developers.openai.com/plugins/concepts/plugins
- Plugins reference
  https://developers.openai.com/plugins/reference
- Codex plugins
  https://developers.openai.com/codex/plugins

### CodexSessionManager 仓库关键文件

- `README-cn.md`
- `pyproject.toml`
- `src/codex_session_manager/mcp_server.py`
- `src/codex_session_manager/mcp_bridge.py`
- `src/codex_session_manager/gui/main_window.py`
- `docs/CodexSessionManager-next-development-plan-cn.md`
- `docs/acceptance/first-delivery-v1.1.0.md`
- `docs/acceptance/formal-release-manual-v1.1.0.md`

仓库地址：

https://github.com/Aiyawoc/CodexSessionManager
