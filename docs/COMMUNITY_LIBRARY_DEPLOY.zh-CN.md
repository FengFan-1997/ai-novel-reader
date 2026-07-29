# 声阅公共书库上线手册

这套改造不再让 Render 代理音频，也不需要维护者的 Mac 在线。Render 只保存控制 API 和节点目录；模型仍运行在每位贡献者自己的电脑上。

## 一次性配置

1. 新建一个独立的 Neon PostgreSQL 项目，复制连接串到 Render 的 `DATABASE_URL`。
2. 新建 Cloudflare R2 Standard bucket：`shengyue-hot-cache`。配置 CORS，允许 `https://shengyue-fengfan.vercel.app` 执行 `GET, PUT, HEAD`，并填入 Render 的四个 `R2_*` 环境变量。
3. 保持 `R2_HOT_MAX_BYTES=8589934592`，即 8GB 音频热缓存；剩余免费空间用于上传临时余量。
4. 在 Render 部署 `render.yaml`。服务启动时会自动执行 `cloud/relay/migrations/001_community_library.sql`。
5. 在 Vercel 重新构建 `cloud/web`：`npm run build`。公开书库入口是 `/library`，控制 API 经 `/v1/*` 自动重写到 Render。
6. 在本地声阅的“设置 → 共享书库”填写 Render URL，确认一次告知。之后每个完成章节会在后台自动转为 Opus、登记、上传或做种。

## 真实可用性

- R2 命中：网页立即播放。
- R2 未命中但贡献者在线：控制 API 返回在线节点，并提供短时 WebRTC 信令票据；Render 只转发 SDP/ICE，不接收音频字节。首发客户端仍需启用对应的 WebRTC/WebTorrent 做种适配器后才能把本地 Opus 作为数据通道发送。
- 两者都没有：页面显示“等待节点”，不会假装可播放。

## 当前迁移

现有本地生成任务不会中断。只要在完成下一章前启用共享书库，它会自动成为第一批公共章节。已完成的旧章节可在“我的有声书 → 更多 → 贡献已完成章节”触发后台回填；不会重新调用 TTS，也不会占用模型推理队列。

## 运行前检查

- Render `/v1/health` 显示 `configured: true`。
- 本地 `/api/community/status` 显示已连接设备。
- 完成一章后，`data/community_library.db` 中出现 `complete` 或 `seeded` 状态。
- R2 音频应是 24kHz、单声道、48kbps Opus；不上传中间 WAV 与小说原文。
- R2 达到 8GB 热缓存配额时，服务会淘汰低热度、非近期播放且没有在线节点保护的章节；无法安全腾出空间时，新贡献只登记为 P2P 种子，不会突破配额。
