# PreCompact Hook 对原生压缩 fail-open

Hook 只在 TrimPlan 已成功持久化时阻止本次原生压缩；关闭、崩溃、启动失败、用户取消或超时均返回继续。Hook 模式不在进行中的 turn 内创建派生任务，因为避免压缩失败或重复触发比自动裁剪覆盖率更重要。
