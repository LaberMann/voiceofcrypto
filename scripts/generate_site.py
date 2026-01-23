#!/usr/bin/env python3
# scripts/generate_site.py
#
# VoiceOfCrypto — Matrix Terminal Brief (EN then ZH)
# - EN: typewriter / terminal
# - ZH: Songti-style body, terminal-style headers & tags
# - ASCII logo + 🐶
# - Breaking rows: highlighted + subtle pulse (CSS)
# - Matrix-style math rain background (canvas)
# - Output: <out>/index.html + <out>/.nojekyll
#
# IMPORTANT:
# Avoid Python f-string for full HTML template because CSS/JS uses lots of { }.
# Use placeholder replacement instead to prevent "f-string: single '}'" syntax errors.

import argparse
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Tuple, Optional

import pytz
import yaml
import feedparser
from dateutil import parser as dtparser


# ----------------------------
# Helpers
# ----------------------------

def normalize_title(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[“”\"'’`]", "", s)
    s = re.sub(r"[\[\]\(\)\{\}]", "", s)
    return s


def classify(title: str) -> str:
    t = (title or "").lower()
    if any(k in t for k in ["hack", "exploit", "drain", "scam", "phishing", "ransom", "breach"]):
        return "Security"
    if any(k in t for k in ["sec", "regulat", "bill", "law", "court", "lawsuit", "ban", "fine", "probe"]):
        return "Regulation"
    if any(k in t for k in ["etf", "raises", "raise", "series", "funding", "acquire", "acquisition", "merger"]):
        return "Biz/Capital"
    if any(k in t for k in ["btc", "bitcoin", "eth", "ether", "price", "market", "liquidat", "dump", "pump"]):
        return "Markets"
    return "General"


def score_item(title: str, kind: str = "news") -> float:
    t = (title or "").lower()
    base = 4.6 if kind == "news" else 4.2
    keywords = [
        ("exploit", 2.6), ("hack", 2.6), ("drain", 2.4),
        ("sec", 2.1), ("lawsuit", 2.0), ("court", 1.8),
        ("etf", 2.0), ("liquidat", 2.0),
        ("stablecoin", 1.6), ("btc", 0.6), ("eth", 0.4),
    ]
    for k, w in keywords:
        if k in t:
            base += w
    return float(min(10.0, round(base, 1)))


def safe_parse_dt(entry) -> Optional[datetime]:
    for key in ("published", "updated", "pubDate"):
        if getattr(entry, key, None):
            try:
                return dtparser.parse(getattr(entry, key))
            except Exception:
                pass
    return None


@dataclass
class SourceCfg:
    id: str
    name: str
    url: str
    lang: str
    kind: str
    weight: float = 1.0


@dataclass
class Item:
    source: str
    source_id: str
    title: str
    link: str
    published_sgt: str
    cls: str
    score: float
    kind: str
    lang: str


def load_sources(path: str) -> List[SourceCfg]:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    out: List[SourceCfg] = []
    for s in cfg.get("sources", []):
        out.append(SourceCfg(
            id=s["id"],
            name=s["name"],
            url=s["url"],
            lang=s["lang"],
            kind=s["kind"],
            weight=float(s.get("weight", 1.0)),
        ))
    return out


def fetch_items(sources: List[SourceCfg], tz, win_start: datetime, win_end: datetime) -> List[Item]:
    items: List[Item] = []
    for src in sources:
        feed = feedparser.parse(src.url)
        for e in getattr(feed, "entries", [])[:80]:
            dt = safe_parse_dt(e)
            if not dt:
                continue
            if dt.tzinfo is None:
                dt = pytz.UTC.localize(dt)
            dt_sgt = dt.astimezone(tz)
            if not (win_start <= dt_sgt <= win_end):
                continue

            title = (getattr(e, "title", "") or "").strip()
            link = (getattr(e, "link", "") or "").strip()
            if not title or not link:
                continue

            items.append(Item(
                source=src.name,
                source_id=src.id,
                title=title,
                link=link,
                published_sgt=dt_sgt.isoformat(),
                cls=classify(title),
                score=round(min(10.0, score_item(title, src.kind) * src.weight), 1),
                kind=src.kind,
                lang=src.lang
            ))
    return items


def dedup(items: List[Item]) -> List[Item]:
    seen = set()
    out: List[Item] = []
    for it in sorted(items, key=lambda x: (-x.score, x.published_sgt)):
        key = normalize_title(it.title)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def pick_sections(items: List[Item]) -> Tuple[List[Item], List[Item], List[Item]]:
    items_sorted = sorted(items, key=lambda x: (-x.score, x.published_sgt))
    breaking = [x for x in items_sorted if x.score >= 8.8][:2]
    rest = [x for x in items_sorted if x not in breaking]
    headlines = rest[:5]
    quick = rest[5:17]
    return headlines, breaking, quick


def render_section(items: List[Item], prefix: str) -> str:
    if not items:
        return '<div class="row dim empty">-- empty --</div>'

    out = []
    for i, it in enumerate(items, 1):
        # minimal escaping for titles
        title = (it.title or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        link = (it.link or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        out.append(
            f'<div class="row"><div>'
            f'<span class="mono">[{prefix}{i}]</span>'
            f'<span class="pill">[{it.score}/10]</span>'
            f'<span class="pill dim">[{it.cls}]</span> '
            f'<a class="t" href="{link}" target="_blank" rel="noreferrer">{title}</a>'
            f'</div><div class="dim">↳ src: {it.source}</div></div>'
        )
    return "\n".join(out)


# ----------------------------
# HTML (no f-string template)
# ----------------------------

def html_page(now_sgt: str, win_start: str, win_end: str, en_html: str, zh_html: str) -> str:
    tpl = """<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>VoiceOfCrypto — Matrix Brief</title>

<style>
:root {
  --bg:#000;
  --fg:#00ff66;
  --dim:#00aa44;
  --line:rgba(0,255,102,.22);
  --lineStrong:rgba(0,255,102,.55);
  --hi:rgba(0,255,102,.10);

  --font-en:"American Typewriter","Courier New",Courier,ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;
  --font-zh:"Songti SC","SimSun","Noto Serif CJK SC","Source Han Serif SC",serif;
}

html,body{height:100%;}
body{
  margin:0;
  background:var(--bg);
  color:var(--fg);
  font-family:var(--font-en);
  letter-spacing:.2px;
}

#matrix-rain{
  position: fixed;
  inset: 0;
  z-index: -1;
  pointer-events: none;
}

.wrap{max-width:980px;margin:0 auto;padding:18px 14px 30px;}
.box{border:1px solid var(--line);padding:12px;margin:10px 0;}
.title{font-weight:800;}
.dim{color:var(--dim);}
a{color:var(--fg);text-decoration:underline;}
.row{padding:10px 0;border-top:1px dashed var(--line);}
.row:first-child{border-top:none;}
.pill{display:inline-block;padding:1px 8px;border:1px solid var(--line);margin:0 6px;}
.mono{font-weight:800;}
.t{font-weight:600;}

.logo-ascii{float:left;margin-right:12px;color:var(--dim);font-weight:800;line-height:1.25;}
.logo-ascii span{display:block;}

.breaking .row{
  border-top:1px solid var(--lineStrong);
  background:var(--hi);
  animation:pulse 1.2s ease-in-out infinite;
}
.breaking .row.empty{
  animation:none;
  background:transparent;
  border-top:1px dashed var(--line);
}
@keyframes pulse{
  0%{background:rgba(0,255,102,.06)}
  50%{background:rgba(0,255,102,.20)}
  100%{background:rgba(0,255,102,.06)}
}

.zh{font-family:var(--font-zh);}
.zh .title,.zh .mono,.zh .pill{font-family:var(--font-en);}
</style>
</head>

<body>
<canvas id="matrix-rain"></canvas>

<div class="wrap">
  <div class="box">
    <div class="logo-ascii">
      <span>[ V ]</span>
      <span>[ O ]</span>
      <span>[ C ]</span>
    </div>
    <div class="title">CRYPTO::GLOBAL_NEWS_ALARM | VOICEofCRYPTO | MATRIX BRIEF 🐶</div>
    <div class="dim">T+   : %%NOW%% (Asia/Singapore)</div>
    <div class="dim">WIN  : %%WIN_START%% → %%WIN_END%% (SGT)</div>
  </div>

  <div class="box">
    <div class="title">[EN BRIEF]</div>
    <div class="split"></div>
    %%EN_HTML%%
  </div>

  <div class="box zh">
    <div class="title">[中文简报]</div>
    <div class="split"></div>
    %%ZH_HTML%%
  </div>
</div>

<script>
(function () {
  const canvas = document.getElementById('matrix-rain');
  const ctx = canvas.getContext('2d');

  const chars = '0123456789+-×÷=∑∫√∞πλμσΔ';
  const fontSize = 12;
  const speed = 1;
  let cols = 0;
  let drops = [];

  function resize() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    cols = Math.floor(canvas.width / fontSize);
    drops = Array(cols).fill(0);
  }

  resize();
  window.addEventListener('resize', resize);

  function draw() {
    ctx.fillStyle = 'rgba(0,0,0,0.08)';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    ctx.fillStyle = 'rgba(0,255,102,0.08)';
    ctx.font = fontSize + 'px monospace';

    for (let i = 0; i < drops.length; i++) {
      const text = chars[Math.floor(Math.random() * chars.length)];
      ctx.fillText(text, i * fontSize, drops[i] * fontSize);

      if (drops[i] * fontSize > canvas.height && Math.random() > 0.975) {
        drops[i] = 0;
      }
      drops[i] += speed;
    }
  }

  setInterval(draw, 40);
})();
</script>
</body>
</html>
"""
    # placeholder replacement (safe)
    return (tpl
            .replace("%%NOW%%", now_sgt)
            .replace("%%WIN_START%%", win_start)
            .replace("%%WIN_END%%", win_end)
            .replace("%%EN_HTML%%", en_html)
            .replace("%%ZH_HTML%%", zh_html)
            )

import os

def log_trigger_info():
    # GitHub 会自动注入这些环境变量
    workflow_name = os.getenv('GITHUB_WORKFLOW', 'Local Run')
    actor = os.getenv('GITHUB_ACTOR', 'Unknown')
    event_name = os.getenv('GITHUB_EVENT_NAME', 'manual/local')
    
    print("-" * 30)
    print(f"🚀 工作流名称: {workflow_name}")
    print(f"👤 执行角色 (Actor): {actor}")
    print(f"📅 触发事件 (Event): {event_name}")
    
    if event_name == 'schedule':
        print("⏰ 状态确认: 这是一个定时自动触发的任务")
    elif event_name == 'workflow_dispatch':
        print("🖱️ 状态确认: 这是一个手动点击触发的任务")
    print("-" * 30)

# 在程序启动时调用
if __name__ == "__main__":
    log_trigger_info()
    # ... 你原来的 generate_site 逻辑 ...

# ----------------------------
# Main
# ----------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window-hours", type=int, default=4)
    ap.add_argument("--tz", type=str, default="Asia/Singapore")
    ap.add_argument("--out", type=str, default="site")
    ap.add_argument("--config", type=str, default="config/sources.yaml")
    args = ap.parse_args()

    tz = pytz.timezone(args.tz)
    now = datetime.now(tz)
    win_end = now
    win_start = now - timedelta(hours=args.window_hours)

    sources = load_sources(args.config)
    en_sources = [s for s in sources if s.lang == "en"]
    zh_sources = [s for s in sources if s.lang == "zh"]

    en_items = dedup(fetch_items(en_sources, tz, win_start, win_end)) if en_sources else []
    zh_items = dedup(fetch_items(zh_sources, tz, win_start, win_end)) if zh_sources else []

    en_head, en_break, en_quick = pick_sections(en_items)
    zh_head, zh_break, zh_quick = pick_sections(zh_items)

    en_html = (
        '<div class="title dim">> [HEADLINES]</div>' +
        render_section(en_head, "H") +
        '<div class="title dim">> [BREAKING]</div><div class="breaking">' +
        render_section(en_break, "B") +
        '</div><div class="title dim">> [QUICK_HITS]</div>' +
        render_section(en_quick, "Q")
    )

    zh_html = (
        '<div class="title dim">> [头条]</div>' +
        render_section(zh_head, "H") +
        '<div class="title dim">> [突发]</div><div class="breaking">' +
        render_section(zh_break, "B") +
        '</div><div class="title dim">> [快讯]</div>' +
        render_section(zh_quick, "Q")
    )

    page = html_page(
        now_sgt=now.strftime("%Y-%m-%d %H:%M:%S"),
        win_start=win_start.strftime("%H:%M"),
        win_end=win_end.strftime("%H:%M"),
        en_html=en_html,
        zh_html=zh_html,
    )

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, ".nojekyll"), "w", encoding="utf-8") as f:
        f.write("")
    with open(os.path.join(args.out, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)


if __name__ == "__main__":
    main()
