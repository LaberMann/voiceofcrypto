#!/usr/bin/env python3
# scripts/generate_site.py
#
# VoiceOfCrypto — Matrix Terminal Brief (EN then ZH)
# - No OpenAI needed: EN brief uses EN sources; ZH brief uses ZH sources (no translation)
# - No per-item timestamps; only top banner has Send time + 4h window (Asia/Singapore)
# - Each item title is a clickable hyperlink (no separate [LINKS] block)
# - Breaking rows: highlighted + subtle pulse (CSS)
# - Head box: add ASCII logo (dim) on the left + 🐶 marker; VOICEOFCRYPTO -> VOICEofCRYPTO
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
    """0–10 impact-ish score. quick/newsflash slightly downweighted by default."""
    t = (title or "").lower()
    base = 4.6 if kind == "news" else 4.2

    keywords = [
        ("exploit", 2.6), ("hack", 2.6), ("drain", 2.4),
        ("sec", 2.1), ("lawsuit", 2.0), ("court", 1.8), ("bill", 1.8), ("ban", 1.9),
        ("etf", 2.0), ("liquidat", 2.0), ("insolv", 2.3), ("bankrupt", 2.5),
        ("halt", 2.2), ("outage", 2.0), ("delist", 1.7),
        ("stablecoin", 1.6), ("treasury", 1.6), ("fed", 1.5), ("rate", 1.3),
        ("btc", 0.6), ("bitcoin", 0.6), ("eth", 0.4),
    ]
    for k, w in keywords:
        if k in t:
            base += w

    # a little bump for "breaking" words, but keep bounded
    if any(k in t for k in ["breaking", "urgent", "suspends", "emergency", "freeze"]):
        base += 0.8

    return float(min(10.0, round(base, 1)))


def safe_parse_dt(entry) -> Optional[datetime]:
    """Try best-effort time extraction from RSS entry."""
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
    lang: str   # "en" or "zh"
    kind: str   # "news" or "newsflash"
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

    # Support both:
    # 1) cfg["sources"] = [ {id,name,url,lang,kind,weight}, ... ]
    # 2) legacy cfg["rss"] = [ {name,url}, ... ] (assume en/news)
    out: List[SourceCfg] = []
    if isinstance(cfg.get("sources"), list):
        for s in cfg["sources"]:
            if not isinstance(s, dict):
                continue
            out.append(SourceCfg(
                id=str(s.get("id") or s.get("name") or s.get("url")),
                name=str(s.get("name") or s.get("id") or "Unknown"),
                url=str(s.get("url") or "").strip(),
                lang=str(s.get("lang") or "en").lower(),
                kind=str(s.get("kind") or "news").lower(),
                weight=float(s.get("weight") or 1.0),
            ))
    elif isinstance(cfg.get("rss"), list):
        for i, s in enumerate(cfg["rss"]):
            if not isinstance(s, dict):
                continue
            out.append(SourceCfg(
                id=f"rss_{i}",
                name=str(s.get("name") or "RSS"),
                url=str(s.get("url") or "").strip(),
                lang="en",
                kind="news",
                weight=1.0
            ))
    else:
        raise RuntimeError("No sources found in config/sources.yaml. Expected key: sources: [...]")

    out = [s for s in out if s.url]
    if not out:
        raise RuntimeError("No valid sources with URL found in config/sources.yaml.")
    return out


def fetch_items(sources: List[SourceCfg], tz, win_start: datetime, win_end: datetime) -> List[Item]:
    # Make RSS fetch more reliable for some sites
    feedparser.USER_AGENT = "Mozilla/5.0 (compatible; VoiceOfCryptoBot/1.0; +https://github.com/LaberMann/voiceofcrypto)"

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

            link = (getattr(e, "link", "") or "").strip()
            title = (getattr(e, "title", "") or "").strip()
            if not title or not link:
                continue

            raw_score = score_item(title, kind=src.kind)
            score = round(min(10.0, raw_score * src.weight), 1)

            items.append(Item(
                source=src.name,
                source_id=src.id,
                title=title,
                link=link,
                published_sgt=dt_sgt.isoformat(),
                cls=classify(title),
                score=score,
                kind=src.kind,
                lang=src.lang
            ))
    return items


def dedup(items: List[Item]) -> List[Item]:
    seen_title = set()
    seen_link = set()
    out: List[Item] = []

    def key(it: Item):
        return (-it.score, it.published_sgt)

    for it in sorted(items, key=key):
        nt = normalize_title(it.title)
        if nt in seen_title or it.link in seen_link:
            continue
        seen_title.add(nt)
        seen_link.add(it.link)
        out.append(it)
    return out


def pick_sections(items: List[Item]) -> Tuple[List[Item], List[Item], List[Item]]:
    items_sorted = sorted(items, key=lambda x: (-x.score, x.published_sgt))
    breaking = [x for x in items_sorted if x.score >= 8.8][:2]
    remaining = [x for x in items_sorted if x not in breaking]
    headlines = remaining[:5]
    quick = remaining[5:17]
    return headlines, breaking, quick


# ----------------------------
# HTML Rendering (Matrix UI)
# ----------------------------

def render_section(items: List[Item], prefix: str) -> str:
    if not items:
        return '<div class="row dim empty">-- empty --</div>'

    rows = []
    for i, it in enumerate(items, start=1):
        title = (
            it.title
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        url = (
            it.link
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

        rows.append(
            f'<div class="row">'
            f'<div>'
            f'<span class="mono">[{prefix}{i}]</span>'
            f'<span class="pill">[{it.score}/10]</span>'
            f'<span class="pill dim">[{it.cls}]</span> '
            f'<a class="t" href="{url}" target="_blank" rel="noreferrer">{title}</a>'
            f'</div>'
            f'<div class="dim">↳ src: {it.source}</div>'
            f'</div>'
        )
    return "\n".join(rows)


def html_page(
    now_sgt: str,
    win_start: str,
    win_end: str,
    en_blocks: Dict[str, str],
    zh_blocks: Dict[str, str],
) -> str:
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>VoiceOfCrypto — Matrix Brief</title>
<style>
  :root {{
    --bg:#000000;
    --fg:#00ff66;
    --dim:#00aa44;
    --line:rgba(0,255,102,.22);
    --lineStrong:rgba(0,255,102,.55);
    --hi:rgba(0,255,102,.10);
    --hi2:rgba(0,255,102,.18);
  }}
  html,body{{height:100%;}}
  body{{
    margin:0;
    background:var(--bg);
    color:var(--fg);
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
    letter-spacing: .2px;
  }}
  .wrap{{max-width:980px;margin:0 auto;padding:18px 14px 30px;}}
  .box{{border:1px solid var(--line); padding:12px; margin:10px 0;}}
  .title{{font-weight:800;}}
  .dim{{color:var(--dim);}}
  a{{color:var(--fg); text-decoration:underline;}}
  .sec{{margin-top:14px;}}
  .row{{padding:10px 0; border-top:1px dashed var(--line);}}
  .row:first-child{{border-top:none;}}
  .pill{{display:inline-block; padding:1px 8px; border:1px solid var(--line); margin:0 6px 0 6px;}}
  .mono{{font-weight:800;}}
  .t{{font-weight:600;}}
  .split{{height:1px;background:var(--line);margin:12px 0;}}

  /* ASCII logo (left, Fallout/Pip-Boy style) */
  .logo-ascii{{
    float:left;
    margin-right:12px;
    color:var(--dim);
    font-weight:800;
    line-height:1.25;
    letter-spacing:.6px;
  }}
  .logo-ascii .cell{{display:block;}}

  /* ===== Breaking Highlight + Pulse ===== */
  .breaking .row{{
    border-top: 1px solid var(--lineStrong);
    background: var(--hi);
    box-shadow: 0 0 14px rgba(0,255,102,.14) inset;
  }}
  @keyframes matrixPulse {{
    0%   {{ background: rgba(0,255,102,.06); }}
    50%  {{ background: rgba(0,255,102,.20); }}
    100% {{ background: rgba(0,255,102,.06); }}
  }}
  .breaking .row{{
    animation: matrixPulse 1.2s ease-in-out infinite;
  }}
  .breaking .row.empty{{
    animation: none;
    background: transparent;
    box-shadow: none;
    border-top: 1px dashed var(--line);
  }}
</style>
</head>
<body>
<div class="wrap">
  <div class="box">
    <div class="logo-ascii">
      <span class="cell">[ V ]</span>
      <span class="cell">[ O ]</span>
      <span class="cell">[ C ]</span>
    </div>

    <div class="title">CRYPTO::GLOBAL_NEWS_ALARM  |  VOICEofCRYPTO  |  MATRIX BRIEF  🐶</div>
    <div class="dim">T+   : {now_sgt} (Asia/Singapore)</div>
    <div class="dim">WIN  : {win_start} → {win_end} (SGT)  |  MODE: EN_sources & ZH_sources (no translation)</div>
  </div>

  <div class="box sec">
    <div class="title">[EN BRIEF]</div>
    <div class="split"></div>

    <div class="title dim">> [HEADLINES]</div>
    {en_blocks.get("headlines","")}

    <div class="split"></div>
    <div class="title dim">> [BREAKING]</div>
    <div class="breaking">
      {en_blocks.get("breaking","")}
    </div>

    <div class="split"></div>
    <div class="title dim">> [QUICK_HITS]</div>
    {en_blocks.get("quick","")}
  </div>

  <div class="box sec">
    <div class="title">[中文简报]</div>
    <div class="split"></div>

    <div class="title dim">> [头条]</div>
    {zh_blocks.get("headlines","")}

    <div class="split"></div>
    <div class="title dim">> [突发]</div>
    <div class="breaking">
      {zh_blocks.get("breaking","")}
    </div>

    <div class="split"></div>
    <div class="title dim">> [快讯]</div>
    {zh_blocks.get("quick","")}
  </div>
</div>
</body>
</html>"""


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

    # Fetch + dedup per language (so EN and ZH are independent)
    en_items = dedup(fetch_items(en_sources, tz, win_start, win_end)) if en_sources else []
    zh_items = dedup(fetch_items(zh_sources, tz, win_start, win_end)) if zh_sources else []

    en_head, en_break, en_quick = pick_sections(en_items)
    zh_head, zh_break, zh_quick = pick_sections(zh_items)

    en_blocks = {
        "headlines": render_section(en_head, "H"),
        "breaking":  render_section(en_break, "B"),
        "quick":     render_section(en_quick, "Q"),
    }
    zh_blocks = {
        "headlines": render_section(zh_head, "H"),
        "breaking":  render_section(zh_break, "B"),
        "quick":     render_section(zh_quick, "Q"),
    }

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, ".nojekyll"), "w", encoding="utf-8") as f:
        f.write("")

    page = html_page(
        now_sgt=now.strftime("%Y-%m-%d %H:%M:%S"),
        win_start=win_start.strftime("%H:%M"),
        win_end=win_end.strftime("%H:%M"),
        en_blocks=en_blocks,
        zh_blocks=zh_blocks,
    )
    with open(os.path.join(args.out, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)


if __name__ == "__main__":
    main()
