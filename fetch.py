#!/usr/bin/env python3
"""每日数据更新:抓取 GitHub 上的 AI 开源项目,记录 star 历史,并用 Claude 为新项目写中文介绍。

用法:
    python3 fetch.py            # 正式运行(需要环境变量 GITHUB_TOKEN;有 ANTHROPIC_API_KEY 时生成中文介绍)
    python3 fetch.py --sample   # 用模拟数据离线测试

数据保存在 data/ 目录,由 GitHub Actions 提交回仓库:
    data/repos.json          最新抓到的项目元数据
    data/history.json        每个项目每天的 star 数(保留 60 天)
    data/desc/<id>.json      Claude 生成的中文介绍(每个项目只生成一次)
    data/daily/<日期>.json    当天热榜存档
"""
import base64
import datetime as dt
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
DESC = DATA / "desc"
DAILY = DATA / "daily"
TODAY = dt.date.today().isoformat()
README_CHARS = 8000  # 只把 README 开头这部分交给 Claude,控制费用


def rid(full_name):
    return full_name.replace("/", "--").lower()


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


# ---------- GitHub ----------

def gh(path, raw=False):
    req = urllib.request.Request("https://api.github.com" + path, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "User-Agent": "ai-site",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read() if raw else json.load(r)


def search(q):
    path = "/search/repositories?" + urllib.parse.urlencode({"q": q, "sort": "stars", "per_page": 50})
    for attempt in range(3):
        try:
            return gh(path)["items"]
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and attempt < 2:
                time.sleep(60)
                continue
            raise
    return []


def slim(item, cat):
    lic = item.get("license") or {}
    return {
        "full_name": item["full_name"], "url": item["html_url"], "description": item.get("description") or "",
        "homepage": item.get("homepage") or "", "stars": item["stargazers_count"], "forks": item["forks_count"],
        "language": item.get("language") or "", "license": lic.get("spdx_id") or "", "topics": item.get("topics", []),
        "created_at": item["created_at"][:10], "pushed_at": item["pushed_at"][:10], "archived": item.get("archived", False),
        "cats": [cat],
    }


def collect(cfg):
    repos = {}
    since = (dt.date.today() - dt.timedelta(days=cfg["new_repo_days"])).isoformat()
    for cat, c in cfg["categories"].items():
        for topic in c["topics"]:
            for q in (f"topic:{topic} stars:>={cfg['min_stars']}",
                      f"topic:{topic} stars:>={cfg['new_repo_min_stars']} created:>={since}"):
                for item in search(q):
                    if item.get("archived") or item.get("fork"):
                        continue
                    r = repos.get(item["full_name"])
                    if r:
                        if cat not in r["cats"]:
                            r["cats"].append(cat)
                    else:
                        repos[item["full_name"]] = slim(item, cat)
                time.sleep(2.5)  # 搜索接口限速 30 次/分钟
    return repos


def readme(full_name):
    try:
        d = gh(f"/repos/{full_name}/readme")
        return base64.b64decode(d["content"]).decode("utf-8", "replace")[:README_CHARS]
    except Exception:
        return ""


# ---------- Claude ----------

SYSTEM = """你是一个中文 AI 开源项目导航网站的编辑。根据给出的 GitHub 项目信息和 README,为中文读者写一份准确、实用的项目介绍。

要求:
- 只写 README 和项目信息里能确认的内容,不要编造功能、数据、公司背景或评价;信息不足时宁可少写。
- 语言简洁自然,面向想了解和上手这个项目的开发者与普通用户,不要营销腔。
- 专有名词、命令、模型名保留英文原文。
- quickstart 只在 README 给出了安装或使用方法时填写,命令必须来自 README;没有就返回空数组。
- 如果这个项目实际上与 AI 无关,或只是资料合集、教程目录、空项目,ai_related 填 false。"""

SCHEMA = {
    "type": "object",
    "properties": {
        "ai_related": {"type": "boolean"},
        "tagline": {"type": "string", "description": "一句话介绍,不超过 40 个汉字"},
        "intro": {"type": "string", "description": "项目介绍,150~300 个汉字,可分 2~3 段,段落之间用换行分隔"},
        "features": {"type": "array", "items": {"type": "string"}, "description": "3~6 条主要功能"},
        "audience": {"type": "string", "description": "适合谁使用,1~2 句话"},
        "quickstart": {"type": "array", "items": {"type": "string"}, "description": "2~5 个上手步骤,可含 README 中的命令"},
    },
    "required": ["ai_related", "tagline", "intro", "features", "audience", "quickstart"],
    "additionalProperties": False,
}


def describe(client, cfg, repo, text):
    info = {k: repo[k] for k in ("full_name", "description", "homepage", "language", "license", "topics", "stars")}
    resp = client.messages.create(
        model=cfg["model"],
        max_tokens=8000,
        system=SYSTEM,
        output_config={"effort": cfg["effort"], "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": f"项目信息:\n{json.dumps(info, ensure_ascii=False)}\n\nREADME(开头部分):\n{text}"}],
    )
    if resp.stop_reason != "end_turn":
        print(f"  跳过 {repo['full_name']}:stop_reason={resp.stop_reason}")
        if resp.stop_reason == "refusal" and resp.stop_details:
            print(f"    {resp.stop_details.category}: {resp.stop_details.explanation}")
        return None
    out = json.loads(next(b.text for b in resp.content if b.type == "text"))
    out.update({"model": resp.model, "date": TODAY})
    return out


def sample_desc(repo):
    return {"ai_related": True, "tagline": f"{repo['full_name'].split('/')[1]} 的示例一句话介绍",
            "intro": "这是离线测试用的示例介绍。\n正式运行时由 Claude 根据 README 自动生成。",
            "features": ["示例功能一", "示例功能二", "示例功能三"], "audience": "示例适用人群。",
            "quickstart": ["git clone " + repo["url"], "按 README 安装依赖"], "model": "sample", "date": TODAY}


def sample_repos(cfg):
    rng = random.Random(TODAY)
    repos = {}
    for i in range(60):
        cat = list(cfg["categories"])[i % len(cfg["categories"])]
        name = f"demo-org/project-{i}"
        repos[name] = {"full_name": name, "url": f"https://github.com/{name}", "description": f"Demo project {i}",
                       "homepage": "", "stars": 300 + i * 137 + rng.randint(0, 200), "forks": 10 + i, "language": "Python",
                       "license": "MIT", "topics": cfg["categories"][cat]["topics"][:1], "created_at": "2026-09-01",
                       "pushed_at": TODAY, "archived": False, "cats": [cat]}
    return repos


# ---------- 主流程 ----------

def main():
    sample = "--sample" in sys.argv
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    repos = sample_repos(cfg) if sample else collect(cfg)
    print(f"抓到 {len(repos)} 个项目")
    save(DATA / "repos.json", repos)

    # star 历史
    hist = load(DATA / "history.json", {})
    cutoff = (dt.date.today() - dt.timedelta(days=60)).isoformat()
    for name, r in repos.items():
        h = hist.setdefault(name, {})
        h[TODAY] = r["stars"]
        for d in [d for d in h if d < cutoff]:
            del h[d]
    save(DATA / "history.json", hist)

    # 为还没有介绍的项目生成中文介绍:优先新项目和 star 多的
    todo = [r for r in repos.values() if not (DESC / f"{rid(r['full_name'])}.json").exists()]
    todo.sort(key=lambda r: (r["created_at"] < (dt.date.today() - dt.timedelta(days=cfg["new_repo_days"])).isoformat(), -r["stars"]))
    todo = todo[:cfg["max_new_per_day"]]
    # 运行结果写入 data/status.json,方便在仓库里直接查看(不含任何密钥)
    status = {"date": TODAY, "repos": len(repos), "todo": len(todo), "key_present": bool(os.environ.get("ANTHROPIC_API_KEY")),
              "model": cfg["model"], "generated": 0, "skipped": [], "errors": []}
    if sample:
        for r in todo:
            save(DESC / f"{rid(r['full_name'])}.json", sample_desc(r))
            status["generated"] += 1
    elif status["key_present"]:
        import anthropic
        client = anthropic.Anthropic()
        fails = 0
        for r in todo:
            try:
                d = describe(client, cfg, r, readme(r["full_name"]))
            except anthropic.APIStatusError as e:
                msg = f"{r['full_name']}: {e.status_code} {e.message}"
                print("  生成失败 " + msg)
                status["errors"].append(msg[:500])
                fails += 1
                if e.status_code in (401, 403) or fails >= 5:
                    break  # 密钥无效、余额不足或连续失败,今天不再尝试
                continue
            except (anthropic.APIConnectionError, json.JSONDecodeError, StopIteration) as e:
                msg = f"{r['full_name']}: {type(e).__name__} {e}"
                print("  生成失败 " + msg)
                status["errors"].append(msg[:500])
                fails += 1
                if fails >= 5:
                    break
                continue
            fails = 0
            if d:
                save(DESC / f"{rid(r['full_name'])}.json", d)
                status["generated"] += 1
                print(f"  已生成 {r['full_name']}")
            else:
                status["skipped"].append(r["full_name"])
    else:
        print("未设置 ANTHROPIC_API_KEY,跳过中文介绍生成")
    save(DATA / "status.json", status)
    print(json.dumps(status, ensure_ascii=False))

    # 当天热榜存档:按近 1 天 star 增长排序(第一天没有历史,按 star 数)
    def gain(name, days):
        h = hist.get(name, {})
        past = (dt.date.today() - dt.timedelta(days=days)).isoformat()
        older = [d for d in h if d <= past]
        return h[TODAY] - h[max(older)] if older else 0
    ranked = sorted(repos, key=lambda n: (gain(n, 1), repos[n]["stars"]), reverse=True)
    save(DAILY / f"{TODAY}.json", [{"full_name": n, "stars": repos[n]["stars"], "gain": gain(n, 1)} for n in ranked[:30]])


if __name__ == "__main__":
    main()
