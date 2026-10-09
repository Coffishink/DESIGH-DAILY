"""
抓取多个设计类 RSS 信息源（平面、品牌、字体、UI/UX、建筑、艺术）
带 URL 去重：7 天内推送过的文章不再重复抓取
"""
import feedparser
import time
import json
from datetime import datetime, timezone, timedelta

# 只保留最近几天的内容
MAX_AGE_DAYS = 3

# 已推送 URL 的保留天数
SEEN_MAX_AGE_DAYS = 7
SEEN_FILE = "seen_articles.json"

# 信息源清单：名字 + RSS地址
RSS_SOURCES = {
    # 平面、品牌、字体、包装与视觉设计
    "It's Nice That": "https://feeds2.feedburner.com/itsnicethat/SlXC",
    "Fonts In Use": "https://fontsinuse.com/staff-picks.rss",
    "BP&O": "https://bpando.org/feed/",
    "Slanted": "https://www.slanted.de/feed/",
    "Creative Bloq": "https://www.creativebloq.com/feed",

    # 产品、工业、建筑、空间与跨领域设计
    "Core77": "https://feeds.feedburner.com/core77/blog",
    "Designboom": "https://www.designboom.com/feed/",
    "Design Milk": "https://design-milk.com/feed/",
    "Yanko Design": "https://www.yankodesign.com/feed/",
    "Dezeen Interiors": "https://www.dezeen.com/interiors/feed/",

    # 网页、交互与 UI/UX
    "Smashing Magazine": "https://www.smashingmagazine.com/feed/",
    "Awwwards": "https://www.awwwards.com/blog/feed/",
    "HOVERSTAT.ES": "https://www.hoverstat.es/rss.xml",

    # 艺术、工艺、装置与视觉文化
    "Colossal": "https://www.thisiscolossal.com/feed/",
    "Disegno": "https://disegnojournal.com/newsfeed?format=rss",
}


def load_seen():
    """读取已见 URL 字典，并清理超过保留期限的旧记录"""
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}

    # 兼容旧格式（list）
    if isinstance(data, list):
        return {}

    now = datetime.now().timestamp()
    cutoff = now - SEEN_MAX_AGE_DAYS * 86400

    cleaned = {}
    for url, ts in data.items():
        try:
            if float(ts) >= cutoff:
                cleaned[url] = ts
        except Exception:
            continue
    return cleaned


def save_seen(seen_dict):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen_dict, f, ensure_ascii=False, indent=2)


def _is_recent(entry, max_age_days=MAX_AGE_DAYS):
    """判断这条内容是否在最近 N 天内。解析不出日期时保留（避免误杀）。"""
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                entry_ts = time.mktime(parsed)
                now_ts = datetime.now().timestamp()
                return (now_ts - entry_ts) <= max_age_days * 86400
            except Exception:
                continue
    return True


def fetch_rss(name, url, max_items=50):
    """抓取单个RSS源，返回最近几条（只保留近期内容）"""
    feed = feedparser.parse(url)

    if feed.bozo and not feed.entries:
        print(f"⚠️ {name} 抓取可能有问题，跳过（{url}）")
        return []

    results = []
    for entry in feed.entries[:max_items]:
        if not _is_recent(entry):
            continue
        results.append({
            "source": name,
            "title": entry.get("title", ""),
            "url": entry.get("link", ""),
            "published": entry.get("published", entry.get("updated", "")),
        })
    return results


if __name__ == "__main__":
    seen = load_seen()
    print(f"已加载 {len(seen)} 条历史记录（保留最近 {SEEN_MAX_AGE_DAYS} 天）")

    now_ts = datetime.now().timestamp()
    all_items = []

    for name, url in RSS_SOURCES.items():
        print(f"正在抓取 {name} ...")
        items = fetch_rss(name, url)
        fresh = [x for x in items if (x.get("url") or "").strip() not in seen]
        print(f"  → 抓到 {len(items)} 条，其中 {len(fresh)} 条是新的")
        for x in fresh:
            u = (x.get("url") or "").strip()
            if u:
                seen[u] = now_ts
        all_items.extend(fresh)

    print(f"\n总共抓到 {len(all_items)} 条新内容")

    output = {
        "fetched_at": datetime.now().isoformat(),
        "source": "rss_design",
        "items": all_items,
    }
    with open("rss_sources.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    save_seen(seen)

    print(f"已保存到 rss_sources.json（{len(all_items)} 条新内容）")
    print(f"已更新 seen_articles.json（当前 {len(seen)} 条，自动清理 {SEEN_MAX_AGE_DAYS} 天前的记录）")
