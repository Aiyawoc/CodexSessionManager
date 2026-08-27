# v1.1.0 首次交付验收 Runbook

本 Runbook 用于把源码候选推进到**可交给首批用户受控测试**的状态。它不会授权永久删除、真实生产数据批量操作、公开发布、签名或公证。

维护者在本机执行真实账号、真实归档或真实文件修改时，必须另外遵循
[v1.1.0 本机两步受控验收计划](local-controlled-v1.1.0.md)。该计划先做只读基线，
再创建本机排除认证文件的 .codex 数据加密回滚快照；该快照不等于按对话逻辑备份，也不进入
测试包或共享证据。

## 1. 准备独立验收环境

在真实 Apple Silicon macOS 上使用与候选提交一致的 fresh checkout：

```bash
uv sync --locked --all-groups
git status --short
```

要求工作区干净。所有测试使用：

- 一个无重要内容的 Codex 测试项目和测试对话；
- 一个专用测试目录中的 `MEMORY.md`；
- 独立的 CSM evidence 目录；
- 不包含生产凭据或真实敏感对话的测试数据。

## 2. 源码首次交付门禁

使用一个不存在或为空的 evidence 目录：

```bash
scripts/accept_first_delivery.sh \
  --evidence-dir build/first-delivery-source-$(date +%Y%m%d-%H%M%S)
```

脚本会执行：

1. `scripts/check.sh`；
2. Ruff、严格 mypy、全量 pytest、Qt 资源和 Skill 合约；
3. 隔离的 MCP 工具白名单检查；
4. 临时记忆文件的 plan → version → atomic apply → restore → audit 回环；
5. PendingTrimPlan 的 waiting → ready → cancelled 生命周期；
6. 原 GUI 左侧第二按钮的记忆分段加载；
7. 生成不可覆盖的 JSON 与 Markdown 报告。

报告必须满足：

```text
delivery_ready: true
production_ready: false
failed_required_checks: []
```

## 3. 构建 fresh macOS App

测试版构建使用 ad-hoc 签名，并跳过真实 App Server 写入验收：

```bash
CSM_TEST_RELEASE=1 \
CSM_SKIP_APP_SERVER_ACCEPTANCE=1 \
scripts/build_macos_app.sh
```

构建必须来自当前 checkout，并通过：

- Nuitka completion report；
- bundle 内主程序、age、Skill、许可证和 build channel 检查；
- `codesign --verify --deep --strict`；
- bundle 自带 CLI `doctor --skip-app-server`。

## 4. 安装包首次交付门禁

先在专用 macOS 测试用户或临时 `HOME` 中安装 fresh bundle，避免修改真实用户的稳定安装路径：

```bash
CSM_TEST_HOME=/private/tmp/csm-first-delivery-home
HOME="$CSM_TEST_HOME" \
CSM_INSTALL_SKIP_APP_SERVER=1 \
scripts/install_user.sh "$PWD/dist/CodexSessionManager.app"

HOME="$CSM_TEST_HOME" \
scripts/accept_first_delivery.sh \
  --evidence-dir build/first-delivery-bundle-$(date +%Y%m%d-%H%M%S) \
  --app dist/CodexSessionManager.app \
  --stable-app "$CSM_TEST_HOME/Applications/CodexSessionManager.app"
```

除源码门禁外，此步骤还要求：

- bundle 验收脚本通过；
- bundle 内 age 可执行；
- 独立稳定应用可执行路径可解析，且版本、channel 和 executable SHA-256 与候选 bundle 一致；
- `acceptance release` 的全部必需检查为 `passed`。

安装后验证版本、doctor 和回退副本：

```bash
scripts/install_user.sh "$PWD/dist/CodexSessionManager.app"
~/.local/bin/csm version
~/.local/bin/csm doctor
```

版本应为 `1.1.0`。

生成可交给首批用户的测试 ZIP，并对解压结果二次验收：

```bash
scripts/package_macos_release.sh --app dist/CodexSessionManager.app
```

脚本会输出 ZIP、SHA-256 和 checksum 文件路径。测试/adhoc 通道使用 `-test` 文件名；脚本拒绝覆盖既有资产。发布前把 ZIP、`.sha256`、候选提交和验收报告 SHA 一起登记。

## 5. 对话清理人工验收

只选择测试项目中的一个旧测试根对话：

```bash
csm cleanup review --older-than-days 1 --project /absolute/test/project
```

检查：

- 建议根和后代按项目显示；
- 用户取消的根不进入最终范围；
- 安全补选默认不选中；
- 永久删除资格只读且不可混入归档；
- “备份并归档”要求 age recipient 与 identity；
- 备份完整复验后才归档；
- 备份后人为制造状态或内容漂移时归档被拒绝；
- 审计链包含备份、最终计划和归档结果。

不得执行永久删除。

## 6. 上下文优化与待处理计划人工验收

在一个无重要内容的测试对话中：

1. 运行 `csm trim review THREAD_ID`；
2. 修改 Keep/Exclude/Summary/Protect；
3. 保存计划并确认原对话未变化；
4. 创建派生任务，确认新 ID 和投影内容；
5. 使用 Hook 测试生成 PendingTrimPlan；
6. 在“待处理计划”中点击“检查状态”；
7. active 时保持 WAITING，idle/notLoaded 且指纹一致时进入 READY；
8. 打开复核，确认加载的是原密封计划；
9. 创建派生任务后状态变为 APPLIED；
10. 修改源内容或能力画像后旧计划进入 INVALIDATED。

## 7. 记忆管理人工验收

创建专用测试文件：

```bash
mkdir -p ~/csm-first-delivery-test
cat > ~/csm-first-delivery-test/MEMORY.md <<'EOF'
# Test profile

- Likes tea
- Uses macOS
EOF

csm memory register \
  ~/csm-first-delivery-test/MEMORY.md \
  --root ~/csm-first-delivery-test
csm memory sources
csm memory review SOURCE_ID
```

检查：

- 左侧第二按钮加载已登记来源；
- 标题和结构空白受保护；
- 列表项可 Keep/Delete/Replace/Protect；
- 保存方案展示完整 unified diff；
- 应用前再次确认；
- 写入后存在可验证版本和审计事件；
- `csm memory history SOURCE_ID` 能看到版本；
- 恢复先 plan，再精确确认；
- 修改源文件后旧 plan 因并发漂移被拒绝；
- 未登记路径、路径逃逸和符号链接被拒绝。

## 8. Codex 桌面端本机 MCP 验收

本次真实测试使用 Codex desktop app，而不是 ChatGPT 网页端。Codex desktop 支持
本机 MCP，并可按 `~/.codex/config.toml` 启动 stdio 子进程，因此不需要 HTTPS、
固定 Tunnel、OpenAI Secure MCP Tunnel 或 Bearer token。

测试包的 `configure-codex-mcp.sh` 应配置：

```toml
[mcp_servers.codex_session_manager]
command = "/Users/测试用户/.local/bin/csm"
args = ["mcp", "stdio"]
```

配置中的 `CODEX_HOME`、`CSM_CODEX_HOME`、`CSM_DATA_DIR`、`CSM_CONFIG_DIR`、
`CSM_CACHE_DIR` 和 `CSM_LOG_DIR` 必须指向同一个测试机数据根。完全退出并重启
Codex desktop，在 Settings → MCP servers 或 composer 的 `/mcp` 中确认服务已发现。
官方配置和传输说明以 [Codex MCP 文档](https://learn.chatgpt.com/docs/extend/mcp)
为准。

核对工具快照只包含 CSM 的以下十个工具：

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

不得出现归档、永久删除、裁剪应用、恢复应用或记忆写入执行器。

依次用测试数据验证：

1. 只读盘点；
2. 清理建议准备并唤起原 GUI；
3. 上下文建议准备并唤起原 GUI；
4. 已登记测试记忆来源的分段读取、建议准备和 GUI 唤起；
5. 应用已运行时窗口置前；
6. 关闭/重启 Codex desktop 后 MCP 子进程可以重新启动，私有队列中的请求仍可复核；
7. 修改工具定义或配置后，Codex desktop 重新启动并重新发现服务；
8. MCP 子进程退出时只影响 MCP 请求，不绕过 CSM GUI 的计划和确认门禁。

记录：Codex desktop 版本、MCP 配置名称、工具清单哈希、测试 request ID、窗口行为、
重启恢复结果和日期。不要记录 token、认证信息、对话正文或记忆正文。

`csm mcp serve` 的 Bearer/Origin/请求大小检查仍可作为独立 HTTP 诊断，但不是本次
Codex desktop 本机 stdio 验收门禁；不得把 HTTP 诊断服务暴露到公网。

## 9. 发布判定

首次交付候选可以交给首批用户受控测试，需要同时满足：

- 源码和 bundle evidence 均为 `delivery_ready: true`；
- fresh bundle、稳定安装和回退路径通过；
- 一个真实测试对话和一个测试记忆文件闭环通过；
- Codex desktop 本机 MCP 工具发现、stdio 启动和 GUI 唤起通过；
- README、Skill、版本和 checksum 与候选提交一致；
- 已明确标注未签名/未公证/未生产验收的限制。

正式公开发布还需要单独完成 Developer ID、公证、Windows 原生验收和发布资产检查。

正式公开发布使用更严格的人工门禁，见 [`v1.1.0 正式发布前人工验收 Runbook`](formal-release-manual-v1.1.0.md)。
