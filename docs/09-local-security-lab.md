# Local GPU and network security experiments

These experiments show how network evidence and resource telemetry help explain
activity inside a data center. It combines real container traffic, a Zeek sensor,
an OpenCanary decoy, simulated GPU telemetry, and the project's existing Isolation
Forest. Run scenarios, observe their effects, and inspect the records behind findings.
The browser is an optional diagnostic client; the code and evidence are the project.

## Run the project

With Docker Desktop running Linux containers, run from the repository root:

```bash
docker compose -f compose.lab.yml up --build -d
```

Open http://localhost:8765. The first build needs internet access for images and
Python packages. The running lab uses an internal Docker network. The dashboard
is the only published service, bound to `127.0.0.1:8765`.
It uses a separate management bridge and reads shared evidence files; it has no
network attachment to the worker/decoy network.

Choose **Run 120-second test cycle** for a fresh run, or select and apply a scenario
manually. Manual scenarios continue until changed. **Return to baseline** stops
unusual traffic generation and retains findings for inspection. A new guided
cycle clears the dashboard's run view without deleting files.

```bash
docker compose -f compose.lab.yml logs --tail 40 zeek canary worker dashboard
python scripts/verify_lab.py
docker compose -f compose.lab.yml down
```

The verifier starts a new guided run and writes `lab/runtime/verification.json`.
Run it without simultaneously changing scenarios. `down` stops only this Compose
project. Evidence remains under `lab/runtime/`.
Archive evidence before recreating the sensor: a new Zeek process can replace
its current log files. Saved JSON exports are independent of that sensor lifecycle.

## How the traffic cycle works

```text
worker -------- approved API
  |     \------ OpenCanary decoy
  |      \----- harmless test receiver
  |
  +-- Zeek captures eth0 in the worker network namespace -> conn.log
  +-- GPU simulator -> gpu.jsonl and simulated approved-job context
                              |
          collector joins timestamp and worker identity
                              |
           window features + Isolation Forest + explicit rules + correlation
                              |
         JSON snapshot -> CLI, evidence export, or optional diagnostic viewer
```

The worker calls the approved API roughly every two seconds. Zeek shares its
network namespace through `network_mode: service:worker`, observing packets on
the worker's interface even on Windows Docker Desktop. It does not monitor the
whole host network. `-C` handles checksum offloading in virtual networking.

GPU samples arrive about once a second; the collector reads files every second;
the browser polls every 1.5 seconds. Zeek writes connection records after a
connection closes, with additional delays for failed attempts. Record timestamps
describe the observed connection; collection and display occur later.

## Explore the scenarios

| Default time | Scenario | Observation and interpretation |
|---|---|---|
| 0–15 s | Baseline | Ordinary API traffic and low simulated GPU activity. |
| 15–30 s | Approved load | High GPU utilization with an approved simulated job; load alone is not a security finding. |
| 30–45 s | Cooling fault | Temperature exceeds 85 °C; the finding is operational. |
| 45–60 s | Internal discovery | Seven fixed decoy ports are probed and dummy credentials submitted to its HTTP service. Zeek sees attempts; OpenCanary records the interaction. |
| 60–90 s | Repeating connections | Harmless HTTP heartbeats go to an internal receiver outside the approved destination policy. Six regular observations produce a beacon-like candidate. |
| 90–105 s | Compute misuse scenario | High simulated GPU use has no approved job while dummy data transfers occur. The repeated 66 kB transfers also exceed the 60-second volume threshold. Co-occurrence does not establish causation. |
| 105–120 s | Recovery | Unusual traffic generation stops; approved calls continue and evidence stays visible. |

During the misuse scenario the worker also probes its asset mount directly:
`security/assets` is bound read-only at `/assets`, so the read succeeds, the write
is refused by the kernel (`EROFS`), and the integrity key is absent because
`security/local` is not mounted into any container. Results land in
`lab/runtime/boundary.jsonl` and the verifier checks them.

The receiver is an internal container. No commands, malware, mining workload, or
real exfiltration are executed. The decoy has no host-published service ports.
Docker isolates the whole lab from external networks; per-workload
micro-segmentation is not implemented.

## Detection and evidence

Detection never reads scenario names. Presenter markers explain the cycle but
are excluded from decisions. Rules evaluate sensor observations or explicitly
simulated metrics:

- Temperature above the configured threshold creates an operational finding.
- High utilization without an approved simulated job creates an investigation finding.
- Worker-origin OpenCanary events create a decoy-contact finding.
- Six distinct destination ports on one peer in 20 seconds indicate probing.
- Six connections to an unapproved peer, with interval variation at most 0.25
  and mean spacing at most 30 seconds, indicate periodic traffic. Regular
  connections can be benign; this is not proof of C2.
- At least 150,000 combined bytes to one unapproved peer within 60 seconds
  creates an outbound-volume finding. Bytes count both directions and content is
  unknown; this is volume to review, not confirmed exfiltration.
- Unapproved GPU activity within five seconds of a connection carrying at least
  50,000 combined bytes to an unapproved peer creates a cross-source investigation
  finding. The node and source IP must match the configured worker. This is a
  correlation, not proof that the GPU process sent the data.

Click findings for their explanation, source, timestamps, and original records.
Startup logs, other source IPs, duplicate Zeek UIDs, old-run connections, and
malformed records are filtered. Missing/stale sources are visible. OpenCanary's
“log available” means a readable event file, not continuous process health.

**Export JSON** downloads a bounded JSON snapshot. Full files remain under
`lab/runtime/`. Each collector read uses the last 4,000 lines per source; the UI
keeps the latest 120 GPU samples/connections, 40 decoy hits, and 1,500 evidence
records. Findings accumulate within that retained run window and are not all
active incidents. This short-demo storage is not a production SIEM or durable
audit archive. Archive or remove growing logs while the lab is stopped.

## Connection to the analytics project

`lab/analytics.py` calls the existing `features.windows.make_windows` and
`detectors.classical.IsolationForestDetector`. Four GPU measurements (utilization,
memory, temperature, power) become 12 summary features: mean, standard deviation,
and last-minus-first for each metric.

Ten samples make a demo window, approximately ten seconds by default. This is
separate from the benchmark's minute-based windows and PCA reduction. Training
uses synthetic baseline and approved-load samples; a separate seeded reference
set establishes a 99th-percentile score threshold. The score is not a security
probability. A thermal event can remain below this general model threshold while
the explicit temperature rule detects it. The model supplies supplementary context.

The quantum detectors and benchmark remain in the original CLI and are not run
in the live dashboard. See [results](results.md) for the reconstructed benchmark
generator and limits on reproducing historical results.

## Configuration and extension points

`lab/settings.json` contains intervals, thresholds, and fixed local service names.
`lab/opencanary.conf` enables the HTTP decoy; `lab/local.zeek` selects JSON logs.
Controls accept only declared scenarios and cannot submit arbitrary targets or
execute commands. The dashboard has no Docker socket access.

Future AWS integration can use the existing boundaries: telemetry inputs,
normalized observations, detector outputs, and evidence export. A real GPU exporter
can replace the simulator when hardware is available. This local release creates
no cloud resources and implements no cloud enforcement; the proposed mapping is
written up in [the AWS architecture](12-aws-architecture.md). Local asset
integrity and access-policy checks live in `src/qdc_anomaly/security/` and are
described in [data security and integrity](13-data-security-and-integrity.md).

## Validate changes

```bash
pip install -e ".[dev]"
ruff check src tests
ruff format --check src tests
pytest
python scripts/verify_lab.py
```

Unit tests check evidence filtering, missing sensors, time-window rules, approved
load, model integration, cycle transitions, and (in `tests/test_security.py`) the
asset integrity, policy, and evidence-sealing cases on disposable fixtures. The live verifier requires Docker
and checks the actual sensor pipeline end to end.
