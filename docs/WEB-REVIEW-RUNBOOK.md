# 网页本地运行与部署草案

状态：本地预览版，服务器部署未执行。个股新闻缓存和公开候选导出已实现；市场事件、正式纠偏对照和原附件下载尚未完成。
目标和进度分别见WEB-REVIEW-PLAN.md、WEB-REVIEW-PROGRESS.md。

## 本地运行

```bash
python -m pip install -r requirements-web.txt
python -m analysis.web_review_server --host 127.0.0.1 --port 8081
```

访问http://127.0.0.1:8081/。如果端口已占用，换一个空闲端口，不结束其他服务。
本次2026-10-23验证使用8082：`python -m analysis.web_review_server --port 8082`。
重启后先检查/api/strategies/日期包含correction，避免浏览器仍在访问旧实例；最新真实纠偏验收日期20261021。
WEB_DATABASE_DSN优先；本地兼容DATABASE_DSN，连接强制只读，查询有5秒超时。
没有数据库也能展示reports/daily中的结构化摘要和计划，缺失显式展示。
接口不调用选股、补数、邮件、迁移或LLM。新闻采集独立于网页请求，使用原日报环境的AkShare依赖：

```bash
python -m analysis.web_review_events --date 20261014 --codes 605287
```

每次最多20只，每只独立子进程超时25秒；整批默认120秒，可用--time-budget设置1至600秒。
预算耗尽的股票返回budget_exhausted。缓存reports/events；失败或空结果保留已有结果，
缓存不可写返回cache_unwritable，旧证据仍保留原发布时间/采集时间，不标成新采集结果。
只保留标题、来源、链接及时间，不保存全文。补采旧日期标记事后证据，不能用于历史无前视回测。
已接入现有pipeline_runner的web_news可选步骤，cron命令不变。
顺序为daily_report、daily_email、web_news、daily_reconcile；web_news只依赖daily_report，
邮件失败仍采集、日报失败则阻止；新闻失败/降级记录在子任务与parent metadata.optional_issues，
不改变日报主流程状态。默认启用，设置WEB_NEWS_ENABLED=0可关闭，无须改cron。
自动采集仅使用当天daily_decision_v1规范计划，按原顺序去重取前20只主板/创业板代码，
包括观察和回避记录，不意味着这些股票可交易；不读取浏览器个人关注。
缺失、日期不符、旧格式或空计划跳过，不回退到昨日计划。
网页容器仅挂载只读缓存，不安装采集依赖；日报容器已有AkShare并挂载reports目录。
同一批任务先采集东方财富财经快讯，再采集个股，合计仍受120秒预算限制。
市场快讯最多保留50条标题/来源/链接；按时间排列，不标记因果。板块关联仅匹配标题中明确出现的板块名称，
未命中不等于没有消息，命中不等于驱动涨跌。历史日期不能从当前快讯列表可靠回补。

网页读取同日daily_intelligence解读和reports/evaluation/correction_effectiveness_DATE.json审计。
Compose已只读挂载evaluation目录，API仅选择公开统计字段，不开放该目录浏览或原始明细下载。
纠偏按原产物口径展示样本与分组收益，不把组间均值差称作纠偏净收益；事后生成时间明确显示。

邮件在原日报环境设置WEB_PUBLIC_URL（如正式公网网页根地址）后附带?date=YYYYMMDD链接；
不设置则保留原邮件。只有公网验收通过后才配置正式地址，避免邮件包含不可访问链接。
原附录MD和板块Excel附件保持不变；预览--dry-run不发送邮件，也不写任务账本。
本轮没有关闭邮件。未来仅网页模式必须同步调整pipeline完成门禁和失败提醒，不能简单删除发送步骤。

主流程完成后再次运行会按既有幂等规则跳过；若只需补新闻，使用原日报运行环境：

```bash
python -m analysis.web_review_events --date 20261021 --from-plan --time-budget 120
```

服务器可使用原stock-report镜像：

```bash
docker compose run --rm --entrypoint python stock-report -m analysis.web_review_events --date 20261021 --from-plan --time-budget 120
```

日期应替换成需要补采且已有规范计划的日期。此命令不重跑选股、不写业务表、不发送邮件。
自动入口退出码：0完成（可能没有匹配消息）、2部分失败/预算耗尽、3无有效计划而跳过。
编排器分别记录success/deferred/skipped；其他异常记failed但不使主流程失败。
以上命令属于部署后的运行方式，本轮未修改服务器配置、未实际部署。

```bash
python -m unittest analysis.web_review_data_regression_check analysis.web_review_regression_check
```

浏览器检查使用Playwright及Chromium：

```bash
node tests/web_review_browser_check.cjs
```

可通过NODE_PATH指定已有Playwright安装，WEB_BROWSER_EXECUTABLE指定Chrome/Chromium路径，
WEB_REVIEW_URL指定测试地址。当前真实数据检查使用20260626及605287；换环境需提供对应数据。
截图写到logs/web-review-qa，不提交报告和截图中的个股数据。

## 服务器部署（待现场验证）

### 发布前提

- 使用已提交且无跟踪文件修改的代码；先合并到main，再在服务器按原发布流程拉main。
- 本机未安装Docker，不能用本地Python测试替代镜像构建验收。
- `.env`设置WEB_DATABASE_DSN（专用只读账号），不要贴出口令。WEB_BIND_ADDRESS默认127.0.0.1，公网发布显式设置0.0.0.0；WEB_PORT默认8081。
- reports/daily必须是原日报产物目录；容器uid10001需要目录遍历与文件读取权限，不授予写权限。
- PostgreSQL的访问授权只允许必要容器网段/账号，不对公网开放5432；80端口已有服务不动。
- 正式运行前确认8081未占用，保留旧镜像与配置，预留构建内存。192MiB是网页运行限制，不限制镜像构建资源。

### 标准发布入口

```bash
bash scripts/deploy_web.sh 20261021
```

日期换成服务器预期已完成的最近一个日报日期，不自动猜今天或用旧日期兜底。
脚本只操作独立Compose项目stock-review-web，镜像以提交号和UTC时间标记。
Dockerfile.web.dockerignore仅允许网页代码和依赖进入构建上下文，不发送.env、日志、报告或Git目录。
先检查文件存在、构建新镜像，再替换网页容器；等待存活检查后，在容器内检查指定日期的真实数据。
验收涵盖数据库、完整市场字段、主题字段、规范计划、源冲突、策略读取、首只候选的K线/历史、静态资源、导出、私有路径拒绝和写请求拒绝。
失败会尝试恢复发布前正在运行的网页镜像；首次发布失败则停止新网页。回滚失败只打印错误，必须现场核实状态。
成功写logs/web-release-时间.txt，并打印回滚命令；不输出数据库凭证。
此检查只覆盖容器内可达性，不能替代公网、安全组、手机实际访问和服务器资源验收。

单独复查，无构建/写库/邮件：

```bash
docker compose -f compose.web.yml exec -T stock-web python -m analysis.web_review_smoke --date 20261021
docker compose -f compose.web.yml ps
docker stats --no-stream
```

仅进程存活使用/healthz；正式发布不能仅凭该接口成功。新闻缺失不阻塞上线，市场摘要和规范计划缺失会阻塞。
发布完成后继续使用deploy_web.sh更新；不要用默认local镜像手动up替换已发布的版本镜像。

使用独立compose.web.yml，不替换现有docker-compose.yml和cron。
配置WEB_DATABASE_DSN为专用SELECT账号；容器访问宿主机PostgreSQL需使用可达地址，
例如host.docker.internal，不应直接沿用宿主机的localhost。账号、pg_hba和防火墙由部署阶段核验。
该账号只需读取候选快照、K线、交易日历和规范评价视图。
不要向网页容器传SMTP密码或全部日报环境变量。

查看日志：`docker compose -f compose.web.yml logs --tail 50 stock-web`。

默认只绑定127.0.0.1，避免未验收版本意外公开。
按用户确认的IP直接访问方式发布时，显式设置WEB_BIND_ADDRESS=0.0.0.0，
并在阿里云安全组开放所选WEB_PORT。无登录，内容公开只读。
个人关注仅存当前浏览器，不跨设备同步；相同设备换域名/协议/端口也属于不同存储空间。

镜像不包含.env、数据库口令或主链启动入口。容器非root、只读文件系统、
报告目录只读挂载；静态服务仅开放web/static，API字段白名单。
192MiB和0.5CPU是初始限制，不代表已验证在服务器夜间峰值下足够。

## 回滚

发布前保留旧镜像标签与配置。若仅停用网页：

```bash
docker compose -f compose.web.yml stop stock-web
```

这不会停止日报任务、PostgreSQL或法律工具。
真正的发布验收须记录镜像/提交、访问URL、healthz、内存峰值及回滚版本。

## 当前限制

- 数据库候选快照不包含全市场宽度；文件摘要缺失时不从候选反推全市场。
- 摘要文件存在不代表完整：readiness列出缺失市场字段，partial_market不进行完整市场日间比较。
- 本地2026-10-23核对仅有7天历史摘要，最新20260626。上线须核对服务器reports/daily只读挂载，不能把本地缺文件当成服务器缺数据。
- K线缓存复权口径未逐行记录，可能混源；不自动计算旧计划是否触价。
- 层级延续不等于逻辑兑现；未再次入选不等于逻辑失效。
- 策略成绩为正式T+1信号统计，不含交易成本、成交约束及同池实验。
- 市场/个股资讯已接入；板块只有标题字面关联，未实现自动可靠因果解释或LLM解释。
- 已提供公开候选MD/Excel，不替代原邮件审计附件和板块趋势Excel。
- 邮件已有日期链接，原附件保留；LLM解释、因果纠偏对照及服务器验收未完成，不能标记全部里程碑完成。
# 新闻缓存保留与权限（2026-10-23）

## 网页模式与故障恢复（2026-10-28）

- `.env`新增`REPORT_DELIVERY=web`后，日常日报邮件关闭；默认或`email`保持原发送行为。`REPORT_FAILURE_EMAIL=1`单独启用故障邮件，默认0。不要在未验收网页之前切换。
- 保留原cron和统一入口；更新时同时重建stock-report分析镜像及独立网页镜像，仅更新网页容器不会修复采集。源码合并main不等于服务器镜像已更新。
- 新增published_YYYYMMDD.json是校验后原子发布的摘要/交易计划/intelligence整包，仍存reports/daily；publication_state_YYYYMMDD.json记录尝试状态。无需数据库迁移或新增挂载。网页不以半生成文件替换已发布包。
- 首次部署可对已有完整产物运行`docker compose run --rm --entrypoint python stock-report -m analysis.report_publication --date YYYYMMDD`。日期必须替换成实际完整报告日；缺少核心数据/规范计划时命令会失败，不要手工造文件越过校验。
- 当天生成必须在北京时间收盘后运行；已有历史信号仍走恢复/重渲染。不存在的历史行情不能靠实时接口补造。采集异常时保留旧发布包，状态单独标失败。
- 板块缺失发布partial并暂停新增推荐；核心行情缺失不发布。部署冒烟检查增加report_published；新闻的非关键失败不影响日常日报任务，但首次发布验收仍需核对新闻读取。
- 本地仅验证了模拟故障和只读网页；上线仍需真实采集、非root文件读取、Docker健康和公网访问验收。

- 只保存标题、超链接、来源和时间，不保存新闻正文、图片或视频。
- 新闻CLI在采集前清理过期缓存，按北京时间保留当天及前6个自然日，无需新增cron。停机期间不会清理，下次采集时补清理。
- 仅清理reports/events中合法日期+股票代码或market的JSON文件；不递归、不处理符号链接、不触碰日报/K线/ML样本。清理失败数输出到任务日志。
- 超出保留期的日期跳过采集；历史页面没有缓存时显示过期，不用当前消息代替。
- 新缓存采用0644权限，网页容器保持非root只读。旧的0600缓存需要对仍在保留期内的日期重新采集；不对整个reports递归放宽权限。
- 发布检查新增market_news_readable：available/empty有效，expired为历史保留策略豁免；invalid/failed/not_collected不通过。新闻失败仍不阻断日常日报及邮件任务。
