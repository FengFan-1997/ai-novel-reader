# 声阅本机搜索底座

本目录运行一个仅监听 `127.0.0.1:8888` 的 SearXNG。它向“找书”页提供 JSON 搜索结果，不会暴露到局域网或公网。

```bash
cd search-stack
cp .env.example .env
sed -i '' "s/replace-with-a-random-local-secret/$(openssl rand -hex 32)/" .env
docker compose up -d
```

健康检查：

```bash
curl --get --data-urlencode 'q=声阅' --data 'format=json' http://127.0.0.1:8888/search
```

停止服务使用 `docker compose down`。声阅的启动脚本只检测该地址，不会启动 Docker Desktop；SearXNG 停机时，Google Books 和 Open Library 等直连来源仍然可用。

配置关闭 Safe Search，以便默认搜索所有已启用来源，但专门用于未授权下载索引的引擎已从配置中排除。搜索结果只提供来源入口，声阅不会代理下载或缓存站点正文。
