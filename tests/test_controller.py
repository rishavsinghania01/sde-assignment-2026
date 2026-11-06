import json

import pytest

from controller.learning import Counts, bounds, expected_loss, guardrail_ok, move_weight, readout
from controller.store import Store

PICKUP_GUARD = {'pickup_rate_max_drop': .02}


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


@pytest.mark.parametrize(('phase', 'challenger_pickups', 'challenger_conclusions', 'expected'), [
    ('experiment', 5000, 3100, 'promote'),
    ('experiment', 4400, 3100, 'end_experiment'),
    ('promote', 5000, 1600, 'rollback'),
])
def test_experiment_requires_guardrail_and_can_rollback(tmp_path, phase, challenger_pickups,
                                                       challenger_conclusions, expected):
    from controller.strategy import Strategy

    store = Store(tmp_path / 'trial.db')
    ts = '2027-01-06T11:00:00+05:30'
    trial = {'phase': phase, 'version': 2, 'started': '2027-01-05T10:00:00+05:30',
             'dimension': 'voice', 'group': 'voice', 'control': 'A', 'challenger': 'B',
             'baseline': {'A': 1.0}, 'proposal_id': 'trial'}
    with store.db:
        store.set('wf', 'experiment', trial)
        store.db.executemany('INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', [
            ('wf', '2027-01-05T11', 2, 'default', 'P', 'D', 'A', 'W', 10000, 5000, 2500, 0),
            ('wf', '2027-01-05T11', 2, 'default', 'P', 'D', 'B', 'W', 10000,
             challenger_pickups, challenger_conclusions, 0),
        ])
    workflow = {'workflow_id': 'wf', 'cadence': [2, 2], 'daily_batch': {'size': 1000},
                'objective': {'primary': 'engagement_rate', 'guardrail': {'pickup_rate_max_drop': .02}}}
    config = {'version': 2, 'config': {'cohorts': [], 'allocations': {'default': {
        'voice': {'A': .55, 'B': .45}
    }}}}
    plan = Strategy(store, None, None).experiment_plan(workflow, config, {}, ts)
    assert plan['action'] == expected
    assert plan['config']['allocations']['default']['voice'] == (
        {'A': .20, 'B': .80} if expected == 'promote' else {'A': 1.0}
    )
    store.close()


def test_expected_loss_matches_the_closed_form():
    assert expected_loss(0, .01) == pytest.approx(.01 / (2 * 3.141592653589793) ** .5)
    assert expected_loss(.05, .01) < 1e-6
    assert expected_loss(-.05, .01) == pytest.approx(.05, rel=1e-4)


def test_two_point_lift_is_promoted_at_trial_volume():
    # The old fixed read wanted a +1 point lower bound at z=2.807 and ended this trial.
    control, challenger = Counts(8000, 2000, 1100), Counts(8000, 2000, 1140)
    assert bounds(challenger, control, 'engagement_rate', 2.807)[0] < .01
    decision, risk = readout(challenger, control, 'engagement_rate', PICKUP_GUARD)
    assert decision == 'promote'
    assert risk['candidate_loss'] < .0025 < risk['control_loss']


def test_readout_waits_on_thin_evidence_and_blocks_guardrail_breaches():
    thin = readout(Counts(4000, 1000, 560), Counts(4000, 1000, 550), 'engagement_rate', PICKUP_GUARD)
    assert thin[0] is None
    loser = readout(Counts(8000, 2000, 1060), Counts(8000, 2000, 1140), 'engagement_rate', PICKUP_GUARD)
    assert loser[0] == 'restore'
    fewer_pickups = readout(Counts(8000, 1840, 1080), Counts(8000, 2000, 1100), 'engagement_rate', PICKUP_GUARD)
    assert fewer_pickups[0] is None and fewer_pickups[1]['guardrail_breach'] > .10


@pytest.mark.parametrize(('ts', 'expected'), [
    ('2027-01-06T11:00:00+05:30', None),
    ('2027-01-09T11:00:00+05:30', 'end_experiment'),
])
def test_undecided_trial_keeps_running_until_its_deadline(tmp_path, ts, expected):
    from controller.strategy import Strategy

    store = Store(tmp_path / 'trial.db')
    trial = {'phase': 'experiment', 'version': 2, 'started': '2027-01-05T10:00:00+05:30',
             'dimension': 'voice', 'group': 'voice', 'control': 'A', 'challenger': 'B',
             'baseline': {'A': 1.0}, 'proposal_id': 'trial'}
    with store.db:
        store.set('wf', 'experiment', trial)
        store.db.executemany('INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', [
            ('wf', '2027-01-05T11', 2, 'default', 'P', 'D', 'A', 'W', 4000, 1000, 550, 0),
            ('wf', '2027-01-05T11', 2, 'default', 'P', 'D', 'B', 'W', 4000, 1000, 560, 0),
        ])
    workflow = {'workflow_id': 'wf', 'cadence': [2, 2], 'daily_batch': {'size': 1000},
                'objective': {'primary': 'engagement_rate', 'guardrail': PICKUP_GUARD}}
    config = {'version': 2, 'config': {'cohorts': [], 'allocations': {'default': {
        'voice': {'A': .55, 'B': .45}
    }}}}
    plan = Strategy(store, None, None).experiment_plan(workflow, config, {}, ts)
    assert (plan and plan['action']) == expected
    store.close()


def test_no_new_trial_while_a_prompt_fix_is_being_verified(tmp_path):
    from controller.strategy import Strategy

    store = Store(tmp_path / 'start.db')
    ts = '2027-01-06T11:00:00+05:30'
    with store.db:
        store.db.execute('INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                         ('wf', '2027-01-05T11', 1, 'default', 'P', 'D', 'V1', 'W1', 4000, 1000, 550, 0))
    workflow = {'workflow_id': 'wf', 'cadence': [2, 2], 'daily_batch': {'size': 1000},
                'options': {'voice': ['V1', 'V2'], 'welcome_message': ['W1']},
                'objective': {'primary': 'engagement_rate', 'guardrail': PICKUP_GUARD}}
    config = {'version': 1, 'config': {'cohorts': [], 'allocations': {'default': {
        'voice': {'V1': 1}, 'welcome_message': {'W1': 1},
    }}}}
    state = {'sim_minute': 0, 'end_minute': 10 * 1440}
    strategy = Strategy(store, None, None)
    assert strategy.experiment_plan(workflow, config, state, ts)['action'] == 'experiment'
    with store.db:
        store.set('wf', 'verify_prompt_version', {'version': 1})
    assert strategy.experiment_plan(workflow, config, state, ts) is None
    store.close()
