#!/usr/bin/env python3
import argparse, os, re, json
from datetime import datetime, timedelta
from dateutil import parser as dtparser
import pytz, feedparser, yaml

# Optional LLM bilingual helper
def llm_bilingual_lines(items, tz_label="SGT"):
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        # Fallback: no translation
        out = []
        for it in items:
            out.append({"en": it["title"], "zh": "（未配置 OPENAI_API_KEY，无法自动翻译）"})
        return out

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        payload = {
            "type": "text",
            "text": "For each item, produce: (1) concise EN headline rewrite (<=14 words) and (2) concise ZH translation (<=20 chars if possible). Return JSON array: [{en, zh}...].\n\nItems:\n"
                    + "\n".join([f"- {it['title']}" for it in items])
        }
        resp = client.responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            input=[payload],
        )
        text = resp.output_text.strip()
        data = json.loads(text)
        # Basic sanity
        if isinstance(data, list) and len(data) == len(items):
            return data
    except Exception:
        pass

    # Fallback if LLM fails
    out = []
    for it in items:
        out.append({"en": it["title"], "zh": "（翻译服务暂不可用）"})
    return out

def normalize_title(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[“”\"'’]", "", s)
    return s

def score_item(title: str) -> float:
    t = title.lower()
    hot = [
        ("sec", 2.0), ("etf", 2.0), ("hack", 2.5), ("exploit", 2.5), ("liquidat", 2.0),
        ("ban", 2.0), ("lawsuit", 2.0), ("arrest", 2.3), ("indict", 2.3),
        ("bankrupt", 2.5), ("halt", 2.2), ("outage", 2.0), ("stablecoin", 1.6),
        ("fed", 1.6), ("treasury", 1.6), ("rate", 1.4),
    ]
    base = 4.5
    for k, w in hot:
        if k in t:
            base += w
    return min(10.0, round(base, 1))

def classify(title: str) -> str:
    t = title.lower()
    if any(k in t for k in ["hack", "exploit", "drain", "scam", "phishing", "ransom"]):
        return "Security"
    if any(k in t for k in ["sec", "law", "regulat", "ban", "court", "bill"]):
        return "Regulation"
    if any(k in t for k in ["etf", "funding", "raises", "series", "acquire", "merger"]):
        return "Biz/Capital"
    if any(k in t for k in ["btc", "bitcoin", "eth", "ether", "price", "liquidat", "market"]):
        return "Markets"
    return "General"

def html_page(now_sgt, win_start, win_end, rows, links):
    # Matrix black + green terminal
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
  .title{{font-weight:700;}}
  .dim{{color:var(--dim);}}
  a{{color:var(--fg); text-decoration:underline;}}
  .sec{{margin-top:14px;}}
  .row{{padding:8px 0; border-top:1px dashed var(--line);}}
  .row:first-child{{border-top:none;}}
  .tag{{display:inline-block; padding:1px 8px; border:1px solid var(--line); margin-right:8px;}}
  .score{{float:right;}}
  .links li{{margin:6px 0;}}
</style>
</head>
<body>
<div class="wrap">
  <div class="box">
    <div class="title">CRYPTO::GLOBAL_NEWS_ALARM  |  MATRIX BRIEF</div>
    <div class="dim">T+   : {now_sgt}</div>
    <div class="dim">WIN  : {win_start} → {win_end} (SGT)  |  MODE: RSS/X → DEDUP → SCORE → BRIEF</div>
  </div>

  <div class="sec box">
    <div class="title">[HEADLINES]</div>
    {rows.get("headlines","")}
  </div>

  <div class="sec box">
    <div class="title">[BREAKING]</div>
    {rows.get("breaking","")}
  </div>

  <div class="sec box">
    <div class="title">[QUICK_HITS]</div>
    {rows.get("quick","")}
  </div>

  <div class="sec box">
    <div class="title">[LINKS]</div>
    <ul class="links">
      {links}
    </ul>
  </div>
</div>
</body>
</html>"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window-hours", type=int, default=4)
    ap.add_argument("--tz", type=str, default="Asia/Singapore")
    ap.add_argument("--out", type=str, default="site")
    args = ap.parse_args()

    tz = pytz.timezone(args.tz)
    now = datetime.now(tz)
    win_end = now
    win_start = now - timedelta(hours=args.window_hours)

    with open("config/sources.yaml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    items = []
    for src in cfg.get("rss", []):
        feed = feedparser.parse(src["url"])
        for e in feed.entries[:50]:
            dt = None
            for k in ("published", "updated", "pubDate"):
                if getattr(e, k, None):
                    try:
                        dt = dtparser.parse(getattr(e, k))
                        break
                    except Exception:
                        pass
            if not dt:
                continue
            if dt.tzinfo is None:
                dt = pytz.UTC.localize(dt)
            dt_sgt = dt.astimezone(tz)
            if not (win_start <= dt_sgt <= win_end):
                continue
            link = getattr(e, "link", "").strip()
            title = getattr(e, "title", "").strip()
            if not title or not link:
                continue
            items.append({
                "source": src["name"],
                "title": title,
                "link": link,
                "published_sgt": dt_sgt.isoformat(),
                "class": classify(title),
                "score": score_item(title),
            })

    # Dedup by (normalized title OR link)
    seen_title = set()
    seen_link = set()
    dedup = []
    for it in sorted(items, key=lambda x: (-x["score"], x["published_sgt"])):
        nt = normalize_title(it["title"])
        if nt in seen_title or it["link"] in seen_link:
            continue
        seen_title.add(nt)
        seen_link.add(it["link"])
        dedup.append(it)

    # Simple selection
    dedup = sorted(dedup, key=lambda x: (-x["score"], x["published_sgt"]))
    breaking = [x for x in dedup if x["score"] >= 8.5][:2]
    remaining = [x for x in dedup if x not in breaking]
    headlines = remaining[:5]
    quick = remaining[5:17]

    # bilingual lines (only for displayed items)
    display = breaking + headlines + quick
    bilingual = llm_bilingual_lines(display)

    # Build HTML rows + links list
    link_map = []
    def render_block(block, start_idx):
        html = []
        for i, it in enumerate(block):
            bi = bilingual[start_idx + i]
            idx = len(link_map) + 1
            link_map.append((idx, it["source"], it["link"]))
            html.append(
                f'<div class="row">'
                f'<span class="tag">{it["class"]}</span>'
                f'<span class="score">[{it["score"]}/10]</span><br/>'
                f'<div>EN: {bi.get("en","")}</div>'
                f'<div>ZH: {bi.get("zh","")}</div>'
                f'<div class="dim">↳ src: ({idx}) {it["source"]}</div>'
                f'</div>'
            )
        return "\n".join(html)

    rows = {}
    k = 0
    rows["headlines"] = render_block(headlines, k + len(breaking))
    rows["breaking"]  = render_block(breaking, 0)
    rows["quick"]     = render_block(quick, len(breaking) + len(headlines))
    links_html = "\n".join([f'<li>({i}) [{src}] <a href="{url}" target="_blank" rel="noreferrer">{url}</a></li>'
                            for i, src, url in link_map])

    os.makedirs(args.out, exist_ok=True)
    # Jekyll off
    with open(os.path.join(args.out, ".nojekyll"), "w", encoding="utf-8") as f:
        f.write("")
    page = html_page(
        now_sgt=now.strftime("%Y-%m-%d %H:%M:%S SGT"),
        win_start=win_start.strftime("%H:%M"),
        win_end=win_end.strftime("%H:%M"),
        rows=rows,
        links=links_html
    )
    with open(os.path.join(args.out, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)

if __name__ == "__main__":
    main()
