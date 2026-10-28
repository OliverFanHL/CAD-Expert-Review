"""Local visual review, source-bound human records, exports and rater comparison.

No prediction, retrieval rank or AI judgment is read by the review interface.
Reviewer identity and human review are self-attested, not authenticated credentials.
"""
from __future__ import annotations

import json
import gzip
import hashlib
import re
import threading
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
from .io import object_hash, read_csv, read_json, sha256, write_csv, write_json

DECISIONS = {'shortlist': 2, 'conditional': 1, 'reject': 0, 'cannot_assess': None}
REASONS = {
    'features_visible': 'Required shape features are visible',
    'feature_missing': 'A required feature is visibly absent',
    'wrong_form': 'Visible form conflicts with the requested role',
    'feature_unverified': 'A required feature remains unverified',
    'views_insufficient': 'Additional views or documentation are needed',
    'other': 'Other evidence, explained in the note',
}


def reviewer_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{1,63}', value):
        raise ValueError('Use a stable reviewer ID of 2–64 letters, digits, dots, hyphens or underscores')
    return value


def now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class Review:
    def __init__(self, run, workspace, tasks=None, validation_fixture=False):
        self.run, self.workspace = Path(run).resolve(), Path(workspace).resolve()
        self.validation_fixture = validation_fixture
        self.protocol = read_json(self.run/'protocol.json')
        self.manifest = {r['part_id']: r for r in read_csv(self.run/'pool_manifest.csv')}
        self.bycode = {r['inspection_id']: r for r in self.manifest.values()}
        self.pools = read_json(self.run/'family_pools.json')
        self.tasks = read_json(tasks or ROOT/'data/review_tasks.json')['tasks']
        self.bytask = {t['family_id']: t for t in self.tasks}
        self.families = {f['family_id']: f for f in self.protocol['families']}
        if set(self.bytask) != set(self.families) or set(self.pools) != set(self.families):
            raise ValueError('Review tasks must cover exactly the frozen experiment families')
        for fid, task in self.bytask.items():
            if task['request'] != self.families[fid]['scope']:
                raise ValueError('Task request changed; freeze a new experiment before collecting new labels')
        self.knowledge_dir = self.run/'knowledge'
        self.functions = {r['function_id']: r for r in read_csv(self.knowledge_dir/'functions.csv')}
        self.priors = read_csv(self.knowledge_dir/'class_functions.csv')
        self.prior_keys = {r['class_id']+'|'+r['function_id']: r for r in self.priors}
        self.binding = {'query_sha256': self.protocol['query_sha256'], 'scope_sha256': self.protocol['scope_sha256'],
                        'task_instructions_sha256': object_hash(self.tasks),
                        'pool_manifest_sha256': sha256(self.run/'pool_manifest.csv'),
                        'rankings_sha256': sha256(self.run/'rankings.csv'),
                        'knowledge_sha256': object_hash({'functions': self.functions, 'priors': self.priors}),
                        'review_dataset_id': self.protocol['review_dataset_id'],
                        'validation_fixture': validation_fixture}
        self.lock = threading.RLock()
        self.store = None
        self.evidence_metadata = read_json(self.run/'evidence.json')
        self.source_root = ROOT/'public/evidence'
        self.verify_sources = True
        self.checked_sources = {}

    def path(self, reviewer):
        identifier = reviewer_id(reviewer)
        # A digest also avoids Windows device names and case-folding collisions.
        return self.workspace/'reviewers'/(object_hash(identifier)+'.json')

    def load(self, reviewer):
        reviewer_id(reviewer)
        if self.store is not None:
            state = self.store.load(reviewer)
            if state is not None:
                return self.validate_state(state, reviewer)
        target = self.path(reviewer)
        if self.store is None and target.exists():
            state = read_json(target)
            if state['binding'] != self.binding or state['reviewer'] != reviewer:
                raise ValueError('Review belongs to different source inputs or instructions')
            return state
        return self.empty_state(reviewer)

    def empty_state(self, reviewer):
        return {'schema_version': 1, 'source': 'validation_fixture' if self.validation_fixture else 'independent_expert', 'reviewer': reviewer,
                'human_review_attested': False, 'binding': self.binding, 'run': str(self.run),
                'task_reviews': {}, 'knowledge_reviews': {}, 'judgments': {}, 'history': []}

    def validate_state(self, state, reviewer):
        if state['binding'] != self.binding or state['reviewer'] != reviewer:
            raise ValueError('Review belongs to different source inputs or instructions')
        return state

    def check_source(self, pid):
        item = self.manifest[pid]
        path = self.source_root/(item['inspection_id']+'.step.gz')
        # Production source bytes are verified at build time and served by the CDN.
        if self.verify_sources:
            with self.lock:
                stat = path.stat()
                signature = (stat.st_mtime_ns, stat.st_size)
                if self.checked_sources.get(pid) != signature:
                    if hashlib.sha256(gzip.decompress(path.read_bytes())).hexdigest() != item['source_sha256']:
                        raise ValueError('Original STEP changed; stop review and rebuild evidence')
                    self.checked_sources[pid] = signature
        return path

    def evidence(self, code):
        if code not in self.bycode:
            raise ValueError('Unknown neutral CAD ID')
        item = self.bycode[code]
        self.check_source(item['part_id'])
        data = self.evidence_metadata[code]
        if data['part_id'] != item['part_id'] or data['source_sha256'] != item['source_sha256']:
            raise ValueError('Rendered evidence is not bound to the original STEP')
        return item

    def bootstrap(self, reviewer=None):
        state = self.load(reviewer) if reviewer else None
        return {'tasks': self.tasks, 'reasons': REASONS, 'state': state,
                'parts': [{'family_id': fid, 'part_id': pid, 'inspection_id': self.manifest[pid]['inspection_id']}
                          for fid, ids in self.pools.items() for pid in sorted(ids, key=lambda x: object_hash((fid,x)))],
                'knowledge': [{'key': key, **r, 'function_label': r['function_id'].replace('_',' ')}
                              for key,r in self.prior_keys.items()]}

    def save(self, payload):
        reviewer = reviewer_id(payload.get('reviewer'))
        if payload.get('human_review_attested') is not True:
            raise ValueError('Confirm that these are your own human review decisions')
        kind, key = payload.get('kind'), payload.get('key')
        record = payload.get('record')
        if not isinstance(record, dict):
            raise ValueError('Missing review decision')
        notes = record.get('notes', '').strip()
        if len(notes) > 4000:
            raise ValueError('Please keep the review note under 4,000 characters')
        if kind in {'task_reviews', 'knowledge_reviews'}:
            allowed = self.bytask if kind == 'task_reviews' else self.prior_keys
            if key not in allowed or record.get('decision') not in {'accept','request_change','reject','cannot_assess'}:
                raise ValueError('Unknown task/prior or review decision')
            if record['decision'] != 'accept' and not notes:
                raise ValueError('Explain the change, rejection or missing evidence')
            cleaned = {'decision': record['decision'], 'notes': notes}
        elif kind == 'judgments':
            fid, pid = record.get('family_id'), record.get('part_id')
            if fid not in self.pools or pid not in self.pools[fid] or key != fid+'|'+pid:
                raise ValueError('Part does not belong to this task pool')
            decision, reason = record.get('decision'), record.get('reason')
            if decision not in DECISIONS or reason not in REASONS:
                raise ValueError('Choose a shortlist decision and an evidence reason')
            features = record.get('features', {})
            expected = {f['id'] for f in self.bytask[fid]['features']}
            if set(features) - expected or any(v not in {'present','absent','unclear'} for v in features.values()):
                raise ValueError('Invalid feature observation')
            if decision != 'cannot_assess' and not features and not notes:
                raise ValueError('Record visible feature evidence or a specific observation')
            if decision == 'shortlist' and (set(features) != expected or any(v != 'present' for v in features.values())):
                raise ValueError('For Shortlist, confirm all required visible features; use Conditional if one is unclear')
            if reason in {'other','wrong_form'} and not notes:
                raise ValueError('Add a short description of the visible evidence')
            item = self.evidence(self.manifest[pid]['inspection_id'])
            point = record.get('point')
            if point is not None and (not isinstance(point, list) or len(point)!=3 or
                                      any(type(v) not in {int,float} or not np.isfinite(v) or abs(v)>2 for v in point)):
                raise ValueError('Invalid optional surface marker')
            labels = {f['id']: f['label'] for f in self.bytask[fid]['features']}
            cleaned = {'family_id':fid, 'part_id':pid, 'inspection_id':item['inspection_id'],
                       'source_sha256':item['source_sha256'], 'decision':decision, 'grade':DECISIONS[decision],
                       'features':features, 'reason':reason, 'notes':notes, 'point':point,
                       'observation': '; '.join(labels[k]+': '+v for k,v in features.items()) or notes or REASONS[reason],
                       'rationale': REASONS[reason]+('. '+notes if notes else ''),
                       'evidence':f"source STEP and evidence/{item['inspection_id']}.png",
                       'source':'validation_fixture' if self.validation_fixture else 'independent_expert',
                       'reviewer':reviewer, 'human_review_attested':not self.validation_fixture}
        else:
            raise ValueError('Unknown review section')
        cleaned['reviewed_at'] = now()
        def update(state):
            state = self.validate_state(state, reviewer) if state is not None else self.empty_state(reviewer)
            previous = state[kind].get(key)
            state['history'].append({'kind':kind,'key':key,'previous':previous,'saved_at':cleaned['reviewed_at']})
            state[kind][key] = cleaned
            state['human_review_attested'] = not self.validation_fixture
            return state
        if self.store is not None:
            self.store.update(reviewer, update)
        else:
            with self.lock:
                state = update(self.load(reviewer))
                target = self.path(reviewer)
                temporary = target.with_suffix('.tmp')
                write_json(temporary, state)
                temporary.replace(target)
        return {'saved': True, 'record': cleaned}

    def export(self, reviewer, output):
        state = self.load(reviewer)
        output = Path(output)
        write_json(output/'review.json', state)
        rows = list(state['judgments'].values())
        write_csv(output/'judgments.csv', [{k:v for k,v in r.items() if k not in {'features','point'}} for r in rows],
                  ['family_id','part_id','inspection_id','source_sha256','decision','grade','reason','notes',
                   'observation','rationale','evidence','source','reviewer','human_review_attested','reviewed_at'])
        write_json(output/'task_reviews.json', state['task_reviews'])
        write_json(output/'knowledge_reviews.json', state['knowledge_reviews'])
        # Only accepted generic priors are exported. Evaluation labels never enter this directory.
        functions, priors = {}, []
        for key,r in state['knowledge_reviews'].items():
            if r['decision'] != 'accept' or self.validation_fixture:
                continue
            prior = self.prior_keys[key]
            fid = prior['function_id']
            functions[fid] = {**self.functions[fid], 'status':'curated', 'reviewer':reviewer}
            priors.append({**prior, 'status':'curated', 'reviewer':reviewer})
        write_csv(output/'knowledge/functions.csv', list(functions.values()), list(next(iter(self.functions.values())).keys()))
        write_csv(output/'knowledge/class_functions.csv', priors, list(self.priors[0].keys()))
        write_csv(output/'knowledge/interfaces.csv', [], ['part_id','interface_id','role','diameter_mm','min_mm','max_mm','unit','reviewer','evidence','status'])
        return {'reviewer':reviewer,'decisions':len(rows),'cannot_assess':sum(r['grade'] is None for r in rows),
                'accepted_priors':len(priors),'output':str(output.resolve())}


def agreement(review, reviewers, output):
    a,b = [review.load(r)['judgments'] for r in reviewers]
    common = sorted(set(a)&set(b))
    valid = [k for k in common if a[k]['grade'] is not None and b[k]['grade'] is not None]
    counts = np.zeros((3,3),dtype=int)
    for key in valid:
        counts[a[key]['grade'],b[key]['grade']] += 1
    n=int(counts.sum())
    weights=np.square(np.arange(3)[:,None]-np.arange(3)[None,:])/4
    expected=np.outer(counts.sum(1),counts.sum(0))/n if n else np.zeros((3,3))
    denom=float((weights*expected).sum())
    result={'reviewers':reviewers,'common_records':len(common),'both_assessable':n,
            'cannot_assess_in_either':len(common)-n,'agreement':float(np.trace(counts)/n) if n else None,
            'quadratic_weighted_kappa':1-float((weights*counts).sum())/denom if denom else None,
            'confusion_matrix_grade012':counts.tolist(),
            'interpretation':'Descriptive overlap only; unresolved cases excluded from kappa, not coded as rejection.'}
    write_json(Path(output)/'agreement.json',result)
    rows=[{'key':k,'family_id':a[k]['family_id'],'inspection_id':a[k]['inspection_id'],
           'reviewer_a_decision':a[k]['decision'],'reviewer_b_decision':b[k]['decision'],
           'reviewer_a_reason':a[k]['rationale'],'reviewer_b_reason':b[k]['rationale']}
          for k in common if a[k]['decision']!=b[k]['decision'] or a[k]['grade'] is None]
    write_csv(Path(output)/'disagreements.csv',rows,['key','family_id','inspection_id','reviewer_a_decision','reviewer_b_decision','reviewer_a_reason','reviewer_b_reason'])
    return result

