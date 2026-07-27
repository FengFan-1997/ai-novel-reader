# AI Novel Reader 部署说明

最后核验：2026-07-27

## 仓库分支

- `main`：上游 TTS-Story 基线，不是当前云端体验的部署来源。
- `codex/cloud-bridge-launch`：当前声阅云端桥接来源。

## 当前体验

| 层 | 地址 |
|---|---|
| Vercel 前端 | <https://shengyue-fengfan.vercel.app> |
| Render 中继 | <https://shengyue-relay.onrender.com> |
| 中继健康检查 | <https://shengyue-relay.onrender.com/healthz> |
| 本地应用 | <http://127.0.0.1:7860> |

云端页面不保存模型和小说正文。生成能力依赖用户自己的 Mac、本地模型服务和出站桥接；电脑离线时，公网只显示静态界面和离线状态。

完整架构、环境变量和离线边界见云端分支的 [`DEPLOYMENT.zh-CN.md`](https://github.com/FengFan-1997/ai-novel-reader/blob/codex/cloud-bridge-launch/DEPLOYMENT.zh-CN.md)。
