# 找书服务上游调研与采用记录

更新日期：2026-08-04

本记录用于说明找书功能采用了哪些公开项目，以及哪些代码因许可或产品边界被排除。Gutendex 的完整 MIT 源码已固定到 `vendor/gutendex`；其他候选仅在系统临时目录审阅。

## 已采用

### Gutendex / Project Gutenberg

- 仓库：https://github.com/garethbjohnson/gutendex
- 许可：MIT
- 接口：`GET https://gutendex.com/books/?search={query}&page={page}&copyright=false`
- 用途：搜索 Project Gutenberg 目录中的公版电子书元数据，读取作者、摘要、主题、封面和可用格式。
- 源码入库：提交 `c3f75a8bd783ca91d9cd37d133028ff994e7ba4b` 的完整上游树原样保存在 `vendor/gutendex`，并保留 MIT `license`。其中的标题整理实现已复制进 `src/upstream_book_algorithms.py`，不是把 Gutendex 应用作为本地或远程服务连接进来。
- 声阅适配：`GutendexAdapter` 只接收 `copyright: false` 的记录；原站入口固定为 `https://www.gutenberg.org/ebooks/{id}`。当返回值含 `text/plain` 格式时，标记为“提供公版文本”，但仍需用户核对所在地版权规则。
- 可用性补强：Gutendex 公共实例超时时，降级到 Project Gutenberg 官方 OPDS 搜索接口。OPDS 只提供基础条目时不宣称可直接导入，避免把不完整的授权判断扩张为下载许可。

### SearXNG

- 仓库：https://github.com/searxng/searxng
- 许可：AGPL-3.0-or-later
- 用途：理解成熟元搜索引擎的 `request` / `response` 适配器边界、单引擎超时、失败暂停和部分结果模型。
- 声阅实现：沿用自身独立实现的 Python 适配器接口，并增加进程内来源熔断；没有复制或改写 SearXNG 的 AGPL 源码。SearXNG 仍以独立 Docker 服务运行。
- 安全选择：不启用 torrent、Usenet、IRC 或专门面向盗版下载的搜索引擎。

### AgentSearch

- 仓库：https://github.com/brcrusoe72/agent-search
- 许可：MIT
- 用途：核对多来源诊断、失败隔离、缓存和 URL 清洗的工程模式。
- 声阅实现：独立增加 `SourceCircuitBreaker`。来源连续失败两次后从 30 秒开始指数退避，最长 10 分钟；HTTP 429 优先服从有上限的 `Retry-After`，成功调用会立即恢复来源。
- 排除项：没有采用仓库中的 Cloudflare 绕过、Google Cache/Wayback 回退或挑战页处理代码。

## 审阅后未采用

### DDGS

- 仓库：https://github.com/deedy5/ddgs
- 许可：MIT，约 2865 stars（调研时）。
- 排除原因：其通用结果聚合代码可用，但当前 `books` 后端指向 Anna's Archive。为避免把盗版目录引入找书功能，本轮不复制该图书引擎。

### Book Searcher

- 仓库：https://github.com/zu1k/book-searcher
- 许可：BSD-3-Clause，约 6306 stars（调研时）。
- 排除原因：本地索引性能设计优秀，但数据结构包含 `ipfs_cid`，更适合用户自有书库索引，不适合声阅当前的公开网页发现边界。

### xynehq/websearch

- 仓库：https://github.com/xynehq/websearch
- 原因：GitHub 未声明许可证。可理解其公开接口描述，但不能复制、修改或分发代码。

### Shelfmark、Readarr 类下载聚合器

- 原因：功能包含 torrent、Usenet、IRC 或非授权电子书下载发现，不符合声阅只做公开书目发现和原站跳转的边界，因此不克隆、不集成。

### 登录与访问控制绕过

- 不采用伪造登录、验证码破解、Cloudflare 挑战绕过、共享 Cookie、付费墙规避、TLS 校验关闭或跨域凭据复用。
- 合法账号只能通过原站正常登录流程使用。遇到验证码、二次验证或策略变化时，来源状态显示“需要手动登录”，由用户打开原站处理。
- 来源域名变更时，旧凭据不会自动发送到候选域名。

## 后续可评估

- OpenAlex：适合补充学术书籍与作者信息，公开 API 但需要按其礼貌池规范配置联系邮箱。
- Hardcover：元数据质量较高，但需要用户自备 API 凭据，不适合作为默认零配置来源。
- 本地自托管 Gutendex：当公共实例限流或隐私要求更高时，可作为可选 Docker profile，而不是默认增加数 GB 目录数据。
