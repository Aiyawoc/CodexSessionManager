# 测试版证据不等于生产发布

源码测试、假 App Server、offscreen Qt、CI runner、本机构建和 bundle 验收分别只证明其对应层级。未完成 Developer ID 签名、公证与 staple 的 macOS 包，以及未完成 Authenticode 和干净机信誉验证的 Windows 包，只能作为明确标记的 prerelease 测试产物，任何验收报告都固定为 `production_ready: false`。
