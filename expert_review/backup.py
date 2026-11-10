"""Read-only database backup. Restore one reviewer with `manage.py import --file`."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .io import write_json


def backup(store, output):
    """Write every stored review row to a new timestamped folder; never modifies the database."""
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target = Path(output)/f'review-backup-{stamp}'
    target.mkdir(parents=True, exist_ok=False)  # never overwrite an earlier backup
    rows = store.dump()
    files = []
    for key, text in rows:
        state = json.loads(text)
        name = state.get('reviewer') if isinstance(state.get('reviewer'), str) else ''
        name = re.sub(r'[^A-Za-z0-9_.-]', '_', name) or 'reviewer'
        # The key suffix keeps case-insensitive file systems from merging reviewers.
        path = target/'reviewers'/f'{name}__{key[:12]}.json'
        write_json(path, state)  # same format `manage.py import --file` accepts
        files.append({'reviewer_key': key, 'reviewer': state.get('reviewer'), 'file': str(path.relative_to(target)),
                      'judgments': len(state.get('judgments') or {}),
                      'stored_sha256': hashlib.sha256(text.encode()).hexdigest()})
    (target/'rows.jsonl').write_text(''.join(json.dumps({'reviewer_key': k, 'state': t}) + '\n' for k, t in rows),
                                     encoding='utf-8')
    manifest = {'created_at': datetime.now(timezone.utc).isoformat(),
                'storage': 'postgresql' if store.database_url else 'sqlite',
                'rows': len(rows), 'judgments': sum(f['judgments'] for f in files), 'files': files,
                'restore': 'python manage.py import --file <reviewers/...json> (refuses to overwrite an existing reviewer)'}
    write_json(target/'manifest.json', manifest)
    return {'output': str(target.resolve()), 'rows': len(rows), 'judgments': manifest['judgments']}


def export_all(review, output):
    """Run the standard per-reviewer export for every stored reviewer; read-only on the database."""
    import csv
    output = Path(output)
    exported, skipped, rows, folders = [], [], [], set()
    for key, text in review.store.dump():
        state = json.loads(text)
        reviewer = state.get('reviewer')
        if state.get('binding') != review.binding:
            skipped.append({'reviewer': reviewer, 'reason': 'different source binding (kept in backups)'})
            continue
        folder = reviewer if reviewer.lower() not in folders else f'{reviewer}__{key[:12]}'
        folders.add(folder.lower())
        result = review.export(reviewer, output/folder)
        exported.append(result)
        with (output/folder/'judgments.csv').open(encoding='utf-8', newline='') as stream:
            rows.extend(csv.DictReader(stream))
    fields = ['family_id','part_id','inspection_id','source_sha256','decision','grade','reason','notes',
              'observation','rationale','evidence','source','reviewer','human_review_attested','reviewed_at']
    from .io import write_csv
    write_csv(output/'all_judgments.csv', rows, fields)
    return {'reviewers': len(exported), 'decisions': len(rows), 'skipped': skipped,
            'output': str(output.resolve()), 'exports': exported}
