# Public 03 load benchmark

One full five-day run of `scenarios/public_03_load.yaml`, including the seven-day event history. Python 3.12.16 on ARM64 Linux in Docker Desktop on an Apple M1 Pro. The container CPU quota was four CPUs (`cpu.max = 400000 100000`) and its memory limit was 8 GiB (`memory.max = 8589934592`). The controller and simulator shared the same limits.

| Phase | Events ingested | HTTP fetch + parse + SQLite commit | End-to-end wall time |
|---|---:|---:|---:|
| History at D0 | 5,537,531 | 23.43 s | 23.49 s |
| D0 | 840,028 | 3.63 s | 12.09 s |
| D1 | 840,028 | 3.70 s | 12.28 s |
| D2 | 840,012 | 3.69 s | 12.36 s |
| D3 | 840,012 | 3.63 s | 12.42 s |
| D4 | 840,012 | 3.67 s | 12.45 s |
| All live days | 4,200,092 | 18.32 s | 61.59 s |

- Live ingestion averaged **229,321 events/s** during the chunk ingest path, or about **68,191 events/s** including simulator advancement and controller decisions.
- Across 88 live rounds that produced events, p95 time from the start of the advance to completed assessment was **1.50 s**, with a **1.58 s** maximum. The largest event-bearing advance was **60 simulated minutes**, the upper bound on arrival-to-assessment for events generated in that advance. Approval polling uses 15-minute advances while an approval is open. These measurements exclude the time a proposal waits for approval or statistical evidence.
- Controller peak RSS was **33.5 MiB**. Container peak memory was **4.84 GiB**, including the simulator and filesystem cache. The finished SQLite file occupied 476 KiB.
- The controller finished in **85.09 s** including history ingestion, excluding simulator history generation (**45.6 s**). It applied 16 config changes and spent zero credits. The simulator ended at D5 00:00 after 9,737,623 ingested events.
- Midnight checkpoints show 180 simulated minutes since the last chunk on each live day. Calls stopped at 21:00 in this run. The clock advanced through those idle hours with no unconsumed chunks.

The ingest rate measures service time while ingesting. The lower end-to-end rate includes the time to generate events and make decisions. The slowest simulated day took 12.45 seconds after startup. This benchmark is for one world on a local ARM64 Docker host. Production latency depends on the event broker, real-time dispatch, storage and network.

## Reproduce

Run from the repository root. Use an empty run directory for each benchmark. The simulator writes several GiB of event data.

```sh
mkdir -p runs/load-linux
docker run --rm --cpus=4 --memory=8g --memory-swap=8g \
  -v "$PWD:/assignment:ro" -v "$PWD/runs/load-linux:/evidence" \
  -w /assignment python:3.12-slim bash -euc '
    set -o pipefail
    python -m pip install -r requirements.txt
    cat /sys/fs/cgroup/cpu.max /sys/fs/cgroup/memory.max > /evidence/limits.txt
    python -m sim serve --scenario scenarios/public_03_load.yaml \
      --run-dir /evidence/world >/evidence/server.log 2>&1 &
    server=$!
    trap "kill $server 2>/dev/null || true" EXIT
    for i in {1..240}; do
      if python -c "import urllib.request; urllib.request.urlopen(\"http://127.0.0.1:8700/health\", timeout=1)" 2>/dev/null; then
        break
      fi
      kill -0 "$server"
      sleep 1
    done
    CONTROLLER_PYTHON=python CONTROLLER_DB=/evidence/controller.sqlite3 \
      ./run.sh http://127.0.0.1:8700 2>&1 | tee /evidence/controller.log
    cat /sys/fs/cgroup/memory.peak >> /evidence/limits.txt
  '
```

Read per-day totals from `checkpoints` and take differences in `elapsed`, `ingest` and `events`. For decision latency, query `SELECT span_minutes, seconds FROM rounds WHERE events > 0 ORDER BY seconds` and take the nearest-rank p95 of `seconds`.

At 10×, partition the stream by tenant and workflow before increasing controller workers. The dominant cost in the measured ingest path is serial delivery and JSON decoding. Keep a single owner per workflow and test throughput under a skewed load, where a small number of workflows generate most of the traffic.
