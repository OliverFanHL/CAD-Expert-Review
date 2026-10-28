"""Verify every frozen input and static evidence asset before deployment."""
import json
import gzip
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from expert_review.io import read_json, sha256
from expert_review.review import Review


def verify(root=ROOT):
    for manifest_name in ['data.sha256.json', 'assets.sha256.json']:
        manifest = read_json(root/'data'/manifest_name)
        for name, expected in manifest.items():
            path = (root/name).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file() or sha256(path) != expected:
                raise ValueError(f'Missing or changed frozen input: {name}')
    review = Review(root/'data', root/'workspace')
    review.source_root = root/'public/evidence'
    if set(review.manifest) != set().union(*map(set, review.pools.values())):
        raise ValueError('Candidate pools and source manifest differ')
    assets = read_json(root/'data/assets.sha256.json')
    for row in review.manifest.values():
        code = row['inspection_id']
        review.evidence(code)
        if hashlib.sha256(gzip.decompress((root/'public/evidence'/f'{code}.step.gz').read_bytes())).hexdigest() != row['source_sha256']:
            raise ValueError(f'Original STEP binding changed: {code}')
        mesh = gzip.decompress((root/'public/evidence'/f'{code}.bin.gz').read_bytes())
        if len(mesh) == 0 or len(mesh) % 36 or len(mesh) != review.evidence_metadata[code]['mesh_bytes']:
            raise ValueError(f'Invalid normalized triangle data: {code}')
        if (root/'public/evidence'/f'{code}.png').read_bytes()[:8] != b'\x89PNG\r\n\x1a\n':
            raise ValueError(f'Invalid source views: {code}')
    print(json.dumps({'verified': True, 'source_CADs': len(review.manifest),
                      'assessments': sum(map(len, review.pools.values())), 'tasks': len(review.tasks),
                      'knowledge_priors': len(review.priors), 'binding': review.binding}, indent=2))


if __name__ == '__main__':
    verify()
