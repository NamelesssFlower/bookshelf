#!/usr/bin/env python3
"""
📚 Book Tracker — Add a book to your Airtable library
Usage: python3 add_book.py <any_url_or_title>

Supports: Amazon, Goodreads, publisher sites, bookshops, any webpage
Cover images are pulled directly from the source page — always edition-accurate.
"""

import sys
import re
import json
import html
import urllib.request
import urllib.parse
import urllib.error
from datetime import date

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
AIRTABLE_API_KEY = "patfe9Lvrx5VRxgZ6.9d03ef17ad51be02a10b644af5ee1e7d95c439d2c1cfc702a74497bb9df6eb43"
AIRTABLE_BASE_ID = "appVVvwt9KyiMkf6T"
AIRTABLE_TABLE   = "Books"
# ─────────────────────────────────────────────


def is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def fetch_page_info(url: str) -> dict:
    """
    Fetch a webpage and extract:
      - title: best available title string
      - cover: og:image URL (edition-accurate cover from the actual page)
    """
    result = {"title": None, "cover": None}
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-GB,en;q=0.9",
        })
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read(80000).decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  ⚠️  Could not fetch page: {e}")
        return result

    # ── Cover: og:image ──────────────────────────────────────────────────────
    # Try both attribute orderings
    for pattern in [
        r'property=["\']og:image["\'][^>]+content=["\'](https?://[^"\']+)["\']',
        r'content=["\'](https?://[^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'name=["\']og:image["\'][^>]+content=["\'](https?://[^"\']+)["\']',
    ]:
        m = re.search(pattern, raw, re.I)
        if m:
            result["cover"] = html.unescape(m.group(1).strip())
            break

    # ── Title: og:title > <title> > <h1> ────────────────────────────────────
    for pattern in [
        r'property=["\']og:title["\'][^>]+content=["\'](.*?)["\']',
        r'content=["\'](.*?)["\'][^>]+property=["\']og:title["\']',
    ]:
        m = re.search(pattern, raw, re.I)
        if m:
            result["title"] = html.unescape(m.group(1)).strip()
            break

    if not result["title"]:
        m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
        if m:
            result["title"] = html.unescape(m.group(1)).strip()

    if not result["title"]:
        m = re.search(r"<h1[^>]*>(.*?)</h1>", raw, re.I | re.S)
        if m:
            result["title"] = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()

    return result


def clean_page_title(raw_title: str) -> str:
    """
    Turn a page title like:
      "Pond by Claire-Louise Bennett | Fitzcarraldo Editions"
    into a clean search query:
      "Pond Claire-Louise Bennett"
    """
    t = raw_title

    # "Title by Author" pattern — very common on publisher sites
    by_match = re.match(r"^(.+?)\s+by\s+(.+?)(?:\s*[\|–—:\-]|$)", t, re.I)
    if by_match:
        title  = by_match.group(1).strip()
        author = re.split(r"[\|–—]", by_match.group(2))[0].strip()
        return f"{title} {author}"

    # Split on separators, take the first/longest meaningful chunk
    parts = re.split(r"\s*[\|–—]\s*", t)
    parts = [p.strip() for p in parts if len(p.strip()) > 4]
    if parts:
        return parts[0] if len(parts[0]) > 8 else " ".join(parts[:2])

    return t


def get_search_query_and_cover(raw: str) -> tuple[str, str | None]:
    """
    Returns (search_query, cover_url_or_None).
    cover_url comes from the page's og:image when available — always edition-accurate.
    """
    if not is_url(raw):
        return raw, None  # plain title — no cover from URL

    print("  🌐  Fetching page…")

    # Amazon: use title slug for query, but still fetch og:image for cover
    if "amazon." in raw:
        m = re.search(r"amazon\.[^/]+/([A-Za-z][^/]{4,})/dp/", raw)
        if m:
            slug = m.group(1).replace("-", " ")
            # Try to get cover from page too
            info = fetch_page_info(raw)
            cover = info.get("cover")
            print(f"  → query: \"{slug}\"")
            if cover:
                print(f"  → cover from page ✓")
            return slug, cover
        # ASIN only — fetch the page
        info = fetch_page_info(raw)
        query = clean_page_title(info["title"]) if info["title"] else raw
        return query, info.get("cover")

    # Goodreads: use slug for query, fetch page for cover
    if "goodreads.com" in raw:
        m = re.search(r"goodreads\.com/book/show/\d+[.-](.+?)(?:\?|$)", raw)
        info = fetch_page_info(raw)
        cover = info.get("cover")
        if m:
            slug = m.group(1).replace("-", " ").replace("_", " ")
            print(f"  → query: \"{slug}\"")
            return slug, cover
        if info["title"]:
            query = clean_page_title(info["title"])
            return query, cover

    # Everything else: fetch page for both title and cover
    info = fetch_page_info(raw)

    if info["cover"]:
        print(f"  → cover image found on page ✓")
    else:
        print(f"  → no cover image on page, will use Google Books")

    if info["title"]:
        query = clean_page_title(info["title"])
        print(f"  → page title: \"{info['title']}\"")
        print(f"  → searching: \"{query}\"")
        return query, info.get("cover")

    # Last resort: ask user
    print("  ⚠️  Couldn't extract a title from that page.")
    fallback = input("  Enter the book title/author manually: ").strip()
    return fallback, None


# ── Google Books ──────────────────────────────

def _gb_fetch(url: str) -> list:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BookTracker/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read()).get("items", [])
    except Exception as e:
        print(f"  ✗ Google Books error: {e}")
        return []


def search_google_books(query: str) -> dict | None:
    base  = "https://www.googleapis.com/books/v1/volumes"
    clean = re.sub(r"[-\s]", "", query)

    if re.fullmatch(r"\d{13}", clean):
        items = _gb_fetch(f"{base}?q=isbn:{clean}")
        if items:
            return _parse_volume(items[0])

    items = _gb_fetch(f"{base}?q={urllib.parse.quote(query)}&maxResults=5")
    if items:
        return _parse_volume(items[0])

    return None


def _parse_volume(item: dict) -> dict:
    info  = item.get("volumeInfo", {})
    ids   = {i["type"]: i["identifier"] for i in info.get("industryIdentifiers", [])}
    img   = info.get("imageLinks", {})
    cover = (img.get("extraLarge") or img.get("large") or
             img.get("medium")     or img.get("thumbnail", ""))
    cover = re.sub(r"&zoom=\d", "", cover).replace("http://", "https://")
    cats  = info.get("categories", [])
    return {
        "google_id":      item.get("id", ""),
        "title":          info.get("title", "Unknown Title"),
        "author":         ", ".join(info.get("authors", ["Unknown Author"])),
        "publisher":      info.get("publisher", ""),
        "published_year": (info.get("publishedDate") or "")[:4],
        "genre":          cats[0] if cats else "",
        "description":    info.get("description", ""),
        "isbn":           ids.get("ISBN_13") or ids.get("ISBN_10", ""),
        "cover_url":      cover,  # may be overridden by page cover
    }


# ── User prompt ───────────────────────────────

def prompt_user(book: dict) -> dict | None:
    print()
    print("─" * 52)
    print(f"  📖  {book['title']}")
    print(f"  ✍️   {book['author']}")
    if book["publisher"]:
        print(f"  🏠  {book['publisher']} ({book['published_year']})")
    if book["genre"]:
        print(f"  🏷   {book['genre']}")
    cover_src = book.get("cover_source", "Google Books")
    print(f"  🖼   {'Cover: ' + cover_src if book['cover_url'] else 'No cover image found'}")
    print("─" * 52)

    if input("  Is this the right book? [Y/n]: ").strip().lower() == "n":
        new_query = input("  Enter title/author to search instead: ").strip()
        if not new_query:
            return None
        new_book = search_google_books(new_query)
        if not new_book:
            print("  ✗ Couldn't find it. Try a different title/author combo.")
            return None
        new_book["cover_source"] = "Google Books"
        return prompt_user(new_book)

    print()
    print("  Which list?")
    print("    1 → To Read  (I own it)")
    print("    2 → To Buy   (I want it)")
    print("    3 → Read     (finished)")
    choice   = input("  Choice [1/2/3, default 1]: ").strip()
    list_map = {"1": "To Read", "2": "To Buy", "3": "Read"}
    book["list"] = list_map.get(choice, "To Read")

    tags_raw      = input("  Tags (comma-separated, or blank): ").strip()
    book["tags"]  = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
    book["notes"] = input("  Notes (optional): ").strip()
    return book


# ── Airtable ──────────────────────────────────

def check_duplicate(google_id: str) -> bool:
    formula = urllib.parse.quote(f"{{Google Books ID}} = '{google_id}'")
    url = (f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/"
           f"{urllib.parse.quote(AIRTABLE_TABLE)}?filterByFormula={formula}&maxRecords=1")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {AIRTABLE_API_KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return len(json.loads(resp.read()).get("records", [])) > 0
    except Exception:
        return False


def save_to_airtable(book: dict) -> bool:
    fields = {
        "Title":           book["title"],
        "Author":          book["author"],
        "Cover URL":       book["cover_url"],
        "Genre":           book["genre"],
        "Publisher":       book["publisher"],
        "ISBN":            book["isbn"],
        "Google Books ID": book["google_id"],
        "List":            book["list"],
        "Date Added":      date.today().isoformat(),
    }
    if book.get("published_year"):
        try:    fields["Published Year"] = int(book["published_year"])
        except ValueError: pass
    if book.get("tags"):   fields["Tags"]  = book["tags"]
    if book.get("notes"):  fields["Notes"] = book["notes"]

    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{urllib.parse.quote(AIRTABLE_TABLE)}"
    req = urllib.request.Request(
        url, data=json.dumps({"fields": fields}).encode(),
        headers={"Authorization": f"Bearer {AIRTABLE_API_KEY}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        print(f"\n  ✅  Saved! \"{book['title']}\" → {book['list']}")
        return True
    except urllib.error.HTTPError as e:
        print(f"\n  ✗  Airtable error {e.code}: {e.read().decode()}")
        return False


# ── Main ──────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 add_book.py <url_or_title>")
        print()
        print("  Any URL works:")
        print('    python3 add_book.py "https://fitzcarraldoeditions.com/books/pond"')
        print('    python3 add_book.py "https://www.amazon.com/dp/0374533555"')
        print('    python3 add_book.py "https://www.versobooks.com/products/123"')
        print('    python3 add_book.py "https://www.waterstones.com/book/..."')
        print()
        print("  Or plain title/author:")
        print('    python3 add_book.py "Pond Claire-Louise Bennett"')
        sys.exit(1)

    raw = " ".join(sys.argv[1:])
    print(f"\n🔍  Looking up: {raw}")

    query, page_cover = get_search_query_and_cover(raw)

    if not query:
        print("  ✗  No search query — exiting.")
        sys.exit(1)

    book = search_google_books(query)

    if not book:
        print(f"  ✗  Couldn't find a match for \"{query}\".")
        retry = input("  Try a different title/author? (or Enter to exit): ").strip()
        if retry:
            book = search_google_books(retry)
        if not book:
            print("  ✗  No match found. Exiting.")
            sys.exit(1)

    # Prefer the page's own cover (edition-accurate) over Google Books cover
    if page_cover:
        book["cover_url"]    = page_cover
        book["cover_source"] = "page image ✓"
    else:
        book["cover_source"] = "Google Books"

    if book["google_id"] and check_duplicate(book["google_id"]):
        print(f"\n  ⚠️   \"{book['title']}\" is already in your library!")
        if input("  Add again anyway? [y/N]: ").strip().lower() != "y":
            sys.exit(0)

    confirmed = prompt_user(book)
    if not confirmed:
        print("  Cancelled.")
        sys.exit(0)

    save_to_airtable(confirmed)


if __name__ == "__main__":
    main()
