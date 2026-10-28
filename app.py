"""Flask entrypoint recognized directly by Vercel."""
import gzip
import json
import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, Response
from werkzeug.exceptions import HTTPException

from expert_review.review import Review, reviewer_id
from expert_review.storage import Store

ROOT = Path(__file__).resolve().parent
CSP = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'"


def stream_json(value, headers=None):
    def chunks():
        buffer, size = [], 0
        for token in json.JSONEncoder(allow_nan=False).iterencode(value):
            buffer.append(token)
            size += len(token)
            if size >= 64_000:
                yield ''.join(buffer)
                buffer, size = [], 0
        if buffer:
            yield ''.join(buffer)
    return Response(chunks(), mimetype='application/json', headers=headers)


def create_app(config=None):
    app = Flask(__name__, static_folder=None)
    app.config.update(MAX_CONTENT_LENGTH=32_000, DATABASE_URL=os.getenv('DATABASE_URL'),
                      WORKSPACE=os.getenv('REVIEW_WORKSPACE', str(ROOT/'workspace')),
                      VERCEL=os.getenv('VERCEL') == '1')
    app.config.update(config or {})
    if app.config['VERCEL'] and not app.config['DATABASE_URL']:
        raise RuntimeError('Set DATABASE_URL to a PostgreSQL connection string before deploying to Vercel.')
    review = Review(ROOT/'data', app.config['WORKSPACE'])
    review.verify_sources = not app.config['VERCEL']
    review.store = Store(app.config['DATABASE_URL'], Path(app.config['WORKSPACE'])/'reviews.sqlite3')
    app.extensions['review'] = review

    @app.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = CSP
        response.headers['Referrer-Policy'] = 'same-origin'
        return response

    @app.before_request
    def same_origin():
        origin = request.headers.get('Origin')
        if request.method == 'POST' and ((origin and origin != request.host_url.rstrip('/'))
                                       or request.headers.get('Sec-Fetch-Site') == 'cross-site'):
            return jsonify(error='Cross-origin review writes are forbidden'), 403

    @app.get('/')
    def index():
        return send_from_directory(ROOT/'public', 'index.html')

    @app.get('/<name>')
    def asset(name):
        if name not in {'app.js', 'style.css'}:
            return jsonify(error='Not found'), 404
        return send_from_directory(ROOT/'public', name)

    @app.get('/evidence/<name>')
    def evidence(name):
        # Production assets are served directly from public/ by Vercel's CDN.
        code, suffix = name.split('.', 1) if '.' in name else ('', '')
        if code not in review.bycode or suffix not in {'png', 'step.gz', 'bin.gz'}:
            return jsonify(error='Unknown evidence asset'), 404
        review.evidence(code)
        response = send_from_directory(ROOT/'public/evidence', name, mimetype='image/png' if suffix=='png' else 'application/octet-stream',
                                       as_attachment=suffix=='step.gz', download_name=code+'.step' if suffix=='step.gz' else name)
        if suffix.endswith('.gz'):
            response.headers['Content-Encoding'] = 'gzip'
        return response

    @app.get('/api/bootstrap')
    def bootstrap():
        identifier = request.args.get('reviewer')
        if identifier is not None:
            reviewer_id(identifier)
        return stream_json(review.bootstrap(identifier))

    @app.post('/api/save')
    def save():
        payload = request.get_json()
        if not isinstance(payload, dict):
            raise ValueError('Missing review decision')
        return jsonify(review.save(payload))

    @app.get('/api/export')
    def export():
        identifier = reviewer_id(request.args.get('reviewer'))
        return stream_json(review.load(identifier),
                           headers={'Content-Disposition': f'attachment; filename="{identifier}_review.json"'})

    @app.get('/api/health')
    def health():
        return jsonify(status='ok', storage='postgresql' if review.store.database_url else 'sqlite',
                       candidates=len(review.manifest), assessments=sum(map(len, review.pools.values())),
                       tasks=len(review.tasks))

    @app.errorhandler(Exception)
    def error(exc):
        if isinstance(exc, HTTPException):
            return jsonify(error=exc.description), exc.code
        if isinstance(exc, (ValueError, KeyError, TypeError)):
            return jsonify(error=str(exc)), 400
        app.logger.exception('Review request failed')
        return jsonify(error='Review storage is unavailable. Your changes have not been saved; please retry.'), 503

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.getenv('PORT', '8765')))
