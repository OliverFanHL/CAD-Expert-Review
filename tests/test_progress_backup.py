"""Shared progress (counts only), persistence across instances, concurrency and read-only backup."""
import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from app import create_app
from expert_review.backup import backup, export_all
from expert_review.io import read_csv
from expert_review.io import object_hash, read_json
from expert_review.storage import Store

SECRET_NOTE = 'private-observation-7f3a'


@pytest.fixture
def app(tmp_path):
    return create_app({'TESTING': True, 'DATABASE_URL': None, 'VERCEL': False, 'WORKSPACE': str(tmp_path)})


def judgment(review, reviewer, index=0, decision='reject', fid=None):
    fid = fid or next(iter(review.pools))
    pid = review.pools[fid][index]
    return {'reviewer': reviewer, 'human_review_attested': True, 'kind': 'judgments', 'key': fid+'|'+pid,
            'record': {'family_id': fid, 'part_id': pid, 'decision': decision, 'features': {},
                       'reason': 'other', 'notes': SECRET_NOTE, 'point': None}}


def test_progress_reports_counts_but_never_labels(app):
    client = app.test_client()
    review = app.extensions['review']
    fid = next(iter(review.pools))
    for reviewer, parts in [('fixture_alpha', [0, 1, 2]), ('fixture_beta', [0])]:
        for i in parts:
            assert client.post('/api/save', json=judgment(review, reviewer, i)).status_code == 200
    # Task reviews are not CAD assessments and must not inflate progress.
    client.post('/api/save', json={'reviewer': 'fixture_gamma', 'human_review_attested': True, 'kind': 'task_reviews',
                                   'key': fid, 'record': {'decision': 'accept'}})
    response = client.get(f'/api/progress?reviewer=fixture_beta&family={fid}')
    assert response.status_code == 200
    body = response.get_json()
    assert body['total_assessments'] == 19976
    assert body['covered'] == 3 and body['reviewed_records'] == 4
    assert body['by_family'][fid] == {'total': 1816, 'covered': 3}
    pools = review.pools[fid]
    assert body['parts'] == {pools[0]: 2, pools[1]: 1, pools[2]: 1}
    assert sorted((r['label'], r['assessments'], r['you']) for r in body['reviewers']) == \
        [('Reviewer 1', 3, False), ('You', 1, True)]
    text = response.get_data(as_text=True)
    for leaked in [SECRET_NOTE, 'reject', 'fixture_alpha', 'fixture_beta', 'decision', 'notes', object_hash('fixture_alpha')]:
        assert leaked not in text
    anonymous = client.get('/api/progress').get_json()
    assert 'parts' not in anonymous and all(not r['you'] for r in anonymous['reviewers'])


def test_progress_validates_input_and_ignores_other_bindings(app):
    client = app.test_client()
    review = app.extensions['review']
    assert client.get('/api/progress?reviewer=..').status_code == 400
    assert client.get('/api/progress?family=unknown').status_code == 400
    client.post('/api/save', json=judgment(review, 'fixture_current'))
    old = review.empty_state('fixture_old')
    old['binding'] = dict(review.binding, review_dataset_id='earlier-dataset')
    old['judgments'] = {judgment(review, 'x', 5)['key']: {}}
    review.store.update('fixture_old', lambda _: old)
    body = client.get('/api/progress').get_json()
    assert body['covered'] == 1 and len(body['reviewers']) == 1


def test_progress_is_read_only(app):
    client = app.test_client()
    review = app.extensions['review']
    client.post('/api/save', json=judgment(review, 'fixture_alpha'))
    before = review.store.dump()
    for _ in range(3):
        client.get('/api/progress?reviewer=fixture_alpha&family='+next(iter(review.pools)))
    assert review.store.dump() == before


def test_reviewer_sees_only_own_results_after_restart(app):
    review = app.extensions['review']
    client = app.test_client()
    client.post('/api/save', json=judgment(review, 'fixture_alpha', 0, 'reject'))
    client.post('/api/save', json=judgment(review, 'fixture_beta', 1, 'cannot_assess'))
    restarted = create_app(dict(app.config)).test_client()  # e.g. refresh, new device, new server instance
    alpha = restarted.get('/api/bootstrap?reviewer=fixture_alpha').get_json()['state']
    assert list(alpha['judgments']) == [judgment(review, 'x', 0)['key']]
    assert alpha['judgments'][judgment(review, 'x', 0)['key']]['decision'] == 'reject'
    assert restarted.get('/api/progress?reviewer=fixture_alpha').get_json()['covered'] == 2


def run_concurrent_reviews(client_factory, review, reviewers, parts):
    jobs = [(r, i) for r in reviewers for i in range(parts)]
    def save(job):
        response = client_factory().post('/api/save', json=judgment(review, job[0], job[1]))
        assert response.status_code == 200, response.get_data(as_text=True)
    def poll(_):
        assert client_factory().get('/api/progress').status_code == 200
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(save, jobs))
        list(executor.map(poll, range(8)))


def test_simultaneous_reviewers_are_all_counted(app):
    review = app.extensions['review']
    reviewers = [f'fixture_{i}' for i in range(4)]
    instances = [app, create_app(dict(app.config))]
    counter = iter(range(10_000))
    run_concurrent_reviews(lambda: instances[next(counter) % 2].test_client(), review, reviewers, 5)
    body = app.test_client().get('/api/progress?family='+next(iter(review.pools))).get_json()
    assert body['covered'] == 5 and body['reviewed_records'] == 20
    assert set(body['parts'].values()) == {4}
    for r in reviewers:
        assert len(review.load(r)['judgments']) == 5


def test_backup_is_read_only_restorable_and_never_overwrites(app, tmp_path):
    review = app.extensions['review']
    client = app.test_client()
    client.post('/api/save', json=judgment(review, 'fixture_alpha', 0))
    client.post('/api/save', json=judgment(review, 'fixture_alpha', 1))
    client.post('/api/save', json=judgment(review, 'fixture_beta', 0))
    before = review.store.dump()
    result = backup(review.store, tmp_path/'backups')
    assert review.store.dump() == before
    assert result['rows'] == 2 and result['judgments'] == 3
    manifest = read_json(os.path.join(result['output'], 'manifest.json'))
    files = {f['reviewer']: os.path.join(result['output'], f['file']) for f in manifest['files']}
    assert read_json(files['fixture_alpha']) == review.load('fixture_alpha')
    rows = [json.loads(line) for line in open(os.path.join(result['output'], 'rows.jsonl'))]
    assert [(r['reviewer_key'], r['state']) for r in rows] == [tuple(row) for row in before]
    # Restore into an empty store with the existing non-overwriting import path.
    fresh = create_app({'TESTING': True, 'DATABASE_URL': None, 'VERCEL': False, 'WORKSPACE': str(tmp_path/'fresh')})
    restored = fresh.extensions['review']
    state = read_json(files['fixture_alpha'])
    restored.validate_state(state, 'fixture_alpha')
    def import_new(existing):
        if existing is not None:
            raise ValueError('Reviewer already exists; import will not overwrite existing work')
        return state
    restored.store.update('fixture_alpha', import_new)
    assert restored.load('fixture_alpha') == review.load('fixture_alpha')
    with pytest.raises(ValueError, match='will not overwrite'):
        restored.store.update('fixture_alpha', import_new)


def test_postgresql_progress_backup_and_concurrency(tmp_path):
    database_url = os.getenv('TEST_DATABASE_URL')
    if not database_url:
        pytest.skip('Set TEST_DATABASE_URL to test PostgreSQL (provided by CI)')
    config = {'TESTING': True, 'VERCEL': True, 'DATABASE_URL': database_url, 'WORKSPACE': str(tmp_path)}
    instances = [create_app(config) for _ in range(2)]
    review = instances[0].extensions['review']
    instances[0].test_client().get('/api/health')  # initialize the serverless store
    store = review.store
    reviewers = ['fixture_'+uuid.uuid4().hex for _ in range(3)]
    keys = {object_hash(r) for r in reviewers}
    baseline = instances[0].test_client().get('/api/progress').get_json()['reviewed_records']
    try:
        counter = iter(range(10_000))
        run_concurrent_reviews(lambda: instances[next(counter) % 2].test_client(), review, reviewers, 4)
        rows = {k: (b, sorted(j)) for k, b, j in store.progress_rows() if k in keys}
        assert len(rows) == 3 and all(b == review.binding and len(j) == 4 for b, j in rows.values())
        body = instances[1].test_client().get(f'/api/progress?reviewer={reviewers[0]}').get_json()
        assert body['reviewed_records'] == baseline + 12
        assert [r['assessments'] for r in body['reviewers'] if r['you']] == [4]
        assert SECRET_NOTE not in json.dumps(body)
        result = backup(store, tmp_path/'backups')
        dumped = {f['reviewer'] for f in read_json(os.path.join(result['output'], 'manifest.json'))['files']}
        assert set(reviewers) <= dumped
        assert_export_all_matches_downloads(instances[1], reviewers, tmp_path/'all', {r: 4 for r in reviewers})
    finally:
        with store.connection() as db:
            for k in keys:
                db.execute('DELETE FROM expert_reviews WHERE reviewer_key = %s', (k,))


def assert_export_all_matches_downloads(app, reviewers, output, expected_decisions):
    review = app.extensions['review']
    result = export_all(review, output)
    combined = read_csv(output/'all_judgments.csv')
    for r in reviewers:
        download = app.test_client().get('/api/export?reviewer='+r).get_json()  # "Download review JSON"
        assert read_json(output/r/'review.json') == download
        assert len(read_csv(output/r/'judgments.csv')) == len(download['judgments']) == expected_decisions[r]
        assert sum(row['reviewer'] == r for row in combined) == expected_decisions[r]
    return result


def test_export_all_matches_each_reviewers_download(app, tmp_path):
    import subprocess
    import sys
    review = app.extensions['review']
    client = app.test_client()
    for reviewer, parts in [('fixture_alpha', [0, 1, 2]), ('fixture_beta', [0])]:
        for i in parts:
            client.post('/api/save', json=judgment(review, reviewer, i))
    old = review.empty_state('fixture_old')
    old['binding'] = dict(review.binding, review_dataset_id='earlier-dataset')
    review.store.update('fixture_old', lambda _: old)
    before = review.store.dump()
    result = assert_export_all_matches_downloads(app, ['fixture_alpha', 'fixture_beta'], tmp_path/'all',
                                                 {'fixture_alpha': 3, 'fixture_beta': 1})
    assert result['reviewers'] == 2 and result['decisions'] == 4
    assert [s['reviewer'] for s in result['skipped']] == ['fixture_old']
    assert review.store.dump() == before
    # The coordinator CLI uses the same code path against the configured database.
    env = dict(os.environ, REVIEW_WORKSPACE=app.config['WORKSPACE'], DATABASE_URL='')
    env.pop('VERCEL', None)
    cli = subprocess.run([sys.executable, 'manage.py', 'export', '--all', '--output', str(tmp_path/'cli')],
                         cwd=os.path.dirname(os.path.dirname(__file__)), env=env, capture_output=True, text=True)
    assert cli.returncode == 0, cli.stderr
    assert json.loads(cli.stdout)['decisions'] == 4
    assert read_json(tmp_path/'cli'/'fixture_alpha'/'review.json') == review.load('fixture_alpha')
