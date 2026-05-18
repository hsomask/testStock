# 常用命令参考

## Git

```bash
# 查看分支
git branch -a

# 切分支
git checkout dev
git checkout main

# 新建本地分支跟踪远程
git fetch origin
git checkout -b dev origin/dev

# 查看状态
git status

# 提交
git add <文件>
git commit -m "描述"

# 推送
git push origin dev
git push origin main

# 查看日志
git log --oneline -5
```

## 运行

```bash
# 每日报告
python -m analysis.daily_report                       # 默认小白友好版
python -m analysis.daily_report --mode beginner
python -m analysis.daily_report --mode pro
python -m analysis.daily_report --force               # 强制执行（非交易日也运行）

# 单独测试选股策略
python -m analysis.selector --indicator n_latent
python -m analysis.selector --indicator board_linkage
python -m analysis.selector --indicator n_latent,n_breakout,short_strong

# 板块成交占比写入
python -m analysis.board_history

# 个股板块映射更新（每周跑一次）
python -m analysis.stock_board_mapper

# 数据库初始化（首次）
python -m analysis.init_db
```

## 环境

```bash
# .env 文件配置
DATABASE_DSN=postgresql://user:pass@host:port/dbname
FEISHU_WEBHOOK=       # 飞书机器人 Webhook 地址（可选）
FEISHU_SECRET=        # 飞书签名校验密钥（可选）
MINIMAX_API_KEY=      # MiniMax AI API Key（可选）
```

## Docker

```bash
# 构建镜像
docker compose build

# 手动跑一次完整流程
docker compose run --rm stock-report

# 单独跑某个模块（覆盖 entrypoint）
docker compose run --rm stock-report python -m analysis.stock_board_mapper
docker compose run --rm stock-report python -m analysis.selector --indicator board_linkage
```

## 定时调度

```bash
# 宿主机 crontab（Linux）
# 每天晚上 21:00 执行完整流程
0 21 * * * cd /path/to/stock-ai-system && flock -n /tmp/stock-report.lock docker compose run --rm stock-report >> /var/log/stock-report.log 2>&1

# 每周一 9:00 更新个股板块映射
0 9 * * 1 cd /path/to/stock-ai-system && docker compose run --rm stock-report python -m analysis.stock_board_mapper >> /var/log/stock-mapper.log 2>&1
```

## 测试

```bash
python -m analysis.init_db
python -m analysis.stock_board_mapper
python -m analysis.board_history
python -m analysis.daily_report --mode beginner --force
python -m analysis.daily_report --mode pro --force
python -m analysis.selector --indicator board_linkage
```
