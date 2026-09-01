# AGENTS.md

本文件只保留 CodexSessionManager 的项目级硬约束、现行文档入口、验证流程和发布规则。开发细节写入 `README-cn.md`、`README.md`、Skill 参考文档或对应模块测试；不要把单点事故和临时排障记录堆入本文件。

## 基础约定

- 项目固定使用 CPython `3.13.14` 和 uv 管理环境；禁止使用 `/usr/bin/python3`、系统 Python、全局 pip 或 `sudo pip install`。
- Codex 任务在线读取和写入只能通过官方 App Server；禁止直接修改 Codex JSONL、SQLite、认证文件或 Codex 配置。
- 归档与反归档必须先生成不可变计划，并在执行前复核 SHA-256、能力指纹、状态、内容指纹、计划有效期、账号根、已验证备份和后代闭包；读取、备份和生成计划默认可用。
- 当前边界是版本无关、契约敏感：五项最小操作契约由静态规则定义并人工复核，运行时不自动学习或扩大写入语义。
- 当前 Codex 版本、二进制散列和全量 schema 散列是诊断与计划失效证据，不是归档授权条件。
- 归档与反归档由静态、人工复核的最小操作契约逐项评估。
- 无关变化自动兼容；相关方法/字段/关键枚举不兼容时只关闭受影响操作。
- App Server 协议或某项契约未知、不完整或映射不稳定时，只关闭受影响操作并输出具体原因；其它读取、备份、验证和计划能力继续可用。
- 当前上下文能力仅限审查与投影计划；原任务应用不可用，派生投影在完整真实 round-trip probe 通过前保持阻塞。未来若重新开放执行，只能创建受支持的派生任务并保持原任务不变；不得通过编辑原始 JSONL 或 SQLite 伪造裁剪结果。
- 父任务归档或恢复前必须展开并备份全部 spawned descendants；发现缺失父节点、环、闭包重叠或内容不完整时停止写入。
- 第一版任务管理只提供盘点、备份、批量归档和反归档；不提供永久删除的资格盘点、计划、GUI、CLI、Skill、MCP 或执行器。上游 schema 中存在删除方法不构成 CSM 能力授权。
- 写入超时后先查询实际状态，禁止盲目重试；任何不确定结果都按“可能已完成”处理。
- 备份使用 age 加密和原子发布，不包含 Codex 认证、项目源码或未授权配置；口令不得进入模型上下文、参数、环境变量、日志或提交。
- `CSM_CODEX_HOME` 与 `CODEX_HOME` 同时设置时必须解析到同一数据根；否则所有入口拒绝继续。
- PreCompact Hook 失败、关闭、崩溃、启动失败或超时必须继续原生压缩；默认 fail-open。只有计划已成功持久化、用户明确选择严格审查且所有当前能力/指纹门禁通过时才允许输出 `continue: false`。

本项目代码完全由 ChatGPT 生成，但每次修改仍必须经过人工审查、自动化测试和目标环境验证。假服务器、offscreen GUI 和本机构建不能称为真实账号、真实输入或生产验收。

## 修复、分支与提交

- `main` 是当前唯一事实来源。未被用户明确要求时，不创建、推送、合并或发布分支。
- 开始工作先检查 `git status --short` 和目标文件差异；保留已有无关修改，禁止用 `git add -A`、`git commit -a` 或重置命令扩大或覆盖用户改动。
- Bug 修复必须先定位实际协议、数据、线程或 UI 生命周期，再补对应回归测试；不要以静态检查代替运行时证据。
- 修改生成文件时同时更新其源文件，并使用生成命令重新生成；提交前检查生成结果可重复。
- 用户明确要求提交时，使用聚焦的中文 Conventional Commit；未明确要求时只保留工作区修改，不自动提交、推送或创建 PR。
- 提交前执行 `git diff --cached --check`，检查 `git diff --cached --name-status` 和统计；提交后确认工作区及无关路径状态。

## 文档与模块入口

- 领域语言与关系：`CONTEXT.md`；长期架构决策：`docs/adr/`。
- 版本无关操作契约：`docs/adr/0011-version-independent-operation-contracts.md`；ADR 0001 仅在精确画像授权部分被局部取代。
- 用户工作流、安装和安全说明：`README-cn.md`；英文说明：`README.md`。
- App Server 操作契约人工审查：`docs/acceptance/app-server-schema-approval.md`。
- v1.0.1 历史真实账号人工验收：`docs/acceptance/macos-real-account-v1.0.1.md`。
- v1.1.0 首次交付验收：`docs/acceptance/first-delivery-v1.1.0.md`。
- Python 版本、依赖组和锁文件：`.python-version`、`pyproject.toml`、`uv.lock`。
- Skill 使用入口：`skills/manage-codex-sessions/SKILL.md`。
- Skill 安全不变量：`skills/manage-codex-sessions/references/safety.md`。
- Skill 命令工作流：`skills/manage-codex-sessions/references/commands.md`。
- App Server 客户端和能力门禁：`src/codex_session_manager/app_server.py`。
- 操作契约规则与只读差异报告：`src/codex_session_manager/operation_contracts.py`、`src/codex_session_manager/schema_audit.py`（后者仅生成只读报告）。
- 不可变模型、指纹和计划：`models.py`、`hashing.py`、`plans.py`。
- 盘点、清理、备份、导入和裁剪：`inventory.py`、`cleanup.py`、`backup.py`、`importing.py`、`trim.py`。
- CLI/GUI/Hook 共用编排边界：`workflows.py`；脱敏人工验收证据：`acceptance.py`。
- Hook 和 standalone 分发入口：`hooks.py`、`dispatcher.py`、`config.py`。
- 审查请求与 MCP 只读编排边界：`review_requests.py`、`mcp_bridge.py`、`mcp_server.py`；MCP 不暴露归档/反归档执行器、永久删除、裁剪应用或记忆写入执行器。
- PySide6 GUI：`src/codex_session_manager/gui/`；测试：`tests/`；构建、安装和验收：`scripts/`。

保持模块边界：App Server 客户端只负责协议和能力探测；领域服务不依赖 Qt；GUI、CLI、Skill 和 Hook 共用模型、计划、指纹和安全校验；任何入口都不得绕过计划层直接写入 Codex 数据。

## Python 与编码规范

- 使用完整类型标注，目标版本为 Python 3.13；遵守 Ruff 和严格 mypy。修改依赖后必须更新 `uv.lock`。
- 领域 Pydantic 模型默认冻结并拒绝未知字段；不得通过未经校验的可变字典绕过指纹或计划校验。
- 用户数据、计划和审计文件使用项目已有的私有权限与原子写入工具；不要自行实现不安全的覆盖写入。
- 大型 JSONL、备份和附件必须流式处理并使用有界缓存；不得为方便测试一次性加载整个用户数据根。
- 未知 item、字段或协议能力必须保留并标记，或退化为只读；禁止猜测语义后执行写入。
- 工具调用及结果、文件变更及验证必须整体保留或整体摘要，不能拆开后只删除其中一半。
- 内容 AI 建议默认关闭；只有用户显式允许且数据边界明确时才能启用，输出必须标记为建议。

## PySide6 与 UI

- UI 与业务逻辑分离。主线程只负责 Qt 事件和渲染；文件扫描、App Server 请求和分析必须放入 Worker/线程池。
- Designer 源文件位于 `src/codex_session_manager/gui/*.ui`。修改 `.ui` 后必须用 `pyside6-uic` 重新生成对应 `ui_*.py`，禁止手工编辑生成文件：

  ```bash
  uv run --locked pyside6-uic \
    src/codex_session_manager/gui/main_window.ui \
    -o src/codex_session_manager/gui/ui_main_window.py
  ```

- GUI 默认目标尺寸为 `1600x900`，最小尺寸为 `1280x720`；最左侧保留固定功能栏，项目与任务面板可收起，收起后时间线第一列自动填满剩余宽度，时间线与原文之间的 QSplitter 可拖动；左侧使用同一输入框搜索项目/对话或输入完整对话 ID，列表支持多选与安全批量操作；保持键盘焦点、可读对比度、风险提示和禁用状态清晰。
- 统一主题放在 `gui/theme.py` 或 Qt 样式资源中，不要在控制器中散落颜色和尺寸常量。
- 新增交互必须补 GUI 回归测试；大文件时间线使用分页、流式解析和有界缓存。
- GUI 备份仅使用 age recipient 与本地 identity 完整复验；成功后只建立审计证据，不得隐式归档。归档仍需独立计划和确认。
- 离屏预览可以验证布局，但不能替代真实 macOS Cocoa 窗口、缩放和用户输入验收：

  ```bash
  QT_QPA_PLATFORM=offscreen uv run --locked python scripts/render_gui_preview.py \
    --output artifacts/gui-preview.png
  ```

## CLI、Skill 与 Hook

- 源码入口为 `src/codex_session_manager/cli.py`；standalone 统一入口为 `dispatcher.py`：

  ```text
  CodexSessionManager                  打开 GUI
  CodexSessionManager cli ...           执行 CLI
  CodexSessionManager hook precompact   执行 PreCompact Hook
  CodexSessionManager hook postcompact  执行 PostCompact Hook
  ```

- `manage-codex-sessions` 只在用户显式调用 Skill 或明确要求使用时运行；普通代码任务不得自动触发清理、恢复、导入、裁剪或 Hook 安装。
- Hook 必须指向平台稳定安装路径：macOS 为 `~/Applications/CodexSessionManager.app`，Windows 为 `%LOCALAPPDATA%\CodexSessionManager`；禁止指向源码、`.venv` 或 uv。stdout 只能输出最终 JSON，日志写入独立文件。
- Hook 使用 `session_id + turn_id + trigger` 去重，总超时 600 秒、内部截止 540 秒；Hook 模式只保存计划，不在进行中的 turn 内创建派生任务。
- Hook、归档/反归档和裁剪计划前先运行 `doctor`，再执行 dry-run/plan；恢复/导入仅生成计划，不写入 Codex；不得把用户确认隐含为授权。

## 测试与验收

提交前至少运行：

```bash
scripts/check.sh
```

该脚本会重新生成并比较 `.ui` 输出，运行 Ruff、严格 mypy、offscreen pytest 和 Skill 校验。需要局部检查时可运行：

```bash
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked mypy src/codex_session_manager
QT_QPA_PLATFORM=offscreen uv run --locked pytest
```

需要验证完整源码入口时运行 `scripts/test_source_workflow.sh`。涉及安装、Skill 或 Hook 时，分别运行 `scripts/test_install_workflow.sh`、`scripts/test_skill_workflow.sh` 或 `scripts/test_hook_workflow.sh`；这些脚本只使用空白临时 `HOME` 和 `CODEX_HOME`，不得改为复制真实 Codex 数据。完整 macOS 流程运行：

```bash
scripts/test_full_workflow.sh
```

完整流程默认从当前源码重新构建，并依次执行源码门禁、bundle 验收、真实 age 临时生命周期、安装、Skill 和 Hook 流程。`--reuse-app` 只用于已有可信 bundle 的快速本地 smoke，不得作为发布验收。

涉及 standalone `.app` 时，在真实 Apple Silicon macOS 上运行：

```bash
scripts/build_macos_app.sh
scripts/accept_macos_bundle.sh dist/CodexSessionManager.app
```

涉及 Windows standalone 时，在真实 Windows AMD64 或 GitHub `windows-latest` 上运行：

```powershell
.\scripts\check_windows.ps1
.\scripts\build_windows_app.ps1 -Version VERSION
```

Windows bundle 构建还必须执行 `scripts/test_windows_install_workflow.ps1`，覆盖临时 `%LOCALAPPDATA%`、重复安装、中文空格路径、无 Python/uv/age PATH 和 Hook 安装/卸载。Apple Silicon CI 使用 `macos-15` 并显式断言 `arm64`；bundle 验收只接受当前源码的 fresh build。

验收至少覆盖内置 Python、PySide6、Qt 插件、age 校验、无 Python/uv 的运行、中文或空格路径和可写用户目录。隔离测试使用 `scripts/install_test_app.sh`；其复制的 Codex home 可能包含认证信息，结束后只删除脚本打印的精确 `TEST_ROOT`。第一版验收只覆盖明确提供的能力，不得增加永久删除测试或绕过 App Server。

报告结果时区分测试层级：单元测试、假 App Server、offscreen GUI、本机构建和 bundle 验收只能证明对应层级；真实账号联调、真实用户输入、签名公证和生产验收必须单独标明证据。

## 桌面构建与发布

- macOS arm64 只在真实 Apple Silicon 主机构建；Intel 版本必须在 x86_64 主机独立构建。Windows x64 只在真实 Windows AMD64 或 GitHub Windows runner 构建，不以本机模拟代替目标平台验收。
- 使用 `pyside6-deploy` / Nuitka standalone，不改为 onefile；最终用户不应依赖 Python、pip、uv、Homebrew 或系统 age。
- age 使用对应平台固定版本的官方二进制、校验信息和许可证；构建时完成 SHA-256 与 Sigsum 校验，运行时禁止联网下载。
- 未签名 Windows 或 ad-hoc 签名 macOS 产物，只有在用户明确要求时才能作为 GitHub prerelease 测试版发布；标题、说明、文件名和 bundle 通道必须明确标为测试、未签名/未公证，且不得宣称生产可用。
- 正式公开分发的 macOS 产物必须使用 Developer ID 签名、公证并 staple；Windows 正式产物必须使用适当的 Authenticode 证书签名。测试版例外不改变正式发布门禁。
- 发布前执行 bundle `doctor` 和验收；升级先验签和自检，再原子替换稳定路径，并保留上一版本用于回退。
- Hook 永远指向稳定安装路径，不得指向带版本号目录、源码目录或开发环境。

## 文档维护

- 处理模块问题时，先检查本文件与 README、Skill 参考和测试是否冲突；以当前实现、`scripts/check.sh` 和实际 bundle 验收结果为准，并同步修正过期说明。
- 用户要求整理优化代码并提交时，盘点本次变更涉及的 README、Skill、测试和生成 UI 文件，保持文档与实现一致。
- 新增安全边界、安装坑或验收限制时，优先补充到 README 或 Skill 专题文档；`AGENTS.md` 只保留跨模块入口、强制流程和稳定硬约束。
- 不要把未验证的账号、平台、协议版本、性能数字或发布状态写成已确认事实。
