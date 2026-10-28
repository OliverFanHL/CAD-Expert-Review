"""Export, compare and import source-bound reviews without the research repository."""
import argparse
import json
from pathlib import Path

from app import app
from expert_review.io import read_json
from expert_review.review import agreement, reviewer_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    export = commands.add_parser('export')
    export.add_argument('--reviewer', required=True)
    export.add_argument('--output', required=True)
    compare = commands.add_parser('compare')
    compare.add_argument('--reviewers', nargs=2, required=True)
    compare.add_argument('--output', required=True)
    load = commands.add_parser('import')
    load.add_argument('--file', required=True, help='An existing original or standalone review JSON export')
    args = parser.parse_args()
    review = app.extensions['review']
    if args.command == 'export':
        result = review.export(reviewer_id(args.reviewer), args.output)
    elif args.command == 'compare':
        result = agreement(review, [reviewer_id(r) for r in args.reviewers], args.output)
    else:
        state = read_json(Path(args.file))
        identifier = reviewer_id(state.get('reviewer'))
        review.validate_state(state, identifier)
        if state.get('source') != 'independent_expert':
            raise ValueError('Only genuine independent expert exports may be imported')
        def import_new(existing):
            if existing is not None:
                raise ValueError('Reviewer already exists; import will not overwrite existing work')
            return state
        review.store.update(identifier, import_new)
        result = {'imported': identifier, 'decisions': len(state['judgments'])}
    print(json.dumps(result, indent=2))


if __name__ == '__main__': main()
