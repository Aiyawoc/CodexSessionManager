# v1.1.0 正式发布前人工验收 Runbook

本文用于判断 CodexSessionManager `v1.1.0` 是否可以从“首批用户受控测试候选”推进为**正式公开发布版本**。

本文只列出正式发布前必须由维护者、平台测试人员或工作区管理员手动确认的项目。自动化门禁仍是前置条件，但不能替代真实账号、实体 GUI、签名公证、Windows 原生环境和真实 ChatGPT MCP app 验收。

## 1. 发布判定原则

### 1.1 状态定义

| 状态 | 含义 | 是否允许正式发布 |
| --- | --- | --- |
| `PASS` | 步骤、通过标准和证据均完整 | 是 |
| `PASS-WITH-LIMITATION` | 非安全关键限制已记录，且发布说明明确披露 | 需发布负责人批准 |
| `FAIL` | 功能、安全、签名、数据完整性或证据不满足要求 | 否 |
| `NOT-RUN` | 尚未在要求的平台或账号上执行 | 否 |

以下项目不得使用 `PASS-WITH-LIMITATION`：

- 对话、记忆文件或 CSM 审计数据发生不可解释的数据损坏；
- 写操作绕过不可变计划、最终确认或本地安全校验；
- macOS 签名、公证、staple 或 Gatekeeper 验证失败；
- Windows 签名无效、发布者身份错误或正式资产仍为 unsigned；
- MCP 缺少认证、暴露未批准执行器或可读取未授权数据；
- 真实 ChatGPT 无法稳定发现工具或无法唤起本地最终审查 GUI；
- ZIP、校验值、版本、标签或候选提交不一致。

### 1.2 验收数据边界

所有写入验收必须使用：

- 专门创建、无重要内容的 Codex 测试项目和测试对话；
- 专用测试 `MEMORY.md`，不得使用真实长期记忆文件；
- 独立的干净 CSM 数据目录，用于首次生成并复用本机托管 age identity；
- 独立的 CSM evidence 目录；
- 不包含生产凭据、真实客户数据或敏感对话内容的测试输入。

验收期间**不得执行永久删除**。任何写请求超时都按“可能已经完成”处理：停止后续写入，先按目标 ID 重新读取实际状态，禁止盲目重试。

## 2. 正式发布硬门禁总表

| 编号 | 验收域 | 必须环境 | 核心通过标准 |
| --- | --- | --- | --- |
| FR-01 | 候选冻结与自动证据 | fresh checkout | 工作区干净、版本一致、源码与 bundle 门禁通过 |
| FR-02 | macOS 签名、公证与 Gatekeeper | 干净 Apple Silicon macOS | Developer ID、Hardened Runtime、时间戳、公证、staple、Gatekeeper 全部通过 |
| FR-03 | macOS 真实账号与 Cocoa GUI | 真实 Codex 账号、实体窗口 | 清理、上下文审查/投影计划、PendingPlan、记忆、审计闭环通过且原数据符合预期；2.4 应用执行保持上游阻塞 |
| FR-04 | Windows x64 签名与原生运行 | 干净 Windows 11 x64 | Authenticode 有效、安装/升级/GUI/回退通过，无未知发布者或签名错误 |
| FR-05 | ChatGPT MCP app 与固定 Tunnel | 支持完整 MCP 的真实工作区 | 远程连接、认证、工具快照、GUI 唤起、断线恢复和权限隔离通过 |
| FR-06 | 安装、升级、回退与卸载说明 | macOS + Windows | 旧版本升级不丢数据，失败自动回退，手动回退和卸载路径可执行 |
| FR-07 | 安全与隐私负向测试 | 本机 + 公网入口 | 伪造、重放、越权、路径逃逸、错误认证和超限请求全部被拒绝 |
| FR-08 | 发布资产与来源证明 | 发布平台 | 标签、提交、版本、签名资产、校验值、许可证和文档一致，回下载复验通过 |
| FR-09 | 发布后冒烟与回滚准备 | 公开下载入口 | 首次下载可用、关键流程正常、旧资产和撤回方案可立即使用 |

任一硬门禁为 `FAIL` 或 `NOT-RUN` 时，最终结论必须为 **NO-GO**。

## 3. FR-01：候选冻结与自动证据

### 3.1 验收方法

从准备发布的精确提交创建 fresh checkout：

```bash
git status --short
git rev-parse HEAD
git describe --tags --always --dirty
uv sync --locked --all-groups
scripts/check.sh
```

生成源码级首次交付证据：

```bash
scripts/accept_first_delivery.sh \
  --evidence-dir build/formal-release-source-$(date +%Y%m%d-%H%M%S)
```

对 fresh macOS bundle 生成 release 级证据：

```bash
scripts/accept_first_delivery.sh \
  --evidence-dir build/formal-release-bundle-$(date +%Y%m%d-%H%M%S) \
  --app dist/CodexSessionManager.app
```

逐项核对下列位置中的版本均为 `1.1.0`：

```text
src/codex_session_manager/version.py
pyproject.toml
uv.lock
pysidedeploy.windows.spec
scripts/build_windows_app.ps1
应用 Info.plist 或 Windows 文件版本
发布资产文件名
发布说明和标签
```

### 3.2 通过标准

- `git status --short` 为空；
- `git describe` 不包含 `dirty`；
- `scripts/check.sh` 全部通过；
- source 和 release evidence 均满足：

```text
delivery_ready: true
production_ready: false
failed_required_checks: []
```

- evidence JSON/Markdown、候选提交 SHA 和报告 SHA-256 已登记；
- 没有通过修改生成物、关闭测试或放宽安全门禁来“修复”验收结果。

### 3.3 必留证据

- 候选 commit SHA、签名 tag、执行日期和执行人；
- `scripts/check.sh` 完整日志；
- source/release evidence JSON、Markdown 和 SHA-256；
- 版本一致性核对表。

## 4. FR-02：macOS Developer ID、正式公证与 Gatekeeper

### 4.1 前置条件

- 真实 Apple Silicon macOS；
- 有效的 `Developer ID Application` 证书；
- Xcode Command Line Tools 和可用的 `notarytool` keychain profile；
- 构建机时间正确，候选 checkout 干净；
- 正式构建不得使用 ad-hoc 签名或测试 build channel。

Apple 要求面向 Mac App Store 之外分发的软件使用适当的 Developer ID 签名、Hardened Runtime 和安全时间戳，并在分发前完成 notarization。正式验收还必须检查 notary log，而不能只看提交命令的退出码。

### 4.2 验收方法

确认签名身份：

```bash
security find-identity -v -p codesigning
```

使用 Developer ID fresh build：

```bash
CSM_DEVELOPER_ID='Developer ID Application: PUBLISHER (TEAMID)' \
CSM_SKIP_APP_SERVER_ACCEPTANCE=1 \
scripts/build_macos_app.sh
```

**构建后先检查 build channel：**

```bash
cat dist/CodexSessionManager.app/Contents/Resources/build-channel
```

正式发布资产必须标记为：

```text
release
```

如果仍为 `developer-id`、`local-adhoc` 或 `macos-test-adhoc`，必须停止发布并修正构建流程；禁止手工修改已签名 `.app` 内文件，因为这会破坏签名和来源一致性。

检查签名、Hardened Runtime 和安全时间戳：

```bash
codesign --verify --deep --strict --verbose=2 dist/CodexSessionManager.app
codesign -dv --verbose=4 dist/CodexSessionManager.app 2>&1
```

提交公证并 staple：

```bash
scripts/notarize_macos_app.sh \
  dist/CodexSessionManager.app \
  NOTARYTOOL_KEYCHAIN_PROFILE
```

记录 submission ID，并检查 notary log：

```bash
xcrun notarytool log SUBMISSION_ID \
  --keychain-profile NOTARYTOOL_KEYCHAIN_PROFILE
xcrun stapler validate dist/CodexSessionManager.app
spctl --assess --type execute --verbose=4 dist/CodexSessionManager.app
```

生成正式 ZIP 并对解压结果二次验收：

```bash
scripts/package_macos_release.sh \
  --app dist/CodexSessionManager.app
```

最后在一台未构建过 CSM 的干净 macOS 用户或机器上：

1. 通过浏览器下载正式 ZIP，让文件带有真实 quarantine 属性；
2. 校验 `.sha256`；
3. 解压并双击启动；
4. 不使用“仍要打开”、`xattr -d`、关闭 Gatekeeper 或其它绕过手段；
5. 执行 `csm doctor` 和 GUI 冒烟测试。

### 4.3 通过标准

- 签名 Authority 为预期 Developer ID，Team ID 正确；
- Hardened Runtime 已启用；
- 签名包含安全时间戳；
- `codesign --verify --deep --strict` 成功；
- notarization 状态为 `Accepted`；
- notary log 中没有未解释的签名、entitlement、恶意代码或 bundle 结构问题；
- `stapler validate` 成功；
- `spctl` 显示接受且来源为 notarized Developer ID；
- 浏览器下载后的 ZIP 在干净机器上可直接启动，不出现“已损坏”“无法验证开发者”或要求绕过安全策略；
- 解压后 bundle 的版本、签名、age、age-keygen、Skill、许可证和 checksum 与发布记录一致。

### 4.4 必留证据

- Developer ID 证书 Subject、Team ID 和有效期，不记录私钥；
- `codesign` 输出；
- notary submission ID、Accepted 结果和 notary log；
- `stapler validate`、`spctl` 输出；
- ZIP SHA-256、文件大小和干净机测试记录。

## 5. FR-03：macOS 真实账号、Cocoa GUI 与核心业务闭环

### 5.1 只读基线

在真实 Codex 账号、稳定安装路径和实体 Cocoa 窗口中执行：

```bash
csm doctor
csm schema audit --output csm-schema-formal-release.json
csm threads list
csm audit verify
```

只有 Codex App Server 版本、schema 哈希和能力画像精确命中已审核画像，且写能力明确开启时，才允许进入受支持的写入阶段。未知协议、能力缺失或账号根冲突均为 **NO-GO**。通用 `write_enabled` 不会开放上下文应用；2.4 的原任务应用不可用，派生投影须另有完整真实 round-trip 证据。

### 5.2 实体 GUI 与输入法

分别在 `1600×900` 和最小 `1280×720` 检查：

- 中文输入法、英文输入、粘贴、键盘导航和焦点顺序；
- Retina/100%、125% 或系统可用缩放；
- 左侧项目/任务与记忆按钮切换；
- 多选、按钮启用状态、风险提示、确认对话框；
- 上下文应用入口显示为禁用并说明上游阻塞，不把通用 App Server 写能力显示为投影执行能力；
- Splitter 拖动、任务面板收起/展开；
- 写入进行时关闭窗口不会遗留无归属 Worker 或产生重复写入。

**通过标准：**无文字截断导致的歧义，无按钮覆盖，无输入丢失；禁用和风险状态与实际安全条件一致。

### 5.3 对话清理

使用一个旧测试根对话和一个测试后代：

```bash
csm cleanup review \
  --older-than-days 1 \
  --project /absolute/test/project
```

依次验证：

1. LLM/Skill 候选、后代闭包、项目、大小、最后活动时间、风险和备份状态正确；
2. 用户取消的根不进入最终范围；
3. 本地安全补选默认不选中；
4. 永久删除资格只读且不能混入归档；
5. “备份并归档”首次只确认创建本机托管 age identity，后续不再输入 recipient 或选择 identity，并且始终先创建、完整复验备份；
6. 备份后重新读取状态、能力、建议指纹和后代闭包；
7. 人为制造状态或内容漂移时，归档必须停止；
8. 无漂移时只归档最终确认范围；
9. 审计链包含备份、最终计划和归档结果。

**通过标准：**备份失败或任何漂移均不会归档；成功路径中根与完整后代范围精确一致；永久删除没有被调用；审计链可验证。

### 5.4 上下文审查与投影计划及待处理计划

使用无重要内容的测试对话：

1. 在原 GUI 设置 `KEEP/EXCLUDE/SUMMARY/PROTECT`；
2. 验证工具调用/结果、文件变更/验证按组处理；
3. 保存 TrimPlan，重新读取并确认来源对话不变；
4. 用 Hook 生成 PendingTrimPlan；
5. 源任务 active 时检查结果保持 `WAITING`；
6. 源任务 idle/notLoaded 且指纹一致时进入 `READY`；
7. 打开复核后确认加载原密封计划，而不是重新生成的默认建议；
8. 修改源内容、能力画像或计划文件后，旧计划进入 `INVALIDATED`；
9. 过期计划进入 `EXPIRED`，取消计划进入 `CANCELLED`；
10. 将 `thread/inject_items` 的既有真实 round-trip 失败记录为 `blocked_upstream`，不运行 `trim apply`、不盲目重试，也不把目标创建或 `{}` 响应标记为成功。

**通过标准：**原对话保持不变；硬保护无法被 LLM 或用户误操作绕过；只有 `READY` 可继续；上下文应用不作为当前交付能力；2.4 的计划层通过、派生 round-trip 阻塞和 `production_ready: false` 均被准确记录；状态机无非法回退。

### 5.5 记忆管理

创建专用测试文件并登记：

```bash
mkdir -p ~/csm-formal-release-test
cat > ~/csm-formal-release-test/MEMORY.md <<'EOF'
# Test profile

- Likes tea
- Uses macOS
EOF

csm memory register \
  ~/csm-formal-release-test/MEMORY.md \
  --root ~/csm-formal-release-test
csm memory sources
csm memory review SOURCE_ID
```

依次验证：

- 左侧第二按钮加载已登记来源和稳定 segment ID；
- front matter、标题、代码块和结构空白的保护符合设计；
- 可编辑段支持 `KEEP/DELETE/REPLACE/PROTECT`；
- LLM 建议绑定当前 segment 指纹，不能覆盖本地硬保护；
- 保存方案展示完整 unified diff；
- 应用前再次确认；
- 写入前创建并复验私有版本；
- 写入使用同目录临时文件、flush/fsync、原子替换和写后重读验证；
- `memory history` 可见版本，恢复必须先生成不可变计划并精确确认；
- 修改源文件后旧计划因并发漂移被拒绝；
- 未登记路径、路径逃逸、符号链接和未单独授权的指令文件被拒绝。

**通过标准：**diff 与实际写入逐字一致；换行和未知 Markdown 保持；每次修改和恢复均有可验证版本与审计事件；失败不破坏原文件。

### 5.6 必留证据

- 脱敏后的测试对话 ID 哈希和测试记忆 source ID 哈希；
- schema report SHA-256；
- TrimPlan、MemoryPlan、备份 manifest 和 audit chain tail SHA-256；
- 来源不变、投影计划、派生 round-trip 的阻塞结论、归档状态和恢复结果的核对记录；
- GUI 尺寸、系统缩放、macOS 版本和测试日期。

不得在证据中记录对话正文、记忆正文、identity 内容、Bearer token 或用户私有绝对路径。

## 6. FR-04：Windows x64 签名、安装和实体 GUI

### 6.1 要求环境

- 真实或独立虚拟化的 Windows 11 x64；
- 一台没有安装过 CSM 的干净测试用户；
- 有效的 Authenticode code-signing certificate；
- Windows SDK `signtool.exe`；
- 真实 Codex App/CLI 测试账号；
- 100%、125% 和 150% 显示缩放至少覆盖两档。

### 6.2 构建与签名方法

```powershell
.\scripts\check_windows.ps1
.\scripts\build_windows_app.ps1 -Version 1.1.0
```

当前构建脚本产出测试通道 unsigned ZIP。正式资产必须在签名后重新运行 bundle、安装和压缩验收，不得把 `windows-test-unsigned` 资产改名后发布。

至少对下列第一方文件执行 SHA-256 Authenticode 签名和 RFC 3161 时间戳：

```text
CodexSessionManager.exe
Install-CodexSessionManager.ps1
未来新增的第一方辅助 EXE 或安装器
```

示例命令中的证书和时间戳地址由发布环境提供：

```powershell
signtool sign /fd SHA256 /tr RFC3161_TIMESTAMP_URL /td SHA256 `
  /sha1 CERTIFICATE_THUMBPRINT CodexSessionManager.exe

signtool verify /pa /all /v CodexSessionManager.exe
Get-AuthenticodeSignature .\CodexSessionManager.exe
Get-AuthenticodeSignature .\Install-CodexSessionManager.ps1
```

签名后重新运行：

```powershell
.\scripts\accept_windows_bundle.ps1 `
  -BundlePath .\dist\CodexSessionManager-Windows-x64 `
  -ExpectedVersion 1.1.0

.\scripts\test_windows_install_workflow.ps1 `
  -BundlePath .\dist\CodexSessionManager-Windows-x64 `
  -ExpectedVersion 1.1.0
```

最后重新创建正式 ZIP 和 SHA-256；禁止复用签名前生成的 ZIP。

### 6.3 原生人工测试

在干净 Windows 11 x64 用户中通过浏览器下载正式 ZIP：

1. 校验 SHA-256；
2. 解压到中文、空格和长路径目录；
3. 检查 Windows 属性中的签名和发布者；
4. 运行安装脚本；
5. 执行 `csm version`、`csm doctor`、GUI 和 Hook fail-open 冒烟；
6. 测试中文输入法、键盘导航、缩放、窗口关闭和多选状态；
7. 使用测试账号走一次上下文派生和只读清理审查；
8. 使用测试 `MEMORY.md` 走一次修改与恢复；
9. 从上一公开版本升级，再执行失败回退和手动回退；
10. 按发布文档执行卸载，确认用户数据默认保留。

### 6.4 通过标准

- `Get-AuthenticodeSignature` 对第一方可执行文件和安装脚本返回 `Valid`；
- 证书 Subject、发布者名称和时间戳正确；
- 不出现“未知发布者”或“签名无效”；
- SmartScreen 结果已在一台未运行过 CSM 的机器上记录；若仍出现仅由新证书 reputation 导致的警告，正式公开发布必须由负责人明确决定等待信誉建立或将本次发布降级为 prerelease，不能宣称“无 SmartScreen 警告”；
- bundle 和安装工作流全部通过；
- 无开发 Python、uv、源码目录或开发 PATH 仍可运行；
- 中文/空格路径和目标缩放下 GUI 正常；
- 升级、失败回退、手动回退不丢失 CSM 配置、计划、版本和审计数据；
- Windows 实测结果与 macOS 安全边界一致。

### 6.5 必留证据

- Windows 版本、架构、显示缩放和测试机是否干净；
- 签名证书 Subject、有效期和时间戳；
- `signtool verify`、`Get-AuthenticodeSignature` 输出；
- bundle、安装、升级、回退和 SmartScreen 截图/记录；
- 正式 ZIP SHA-256。

## 7. FR-05：真实 ChatGPT MCP app、固定 Tunnel 与权限

### 7.1 工作区和连接方式

截至 `2026-08-18`，OpenAI 官方说明中，完整 MCP（包括被标记为非只读的动作）面向 ChatGPT Business、Enterprise 和 Edu 的 Web 工作区；Pro 仅支持 read/fetch 权限。CSM 的 `prepare_*` 和 `open_*` 工具会创建本地不可变审查请求或唤起 GUI，因此正式端到端验收必须使用能够批准完整工具面的 Business 或 Enterprise/Edu 工作区。仅在 Pro 上通过只读工具发现，不能替代此门禁。

ChatGPT 不能直接连接只监听本机的 MCP server。应使用 OpenAI 支持的 Secure MCP Tunnel，或使用经过安全评审的固定远程 HTTPS 入口。当前项目可使用固定 Cloudflare Tunnel，但不得使用随机 `trycloudflare.com` Quick Tunnel 作为正式发布入口。

### 7.2 Tunnel 配置验收

CSM 仍只监听回环地址：

```bash
export CSM_MCP_BEARER_TOKEN='本地生成的长随机值'
csm mcp serve \
  --host 127.0.0.1 \
  --port 8765 \
  --path /mcp \
  --allowed-origin https://chatgpt.com
```

Cloudflare named tunnel 使用固定 hostname，并将其映射到：

```text
http://127.0.0.1:8765
```

本地管理的 ingress 配置必须包含最终 catch-all 规则：

```yaml
ingress:
  - hostname: openai-mcp.example.com
    service: http://127.0.0.1:8765
  - service: http_status:404
```

验证配置和路由：

```bash
cloudflared tunnel ingress validate
cloudflared tunnel ingress rule https://openai-mcp.example.com/mcp
curl --fail http://127.0.0.1:8765/healthz
curl --fail https://openai-mcp.example.com/healthz
```

不得把 token 写入仓库、命令历史、模型上下文、Issue 或验收报告。若使用 OAuth/OIDC，必须确认 refresh token 能持续刷新；OpenAI 官方说明要求检查 provider 是否支持相应 refresh/offline access。若使用 Cloudflare Access service token，只能在目标 ChatGPT app 确实支持相应认证头时使用，不能为了联通而关闭 CSM 认证。

### 7.3 ChatGPT 工具快照

在 ChatGPT Web 开发者模式中创建 draft app，提供远程 MCP endpoint 和目标认证方式，执行 **Scan Tools**。

工具快照必须精确包含：

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

不得出现：

```text
delete_*
purge_*
execute_archive
execute_trim
apply_trim
apply_memory_edit
restore_apply
```

OpenAI 当前会保存经管理员审核的工具快照。工具名称、参数、权限或元数据发生变化后，必须重新 Scan Tools、复核并发布更新；不能假定 ChatGPT 自动采用服务器端变化。

### 7.4 功能与负向测试

使用测试数据逐项执行：

1. 只读盘点；
2. 生成清理建议并唤起原 GUI；
3. 生成上下文建议并唤起原 GUI；
4. 读取已登记测试记忆来源、生成建议并唤起原 GUI；
5. 本地 App 未运行时正常启动；
6. 本地 App 已运行时窗口置前，不产生重复冲突实例；
7. ChatGPT 工具返回只能声称“建议/请求已创建或 GUI 已打开”，不能声称归档、裁剪或记忆写入已经执行；
8. 用户在 GUI 取消后，ChatGPT 侧不得把请求解释为已执行；
9. 暂停 MCP 服务和 `cloudflared` 后请求明确失败，恢复后私有队列可继续复核；
10. 错误或缺失 Bearer token 返回 `401`；
11. 错误 Origin 返回 `403`；
12. 超过请求大小限制返回 `413`；
13. 错误 Content-Type 返回 `415`；
14. 未知 endpoint 返回 `404`；
15. 未授权工作区用户无法使用 app，授权用户可以使用；
16. token 轮换后旧 token 立即失效，新 token 可用；
17. Tunnel 重启和机器重启后固定 hostname 不变化。

### 7.5 通过标准

- 使用符合要求的 ChatGPT 工作区和 Web 客户端；
- endpoint 为固定 HTTPS 地址，证书有效；
- CSM 只监听回环地址，Tunnel 使用出站连接；
- 工具快照与白名单完全一致；
- 所有建议都进入本地最终审查，MCP 不直接执行高风险写入；
- 认证、Origin、大小、Content-Type 和路由负向测试全部按预期拒绝；
- GUI 启动、置前、队列和恢复稳定；
- Cloudflare/CSM 日志中不含 token、对话正文或记忆正文；
- RBAC/工作区权限符合预期；
- 发布后的工具快照与候选提交保持一致。

### 7.6 必留证据

- ChatGPT 计划类型、工作区类型、管理员和测试用户角色；
- MCP hostname、工具清单和工具定义哈希；
- draft/published app 版本或快照时间；
- 测试 request ID、GUI 启动/置前结果、断线恢复结果；
- 认证负向测试状态码；
- Tunnel 配置哈希和 `cloudflared` 版本；
- token 轮换日期，但绝不记录 token 值。

## 8. FR-06：安装、升级、回退与卸载

### 8.1 macOS

至少覆盖：

1. 干净用户首次安装；
2. 从上一公开版本升级到 `1.1.0`；
3. 安装后 `~/Applications/CodexSessionManager.app`、`~/.local/bin/csm` 和 Skill symlink 正确；
4. 安装不会自动启用 Hook；
5. 人为让 post-install doctor 失败，确认安装器自动恢复上一版本；
6. 使用 `CodexSessionManager.previous.app` 执行手动回退；
7. 回退后重新安装 `1.1.0`；
8. 按文档卸载程序和 launcher，但默认保留用户数据、备份和审计；
9. 用户明确要求删除数据时，只删除文档列出的精确 CSM 目录，不触碰 Codex home。

### 8.2 Windows

至少覆盖：

- 干净安装；
- 同版本重复安装；
- 从上一公开版本升级；
- 中文/空格安装路径；
- 失败回退；
- 无开发 PATH 运行；
- Skill 和 launcher 路径；
- 卸载或便携删除说明；
- 用户数据默认保留。

### 8.3 通过标准

- 安装和升级前后 `csm doctor` 通过；
- CSM data/config/cache/log 的归属和权限正确；
- 计划、记忆版本、备份和审计没有丢失或静默迁移失败；
- 上一版本二进制回退不会因新数据结构直接崩溃；若存在不可逆数据格式，必须在升级前自动备份并在发布说明中明确，否则为 `FAIL`；
- Hook 保持显式 opt-in；
- 卸载说明不会删除 Codex 原始数据。

## 9. FR-07：安全与隐私负向验收

### 9.1 必测项目

| 场景 | 预期结果 |
| --- | --- |
| 篡改 ReviewRequest/SuggestionBundle/Plan | SHA 或身份校验失败，不执行 |
| 重放过期请求 | 拒绝并显示 expired/invalidated |
| 账号根变化 | 拒绝跨账号使用 |
| 对话内容或能力漂移 | 计划失效，不写入 |
| 记忆文件 mtime/inode/大小/指纹变化 | 旧计划失效，不覆盖 |
| 未登记路径、`..`、符号链接 | 拒绝 |
| 错误 Bearer、Origin、Content-Type、超限请求 | 返回预期错误码 |
| MCP 直接请求归档/裁剪/记忆写入工具 | 工具不存在 |
| Hook 超时、崩溃、GUI 取消 | fail-open，继续原生压缩 |
| 写请求超时 | 不自动重试，先复读实际状态 |
| 日志与报告扫描 | 不含 token、identity、正文或私有绝对路径 |
| 托管 identity 缺失/损坏/权限异常，或备份损坏 | 不静默替换已有密钥；完整复验失败，后续动作停止 |
| 永久删除入口误触 | 仍要求独立计划、等待期、备份和精确确认 |

### 9.2 通过标准

- 所有负向场景 fail closed；只有 Hook 的设计性故障路径 fail open；
- 不产生部分写入、重复派生、错误归档或损坏记忆文件；
- 审计链能够解释成功、拒绝和失败结果；
- 没有秘密或正文泄漏到日志、MCP 返回、验收报告、崩溃报告或发布资产。

## 10. FR-08：正式发布资产与来源证明

### 10.1 发布资产清单

正式 Release 至少应包含：

- macOS 对应架构的 Developer ID 签名、公证、stapled ZIP；
- Windows x64 Authenticode 签名 ZIP；
- 每个资产独立 `.sha256`；
- 对应 source archive 或 Git tag；
- 中英文 release notes；
- `THIRD_PARTY_NOTICES.md`；
- bundle 内 age license，以及同时绑定 age/age-keygen SHA-256 的 `age-verification.json`；
- 自动验收报告哈希和人工验收摘要；
- 已知限制、升级、回退和卸载说明。

### 10.2 验收方法

1. 创建指向冻结 commit 的 annotated/signed tag；
2. 在干净 checkout 从该 tag fresh build；
3. 生成最终资产后记录 SHA-256、大小、架构、版本和签名身份；
4. 上传到发布平台；
5. 从公开下载地址重新下载所有资产；
6. 重新校验 SHA-256、macOS 签名/公证和 Windows Authenticode；
7. 确认下载页、README、Skill、版本、文件名和 release notes 一致；
8. 确认没有上传测试数据、identity、token、evidence 私有路径或未清理的崩溃报告；
9. 保留上一稳定版本和撤回/回滚说明。

### 10.3 通过标准

- tag、commit、版本、资产名和应用内部版本完全一致；
- 正式 macOS build channel 为 `release`，Windows 不再标记 `test-unsigned`；
- 公开下载回读的 SHA-256 与发布记录一致；
- 签名和公证在回下载资产上仍有效；
- 发布说明准确区分已完成与未完成的能力；
- 所有第三方许可证和验证元数据存在；
- 发布资产不可被同名覆盖，任何替换都必须使用新版本号和新记录。

## 11. FR-09：发布后冒烟与撤回准备

发布后立即在 macOS 和 Windows 各执行一次：

1. 从公开地址下载；
2. 校验 checksum；
3. 安装或解压；
4. `csm version`、`csm doctor`；
5. 打开 GUI；
6. 运行只读盘点；
7. 使用测试数据打开一次上下文、清理和记忆审查；
8. 从 ChatGPT published app 调用只读盘点和打开演示；
9. 验证公开文档和下载链接；
10. 检查错误监控和支持渠道中是否出现签名、安装或工具快照问题。

发布负责人必须预先准备：

- 撤回 release 的权限和步骤；
- 关闭 ChatGPT app 或撤销工作区访问的步骤；
- 轮换 MCP/OAuth/Cloudflare 凭据的步骤；
- 恢复上一稳定下载资产的步骤；
- 用户公告模板和数据安全说明。

**通过标准：**公开下载链路和关键只读路径正常；出现 P0/P1 问题时可以立即停止新下载、禁用 app、轮换凭据并指引用户回退。

## 12. 最终 GO / NO-GO 标准

只有同时满足以下条件，才允许标记 **GO**：

- FR-01 至 FR-09 全部完成；
- 所有硬门禁为 `PASS`；
- 没有未关闭的 P0/P1 缺陷；
- 所有 `PASS-WITH-LIMITATION` 均为非安全关键问题，已进入 release notes，并由发布负责人签字；
- macOS 公证资产和 Windows 签名资产均从公开下载地址回读验证；
- 真实 Codex 测试账号、实体 GUI、记忆恢复、PendingPlan、备份归档和审计闭环通过；
- 真实 ChatGPT 工作区、固定 Tunnel、工具快照、认证和权限验收通过；
- 安装、升级、失败回退、手动回退和卸载说明通过；
- checksum、版本、tag、commit、许可证和文档一致；
- 发布后撤回和凭据轮换方案可执行。

以下任一情况必须 **NO-GO**：

- 任何硬门禁未运行或失败；
- 需要关闭认证、Gatekeeper、SmartScreen 或本地安全校验才能完成测试；
- 真实数据可能被错误归档、覆盖、泄漏或不可恢复；
- MCP 工具面、参数或管理员审核快照与候选提交不一致；
- 正式资产仍为 ad-hoc、unsigned、未公证或测试通道；
- 发布资产回下载后哈希或签名不一致；
- 无法在规定时间内撤回或轮换凭据。

## 13. 人工验收记录模板

### 13.1 候选信息

```text
版本：
Git commit：
Git tag：
候选冻结时间：
发布负责人：
安全复核人：
macOS 验收人：
Windows 验收人：
ChatGPT 工作区管理员：
```

### 13.2 平台和资产

```text
macOS 版本/架构：
macOS ZIP：
macOS SHA-256：
Developer ID Subject/Team ID：
Notary submission ID：

Windows 版本/架构：
Windows ZIP：
Windows SHA-256：
Authenticode Subject：
时间戳：

Source evidence SHA-256：
Release evidence SHA-256：
Audit chain tail SHA-256：
```

### 13.3 MCP 与 ChatGPT

```text
ChatGPT 计划/工作区类型：
测试客户端：ChatGPT Web
MCP hostname：
认证机制：
工具清单哈希：
published app 快照时间/版本：
cloudflared 版本：
Tunnel 配置哈希：
```

### 13.4 门禁结论

| 编号 | 状态 | 证据位置/哈希 | 缺陷或限制 | 验收人/日期 |
| --- | --- | --- | --- | --- |
| FR-01 |  |  |  |  |
| FR-02 |  |  |  |  |
| FR-03 |  |  |  |  |
| FR-04 |  |  |  |  |
| FR-05 |  |  |  |  |
| FR-06 |  |  |  |  |
| FR-07 |  |  |  |  |
| FR-08 |  |  |  |  |
| FR-09 |  |  |  |  |

### 13.5 最终签字

```text
最终结论：GO / NO-GO
发布负责人：
安全复核人：
日期：
批准的限制：
回滚版本：
撤回负责人和联系方式：
```

## 14. 官方参考

- [OpenAI：Developer mode and MCP apps in ChatGPT](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt-beta)
- [Apple：Notarizing macOS software before distribution](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution)
- [Apple：Signing Mac Software with Developer ID](https://developer.apple.com/developer-id/)
- [Cloudflare：Set up Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/setup/)
- [Cloudflare：Locally-managed tunnel configuration](https://developers.cloudflare.com/tunnel/advanced/local-management/configuration-file/)
- [Cloudflare：Service tokens](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/)
- [Microsoft：SignTool](https://learn.microsoft.com/windows-hardware/drivers/devtest/signtool)
