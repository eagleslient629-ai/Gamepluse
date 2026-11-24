import json, re, urllib.request, xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta

FEEDS = [
    ("IGN", "https://feeds.feedburner.com/ign/news"),
    ("PC Gamer", "https://www.pcgamer.com/rss/"),
    ("GamesRadar+", "https://www.gamesradar.com/rss/"),
    ("Eurogamer", "https://www.eurogamer.net/feed"),
    ("Gematsu", "https://www.gematsu.com/feed"),
]
PER_FEED = 8
IST = timezone(timedelta(hours=5, minutes=30))
UA = {"User-Agent": "Mozilla/5.0 (compatible; gampluse-bot/2.0)"}
PLAT = [
    ("PlayStation", r"playstation|\bps[345]\b|\bpsn\b|\bps plus\b"),
    ("Xbox", r"xbox|game pass"),
    ("Nintendo", r"nintendo|\bswitch\b|zelda|mario|pok[eé]mon|kirby|metroid"),
    ("Mobile", r"\bmobile\b|\bios\b|android|iphone|\bipad\b"),
    ("PC", r"\bpc\b|steam|epic games|nvidia|geforce|\bamd\b|windows|\bgog\b"),
]

def get(url, timeout=25):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()

def strip(tag):
    return tag.split("}")[-1]

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

def image_of(e):
    for c in e.iter():
        if strip(c.tag) in ("content", "thumbnail", "enclosure"):
            u, ty = c.attrib.get("url", ""), c.attrib.get("type", "")
            if u.startswith("https://") and (ty.startswith("image") or c.attrib.get("medium") == "image"
                                             or re.search(r"\.(jpe?g|png|webp)(\?|$)", u, re.I)):
                return u
    for c in e.iter():
        if strip(c.tag) in ("description", "encoded", "summary", "content") and c.text:
            m = re.search(r'<img[^>]+src=["\'](https://[^"\']+)', c.text)
            if m:
                return m.group(1)
    return ""

def load_news():
    items, seen = [], set()
    for name, url in FEEDS:
        try:
            root = ET.fromstring(get(url))
            entries = [e for e in root.iter() if strip(e.tag) in ("item", "entry")]
            for e in entries[:PER_FEED]:
                f = {strip(c.tag): c for c in e}
                title = (f["title"].text or "").strip() if "title" in f else ""
                link = (f["link"].text or "").strip() if "link" in f else ""
                if "link" in f and not link:
                    link = f["link"].attrib.get("href", "")
                when = next((f[k].text for k in ("pubDate", "published", "updated") if k in f and f[k].text), None)
                d = parse_date(when)
                if title and link.startswith("http") and link not in seen:
                    seen.add(link)
                    items.append({"t": title, "u": link, "w": name, "i": image_of(e),
                                  "p": [n for n, r in PLAT if re.search(r, title, re.I)],
                                  "d": d.strftime("%b %d, %Y") if d.year > 1 else "", "_ts": d.timestamp()})
        except Exception as ex:
            print("skip", name, ex)
    items.sort(key=lambda x: x["_ts"], reverse=True)
    for i in items:
        del i["_ts"]
    return items[:36]

def steam():
    j = json.loads(get("https://store.steampowered.com/api/featuredcategories?cc=us&l=en"))
    def conv(x):
        i = x.get("id")
        return {"t": x.get("name"), "u": "https://store.steampowered.com/app/%s" % i,
                "img": x.get("header_image") or "https://cdn.cloudflare.steamstatic.com/steam/apps/%s/header.jpg" % i,
                "orig": x.get("original_price"), "price": x.get("final_price"),
                "off": x.get("discount_percent", 0), "cur": x.get("currency", "USD")}
    sp = [conv(x) for x in j.get("specials", {}).get("items", []) if x.get("discount_percent", 0) > 0 and x.get("id")]
    sp.sort(key=lambda d: d["off"], reverse=True)
    top = [conv(x) for x in j.get("top_sellers", {}).get("items", []) if x.get("id")]
    return sp[:12], top[:8]

def epic():
    j = json.loads(get("https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions?locale=en-US&country=US&allowCountries=US"))
    out = []
    for el in j["data"]["Catalog"]["searchStore"]["elements"]:
        promos = (el.get("promotions") or {}).get("promotionalOffers") or []
        price = (el.get("price") or {}).get("totalPrice") or {}
        if not promos or price.get("discountPrice") != 0:
            continue
        slug = el.get("productSlug") or ((el.get("offerMappings") or [{}])[0].get("pageSlug")) \
            or (((el.get("catalogNs") or {}).get("mappings") or [{}])[0].get("pageSlug"))
        if not slug:
            continue
        imgs = el.get("keyImages") or []
        img = next((x["url"] for x in imgs if x.get("type") in ("OfferImageWide", "DieselStoreFrontWide")),
                   imgs[0]["url"] if imgs else "")
        out.append({"t": el.get("title"), "u": "https://store.epicgames.com/en-US/p/" + slug, "img": img,
                    "orig": price.get("originalPrice"), "cur": price.get("currencyCode", "USD")})
    return out

now = datetime.now(IST).strftime("%b %d, %Y %I:%M %p IST")

items = load_news()
if items:
    json.dump({"updated": now, "items": items}, open("news.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("news", len(items))
else:
    print("no news fetched; news.json unchanged")

try:
    deals = json.load(open("deals.json", encoding="utf-8"))
except Exception:
    deals = {}
changed = False
try:
    sp, top = steam()
    if sp: deals["steam"] = sp; changed = True
    if top: deals["trending"] = top; changed = True
except Exception as ex:
    print("steam failed", ex)
try:
    fr = epic()
    deals["epicFree"] = fr; changed = True
except Exception as ex:
    print("epic failed", ex)
if changed:
    deals["updated"] = now
    json.dump(deals, open("deals.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("deals saved")
