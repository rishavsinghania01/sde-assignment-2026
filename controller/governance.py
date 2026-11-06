import json
import os
import signal
from datetime import datetime, timedelta
from uuid import uuid4

from .learning import normalized


def route_for(policy, current, proposed, dimension):
    auto = policy['auto_apply']
    if dimension != 'caller_id' or not auto['enabled'] or dimension not in auto['allowed_dims']:
        return 'approval'
    old, new = current['allocations'], proposed['allocations']
    for cohort in set(old) | set(new):
        before = normalized(old.get(cohort, {}).get(dimension, old['default'][dimension]))
        after = normalized(new.get(cohort, {}).get(dimension, new['default'][dimension]))
        shift = sum(abs(before.get(v, 0) - after.get(v, 0)) for v in before.keys() | after.keys()) / 2
        if shift > auto['max_shift'] + 1e-9:
            return 'approval'
    return 'auto'


class Governance:
    def __init__(self, store, api):
        self.store = store
        self.api = api
        self.before_apply = None

    def active(self, wid):
        return self.store.db.execute(
            "SELECT * FROM proposals WHERE workflow=? AND state IN ('intent','pending','approved') "
            "ORDER BY rowid DESC LIMIT 1", (wid,)
        ).fetchone()

    def available(self, workflow, ts):
        wid = workflow['workflow_id']
        policy = workflow['governance']
        now = datetime.fromisoformat(ts)
        opening, closing = policy['approver_hours']
        limit = policy['max_requests_per_24h']
        if workflow['tenant_id'] == 'kestrel_finance':
            opening = max(11, opening)
            limit = min(2, limit)
        if not opening <= now.hour < closing or limit <= 0:
            return False
        expiry = now + timedelta(hours=policy['proposal_ttl_hours'])
        # Avoid requests that cannot receive even the fastest response before close or expiry.
        close = now.replace(hour=0, minute=0, second=0) + timedelta(hours=closing)
        earliest = now + timedelta(minutes=policy['approver_latency_minutes'][0])
        if earliest >= min(close, expiry):
            return False
        earliest_counted = (now - timedelta(hours=24)).isoformat()
        count, last = self.store.db.execute(
            "SELECT COUNT(*), MAX(ts) FROM proposals WHERE workflow=? AND route='approval' "
            "AND ts>=? AND (approval_id IS NOT NULL OR state='intent')",
            (wid, earliest_counted)
        ).fetchone()
        rejected = self.store.db.execute(
            "SELECT MAX(updated) FROM proposals WHERE workflow=? AND state='rejected'", (wid,)
        ).fetchone()[0]
        return (count < limit
                and (last is None or now - datetime.fromisoformat(last) >= timedelta(hours=2))
                and (rejected is None or now - datetime.fromisoformat(rejected) >= timedelta(hours=12)))

    def propose(self, workflow, current, ts, plan):
        wid = workflow['workflow_id']
        config = plan['config']
        route = route_for(workflow['governance'], current['config'], config, plan['dimension'])
        if route == 'approval' and not self.available(workflow, ts):
            return
        pid = uuid4().hex
        body = {
            'proposal_id': pid,
            'workflow_id': wid,
            'base_version': current['version'],
            'proposed_config': config,
            'change_summary': plan['summary'],
            'diff': plan['diff'],
            'affected_leads': plan['affected'],
            'dry_run': plan['evidence'],
            'impact_score': plan['impact'],
            'rationale': plan['rationale'],
        }
        if 'validation_run_id' in plan['evidence']:
            body['evidence'] = {'validation_run_id': plan['evidence']['validation_run_id']}
        with self.store.db:
            self.store.db.execute('INSERT INTO proposals VALUES (?,?,?,?,?,?,?,?,?,?)', (
                pid, wid, ts, route, 'intent', json.dumps(body), json.dumps(plan), None, None, ts
            ))
            self.store.audit(wid, ts, 'proposal_intent', {
                'id': pid, 'route': route, 'action': plan['action'], **body,
            })
        self.reconcile(self.active(wid), ts)

    def transition(self, row, ts, status, response):
        aid = response.get('approval_id') or row['approval_id']
        with self.store.db:
            self.store.db.execute(
                'UPDATE proposals SET state=?, approval_id=?, updated=? WHERE id=?',
                (status, aid, ts, row['id'])
            )
            if status != row['state']:
                self.store.audit(row['workflow'], ts, 'proposal_' + status, {
                    'id': row['id'], 'approval_id': aid, 'response': response,
                })

    def reconcile(self, row, ts, finishing=False):
        wid, pid = row['workflow'], row['id']
        body = json.loads(row['body'])
        if row['route'] == 'auto':
            changes = self.api.get(f'/workflows/{wid}/config/history')
            applied = next((change for change in changes if change.get('proposal_id') == pid), None)
            if applied:
                self.applied(row, ts, applied)
                return
            if finishing:
                self.transition(row, ts, 'scenario_ended', {})
                return
            status, response = self.api.mutate('PUT', f'/workflows/{wid}/config', body)
            if status == 200:
                self.applied(row, ts, response)
            else:
                self.failed(row, ts, response)
            return

        if row['approval_id']:
            approval = self.api.get(f"/approvals/{row['approval_id']}")
        else:
            approvals = self.api.get('/approvals', workflow_id=wid)
            approval = next((item for item in approvals if item['proposal_id'] == pid), None)
            if approval is None:
                if finishing:
                    self.transition(row, ts, 'scenario_ended', {})
                    return
                status, approval = self.api.mutate('POST', '/approvals', body)
                if status != 200:
                    if approval.get('error') == 'duplicate_proposal_id':
                        raise RuntimeError(f'Approval {pid} is missing from the reconciliation list')
                    self.failed(row, ts, approval)
                    return
                if os.getenv('CONTROLLER_TEST_KILL') == 'after_approval_post':
                    os.kill(os.getpid(), signal.SIGKILL)
        status = approval['status']
        if status == 'applied':
            change = next(item for item in self.api.get(f'/workflows/{wid}/config/history')
                          if item.get('proposal_id') == pid or
                          item.get('approval_id') == approval['approval_id'])
            self.applied(row, ts, {**approval, **change})
        elif status == 'approved':
            if finishing:
                self.transition(row, ts, 'scenario_ended', approval)
                return
            self.transition(row, ts, status, approval)
            row = self.active(wid)
            if self.api.get(f'/workflows/{wid}/config')['version'] != body['base_version']:
                self.transition(row, ts, 'stale', approval)
                return
            if self.before_apply and not self.before_apply(wid, body, json.loads(row['plan']), ts):
                self.transition(row, ts, 'withheld', {**approval, 'reason': 'new safety evidence'})
                return
            code, response = self.api.mutate('POST', f'/workflows/{wid}/apply',
                                             {'approval_id': approval['approval_id']})
            if code == 200:
                self.applied(row, ts, {**approval, **response})
            else:
                self.failed(row, ts, response, code)
        else:
            self.transition(row, ts, status, approval)

    def failed(self, row, ts, response, status_code=None):
        state = {'stale_base_version': 'stale', 'approval_lapsed': 'lapsed'}.get(
            response.get('error'), 'api_rejected'
        )
        self.transition(row, ts, 'lapsed' if status_code == 410 else state, response)

    def applied(self, row, ts, response):
        wid, pid = row['workflow'], row['id']
        aid = response.get('approval_id') or row['approval_id']
        version = response.get('version')
        if version is None:
            change = next(item for item in self.api.get(f'/workflows/{wid}/config/history')
                          if item.get('proposal_id') == pid or (aid and item.get('approval_id') == aid))
            version = change['version']
            response = {**response, **change}
        plan = json.loads(row['plan'])
        applied_at = response.get('applied_at') or ts
        action = plan['action']
        with self.store.db:
            self.store.db.execute(
                "UPDATE proposals SET state='applied', approval_id=?, applied_version=?, updated=? WHERE id=?",
                (aid, version, ts, pid)
            )
            self.store.audit(wid, ts, 'proposal_applied', {
                'id': pid, 'approval_id': aid, 'action': action, 'version': version,
                'applied_at': applied_at, 'response': response,
            })
            if action in ('experiment', 'promote'):
                self.store.set(wid, 'experiment', {
                    **plan['experiment'], 'phase': action, 'version': version, 'started': applied_at,
                    'proposal_id': pid,
                })
            if action in ('end_experiment', 'rollback'):
                self.store.set(wid, 'experiment', None)
            if action.startswith('caller_') or action == 'prompt_fix':
                self.store.set(wid, 'verify_' + plan['dimension'], {
                    'plan': plan, 'version': version, 'started': applied_at, 'proposal_id': pid,
                })
                trial = self.store.get(wid, 'experiment')
                if trial:
                    self.store.set(wid, 'experiment', {**trial, 'version': version, 'started': applied_at})
