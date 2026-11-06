"""Read the controller's own records without contacting the simulator."""

import argparse
import json
import sqlite3
from pathlib import Path


def explain(db, wid, since):
    return db.execute("""
        SELECT ts, kind, detail FROM audit
        WHERE workflow=? AND ts>=? AND kind IN (
            'proposal_intent','approval_decided','proposal_applied','config_changed',
            'proposal_stale','proposal_withheld','change_verification','verification_superseded',
            'prompt_incident','experiment_readout','supervisor_edit_preserved'
        )
        ORDER BY ts, id
    """, (wid, since))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path)
    parser.add_argument('workflow')
    parser.add_argument('--since', default='')
    parser.add_argument('--limit', type=int, default=40)
    args = parser.parse_args()
    with sqlite3.connect(args.database.resolve().as_uri() + '?mode=ro', uri=True) as db:
        for index, (ts, kind, raw) in enumerate(explain(db, args.workflow, args.since)):
            if index >= args.limit:
                break
            detail = json.loads(raw)
            if kind == 'proposal_intent':
                detail = {key: detail[key] for key in ('id', 'route', 'change_summary', 'rationale', 'diff',
                                                      'dry_run', 'affected_leads', 'impact_score')}
            if kind == 'proposal_applied':
                detail = {key: detail[key] for key in ('id', 'approval_id', 'action', 'version', 'applied_at')}
            print(ts, kind, json.dumps(detail, sort_keys=True))


if __name__ == '__main__':
    main()
