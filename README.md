# CodexSessionManager

CodexSessionManager（`csm`）是面向 Codex App 任务的安全管理工具，包含 CLI、PySide6 裁剪 GUI、显式调用 Skill、可选 PreCompact/PostCompact Hook，以及自带 Python、Qt 和 age 的 macOS `.app`。

在线读取和写入只通过官方 Codex App Server 完成；程序不会直接改写 Codex JSONL 或 SQLite。上下文裁剪始终创建派生任务，原任务不变。任何归档、恢复、导入、裁剪或永久清除都必须消费带 SHA-256 的不可变计划，并在执行前复核协议能力、内容指纹、状态和后代闭包。

## 开发环境

项目固定 CPython 3.13.14，不使用 `/usr/bin/python3`，也不向系统 Python 安装依赖。uv 会在项目隔离环境中取得并管理所需 Python：

```bash
uv sync --locked --compile-bytecode
uv run csm doctor
scripts/check.sh
```

依赖按 `runtime`、`gui`、`dev`、`build` 分组并由 `uv.lock` 锁定。Hook 和 Skill 运行期间不会执行 `uv sync`、下载 Python或安装依赖。
打包使用独立 `build/.venv-build`，只同步 `runtime + gui + build`；该位置也避免 Qt 部署扫描器把打包环境误判为应用 QML 资源。

## 日常使用

源码模式：

```bash
uv run csm --help
uv run csm threads list
uv run csm threads show THREAD_ID --include-content
uv run csm cleanup plan --older-than-days 90
uv run csm trim review THREAD_ID
```

安装后的单一分发入口：

```text
CodexSessionManager                  打开 GUI
CodexSessionManager cli ...          执行 CLI
CodexSessionManager hook precompact  执行 Hook 协议
```

用户级安装不会要求管理员权限：

```bash
scripts/install_user.sh dist/CodexSessionManager.app
~/.local/bin/csm doctor
```

安装器使用原子替换，保留上一版本用于回退。稳定路径为 `~/Applications/CodexSessionManager.app`；Hook 不引用源码目录或 `.venv`。

若要使用当前 `~/.codex` 的副本进行隔离测试，使用测试安装脚本。它会在系统临时目录创建独立的 `HOME`、`codex-home`、数据和日志目录，不覆盖真实用户安装：

```bash
scripts/install_test_app.sh
```

脚本结束时会打印测试目录和启动命令；也可以直接打开 GUI：

```bash
CSM_OPEN_TEST_APP=1 scripts/install_test_app.sh
```

可通过环境变量 `CSM_SOURCE_CODEX_HOME` 指定复制源，通过第二个参数指定一个必须为空的测试根目录。测试根目录包含 Codex home 副本，可能含认证信息，测试完成后应整体删除该精确目录。
安装阶段默认跳过外部 Codex App Server 探测，以便在没有 `codex`、uv 或 Python 的 PATH 中验证 `.app` 自带运行时；需要联调 App Server 时，在打印的测试环境变量中另外设置 `CSM_CODEX_BIN` 后运行完整 `doctor`。

## 安全工作流

典型的归档流程：

```bash
csm backup create backup.csmbackup \
  --thread THREAD_ID \
  --recipient age1... \
  --identity /secure/path/identity.txt
csm cleanup plan --action archive --older-than-days 90
csm cleanup apply PLAN.json --confirm PLAN_ID
```

- 默认 90 天未活动进入候选，单批最多 100 个根任务。
- 自动操作上限为归档；永久清除始终要求人工计划、精确计划 ID 和永久确认短语。
- 父任务操作会展开 spawned descendants；活动中、固定、临时或读取不完整的任务不会进入写计划。
- `parent_id` 与 `forked_from_id` 作为独立图边同时展开；缺失父节点、成环或多个根闭包重叠时停止写入。
- 归档至少 14 天且存在 CSM 可信归档时间和已验证加密备份后，才可能进入人工清除候选；归档证据必须与当时使用的精确备份 manifest 绑定并可在审计哈希链中验证，反归档前会先保守作废该时间凭据。
- 每个根任务永久删除前再次重读归档状态、14 天门、备份证据、loaded 状态、后台终端和本机进程。
- 写入超时后先查询真实状态，不进行盲目重试。
- 只有已审计的 Codex 版本 + 完整 App Server schema SHA-256 组合开放写入；未知协议或映射不稳定时退化为只读、备份和计划。当前写入 allowlist 固定 Codex 0.142.1 的实测 schema。

`.csmbackup` 以 tar 流直接送入 age，manifest 位于流尾。创建只使用加密临时文件，并以不可覆盖的原子发布方式生成目标；验证会完整解密、从嵌入的 `ThreadSnapshot` 重新计算 `backup_fingerprint`，再与逻辑来源和 manifest 逐项比对，但不落地明文容器。恢复第二遍解密必须再次出现所有已验证成员。只有这类全包验证结果才能写入审计链并成为归档/清除证据。口令模式由 age 直接在终端读取；GUI 和自动任务只允许 recipient-key 模式。

`CSM_CODEX_HOME` 与外部 `CODEX_HOME` 若同时设置，必须解析到同一数据根；否则所有入口（包括 Hook 管理命令）均拒绝继续，避免把一个账号的任务与另一个账号的备份/Hook 状态混合。

恢复和跨账号导入会创建新任务 ID。支持：

- CSM 加密备份的逻辑恢复；
- ChatGPT 官方导出的根到叶分支展开；
- 其他账号 Codex rollout JSONL 文件或目录；
- 完全相同跳过、已有完整前缀跳过、来源更完整优先、分叉并存；
- 未确认项目映射时导入 CSM 隔离区；工具调用只保留惰性来源信息，绝不执行或重放。

## 上下文裁剪

```bash
csm trim suggest THREAD_ID
csm trim review THREAD_ID
csm trim apply PLAN.json --confirm PLAN_ID
```

动作包括 `keep`、`exclude`、`summary` 和 `protect`。当前请求、进行中 turn、有效目标、审批决定、未解决错误、未知 item，以及相关联的工具调用/结果和文件变更/验证均受硬保护。GUI 默认按 turn 操作，item 级为高级视图；所有扫描、App Server 请求和分析均在线程池中执行。

连续前缀在 App Server 支持时使用 `thread/fork(lastTurnId)`；若当前协议没有该字段，则只在新 fork 上执行受检 `thread/rollback`。非连续裁剪创建新任务并注入带来源 manifest 的 `ContextProjection`，不会自动启动模型 turn。

## Hook

Hook 是可选功能，不会随应用安装而静默启用：

```bash
csm hook status
csm hook install --yes
csm hook uninstall --yes
```

PreCompact 先显示 15 秒轻提示；关闭、超时、崩溃、启动失败或数据目录不可写时均继续原生压缩。只有 TrimPlan 成功持久化后才输出 `continue:false`。Hook 只保存计划，不会在进行中的 turn 内创建派生任务；stdout 始终只含一个最终 JSON 对象，日志写入独立文件。

安装 Hook 后仍应在 Codex `/hooks` 中审查并信任具体命令。

## macOS arm64 构建

```bash
scripts/build_macos_app.sh
scripts/accept_macos_bundle.sh dist/CodexSessionManager.app
```

构建使用 `pyside6-deploy` / Nuitka standalone，携带 Python、Qt、Qt 插件和经 SHA-256 + Sigsum 验证的官方 age 1.3.1 arm64 二进制。项目携带一个严格校验后临时应用的 Nuitka 4.0 macOS UTF-8 路径补丁，用于满足应用位于中文路径时的启动要求；构建结束会恢复 `build/.venv-build` 中的原始 Nuitka 源码。Nuitka 成功 report 也是打包门禁，不接受 `pyside6-deploy` 遗留的部分 `.app`。

无 `CSM_DEVELOPER_ID` 时只生成 `local-adhoc` 本机构建，不宣称可公开分发。对外发布必须另行执行 Developer ID 签名、公证和 staple：

```bash
CSM_DEVELOPER_ID='Developer ID Application: ...' scripts/build_macos_app.sh
scripts/notarize_macos_app.sh dist/CodexSessionManager.app
```

V1 只在真实 Apple Silicon macOS 上构建和验收；Intel 版本必须在 x86_64 主机独立构建。
构建机需要 uv、Xcode Command Line Tools 和 Go（仅用于从固定模块版本构建 Sigsum 验证器）；这些都不会进入最终用户运行要求。

## 项目结构

- `src/codex_session_manager/`：App Server 客户端、模型、计划、备份、导入、清理、裁剪、Hook 和 GUI。
- `skills/manage-codex-sessions/`：显式调用 Skill 和安全工作流参考。
- `tests/`：假 App Server、备份边界、计划漂移、去重、Hook 和 GUI 测试。
- `scripts/`：检查、age 验证、图标、构建、安装、公证和隔离验收。
- `agent_team/`：后台独立复核的派工与整合账本。
