# v1.1.0 本机两步受控验收计划

本计划用于在维护者自己的 macOS Apple Silicon 机器上，对当前 CodexSessionManager
候选执行一次可回滚的真实账号验收。它把验收严格分成两步：

1. 只读盘点、协议审计和 MCP/GUI 请求链检查；
2. 在停止 Codex、完成并复验排除认证文件的 .codex 数据加密回滚快照后，只对已经确认属于本项目的
   少量任务执行真实归档、对话标题修改、记忆文件修改，以及用户明确单选的一个已归档根的永久删除；上下文只验收审查、投影计划和源任务保护，跳过应用执行。

本计划不是生产发布，也不是把 .codex 打包给其他机器。.codex 快照仍可能包含真实对话
和其他敏感数据，但脚本会排除根目录认证文件（`auth.json`、`credentials*.json`、
`oauth`、`tokens`），因此恢复快照不会恢复登录态。快照只能留在本机受控目录中。
禁止把快照、identity、真实正文或认证文件放入 ZIP、Git、Issue、MCP 返回值或共享盘。

## 0. 一次性准备

以下变量中的仓库路径按当前 checkout 填写；不要把它们改成另一个项目。稳定安装器
完成后，CSM CLI 使用稳定启动器，Codex desktop 的 MCP 也使用同一个启动器。

~~~bash
set -eu
export CSM_REPO_ROOT="/Users/ethen/同步空间/CODE/AI/CodexSessionManager"
cd "$CSM_REPO_ROOT"

export CSM_PROJECT_ROOT="$CSM_REPO_ROOT"
export CSM_CLI="$HOME/.local/bin/csm"
export CSM_EVIDENCE_DIR="$CSM_REPO_ROOT/build/local-controlled-$(date +%Y%m%d-%H%M%S)"
mkdir -m 700 -p "$CSM_EVIDENCE_DIR"
test -x "$CSM_CLI"
~~~

如果稳定启动器尚未安装，先在已确认的 fresh bundle 上安装；这一步不接触对话写入：

~~~bash
CSM_APP="$CSM_REPO_ROOT/dist/CodexSessionManager.app"
test -d "$CSM_APP"
CSM_INSTALL_SKIP_APP_SERVER=1 \
  "$CSM_REPO_ROOT/scripts/install_user.sh" "$CSM_APP"
test -x "$HOME/.local/bin/csm"
~~~

不限制 Codex CLI 的版本用于读取、备份和生成计划。但真实写入仍必须命中 CSM 人工
批准的精确 App Server schema 画像；不能用版本范围、跳过检查或环境变量绕过这一门禁。

## 第一步：只读基线和请求链

这一阶段不归档、不删除、不恢复、不裁剪、不修改记忆文件，也不直接打开 Codex
JSONL、SQLite 或认证文件。MCP 的配置和“打开审查窗口”只会改变 CSM 私有请求队列，
不会改变 Codex 对话；需要严格纯只读时只调用下文列出的 inspect/status 工具。

### 1.1 记录环境和协议画像

~~~bash
git -C "$CSM_REPO_ROOT" rev-parse HEAD > "$CSM_EVIDENCE_DIR/candidate-sha.txt"
git -C "$CSM_REPO_ROOT" status --short > "$CSM_EVIDENCE_DIR/worktree-status.txt"
"$CSM_CLI" version > "$CSM_EVIDENCE_DIR/csm-version.txt"
"$CSM_CLI" doctor > "$CSM_EVIDENCE_DIR/doctor.json"
"$CSM_CLI" schema audit \
  --output "$CSM_EVIDENCE_DIR/schema-audit.json"
"$CSM_CLI" audit verify > "$CSM_EVIDENCE_DIR/audit-verify.json"
~~~

人工确认 doctor 和 schema-audit 的以下字段：

- Python、PySide6、Qt、Qt 插件、age、age-keygen、可写 CSM 私有目录和 App Server 检查通过；
- schema 完整；
- exact_profile_match、conclusion、write_enabled 与实际批准状态一致；
- unknown 或 incomplete schema 时，记录报告并停止所有 Codex 写入；
- 当前候选的 production_ready 永远为 false。

如果当前 Codex 版本没有对应的精确人工批准画像，第一步仍可继续读取和备份，但第二步
只能做到备份和生成计划，不能进入真实归档、删除或对话修改。

### 1.2 只读盘点并锁定项目范围

~~~bash
"$CSM_CLI" threads list \
  --project "$CSM_PROJECT_ROOT" \
  > "$CSM_EVIDENCE_DIR/project-threads.json"
"$CSM_CLI" memory sources \
  > "$CSM_EVIDENCE_DIR/memory-sources.json"
~~~

从 project-threads.json 中人工选择最多三个任务 ID，分别作为后续的
ARCHIVE_THREAD_ID、EDIT_THREAD_ID、TRIM_THREAD_ID。每个 ID 都必须满足：

- cwd 与 CSM_PROJECT_ROOT 完全一致；
- 不是 pinned、ephemeral 或 active；
- 父任务和 spawned descendants 能在同一份盘点中完整展开；
- 只记录 ID、状态、标题摘要、cwd、更新时间和 descendants，不复制正文。

每个候选都必须再次执行：

~~~bash
export ARCHIVE_THREAD_ID="从 project-threads.json 手工复制的精确 ID"
export EDIT_THREAD_ID="从 project-threads.json 手工复制的精确 ID"
export TRIM_THREAD_ID="从 project-threads.json 手工复制的精确 ID"

"$CSM_CLI" threads show "$ARCHIVE_THREAD_ID" \
  > "$CSM_EVIDENCE_DIR/archive-thread-before.json"
"$CSM_CLI" threads show "$EDIT_THREAD_ID" \
  > "$CSM_EVIDENCE_DIR/edit-thread-before.json"
"$CSM_CLI" threads show "$TRIM_THREAD_ID" \
  > "$CSM_EVIDENCE_DIR/trim-thread-before.json"
~~~

若任一 cwd 不等于本项目、ID 不存在、闭包不完整或状态不安全，立即清空变量并停止
写入验收；不要改用“看起来相似”的任务。

### 1.3 Codex desktop 本机 MCP 验证（严格只读与编排 smoke 分开）

Codex desktop 通过 ~/.codex/config.toml 启动本机 stdio MCP，不需要 HTTPS、Tunnel、
Bearer token 或外部服务。若已存在同名配置，不要覆盖，先在 Codex desktop 的 MCP
设置中确认其 command 和 env 是否正是本次验收环境。

在命令行配置本地 MCP 时使用官方 Codex CLI 的配置写入入口：

~~~bash
export CSM_CODEX_BIN="$(command -v codex)"
test -x "$CSM_CODEX_BIN"
CODEX_HOME="$HOME/.codex" "$CSM_CODEX_BIN" mcp add codex_session_manager \
  --env "CODEX_HOME=$HOME/.codex" \
  --env "CSM_CODEX_HOME=$HOME/.codex" \
  --env "CSM_DATA_DIR=$CSM_REPO_ROOT/build/local-csm-data" \
  --env "CSM_CONFIG_DIR=$CSM_REPO_ROOT/build/local-csm-config" \
  --env "CSM_CACHE_DIR=$CSM_REPO_ROOT/build/local-csm-cache" \
  --env "CSM_LOG_DIR=$CSM_REPO_ROOT/build/local-csm-log" \
  --env "CSM_CODEX_BIN=$CSM_CODEX_BIN" \
  -- "$CSM_CLI" mcp stdio
~~~

完全退出并重新启动 Codex desktop，在 MCP 列表或 composer 的 /mcp 中确认工具快照
严格等于以下十个名称：

~~~text
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
~~~

在 Codex desktop 中先发送第一条请求，它是严格只读。只有需要验证 CSM 私有请求队列
和 GUI 唤起时，才继续发送后面三条；后面三条会写入 CSM 私有请求文件或启动 GUI，
但不会修改 Codex 对话、记忆文件或 `.codex`，也不得声称已经修改 Codex 数据。
如果第一步必须保持“任何 CSM 私有目录也不变”，只执行第一条和已有请求的 status 查询，
跳过 prepare/open。

~~~text
请只调用 inspect_conversation_inventory，参数为 {"older_than_days":1}。
只报告安全候选的数量、任务 ID、状态和项目 cwd；不要展示对话正文、记忆正文、
认证信息或 token。不要调用其它工具，不要打开 GUI，不要执行任何写操作。
~~~

~~~text
请对任务 <ARCHIVE_THREAD_ID> 只准备一条清理建议：
{"target_id":"<ARCHIVE_THREAD_ID>","reason":"该任务属于已确认的 CSM 项目范围，供人工审查","confidence":1.0}
调用 prepare_cleanup_suggestions 时 older_than_days 使用 1。
只返回 request_id 和候选摘要，不要声称已经归档或删除。
~~~

~~~text
请调用 get_pending_review_status，参数为 {"request_id":"<上一步返回的 request_id>"}。
只报告请求状态，不要执行归档、删除或其它写入。
~~~

如果准备了审查请求，再发送：

~~~text
请调用 open_cleanup_review，参数为 {"request_id":"<上一步返回的 request_id>"}。
这只允许打开本机 CSM 审查 GUI；不要声称已经归档，等待我在 GUI 中人工操作。
~~~

第一步通过标准：

- CSM 版本、候选 SHA、doctor 和 schema audit 已保存；
- project-threads.json 中的所有后续任务均人工确认属于本项目；
- MCP 工具恰好十个，没有 archive、delete、purge、apply 或 memory-write 工具；
- inspect/status 返回不含正文、token 或认证信息；
- 未发生 Codex 对话、记忆文件或 .codex 的改变。

## 第二步：非认证数据回滚快照后执行真实受控写入

第二步的“受控”不是把整个账号锁成项目沙箱；官方 App Server 仍连接当前账号，
因此安全边界由“停止其它客户端 + 精确项目 cwd + 精确任务 ID + 单根操作 + 计划复核”
共同构成。只要范围、能力画像、状态、内容指纹或后代闭包有任何漂移，就停止。

### 2.1 停止进程并创建本机 .codex 数据回滚快照

先从 Codex desktop 和 CSM GUI 正常退出，再确认没有 App Server writer。不要使用
kill -9，也不要在快照创建期间继续使用 Codex。

~~~bash
if pgrep -x codex >/dev/null 2>&1 || pgrep -x Codex >/dev/null 2>&1; then
  echo "仍有 Codex/codex 进程运行；先正常退出后再继续" >&2
  exit 1
fi

export CSM_LOCAL_BACKUP_ROOT="$HOME/csm-local-controlled-v1.1.0"
mkdir -m 700 -p "$CSM_LOCAL_BACKUP_ROOT"
ssh-keygen -q -t ed25519 -N '' \
  -f "$CSM_LOCAL_BACKUP_ROOT/age-test-identity"
sed -n '1p' "$CSM_LOCAL_BACKUP_ROOT/age-test-identity.pub" \
  > "$CSM_LOCAL_BACKUP_ROOT/recipients.txt"
chmod 600 "$CSM_LOCAL_BACKUP_ROOT/age-test-identity" \
  "$CSM_LOCAL_BACKUP_ROOT/age-test-identity.pub" \
  "$CSM_LOCAL_BACKUP_ROOT/recipients.txt"

export CSM_AGE_BIN="$CSM_REPO_ROOT/vendor/age/age"
export CSM_HOME_SNAPSHOT="$CSM_LOCAL_BACKUP_ROOT/codex-home-data-before-test.tar.age"
"$CSM_REPO_ROOT/scripts/backup_codex_home.sh" create \
  --source "$HOME/.codex" \
  --destination "$CSM_HOME_SNAPSHOT" \
  --recipients-file "$CSM_LOCAL_BACKUP_ROOT/recipients.txt"
"$CSM_REPO_ROOT/scripts/backup_codex_home.sh" verify \
  --backup "$CSM_HOME_SNAPSHOT" \
  --identity-file "$CSM_LOCAL_BACKUP_ROOT/age-test-identity"
~~~

这份快照是数据回滚边界，不是 CSM 的逻辑对话备份，也不替代 archive plan 的
backup.evidence。它不包含 `auth.json`、`credentials*.json`、`oauth` 或 `tokens`，
所以恢复后需要由维护者重新登录 Codex。快照命令不检查或限制 Codex CLI 版本；age
版本固定为仓库已校验的 1.3.1。不要把快照路径加入 Git 或测试 ZIP。

先做一次只写入新目录的恢复演练，确认快照真的可还原；target 必须不存在：

~~~bash
"$CSM_REPO_ROOT/scripts/backup_codex_home.sh" restore \
  --backup "$CSM_HOME_SNAPSHOT" \
  --identity-file "$CSM_LOCAL_BACKUP_ROOT/age-test-identity" \
  --target "$CSM_LOCAL_BACKUP_ROOT/restored-codex-home" \
  --confirm-restore "RESTORE CODEX HOME"
test -d "$CSM_LOCAL_BACKUP_ROOT/restored-codex-home"
~~~

脚本拒绝非空 target、符号链接、源目录内的 destination、归档路径穿越和已有输出；
它不会删除原 .codex，也不会把两个 Codex home 合并。

### 2.2 重新运行写入前门禁并固定单根范围

重新启动 Codex desktop/CSM 后，先再次运行 doctor；不能沿用第一步的旧能力结果。

~~~bash
"$CSM_CLI" doctor > "$CSM_EVIDENCE_DIR/doctor-before-write.json"
"$CSM_CLI" schema audit \
  --output "$CSM_EVIDENCE_DIR/schema-audit-before-write.json"
"$CSM_CLI" threads list \
  --project "$CSM_PROJECT_ROOT" \
  > "$CSM_EVIDENCE_DIR/project-threads-before-write.json"
"$CSM_CLI" threads show "$ARCHIVE_THREAD_ID" \
  > "$CSM_EVIDENCE_DIR/archive-thread-before-write.json"
~~~

只有当 doctor 报告中的 write_enabled 为 true、schema audit 为 trusted_write 且
exact_profile_match 为 true、differences 为空时，才可继续真实 Codex 写入。当前
版本未知或 schema 指纹变化时必须停止；不要修改 protocol_profiles.json 来临时放行。

再次人工确认 ARCHIVE_THREAD_ID 的 cwd 是 CSM_PROJECT_ROOT，且它的完整 descendants
闭包仍只属于该项目。一次只处理一个根；不使用没有项目过滤的全局批量清理。

### 2.3 真实归档：先逻辑备份，再 GUI 确认

运行：

~~~bash
"$CSM_CLI" cleanup review \
  --older-than-days 1 \
  --project "$CSM_PROJECT_ROOT"
~~~

在打开的原始 CSM GUI 中只做以下动作：

1. 初始列表不选中任何候选；手工选择且只选择 ARCHIVE_THREAD_ID；
2. 展开根和 descendants，核对 cwd、状态、标题和数量；
3. 不选择永久删除候选分组；
4. 点击“备份并归档”并选择 `.csmbackup` 输出路径；首次使用时确认创建本机托管的单一 age identity，不手工输入 recipient 或选择 identity 文件；
5. 展开完整 diff/范围，确认备份复验成功后再确认归档；
6. 保存最终 plan_id、backup manifest SHA-256 和完成结果，不保存正文。

随后验证：

~~~bash
"$CSM_CLI" threads show "$ARCHIVE_THREAD_ID" \
  > "$CSM_EVIDENCE_DIR/archive-thread-after.json"
"$CSM_CLI" audit verify > "$CSM_EVIDENCE_DIR/audit-after-archive.json"
~~~

预期只有该根及其完整安全 descendants 进入 archived 状态，CSM 审计链包含备份、
最终计划和归档结果。任何备份复验失败、状态/内容/能力/闭包漂移都必须拒绝归档。
本节的 GUI 托管密钥与 2.2 用于整体 `.codex` 回滚快照的 `age-test-identity` 相互独立；不删除、覆盖或迁移后者。

### 2.4 真实修改：对话标题、上下文审查与投影计划和本地记忆文件

对话本身不能通过编辑原始 JSONL/SQLite 直接修改。当前可验收的真实写入是标题修改和本地记忆文件修改；上下文只验收计划层。

#### 对话标题修改（可逆 App Server 写入）

~~~bash
"$CSM_CLI" gui open --thread "$EDIT_THREAD_ID"
~~~

在任务列表中只选 EDIT_THREAD_ID，右键选择“更名”，改成
CSM v1.1.0 controlled test title，确认精确 plan_id 后应用。用 threads show 核对
标题已改变；再用同一界面把标题改回原值，验证第二次计划和写入也通过。active、
pinned、ephemeral 或闭包不完整时不得更名。

#### 上下文审查与投影计划（不应用到 Codex）

~~~bash
"$CSM_CLI" trim review "$TRIM_THREAD_ID"
~~~

在 GUI 中执行：

1. 只选择一个可以丢弃的 turn/item；
2. 分别设置 Keep、Exclude、Summary、Protect 至少各一项；
3. 点击“保存方案”，记录 plan_id、plan SHA-256 和 projection SHA-256；
4. 对比计划保存前后的原任务摘要，确认原任务未变化；
5. 若通过 Hook 生成 PendingTrimPlan，验证 WAITING → READY → CANCELLED；
6. 改变源内容或能力画像后，确认旧计划变成 INVALIDATED，不能回退到 READY；
7. 将 `thread/inject_items` 派生投影的既有真实 round-trip 失败记录为 `blocked_upstream`，不运行 `trim apply`、不盲目重试、不把目标创建或 `{}` 响应标记为成功。

本步骤不创建派生任务。2.4 已按 [`2.4 收口记录`](v1.1.0-phase-2.4-context-projection-closure.md) 关闭：上下文审查与投影计划可用，原任务应用不可用，派生投影当前真实 round-trip 失败。

Codex desktop 中可使用以下请求准备审查，但 MCP 不执行应用：

~~~text
请只调用 prepare_context_suggestions，参数：
{"thread_id":"<TRIM_THREAD_ID>","suggestions":[
  {"target_id":"<TURN_OR_ITEM_ID>","suggested_action":"summary",
   "reason":"测试摘要投影","confidence":1.0,"suggested_text":"保留可复核的测试结论"}
]}
只返回 request_id 和建议摘要，不要声称已经裁剪或创建派生任务。
~~~

#### 记忆文件真实修改/删除（本地文件写入）

只新建本次验收专用文件，不使用维护者真实 MEMORY.md：

~~~bash
export CSM_MEMORY_ROOT="$CSM_LOCAL_BACKUP_ROOT/memory"
mkdir -m 700 -p "$CSM_MEMORY_ROOT"
printf '%s\n' '# Test profile' '' '- Likes tea' '- Uses macOS' \
  > "$CSM_MEMORY_ROOT/MEMORY.md"
"$CSM_CLI" memory register \
  "$CSM_MEMORY_ROOT/MEMORY.md" \
  --root "$CSM_MEMORY_ROOT"
"$CSM_CLI" memory sources
~~~

从 sources 或 memory show 得到 SOURCE_ID 和两个可操作 SEGMENT_ID 后，先只生成
unified diff 计划：

~~~bash
export SOURCE_ID="刚刚登记的 source ID"
export DELETE_SEGMENT_ID="待删除的 list segment ID"
export REPLACE_SEGMENT_ID="待替换的 list segment ID"
"$CSM_CLI" memory plan "$SOURCE_ID" \
  --delete "$DELETE_SEGMENT_ID" \
  --replace "$REPLACE_SEGMENT_ID=Uses macOS and CodexSessionManager"
~~~

展开 diff、确认标题和结构空白仍受保护后，再用返回的 PLAN_PATH 和 PLAN_ID 执行：

~~~bash
"$CSM_CLI" memory apply "<PLAN_PATH>" --confirm "<PLAN_ID>"
"$CSM_CLI" memory history "$SOURCE_ID"
"$CSM_CLI" audit verify
~~~

预期文件只发生计划中列出的 delete/replace 变化，并有私有版本、版本号、审计事件、
原子写入和重读验证。修改文件后再用旧计划 apply，必须因并发漂移被拒绝。
恢复测试必须先执行 memory restore plan，再用新的精确 plan_id 确认。

Codex desktop 只能准备建议：

~~~text
请对 source_id <SOURCE_ID> 调用 prepare_memory_suggestions，建议：
{"target_id":"<REPLACE_SEGMENT_ID>","suggested_action":"replace",
 "reason":"测试记忆替换","confidence":1.0,
 "suggested_text":"Uses macOS and CodexSessionManager"}
不要调用不存在的写入工具，也不要声称已经写入记忆文件。
~~~

### 2.5 永久删除：即时但独立的人工子步骤

固定 14 天等待期已取消；同一轮由 CSM 成功归档的任务可以立即进入人工永久删除验收。但完整备份本身不能解锁删除，CSM 的 purge 计划仍要求：

- 根和完整 descendants 已归档、inactive、非 pinned/ephemeral；
- 每个受影响任务都有 archive-bound 的已验证加密逻辑备份；
- 每个受影响任务都有 CSM 自有可信归档审计记录，且记录绑定的 manifest 与当前有效备份完全一致；
- 写入前重新通过 doctor、schema、状态、内容指纹、能力指纹和闭包复核；
- 没有其它 Codex 进程、loaded thread 或 background terminal；
- 只选择一个已经确认属于 CSM_PROJECT_ROOT 的根；
- 计划 ID 只读展示，人工只需单次精确输入“确认删除”。

完成 2.3 并确认归档与审计证据后，从同一个精确根 ID 打开：

~~~bash
"$CSM_CLI" gui open --thread "$ARCHIVE_THREAD_ID"
~~~

关闭其它 Codex Desktop/CLI 进程，确保该任务未在其它窗口加载。随后在 GUI 中单选该已归档根并点击“删除”，确认：

1. 计划只有这个根及其完整 descendants；
2. CSM 可信归档记录和 archive-bound 当前 backup evidence 均满足；
3. 对话 cwd 仍为 CSM_PROJECT_ROOT；
4. 计划 ID 与单根/完整 descendants 范围只读显示正确；
5. 唯一一处确认输入精确短语“确认删除”。

删除后重新运行 `threads show` 和 `audit verify`，保存“目标已不存在”的回读结果、purge plan SHA-256、审计事件和备份 manifest SHA-256；不保存正文。该证据层级必须标记为“真实本机 App Server 永久删除”，不能由 fixture、offscreen GUI 或只有计划的结果替代。

任何不满足项都应取消。不得用 App Server 原始方法、MCP 工具、脚本或直接文件删除
绕过 purge 计划。

#### 2026-09-01 本轮门禁记录

- 实现层证据：`scripts/check.sh`、`scripts/test_source_workflow.sh` 均通过；Ruff、严格 mypy、UI 生成一致性、Skill 校验和 `254 passed` 全部通过。大文本敏感筛查曾重复触发 Qt 心跳超时，定位为 macOS `sleep(0)` 不能保证主线程调度；改为每个 256 KiB 扫描块让出 1 ms 后，完整 GUI 套件和全套测试通过。
- bundle 层证据：从当前源码 fresh 构建 arm64 standalone；`accept_macos_bundle.sh`、ad-hoc `codesign --verify --deep --strict`、中文空格路径、内置 CPython/PySide6/Qt/age 和 bundled Skill 工作流通过。
- 真实 App Server 写入与回读证据：显式使用已批准的 Codex CLI `0.142.1`，精确 schema SHA-256 `3e07fdc39d62bb0afaa1509863bebee96178572372a8eeaa7e95bddb2b2f24ad`，`write_enabled=true`。用户指定根 ID 的 SHA-256 为 `e1c2bddbdd61d18259e51fc19192c3d118f8c5e13601e9812a718862eae501af`；托管 age 备份覆盖根与一个 descendant，manifest SHA-256 为 `96d26c9fb91ee7f6e18a1c9064a2ad5b3320b1f8ef052c1fa9a34454bad5584e`；归档计划 ID 仅记录 SHA-256 `ea3adc42650ff38a4819035efb4466851cfe3caefea1471e5b15b8451b24696c`。归档列表回读确认两者均为 `archived=true`、`notLoaded`、非 pinned。
- 当前阻塞：首次实体 GUI 永久删除尝试在任何 `thread/delete` 之前被 `thread/backgroundTerminals/list` 的 `-32600 thread not found` 停止；失败后官方 App Server 归档列表再次确认根与 descendant 仍完整归档，故不能记为真实永久删除通过。根因是该接口无法寻址 `archived + notLoaded` 任务；实现仅对同一任务的这一精确错误组合归一化为空终端结果，其它状态、错误码或 ID 继续失败关闭。
- 下一步：完成本次回归、fresh bundle 验收后，在实体 GUI 中再次单选该已归档根，确认只出现一次输入并精确填写“确认删除”；随后回读目标不存在状态、purge 审计事件和既有备份证据。

## 3. 回滚和收尾

验收结束后，先停止 Codex/CSM，再把当前测试中的 .codex 移到一个明确的旁路目录，
不要删除它；随后将快照恢复到新的、原本不存在的 HOME/.codex：

~~~bash
if pgrep -x codex >/dev/null 2>&1 || pgrep -x Codex >/dev/null 2>&1; then
  echo "仍有 Codex/codex 进程运行；不能回滚" >&2
  exit 1
fi
mv "$HOME/.codex" \
  "$HOME/.codex.after-csm-test-$(date +%Y%m%d-%H%M%S)"
"$CSM_REPO_ROOT/scripts/backup_codex_home.sh" restore \
  --backup "$CSM_HOME_SNAPSHOT" \
  --identity-file "$CSM_LOCAL_BACKUP_ROOT/age-test-identity" \
  --target "$HOME/.codex" \
  --confirm-restore "RESTORE CODEX HOME"
~~~

确认 Codex desktop 能正常读取恢复后的原始环境后，再由维护者人工决定如何处理
旁路目录和专用 identity；本计划不自动删除它们。

## 4. 证据和最终判定

可共享的证据只保留脱敏后的环境、计划、哈希、状态和审计结果。不要共享：

- .codex 非认证数据 age 快照、解密后的 restore 目录、identity/private key；
- 对话正文、记忆正文、认证文件、MCP 环境中的 token；
- 未脱敏的用户路径或完整任务标题。

最终报告必须明确：

- 这是本机真实账号的受控验收，不是生产验收；
- source/release evidence 是否为 delivery_ready；
- production_ready 必须为 false；
- 当前 Codex 版本是否命中已批准 schema；
- 哪些是真实 App Server/GUI 写入，哪些只是本地 fixture、offscreen 或 MCP 请求准备；
- 若写入门禁未通过，只完成了只读、备份和计划，不能描述为“归档/删除/修改已完成”。

相关背景和 MCP 配置依据：[OpenAI MCP 官方文档](https://learn.chatgpt.com/docs/extend/mcp)。
