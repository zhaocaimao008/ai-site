# AI开源雷达(ai427.com)

每天自动更新的 AI 开源项目中文导航：
- GitHub Actions 每天北京时间 6:00 抓取 10 个分类下的 AI 开源项目(`config.json` 的 `categories`)
- 记录每个项目每天的 star 数,生成今日热榜、分类排行、近 7 天增长、历史日榜
- 新项目由 DeepSeek 根据 README 自动写中文介绍(每个项目只写一次,每天最多 `max_new_per_day` 个)
- 只有写好中文介绍的项目才生成详情页,避免低质量页面

## 一次性设置

1. 仓库设为公开;Settings → Pages → Source 选 **GitHub Actions**,Custom domain 填 `ai427.com`
2. Settings → Secrets and variables → Actions → New repository secret:
   名称 `DEEPSEEK_API_KEY`,值为 DeepSeek API 密钥(platform.deepseek.com)(不设置也能运行,只是不生成中文介绍)
3. 域名 DNS:4 条 A 记录 `@` → 185.199.108.153 / 109.153 / 110.153 / 111.153,CNAME `www` → `<用户名>.github.io`

## 费用

GitHub 部分免费。DeepSeek 费用取决于 `config.json` 的 `model` 和 `max_new_per_day`,
按充值余额扣费,余额用完会自动停止生成。

## 本地测试

```bash
python3 fetch.py --sample && python3 build.py
python3 -m http.server -d dist
```
