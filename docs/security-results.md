# Security results log

Record commands and observations here. Passing fixture checks does not establish
detection accuracy, authenticated caller identity, or production readiness.

## 2026-11-05: local interfaces and integrity experiments

Machine: Windows 11, build 26200, AMD64; repository virtual environment,
Python 3.12.10. Docker client 28.3.2; Desktop startup log identifies 4.43.2.
Commands ran in PowerShell from the repository root. No cloud service was used.
The original detector, feature, evaluation, CLI, configuration, and original test
files were unchanged in this work.

### Verification before changes

```powershell
.\.venv\Scripts\ruff.exe check src tests scripts
.\.venv\Scripts\ruff.exe format --check src tests scripts
.\.venv\Scripts\python.exe -m pytest --basetemp=lab/runtime/pytest-before-seams-1105 -q
```

Observed: `All checks passed!`, `49 files already formatted`, and
`86 passed, 1 skipped in 52.20s`. The skipped test was the escaping symlink case:
Windows did not permit symlink creation. Earlier counts supplied in the handoff
were history, not used as this run's result. The explicit pytest temporary path
keeps disposable test files under the ignored runtime directory.

### Local experiments after changes

```powershell
.\.venv\Scripts\python.exe scripts\verify_security.py --out lab/runtime/security-experiment-1105
```

Recorded at `2026-11-05T11:47:25.837719+00:00` (06:47 EST). The command created a
new copy of the four declared fixtures and explicitly approved baseline 1 for
that copy. It did not alter the repository assets or existing local baselines.

| Experiment | Observed result |
|---|---|
| Unchanged assets | `passed: true`; all four asset IDs reported `ok`. |
| Append bytes to copied dataset | `passed: false`; `dataset:telemetry-sample: modified`; other three assets `ok`. |
| Restore dataset, plant `models/planted.bin` | `passed: false`; all declared assets `ok`; `unexpected: ["models/planted.bin"]`. |
| Authorized dataset read | Returned 13,708 verified bytes. |
| Unauthorized model write | `AccessDenied`; recorded `unauthorized_write_denied: true`. |
| Seal and verify sample evidence | `sealed_bundle_verified: true`. |
| Insert a record into the sealed snapshot | Rejected: `evidence bundle content does not match its authentication tag`. |
| Restore copied assets | Verification passed; baseline version remained 1 throughout the checks. |

The full report is saved locally as
`lab/runtime/security-experiment-1105/report.json`. The experiment's key, audit,
and baseline are under the same ignored tree. Use a new `--out` directory to
repeat; an existing directory is refused.

A separate disposable manifest, pointer, and sealed export were created with the
pre-change code under `lab/runtime/pre-seam-compatibility/`. After the changes,
an inline Python check loaded that inventory and key, called
`BaselineStore.load_approved`, `verify_assets`, and `verify_sealed_evidence`, and
asserted the original run ID. Output:

```text
PASS: actual pre-change manifest, pointer, and sealed bundle still verify; no baseline regenerated.
```

### Checks after changes

```powershell
.\.venv\Scripts\ruff.exe check src tests scripts
.\.venv\Scripts\ruff.exe format --check src tests scripts
.\.venv\Scripts\python.exe -m pytest --basetemp=lab/runtime/pytest-final-seams-1105 -q
docker compose -f compose.lab.yml config --quiet
```

Observed: `All checks passed!`, `53 files already formatted`, and
`108 passed, 1 skipped in 30.57s`. Compose configuration validation exited 0.
A formatting check first identified one wrapped argument in the new experiment
script; it was formatted and the lint/format checks were rerun successfully.
The same Windows symlink test remains skipped.

The new tests exercise a non-HMAC fake authenticator across baseline and evidence
round trips, legacy HMAC encoding, malformed tags, a memory-backed guarded store
with all local artifact files removed, denied writes before backend access,
failed atomic replacement, path escapes, both inventory versions, location
binding, and rejection of cloud locations by local storage. Test doubles are not
runtime integrations.

### Live verification: blocked on this machine

Attempted:

```powershell
docker compose -f compose.lab.yml up --build -d
.\.venv\Scripts\python.exe scripts\verify_lab.py
docker compose -f compose.lab.yml down
```

Docker was initially stopped. Starting it through the desktop CLI and then its
installed executable did not produce a usable engine. The build/start attempt
first failed because `dockerDesktopLinuxEngine` was missing; a later attempt
waited without output and was interrupted after the startup error was confirmed.
The Desktop backend log reported:

```text
starting services: initializing Inference manager:
... Docker\run\dockerInference: The file cannot be accessed by the system.
```

The initial verifier attempt was restricted by the execution sandbox. Retrying
with local-network access reached the host but failed with `WinError 10061`
(connection refused at `127.0.0.1:8765`). The `down` attempt also waited for the
unavailable engine and was interrupted; successful Compose shutdown could not be
confirmed. No factory reset, container-data deletion, or threshold change was made.

| Required live observation | This run |
|---|---|
| Worker read-only boundary record | Not observed: worker was not started successfully. |
| Seven-finding live set | Not observed: the traffic cycle did not start. |
| Current per-flow byte counts for `outbound-volume` | Not measured; old `conn.log` data was not presented as a new run. |
| Live recovery and sensor evidence links | Not verified. |

The expected finding set remains `thermal`, `unapproved-compute`,
`honeypot-contact`, `port-spread`, `periodic-connection`, `outbound-volume`, and
`compute-network-overlap`. This is the verifier's expectation, not an observed
result from this session. Restore Docker engine availability, run the live
commands again, and record the actual boundary JSON and finding set before
claiming a current end-to-end pass. If volume is absent in a running cycle,
inspect combined and per-flow bytes before proposing a threshold change.
