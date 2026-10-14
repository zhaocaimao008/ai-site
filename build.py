#!/usr/bin/env python3
"""根据 data/ 生成 AI 开源项目导航静态网站到 dist/。"""
import datetime as dt
import html
import json
import shutil
import urllib.parse
from pathlib import Path

from fetch import DAILY, DATA, DESC, load, rid

ROOT = Path(__file__).parent
OUT = ROOT / "dist"


def esc(s):
    return html.escape(str(s))


def num(n):
    return f"{n / 10000:.1f}万" if n >= 10000 else f"{n:,}"


CSS = """
:root{--bg:#f7f8fa;--card:#fff;--text:#1d2129;--muted:#6b7280;--line:#e5e7eb;--accent:#1f6feb;--up:#d93025;--tag:#eef2ff}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--card:#171a21;--text:#e6e8eb;--muted:#9aa1ac;--line:#2a2f3a;--accent:#58a6ff;--up:#ff7b72;--tag:#1f2633}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
header,main,footer{max-width:900px;margin:0 auto;padding:0 16px}
header{padding-top:16px}header .logo{font-weight:700;font-size:18px;color:var(--text)}
nav{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:15px;margin-top:6px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px;margin:16px 0}
h1{font-size:24px;line-height:1.4;margin:8px 0;overflow-wrap:anywhere}h2{font-size:19px;margin:0 0 12px}
.muted{color:var(--muted);font-size:14px}.up{color:var(--up)}
.item{padding:12px 0;border-bottom:1px solid var(--line)}.item:last-child{border-bottom:0}
.item .t{font-weight:600;overflow-wrap:anywhere}.item .m{color:var(--muted);font-size:13px}
.tag{display:inline-block;background:var(--tag);border-radius:6px;padding:0 8px;font-size:13px;margin:2px 4px 2px 0}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin-top:12px}.stats div{background:var(--bg);border-radius:8px;padding:8px 12px;font-size:13px;color:var(--muted)}.stats b{display:block;font-size:18px;color:var(--text)}
ol,ul{padding-left:22px}code{background:var(--bg);padding:1px 6px;border-radius:4px;font-size:14px;overflow-wrap:anywhere}
svg{width:100%;height:auto}.ad{margin:16px 0;min-height:90px}
footer{padding:24px 16px;color:var(--muted);font-size:13px}
"""


class Site:
    def __init__(self):
        self.cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        self.repos = load(DATA / "repos.json", {})
        self.hist = load(DATA / "history.json", {})
        self.desc = {}
        for name in self.repos:
            d = load(DESC / f"{rid(name)}.json", None)
            if d and d.get("ai_related"):
                self.desc[name] = d
        self.today = max((max(h) for h in self.hist.values() if h), default=dt.date.today().isoformat())
        self.urls = []

    # ----- 数据 -----
    def gain(self, name, days):
        h = self.hist.get(name, {})
        if not h:
            return 0
        last = max(h)
        past = (dt.date.fromisoformat(last) - dt.timedelta(days=days)).isoformat()
        older = [d for d in h if d <= past]
        return h[last] - h[max(older)] if older else 0

    def page_url(self, name):
        return f"/p/{rid(name)}/"

    # ----- 布局 -----
    def ad(self):
        c = self.cfg.get("adsense_client")
        if not c:
            return ""
        return (f'<div class="ad"><ins class="adsbygoogle" style="display:block" data-ad-client="{esc(c)}" data-ad-format="auto" '
                'data-full-width-responsive="true"></ins><script>(adsbygoogle=window.adsbygoogle||[]).push({});</script></div>')

    def write(self, path, title, desc, body):
        cfg = self.cfg
        ads = ""
        if cfg.get("adsense_client"):
            ads = (f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client='
                   f'{esc(cfg["adsense_client"])}" crossorigin="anonymous"></script>')
        nav = "".join(f'<a href="/c/{k}/">{esc(c["name"])}</a>' for k, c in cfg["categories"].items())
        prefix = urllib.parse.urlparse(cfg["base_url"]).path.rstrip("/")
        page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{esc(cfg["base_url"].rstrip("/") + path)}">{ads}<style>{CSS}</style></head><body>
<header><a class="logo" href="/">{esc(cfg["site_name"])}</a><nav><a href="/">今日热榜</a>{nav}<a href="/daily/">历史榜单</a></nav></header>
<main>{body}</main>
<footer>数据来自 GitHub 公开信息,每天自动更新;项目介绍由 AI 根据项目 README 整理,可能存在疏漏,请以项目官方说明为准。</footer>
</body></html>""".replace('href="/', f'href="{prefix}/')
        f = OUT / path.strip("/") / "index.html"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(page, encoding="utf-8")
        self.urls.append(path)

    # ----- 组件 -----
    def item(self, name, show_gain=True):
        r, d = self.repos[name], self.desc.get(name)
        title = f'<a href="{self.page_url(name)}">{esc(name)}</a>' if d else f'<a href="{esc(r["url"])}" rel="nofollow">{esc(name)}</a>'
        text = d["tagline"] if d else r["description"]
        g = self.gain(name, 1)
        gtxt = f' · <span class="up">今日 +{g:,}</span>' if show_gain and g > 0 else ""
        return (f'<div class="item"><div class="t">{title}</div><div>{esc(text)}</div>'
                f'<div class="m">★ {num(r["stars"])}{gtxt} · {esc(r["language"] or "—")} · 更新于 {r["pushed_at"]}</div></div>')

    def chart(self, name):
        h = self.hist.get(name, {})
        if len(h) < 3:
            return ""
        days = sorted(h)
        vals = [h[d] for d in days]
        w, ht, pad = 600, 160, 24
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or 1
        pts = " ".join(f"{pad + i * (w - 2 * pad) / (len(vals) - 1):.1f},{ht - pad - (v - lo) / span * (ht - 2 * pad):.1f}"
                       for i, v in enumerate(vals))
        return (f'<div class="card"><h2>Star 增长趋势</h2><svg viewBox="0 0 {w} {ht}" role="img" aria-label="star 趋势">'
                f'<polyline fill="none" stroke="currentColor" stroke-width="2" points="{pts}" style="color:var(--accent)"/>'
                f'<text x="{pad}" y="14" font-size="12" fill="currentColor" opacity=".6">{hi:,}</text>'
                f'<text x="{pad}" y="{ht - 4}" font-size="12" fill="currentColor" opacity=".6">{lo:,} · {days[0]} 至 {days[-1]}</text></svg></div>')

    # ----- 页面 -----
    def project(self, name):
        r, d = self.repos[name], self.desc[name]
        cats = "".join(f'<a class="tag" href="/c/{c}/">{esc(self.cfg["categories"][c]["name"])}</a>' for c in r["cats"])
        intro = "".join(f"<p>{esc(p)}</p>" for p in d["intro"].split("\n") if p.strip())
        feats = "".join(f"<li>{esc(x)}</li>" for x in d["features"])
        qs = "".join(f"<li>{esc(x)}</li>" for x in d["quickstart"])
        qs_card = f'<div class="card"><h2>快速上手</h2><ol>{qs}</ol></div>' if qs else ""
        home = f' · <a href="{esc(r["homepage"])}" rel="nofollow">官网</a>' if r["homepage"].startswith("http") else ""
        same = [n for n in self.desc if n != name and set(self.repos[n]["cats"]) & set(r["cats"])]
        same.sort(key=lambda n: -self.repos[n]["stars"])
        related = "".join(self.item(n, False) for n in same[:6])
        short = name.split("/")[1]
        body = f"""<div class="card"><h1>{esc(short)} 是什么?{esc(d["tagline"])}</h1>
<div class="muted">{esc(name)} · <a href="{esc(r["url"])}" rel="nofollow">GitHub</a>{home}</div><div style="margin-top:6px">{cats}</div>
<div class="stats"><div>Star<b>{num(r["stars"])}</b></div><div>近 7 天新增<b>{self.gain(name, 7):,}</b></div>
<div>编程语言<b>{esc(r["language"] or "—")}</b></div><div>开源协议<b>{esc(r["license"] or "未注明")}</b></div>
<div>创建于<b>{r["created_at"]}</b></div><div>最近更新<b>{r["pushed_at"]}</b></div></div></div>
{self.ad()}
<div class="card"><h2>项目介绍</h2>{intro}</div>
<div class="card"><h2>主要功能</h2><ul>{feats}</ul></div>
<div class="card"><h2>适合谁用</h2><p>{esc(d["audience"])}</p></div>
{qs_card}{self.chart(name)}{self.ad()}
<div class="card"><h2>同类项目</h2>{related}</div>"""
        self.write(self.page_url(name), f"{short} 是什么 - {d['tagline']} | GitHub {num(r['stars'])} Star",
                   f"{short}:{d['tagline']}。{d['intro'][:80]}", body)

    def category(self, key):
        c = self.cfg["categories"][key]
        names = [n for n, r in self.repos.items() if key in r["cats"]]
        hot = sorted(names, key=lambda n: (-self.gain(n, 7), -self.repos[n]["stars"]))[:20]
        top = sorted(names, key=lambda n: -self.repos[n]["stars"])
        body = f"""<div class="card"><h1>{esc(c["name"])}开源项目推荐({len(names)} 个)</h1>
<p class="muted">GitHub 上 {esc(c["name"])}相关的热门开源项目,按 star 和近期增长自动排序,每天更新。</p></div>{self.ad()}
<div class="card"><h2>近 7 天增长最快</h2>{"".join(self.item(n) for n in hot)}</div>
<div class="card"><h2>按 Star 排序</h2>{"".join(self.item(n) for n in top)}</div>"""
        self.write(f"/c/{key}/", f"{c['name']}开源项目推荐 - GitHub 热门{c['name']}项目排行({self.today[:4]})",
                   f"每天更新的 GitHub {c['name']}开源项目排行榜,共 {len(names)} 个项目,附中文介绍、star 增长和上手方法。", body)

    def home(self):
        latest = load(DAILY / f"{self.today}.json", [])
        hot = [x["full_name"] for x in latest if x["full_name"] in self.repos][:20]
        cutoff = (dt.date.fromisoformat(self.today) - dt.timedelta(days=self.cfg["new_repo_days"])).isoformat()
        new = sorted([n for n, r in self.repos.items() if r["created_at"] >= cutoff], key=lambda n: -self.repos[n]["stars"])[:10]
        cats = "".join(f'<a class="tag" href="/c/{k}/">{esc(c["name"])}</a>' for k, c in self.cfg["categories"].items())
        body = f"""<div class="card"><h1>今日 AI 开源热榜({self.today})</h1>
<p class="muted">每天自动追踪 GitHub 上 {len(self.repos)} 个 AI 开源项目的 star 变化,发现最新最火的大模型、智能体、AI 绘画、AI 编程工具。</p>
<div>{cats}</div></div>{self.ad()}
<div class="card"><h2>今日热榜</h2>{"".join(self.item(n) for n in hot)}</div>
<div class="card"><h2>近期新项目</h2>{"".join(self.item(n) for n in new)}</div>"""
        self.write("/", f"{self.cfg['site_name']} - 每日 AI 开源项目热榜与中文导航",
                   "每天自动更新的 AI 开源项目中文导航:GitHub 热门大模型、AI 智能体、MCP、RAG、AI 绘画、AI 编程项目排行与中文介绍。", body)

    def daily(self):
        files = sorted(DAILY.glob("*.json"), reverse=True)
        for f in files:
            day = f.stem
            rows = [x for x in load(f, []) if x["full_name"] in self.repos]
            items = "".join(
                f'<div class="item"><div class="t">{i}. '
                + (f'<a href="{self.page_url(x["full_name"])}">{esc(x["full_name"])}</a>' if x["full_name"] in self.desc
                   else esc(x["full_name"]))
                + f'</div><div class="m">★ {num(x["stars"])}' + (f' · <span class="up">当日 +{x["gain"]:,}</span>' if x["gain"] > 0 else "")
                + "</div></div>" for i, x in enumerate(rows, 1))
            self.write(f"/daily/{day}/", f"AI 开源项目日榜 {day}", f"{day} GitHub AI 开源项目 star 增长排行榜。",
                       f'<div class="card"><h1>AI 开源项目日榜 · {day}</h1></div><div class="card">{items}</div>')
        links = "".join(f'<a class="tag" href="/daily/{f.stem}/">{f.stem}</a>' for f in files)
        self.write("/daily/", "AI 开源项目历史日榜", "每日 GitHub AI 开源项目热榜存档。",
                   f'<div class="card"><h1>历史日榜</h1>{links}</div>')

    def build(self):
        if OUT.exists():
            shutil.rmtree(OUT)
        OUT.mkdir()
        self.home()
        for k in self.cfg["categories"]:
            self.category(k)
        for name in self.desc:
            self.project(name)
        self.daily()
        base = self.cfg["base_url"].rstrip("/")
        sm = "".join(f"<url><loc>{esc(base + u)}</loc><lastmod>{self.today}</lastmod></url>" for u in self.urls)
        (OUT / "sitemap.xml").write_text(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{sm}</urlset>', encoding="utf-8")
        (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {base}/sitemap.xml\n", encoding="utf-8")
        if self.cfg.get("adsense_client"):
            (OUT / "ads.txt").write_text(f"google.com, {self.cfg['adsense_client'].replace('ca-', '')}, DIRECT, f08c47fec0942fa0\n", encoding="utf-8")
        print(f"生成 {len(self.urls)} 个页面(项目详情页 {len(self.desc)} 个)")


if __name__ == "__main__":
    Site().build()
