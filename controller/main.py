import argparse
import fcntl
import logging
import os
import resource
import sys
from datetime import datetime
from pathlib import Path
from time import monotonic, sleep

import httpx

from .governance import Governance
from .store import Store
from .strategy import Strategy


log = logging.getLogger(__name__)


class TemporaryAPIError(Exception):
    pass


class API:
    def __init__(self, client):
        self.client = client

    def get(self, path, **params):
        response = self.client.get(path, params=params)
        if response.status_code >= 500 or response.status_code == 429:
            raise TemporaryAPIError(f'GET {path}: {response.status_code}')
        response.raise_for_status()
        return response.json()

    def mutate(self, method, path, payload):
        response = self.client.request(method, path, json=payload)
        if response.status_code >= 500 or response.status_code == 429:
            raise TemporaryAPIError(f'{method} {path}: {response.status_code}')
        return response.status_code, response.json()

    def ingest(self, store, chunks):
        for chunk in sorted(chunks, key=lambda ch: ch['chunk']):
            started = monotonic()
            if chunk['chunk'] <= store.cursor:
                continue
            with self.client.stream('GET', f"/events/chunks/{chunk['chunk']}") as response:
                if response.status_code >= 500 or response.status_code == 429:
                    raise TemporaryAPIError(f"Chunk {chunk['chunk']}: {response.status_code}")
                response.raise_for_status()
                store.ingest(chunk, response.iter_lines(), started)


def checkpoint(store, state, elapsed, max_round):
    events, ingest, until = store.db.execute(
        'SELECT COALESCE(SUM(events),0), COALESCE(SUM(ingest_seconds),0), MAX(until_ts) FROM chunks'
    ).fetchone()
    lag = (datetime.fromisoformat(state['ts']) - datetime.fromisoformat(until)).total_seconds() / 60 if until else 0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    mib = rss / (2 ** 20 if sys.platform == 'darwin' else 2 ** 10)
    with store.db:
        store.db.execute('INSERT OR REPLACE INTO checkpoints VALUES (?,?,?,?,?,?,?,?,?)', (
            state['sim_minute'], state['ts'], elapsed, ingest, events, lag,
            state['credits_remaining'], max_round, mib,
        ))
    log.info('%s events=%d ingest=%.2fs elapsed=%.2fs rss=%.1fMiB credits=%s',
             state['ts'], events, ingest, elapsed, mib, state['credits_remaining'])


def run(api, store):
    started = monotonic()
    max_round = 0.0
    state = api.get('/sim/state')
    identity = [str(api.client.base_url), state['scenario'], state['end_minute']]
    existing = store.meta('world')
    if existing is not None and existing != identity:
        raise SystemExit('State belongs to a different simulator. Set CONTROLLER_DB to a fresh path.')
    latest = store.db.execute('SELECT MAX(last_event_id), MAX(until_ts) FROM chunks').fetchone()
    last_round = store.meta('last_round')
    if (latest[0] is not None and (latest[0] > state['last_event_id'] or latest[1] > state['ts'])
            or last_round is not None and last_round > state['sim_minute']):
        raise SystemExit('The simulator moved backwards. Set CONTROLLER_DB to a fresh path.')
    with store.db:
        store.set_meta('world', identity)
        if store.meta('initial_credits') is None:
            store.set_meta('initial_credits', state['credits_remaining'])
    api.ingest(store, api.get('/events/chunks', kind='history', after=store.cursor))
    api.ingest(store, api.get('/events/chunks', kind='events', after=store.cursor))

    workflows = sorted(api.get('/workflows'), key=lambda w: (w['tenant_id'], w['workflow_id']))
    governance = Governance(store, api)
    strategy = Strategy(store, api, governance)
    def approval_is_still_safe(wid, body, plan, ts):
        if plan['action'] not in ('experiment', 'promote'):
            return True
        prompt = body['proposed_config']['prompt_version']
        return strategy.detect_prompt(wid, prompt, ts) is None

    governance.before_apply = approval_is_still_safe
    last_checkpoint = None
    while True:
        round_started = monotonic()
        ts = state['ts']
        for workflow in workflows:
            wid = workflow['workflow_id']
            row = governance.active(wid)
            if row is not None:
                governance.reconcile(row, ts, finishing=state['finished'])
            current = api.get(f'/workflows/{wid}/config')
            strategy.assess(workflow, current, state, ts,
                            not state['finished'] and governance.active(wid) is None)
        with store.db:
            store.set_meta('last_round', state['sim_minute'])
        max_round = max(max_round, monotonic() - round_started)
        if (state['sim_minute'] % 1440 == 0 or state['finished']) and last_checkpoint != state['sim_minute']:
            state = api.get('/sim/state')
            checkpoint(store, state, monotonic() - started, max_round)
            last_checkpoint = state['sim_minute']
            max_round = 0.0
        if state['finished']:
            break

        active = store.db.execute(
            "SELECT 1 FROM proposals WHERE state IN ('intent','pending','approved') LIMIT 1"
        ).fetchone()
        minutes = state['tick_minutes'] if active else 60
        # Align unattended rounds to the next hour to keep detection on whole buckets.
        minutes = min(minutes, 60 - state['sim_minute'] % 60, state['end_minute'] - state['sim_minute'])
        code, update = api.mutate('POST', '/sim/advance', {'minutes': minutes})
        if code == 409 and update.get('error') == 'finished':
            state = api.get('/sim/state')
            api.ingest(store, api.get('/events/chunks', kind='events', after=store.cursor))
            continue
        if code != 200:
            raise RuntimeError(f'Advance failed: {code} {update}')
        api.ingest(store, update['new_chunks'])
        state.update(update)
        max_round = max(max_round, monotonic() - round_started)


def main():
    parser = argparse.ArgumentParser(description='Run the outcome controller over HTTP')
    parser.add_argument('url')
    parser.add_argument('--db', default=os.environ.get('CONTROLLER_DB', 'runs/controller.sqlite3'))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    lock_path = Path(args.db + '.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a') as lock, httpx.Client(base_url=args.url, timeout=180, trust_env=False) as client:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error(f'Another controller holds {lock_path}')
        store = Store(args.db)
        try:
            api = API(client)
            for attempt in range(6):
                try:
                    run(api, store)
                    return
                except (httpx.TransportError, TemporaryAPIError) as error:
                    if attempt == 5:
                        raise
                    log.warning('Simulator unavailable; reconciling from checkpoint: %s', error)
                    sleep(min(2 ** attempt, 15))
        finally:
            store.close()


if __name__ == '__main__':
    main()
