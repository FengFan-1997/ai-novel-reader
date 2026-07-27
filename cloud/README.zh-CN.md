# 声阅云端桥接

生产拓扑：

```text
用户浏览器 → Vercel 静态前端 → Render 安全中继 ⇄ 本地 Mac → Flask / 本地模型
```

- Render 不保存模型、小说或 API Key。
- 本地 Mac 只建立出站 WebSocket，不开放公网端口。
- 所有代理 API 需要云端访问密码签发的 HttpOnly Cookie。
- Render 与本地桥接使用独立随机密钥认证。
- 本地离线时 `/bridge/status` 返回维护状态，前端只提供静态界面和使用帮助。

必需的 Render 环境变量：

- `CLOUD_ACCESS_PASSWORD`
- `BRIDGE_SHARED_SECRET`
- `SESSION_SECRET`
- `PUBLIC_ORIGIN`

本地桥接默认从 macOS Keychain 读取：

- `ShengYue Cloud Bridge URL`
- `ShengYue Cloud Bridge Secret`
