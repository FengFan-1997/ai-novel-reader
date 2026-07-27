# 声阅部署说明

最后核验：2026-07-27

## 当前部署

| 层 | 位置 | 状态 |
|---|---|---|
| GitHub | [FengFan-1997/ai-novel-reader](https://github.com/FengFan-1997/ai-novel-reader) | 公开仓库 |
| 云端功能分支 | `codex/cloud-bridge-launch` | 当前云端来源 |
| 公网前端 | <https://shengyue-fengfan.vercel.app> | Vercel，HTTP 200 |
| 安全中继 | <https://shengyue-relay.onrender.com> | Render / Virginia |
| 中继健康检查 | <https://shengyue-relay.onrender.com/healthz> | HTTP 200 |
| 本地应用 | <http://127.0.0.1:7860> | 仅本机 |
| 本地推理 | Apple Silicon Mac、Ollama、MLX / IndexTTS | 不上传云端 |

生产拓扑：

```text
用户浏览器
  → Vercel 静态前端
  → Render 安全中继
  ⇄ 本地 Mac 出站 WebSocket
  → Flask 与本地模型
```

## 安全与离线边界

- Render 不保存模型、小说正文或模型 API Key。
- 本地 Mac 不开放公网端口，只主动建立出站桥接。
- 云端访问使用密码签发的 HttpOnly Cookie。
- Render 与本地桥接使用独立共享密钥。
- 本地电脑关机、休眠或桥接停止时，公网只能显示静态界面和离线状态，不能执行朗读任务。

## Render 配置

- Workspace：`artigen`
- Service：`shengyue-relay`
- Region：`Virginia`
- Root directory：`cloud/relay`
- Build：`npm ci --omit=dev`
- Start：`npm start`
- Health：`/healthz`
- Auto deploy：关闭；发布需要人工确认

敏感变量只放在 Render 环境变量或 macOS Keychain：

- `CLOUD_ACCESS_PASSWORD`
- `BRIDGE_SHARED_SECRET`
- `SESSION_SECRET`
- `ShengYue Cloud Bridge URL`
- `ShengYue Cloud Bridge Secret`

## Vercel 配置

Vercel 托管 `cloud/web` 静态前端，并把 `/bridge`、`/api`、`/files`、`/healthz` 和 `/readyz` 转发到 Render 中继。前端不包含桥接密钥。

## 本地启动

纯本地版本：

```bash
./run-macos-zero-cost.sh
```

云端桥接需要本地服务和桥接客户端同时运行。具体密钥不写入仓库；以 macOS Keychain 与部署平台实际配置为准。
