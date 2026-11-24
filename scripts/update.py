import json, urllib.request, xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta

FEEDS = [
    ("IGN", "https://feeds.feedburner.com/ign/news"),
    ("PC Gamer", "https://www.pcgamer.com/rss/"),
    ("GamesRadar+", "https://www.gamesradar.com/rss/"),
    ("Eurogamer", "https://www.eurogamer.net/feed"),
    ("Gematsu", "https://www.gematsu.com/feed"),
]
PER_FEED = 6
IST = timezone(timedelta(hours=5, minutes=30))

def parse_date(t):
    if not t:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        d = parsedate_to_datetime(t)
    except Exception:
        try:
            d = datetime.fromisoformat(t.replace("Z", "+00:00"))
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

def strip(tag):
    return tag.split("}")[-1]

items = []
for name, url in FEEDS:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "gampluse-bot/1.0"})
        root = ET.fromstring(urllib.request.urlopen(req, timeout=20).read())
        entries = [e for e in root.iter() if strip(e.tag) in ("item", "entry")]
        for e in entries[:PER_FEED]:
            f = {strip(c.tag): c for c in e}
            title = (f["title"].text or "").strip() if "title" in f else ""
            link = (f["link"].text or "").strip() if "link" in f else ""
            if "link" in f and not link:
                link = f["link"].attrib.get("href", "")
            when = None
            for k in ("pubDate", "published", "updated"):
                if k in f and f[k].text:
                    when = f[k].text
                    break
            d = parse_date(when)
            if title and link.startswith("http"):
                items.append({"t": title, "u": link, "w": name,
                              "d": d.strftime("%b %d, %Y") if d.year > 1 else "", "_ts": d.timestamp()})
    except Exception as ex:
        print("skip", name, ex)

items.sort(key=lambda x: x["_ts"], reverse=True)
for i in items:
    del i["_ts"]
if items:
    out = {"updated": datetime.now(IST).strftime("%b %d, %Y %I:%M %p IST"), "items": items[:30]}
    json.dump(out, open("news.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("wrote", len(out["items"]))
else:
    print("no items fetched; news.json unchanged")
