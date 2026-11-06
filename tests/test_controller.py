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
