# Code and API reference

The Python implementation owns collection, normalization, anomaly scoring, rules,
correlation, and evidence. A frontend is an optional client. This document is the
handoff boundary for later design work; it specifies no layout or branding.

## Modules

| File under `src/qdc_anomaly/lab/` | Responsibility |
|---|---|
| `simulator.py` | Generates explicitly simulated GPU metrics and job context. |
| `worker.py` | Sends controlled traffic to fixed Compose peers and records the boundary probe. |
| `boundary.py` | Asks the OS whether this process can read a dataset, write the model folder, or open the key; writes `boundary.jsonl`. |
| `adapters.py` | `SourceAdapter`, `CollectionContext`, `SourceResult`, JSONL validation. |
| `detection.py` | Zeek/OpenCanary normalization and six explicit detection rules. |
| `framework.py` | `TelemetryBatch`, pluggable `RulePack`, rule execution, time/identity correlation. |
| `analytics.py` | Reuses the existing QDC windows and Isolation Forest. |
| `collector.py` | Joins adapters, evaluates rules/model, returns a bounded snapshot. |
| `replay.py` | Recomputes findings from exported raw observations offline. |
| `storage.py` | Atomic control files, append-only JSONL, evidence IDs. |
| `server.py` | Local JSON API and minimal diagnostic client. |

| File under `src/qdc_anomaly/security/` | Responsibility |
|---|---|
| `assets.py` | Inventory schemas 1 and 2, lexical path validation, optional asset locations. |
| `backends.py` | `ArtifactBackend` and `LocalDirectoryBackend`; scoped reads, atomic writes, digests, file enumeration. |
| `authenticators.py` | `Authenticator`, `LocalHmacAuthenticator`, and the raw-key compatibility helper. |
| `access_policy.py` | Deny-by-default policy evaluation on simulated workload labels; no side effects. |
| `store.py` | The guarded read/write/approve path that consults the policy and verifies the baseline. |
| `integrity.py` | Authenticated manifests, approval pointers, and evidence bundles using the injected authenticator; asset checks use the backend. |
| `audit.py` | Fixed-field JSONL audit records. |
| `findings.py` | `data-security-v1` rule pack and observation builders. |
| `__main__.py` | `keygen`, `baseline`, `verify`, `access-demo`, `seal-evidence`, `verify-evidence` commands. |

The Compose source bind is read-only and `PYTHONPATH=/app/src` uses the checkout's
code. Python changes need a service restart; static assets load on page refresh.
Zeek shares the worker's network namespace. Worker/API/decoy/receiver use an
internal network. The viewer uses a separate management bridge and reads shared
files. Docker documents network membership and `internal` isolation in its
[Compose network reference](https://docs.docker.com/reference/compose-file/networks/).

## Headless commands

From the repository root after `pip install -e ".[dev]"`:

```bash
python -m qdc_anomaly.lab describe
python -m qdc_anomaly.lab inspect --evidence lab/runtime
python -m qdc_anomaly.lab replay --input evidence.json --out replay.json
```

All commands accept `--config lab/settings.json`. `inspect` reads a local evidence
directory containing `control.json`, `inventory.json`, and source files. `replay`
requires an API export, not the verifier's report wrapper. It re-normalizes raw
records and recalculates findings; saved findings are not trusted as results.
Replay covers only records retained in the export and does not regenerate traffic.

## Extension contracts

The security package has two additional Python interfaces:

- `Authenticator`: `algorithm`, `key_id()`, `sign(bytes) -> str` (hex), and
  `verify(bytes, tag) -> bool`. Pass one where the existing APIs accept `key`.
  `as_authenticator` wraps raw bytes in the local HMAC implementation. The
  `auth` document block still contains `algorithm`, `key_id`, and `mac`.
- `ArtifactBackend`: `name`, `read_bytes(relative)`, atomic
  `write_bytes(relative, data)`, `exists(relative)`,
  `digest(relative) -> (sha256, size)`, `list_files()`, and `escaped_links()`.
  Paths are relative POSIX strings. Pass a backend to `GuardedStore`,
  `BaselineStore.create`, `digest_inventory`, or `verify_assets`; omission selects
  `LocalDirectoryBackend` for the inventory root. Manifests, pointers, and audit
  files still use their separate local paths.

`tests/test_security_seams.py` uses a fake authenticator and an in-memory backend
to verify that these boundaries drive real operations. Neither is a runtime
implementation. KMS and S3 adapters do not exist. See [data security and
integrity](13-data-security-and-integrity.md) for schema and trust limits.

An adapter implements `read(CollectionContext) -> SourceResult`. Results contain
normalized records, the count of malformed records, and the raw-record count.
`Collector(..., adapters=...)` accepts replacements for the three input contracts
`gpu`, `zeek`, and `opencanary`. Current normalized shapes are defined by the
functions and exercised in `tests/test_lab.py` and `tests/test_framework.py`.

A `RulePack` supplies an ID, description, and a callable
`evaluate(TelemetryBatch, LabConfig) -> list[dict]`. Pass custom packs explicitly
to `SecurityFramework(config, packs=(... ,))`; no dynamic code is loaded from JSON.
For built-in packs, `enabled_packs` in the configuration can select
`datacenter-v1`, `compute-network-v1`, `data-security-v1`, all three (the default), or an
empty list.
Unknown or duplicate IDs are rejected. `Collector` also accepts an injected engine.
`TelemetryBatch.security` carries data-security observations (integrity differences,
denied requests, failed record authentication) built by `qdc_anomaly.security.findings`;
`Collector(..., security_source=callable)` supplies them per snapshot, where the
callable takes the run start time and returns `(observations, bad_record_count)`.
`qdc_anomaly.security.findings.audit_source(path)` builds one from an audit log, and
`inspect --security-audit PATH` uses it from the command line. Without a source the
snapshot's `security` block reports `"source": "none"` and the pack sees nothing.

A finding contains `rule`, `category`, `title`, `explanation`, `first_seen`,
`last_seen`, `count`, `source`, and `evidence_ids`; the engine adds `rule_pack`.
Timestamps are Unix seconds. Categories are `operational`, `investigate`, and
`security`. Evidence IDs are source-prefixed hashes of records, not signatures or
proof of an untampered audit chain. Custom packs are trusted Python code and must
return the same contract.

The correlation pack maps `worker_node_id` (default `compute-01`) to the discovered
worker IP. This is an explicit single-worker lab mapping, not multi-host identity
resolution. Adding multiple workers requires an inventory contract and per-worker
time-window tests before correlation is extended.

## HTTP contract

| Endpoint | Behavior |
|---|---|
| `GET /api/health` | 200 if collection has no error; 503 while starting or on collector error. Check source freshness separately. |
| `GET /api/framework` | Current stages, rule packs, thresholds, and observe-only response mode. |
| `GET /api/state` | Snapshot plus a per-process control token for this local client. |
| `GET /api/export` | Downloadable snapshot without the control token. |
| `POST /api/control` | Selects a declared local scenario; cannot run arbitrary commands or choose targets. |

POST requires `Content-Type: application/json` and `X-Lab-Token` from `/api/state`.
If present, `Origin` must match the request host. Example bodies:

```json
{"mode":"guided","new_run":true}
```

```json
{"mode":"baseline","new_run":false}
```

Modes are `baseline`, `approved_load`, `thermal`, `recon`, `beacon`, `misuse`,
`recovery`, and `guided`. Guided mode requires a fresh run. Controls alter the
traffic simulator, never network policy. The token is not a production login or
authorization system. Keep the server local.

Snapshot schema version 1 includes `control`, `phase`, `complete`, `inventory`,
`gpu`, `flows`, `honeypot_hits`, `model`, `findings`, `security`, `evidence`, `counts`,
`health`, and `framework`. API snapshots also expose `error`; preserve that state in clients.
Timestamps in observations differ from `generated_at`, the snapshot time. Counts
are retained-run totals, not per-second traffic rates. Model scores are not
probabilities, and findings are not automatically resolved incidents.

## Checks before a new client is connected

```bash
ruff check src tests scripts
ruff format --check src tests scripts
pytest
docker compose -f compose.lab.yml config --quiet
python scripts/verify_lab.py
python scripts/verify_security.py --out lab/runtime/new-security-experiment
```

Keep real/simulated source labels, error/stale states, original-evidence access,
and the observe-only response boundary in any replacement client. Do not generate
fake findings in the frontend. Styling can be changed independently under `static/`.
