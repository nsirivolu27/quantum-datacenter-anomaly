# Sentinel Lab: Data Center Anomaly Detection and Data Security

A study repository that asks a narrow question with rigor: given the telemetry a
GPU node emits every second and the connections it opens, how far can a detection
pipeline go in separating expected work, equipment faults, policy violations, and
activity that warrants investigation, and what does each layer of evidence prove.

It contains three layers that share one evidence model:

1. **Anomaly detection research.** Synthetic rack telemetry, windowed features,
   classical detectors (Isolation Forest, one-class SVM, PCA reconstruction) and
   two quantum detectors (kernel SVM, autoencoder), benchmarked under one protocol.
2. **A local security lab.** Simulated GPU metrics joined with real packet capture
   (Zeek) and a real decoy (OpenCanary) inside an isolated Docker network, scored
   by explicit rules and time/identity correlation, with offline replay.
3. **A data security and integrity layer.** Deny-by-default access policy over a
   declared asset inventory, HMAC-authenticated baselines with an approved-version
   pointer, sealed evidence exports, a fixed-field audit log, and a kernel-enforced
   read-only boundary the workload probes and records itself.

Two interactive walkthroughs run in the browser with no install, computed by the
same rule logic: [inside the data center](https://nsirivolu27.github.io/quantum-datacenter-anomaly/site/)
(anomaly detection as a simulation) and
[what an intruder tries](https://nsirivolu27.github.io/quantum-datacenter-anomaly/site/security.html)
(data security as a simulation). [Sentinel Ops](https://nsirivolu27.github.io/quantum-datacenter-anomaly/site/ops/)
is a 3D operations console for the same ideas at hall scale: a scalable GPU
mainframe streaming synthetic telemetry, the lab's rules and thresholds,
simulated attackers against layered controls mapped to the proposed AWS design,
and an authorized red team engagement whose report reproduces the measured gaps.

## Status, stated plainly

| Claim | Evidence | Where |
|---|---|---|
| Unit and integration tests | 103 passing, 1 Windows symlink skip | `pytest` |
| Lint and format | clean | `ruff check`, `ruff format --check` |
| Live Compose cycle: seven findings, approved load silent, kernel `EROFS` on the mount | observed 2026-11-05 on Windows Docker Desktop, before the two newest rules | [security results](docs/security-results.md) |
| Detection quality under benign noise | 500 seeded cycles, per-rule precision, recall, time to detect | [security results](docs/security-results.md) |
| Historical benchmark tables | not valid for the reconstructed generator | [results](docs/results.md) |
| AWS architecture | proposed, nothing deployed | [docs/12](docs/12-aws-architecture.md) |

GPU readings are simulated. Network capture and decoy events are real. Actor names
in the policy layer are labels, not authenticated identities. No automated
containment exists.

## Detection logic

All rules read normalized records only; scenario labels never reach them.
Thresholds live in `lab/settings.json` and are validated on load.

| Rule | Logic | Window | Category |
|---|---|---|---|
| `thermal` | `gpu_temp_c >= 85` | per sample | operational |
| `unapproved-compute` | `gpu_util_percent >= 70 and not job_approved` | per sample | investigate |
| `honeypot-contact` | any OpenCanary event whose `src_host` is the worker | event | security |
| `port-spread` | at least 6 distinct `id.resp_p` to one `id.resp_h` | trailing 20 s, event time | security |
| `periodic-connection` | at least 6 connections to one unapproved `(dst, port)`, mean gap at most 30 s, coefficient of variation of gaps at most 0.25 | last 10 connections in the group | investigate |
| `outbound-volume` | combined `orig_bytes + resp_bytes` to one unapproved peer at least 150,000 | trailing 60 s | investigate |
| `compute-network-overlap` | unapproved high utilization on `worker_node_id` within 5 s of a connection from the worker IP carrying at least 50,000 combined bytes to an unapproved peer | 5 s | investigate |
| `access-policy-violation` | guarded store denied a request | audit record | investigate |
| `integrity-failure` | asset modified, missing, unexpected, escaped, or manifest/pointer authentication failed | verification | security |
| `evidence-verification-failure` | sealed bundle fails tag or digest | verification | security |
| `compute-policy-overlap` | denied or failing asset event with `node_id` within 5 s of unapproved utilization on that node | 5 s | investigate |
| `asset-read-then-transfer` | allowed read of a dataset or model by the worker node, then a transfer of at least 50,000 bytes to an unapproved peer within 30 s | 30 s, ordered | investigate |

Correlation joins are deliberately narrow: node identity and time must both agree,
and every joined finding states that it does not establish causation. Byte counts
are bidirectional and are never described as exfiltrated volume. The Isolation
Forest from the research layer scores ten-sample windows (mean, standard deviation,
trend per metric) against a seeded synthetic reference set; its output is
supplementary context with a 99th percentile threshold, not a security probability.

## Measured detection quality

`python scripts/evaluate_detections.py --cycles 500` generates 120 second cycles
from the simulator's distributions, normalizes them through the collector's own
functions, and scores them with the real framework. Four behaviors are injected
independently with randomized parameters, some below threshold on purpose. Benign
noise is always present: an approved 20 second burst, approved-API polling at 2,
5, or 10 s, and a multi-upload backup to an approved destination. Ground truth is
behavior injected, not threshold crossed.

| rule | precision | recall | median time to detect | what the misses are |
|---|---|---|---|---|
| thermal | 1.00 | 1.00 | 0.4 s | none |
| unapproved-compute | 1.00 | 1.00 | 0.5 s | none |
| honeypot-contact | 1.00 | 1.00 | 3.5 s | none |
| port-spread | 1.00 | 0.76 | 0.0 s | every scan paced at 5 s per port: seven knocks span 30 s, the window is 20 s |
| periodic-connection | 0.96 | 0.70 | 0.0 s | five-connection beacons, 35 percent jitter, and beacons interleaved with a dump to the same `(dst, port)`; 8 false alarms where a bursty dump happened to be regular |
| outbound-volume | 1.00 | 0.83 | 1.0 s | every two-upload dump: 132 kB is under 150 kB |
| compute-network-overlap | 1.00 | 1.00 | 1.0 s | none |

The misses table in [security results](docs/security-results.md) lists each
parameter combination. These describe the generator, not production traffic; they
exist so threshold changes are argued from numbers.

The context model is measured the same way. `model_detector` in `lab/settings.json`
selects any research-layer detector (Isolation Forest by default; one-class SVM,
PCA reconstruction, or the two quantum detectors with features reduced to four
angles), built through the benchmark's `build_detector` and calibrated at the
99th percentile of a synthetic reference set that now includes workload
transitions. On the same cycles, with a drift behavior (temperature 10 to 14 °C
above the load curve, under the limit, no rule for it) as the test of what a model
adds: Isolation Forest AUC 0.74, 4 percent quiet false alarms, 1 percent of drift
windows caught; the SVM and PCA twins catch about 4 percent at the same false
alarm rate. The earlier reference set without transitions flagged 24 percent of
quiet windows. Both operating points are in the results log. The model remains
what the docs call it, context, and the next experiment is a feature for
temperature relative to expected temperature for the load.

## Integrity design

- **Canonical encoding.** Every authenticated document is encoded as sorted-key,
  compact, ASCII JSON before tagging, so semantically equal documents produce
  equal tags and whitespace is never a bypass.
- **Baselines.** `baseline-NNNN.json` holds SHA-256 digests of every declared
  asset and is HMAC-SHA256 authenticated. `approved.json` is a second
  authenticated document naming the current version and the SHA-256 of that
  manifest file. Verification order: pointer tag, manifest digest against the
  pointer, manifest tag, then assets. This binds "approved" to one exact file, so
  an older manifest with a valid tag is rejected at the digest step and a deleted
  pointer is an explicit failure rather than a fallback.
- **Verify before use.** `GuardedStore.read` hashes the bytes it returns and
  compares them to the approved digest, so the consumer receives exactly what was
  verified. The guarantee does not extend to a second open by path; the TOCTOU
  window is stated rather than hidden.
- **Key handling.** 32 random bytes, mode 0600 where honored, refused if located
  inside the inventory root, never logged; manifests carry a derived key id only.
  HMAC is shared-key authentication: anyone with the key can sign, which is why the
  key lives outside every container mount and why the cloud design replaces it
  with KMS `Sign`/`Verify` under a key policy the workload cannot satisfy.
- **Policy before storage.** Policy evaluation is a pure function; the store
  consults it before any backend call. The `Authenticator` and `ArtifactBackend`
  protocols are the seams where a KMS signer and an S3 backend would attach.
- **Kernel boundary.** The Compose worker mounts `security/assets` read-only and
  mounts nothing under `security/local`. The worker probes read, write, and key
  open at startup and during misuse and records `allowed`, `denied EROFS`, `absent`;
  the live verifier fails without that record.

## Architecture

```text
worker (traffic + GPU simulator) ── internal Docker network ── approved api / test receiver / OpenCanary
   │  shares network namespace with Zeek  →  zeek/conn.log
   │  /assets read-only                   →  boundary.jsonl
   └──────────────── lab/runtime (append-only JSONL, atomic control file) ─────────────┐
                                                                                        ▼
                    adapters (filter by run and worker, validate, dedupe, keep raw)  →  TelemetryBatch
                                                                                        ▼
                    rule packs: datacenter-v1, compute-network-v1, data-security-v1   →  findings + evidence ids
                                                                                        ▼
                    snapshot  →  sealed export (HMAC)  →  offline replay recomputes from raw records
```

The viewer on `127.0.0.1:8765` sits on a separate management bridge, reads shared
files only, and can select declared scenarios and nothing else.

## Run it

Terminal: PowerShell or bash from the repository root.

```bash
pip install -e ".[dev]"
ruff check src tests scripts && ruff format --check src tests scripts
pytest
python scripts/evaluate_detections.py --cycles 500
```

Live lab (Docker Desktop with Linux containers):

```bash
docker compose -f compose.lab.yml up --build -d
python scripts/verify_lab.py
docker compose -f compose.lab.yml down
```

Integrity experiments (key and baselines go under `security/local/`, ignored by git):

```bash
python -m qdc_anomaly.security keygen
python -m qdc_anomaly.security baseline --approved-by publisher
python -m qdc_anomaly.security verify
python -m qdc_anomaly.security access-demo
python -m qdc_anomaly.security seal-evidence --input evidence.json --out evidence.sealed.json
python -m qdc_anomaly.security verify-evidence --input evidence.sealed.json
```

Headless analysis without Docker:

```bash
python -m qdc_anomaly.lab describe
python -m qdc_anomaly.lab inspect --evidence lab/runtime --security-audit security/local/audit.jsonl
python -m qdc_anomaly.lab replay --input evidence.json --out replay.json
```

## Repository map

| Path | Contents |
|---|---|
| `src/qdc_anomaly/data`, `features`, `detectors`, `evaluation`, `cli.py` | The research layer: generator, windows, five detectors, benchmark |
| `src/qdc_anomaly/lab/` | Simulator, worker, adapters, rules, framework, collector, replay, boundary probe, pluggable context model, quality evaluation, optional viewer |
| `src/qdc_anomaly/security/` | Inventory, policy, guarded store, integrity, authenticators, backends, audit, findings, CLI |
| `security/` | Declared sample assets, inventory, policy; `local/` holds the key, baselines, audit (ignored) |
| `lab/`, `compose.lab.yml` | Settings, Zeek and OpenCanary config, Compose stack |
| `scripts/` | `verify_lab.py` (live), `verify_security.py` (integrity experiments), `evaluate_detections.py` (quality) |
| `tests/` | 104 tests across all three layers |
| `docs/` | Lessons 01 to 08 (research), 09 to 14 (lab, metrics, code reference, AWS proposal, data security, threat model), results logs |
| `site/` | The two interactive walkthroughs, served by GitHub Pages |

## Threat model

Assets, boundaries, the attacker assumed, and an ATT&CK mapping for every rule are
in [docs/14-threat-model.md](docs/14-threat-model.md). In short: the adversary has
code execution on the worker; host root, a stolen key, or compromised sensors
defeat the corresponding layer, and the documentation says which.

## Limitations and next work

- GPU telemetry is simulated; a DCGM or CloudWatch agent adapter is the path to
  real readings, with units and sampling semantics validated against hardware.
- Process-level attribution is absent: joins are by node and time. A cgroup and
  socket sampler (`/proc` or eBPF) would turn "same node" into "same container".
- Detection rules are not yet exported as Sigma; the Python is the only source.
- The audit log is an ordinary file. Durable, append-only audit needs the cloud
  design (S3 Object Lock, CloudTrail data events) or a local equivalent.
- Live verification has not been rerun since `outbound-volume` and
  `asset-read-then-transfer` landed; the expected set is a verifier assertion
  until the next Docker run is recorded.
- Findings carry evidence ids that are content hashes, not signatures; only the
  sealed export is an authenticated bundle.

## License

MIT.
