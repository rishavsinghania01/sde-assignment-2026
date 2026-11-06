import json

import pytest

from controller.learning import Counts, bounds, guardrail_ok, move_weight
from controller.store import Store


def test_denominators_and_guardrail_are_separate():
    control = Counts(10000, 5000, 2500, 10)
    challenger = Counts(10000, 4600, 3200, 10)
    assert bounds(challenger, control, 'engagement_rate', 2.58)[0] > 0
    assert not guardrail_ok(challenger, control, {'pickup_rate_max_drop': .02}, 2.58)
    assert guardrail_ok(control, control, {'pickup_rate_max_drop': .04}, 2.58)


def test_rotation_respects_shift_and_preserves_other_ids():
    assert move_weight({'A': .45, 'B': .35, 'C': .2}, 'A', 'B', .2) == {
        'A': .25, 'B': .55, 'C': .2,
    }


def test_chunk_replay_and_bad_chunk_are_atomic(tmp_path):
    path = tmp_path / 'state.db'
    store = Store(path)
    timestamp = '2027-01-04T10:15:00+05:30'
    call = dict(type='call', event_id=1, ts=timestamp, workflow_id='wf', config_version=1,
                cohort_id='default', variant=dict(prompt_version='P1', caller_id='D1',
                welcome_message='W1', voice='V1'), connected=True, engaged=False,
                qa=dict(hallucination_flag=True))
    chunk = dict(chunk=0, events=1, first_event_id=1, last_event_id=1, until_ts=timestamp)
    store.ingest(chunk, [json.dumps(call)])
    store.close()
    store = Store(path)
    store.ingest(chunk, [json.dumps(call)])
    with pytest.raises(ValueError):
        store.ingest(dict(chunk, chunk=1, first_event_id=2, last_event_id=2), [])
    assert store.cursor == 0
    assert tuple(store.db.execute('select dials, connected, engaged, flags from calls').fetchone()) == (1, 1, 0, 1)
    store.close()


def test_stale_approval_never_calls_apply(tmp_path):
    from controller.governance import Governance

    class API:
        def __init__(self):
            self.posts = []

        def get(self, path, **params):
            if path == '/approvals/a1':
                return {'status': 'approved', 'approval_id': 'a1'}
            return {'version': 2}

        def mutate(self, *args):
            self.posts.append(args)
            raise AssertionError('Must never send a stale apply')

    store = Store(tmp_path / 'governance.db')
    api = API()
    governor = Governance(store, api)
    now = '2027-01-04T11:00:00+05:30'
    with store.db:
        store.db.execute('INSERT INTO proposals VALUES (?,?,?,?,?,?,?,?,?,?)', (
            'p1', 'wf', now, 'approval', 'pending', '{"base_version":1}', '{}', 'a1', None, now
        ))
    governor.reconcile(governor.active('wf'), now)
    assert not api.posts
    assert store.db.execute('SELECT state FROM proposals').fetchone()[0] == 'stale'


def test_auto_route_requires_permission_for_the_entire_diff():
    from controller.governance import route_for

    policy = {'auto_apply': {'enabled': True, 'allowed_dims': ['caller_id'], 'max_shift': .2}}
    config = {'allocations': {'default': {'caller_id': {'A': .5, 'B': .5}}}}
    for weight, expected in ((.65, 'auto'), (.75, 'approval')):
        changed = {'allocations': {'default': {'caller_id': {'A': weight, 'B': 1 - weight}}}}
        assert route_for(policy, config, changed, 'caller_id') == expected
    assert route_for(policy, config, config, 'prompt_version') == 'approval'


def test_prompt_detection_catches_a_sustained_moderate_spike():
    from controller.strategy import prompt_signal

    reference = Counts(25000, 6000, 3000, 92)
    hourly = Counts(1400, 300, 150, 15)
    daily = Counts(5000, 1200, 600, 62)
    assert prompt_signal(hourly, reference, 6) is None
    assert prompt_signal(daily, reference, 24) > .007
    assert prompt_signal(Counts(5000, 1200, 600, 24), reference, 24) is None
