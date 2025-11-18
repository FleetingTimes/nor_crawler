# 爬虫指南（基于 nor_crawler 通用爬虫框架）

本指南系统性介绍如何使用 nor_crawler 构建稳定、可维护、可扩展的网页爬虫，包括法律与合规、架构与配置、插件开发、反爬与稳定性、增量抓取、持久化与目录规范、调试与排错、性能优化、生产化部署等。你可以把本指南作为“站点适配”的参考手册，将不同网站的解析逻辑封装为插件与配置文件即可完成抓取任务。

—

## 一、合规与伦理
- 合法性与授权：在抓取前确认目标站点的使用条款与 robots.txt；若有授权或开放接口优先采用官方渠道。
- 风险与限制：遵守站点限速与访问规则，避免高并发刷流量；遵循数据使用边界，不采集个人敏感信息。
- 透明与尊重：标识合理的 User-Agent；如站点明确禁止抓取，应停止并寻求替代方案。
- 安全与隐私：对登录态、Cookie、Token 等敏感信息进行妥善保管，不外泄。

—

## 二、框架总览（nor_crawler 架构）
- 抓取层（`crawler/fetcher.py`）
  - 基于 `httpx.AsyncClient` 的异步 HTTP 抓取。
  - 内置速率限制（域级）、退避重试（指数退避）、UA/代理轮换、robots.txt 尊重（可选）。
  - 可选集成 Playwright（如已安装），支持对强依赖 JS 的页面进行渲染。
- 调度层（`crawler/scheduler.py`）
  - 管理抓取队列与并发度；支持简单的去重与状态管理（具体实现可根据项目演进调整）。
- 解析层（`crawler/parser.py`）
  - 提供基础 HTML 链接提取（`extract_links`）；站点特定的结构解析应在插件中实现，避免耦合。
- 存储层（`crawler/storage.py`）
  - SQLite 记录抓取页 URL/状态码/时间戳（断点统计与审计）。
  - 本地文件保存 HTML 快照（支持 `html_subdir` 将页面快照归档到子目录，如 `pages/`）与 JSON 数据。
- 登录模块（`crawler/login.py`）
  - 支持表单登录与 API 登录；维护会话 Cookie/Token；保留验证码处理 Hook（需集成外部服务）。
- CLI 入口（`crawler/cli.py`）
  - 从 JSON 配置加载各模块，启动抓取；把插件、抓取器、存储、配置注入到 `handle` 的上下文中。

—

## 三、快速上手
- 第一步：编写配置文件（如 `config/my_site.json`）。
- 第二步：编写插件（如 `plugins/my_site_plugin.py`），在其中解析列表页与详情页结构，返回下一步链接。
- 第三步：运行命令：`python -m crawler.cli --config config/my_site.json`。
- 第四步：查看输出目录（`output_dir`）、页面快照（`html_subdir`）与业务输出（由插件决定的文件路径）。

—

## 四、配置详解（config.json）
- 基本字段：
  - `seeds`：入口 URL 列表。
  - `allowed_domains`：允许抓取的域名白名单，避免越界抓取。
  - `plugins`：插件模块路径列表（如 `plugins.alljavxx_plugin`）。
  - `disable_global_link_extraction`：是否禁用全局链接提取（建议站点专项抓取设为 `true`，仅跟随插件返回链接）。
- 存储：
  - `storage.output_dir`：输出根目录（HTML/JSON/业务输出在此归档）。
  - `storage.sqlite_path`：SQLite 路径（建议放在输出根目录下）。
  - `storage.html_subdir`：页面快照的子目录（如 `pages`）。
- 抓取与反爬：
  - `max_concurrency`：并发抓取数。
  - `per_domain_delay_ms`：域级最小请求间隔（毫秒）。
  - `max_retries`、`retry_backoff_initial_ms`、`retry_backoff_max_ms`：退避重试策略。
  - `user_agents`、`proxies`：UA 与代理池（可选）。
  - `respect_robots_txt`：是否尊重 robots.txt。
- 登录：
  - `login.enabled`：是否启用登录。
  - `login.type`：登录类型（`form` 或 `api`）。
  - `login_url`、`username`、`password`、`payload`、`headers`、`captcha_solver_hook`（可选）。
- 插件参数：
  - `plugin_params`：为插件传入专用参数（如列表页增量抓取策略）。

—

## 五、插件开发（站点适配层）
插件是 nor_crawler 的核心扩展点。你只需编写插件与配置文件，无需更改框架代码。

### 5.1 插件职责
- 控制作用域：判断当前 URL 是否由本插件处理（如按域名或路径前缀）。
- 解析页面：从 HTML 中提取业务字段（列表条目、详情内容）。
- 输出与归档：把业务数据写入到插件专属目录（文本、图片、去重列表、失败列表等）。
- 调度链接：返回需要继续抓取的链接（详情页或分页链接）。

### 5.2 接口约定
- `should_handle(url: str) -> bool`：决定是否由本插件处理该 URL（通常检查域名/路径）。
- `handle(url: str, html: str, context: Dict[str, Any]) -> List[str]`：处理页面并返回下一步链接；`context` 包含：
  - `storage`：`crawler.storage.Storage` 实例（保存 HTML/JSON、提供输出目录）。
  - `fetcher`：抓取器实例（如需下载图片或做二次请求）。
  - `config`：完整配置对象（含 `plugin_params`）。
  - `plugin_params`：插件参数映射（同 `config.plugin_params`）。

### 5.3 典型设计模式（列表页 + 详情页）
- 列表页：
  - 解析条目，形成 `{keyword, image_url, detail_url}`；对“未在 `dedup.txt` 中”的关键字写入 `staging/<keyword>.json` 并返回其详情链接；发现分页链接（可选）并返回。
  - 增量策略：
    - `stop_when_zero_new=true`：若本页没有新增关键字（都已在 `dedup.txt`），停止继续翻页。
    - `max_pages_per_run=N`：一次运行最多翻 N 页（结合 `?page=` 解析）。
- 详情页：
  - 提取业务字段（内容、发布日期、类别等）；从 `staging` 恢复 `keyword` 与 `image_url`（若结构变动导致关键字解析失败）。
  - 下载图片（根据 URL/响应头识别扩展名），写入文本（采用“追加写入”），更新 `dedup.txt`，删除对应 `staging`。
  - 失败回滚：若文本写入失败或字段缺失，删除已写入的图片，记录到 `failed_keywords.txt`。

### 5.4 目录与命名
- 页面快照（HTML）：由框架保存到 `output_dir[/html_subdir]/`；文件名为 URL 安全化（替换 `/ : ?` 为 `_`）。
- 业务输出（插件）：建议在 `output_dir` 下建立站点专属子目录，如 `YourSite_Output/`，并在其中：
  - `data.txt`：文本汇总（关键字/内容/发布时间/类别/空行），采用“追加写入”。
  - `images/`：图片目录，文件名规则：`<keyword><ext>`，其中 `keyword` 会做文件名安全化；`.jpeg` 归一为 `.jpg`，无法识别时使用 `.bin`。
  - `dedup.txt`：已成功抓取的关键字列表；防止重复写入。
  - `failed_keywords.txt`：失败关键字列表；便于后续“失败重试模式”。
  - `staging/`：列表阶段的临时记录（详情成功后删除）；格式通常为包含 `keyword/image_url/detail_url` 的 JSON。

—

## 六、抓取策略与反爬（稳定性优先）
- 速率控制：
  - `per_domain_delay_ms` 控制域级最小请求间隔，合理设置避免触发限流或封禁。
  - `max_concurrency` 控制并发度；不要贪多，结合站点服务能力与自身网络/CPU资源调整。
- 退避重试：
  - 配置 `max_retries`、`retry_backoff_initial_ms`、`retry_backoff_max_ms`，应对网络波动、5xx 错误、超时等。
  - 重试应避免对 4xx（尤其 403/404）进行无意义重试；可以在插件中对具体状态码做判断。
- UA/代理轮换：
  - 配置 `user_agents` 与 `proxies`；轮换策略可以在抓取器中实现或扩展。
  - 代理质量不一，建议做好失败熔断与健康检查。
- robots.txt：
  - 尊重或按需关闭（`respect_robots_txt`）；对禁止抓取的路径应停止抓取。
- 登录态：
  - 启用登录后，在抓取前建立会话（Cookie/Token），避免匿名访问受限；表单登录与 API 登录均支持自定义 `payload` 与 `headers`。

—

## 七、HTML 解析与选择器技巧
- 结构识别：根据页面稳定的结构定位元素；避免使用易变的短类名或无语义标记。
- 文本清洗：使用 `.get_text(strip=True)` 去除空白；按需对换行/空格标准化。
- 链接标准化：对相对链接使用 `urljoin(base, href)` 转为绝对链接；去除片段 `#hash`。
- 选择器容错：为关键字段设置回退路径（如标题不存在则回退到备用位置）。
- 正则增强：对于关键字等规范文本，使用正则二次匹配提高鲁棒性（如 `[A-Za-z]{2,6}-\d{2,4}`）。

—

## 八、增量抓取与复跑
- 去重文件 `dedup.txt`：记录“已成功”关键字，作为唯一完成判据。
- 列表页增量：
  - `stop_when_zero_new=true`：当前页无新增条目（均在 `dedup` 中）时停止继续翻页，避免遍历旧页面。
  - `max_pages_per_run=N`：一次运行分页深度上限，控制运行时长与资源消耗。
- 中途停止：
  - 列表阶段未全部生成 `staging` 就停止：重启后会对“不在 `dedup` 中”的关键字继续写入或覆盖 `staging` 并返回详情链接；表现为“接上次继续生成缺失的 `staging`”。
  - 已生成全部 `staging` 后停止：重启后同样会重新写入/覆盖 `staging` 并返回详情链接（幂等、安全，不重复写最终数据）。
  - 默认行为：重启会“重新生成/覆盖 `staging` 并继续详情阶段”；如需改为“直接消费现有 `staging` 的 `detail_url`，跳过重新写 staging”，可做小幅代码改动作为可选策略。
- 详情阶段落盘：仅在详情成功后写入文本与图片、更新 `dedup` 并删除 `staging`；`data.txt` 采用“追加写入”。

—

## 九、持久化与目录规范
- 页面快照（HTML）：
  - 框架通过 `Storage.save_html(url, html)` 按 URL 安全化命名保存到 `output_dir[/html_subdir]/`。
  - `html_subdir` 可用来将页面快照与业务输出分离（建议设为 `pages`）。
- 解析结果（JSON）：
  - 可按需使用 `Storage.save_json(url, data)` 保存结构化数据到 `output_dir/`。
- 业务输出（插件自定义）：
  - 建议 `output_dir/YourSite_Output/` 下规范化组织（`data.txt`、`images/`、`dedup.txt`、`failed_keywords.txt`、`staging/`）。
- 命名规则（图片）：
  - 文件名 `<keyword><ext>`；`keyword` 做文件名安全化（替换 `/ : ?` 为 `_`）；`.jpeg` 归一为 `.jpg`，无法识别时使用 `.bin`。
- 写入策略（`data.txt`）：
  - 采用“追加写入”；通过 `dedup.txt` 避免重复记录；中途停止后重启不覆盖历史。

—

## 十、调试与排错
- 常见状态码：
  - 200：成功；应保存 HTML 快照。
  - 3xx：重定向；注意是否进入登录页或语言切换页。
  - 4xx：请求错误或禁止访问；检查 UA/Headers/登录态/代理质量。
  - 5xx：服务端错误；应用退避重试策略。
- 典型问题：
  - 图片未保存：通常还停留在列表阶段；需等待详情阶段成功落盘。
  - 结构变更：关键字段解析失败；为选择器添加回退路径或引入正则备选。
  - 代理失效：高失败率时更换代理或降低并发与速率。
  - 登录失效：Token/Cookie 过期；增加续期或在失败时重新登录。
- 日志与可观测性：
  - 插件中使用 `logging` 打印关键信息（入队链接数、去重命中、解析失败原因、写盘成功/失败）。
  - 对失败关键字建立集中列表（`failed_keywords.txt`），方便后续复跑或定向修复。

—

## 十一、性能优化与稳定性
- 抓取层优化：
  - HTTP/2 与合理超时；连接复用；控制域级速率与整体并发。
  - 退避重试：指数退避，避免拥塞与频繁失败重试。
- 解析层优化：
  - 避免过度深度的选择器；清洗逻辑尽量线性化；必要时做轻量正则匹配。
- 写盘优化：
  - 合理的文件组织与命名；避免频繁小文件写入导致碎片与性能下降。
- 资源控制：
  - 监控内存与文件句柄数量；长时间运行建议做分批次或分页上限控制。

—

## 十二、Playwright 渲染（可选）
- 使用建议：
  - 仅对 JS 重度页面启用；普通静态页面不建议渲染以减少复杂度与资源开销。
  - 渲染后仍由插件解析 HTML 内容并返回链接；保持插件逻辑纯粹。
- 注意事项：
  - 浏览器指纹与反自动化检测；可启用无头模式或定制指纹；谨慎对待登录流程中的动态校验。

—

## 十三、生产化部署建议
- 任务编排：
  - 通过计划任务（如 cron / Windows 任务计划）周期运行；按需设置分页上限与早停策略。
- 监控与告警：
  - 记录成功与失败计数、耗时与输出体量；在失败率超过阈值时告警。
- 存储归档：
  - 页面快照与业务输出分目录保存；按站点与时间分区；定期清理无用数据。
- 风险控制：
  - 对代理与登录态做健康检查与熔断；对异常行为（如短时间大量 403）自动降速或暂停。

—

## 十四、示例工作流（站点适配）
1) 需求确认：明确抓取范围（列表/详情）、要提取的字段（标题、内容、日期、类别、图片等）。
2) 结构探查：打开页面，定位稳定的选择器；为关键元素准备回退路径与正则备选。
3) 插件编写：实现 `should_handle` 与 `handle`，拆分“列表阶段（写 staging）”与“详情阶段（写业务数据）”。
4) 配置落地：填写 `seeds`、`allowed_domains`、`plugins`、`storage`（含 `html_subdir`）与插件参数（如增量策略）。
5) 运行调试：观察日志与输出目录，验证 `pages/` 与业务输出是否按预期生成；根据实际再微调速率与分页上限。
6) 稳定化：完善失败回滚与选择器回退；将失败关键字集中记录并建立复跑流程；根据站点节奏调整并发与限速。

—

## 十五、FAQ（常见问题）
- 第二次运行会覆盖 `data.txt` 吗？
  - 不会。`data.txt` 采用“追加写入”；通过 `dedup.txt` 防止重复记录。
- 停在列表阶段后重启会不会丢失数据？
  - 不会。重启会继续写入或覆盖 `staging` 并返回详情链接；最终数据只在详情成功后一次性写入。
- 图片扩展名如何识别？
  - 优先根据 URL 路径尾部匹配 `.(jpg|jpeg|png|webp|gif)(\d+)?$`；回退使用 `Content-Type`，`.jpeg` 归一为 `.jpg`，无法识别时使用 `.bin`。
- 能否只跟随插件返回的链接？
  - 可以。设置 `disable_global_link_extraction=true`，抓取范围更可控。
- 需要修改框架才能适配新站点吗？
  - 不需要。只需编写插件与配置文件；插件中实现解析逻辑与输出写入即可。

—

## 十六、参考与术语
- robots.txt：站点对抓取行为的声明与限制。
- 指数退避（Exponential Backoff）：在重试时逐步增加等待时间的策略。
- 去重（Dedup）：对已成功处理的条目做记录，避免重复处理。
- staging：列表阶段的临时文件，保存详情链接与必要字段；详情成功后删除。
- Playwright：浏览器自动化工具，用于渲染 JS 重度页面。

—

## 十七、结语
nor_crawler 的设计目标是让“站点适配”变得简单、清晰、稳健——你只需把站点结构与业务字段封装为一个插件，并提供相应的配置，即可在通用抓取与存储的加持下，快速构建出可复跑、可审计、可维护的爬虫系统。如果你需要把某些策略（如“重启后优先消费现有 staging”）设为默认行为，也可以在插件层做小幅改动并在文档中同步说明。

附：运行命令示例
- `python -m crawler.cli --config config/alljavxx.json`
- 视具体站点与策略调整 `max_concurrency`、`per_domain_delay_ms`、`plugin_params` 等参数。

—

如需针对你的目录或命名规范进一步优化（例如统一站点输出目录、细化日志格式、增加失败重试模式或报告），欢迎提出具体目标，我可以协助同步修改插件实现与说明文档。