# Data security and integrity

The GPU and network experiments answer "what happened on the wire and on the
device". This part answers a narrower set of questions about the project's own
files: which simulated workload may read or change a declared asset, whether a
dataset, model artifact, or configuration still matches an approved version, and
whether exported evidence has changed since it was sealed. Everything runs locally
on sample files under `security/assets/`. Nothing here watches or edits files
outside that folder.

Recorded commands, observations, and verification gaps are in the
[security results log](security-results.md).

## What is implemented

| Module under `src/qdc_anomaly/security/` | Does |
|---|---|
| `assets.py` | Loads inventory schema 1 or 2: asset id, kind, relative path, approved version, optional location. Rejects absolute paths, drive letters, and `..`. |
| `backends.py` | `ArtifactBackend` and `LocalDirectoryBackend`; resolves links within the root, reads, atomically replaces files, hashes, and enumerates files and escaping links. |
| `authenticators.py` | `Authenticator` protocol and `LocalHmacAuthenticator`, the only runtime implementation. |
| `access_policy.py` | Deny-by-default evaluation of `(actor, operation, asset_id)` against `security/policy.json`. Pure function, no side effects. |
| `store.py` | `GuardedStore.read / write / approve_baseline / verify`. Checks read/write/approve policy; reads verify the baseline before returning bytes, while permitted writes require a later explicit approval. Records decisions and verification results. |
| `integrity.py` | SHA-256 digests, authenticated manifests, the approved-version pointer, and sealed evidence bundles. Uses the injected authenticator and artifact backend. |
| `audit.py` | Fixed-field JSONL audit records. |
| `findings.py` | Turns audit records into observations and runs the `data-security-v1` rule pack. |
| `__main__.py` | `keygen`, `baseline`, `verify`, `access-demo`, `seal-evidence`, `verify-evidence`. |

Sample fixtures:

```text
security/
├── inventory.json      four declared assets, root = security/assets
├── policy.json         training-job, collector, publisher, auditor
├── assets/
│   ├── datasets/telemetry-sample.csv
│   ├── models/isolation-forest-reference.json
│   ├── configs/detector-thresholds.json
│   └── evidence/sample-export.json
└── local/              created by you, ignored by git: integrity.key, baselines/, audit.jsonl
```

## Interfaces and inventory versions

`Authenticator` defines `algorithm`, `key_id()`, `sign(bytes) -> hex tag`, and
`verify(bytes, tag) -> bool`. `LocalHmacAuthenticator` uses HMAC-SHA256 and
constant-time tag comparison. `authenticate`, `verify_authenticated`, baseline
creation/loading, evidence sealing/verification, and `GuardedStore` accept this
interface. Existing callers may still pass raw key bytes through the `key`
parameter; `as_authenticator` wraps them. Document shapes and canonical bytes
stay compatible with existing baselines: `auth.algorithm`, `auth.key_id`, and
`auth.mac` retain their names. This interface authenticates documents, not users.

`ArtifactBackend` defines a `name` plus `read_bytes`, atomic `write_bytes`,
`exists`, `digest -> (sha256, byte_count)`, `list_files`, and `escaped_links`.
Each path is relative POSIX text. `GuardedStore(..., backend=...)` routes reads,
writes, baseline creation, and whole-inventory verification through it. Direct
calls to `verify_assets` or `BaselineStore.create` also accept `backend=`.
The default is `LocalDirectoryBackend` with the inventory's root. Local writes
use an exclusively created temporary sibling and `os.replace`; a failed replace
leaves the original file in place. Linked directories are not traversed during
enumeration. Resolving a path before opening it is not a kernel-enforced defense
against a privileged process racing to swap directories or links; the existing
read-only container mount remains the demonstrated OS boundary.

Inventory schema 1 continues to load without edits. Schema 2 optionally adds:

```json
{"id":"dataset:sample","kind":"dataset","path":"datasets/sample.csv",
 "approved_version":"v1","location":{"backend":"local"}}
```

The location schema also accepts non-empty `bucket` and `version_id` strings for
a future backend. Local operations reject another backend name and reject cloud
location fields, rather than silently reading a local file instead. A schema 1
inventory containing a location is rejected; change its schema explicitly.
The sample inventory remains version 1. A manifest entry includes `location`
only when supplied. Verification binds each digest to its path, kind, approved
version label, and location. Changing that binding requires an explicit new
baseline, even if file bytes are unchanged. Manifest document schema remains 1.

Only local implementations ship. Baseline/pointer files and audit JSONL remain
local even when an artifact backend is injected. Remote-only inventories, cloud
configuration, S3 storage, and KMS authentication still require implementation.

## Trust boundaries, stated plainly

- **Actors are labels.** `training-job`, `collector`, `publisher`, and `auditor` are
  strings passed by the caller. Nothing authenticates them, and the simulator's
  `job_approved` flag is also synthetic. A policy decision therefore means "this
  label is permitted", not "this caller is who it claims".
- **Enforcement covers the guarded path, plus one real OS boundary in the lab.**
  `GuardedStore` refuses to act when policy denies, but a process that opens
  `security/assets/...` directly is not stopped by Python. In the Compose lab the
  worker container mounts `security/assets` **read-only** at `/assets` and nothing
  mounts `security/local`, so the kernel refuses writes and the key is simply not
  there. The worker proves this itself: `lab/boundary.py` tries to read a dataset,
  write into the model folder, and open the key path, and records the operating
  system's answers in `lab/runtime/boundary.jsonl` (`allowed`, `denied` with
  `EROFS`, `absent`). `scripts/verify_lab.py` fails if any of those answers differ.
  Outside Docker, on your own user account, there is no such boundary: you can
  edit the fixtures freely, which is exactly what `verify` is there to catch.
- **The key file is the trust anchor.** Whoever can read `security/local/integrity.key`
  can authenticate any manifest or bundle. The key is generated locally, never
  committed (`*.key` and `/security/local/` are ignored), never logged, and the
  loader refuses a key stored inside the inventory root. `keygen` writes the file
  with mode `0600` on systems that honor it; on Windows, folder permissions decide.
- **Who may approve.** The policy grants `approve` to `publisher` only. The real
  gate is still possession of the key, because `baseline` needs it to sign.
- **If the host or the key holder is compromised,** every guarantee here falls.
  An attacker with the key can re-sign altered manifests; an attacker with write
  access to the audit log can edit history. The audit log is an ordinary writable
  file, not an immutable ledger. A cloud design would move signing and audit
  storage to services with separate credentials; see
  [the AWS architecture](12-aws-architecture.md).

## Access policy

`policy.json` lists, per actor, which asset ids or kinds it may `read` or `write`
and whether it may `approve`. Patterns are an exact id, `kind:*`, or `*`. A request
for an id that is not in the inventory is denied as outside scope before any
pattern is consulted, which is what stops `../lab/settings.json` or an absolute
path from ever reaching the file system.

`python -m qdc_anomaly.security access-demo` runs the three required cases:

1. `training-job` reads `dataset:telemetry-sample`: allowed, bytes returned.
2. `training-job` writes `model:isolation-forest-reference`: denied, file untouched.
3. `training-job` reads `../../lab/settings.json`: denied, outside scope.

Each produces one audit line.

## Baselines and the approved version

`baseline --approved-by publisher` digests every declared asset and writes
`security/local/baselines/baseline-000N.json`, authenticated with HMAC-SHA256 over
its canonical JSON. It also rewrites `approved.json`, an authenticated pointer that
names the approved version and the SHA-256 of that manifest file.

Why the pointer exists: every manifest ever approved stays valid under the key, so
a valid tag on `baseline-0001.json` does not say whether version 1 is still the
approved one. Verification always starts from the pointer, checks its tag, loads
the named manifest, compares its digest to the pointer, then checks the manifest's
own tag. Copying an old manifest over a new one fails at the digest step; editing
the pointer without the key fails at its tag; deleting the pointer is an explicit
"nothing is approved" error, never a silent fallback to the newest file.

The pointer does not solve rollback of the entire trusted state: restoring an
older valid pointer together with its matching manifest can still verify. A
separately protected monotonic version or external approval history would be
needed to detect that. The local key authenticates content, not freshness.

Approved updates are explicit: `publisher` writes the new content through the
store, then runs `baseline` again. That creates version N+1 and an `approve` audit
record. `verify` never regenerates a baseline when it finds a difference.

## Verification

`verify` reports, per asset, `ok`, `modified`, `missing`, `escaped` (a link now
points outside the root), or `unapproved` (declared but not in the manifest), plus
`unexpected` files found inside the root that no manifest entry covers. It exits
non-zero on any problem and records one audit line per problem.

`GuardedStore.read` verifies before use: it reads the bytes once, hashes those
bytes, compares to the approved digest, and returns the same bytes. The caller
therefore consumes exactly what was verified. The file on disk can still change a
moment later; a second `read` verifies again. There is no guarantee for code that
opens the path itself after a successful `verify`.

## Sealed evidence

`seal-evidence --input export.json --out export.sealed.json` wraps an exported
snapshot with its canonical digest, a timestamp, a label, and an HMAC tag.
`verify-evidence` checks the tag and the digest and can write the verified
snapshot out for `python -m qdc_anomaly.lab replay`. Any edit to the snapshot, the
metadata, or the tag fails with an explicit message, as does a different key.

Two limits to keep in mind. The short `source:hash` evidence ids that findings
carry are record identifiers, not an authenticated trail; only the bundle tag is.
And a verified bundle proves the export has not changed since sealing, not that
the sensors reported truthfully in the first place.

## Audit records

Store decisions and verification results append JSON lines to
`security/local/audit.jsonl` with these fields and no others:

`ts, actor, operation, decision, outcome, asset_id, baseline_version, evidence_ids, detail, node_id, job_id, source`

`evidence_ids` carry truncated content digests or bundle digests; `detail` is a
short reason capped at 300 characters. Contents, keys, and credentials never
appear. `node_id` and `job_id` are optional simulated workload identity supplied
by the caller for correlation.
Filesystem failures can interrupt an operation before its audit record is
written; this is not a transactional audit system.

## How findings reach the existing analysis

`qdc_anomaly.security.findings.normalize_security` turns failing audit rows and
successful reads into observations with the usual `id / ts / source / raw` shape, so they sit
in the evidence list beside Zeek and GPU records and replay from an export. The
`data-security-v1` rule pack, enabled by default alongside the other two, produces:

| Finding | Category | Means |
|---|---|---|
| `access-policy-violation` | investigate | The store denied a request. Blocked, so a policy violation to review, not an incident. |
| `integrity-failure` | security | An asset, manifest, or pointer did not verify. Something changed; who changed it is not established. |
| `evidence-verification-failure` | security | A sealed bundle did not verify. Treat its contents as unverified. |
| `compute-policy-overlap` | investigate | A denied or failing asset event carried a `node_id` matching unapproved GPU activity within `correlation_seconds`. Overlap in identity and time only. |
| `asset-read-then-transfer` | investigate | An allowed read of a dataset or model by a workload on the configured node was followed within `exfil_window_seconds` by a connection of at least `transfer_bytes` to an unapproved peer. An ordered pair, not proof that the asset's content moved. |

Successful reads are kept as observations so the last rule can see them; a read on
its own never produces a finding, and only reads carrying a `node_id` take part.

Resource anomalies (`thermal`), unexpected network activity (`port-spread`,
`periodic-connection`, `honeypot-contact`, `outbound-volume`), policy violations,
and integrity failures stay separate findings. The two join rules require node
identity and timing to agree, and both say in their explanation what they do not
prove.

To include audit observations in a headless snapshot:

```bash
python -m qdc_anomaly.lab inspect --evidence lab/runtime --security-audit security/local/audit.jsonl
```

The Compose services do not read the audit log, because the folder is not mounted
into them; that is a deliberate boundary, not an omission to fix in the compose file.

## The boundary probe

`probe_boundary(asset_root, key_path)` returns one record:

```json
{"source": "os-boundary", "enforced": true, "checks": [
  {"action": "read-dataset",    "result": "allowed", "detail": "13708 bytes"},
  {"action": "write-model-dir", "result": "denied",  "detail": "EROFS"},
  {"action": "open-key",        "result": "absent",  "detail": "not mounted"}]}
```

It runs at worker startup and again when the misuse scenario begins. If the mount
were ever writable the probe reports `allowed`, removes its probe file, and sets
`enforced` to false; nothing is hidden. The record is informational and is never
read by the rule packs, because "the worker tried to write" in this lab is a
scripted experiment, not an observed intrusion.

## Reproduce the experiments

Terminal, repository root, after `pip install -e ".[dev]"`:

```bash
python -m qdc_anomaly.security keygen
python -m qdc_anomaly.security baseline --approved-by publisher --note "initial sample baseline"
python -m qdc_anomaly.security verify
python -m qdc_anomaly.security access-demo
python -m qdc_anomaly.security seal-evidence --input security/assets/evidence/sample-export.json --out security/local/sample.sealed.json
python -m qdc_anomaly.security verify-evidence --input security/local/sample.sealed.json
```

For repeatable tamper experiments, use a fresh disposable copy:

```bash
python scripts/verify_security.py --out lab/runtime/new-security-experiment
```

The command refuses an existing output directory. It explicitly creates one
initial baseline, verifies unchanged assets, modifies and restores a copied
dataset, plants and removes a copied-root file, checks a denied write, and verifies
both an intact and altered evidence bundle. It saves `report.json`; its key and
baseline stay under the ignored runtime folder. It never changes the repository
fixtures or silently approves altered data. `tests/test_security.py` covers further cases on a
disposable copy, including traversal paths, a symlink that escapes the root, an old
manifest copied over a newer one, and a workload trying to approve its own baseline.

## What remains unknown after these checks pass

A passing `verify` says the sample files match what `publisher` approved under
this key. It does not say the approved content was correct, that the approver was
who the label claims, that no one read the files outside the store, or that the
host itself is trustworthy. Encryption at rest and authenticated caller identities
are not implemented. The Compose read-only asset mount is the only demonstrated
filesystem boundary; it does not constrain the host account running the store.
