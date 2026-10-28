import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import ROOT, create_app
from expert_review.io import read_csv, read_json
from expert_review.review import agreement
from expert_review.storage import Store


@pytest.fixture
def app(tmp_path):
    return create_app({'TESTING': True, 'DATABASE_URL': None, 'VERCEL': False, 'WORKSPACE': str(tmp_path)})


def payload(review, decision='shortlist', reviewer='fixture_expert'):
    fid = next(iter(review.pools))
    pid = review.pools[fid][0]
    features = {f['id']: 'present' for f in review.bytask[fid]['features']}
    return {'reviewer': reviewer, 'human_review_attested': True, 'kind': 'judgments', 'key': fid+'|'+pid,
            'record': {'family_id': fid, 'part_id': pid, 'decision': decision,
                       'features': features, 'reason': 'features_visible', 'notes': '', 'point': None}}


def test_queue_and_neutral_assets(app):
    client = app.test_client()
    data = client.get('/api/bootstrap').get_json()
    assert len(data['tasks']) == 11 and len(data['parts']) == 19976 and len(data['knowledge']) == 11
    assert len({p['part_id'] for p in data['parts']}) == 1816
    assert data['state'] is None
    assert set(data['parts'][0]) == {'family_id', 'part_id', 'inspection_id'}
    for route in ['/', '/app.js', '/style.css', '/evidence/Z0001.png', '/evidence/Z0001.bin.gz', '/evidence/Z0001.step.gz']:
        response = client.get(route)
        assert response.status_code == 200, route
        assert 'nosniff' == response.headers['X-Content-Type-Options']
    assert client.get('/evidence/Z9999.step.gz').status_code == 404
    assert client.get('/data/rankings.csv').status_code == 404


def test_compressed_mesh_and_source_decode(app):
    import gzip
    import hashlib
    review = app.extensions['review']
    for extension in ['bin', 'step']:
        response = app.test_client().get('/evidence/Z0001.'+extension+'.gz')
        assert response.headers['Content-Encoding'] == 'gzip'
        content = gzip.decompress(response.data)
        if extension == 'step':
            assert hashlib.sha256(content).hexdigest() == review.bycode['Z0001']['source_sha256']
        else:
            assert len(content) == review.evidence_metadata['Z0001']['mesh_bytes']


def test_large_workspace_and_export_use_streaming(app):
    review = app.extensions['review']
    state = review.empty_state('fixture_large')
    state['judgments'] = {str(i): {'notes':'x'*4000} for i in range(1300)}
    review.store.update('fixture_large', lambda _: state)
    for url in ['/api/bootstrap?reviewer=fixture_large', '/api/export?reviewer=fixture_large']:
        response = app.test_client().get(url)
        assert response.is_streamed
        assert 'Content-Length' not in response.headers
        assert len(response.data) > 4_500_000
        value = response.get_json()
        assert len(value.get('state',value)['judgments']) == 1300


def test_source_changes_block_saving(app, tmp_path):
    import gzip
    review = app.extensions['review']
    p = payload(review)
    row = review.manifest[p['record']['part_id']]
    review.source_root = tmp_path
    (tmp_path/(row['inspection_id']+'.step.gz')).write_bytes(gzip.compress(b'changed source'))
    with pytest.raises(ValueError, match='Original STEP changed'):
        review.save(p)


def test_save_revise_resume_and_download(app):
    client = app.test_client()
    review = app.extensions['review']
    p = payload(review, 'cannot_assess')
    assert client.post('/api/save', json=p).get_json()['record']['grade'] is None
    p['record']['decision'] = 'reject'
    assert client.post('/api/save', json=p).get_json()['record']['grade'] == 0
    restarted = create_app(dict(app.config))
    state = restarted.test_client().get('/api/bootstrap?reviewer=fixture_expert').get_json()['state']
    assert state['judgments'][p['key']]['decision'] == 'reject'
    assert state['history'][-1]['previous']['grade'] is None
    exported = restarted.test_client().get('/api/export?reviewer=fixture_expert')
    assert exported.get_json() == state
    assert 'attachment;' in exported.headers['Content-Disposition']
    assert state['binding'] == review.binding


@pytest.mark.parametrize('mutate', [
    lambda p: p.update(human_review_attested=False),
    lambda p: p.update(reviewer='../reviewer'),
    lambda p: p['record'].update(features={}),
    lambda p: p['record'].update(reason='unknown'),
    lambda p: p['record'].update(point=[float('nan'), 0, 0]),
    lambda p: p['record'].update(notes='x'*4001),
    lambda p: p['record'].update(part_id='not_in_pool'),
])
def test_invalid_decisions_never_save(app, mutate):
    p = payload(app.extensions['review'])
    mutate(p)
    assert app.test_client().post('/api/save', json=p).status_code == 400
    assert app.extensions['review'].load('fixture_expert')['judgments'] == {}


def test_task_and_knowledge_export_stay_separate(app, tmp_path):
    client = app.test_client()
    review = app.extensions['review']
    p = payload(review)
    assert client.post('/api/save', json=p).status_code == 200
    for kind, key in [('task_reviews', p['record']['family_id']), ('knowledge_reviews', next(iter(review.prior_keys)))]:
        body = dict(p, kind=kind, key=key, record={'decision': 'request_change', 'notes': ''})
        assert client.post('/api/save', json=body).status_code == 400
        body['record'] = {'decision': 'accept'}
        assert client.post('/api/save', json=body).status_code == 200
    output = tmp_path/'export'
    assert review.export('fixture_expert', output)['accepted_priors'] == 1
    assert len(read_csv(output/'judgments.csv')) == 1
    assert len(read_csv(output/'knowledge/class_functions.csv')) == 1
    assert not (output/'knowledge/judgments.csv').exists()
    assert read_json(output/'review.json')['task_reviews']


def test_changed_binding_blocks_resume_and_save(app):
    review = app.extensions['review']
    p = payload(review)
    review.save(p)
    review.binding = dict(review.binding, query_sha256='changed')
    with pytest.raises(ValueError, match='different source inputs'):
        review.load('fixture_expert')
    with pytest.raises(ValueError, match='different source inputs'):
        review.save(p)


def test_unknown_excluded_from_agreement(app, tmp_path):
    review = app.extensions['review']
    review.save(payload(review, 'cannot_assess', 'fixture_a'))
    review.save(payload(review, 'reject', 'fixture_b'))
    result = agreement(review, ['fixture_a', 'fixture_b'], tmp_path/'agreement')
    assert result['common_records'] == 1 and result['both_assessable'] == 0
    assert result['quadratic_weighted_kappa'] is None


def test_requests_and_production_storage_guard(app, tmp_path):
    client = app.test_client()
    p = payload(app.extensions['review'])
    assert client.post('/api/save', json=p, headers={'Origin': 'https://other.example'}).status_code == 403
    assert client.post('/api/save', data='{}', content_type='text/plain').status_code == 415
    assert client.post('/api/save', data='x'*33_000, content_type='application/json').status_code == 413
    assert client.get('/api/bootstrap?reviewer=..').status_code == 400
    with pytest.raises(RuntimeError, match='DATABASE_URL'):
        create_app({'VERCEL': True, 'DATABASE_URL': None, 'WORKSPACE': str(tmp_path)})


@pytest.mark.parametrize('backend', ['sqlite', 'postgresql'])
def test_concurrent_instances_preserve_history(tmp_path, backend):
    database_url = os.getenv('TEST_DATABASE_URL') if backend == 'postgresql' else None
    if backend == 'postgresql' and not database_url:
        pytest.skip('Set TEST_DATABASE_URL to test PostgreSQL (provided by CI)')
    stores = [Store(database_url, tmp_path/'concurrent.sqlite3') for _ in range(2)]
    identifier = 'fixture_'+uuid.uuid4().hex
    def update(i):
        def change(state):
            state = state or {'history': []}
            state['history'].append(i)
            return state
        stores[i % 2].update(identifier, change)
    try:
        with ThreadPoolExecutor(max_workers=6) as executor:
            list(executor.map(update, range(24)))
        assert sorted(stores[0].load(identifier)['history']) == list(range(24))
    finally:
        if database_url:
            from expert_review.io import object_hash
            with stores[0].connection() as db:
                db.execute('DELETE FROM expert_reviews WHERE reviewer_key = %s', (object_hash(identifier),))
