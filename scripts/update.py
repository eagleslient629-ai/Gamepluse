import json, re, urllib.request, xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone, timedelta

FEEDS = [
    ("IGN", "https://feeds.feedburner.com/ign/news", ""),
    ("PC Gamer", "https://www.pcgamer.com/rss/", "PC"),
    ("GamesRadar+", "https://www.gamesradar.com/rss/", ""),
    ("Eurogamer", "https://www.eurogamer.net/feed", ""),
    ("Gematsu", "https://www.gematsu.com/feed", ""),
    ("Push Square", "https://www.pushsquare.com/feeds/latest", "PlayStation"),
    ("Pure Xbox", "https://www.purexbox.com/feeds/latest", "Xbox"),
    ("Nintendo Life", "https://www.nintendolife.com/feeds/latest", "Nintendo"),
    ("Pocket Gamer", "https://www.pocketgamer.com/rss/", "Mobile"),
    ("IndieGamesPlus", "https://indiegamesplus.com/feed", "Indie"),
    ("Rock Paper Shotgun", "https://www.rockpapershotgun.com/feed/news", "PC"),
]
PER_FEED = 10
IST = timezone(timedelta(hours=5, minutes=30))
UA = {"User-Agent": "Mozilla/5.0 (compatible; gampluse-bot/2.2)"}
PLAT = [
    ("PlayStation", r"playstation|\bps[345]\b|\bpsn\b|\bps plus\b"),
    ("Xbox", r"xbox|game pass"),
    ("Nintendo", r"nintendo|\bswitch\b|zelda|mario|pok[eé]mon|kirby|metroid"),
    ("Mobile", r"\bmobile\b|\bios\b|android|iphone|\bipad\b"),
    ("PC", r"\bpc\b|steam|epic games|nvidia|geforce|\bamd\b|windows|\bgog\b|itch\.io"),
    ("Indie", r"\bindie\b|solo dev|roguelike|pixel art|itch\.io|small studio"),
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

def og_image(url):
    try:
        html = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=8).read(200000).decode("utf-8", "ignore")
        for p in (r'<meta[^>]+property=["\']og:image["\'][^>]*content=["\']([^"\']+)',
                  r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*property=["\']og:image["\']'):
            m = re.search(p, html, re.I)
            if m and m.group(1).startswith("https://"):
                return m.group(1).replace("&amp;", "&")
    except Exception:
        pass
    return ""

def load_news():
    items, seen = [], set()
    for name, url, dp in FEEDS:
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
                                  "p": sorted(set([n for n, r in PLAT if re.search(r, title, re.I)] + ([dp] if dp else []))),
                                  "d": d.strftime("%b %d, %Y") if d.year > 1 else "", "_ts": d.timestamp()})
        except Exception as ex:
            print("skip", name, ex)
    items.sort(key=lambda x: x["_ts"], reverse=True)
    for i in items:
        del i["_ts"]
    return items[:70]

def app_inr_details(appid):
    # Fetch exact INR regional pricing for a single Steam appid via appdetails
    try:
        det = json.loads(get("https://store.steampowered.com/api/appdetails?appids=%s&cc=IN&l=en" % appid, timeout=12))
        entry = det.get(str(appid), {})
        if not entry.get("success"):
            return None
        data = entry.get("data") or {}
        po = data.get("price_overview")
        if not po:
            return None
        return {
            "t": data.get("name"),
            "u": "https://store.steampowered.com/app/%s" % appid,
            "img": data.get("header_image") or "https://cdn.cloudflare.steamstatic.com/steam/apps/%s/header.jpg" % appid,
            "orig": po.get("initial"),
            "price": po.get("final"),
            "off": po.get("discount_percent", 0),
            "cur": po.get("currency", "INR"),
        }
    except Exception:
        return None

def steam():
    # Use uppercase cc=IN; if featuredcategories returns 0 prices from US GitHub runners,
    # enrich each appid directly via appdetails?cc=IN which always returns true INR pricing.
    j = json.loads(get("https://store.steampowered.com/api/featuredcategories?cc=IN&l=en"))
    def conv(x):
        i = x.get("id")
        if not i:
            return None
        orig = x.get("original_price") or 0
        price = x.get("final_price") or 0
        cur = x.get("currency") or "INR"
        if price <= 0 or cur != "INR":
            enriched = app_inr_details(i)
            if enriched and (enriched.get("price") or 0) > 0:
                return enriched
        if price <= 0:
            return None
        return {
            "t": x.get("name"),
            "u": "https://store.steampowered.com/app/%s" % i,
            "img": x.get("header_image") or "https://cdn.cloudflare.steamstatic.com/steam/apps/%s/header.jpg" % i,
            "orig": orig,
            "price": price,
            "off": x.get("discount_percent", 0),
            "cur": cur,
        }

    sp_raw = [x for x in j.get("specials", {}).get("items", []) if x.get("discount_percent", 0) > 0 and x.get("id")]
    sp = [c for c in (conv(x) for x in sp_raw[:16]) if c]
    sp.sort(key=lambda d: d["off"], reverse=True)

    top_raw = [x for x in j.get("top_sellers", {}).get("items", []) if x.get("id")]
    top = [c for c in (conv(x) for x in top_raw[:12]) if c]
    return sp[:12], top[:8]

def steam_indies():
    # Fetch discounted indie games & small studio releases in INR (tag 492 = Indie)
    url = "https://store.steampowered.com/search/results/?query&start=0&count=18&tags=492&specials=1&cc=IN&l=en&json=1"
    j = json.loads(get(url))
    out = []
    for it in j.get("items", []):
        logo = it.get("logo", "")
        m = re.search(r"/apps/(\d+)/", logo)
        if not m:
            continue
        appid = m.group(1)
        enriched = app_inr_details(appid)
        if enriched and (enriched.get("price") or 0) > 0:
            out.append(enriched)
            if len(out) >= 8:
                break
    return out

def epic():
    j = json.loads(get("https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions?locale=en-US&country=IN&allowCountries=IN"))
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
                    "orig": price.get("originalPrice"), "cur": price.get("currencyCode", "INR")})
    return out

now = datetime.now(IST).strftime("%b %d, %Y %I:%M %p IST")

items = load_news()
need = [it for it in items[:45] if not it["i"]]
with ThreadPoolExecutor(8) as ex:
    for it, img in zip(need, ex.map(lambda i: og_image(i["u"]), need)):
        it["i"] = img
print("images added", sum(1 for it in need if it["i"]), "of", len(need))
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
    ind = steam_indies()
    if ind: deals["indies"] = ind; changed = True
except Exception as ex:
    print("steam indies failed", ex)
try:
    fr = epic()
    deals["epicFree"] = fr; changed = True
except Exception as ex:
    print("epic failed", ex)
if changed:
    deals["updated"] = now
    json.dump(deals, open("deals.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("deals saved")
