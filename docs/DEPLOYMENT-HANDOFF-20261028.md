# 服务器部署交接：2026-10-28

## 新对话先读

这是本次对话迁移的现场记录。服务器状态来自用户执行命令后回传的截图，并非助手直接 SSH 检查。不要重新从头部署，也不要把本地测试通过当作服务器全链路完成。

当前任务：完成复盘网页上线，随后让每日数据采集、评价、发布继续运行，以网页替代日报邮件。用户在服务器执行命令，助手逐步给命令并根据回传结果推进。

**目前停在：服务器内部验收通过、8081 已对外监听，等待用户确认公网浏览器能否打开。邮件开关尚未切换，真实当日日报链路尚未验收。**

## 代码与文档

- 本机目录：`D:\code\stock-ai-system`，开发分支 `dev`。
- 本机本轮交接前 HEAD：`9da629f fix: make web delivery resilient to board acquisition failures`，此前已经推送。
- 服务器 `/root/stock-ai-system`，分支 `main`，用户已合并并拉取，截图 HEAD 为 `c3802f7`（Merge PR #61）。已通过祖先检查确认包含 `9da629f`。
- 前次网页提交 `e98df59`，初版 `0b2736f`。
- 主要参考：`WEB-REVIEW-PLAN.md`、`WEB-REVIEW-PROGRESS.md`、`WEB-REVIEW-DATA-CONTRACT.md`、`WEB-REVIEW-RUNBOOK.md`。
- 原 `codex-handoff.md` 中早期本地路径及“当前状态”属于历史记录，不代表此次现场。
- 本机有两份无关未跟踪文档，保留：`PRDs/V4-Stabilization-2.md`、`PRDs/fixed/V4-Stabilization-1.md`。
- 服务器存在原有已跟踪文件删除：`reports/daily/daily_report_20260517.md`。不要 reset/restore；因此目前使用直接 compose 命令，未走要求干净工作区的部署脚本。
- 本交接文档是新生成的记录，尚未提交；后续先检查 git 状态，再决定同步方式，不要覆盖它。

## 用户确定的产品范围

- 手机为主，兼容 iPad；收盘后理解市场，开盘前看昨晚报告。
- 市场到板块到个股，解释发生了什么、入选依据、原有逻辑是否仍成立；事实与推测分开。
- 首页系统候选 10 只，保留本地关注；创业板仅研究展示，用户目前不能交易。
- 市场差时不推荐新买入，并说明理由。
- 首版不做登录、社交、持仓成本管理；用户接受公网 IP 直接访问。公开内容不要放敏感数据。
- 新闻只保存标题、链接、来源、时间等元信息，不下载正文或图片；保留 7 个自然日，随采集清理，不新增 cron。
- 不改原有评分逻辑，不为网页叠加重复业务链路。后续开发必须持续记录里程碑。

## 服务器已确认配置

- 阿里云 IP：`8.146.237.37`，Ubuntu 24.04.2，2 CPU，1.6 GiB 内存，无 swap，磁盘剩余约 19 GB。
- PostgreSQL 16 在宿主机 5432，数据库 `stock_db`，监听 `*`。
- 原业务账号 `stock_user`、原业务连接保持不变。
- 律师容器经用户要求已经停止：`testlawyer-web-1`、`testlawyer-api-1`，没有删除数据。需要恢复时：`docker start testlawyer-api-1 testlawyer-web-1`。
- 网页独立 compose：`compose.web.yml`，项目 `stock-review-web`，服务 `stock-web`，容器 `stock-review-web-stock-web-1`，镜像 `stock-review-web:local`。
- 网页 Docker 网络 `stock-review-web_default`：`172.19.0.0/16`；`host.docker.internal` 解析为 `172.17.0.1`。
- 网页只读角色 `stock_web_reader` 已创建，设置只读事务、5 秒语句超时、连接上限 6。
- 已授予数据库连接、public schema 使用以及五张表 SELECT：`candidate_feature_snapshot`、`stock_hist_kline`、`exchange_calendar`、`canonical_daily_evaluation_result`、`canonical_daily_evaluation_summary`。
- `/etc/postgresql/16/main/pg_hba.conf` 已备份并加入：`host stock_db stock_web_reader 172.19.0.0/16 scram-sha-256`，已 reload。
- `.env` 已备份且权限 0600，`WEB_DATABASE_DSN` 使用只读账号和 URL 编码密码，地址为 `host.docker.internal:5432/stock_db`，连接超时 5 秒。不要输出密码或完整 DSN。
- `WEB_PORT=8081`，最新 `WEB_BIND_ADDRESS=0.0.0.0`。
- 未改变原有 cron；未确认云安全组与主机防火墙是否已放行 8081，不能假设公网已通。不要对公网开放 5432。

## 已完成并验证的部署步骤

1. `docker compose build stock-report` 成功。
2. `docker compose run --rm --entrypoint python stock-report -m analysis.report_publication --date 20261021` 返回 `success`。发布既有历史产物，非重新采集历史行情。
3. `docker compose -f compose.web.yml build stock-web` 成功。
4. 解决容器访问数据库的 HBA 拒绝：最初追加规则后漏 reload，之后已 reload。
5. 解决密码不一致：通过 psql 的 `\password stock_web_reader` 重置；隐藏输入同一密码，先验证再更新 `.env`。不需要重做账号与 HBA。
6. `docker compose -f compose.web.yml up -d --no-build stock-web` 成功。
7. 容器内 `analysis.web_review_smoke.check_release("http://127.0.0.1:8081", "20261021")` **总结果 pass**。该测试含发布数据、API、个股 K 线、静态资源、导出、私有路径和只读限制等检查。
8. 原本绑定 127.0.0.1 的容器已出现 healthy。修改绑定为 0.0.0.0 后重新 up，截图显示 `0.0.0.0:8081->8081/tcp`，新容器当时 health starting。
9. 修改绑定后宿主机 `curl --fail --max-time 10 http://127.0.0.1:8081/healthz` 返回 `{"mode":"read_only","status":"ok"}`。

Compose 的 version obsolete、buildx 缺失警告没有阻止以上构建，不要把它们当作当前故障。

## 下一步按顺序执行

### 1. 公网可达性与页面验收

请用户用电脑或手机打开 `http://8.146.237.37:8081/?date=20261021`，确认首页、日期切换、个股详情和 K 线。

若打不开，先核查容器状态、端口和服务器防火墙，再核查阿里云安全组，按最小范围放行 TCP 8081。不要停用整个防火墙，不要修改数据库对公网规则。若能打开，记录实测结果，不仅凭 healthz 宣布全站完成。

### 2. 网页交付替代邮件

公网与功能通过后，再核对代码/运行手册中的配置，切换 `REPORT_DELIVERY=web`，保留原有采集和统一 pipeline 定时任务。

可选故障通知 `REPORT_FAILURE_EMAIL=1` 为独立失败邮件，默认关闭；与用户明确是否开启。不要把“不要日报邮件”理解成停止采集、评价或发布。

先读取服务器当前 crontab（不要猜测旧截图仍有效），确认它使用统一入口且没有重复任务。不要直接覆盖整份 crontab。配置切换后检查哪些容器需要重建或重建实例，不要无意义重编译所有服务。

### 3. 真实日报链路验收

截图当天为 2026-10-28，最近操作约 14:30。代码禁止在 15:00 前生成当日实时报告，也禁止用实时行情冒充历史日。必须先确认当前服务器日期时间、交易日，再按现有入口收盘后执行。

当前网页用于部署验收的是 20261021，不代表已经恢复最新每日采集。真实跑通后确认：核心行情成功、评价状态、发布状态 success/partial、网页最新日期推进、邮件跳过行为、故障通知行为。不能只看容器 healthy。

若行情上游失败，保留上一份成功发布报告，网页应显示失败/降级状态，不把旧数据冒充今日。不要伪造补历史数据。

### 4. 完成记录

把现场验收、公网端口、交付开关、实际 cron、最新发布日期和未解决风险写入进度文档；记录回滚方式，再判断是否完成部署。尚未确认公网访问前，不要声称已经全面上线。

## 最新修复概要（供定位，非要求重新开发）

- `analysis/delivery_policy.py`：email/web 交付模式，默认 email。
- `analysis/pipeline_runner.py`、`daily_reconciliation.py`、`email_sender.py`：web 模式跳过日报邮件；采集、评价、发布仍执行。
- `analysis/acquisition_guard.py`、`entrypoint.sh`、`daily_report.py`：板块上游采集有时间预算和有限重试；禁止盘前/历史日实时采集。
- `selector.py`、`trade_plan.py`：板块缺失不沿用旧板块联动信号，禁新交易、仓位上限归零，保留其他观察；非修改原评分公式。
- `analysis/report_publication.py`、`report_dispatcher.py`：校验同日三份核心 JSON 后原子发布 `published_YYYYMMDD.json`，记录状态；失败保留旧版本。
- `web_review_data.py`、`web_review_service.py`、`web/static/app.js`：优先读取发布包，隐藏未发布半成品，显示发布失败/降级提示。
- `analysis/report_failure_notice.py`：可选失败邮件，独立于日报邮件，有限超时与成功记录去重。

之前无邮件的已定位原因是板块行情采集 EastMoney 请求重试仍失败，`set -e` 导致日报阶段退出，日报邮件被依赖阻断，不是 SMTP 问题。旧服务器曾长期停留 9 月代码，现在已经更新，不要再按旧版本诊断。

## 测试证据与边界

- 推送前 74 项相关 unittest 通过：report_resilience、delivery_policy、web_review_data、web_review、web_review_release、web_review_email 对应 regression_check。
- 独立 pipeline_runner、trade_plan、report_dispatcher、daily_reconciliation、daily_intelligence 回归通过；shell 语法、编译与 git diff 检查通过。
- 手机/iPad 本地浏览器检查通过（部分异常状态用测试夹具）。
- 服务器 20261021 完整发布冒烟已 pass；**公网手机访问、最新交易日采集发布、正式切换 web 后的每日运行尚未验证**。
- 历史新闻过期允许明确显示；7 天保留规则不删除日报、K 线或 ML 数据。
- 失败通知未实际发 SMTP 验证；进程被强杀可能留下 running，需要后续观察，不能承诺完全自动恢复。

## 操作纪律

- 用户执行服务器命令并回传，每次给一小步，尤其密码输入与后续命令分开。
- 不需要 SSH 密钥，不读取或展示 `.env` 全文。
- 修改代码前检查 git 状态并同步远端；保留未提交工作，不做破坏性 reset。
- 先定位相关 3–5 个文件，说明最小计划，再改动和最小验证；无授权不做大架构重写。
- 本文是交接记录，不是已执行的未来操作清单；“下一步”都仍待完成。
