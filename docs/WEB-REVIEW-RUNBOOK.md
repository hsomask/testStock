# 网页本地运行与部署草案

状态：本地预览版，服务器部署未执行。个股新闻缓存和公开候选导出已实现；市场事件、正式纠偏对照和原附件下载尚未完成。
目标和进度分别见WEB-REVIEW-PLAN.md、WEB-REVIEW-PROGRESS.md。

## 本地运行

```bash
python -m pip install -r requirements-web.txt
python -m analysis.web_review_server --host 127.0.0.1 --port 8081
```

访问http://127.0.0.1:8081/。如果端口已占用，换一个空闲端口，不结束其他服务。
WEB_DATABASE_DSN优先；本地兼容DATABASE_DSN，连接强制只读，查询有5秒超时。
没有数据库也能展示reports/daily中的结构化摘要和计划，缺失显式展示。
接口不调用选股、补数、邮件、迁移或LLM。新闻采集独立于网页请求，使用原日报环境的AkShare依赖：

```bash
python -m analysis.web_review_events --date 20261014 --codes 605287
```

每次最多20只，每只独立子进程超时25秒，缓存reports/events；失败保留已有结果。
只保留标题、来源、链接及时间，不保存全文。补采旧日期标记事后证据，不能用于历史无前视回测。
尚未接入夜间调度；网页容器仅挂载只读缓存，不安装采集依赖。

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

使用独立compose.web.yml，不替换现有docker-compose.yml和cron。
配置WEB_DATABASE_DSN为专用SELECT账号；容器访问宿主机PostgreSQL需使用可达地址，
例如host.docker.internal，不应直接沿用宿主机的localhost。账号、pg_hba和防火墙由部署阶段核验。
该账号只需读取候选快照、K线、交易日历和规范评价视图。
不要向网页容器传SMTP密码或全部日报环境变量。

```bash
docker compose -f compose.web.yml build stock-web
docker compose -f compose.web.yml up -d stock-web
docker compose -f compose.web.yml ps
docker compose -f compose.web.yml logs --tail 50 stock-web
```

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
- K线缓存复权口径未逐行记录，可能混源；不自动计算旧计划是否触价。
- 层级延续不等于逻辑兑现；未再次入选不等于逻辑失效。
- 策略成绩为正式T+1信号统计，不含交易成本、成交约束及同池实验。
- 个股新闻检索只是相关线索，不输出消息因果解释；市场与板块事件尚未接入。
- 已提供公开候选MD/Excel，不替代原邮件审计附件和板块趋势Excel。
- 邮件改版、完整事件链路及服务器验收未完成，不能标记全部里程碑完成。
