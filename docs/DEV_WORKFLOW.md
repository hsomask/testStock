# 开发工作流程

## 分支策略

| 分支 | 用途 |
|------|------|
| `dev` | 开发分支，日常修改、功能测试 |
| `main` | 稳定部署分支，只接受 dev 测试通过后的合并 |

## 开发前

```bash
git checkout dev
git pull origin dev
git merge origin/main
git status
```

## 开发完成

```bash
git add .
git commit -m "描述本次修改"
git push origin dev
```

## 测试通过，合并发布

```bash
git checkout main
git pull origin main
git merge dev
git push origin main
```

## 服务器部署

```bash
git checkout main
git pull origin main
docker compose build
docker compose run --rm stock-report
```

## 验收命令

```bash
python -m analysis.validate_pipeline
```

## 注意事项

- 不要在 main 上直接开发
- 不要直接 push main
- 服务器只部署 main
- 出现冲突优先保留 main 的稳定逻辑
