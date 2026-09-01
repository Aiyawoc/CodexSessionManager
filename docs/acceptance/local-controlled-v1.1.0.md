# v1.1.0 本机两步受控验收计划

本计划用于在维护者自己的 macOS Apple Silicon 机器上，对当前 CodexSessionManager
候选执行一次可回滚的真实账号验收。它把验收严格分成两步：

1. 只读盘点、协议审计和 MCP/GUI 请求链检查；
2. 在停止 Codex、完成并复验排除认证文件的 .codex 数据加密回滚快照后，只对已经确认属于本项目的
   少量任务执行真实归档/反归档；上下文只验收审查、投影计划和源任务保护。永久删除、重命名、restore/import 写入、上下文应用和 MCP 写入均跳过执行。

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

Codex CLI 的版本、二进制和全量 schema 散列可随运行时变化；它们是诊断与计划失效证据，
不是归档授权条件。真实归档/反归档写入仍必须分别通过 CSM 静态、人工复核的最小操作契约，
不能用跳过检查或环境变量绕过计划、备份、状态、内容指纹和后代闭包门禁。

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
- 五项 `operation_capabilities` 与实际契约评估一致，并记录具体阻塞原因；
- 相关契约未知或 incomplete 时，只关闭受影响操作；其它读取、备份、验证和计划继续可用；
- 当前候选的 production_ready 永远为 false。

如果某项归档/反归档契约不兼容，第一步仍可继续读取、备份和生成计划，但第二步
只能执行仍通过契约和其它安全门禁的操作；不得执行永久删除、重命名或其它当前不可用写入。

### 1.2 只读盘点并锁定项目范围

~~~bash
"$CSM_CLI" threads list \
  --project "$CSM_PROJECT_ROOT" \
  > "$CSM_EVIDENCE_DIR/project-threads.json"
"$CSM_CLI" memory sources \
  > "$CSM_EVIDENCE_DIR/memory-sources.json"
~~~

从 project-threads.json 中人工选择一个任务 ID 作为后续的
ARCHIVE_THREAD_ID。该 ID 必须满足：

- cwd 与 CSM_PROJECT_ROOT 完全一致；
- 不是 pinned、ephemeral 或 active；
- 父任务和 spawned descendants 能在同一份盘点中完整展开；
- 只记录 ID、状态、标题摘要、cwd、更新时间和 descendants，不复制正文。

每个候选都必须再次执行：

~~~bash
export ARCHIVE_THREAD_ID="从 project-threads.json 手工复制的精确 ID"
export TRIM_THREAD_ID="从 project-threads.json 手工复制的精确 ID"

"$CSM_CLI" threads show "$ARCHIVE_THREAD_ID" \
  > "$CSM_EVIDENCE_DIR/archive-thread-before.json"
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
- MCP 工具恰好十个，没有 archive/unarchive executor、永久删除、上下文应用或 memory-write 工具；
- inspect/status 返回不含正文、token 或认证信息；
- 未发生 Codex 对话、记忆文件或 .codex 的改变。

## 第二步：非认证数据回滚快照后执行真实受控写入

第二步的“受控”不是把整个账号锁成项目沙箱；官方 App Server 仍连接当前账号，
因此安全边界由“停止其它客户端 + 精确项目 cwd + 精确任务 ID + 单根操作 + 计划复核”
共同构成。只要范围、相关操作契约、状态、内容指纹或后代闭包有任何漂移，就停止受影响操作。

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

只有当 `archive` 或 `unarchive` 对应契约可用，且计划、备份、状态、内容指纹和完整闭包
均通过复核时，才可继续真实 Codex 写入。版本、二进制或全量 schema 指纹变化本身不阻塞；
相关契约变化必须报告具体原因，不得修改规则或报告来临时放行。

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
3. 点击“备份”并选择 `.csmbackup` 输出路径；首次使用时确认创建本机托管的单一 age identity，不手工输入 recipient 或选择 identity 文件；
4. 复验备份后点击“归档”，展开完整范围并确认；
5. 切换到“已归档”筛选，确认同一选择的按钮显示“反归档”；完成反归档后再次归档，以保留预期最终状态；
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

### 2.4 上下文审查与投影计划和本地记忆文件

对话本身不能通过编辑原始 JSONL/SQLite 直接修改。第一版不提供任务重命名、restore/import
写入或上下文应用；本节只验收上下文计划层和本地记忆文件的独立安全流程。

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
6. 改变源内容或相关操作契约后，确认旧计划变成 INVALIDATED，不能回退到 READY；
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

### 已退役流程的历史证据

永久删除不属于第一版能力或本 Runbook。曾经的设计与真实部分提交证据已移至 [`docs/archive/2026-09-01-purge-retirement/`](../archive/2026-09-01-purge-retirement/)，并标记为 `SUPERSEDED`；不得把归档记录当作当前操作步骤。

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
