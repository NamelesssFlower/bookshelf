#!/usr/bin/env python3
"""
📚 Book Tracker — Add a book to your Firebase library
Usage: python3 add_book.py <any_url_or_title>
"""

import sys
import re
import json
import html
import os
import pathlib
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone
import time

# ── Load .env ─────────────────────────────────
def _load_env():
    env_file = pathlib.Path(__file__).parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())
_load_env()

# ── Find service account JSON ─────────────────
def _find_service_account() -> pathlib.Path | None:
    here = pathlib.Path(__file__).parent

    # 1. Explicit env var
    explicit = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    if explicit and pathlib.Path(explicit).exists():
        return pathlib.Path(explicit)

    # 2. Known filename (your downloaded file)
    known = here / "bookshelf-1d2b7-firebase-adminsdk-fbsvc-e366add83c.json"
    if known.exists():
        return known

    # 3. Auto-detect any adminsdk / service-account JSON in same folder
    for pattern in ["*firebase-adminsdk*.json", "*service-account*.json"]:
        matches = list(here.glob(pattern))
        if matches:
            return matches[0]

    return None

SERVICE_ACCOUNT = _find_service_account()
# ─────────────────────────────────────────────

# Optional Google Books API key (set via env or in .env to increase quota)
GOOGLE_BOOKS_API_KEY = os.environ.get("GOOGLE_BOOKS_API_KEY")


def init_firebase():
    """Initialise firebase-admin. Install with: pip3 install firebase-admin"""
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore
    except ImportError:
        print("\n  ✗  firebase-admin is not installed.")
        print("     Fix: pip3 install firebase-admin --break-system-packages")
        sys.exit(1)

    if SERVICE_ACCOUNT is None:
        print("\n  ✗  Service account JSON not found.")
        print("     Make sure this file is in the same folder as add_book.py:")
        print("     bookshelf-1d2b7-firebase-adminsdk-fbsvc-e366add83c.json")
        sys.exit(1)

    print(f"  🔑  Service account: {SERVICE_ACCOUNT.name}")

    if not firebase_admin._apps:
        cred = credentials.Certificate(str(SERVICE_ACCOUNT))
        firebase_admin.initialize_app(cred)

    return firestore.client()


# ── Page fetching ─────────────────────────────

def is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def fetch_page_info(url: str) -> dict:
    """Fetch og:title and og:image from any webpage."""
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

    for pattern in [
        r'property=["\']og:image["\'][^>]+content=["\'](https?://[^"\']+)["\']',
        r'content=["\'](https?://[^"\']+)["\'][^>]+property=["\']og:image["\']',
    ]:
        m = re.search(pattern, raw, re.I)
        if m:
            result["cover"] = html.unescape(m.group(1).strip())
            break

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
            result["title"] = html.unescape(
                re.sub(r"<[^>]+>", "", m.group(1))
            ).strip()

    return result


def clean_page_title(raw_title: str) -> str:
    t = raw_title
    by_match = re.match(r"^(.+?)\s+by\s+(.+?)(?:\s*[\|–—:\-]|$)", t, re.I)
    if by_match:
        title  = by_match.group(1).strip()
        author = re.split(r"[\|–—]", by_match.group(2))[0].strip()
        return f"{title} {author}"
    parts = re.split(r"\s*[\|–—]\s*", t)
    parts = [p.strip() for p in parts if len(p.strip()) > 4]
    if parts:
        return parts[0] if len(parts[0]) > 8 else " ".join(parts[:2])
    return t


def get_search_query_and_cover(raw: str) -> tuple[str, str | None]:
    if not is_url(raw):
        return raw, None

    print("  🌐  Fetching page…")

    if "amazon." in raw:
        m = re.search(r"amazon\.[^/]+/([A-Za-z][^/]{4,})/dp/", raw)
        info = fetch_page_info(raw)
        if m:
            slug = m.group(1).replace("-", " ")
            print(f"  → query: \"{slug}\"")
            if info.get("cover"): print("  → cover from page ✓")
            return slug, info.get("cover")
        if info["title"]:
            return clean_page_title(info["title"]), info.get("cover")

    if "goodreads.com" in raw:
        m = re.search(r"goodreads\.com/book/show/\d+[.-](.+?)(?:\?|$)", raw)
        info = fetch_page_info(raw)
        if m:
            return m.group(1).replace("-", " ").replace("_", " "), info.get("cover")
        if info["title"]:
            return clean_page_title(info["title"]), info.get("cover")

    info = fetch_page_info(raw)
    if info.get("cover"): print("  → cover image found on page ✓")
    if info["title"]:
        query = clean_page_title(info["title"])
        print(f"  → page title: \"{info['title']}\"")
        print(f"  → searching:  \"{query}\"")
        return query, info.get("cover")

    print("  ⚠️  Couldn't extract a title from that page.")
    fallback = input("  Enter the book title/author manually: ").strip()
    return fallback, None


# ── Google Books ──────────────────────────────

def _gb_fetch(url: str) -> list:
    # attach API key if provided to increase quota
    if GOOGLE_BOOKS_API_KEY and "key=" not in url:
        url = url + ("&" if "?" in url else "?") + "key=" + urllib.parse.quote(GOOGLE_BOOKS_API_KEY)

    max_attempts = 5
    base_delay = 1.0
    for attempt in range(1, max_attempts + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "BookTracker/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read()).get("items", [])
        except urllib.error.HTTPError as e:
            if e.code == 429:
                # Rate limited — respect Retry-After if present, otherwise exponential backoff
                retry_after = None
                try:
                    retry_after = e.headers.get("Retry-After")
                except Exception:
                    retry_after = None
                if retry_after:
                    try:
                        wait = float(retry_after)
                    except Exception:
                        wait = base_delay * (2 ** (attempt - 1))
                else:
                    wait = base_delay * (2 ** (attempt - 1))
                print(f"  ✗ Google Books rate-limited (429). Retrying in {wait:.1f}s (attempt {attempt}/{max_attempts})")
                time.sleep(wait)
                continue
            else:
                print(f"  ✗ Google Books HTTP error {e.code}: {e.reason}")
                return []
        except Exception as e:
            print(f"  ✗ Google Books error: {e}")
            if attempt < max_attempts:
                wait = base_delay * (2 ** (attempt - 1))
                time.sleep(wait)
                continue
            return []
    return []


def search_google_books(query: str) -> dict | None:
    base  = "https://www.googleapis.com/books/v1/volumes"
    clean = re.sub(r"[-\s]", "", query)

    if re.fullmatch(r"\d{13}", clean):
        items = _gb_fetch(f"{base}?q=isbn:{clean}")
        if items: return _parse_volume(items[0])

    items = _gb_fetch(f"{base}?q={urllib.parse.quote(query)}&maxResults=5")
    if items: return _parse_volume(items[0])
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
        "googleId":      item.get("id", ""),
        "title":         info.get("title", "Unknown Title"),
        "author":        ", ".join(info.get("authors", ["Unknown Author"])),
        "publisher":     info.get("publisher", ""),
        "publishedYear": (info.get("publishedDate") or "")[:4],
        "genre":         cats[0] if cats else "",
        "isbn":          ids.get("ISBN_13") or ids.get("ISBN_10", ""),
        "coverUrl":      cover,
    }


# ── Prompt ────────────────────────────────────

def prompt_user(book: dict) -> dict | None:
    print()
    print("─" * 52)
    print(f"  📖  {book['title']}")
    print(f"  ✍️   {book['author']}")
    if book.get("publisher"):
        print(f"  🏠  {book['publisher']} ({book.get('publishedYear', '')})")
    if book.get("genre"):
        print(f"  🏷   {book['genre']}")
    src = book.get("coverSource", "Google Books")
    print(f"  🖼   {'Cover: ' + src if book.get('coverUrl') else 'No cover image'}")
    print("─" * 52)

    if input("  Is this the right book? [Y/n]: ").strip().lower() == "n":
        new_query = input("  Enter title/author to search instead: ").strip()
        if not new_query: return None
        new_book = search_google_books(new_query)
        if not new_book:
            print("  ✗ Couldn't find it.")
            return None
        return prompt_user(new_book)

    print()
    print("  Which list?")
    print("    1 → To Read  (I own it)")
    print("    2 → To Buy   (I want it)")
    print("    3 → Read     (finished)")
    choice   = input("  Choice [1/2/3, default 1]: ").strip()
    book["list"] = {"1": "To Read", "2": "To Buy", "3": "Read"}.get(choice, "To Read")

    tags_raw      = input("  Tags (comma-separated, or blank): ").strip()
    book["tags"]  = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
    book["notes"] = input("  Notes (optional): ").strip()
    return book


# ── Firebase ──────────────────────────────────

def check_duplicate(db, google_id: str) -> bool:
    try:
        from google.cloud.firestore_v1.base_query import FieldFilter
        docs = (db.collection("books")
                  .where(filter=FieldFilter("googleId", "==", google_id))
                  .limit(1).get())
    except Exception:
        # older firebase-admin fallback
        docs = (db.collection("books")
                  .where("googleId", "==", google_id)
                  .limit(1).get())
    return len(docs) > 0


def save_to_firebase(db, book: dict) -> bool:
    doc = {
        "title":         book["title"],
        "author":        book["author"],
        "coverUrl":      book.get("coverUrl", ""),
        "genre":         book.get("genre", ""),
        "publisher":     book.get("publisher", ""),
        "isbn":          book.get("isbn", ""),
        "googleId":      book.get("googleId", ""),
        "publishedYear": book.get("publishedYear", ""),
        "list":          book["list"],
        "tags":          book.get("tags", []),
        "notes":         book.get("notes", ""),
        "dateAdded":     datetime.now(timezone.utc),
    }
    try:
        db.collection("books").add(doc)
        print(f"\n  ✅  Saved! \"{book['title']}\" → {book['list']}")
        return True
    except Exception as e:
        print(f"\n  ✗  Firebase error: {e}")
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
        print()
        print("  Or plain title/author:")
        print('    python3 add_book.py "Pond Claire-Louise Bennett"')
        sys.exit(1)

    # Install check
    try:
        import firebase_admin
    except ImportError:
        print("\n  ✗  firebase-admin is not installed.")
        print("     Run this first:")
        print("     pip3 install firebase-admin --break-system-packages")
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
        if retry: book = search_google_books(retry)
        if not book:
            print("  ✗  No match found. Exiting.")
            sys.exit(1)

    # Page cover takes priority — it's always the right edition
    if page_cover:
        book["coverUrl"]    = page_cover
        book["coverSource"] = "page ✓"
    else:
        book["coverSource"] = "Google Books"

    db = init_firebase()

    if book.get("googleId") and check_duplicate(db, book["googleId"]):
        print(f"\n  ⚠️   \"{book['title']}\" is already in your library!")
        if input("  Add again anyway? [y/N]: ").strip().lower() != "y":
            sys.exit(0)

    confirmed = prompt_user(book)
    if not confirmed:
        print("  Cancelled.")
        sys.exit(0)

    save_to_firebase(db, confirmed)


if __name__ == "__main__":
    main()