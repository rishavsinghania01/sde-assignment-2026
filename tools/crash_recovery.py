"""Kill after a server-side approval write, then restart against the same world."""

import argparse
import os
import signal
import sqlite3
import subprocess
import sys
from pathlib import Path
from time import monotonic, sleep

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8752)
    parser.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    run = args.run_dir.resolve()
    run.mkdir(parents=True, exist_ok=False)
    database = run / 'controller.sqlite3'
    url = f'http://127.0.0.1:{args.port}'
    env = {**os.environ, 'CONTROLLER_DB': str(database), 'CONTROLLER_PYTHON': sys.executable}
    env.pop('CONTROLLER_TEST_KILL', None)
    entry = ['./run.sh', url]

    with (run / 'server.log').open('w') as log, httpx.Client(base_url=url, timeout=15) as api:
        server = subprocess.Popen(
            [sys.executable, '-m', 'sim', 'serve', '--scenario', 'scenarios/public_02_incidents.yaml',
             '--run-dir', str(run / 'world'), '--port', str(args.port)],
            cwd=root, stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            deadline = monotonic() + 60
            while monotonic() < deadline:
                if server.poll() is not None:
                    raise RuntimeError(f'Simulator exited. See {log.name}')
                try:
                    if api.get('/health').is_success:
                        break
                except httpx.ConnectError:
                    sleep(.2)
            else:
                raise RuntimeError(f'Simulator did not become ready. See {log.name}')

            with (run / 'killed.log').open('w') as killed_log:
                killed = subprocess.run(entry, cwd=root, env={**env, 'CONTROLLER_TEST_KILL': 'after_approval_post'},
                                        stdout=killed_log, stderr=subprocess.STDOUT, timeout=180)
            assert killed.returncode == -signal.SIGKILL, killed.returncode
            with sqlite3.connect(database) as db:
                pid, wid, base, state, approval_id = db.execute(
                    "SELECT id, workflow, json_extract(body,'$.base_version'), state, approval_id "
                    "FROM proposals WHERE state='intent'"
                ).fetchone()
                before_chunks = db.execute('SELECT COUNT(*) FROM chunks').fetchone()[0]
            first = api.get('/approvals', params={'workflow_id': wid}).json()
            accepted = next(item for item in first if item['proposal_id'] == pid)
            assert state == 'intent' and approval_id is None and accepted['status'] == 'pending'
            print(f'SIGKILL at {accepted["created_at"]} on {wid} base v{base}, '
                  f'local state=intent, remote state=pending ({accepted["approval_id"]}).')

            with (run / 'apply-killed.log').open('w') as killed_log:
                killed_apply = subprocess.run(
                    entry, cwd=root, env={**env, 'CONTROLLER_TEST_KILL': 'after_apply_post'},
                    stdout=killed_log, stderr=subprocess.STDOUT, timeout=180,
                )
            assert killed_apply.returncode == -signal.SIGKILL, killed_apply.returncode
            with sqlite3.connect(database) as db:
                apply_pid, apply_wid, apply_aid = db.execute(
                    "SELECT id, workflow, approval_id FROM proposals WHERE state='approved'"
                ).fetchone()
            remote_apply = api.get(f'/approvals/{apply_aid}').json()
            assert remote_apply['status'] == 'applied'
            print(f'SIGKILL after apply on {apply_wid}, local state=approved, '
                  f'remote state=applied ({apply_aid}).')

            with (run / 'restarted.log').open('w') as resumed_log:
                subprocess.run(entry, cwd=root, env=env, stdout=resumed_log,
                               stderr=subprocess.STDOUT, timeout=180, check=True)
            final = api.get('/sim/state').json()
            approvals = api.get('/approvals', params={'workflow_id': wid}).json()
            matching = [item for item in approvals if item['proposal_id'] == pid]
            assert final['finished'] and len(matching) == 1
            assert matching[0]['approval_id'] == accepted['approval_id']
            history = api.get(f'/workflows/{apply_wid}/config/history').json()
            applied = [item for item in history if item.get('approval_id') == apply_aid]
            assert len(applied) == 1
            with sqlite3.connect(database) as db:
                after_chunks, events, last_event = db.execute(
                    'SELECT COUNT(*), SUM(events), MAX(last_event_id) FROM chunks'
                ).fetchone()
                saved = db.execute('SELECT state, approval_id, applied_version FROM proposals WHERE id=?',
                                   (apply_pid,)).fetchone()
                recovered = db.execute('SELECT state, approval_id FROM proposals WHERE id=?',
                                       (pid,)).fetchone()
                applied_audit = db.execute(
                    "SELECT COUNT(*) FROM audit WHERE kind='proposal_applied' AND json_extract(detail,'$.id')=?",
                    (apply_pid,),
                ).fetchone()[0]
                integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
            assert saved == ('applied', apply_aid, applied[0]['version'])
            assert recovered == (matching[0]['status'], accepted['approval_id'])
            assert applied_audit == 1 and integrity == 'ok'
            assert after_chunks == final['chunks'] and last_event == final['last_event_id']
            print(f'Recovered {accepted["approval_id"]} exactly once, terminal state={recovered[0]}.')
            print(f'Reconciled {apply_aid} as v{applied[0]["version"]} exactly once '
                  f'at {applied[0]["applied_at"]}.')
            print(f'Finished at {final["ts"]}. Chunks {before_chunks} before kill, {after_chunks} after '
                  f'restart. Events {events:,}, last ID {last_event:,}. SQLite integrity check passed.')
        finally:
            server.terminate()
            server.wait(timeout=15)


if __name__ == '__main__':
    main()
