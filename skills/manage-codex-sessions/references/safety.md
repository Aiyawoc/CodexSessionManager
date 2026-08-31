# 安全不变量

## 所有 Codex 写入

- 只使用官方 App Server 或 Codex App 原生任务工具。
- 禁止直接写 JSONL、SQLite、rollout 路径、认证或 Codex 配置。
- 消费已持久化、带 SHA-256 的不可变计划。
- 应用前重读 capability fingerprint、状态、内容/管理 fingerprint 和 spawned descendant closure。
- 任何漂移使计划失效；重新生成，不修补旧计划。
- 写入超时先查询真实后置状态，禁止直接重试。
- 父任务操作必须包含并展示全部 descendants。
- `parent_id` 和 `forked_from_id` 必须同时作为图边；缺父节点、环或根闭包重叠均停止写入。
- `CODEX_HOME` 与 `CSM_CODEX_HOME` 必须指向同一数据根。

## 清理与永久删除

- 自动操作最多归档。
- 归档前要求覆盖受影响快照的已验证加密备份。
- 固定、活动、加载中、映射不完整或状态不明的任务停止写入。
- 永久删除只接受人工计划，要求 CSM 自有审计记录的归档时间至少 14 天。
- 永久删除前拒绝其他 Codex 进程；测试只能使用临时隔离 Codex 数据根。
- 每个 purge 计划只允许一个根闭包，避免多根执行中断产生无法安全恢复的部分删除。
- 每个根删除前重读并重新校验 archived、14 天门、backup、loaded、后台终端和进程证据。
- 不把文件 mtime、Codex archived 标志或外部记录冒充 CSM 可信归档时间。

## 备份与密钥

- tar 直接流入 age，只产生加密临时目标；完整复验并锁定密文哈希/大小后，才以不覆盖的原子方式发布。
- manifest 位于流尾；校验时完整解密并计算每个成员 checksum，不落地明文容器。
- manifest 的 source fingerprints 必须与逻辑任务条目一一对应；从条目内嵌 `ThreadSnapshot` 重新计算 `backup_fingerprint`，禁止信任包内自报值。
- 备份覆盖与可信归档证据必须绑定到审计哈希链事件；永久删除使用的备份 manifest 必须与归档时记录的 manifest 完全相同。
- 恢复先完整校验，再第二遍解密导入；第二遍缺少任一已验证成员即失败。
- 口令只由 age 从控制终端读取；不进入模型、CLI 参数、环境、剪贴板建议或日志。
- GUI 只用 CSM 私有数据目录中的一个本机托管 recipient-key：首次用官方 `age-keygen` 生成，以后校验并复用；不写入备份或日志，不在缺失、损坏或权限异常时静默替换。
- 只收集已知 App 管理附件目录；拒绝符号链接和路径逃逸。
- 排除项目源码、Codex 认证和配置。

## 裁剪与导入

- 原任务始终保留。
- 任务内容、lineage mapping 或顶层协议字段不完整时拒绝裁剪写入。
- 当前请求、进行中 turn、目标、审批、未解决错误和未知 item 为硬保护。
- 系统/开发者指令不作为普通历史注入；派生任务重新加载当前项目指令。
- 工具 sidecar 只读、惰性、不可执行。
- 注入后重读派生任务并核验来源 manifest；不自动发起 turn。
