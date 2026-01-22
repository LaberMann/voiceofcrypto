#!/usr/bin/env python3
# scripts/generate_site.py
#
# VoiceOfCrypto — Matrix Terminal Brief (EN then ZH)
# - EN: typewriter / terminal
# - ZH: Songti-style body, terminal-style headers & tags
# - ASCII logo + 🐶
# - Breaking rows: highlighted + subtle pulse (CSS)
# - Output: <out>/index.html + <out>/.nojekyll

import argparse
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

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
    out = []
    for s in cfg.get("sources", []):
        out.append(SourceCfg(
            id=s["id"], name=s["name"], url=s["url"],
            lang=s["lang"], kind=s["kind"], weight=s.get("weight", 1.0)
        ))
    return out


def fetch_items(sources, tz, win_start, win_end):
    items = []
    for src in sources:
        feed = feedparser.parse(src.url)
        for e in feed.entries[:80]:
            dt = safe_parse_dt(e)
            if not dt:
                continue
            if dt.tzinfo is None:
                dt = pytz.UTC.localize(dt)
            dt_sgt = dt.astimezone(tz)
            if not (win_start <= dt_sgt <= win_end):
                continue
            if not getattr(e, "title", None) or not getattr(e, "link", None):
                continue
            items.append(Item(
                source=src.name,
                source_id=src.id,
                title=e.title.strip(),
                link=e.link.strip(),
                published_sgt=dt_sgt.isoformat(),
                cls=classify(e.title),
                score=round(score_item(e.title, src.kind) * src.weight, 1),
                kind=src.kind,
                lang=src.lang
            ))
    return items


def dedup(items):
    seen = set()
    out = []
    for it in sorted(items, key=lambda x: (-x.score, x.published_sgt)):
        key = normalize_title(it.title)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def pick_sections(items):
    breaking = [x for x in items if x.score >= 8.8][:2]
    rest = [x for x in items if x not in breaking]
    return rest[:5], breaking, rest[5:17]


def render_section(items, prefix):
    if not items:
        return '<div class="row dim empty">-- empty --</div>'
    out = []
    for i, it in enumerate(items, 1):
        out.append(
            f'<div class="row"><div>'
            f'<span class="mono">[{prefix}{i}]</span>'
            f'<span class="pill">[{it.score}/10]</span>'
            f'<span class="pill dim">[{it.cls}]</span> '
            f'<a class="t" href="{it.link}" target="_blank">{it.title}</a>'
            f'</div><div class="dim">↳ src: {it.source}</div></div>'
        )
    return "\n".join(out)


def html_page(now_sgt, win_start, win_end, en, zh):
    return f"""<!doctype html>
<html><head><meta charset="utf-8"/>
<style>
:root {{
--bg:#000;--fg:#00ff66;--dim:#00aa44;--line:rgba(0,255,102,.22);
--font-en:"American Typewriter","Courier New",Courier,ui-monospace,monospace;
--font-zh:"Songti SC","SimSun","Noto Serif CJK SC","Source Han Serif SC",serif;
}}
body{{margin:0;background:var(--bg);color:var(--fg);font-family:var(--font-en);}}
.zh{{font-family:var(--font-zh);}}
.zh .title,.zh .mono,.zh .pill{{font-family:var(--font-en);}}
.box{{border:1px solid var(--line);padding:12px;margin:10px;}}
.logo-ascii{{float:left;margin-right:12px;color:var(--dim);font-weight:800;}}
.logo-ascii span{{display:block;}}
.row{{padding:8px 0;border-top:1px dashed var(--line);}}
.breaking .row{{animation:pulse 1.2s infinite;}}
@keyframes pulse{{0%{{background:rgba(0,255,102,.06)}}50%{{background:rgba(0,255,102,.2)}}100%{{background:rgba(0,255,102,.06)}}}}
</style></head>
<body>
<div class="box">
<div class="logo-ascii"><span>[ V ]</span><span>[ O ]</span><span>[ C ]</span></div>
<div class="title">CRYPTO::GLOBAL_NEWS_ALARM | VOICEofCRYPTO | MATRIX BRIEF 🐶</div>
<div class="dim">T+ : {now_sgt} (SGT)</div>
<div class="dim">WIN : {win_start} → {win_end}</div>
</div>

<div class="box">
<div class="title">[EN BRIEF]</div>{en}
</div>

<div class="box zh">
<div class="title">[中文简报]</div>{zh}
</div>
</body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/sources.yaml")
    ap.add_argument("--out", default="site")
    args = ap.parse_args()

    tz = pytz.timezone("Asia/Singapore")
    now = datetime.now(tz)
    win_start = now - timedelta(hours=4)

    sources = load_sources(args.config)
    en = dedup(fetch_items([s for s in sources if s.lang=="en"], tz, win_start, now))
    zh = dedup(fetch_items([s for s in sources if s.lang=="zh"], tz, win_start, now))

    en_h,en_b,en_q = pick_sections(en)
    zh_h,zh_b,zh_q = pick_sections(zh)

    html = html_page(
        now.strftime("%Y-%m-%d %H:%M:%S"),
        win_start.strftime("%H:%M"),
        now.strftime("%H:%M"),
        render_section(en_h,"H")+render_section(en_b,"B")+render_section(en_q,"Q"),
        render_section(zh_h,"H")+render_section(zh_b,"B")+render_section(zh_q,"Q")
    )

    os.makedirs(args.out, exist_ok=True)
    open(os.path.join(args.out,".nojekyll"),"w").close()
    open(os.path.join(args.out,"index.html"),"w",encoding="utf-8").write(html)


if __name__ == "__main__":
    main()
