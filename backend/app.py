import os
import json
from flask import Flask, request, jsonify, send_from_directory, abort
from flask_cors import CORS

# We import helpers from the CLI script to reuse parsing/search logic.
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
try:
    import add_book as ab
except Exception:
    # If import fails, ensure relative imports still work
    from importlib import import_module
    ab = import_module('add_book')

app = Flask(__name__)
CORS(app)


@app.route('/')
def index():
    # Serve the project's index.html from the repo root
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    target = os.path.join(root, 'index.html')
    if os.path.isfile(target):
        return send_from_directory(root, 'index.html')
    return jsonify({'error': 'index.html not found'}), 404


@app.route('/<path:path>')
def static_proxy(path):
    # Serve static assets (CSS/JS) from repo root
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    target = os.path.join(root, path)
    if os.path.isfile(target):
        return send_from_directory(root, path)
    abort(404)


@app.route('/api/add-book', methods=['POST'])
def add_book():
    data = request.get_json() or {}
    raw = data.get('input') or data.get('url') or ''
    if not raw:
        return jsonify({'error': 'Missing `input` parameter'}), 400

    # Non-interactive processing: derive a search query and optional cover
    page_cover = None
    query = raw
    try:
        if ab.is_url(raw):
            # handle amazon / goodreads heuristics similarly to the CLI
            if 'amazon.' in raw:
                m = ab.re.search(r"amazon\.[^/]+/([A-Za-z][^/]{4,})/dp/", raw)
                if m:
                    query = m.group(1).replace('-', ' ')
                else:
                    info = ab.fetch_page_info(raw)
                    if info.get('title'):
                        query = ab.clean_page_title(info['title'])
                    page_cover = info.get('cover')
            elif 'goodreads.com' in raw:
                m = ab.re.search(r"goodreads\.com/book/show/\d+[.-](.+?)(?:\?|$)", raw)
                info = ab.fetch_page_info(raw)
                page_cover = info.get('cover')
                if m:
                    query = m.group(1).replace('-', ' ').replace('_', ' ')
                elif info.get('title'):
                    query = ab.clean_page_title(info['title'])
            else:
                info = ab.fetch_page_info(raw)
                page_cover = info.get('cover')
                if info.get('title'):
                    query = ab.clean_page_title(info['title'])
                else:
                    # fallback to raw URL as query
                    query = raw
        else:
            query = raw
    except Exception as e:
        return jsonify({'error': f'Failed to parse input: {e}'}), 500

    # Search Google Books
    book = ab.search_google_books(query)
    if not book:
        return jsonify({'error': 'No match found on Google Books', 'query': query}), 404

    # Prefer page cover if available
    if page_cover:
        book['coverUrl'] = page_cover
        book['coverSource'] = 'page'
    else:
        book['coverSource'] = 'Google Books'

    # Defaults: assume yes, default list "To Read"
    book['list'] = 'To Read'
    book.setdefault('tags', [])
    book.setdefault('notes', '')

    # Persist to Firestore using admin SDK (init_firebase uses service account)
    try:
        db = ab.init_firebase()
    except Exception as e:
        return jsonify({'error': f'Failed to initialize Firebase: {e}'}), 500

    try:
        # if duplicate check exists, skip or return info
        if book.get('googleId') and ab.check_duplicate(db, book['googleId']):
            return jsonify({'status': 'exists', 'message': 'Book already in library', 'book': book}), 200
        ok = ab.save_to_firebase(db, book)
        if ok:
            return jsonify({'status': 'ok', 'book': book}), 201
        return jsonify({'error': 'Failed to save to Firestore'}), 500
    except Exception as e:
        return jsonify({'error': f'Error saving book: {e}'}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
