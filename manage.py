"""Export, compare and import source-bound reviews without the research repository."""
import argparse
import json
from pathlib import Path

from app import app
from expert_review.backup import backup, export_all
from expert_review.io import read_json
from expert_review.review import agreement, reviewer_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    export = commands.add_parser('export')
    who = export.add_mutually_exclusive_group(required=True)
    who.add_argument('--reviewer')
    who.add_argument('--all', action='store_true', help='Export every reviewer stored in the database')
    export.add_argument('--output', required=True)
    compare = commands.add_parser('compare')
    compare.add_argument('--reviewers', nargs=2, required=True)
    compare.add_argument('--output', required=True)
    load = commands.add_parser('import')
    load.add_argument('--file', required=True, help='An existing original or standalone review JSON export')
    save_all = commands.add_parser('backup', help='Read-only snapshot of every reviewer row')
    save_all.add_argument('--output', required=True)
    args = parser.parse_args()
    review = app.extensions['review']
    if args.command == 'export' and args.all:
        result = export_all(review, args.output)
    elif args.command == 'export':
        result = review.export(reviewer_id(args.reviewer), args.output)
    elif args.command == 'compare':
        result = agreement(review, [reviewer_id(r) for r in args.reviewers], args.output)
    elif args.command == 'backup':
        result = backup(review.store, args.output)
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
