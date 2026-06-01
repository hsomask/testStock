# V3-PostMerge M8B：数据库数据可信性审计与非交易日污染清理

## 当前背景

项目：`testStock`

当前问题：

非交易日曾经触发过邮件发送，说明系统里可能已经存在非交易日或错误日期生成的垃圾产物。

`email_sender.py` 的非交易日守卫已经修复。

下一步不是继续修入口，而是检查数据库中是否已经被写入了不可信数据。

---

## 一、本轮目标

本轮只做数据库可信性治理的第一版：

1. 新增数据库审计脚本；
2. 扫描数据库中非交易日日期是否存在数据；
3. 输出每个表、每个日期的异常行数；
4. 新增数据库清理脚本，但默认只 dry-run；
5. 不直接删除任何数据库数据；
6. 不修改业务逻辑；
7. 不修改日报生成逻辑；
8. 不修改 selector；
9. 不修改 report_renderer；
10. 不修改 email_sender。

---

## 二、允许新增文件

允许新增：

```text
analysis/db_data_audit.py
analysis/cleanup_invalid_db_data.py
```

可选新增文档：

```text
docs/DATA-TRUST-CLEANUP.md
```

---

## 三、禁止修改文件

禁止修改：

```text
analysis/daily_report.py
analysis/email_sender.py
analysis/report_renderer.py
analysis/selector.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
analysis/market.py
analysis/theme_detector.py
analysis/board_history.py
analysis/board_mapping_quality.py
analysis/board_trend_tracker.py
entrypoint.sh
data/config.py
```

本轮不改业务链路，只新增审计/清理工具。

---

## 四、重点审计表

优先审计这些表，存在则检查，不存在则跳过并记录：

```text
stock_signal
board_amount_ratio
pipeline_job_log
signal_tracker
signal_performance
backtest_result
```

如果数据库中实际表名不同，脚本应自动跳过不存在的表，不报错中断。

---

## 五、新增脚本 1：db_data_audit.py

新增：

```text
analysis/db_data_audit.py
```

运行方式：

```bash
python -m analysis.db_data_audit --date 20260531
```

也支持全量扫描最近日期：

```bash
python -m analysis.db_data_audit --days 30
```

如果 `--date` 和 `--days` 都没传，默认扫描最近 30 天。

---

## 六、db_data_audit.py 检查逻辑

### 1. 连接数据库

使用：

```python
from data.config import DATABASE_DSN
```

如果 `DATABASE_DSN` 缺失或连接失败，输出错误并正常退出，不抛出大异常。

---

### 2. 判断交易日

使用：

```python
from analysis.data_fetcher import is_trade_day
```

注意：

```text
trade_date 支持 YYYYMMDD
数据库中如果是 YYYY-MM-DD，需要统一转换比较
```

---

### 3. 检查表是否存在

每个表先查：

```sql
SELECT EXISTS (
  SELECT 1
  FROM information_schema.tables
  WHERE table_name = %s
)
```

不存在则跳过。

---

### 4. 统计每个日期行数

对每个表，如果存在 `trade_date` 字段，则执行：

```sql
SELECT trade_date, COUNT(*)
FROM table_name
GROUP BY trade_date
ORDER BY trade_date DESC
```

如果表没有 `trade_date` 字段，记录：

```text
skipped: no trade_date column
```

---

### 5. 识别异常

异常规则：

```text
非交易日存在数据：failed
交易日但行数异常为 0：不作为错误
表不存在：skipped
表无 trade_date 字段：skipped
```

第一版只检查非交易日污染，不判断策略质量。

---

## 七、db_data_audit.py 输出

打印摘要，并生成 JSON：

```text
reports/daily/db_data_audit.json
```

JSON 结构建议：

```json
{
  "status": "ok|warning|failed",
  "checked_tables": [],
  "skipped_tables": [],
  "invalid_dates": {
    "20260531": {
      "is_trade_day": false,
      "tables": {
        "stock_signal": {
          "rows": 35,
          "issue": "非交易日存在数据"
        },
        "board_amount_ratio": {
          "rows": 120,
          "issue": "非交易日存在数据"
        }
      }
    }
  },
  "cleanup_candidates": [
    {
      "table": "stock_signal",
      "trade_date": "20260531",
      "rows": 35
    }
  ]
}
```

---

## 八、新增脚本 2：cleanup_invalid_db_data.py

新增：

```text
analysis/cleanup_invalid_db_data.py
```

运行方式：

```bash
python -m analysis.cleanup_invalid_db_data --date 20260531 --dry-run
```

真正执行参数暂时保留，但第一版可以只打印提示，不做 delete：

```bash
python -m analysis.cleanup_invalid_db_data --date 20260531 --apply
```

---

## 九、cleanup_invalid_db_data.py 第一版要求

### 第一版只做 dry-run

默认：

```text
--dry-run
```

输出将要清理的候选：

```text
[DRY-RUN] stock_signal trade_date=20260531 rows=35
[DRY-RUN] board_amount_ratio trade_date=20260531 rows=120
```

### apply 第一版不要直接 delete

如果用户传：

```bash
--apply
```

第一版可以输出：

```text
[SAFE STOP] 第一版不执行数据库删除，请人工确认后再开放 apply
```

也就是说，当前版本不要执行 `DELETE`。

---

## 十、未来清理策略预留

脚本中可以预留注释：

```text
未来版本可支持：
1. INSERT INTO xxx_quarantine SELECT ...
2. DELETE FROM xxx WHERE trade_date = ...
```

但本轮不要实现自动删除。

---

## 十一、验收命令

执行：

```bash
python -m compileall analysis
python -m analysis.db_data_audit --date 20260531
cat reports/daily/db_data_audit.json
python -m analysis.cleanup_invalid_db_data --date 20260531 --dry-run
git diff --stat
git status --short --untracked-files=all
```

如果 20260531 没有数据库数据，可以再跑最近 30 天：

```bash
python -m analysis.db_data_audit --days 30
```

---

## 十二、预期 diff

理想 diff：

```text
analysis/db_data_audit.py
analysis/cleanup_invalid_db_data.py
```

可选：

```text
docs/DATA-TRUST-CLEANUP.md
```

不应该出现：

```text
analysis/daily_report.py
analysis/email_sender.py
analysis/report_renderer.py
analysis/selector.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
entrypoint.sh
data/config.py
reports/
__pycache__/
.claude/
PRDs/
```

---

## 十三、提交要求

如果验收通过：

```bash
git add analysis/db_data_audit.py analysis/cleanup_invalid_db_data.py
git commit -m "chore: add database data trust audit tools"
```

如果新增文档：

```bash
git add docs/DATA-TRUST-CLEANUP.md
git commit -m "docs: add database cleanup guide"
```

不要提交：

```text
reports/
__pycache__/
.claude/
.env
PRDs/V3-Stabilization.md
PRDs/V3-StabilizationM2.md
```

---

## 十四、本轮通过标准

1. 能扫描数据库表；
2. 能识别非交易日存在数据；
3. 能输出每个异常表的行数；
4. 能生成 `db_data_audit.json`；
5. cleanup 脚本默认 dry-run；
6. cleanup 脚本第一版不 delete；
7. 不改业务逻辑；
8. 不改日报生成；
9. 不改 selector；
10. 不改 email_sender；
11. 无 reports / pycache / local config 进入 Git。

# V3-PostMerge M8C：数据库污染隔离与安全清理

## 当前背景

M8B 数据库审计已经完成。

运行结果：

```text
python -m compileall analysis                     ✅ 编译通过
python -m analysis.db_data_audit --date 20260531  ✅ 无异常
python -m analysis.db_data_audit --days 30        ✅ 检测到污染数据
python -m analysis.cleanup_invalid_db_data --apply ✅ SAFE STOP，不真删
git diff --stat                                   ✅ 无业务文件修改
```

发现的非交易日污染数据：

```text
20260523: stock_signal(25行) + signal_performance(4行)
20260524: stock_signal(25行) + signal_performance(4行)
```

不存在并跳过的表：

```text
pipeline_job_log
signal_tracker
backtest_result
```

本轮目标是对已确认的数据库污染数据做安全隔离和清理。

---

## 一、本轮目标

本轮只做数据库清理工具的第二版：

1. 支持 `--apply`；
2. 不直接裸删；
3. apply 时先备份到 quarantine 表；
4. 备份成功后再删除原表污染行；
5. 只处理指定日期；
6. 只处理确认存在且有 `trade_date` 字段的表；
7. 输出每张表备份/删除行数；
8. 不修改任何业务逻辑。

---

## 二、允许修改文件

只允许修改：

```text
analysis/cleanup_invalid_db_data.py
```

可选修改：

```text
analysis/db_data_audit.py
```

仅当需要复用候选生成逻辑时允许小改。

可选新增文档：

```text
docs/DATA-TRUST-CLEANUP.md
```

---

## 三、禁止修改文件

禁止修改：

```text
analysis/daily_report.py
analysis/email_sender.py
analysis/report_renderer.py
analysis/selector.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
analysis/market.py
analysis/theme_detector.py
analysis/board_history.py
analysis/board_mapping_quality.py
analysis/board_trend_tracker.py
entrypoint.sh
data/config.py
```

---

## 四、清理范围

本轮只允许清理非交易日污染数据。

默认候选表：

```text
stock_signal
signal_performance
```

如果其他表不存在或没有污染，不处理。

本轮已确认污染日期：

```text
20260523
20260524
```

但脚本应支持任意指定日期：

```bash
python -m analysis.cleanup_invalid_db_data --date 20260523 --dry-run
python -m analysis.cleanup_invalid_db_data --date 20260523 --apply
```

---

## 五、quarantine 设计

不要直接删除。

对每个被清理表，创建对应 quarantine 表：

```text
stock_signal_quarantine
signal_performance_quarantine
```

如果 quarantine 表不存在，自动创建。

推荐方式：

```sql
CREATE TABLE IF NOT EXISTS stock_signal_quarantine AS
SELECT *, now() AS quarantined_at, 'initial_schema'::text AS quarantine_reason
FROM stock_signal
WHERE 1=0;
```

但注意：如果 `SELECT *, now() AS quarantined_at` 和原表字段冲突，需要避免重复字段名。

更稳妥方式：

1. 如果 quarantine 表不存在：

```sql
CREATE TABLE stock_signal_quarantine AS
SELECT *
FROM stock_signal
WHERE 1=0;
```

2. 然后确保补充元信息列：

```sql
ALTER TABLE stock_signal_quarantine
ADD COLUMN IF NOT EXISTS quarantined_at TIMESTAMP DEFAULT now();

ALTER TABLE stock_signal_quarantine
ADD COLUMN IF NOT EXISTS quarantine_reason TEXT;
```

3. 备份时：

```sql
INSERT INTO stock_signal_quarantine
SELECT *, now(), %s
FROM stock_signal
WHERE trade_date = %s
```

如果列数不匹配，需要动态拼接列名，避免 `SELECT *` 与新增列冲突。

建议用 information_schema 读取原表列名，显式 insert：

```text
原表列: code, name, trade_date, ...
quarantine insert columns: code, name, trade_date, ..., quarantined_at, quarantine_reason
select columns: code, name, trade_date, ..., now(), reason
```

---

## 六、apply 逻辑

`--dry-run`：

只打印：

```text
[DRY-RUN] stock_signal trade_date=20260523 rows=25
[DRY-RUN] signal_performance trade_date=20260523 rows=4
```

不写数据库。

`--apply`：

对每张表执行：

1. 查询候选行数；
2. 如果 0 行，跳过；
3. 确保 quarantine 表存在；
4. 插入候选行到 quarantine；
5. 确认插入行数等于候选行数；
6. 删除原表候选行；
7. commit；
8. 输出：

```text
[OK] stock_signal trade_date=20260523 quarantined=25 deleted=25
```

如果任一步失败：

```text
rollback
不要 delete
打印错误
```

---

## 七、安全限制

必须满足：

1. 没有 `--date` 不允许 `--apply`；
2. `--apply` 只允许单日期；
3. 如果日期是交易日，默认禁止清理；
4. 如果用户要清理交易日，必须显式加 `--force`，但本轮可以先不实现 `--force`；
5. 第一版只允许清理非交易日；
6. 不允许无条件删除全表；
7. SQL 必须带 `WHERE trade_date = %s`；
8. 删除前必须先 quarantine；
9. quarantine 插入失败不能 delete。

---

## 八、命令设计

支持：

```bash
python -m analysis.cleanup_invalid_db_data --date 20260523 --dry-run
python -m analysis.cleanup_invalid_db_data --date 20260523 --apply
```

如果用户传：

```bash
python -m analysis.cleanup_invalid_db_data --apply
```

没有 date，应拒绝：

```text
[SAFE STOP] --apply 必须指定 --date
```

如果日期是交易日：

```text
[SAFE STOP] 20260528 是交易日，不允许自动清理
```

---

## 九、验收命令

先 dry-run：

```bash
python -m compileall analysis
python -m analysis.cleanup_invalid_db_data --date 20260523 --dry-run
python -m analysis.cleanup_invalid_db_data --date 20260524 --dry-run
```

确认输出：

```text
stock_signal rows=25
signal_performance rows=4
```

再 apply：

```bash
python -m analysis.cleanup_invalid_db_data --date 20260523 --apply
python -m analysis.cleanup_invalid_db_data --date 20260524 --apply
```

然后重新审计：

```bash
python -m analysis.db_data_audit --days 30
```

预期：

```text
20260523 / 20260524 不再有 stock_signal / signal_performance 非交易日污染
```

同时检查 quarantine：

```sql
SELECT COUNT(*) FROM stock_signal_quarantine WHERE trade_date = '20260523';
SELECT COUNT(*) FROM signal_performance_quarantine WHERE trade_date = '20260523';
```

预期：

```text
25
4
```

---

## 十、预期 diff

理想 diff：

```text
analysis/cleanup_invalid_db_data.py
```

可选：

```text
analysis/db_data_audit.py
docs/DATA-TRUST-CLEANUP.md
```

不应该出现：

```text
analysis/daily_report.py
analysis/email_sender.py
analysis/report_renderer.py
analysis/selector.py
analysis/pipeline_check.py
analysis/report_regression_check.py
analysis/context/report_context.py
entrypoint.sh
data/config.py
reports/
__pycache__/
.claude/
PRDs/
```

---

## 十一、提交要求

如果验收通过：

```bash
git add analysis/cleanup_invalid_db_data.py analysis/db_data_audit.py
git commit -m "chore: support safe quarantine for invalid db data"
```

如果新增文档：

```bash
git add docs/DATA-TRUST-CLEANUP.md
git commit -m "docs: add database quarantine cleanup guide"
```

不要提交：

```text
reports/
__pycache__/
.claude/
.env
PRDs/V3-Stabilization.md
PRDs/V3-StabilizationM2.md
```

---

## 十二、本轮通过标准

1. `--dry-run` 不写数据库；
2. `--apply` 必须指定 `--date`；
3. `--apply` 只处理非交易日；
4. 清理前先写 quarantine 表；
5. quarantine 成功后才 delete；
6. 删除必须带 `WHERE trade_date = %s`；
7. 每张表输出 quarantined/deleted 行数；
8. apply 后 `db_data_audit --days 30` 不再报告 20260523/20260524 污染；
9. quarantine 表中能查到备份数据；
10. 不改业务逻辑。
