"""LeadFlow cloud server. Existing local SQLite files are never opened."""
import hmac
import json
import logging
import os
import re
import time
from collections import deque
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

import requests
from flask import Flask, jsonify, request, send_file

BASE = Path(__file__).resolve().parent
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 8192
logging.basicConfig(level=logging.INFO)
ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', '')
SUPABASE_URL = os.environ.get('SUPABASE_URL', '').rstrip('/')
SUPABASE_KEY = os.environ.get('SUPABASE_SECRET_KEY') or os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
parsed = urlsplit(SUPABASE_URL)
if parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.supabase.co') or parsed.path or parsed.query or parsed.fragment or parsed.username:
    raise RuntimeError('Set SUPABASE_URL to the HTTPS project base URL, without /rest/v1/.')
if not SUPABASE_KEY or SUPABASE_KEY.startswith('sb_publishable_'):
    raise RuntimeError('Set a server-only Supabase secret or legacy service_role key.')
if len(ADMIN_TOKEN) < 24 or not ADMIN_TOKEN.isascii():
    raise RuntimeError('ADMIN_TOKEN must contain at least 24 ASCII characters.')
STATUSES = ('new', 'contacted', 'converted', 'lost')
rate_lock = Lock()
recent_requests = {'public': deque(), 'admin': deque()}


def database(method, query='', payload=None):
    headers = {'apikey': SUPABASE_KEY, 'Content-Type': 'application/json', 'Prefer': 'return=representation'}
    if not SUPABASE_KEY.startswith('sb_secret_'):
        headers['Authorization'] = 'Bearer ' + SUPABASE_KEY
    try:
        response = requests.request(method, SUPABASE_URL + '/rest/v1/leadflow_leads' + query,
                                    headers=headers, json=payload, timeout=(5, 20), allow_redirects=False)
        if not 200 <= response.status_code < 300:
            # Never log secrets, customer fields, or upstream response bodies.
            app.logger.error('Database request failed: status %s', response.status_code)
            raise RuntimeError('database unavailable')
        rows = response.json()
        if not isinstance(rows, list):
            raise RuntimeError('database returned invalid data')
        return rows
    except (requests.RequestException, ValueError) as exc:
        app.logger.error('Database connection or response failed: %s', type(exc).__name__)
        raise RuntimeError('database unavailable') from None


@app.before_request
def limit_requests():
    if request.path.startswith('/api/'):
        bucket = 'public' if request.method == 'POST' else 'admin'
        cap = 30 if bucket == 'public' else 120
        now = time.monotonic()
        # Process-wide cap, independent of untrusted proxy/IP headers.
        with rate_lock:
            queue = recent_requests[bucket]
            while queue and queue[0] < now - 60:
                queue.popleft()
            if len(queue) >= cap:
                return jsonify(error='Too many requests. Please wait one minute.'), 429, {'Retry-After': '60'}
            queue.append(now)


@app.after_request
def security_headers(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response


def authorized():
    supplied = request.headers.get('X-Admin-Token', '')
    return supplied.isascii() and hmac.compare_digest(supplied, ADMIN_TOKEN)


@app.get('/')
def home():
    return send_file(BASE / 'index.html')


@app.get('/dashboard')
@app.get('/dashboard/')
@app.get('/dashboard.html')
def dashboard():
    # HTML contains no lead data; the API enforces authentication.
    return send_file(BASE / 'dashboard.html')


@app.get('/health')
def health():
    return jsonify(ok=True)


@app.get('/api/leads')
def list_leads():
    if not authorized():
        return jsonify(error='Access denied. Check your admin token.'), 403
    return jsonify(leads=database('GET', '?select=*&order=id.desc&limit=500'))


@app.post('/api/leads')
def create_lead():
    if not request.is_json:
        return jsonify(error='Send a JSON inquiry.'), 400
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or data.get('consent') is not True:
        return jsonify(error='Please provide valid fields and consent.'), 400
    cleaned = {}
    for key, limit in [('name', 100), ('email', 254), ('phone', 30), ('company', 120), ('message', 1500)]:
        value = data.get(key, '')
        if not isinstance(value, str) or len(value) > limit or '\x00' in value:
            return jsonify(error='Please check your inquiry fields.'), 400
        cleaned[key] = value.strip()
    if not cleaned['name'] or not cleaned['message'] or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', cleaned['email']):
        return jsonify(error='Enter a name, valid email and requirement.'), 400
    if data.get('website'):
        return jsonify(error='Unable to submit this inquiry.'), 400
    cleaned['consent'] = True
    rows = database('POST', payload=cleaned)
    if not rows or 'id' not in rows[0]:
        raise RuntimeError('database returned no saved inquiry')
    return jsonify(ok=True, id=rows[0]['id']), 201


@app.patch('/api/leads/<int:lead_id>/status')
def update_status(lead_id):
    if not authorized():
        return jsonify(error='Access denied.'), 403
    data = request.get_json(silent=True)
    if lead_id < 1 or not isinstance(data, dict) or data.get('status') not in STATUSES:
        return jsonify(error='Invalid status.'), 400
    rows = database('PATCH', '?id=eq.' + str(lead_id), {'status': data['status']})
    if not rows:
        return jsonify(error='Lead not found.'), 404
    return jsonify(ok=True)


@app.errorhandler(RuntimeError)
def database_error(exc):
    return jsonify(error='Database unavailable. Please try again later.'), 503


@app.errorhandler(413)
def too_large(exc):
    return jsonify(error='Inquiry is too large.'), 413


@app.errorhandler(404)
def not_found(exc):
    return jsonify(error='Not found.'), 404


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '8000')), debug=False)
