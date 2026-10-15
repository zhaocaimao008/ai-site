#!/usr/bin/env python3
"""根据 data/ 生成 AI 开源项目导航静态网站到 dist/。

每个页面带 Open Graph / Twitter Card,以及与页面类型对应的 JSON-LD。
项目页有一段「中文导读」:优先用 data/desc 里的 summary,旧数据没有该字段时,
只用仓库元数据和已有介绍拼出来,不补充材料里没有的事实。
"""
import datetime as dt
import html
import json
import re
import shutil
import urllib.parse
from pathlib import Path

from fetch import DAILY, DATA, DESC, load, rid

ROOT = Path(__file__).parent
OUT = ROOT / "dist"


def esc(s):
    return html.escape(str(s))


def paragraphs(text):
    return "".join(f"<p>{esc(p)}</p>" for p in str(text).split("\n") if p.strip())


def license_url(spdx):
    """把页面上展示的 SPDX 标识转成 schema.org 要的许可证 URL;无法确认时省略。"""
    if not spdx or spdx in ("NOASSERTION", "NONE"):
        return None
    return f"https://spdx.org/licenses/{urllib.parse.quote(spdx, safe='-+.')}.html"


def png_size(path):
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError(f"{path} 不是 PNG")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def jsonld_html(blocks):
    parts = []
    for block in blocks or []:
        raw = json.dumps(block, ensure_ascii=False, separators=(",", ":"))
        raw = raw.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
        parts.append(f'<script type="application/ld+json">{raw}</script>')
    return "".join(parts)

def network_html(cfg):
    """页脚"更多实用工具":同系列网站互相链接(列表见 config.json 的 network)。"""
    sites = [s for s in cfg.get("network", []) if s["url"].rstrip("/") != cfg["base_url"].rstrip("/")]
    if not sites:
        return ""
    return "<br>更多实用工具:" + " · ".join(f'<a href="{esc(s["url"])}">{esc(s["name"])}</a>' for s in sites)



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

    def abs_url(self, path):
        base = self.cfg["base_url"].rstrip("/")
        if not path.startswith("/"):
            path = "/" + path
        return base + "/" if path == "/" else base + path

    def gain_if_known(self, name, days):
        """有更早的 star 记录才返回差值;只有一天数据时返回 None,避免把「不知道」说成「没变化」。"""
        h = self.hist.get(name, {})
        if not h:
            return None
        last = max(h)
        past = (dt.date.fromisoformat(last) - dt.timedelta(days=days)).isoformat()
        older = [d for d in h if d <= past]
        if not older:
            return None
        return h[last] - h[max(older)]

    def breadcrumb(self, items):
        return {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": i, "name": name, "item": self.abs_url(path)}
                for i, (name, path) in enumerate(items, 1)
            ],
        }

    def item_list(self, name, names):
        elements = []
        for n in names:
            if n not in self.desc:
                continue  # 没有站内详情页的不进 ItemList
            url = self.abs_url(self.page_url(n))
            elements.append({"@type": "ListItem", "position": len(elements) + 1, "url": url})
        return {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "name": name,
            "itemListOrder": "https://schema.org/ItemListOrderDescending",
            "numberOfItems": len(elements),
            "itemListElement": elements,
        }

    def website_ld(self, desc):
        url = self.abs_url("/")
        return [
            {
                "@context": "https://schema.org",
                "@type": "WebSite",
                "name": self.cfg["site_name"],
                "url": url,
                "description": desc,
                "inLanguage": "zh-CN",
            },
            {
                "@context": "https://schema.org",
                "@type": "WebApplication",
                "name": self.cfg["site_name"],
                "url": url,
                "description": desc,
                "applicationCategory": "DeveloperApplication",
                "operatingSystem": "All",
                "offers": {"@type": "Offer", "price": "0", "priceCurrency": "CNY"},
                "inLanguage": "zh-CN",
            },
        ]

    def composed_summary(self, name):
        """旧介绍文件没有 summary 时,只用已有字段串成导读,不添加新的功能或评价。"""
        r, d = self.repos[name], self.desc[name]
        short = name.split("/")[1]
        cats = [self.cfg["categories"][c]["name"] for c in r.get("cats") or [] if c in self.cfg["categories"]]
        parts = [f"{short} 是开源项目,站内分类为 {'、'.join(cats)}。" if cats else f"{short} 是开源项目。"]
        tagline = (d.get("tagline") or "").strip().rstrip("。．. ")
        if tagline:
            parts.append(f"简介:{tagline}。")
        feats = [str(x).strip().rstrip("。．") for x in (d.get("features") or []) if str(x).strip()]
        if feats:
            parts.append("项目说明中列出的主要功能包括:" + "；".join(feats[:3]) + "。")
        audience = (d.get("audience") or "").strip()
        if audience:
            if audience[-1] not in "。！？!?":
                audience += "。"
            parts.append(audience)
        return "".join(parts)

    def fact_sentence(self, name):
        r = self.repos[name]
        bits = [f"的编程语言为 {r['language']}" if r.get("language") else "未标注编程语言"]
        lic = r.get("license") or ""
        bits.append(f"开源协议为 {lic}" if lic and lic not in ("NOASSERTION", "NONE") else "开源协议未注明")
        if r.get("created_at"):
            bits.append(f"创建于 {r['created_at']}")
        if r.get("pushed_at"):
            bits.append(f"最近更新于 {r['pushed_at']}")
        if isinstance(r.get("stars"), int):
            bits.append(f"目前有 {r['stars']:,} 个 Star")
        g7 = self.gain_if_known(name, 7)
        if g7 is not None:
            if g7 > 0:
                bits.append(f"近 7 天新增 {g7:,} 个 Star")
            elif g7 < 0:
                bits.append(f"近 7 天减少 {-g7:,} 个 Star")
            else:
                bits.append("近 7 天 Star 数没有变化")
        return "根据 GitHub 公开数据,该项目" + ",".join(bits) + "。"

    def project_summary(self, name):
        stored = (self.desc[name].get("summary") or "").strip().replace("\r\n", "\n").replace("\r", "\n")
        qualitative = stored if stored else self.composed_summary(name)
        parts = [p.strip() for p in qualitative.split("\n") if p.strip()]
        fact = self.fact_sentence(name)
        if fact:
            parts.append(fact)
        return "\n".join(parts)

    def software_ld(self, name, summary):
        r = self.repos[name]
        owner, short = name.split("/", 1)
        data = {
            "@context": "https://schema.org",
            "@type": "SoftwareSourceCode",
            "name": short,
            "description": summary,
            "url": self.abs_url(self.page_url(name)),
            "codeRepository": r["url"],
            "author": {"@type": "Organization", "name": owner, "url": f"https://github.com/{owner}"},
            "dateCreated": r["created_at"],
            "dateModified": r["pushed_at"],
        }
        if r.get("language"):
            data["programmingLanguage"] = r["language"]
        lic = license_url(r.get("license") or "")
        if lic:
            data["license"] = lic
        return data

    # ----- 布局 -----
    def ad(self):
        c = self.cfg.get("adsense_client")
        if not c:
            return ""
        return (f'<div class="ad"><ins class="adsbygoogle" style="display:block" data-ad-client="{esc(c)}" data-ad-format="auto" '
                'data-full-width-responsive="true"></ins><script>(adsbygoogle=window.adsbygoogle||[]).push({});</script></div>')

    def write(self, path, title, desc, body, jsonld=None):
        cfg = self.cfg
        ads = ""
        if cfg.get("adsense_client"):
            ads = (f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client='
                   f'{esc(cfg["adsense_client"])}" crossorigin="anonymous"></script>')
        nav = "".join(f'<a href="/c/{k}/">{esc(c["name"])}</a>' for k, c in cfg["categories"].items())
        prefix = urllib.parse.urlparse(cfg["base_url"]).path.rstrip("/")
        url = self.abs_url(path)
        image = self.abs_url("/og.png")
        site = cfg["site_name"]
        page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{esc(url)}">{ads}
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{esc(url)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{esc(site)}">
<meta property="og:locale" content="zh_CN">
<meta property="og:image" content="{esc(image)}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:type" content="image/png">
<meta property="og:image:alt" content="{esc(site)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(title)}">
<meta name="twitter:description" content="{esc(desc)}">
<meta name="twitter:image" content="{esc(image)}">
<meta name="twitter:image:alt" content="{esc(site)}">
{jsonld_html(jsonld)}<style>{CSS}</style></head><body>
<header><a class="logo" href="/">{esc(site)}</a><nav><a href="/">今日热榜</a>{nav}<a href="/daily/">历史榜单</a></nav></header>
<main>{body}</main>
<footer>数据来自 GitHub 公开信息,每天自动更新;项目介绍由 AI 根据项目 README 整理,可能存在疏漏,请以项目官方说明为准。{network_html(cfg)}</footer>
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
        summary = self.project_summary(name)
        crumbs = [("首页", "/")]
        if r["cats"]:
            cat = r["cats"][0]
            crumbs.append((self.cfg["categories"][cat]["name"], f"/c/{cat}/"))
        crumbs.append((short, self.page_url(name)))
        body = f"""<div class="card"><h1>{esc(short)} 是什么?{esc(d["tagline"])}</h1>
<div class="muted">{esc(name)} · <a href="{esc(r["url"])}" rel="nofollow">GitHub</a>{home}</div><div style="margin-top:6px">{cats}</div>
<div class="stats"><div>Star<b>{num(r["stars"])}</b></div><div>近 7 天新增<b>{self.gain(name, 7):,}</b></div>
<div>编程语言<b>{esc(r["language"] or "—")}</b></div><div>开源协议<b>{esc(r["license"] or "未注明")}</b></div>
<div>创建于<b>{r["created_at"]}</b></div><div>最近更新<b>{r["pushed_at"]}</b></div></div></div>
<div class="card"><h2>中文导读</h2>{paragraphs(summary)}</div>
{self.ad()}
<div class="card"><h2>项目介绍</h2>{intro}</div>
<div class="card"><h2>主要功能</h2><ul>{feats}</ul></div>
<div class="card"><h2>适合谁用</h2><p>{esc(d["audience"])}</p></div>
{qs_card}{self.chart(name)}{self.ad()}
<div class="card"><h2>同类项目</h2>{related}</div>"""
        self.write(self.page_url(name), f"{short} 是什么 - {d['tagline']} | GitHub {num(r['stars'])} Star",
                   f"{short}:{d['tagline']}。{d['intro'][:80]}", body,
                   [self.software_ld(name, summary), self.breadcrumb(crumbs)])

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
                   f"每天更新的 GitHub {c['name']}开源项目排行榜,共 {len(names)} 个项目,附中文介绍、star 增长和上手方法。", body,
                   [self.item_list(f"{c['name']}按 Star 排序", top),
                    self.breadcrumb([("首页", "/"), (c["name"], f"/c/{key}/")])])

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
        desc = "每天自动更新的 AI 开源项目中文导航:GitHub 热门大模型、AI 智能体、MCP、RAG、AI 绘画、AI 编程项目排行与中文介绍。"
        self.write("/", f"{self.cfg['site_name']} - 每日 AI 开源项目热榜与中文导航", desc, body,
                   self.website_ld(desc) + [self.item_list("今日热榜", hot)])

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
                       f'<div class="card"><h1>AI 开源项目日榜 · {day}</h1></div><div class="card">{items}</div>',
                       [self.item_list(f"AI 开源项目日榜 {day}", [x["full_name"] for x in rows]),
                        self.breadcrumb([("首页", "/"), ("历史榜单", "/daily/"), (day, f"/daily/{day}/")])])
        links = "".join(f'<a class="tag" href="/daily/{f.stem}/">{f.stem}</a>' for f in files)
        self.write("/daily/", "AI 开源项目历史日榜", "每日 GitHub AI 开源项目热榜存档。",
                   f'<div class="card"><h1>历史日榜</h1>{links}</div>',
                   [self.breadcrumb([("首页", "/"), ("历史榜单", "/daily/")])])

    def build(self):
        og = ROOT / "assets" / "og.png"
        try:
            size = png_size(og)
        except (OSError, ValueError) as e:
            raise SystemExit(f"缺少分享图: {e}")
        if size != (1200, 630):
            raise SystemExit(f"og.png 尺寸应为 1200x630,实际 {size[0]}x{size[1]}")
        if OUT.exists():
            shutil.rmtree(OUT)
        OUT.mkdir()
        shutil.copy(og, OUT / "og.png")
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
        self.validate()
        print(f"生成 {len(self.urls)} 个页面(项目详情页 {len(self.desc)} 个)")

    def validate(self):
        """按 Google 富媒体结果要求的必填字段检查 JSON-LD,并核对 OG / Twitter 标签。"""
        errors = []
        expected = {"/", "/daily/"}
        expected.update(f"/c/{k}/" for k in self.cfg["categories"])
        expected.update(self.page_url(n) for n in self.desc)
        expected.update(f"/daily/{p.stem}/" for p in DAILY.glob("*.json"))
        if set(self.urls) != expected:
            errors.append(f"页面 URL 与数据不一致,多出 {sorted(set(self.urls) - expected)[:5]},缺少 {sorted(expected - set(self.urls))[:5]}")
        base = self.cfg["base_url"].rstrip("/")
        robots = (OUT / "robots.txt").read_text(encoding="utf-8")
        if "Allow: /" not in robots or f"Sitemap: {base}/sitemap.xml" not in robots:
            errors.append("robots.txt 缺少 Allow 或 Sitemap")
        sitemap = (OUT / "sitemap.xml").read_text(encoding="utf-8")
        locs = set(re.findall(r"<loc>(.*?)</loc>", sitemap))
        if locs != {self.abs_url(u) for u in self.urls}:
            errors.append("sitemap 与页面 URL 不一致")
        if "<lastmod>" not in sitemap or sitemap.count("<lastmod>") != len(self.urls):
            errors.append("sitemap 缺少 lastmod")
        if self.abs_url("/og.png") in locs:
            errors.append("sitemap 不应收录 og.png")
        pages = 0
        blocks = 0
        for path in self.urls:
            file = OUT / "index.html" if path == "/" else OUT / path.strip("/") / "index.html"
            text = file.read_text(encoding="utf-8")
            pages += 1
            self._check_page(path, text, errors)
            blocks += text.count('type="application/ld+json"')
        if errors:
            print("\n".join(f"SEO 校验失败: {e}" for e in errors[:40]))
            raise SystemExit(1)
        print(f"SEO 校验通过: {pages} 个页面, {blocks} 段 JSON-LD")

    def _check_page(self, path, text, errors):
        def attr(pattern):
            m = re.search(pattern, text)
            return html.unescape(m.group(1)) if m else None

        title = attr(r"<title>(.*?)</title>")
        desc = attr(r'<meta name="description" content="(.*?)">')
        canonical = attr(r'<link rel="canonical" href="(.*?)">')
        if not title or not desc or canonical != self.abs_url(path):
            errors.append(f"{path} title/description/canonical 异常")
            return
        expect = {
            "og:title": title, "og:description": desc, "og:url": canonical, "og:type": "website",
            "og:site_name": self.cfg["site_name"], "og:locale": "zh_CN",
            "og:image": self.abs_url("/og.png"), "og:image:width": "1200", "og:image:height": "630",
            "og:image:alt": self.cfg["site_name"],
        }
        for prop, value in expect.items():
            got = attr(rf'<meta property="{prop}" content="(.*?)">')
            if got != value:
                errors.append(f"{path} {prop}={got!r},期望 {value!r}")
        tw = {
            "twitter:card": "summary_large_image", "twitter:title": title, "twitter:description": desc,
            "twitter:image": self.abs_url("/og.png"), "twitter:image:alt": self.cfg["site_name"],
        }
        for name, value in tw.items():
            got = attr(rf'<meta name="{name}" content="(.*?)">')
            if got != value:
                errors.append(f"{path} {name}={got!r},期望 {value!r}")
        nodes = []
        for raw in re.findall(r'<script type="application/ld\+json">(.*?)</script>', text):
            try:
                nodes.append(json.loads(raw))
            except json.JSONDecodeError as e:
                errors.append(f"{path} JSON-LD 无法解析: {e}")
        types = [n.get("@type") for n in nodes if isinstance(n, dict)]
        for n in nodes:
            if not isinstance(n, dict) or n.get("@context") != "https://schema.org" or not n.get("@type"):
                errors.append(f"{path} JSON-LD 缺少 @context 或 @type")
        if path == "/":
            self._check_home(path, nodes, desc, errors)
        else:
            crumbs = [n for n in nodes if n.get("@type") == "BreadcrumbList"]
            if len(crumbs) != 1:
                errors.append(f"{path} 应有且仅有一段 BreadcrumbList")
            else:
                self._check_breadcrumb(path, crumbs[0], canonical, errors)
        if path == "/" or path.startswith("/c/") or re.fullmatch(r"/daily/\d{4}-\d{2}-\d{2}/", path):
            lists = [n for n in nodes if n.get("@type") == "ItemList"]
            if len(lists) != 1:
                errors.append(f"{path} 应有且仅有一段 ItemList")
            elif lists:
                self._check_item_list(path, lists[0], text, errors)
        if path.startswith("/p/"):
            soft = [n for n in nodes if n.get("@type") == "SoftwareSourceCode"]
            if len(soft) != 1:
                errors.append(f"{path} 应有且仅有一段 SoftwareSourceCode")
            else:
                self._check_software(path, soft[0], canonical, text, errors)
        if path != "/" and "WebSite" in types:
            errors.append(f"{path} 不应重复放 WebSite")

    def _check_home(self, path, nodes, desc, errors):
        sites = [n for n in nodes if n.get("@type") == "WebSite"]
        apps = [n for n in nodes if n.get("@type") == "WebApplication"]
        if len(sites) != 1 or len(apps) != 1:
            errors.append(f"{path} 应有 WebSite 与 WebApplication 各一段")
            return
        url = self.abs_url("/")
        for n in (sites[0], apps[0]):
            if n.get("name") != self.cfg["site_name"] or n.get("url") != url or n.get("description") != desc:
                errors.append(f"{path} {n.get('@type')} 的 name/url/description 与页面不一致")
        app = apps[0]
        offers = app.get("offers") or {}
        if (app.get("applicationCategory") != "DeveloperApplication" or app.get("operatingSystem") != "All"
                or offers.get("@type") != "Offer" or str(offers.get("price")) != "0" or offers.get("priceCurrency") != "CNY"):
            errors.append(f"{path} WebApplication 缺少免费应用必填字段")

    def _check_breadcrumb(self, path, node, canonical, errors):
        items = node.get("itemListElement")
        if not isinstance(items, list) or len(items) < 2:
            errors.append(f"{path} BreadcrumbList 至少两项")
            return
        for i, item in enumerate(items, 1):
            if not isinstance(item, dict) or item.get("@type") != "ListItem" or item.get("position") != i:
                errors.append(f"{path} 面包屑 position 不连续")
                return
            if not item.get("name") or not str(item.get("item", "")).startswith("https://"):
                errors.append(f"{path} 面包屑 name/item 无效")
                return
        if items[-1]["item"] != canonical:
            errors.append(f"{path} 面包屑末项不是当前页面")
        if items[0]["name"] != "首页" or items[0]["item"] != self.abs_url("/"):
            errors.append(f"{path} 面包屑首项不是首页")

    def _check_item_list(self, path, node, text, errors):
        items = node.get("itemListElement")
        if not isinstance(items, list) or node.get("numberOfItems") != len(items):
            errors.append(f"{path} ItemList.numberOfItems 与列表长度不一致")
            return
        if node.get("itemListOrder") != "https://schema.org/ItemListOrderDescending":
            errors.append(f"{path} ItemList 缺少排序")
        if not node.get("name"):
            errors.append(f"{path} ItemList 缺少 name")
        for i, item in enumerate(items, 1):
            if not isinstance(item, dict) or item.get("position") != i or item.get("@type") != "ListItem":
                errors.append(f"{path} ItemList position 不连续")
                return
            url = item.get("url")
            if not str(url).startswith("https://ai427.com/p/"):
                errors.append(f"{path} ItemList 第 {i} 项 url 不是站内详情页")
                return
            if set(item.keys()) - {"@type", "position", "url"}:
                errors.append(f"{path} ItemList 第 {i} 项有多余字段")
                return

    def _check_software(self, path, node, canonical, text, errors):
        if node.get("url") != canonical or not str(node.get("codeRepository", "")).startswith("https://github.com/"):
            errors.append(f"{path} SoftwareSourceCode url 或 codeRepository 无效")
        if not node.get("name") or node["name"] not in text:
            errors.append(f"{path} SoftwareSourceCode.name 未出现在页面上")
        author = node.get("author") or {}
        if author.get("@type") != "Organization" or not author.get("name") or not str(author.get("url", "")).startswith("https://github.com/"):
            errors.append(f"{path} SoftwareSourceCode.author 无效")
        m = re.search(r"<h2>中文导读</h2>(.*?)</div>", text)
        if not m:
            errors.append(f"{path} 缺少中文导读")
            return
        visible = "\n".join(html.unescape(p) for p in re.findall(r"<p>(.*?)</p>", m.group(1)))
        if not visible or node.get("description") != visible:
            errors.append(f"{path} JSON-LD 描述与页面上的中文导读不一致")
        for key in ("dateCreated", "dateModified"):
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(node.get(key, ""))):
                errors.append(f"{path} {key} 不是日期")
        lic = node.get("license")
        if lic is not None and not str(lic).startswith("https://spdx.org/licenses/"):
            errors.append(f"{path} license 不是 SPDX URL")


if __name__ == "__main__":
    Site().build()
