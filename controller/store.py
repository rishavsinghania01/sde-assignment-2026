import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from .learning import Counts


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chunks (
    chunk INTEGER PRIMARY KEY, until_ts TEXT, events INTEGER, last_event_id INTEGER,
    ingest_seconds REAL
);
CREATE TABLE IF NOT EXISTS calls (
    workflow TEXT, hour TEXT, version INTEGER, cohort TEXT, prompt TEXT,
    caller TEXT, voice TEXT, welcome TEXT,
    dials INTEGER, connected INTEGER, engaged INTEGER, flags INTEGER,
    PRIMARY KEY (workflow, hour, version, cohort, prompt, caller, voice, welcome)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS uploads (
    campaign TEXT PRIMARY KEY, workflow TEXT, ts TEXT, leads INTEGER
);
CREATE INDEX IF NOT EXISTS uploads_by_workflow ON uploads(workflow, ts);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY, workflow TEXT, ts TEXT, kind TEXT, detail TEXT,
    event_id INTEGER UNIQUE
);
CREATE INDEX IF NOT EXISTS audit_by_workflow ON audit(workflow, ts);
CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY, workflow TEXT, ts TEXT, route TEXT, state TEXT,
    body TEXT, plan TEXT, approval_id TEXT, applied_version INTEGER, updated TEXT
);
CREATE INDEX IF NOT EXISTS proposals_by_workflow ON proposals(workflow, ts);
CREATE TABLE IF NOT EXISTS workflow_state (
    workflow TEXT, key TEXT, value TEXT, PRIMARY KEY (workflow, key)
);
CREATE TABLE IF NOT EXISTS checkpoints (
    sim_minute INTEGER PRIMARY KEY, ts TEXT, elapsed REAL, ingest REAL,
    events INTEGER, lag_minutes REAL, credits REAL, max_round REAL, peak_rss_mib REAL
);
"""
ROLLUP = """
INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(workflow,hour,version,cohort,prompt,caller,voice,welcome) DO UPDATE SET
  dials=dials+excluded.dials, connected=connected+excluded.connected,
  engaged=engaged+excluded.engaged, flags=flags+excluded.flags
"""
GROUPS = {'cohort', 'caller', 'voice', 'welcome', 'prompt', 'version'}


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript(SCHEMA)
        self.cursor = self.db.execute('SELECT COALESCE(MAX(chunk), -1) FROM chunks').fetchone()[0]

    def close(self):
        self.db.close()

    def meta(self, key):
        row = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_meta(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, json.dumps(value)))

    def get(self, wid, key, default=None):
        row = self.db.execute(
            'SELECT value FROM workflow_state WHERE workflow=? AND key=?', (wid, key)
        ).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, wid, key, value):
        self.db.execute('INSERT OR REPLACE INTO workflow_state VALUES (?,?,?)',
                        (wid, key, json.dumps(value)))

    def audit(self, wid, ts, kind, detail, event_id=None):
        self.db.execute('INSERT INTO audit(workflow,ts,kind,detail,event_id) VALUES (?,?,?,?,?)',
                        (wid, ts, kind, json.dumps(detail, sort_keys=True), event_id))

    def ingest(self, chunk, lines, started=None):
        from time import monotonic

        number = chunk['chunk']
        if number <= self.cursor:
            return
        previous = self.db.execute(
            'SELECT COALESCE(MAX(last_event_id), 0) FROM chunks'
        ).fetchone()[0]
        calls = defaultdict(lambda: [0, 0, 0, 0])
        count = 0
        first = None
        last = previous
        with self.db:
            for line in lines:
                event = json.loads(line)
                eid = event['event_id']
                if eid <= last:
                    raise ValueError(f'Out-of-order event {eid} in chunk {number}')
                if first is None:
                    first = eid
                last = eid
                count += 1
                kind = event['type']
                if kind == 'lead':
                    continue
                wid, ts = event['workflow_id'], event['ts']
                if kind == 'call':
                    variant = event['variant']
                    key = (wid, ts[:13], event['config_version'], event['cohort_id'],
                           variant['prompt_version'], variant['caller_id'], variant['voice'],
                           variant['welcome_message'])
                    values = calls[key]
                    values[0] += 1
                    values[1] += event['connected']
                    values[2] += event['engaged']
                    values[3] += bool((event.get('qa') or {}).get('hallucination_flag'))
                elif kind == 'campaign_created':
                    self.db.execute('INSERT INTO uploads VALUES (?,?,?,?)',
                                    (event['campaign_id'], wid, ts, event['leads']))
                elif kind in ('config_changed', 'approval_decided'):
                    self.audit(wid, ts, kind, event, eid)
            if (count, first, last) != (
                chunk['events'], chunk['first_event_id'], chunk['last_event_id']
            ):
                raise ValueError(f'Incomplete chunk {number}: got {count} events')
            self.db.executemany(ROLLUP, ((*key, *values) for key, values in calls.items()))
            seconds = monotonic() - started if started is not None else 0
            self.db.execute('INSERT INTO chunks VALUES (?,?,?,?,?)',
                            (number, chunk['until_ts'], count, last, seconds))
        self.cursor = number

    def counts(self, wid, start, end, group=None, **filters):
        if group is not None and group not in GROUPS or not filters.keys() <= GROUPS:
            raise ValueError('Unknown rollup dimension')
        selected = group or 'NULL'
        sql = f"""SELECT {selected}, SUM(dials), SUM(connected), SUM(engaged), SUM(flags)
                  FROM calls WHERE workflow=? AND hour>=? AND hour<?"""
        params = [wid, start[:13], end[:13]]
        for field, value in filters.items():
            sql += f' AND {field}=?'
            params.append(value)
        if group:
            sql += f' GROUP BY {group} ORDER BY {group}'
        return {row[0]: Counts(*row[1:]) for row in self.db.execute(sql, params) if row[1]}

    def total(self, wid, start, end, **filters):
        return self.counts(wid, start, end, **filters).get(None, Counts())
