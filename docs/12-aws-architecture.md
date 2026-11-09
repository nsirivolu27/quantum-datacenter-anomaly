# Proposed AWS architecture

**Status: proposed, not deployed.** This document describes how AWS services could
host the lab described in [the local security lab](09-local-security-lab.md) and
[data security and integrity](13-data-security-and-integrity.md). No AWS account
was configured, no resource was created, and no deployment template exists in
this repository. Every section ends with what is missing in code before the
proposal could run. Facts about AWS services below were checked against the
official documentation linked at the end on 2026-11-04; service behavior changes,
so re-check before building.
The local integration interfaces and the cited S3, KMS, and Systems Manager
corrections below were reviewed on 2026-11-05. AWS remains proposed, not deployed.

## What the repository contains today

| Item | Actual state |
|---|---|
| CloudWatch loader (`src/qdc_anomaly/data/cloudwatch.py`) | Does not exist. Older text in lessons 2 and 8 described it as present; both lessons now say so. `qdc score --input` reads any CSV with the expected columns. |
| Amazon Braket examples (lesson 8) | Code snippets only. The device ARNs are historical examples, the S3 destination is a placeholder, and nothing in `src/` calls Braket. |
| `boto3` in `pyproject.toml` | Listed under the optional `aws` extra. No module imports it. |
| Local security package | `Authenticator` and `ArtifactBackend` interfaces now exist, with local HMAC and directory implementations only. Inventory schema 2 supports optional locations. No cloud signing or storage. |

Nothing in the repository reads from or writes to AWS. The sections below are a
design, and the "missing" rows are the work list.

## Trust boundaries first

```text
                      +-------------------------------- VPC (no internet gateway) ---------------------------------+
                      |                                                                                            |
  operator -- SSM --> |  [workload subnet]            [monitoring subnet]           [decoy subnet]                 |
  Session Manager     |   EC2 worker                   EC2 sensor/collector          EC2 OpenCanary                |
  (no SSH, no         |   - traffic generator          - Zeek (mirrored or local)    - HTTP decoy only             |
   public IP)         |   - GPU simulator or real      - Python collector + rules    - no outbound except          |
                      |     DCGM/CloudWatch agent      - security verify/seal          CloudWatch logs             |
                      |   - instance role: workload    - instance role: collector    - instance role: decoy        |
                      |                                                                                            |
                      |  interface endpoints: logs, monitoring, kms, sts, ssm, ssmmessages                         |
                      |  gateway endpoint: s3                                                                      |
                      +--------------------------------------------------------------------------------------------+
                                     |                 |                  |                 |
                               CloudWatch           S3 buckets          KMS            CloudTrail
                             metrics + logs     artifacts/manifests   encrypt +      management + S3
                                                evidence/audit        sign/verify    data events
```

Three roles never share credentials: the workload publishes its own telemetry and
reads approved artifacts; the collector reads observations and writes evidence;
a publisher/approver, who is a person or a CI job and not an instance in this
VPC, publishes artifacts and approves baselines. An auditor reads and verifies.
Subnets separate blast radius and routing, but subnet separation is not access
control: security groups, IAM policies, bucket policies, and KMS key policies are
what actually decide who may do what.

## A. Amazon EC2

| Component today | Proposed placement | Notes |
|---|---|---|
| `lab/worker.py` traffic generator | Workload instance | Same fixed peers, now other instances or private DNS names instead of Compose service names. |
| `lab/simulator.py` GPU samples | Workload instance, initial option | Stays simulated. Clearly labeled `simulated: true` as today. |
| Real GPU metrics | Separate future option | A GPU instance family (for example G6, G6e, P5) with the NVIDIA driver installed, or an AMI that ships it. The CloudWatch agent's `nvidia_gpu` section or the DCGM exporter then replaces the simulator. Not required for anything else in this design. |
| Zeek | Monitoring instance (sensor) or on the workload host | See section C. |
| OpenCanary | Decoy instance in its own subnet | Only the HTTP decoy, as in `lab/opencanary.conf`. |
| Python detection and correlation (`lab/collector.py`, `lab/framework.py`, `security/`) | Monitoring instance | Reads local or mirrored sensor output plus CloudWatch, writes findings and evidence. |

No instance has a public IP. Software arrives through a prepared AMI or through
the S3 gateway endpoint from a bucket you control, since private subnets cannot
reach package registries without a NAT gateway or a proxy you also have to secure.

Missing: an AMI or user-data build that installs the package; a systemd unit per
role; an EC2 variant of `lab/settings.json` that names peers by private DNS.

## B. Amazon VPC

- One VPC, no internet gateway, three private subnets (workload, monitoring,
  decoy), each with its own route table.
- Security groups: the workload may reach the API peer, the receiver, and the
  decoy on their service ports and nothing else; the decoy accepts from the
  workload subnet only; the monitoring instance accepts VXLAN (UDP 4789) from
  mirror sources and nothing inbound otherwise. Egress is limited to the declared
  peer ports, endpoint security groups on 443, and the S3 managed prefix list on
  443. A broad allow to the entire VPC CIDR would defeat the peer restrictions.
- Network ACLs as a coarse backstop; they cannot reference prefix lists, so the S3
  gateway prefix list must be allowed in NACLs by CIDR ranges if NACLs are used.
- Interface endpoints (PrivateLink) for CloudWatch Logs (`logs`), CloudWatch
  (`monitoring`), KMS, STS, `ssm`, and `ssmmessages`; a gateway
  endpoint for S3 added to each route table. Private DNS must be enabled on the
  VPC for the default service hostnames to resolve to the endpoints. Endpoint
  policies can further restrict which buckets or keys are reachable through them.
  `ec2messages` is a legacy option depending on the region and agent, not a
  universal requirement; see section I.

Missing: everything. No VPC definition exists in this repository, and the request
for this document explicitly excludes generating one.

## C. Network collection: three different inputs

| Option | What it gives | Fit with current code |
|---|---|---|
| Host-local Zeek on the workload instance | Same `conn.log` as today, same latency, same fields. | `adapters.py` reads it unchanged after the path is set. Preferred first step. |
| VPC Traffic Mirroring to a dedicated sensor | Packet copies of the workload ENI delivered VXLAN-encapsulated to an ENI, NLB, or Gateway Load Balancer endpoint. Zeek on the sensor must decapsulate VXLAN (listen on UDP 4789). Mirroring is out of band: it observes, does not block, and cannot decrypt TLS payloads. Mirrored traffic counts against the source's bandwidth and is dropped first under pressure, so production traffic is prioritized. Not every instance type is a supported source; check the official list for the chosen family. ARP, DHCP, IMDS, and NTP are not mirrored. | Zeek output is the same log, so `adapters.py` still works, but timing and drop behavior must be validated before any claim that it matches the local lab. |
| VPC Flow Logs | Aggregated metadata per flow (addresses, ports, protocol, packets, bytes, start and end, action) delivered to CloudWatch Logs, S3, or Firehose. Default aggregation 10 minutes, optional 1 minute (Nitro instances report at 1 minute or less), with typical delivery delay of about 5 minutes to CloudWatch Logs and about 10 minutes to S3. No payload and no Zeek-style connection state. | Does not fit the current seconds-level rules (`port-spread` uses 20-second windows, `periodic-connection` needs individual connection timestamps, correlation uses a 5-second window). Flow Logs are additional evidence, not a drop-in replacement; using them would need new rules and a new validation run. Flow Logs also do not include mirrored traffic. |

Missing: a `FlowLogAdapter` if Flow Logs are ever used; a sensor AMI with Zeek
configured for VXLAN; a validation script comparing mirrored and host-local
`conn.log` for the same traffic cycle.

## D. Amazon CloudWatch

What would flow in:

- GPU measurements. Simulated samples would be published as custom metrics with a
  dimension such as `source=simulated`, keeping the label the code already carries.
  Real measurements come from the CloudWatch agent `nvidia_gpu` section, which
  runs on Linux hosts with the NVIDIA driver and `nvidia-smi` installed and
  publishes metrics prefixed `nvidia_smi_` (including `utilization_gpu`,
  `memory_used`, `temperature_gpu`, `power_draw`) with `index`, `name`, and `arch`
  dimensions. The agent documentation lists this section for Linux only.
- Zeek and OpenCanary logs via the CloudWatch agent log collection, one log group
  per source, keeping the original JSON line and its own timestamp.
- Application findings and source-health signals (`health` in the snapshot) as a
  structured log stream from the collector.

Why source identity and timestamps matter: the collector already joins records
by `node_id`, worker IP, and event time, and `generated_at` is separate from
observation time. Publishing must keep those fields, not replace them with
ingestion time.

What CloudWatch does not do: it has no idea whether a job is approved, so
`job_approved` would still have to come from a scheduler or identity source. It
does not run the Python rule packs; alarms on thresholds are possible, but the
cross-source rules stay in `framework.py` on the monitoring instance (or in a
later container or Lambda, which is not proposed here).

Missing: a `CloudWatchMetricAdapter` and `CloudWatchLogsAdapter` implementing the
`SourceAdapter` protocol; the agent configuration files; and the long-promised
`data/cloudwatch.py` loader for the benchmark CLI, which would read metric data
into the `qdc score` CSV layout.

## E. Amazon S3

| Bucket (logical) | Holds | Controls |
|---|---|---|
| artifacts | Approved datasets, model artifacts, configuration | Versioning on, SSE-KMS with the storage key, Block Public Access on, bucket policy allowing writes only from the publisher role, reads from workload and collector roles. Manifests reference the exact object version id, so "approved" means a specific version, never "latest". |
| manifests | Baseline manifests and the approved pointer | Same, plus writes allowed only to the approver role. Object Lock in compliance mode on manifest versions if retention is justified. |
| evidence | Sealed evidence exports | Collector writes unique object keys with conditional creation, no delete permission. Object Lock governance mode with a chosen retention period; legal hold for anything under review. |
| audit | Exported audit batches and CloudTrail logs in separate prefixes | Application audit batches use new object keys, not in-place JSONL append. Auditor reads; deletion and lifecycle respect retention policies. CloudTrail writes its own prefix through its service policy. |

Object Lock works only with versioning on and protects specific object versions
from deletion or overwrite for the retention period (compliance mode cannot be
shortened by anyone, governance mode can be bypassed by principals with
`s3:BypassGovernanceRetention`). It does not prevent new versions from being
written, and it does not make the newest version trustworthy. That is exactly why
the approved pointer from lesson 13 is needed in the cloud too: the pointer names
which manifest version is approved, and the manifest names which artifact
versions are approved.

`PutObject` permission alone does not prohibit writing another version at an
existing key. The proposed evidence writer must use `If-None-Match: *`, enforced
by bucket policy, with unique keys and retention controls. General-purpose S3
audit exports would likewise be new batch objects, not append calls on the local
JSONL file. [Conditional writes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html).

Missing: an `S3ArtifactBackend` implementing `security.backends.ArtifactBackend`,
with a relative-path-to-bucket/version map built from the inventory; remote
manifest/pointer persistence; audit/evidence uploads; CLI wiring; retention and
concurrency decisions. The local backend rejects S3 locations. Inventory loading
still requires a local root, so a remote-only inventory also needs loader work.

## F. AWS IAM

| Role | Allowed | Explicitly not allowed |
|---|---|---|
| workload | `s3:GetObjectVersion` for version-specific artifact reads; `cloudwatch:PutMetricData` and `logs:PutLogEvents` to its own namespaces and streams; `kms:Decrypt` on the storage key for those objects. | Any write to artifacts, manifests, evidence, or audit; `kms:Sign` or `kms:GenerateMac`; approving anything. |
| collector | Read Zeek/OpenCanary/GPU sources; conditionally create evidence and audit batch objects; `kms:Sign` or `kms:GenerateMac` on the evidence key. | Delete evidence or replace existing keys; write artifacts or manifests. |
| publisher/approver | `s3:PutObject` to artifacts and manifests; `kms:Sign` on the manifest key; write the approval audit record. Used by a person or CI job outside the VPC. | Run as an instance role inside the VPC; delete audit history. |
| auditor | `s3:GetObject` and `s3:GetObjectVersion` on required objects; `kms:Verify` or `kms:VerifyMac`; `kms:GetPublicKey`; read CloudTrail and CloudWatch. | Any write. |

An explicit version read requires `s3:GetObjectVersion`, whereas an unversioned
read uses `s3:GetObject`. IAM does not interpret this project's manifest: limiting
a role to exactly approved versions needs separately maintained policy conditions
or a controlled artifact service. The application must still verify the approved
manifest before consuming bytes. [GetObject permissions](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html).

All of these are roles assumed with temporary STS credentials; no long-lived
access keys. Two facts shape the design. First, an EC2 instance profile's
credentials are served by the instance metadata service (use IMDSv2) to anything
on that host that can reach it, so an instance role is a per-host identity, not a
per-process or per-container one. If worker and collector ever share a host,
they share its role. Separate instances, or ECS task roles with IMDS access
blocked from containers, are how to separate them. Second, the workload must
never hold `kms:Sign` on the manifest key or write access to the pointer, so it
cannot approve its own baseline, and no role in the VPC may delete audit objects.

Missing: policy documents; a credential provider setting in configuration; a
test that the workload role is denied `PutObject` on manifests.

## G. AWS KMS

The proposal separates storage encryption from document authentication. The local
implementation provides authentication only; it does not encrypt assets:

- A symmetric encryption key (`SYMMETRIC_DEFAULT`) for SSE-KMS on the buckets.
  Its policy grants `kms:GenerateDataKey` to writers and `kms:Decrypt` to readers.
  Symmetric KMS keys encrypt and decrypt; they do not sign.
- A signing key for manifests and evidence. Either an asymmetric key pair with
  key usage `SIGN_VERIFY` (RSA or ECC key specs) where `kms:Sign` and
  `kms:Verify` are separate permissions and the public key can be exported with
  `GetPublicKey` for offline verification, or a KMS HMAC key used through
  `GenerateMac` and `VerifyMac`, whose key material never leaves KMS. The HMAC
  key message limit is 4,096 bytes, so the input would be the SHA-256 digest of
  the canonical manifest or bundle, not the document itself. The same digest-first
  approach works for the proposed RSA/ECC `Sign` algorithms when `MessageType`
  is `DIGEST`, avoiding a second hash. [Sign API](https://docs.aws.amazon.com/kms/latest/APIReference/API_Sign.html).

How this differs from the local approach: locally, anyone who can read
`integrity.key` can both create and verify tags, and the key file is the weak
point. In KMS the private key or HMAC material cannot be read by anyone; the key
policy decides which role may sign (publisher for manifests, collector for
evidence) and which may verify (auditor, workload), and every `Sign` call is a
CloudTrail event tied to a role. Separation of signing from the workload becomes a
policy statement instead of a file permission. The limits stay: a valid signature
proves who signed and that content is unchanged, not that the approved content
was correct or that a sensor measured truthfully, and encryption alone says
nothing about approval.

Missing: a `KmsAuthenticator` implementing `security.authenticators.Authenticator`
(`algorithm`, `key_id`, `sign`, `verify`). `integrity.authenticate` and
`verify_authenticated` already delegate to that interface using canonical bytes;
`LocalHmacAuthenticator` is the only implementation. A future adapter would hash
inside its `sign`/`verify` methods as required and identify that format with a
distinct algorithm label. Digest-first KMS HMAC is not the existing raw-document
HMAC format. The compatibility field `auth.mac` would hold a hex-encoded tag or
signature. Key selection must come from trusted configuration, not an untrusted
document's key ID. No KMS calls or configuration are implemented.

## H. AWS CloudTrail

A trail covering management events records IAM policy changes, KMS key policy
changes, bucket policy changes, role assumptions, and every `kms:Sign`. S3
object-level reads and writes are data events and are not logged by default; they
must be enabled with event selectors (or advanced event selectors for field
filtering) on the artifacts, manifests, evidence, and audit buckets, and they are
billed separately. Without data events, "who read this dataset" has no answer in
CloudTrail.

Log file integrity validation, when enabled on the trail, delivers signed digest
files alongside the logs. That produces the material for validation; the
validation itself still has to be run (`aws cloudtrail validate-logs`) against the
files in their original S3 location. CloudTrail validates CloudTrail's own logs.
It does not authenticate this project's evidence bundles or audit JSONL; those
still rely on the KMS signature from section G.

Missing: nothing in code; this is account configuration. The auditor runbook
should include the validate-logs command and which buckets have data events on.

## I. AWS Systems Manager

Administrative access uses Session Manager instead of SSH: no inbound port, no
key pair, no public IP. Requirements for private instances are SSM Agent on the
AMI, an instance role that includes `AmazonSSMManagedInstanceCore`, and reachable
`ssm` and `ssmmessages` endpoints over HTTPS, which in a VPC with
no internet gateway means the interface endpoints from section B. `ec2messages`
is supported only in regions launched before 2024; agents from 3.3.40.0 prefer
`ssmmessages` when available. Check the chosen agent and region rather than
requiring all three. [Agent endpoint reference](https://docs.aws.amazon.com/systems-manager/latest/userguide/systems-manager-setting-up-messageAPIs.html). Session
logging to CloudWatch Logs or S3 is optional and needs extra permissions. Parameter
Store or Run Command can distribute `settings.json` changes; the current Compose
practice of restarting a service after a Python change becomes a Run Command or a
new AMI.

Missing: an AMI with the agent; a decision on session logging; a parameter layout
for configuration.

## J. Optional: Amazon Braket

Braket is an extension of the original quantum-detector research in lessons 5
through 8, not part of the telemetry, network, or integrity path, and nothing
above depends on it. If used, it runs from the benchmark CLI, outside the VPC,
under a separate role with `braket:CreateQuantumTask` and write access to a
results bucket. The PennyLane plugin is `amazon-braket-pennylane-plugin` with the
`braket.aws.qubit` device. Device availability changes: the official device page
currently lists managed simulators SV1 and DM1 and QPUs from several providers,
with ARNs that differ from the examples in lesson 8, and TN1 is no longer listed
among current simulators. Read the device list and the pricing page before
planning a run rather than copying any ARN or cost figure from this repository.

Missing: a Braket device option in `QuantumConfig`, result handling for
`s3_destination_folder`, and a recorded run in `results.md`.

## Flows

**Telemetry.** Workload instance publishes GPU samples (simulated, or agent
collected for the real option) to CloudWatch with source identity and event time;
collector reads them through a CloudWatch adapter into `TelemetryBatch.gpu`.

**Network.** Zeek on the workload host or on a mirror sensor writes `conn.log`;
OpenCanary writes its event log on the decoy; both ship to CloudWatch Logs and
stay on local disk for the collector's seconds-level reads. Flow Logs, if enabled,
land in S3 as a slower, aggregated second opinion.

**Artifacts.** Publisher uploads a dataset or model to the artifacts bucket,
records its version id, builds the manifest, signs it with the manifest key,
uploads the manifest and the signed pointer. Workload reads only the versions the
pointer's manifest names and verifies the signature before use. Approval sequence:

```text
publisher: PutObject artifact  ->  version id V
publisher: build manifest N (asset ids, version ids, sha256)  ->  kms:Sign(digest)  ->  PutObject manifest N
publisher: pointer {baseline_version: N, manifest_sha256}  ->  kms:Sign  ->  PutObject approved.json (new version)
workload : GetObject approved.json  ->  kms:Verify  ->  GetObject manifest N  ->  compare digest, kms:Verify
workload : GetObject artifact @ V  ->  sha256 == manifest entry  ->  consume those bytes
auditor  : same reads, kms:Verify, plus CloudTrail data events for who wrote what
```

**Evidence.** Collector exports a snapshot, seals it (digest plus `kms:Sign` by the
collector role), writes it to the evidence bucket under Object Lock, and appends
the audit record. Auditor verifies with `kms:Verify` and replays with
`python -m qdc_anomaly.lab replay`.

## Mapping from existing code

| Existing boundary | AWS counterpart | Change needed |
|---|---|---|
| `SourceAdapter.read(CollectionContext)` | CloudWatch metrics and logs adapters | New adapter classes; `Collector` signature unchanged. |
| `TelemetryBatch` and rule packs | Unchanged | None. Rules run on the monitoring instance. |
| `storage.append_event` for evidence files | Local disk plus upload of sealed exports | Upload step after `seal_evidence`. |
| `security.assets.AssetInventory` | Exact S3 bucket and object version bindings | Optional schema 2 `location` now exists; remote-only inventory loading and cloud configuration remain missing. |
| `security.authenticators.Authenticator` | KMS Sign/Verify or GenerateMac/VerifyMac | Interface exists; implement a KMS adapter with explicit algorithm/digest semantics. Only local HMAC ships. |
| `security.backends.ArtifactBackend` | S3 artifact reads, conditional writes, digests, and listing | Interface exists; implement an S3 adapter with version binding and cloud error handling. Only local directory storage ships. |
| `security.store.GuardedStore` | Same policy decisions over a supplied backend | Injection exists; IAM enforcement and caller authentication remain separate future work. |
| `security.integrity.BaselineStore` | Remote manifests and approval pointer | Still filesystem-based; needs separate persistence and concurrency work. The artifact interface alone does not move these files. |
| `security.audit.AuditLog` | Local JSONL plus uploaded batch objects | Upload, retention, and write-once controls are missing; schema can remain. |
| `python -m qdc_anomaly.security verify` | Auditor job | CLI currently constructs local implementations only; cloud configuration/wiring remains missing. |

## Limitations and validation requirements

- Running this proposal needs account configuration, images, and policies that do
  not exist here. Local interfaces are implemented; cloud adapters and deployment
  work listed in the "missing" rows are not.
- Mirrored traffic must be compared against host-local capture before any claim
  that findings match the local lab. Expect differences in timing and drops.
- Flow Logs cannot support the current seconds-level rules without redesign and a
  new validation cycle.
- The GPU path remains simulated until a GPU instance, driver, and collector are
  set up and the adapter is validated against real units (MB versus MiB,
  sampling period semantics).
- An instance role is a host identity. Process-level attribution of a GPU
  allocation and a socket is still not solved by this design.
- IAM enforces what the local store can only promise, but only through the
  services; a compromised instance can still read anything its role can read.
- Signatures establish origin and integrity, never the truth of a measurement or
  the correctness of approved content.
- Costs (data events, interface endpoints per availability zone, metric volume,
  Braket tasks) were not estimated.

## Official references

- CloudWatch agent NVIDIA GPU metrics: https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Agent-NVIDIA-GPU.html
- CloudWatch agent configuration reference: https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Agent-Configuration-File-Details.html
- NVIDIA DCGM exporter: https://docs.nvidia.com/datacenter/cloud-native/gpu-telemetry/latest/dcgm-exporter.html
- EC2 accelerated computing instances: https://docs.aws.amazon.com/ec2/latest/instancetypes/ac.html
- NVIDIA drivers on EC2: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/install-nvidia-driver.html
- Traffic Mirroring sessions, targets, limitations: https://docs.aws.amazon.com/vpc/latest/mirroring/traffic-mirroring-sessions.html , https://docs.aws.amazon.com/vpc/latest/mirroring/traffic-mirroring-targets.html , https://docs.aws.amazon.com/vpc/latest/mirroring/traffic-mirroring-network-limitations.html
- VPC Flow Logs and record fields: https://docs.aws.amazon.com/vpc/latest/userguide/flow-logs.html , https://docs.aws.amazon.com/vpc/latest/userguide/flow-log-records.html
- Gateway and interface endpoints: https://docs.aws.amazon.com/vpc/latest/privatelink/vpce-gateway.html , https://docs.aws.amazon.com/vpc/latest/privatelink/vpce-interface.html
- S3 Block Public Access, versioning, SSE-KMS, Object Lock: https://docs.aws.amazon.com/AmazonS3/latest/userguide/configuring-block-public-access-bucket.html , https://docs.aws.amazon.com/AmazonS3/latest/userguide/Versioning.html , https://docs.aws.amazon.com/AmazonS3/latest/userguide/UsingKMSEncryption.html , https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html
- Instance role credentials via IMDS: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/instance-metadata-security-credentials.html
- ECS task roles and container IMDS blocking: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-iam-roles.html
- KMS key specs, Sign, Verify, HMAC keys: https://docs.aws.amazon.com/kms/latest/developerguide/symm-asymm-choose-key-spec.html , https://docs.aws.amazon.com/kms/latest/APIReference/API_Sign.html , https://docs.aws.amazon.com/kms/latest/APIReference/API_Verify.html , https://docs.aws.amazon.com/kms/latest/developerguide/hmac.html
- CloudTrail data events, management events, log validation: https://docs.aws.amazon.com/awscloudtrail/latest/userguide/logging-data-events-with-cloudtrail.html , https://docs.aws.amazon.com/awscloudtrail/latest/userguide/logging-management-events-with-cloudtrail.html , https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-log-file-validation-cli.html
- Session Manager prerequisites: https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-prerequisites.html
- Braket devices, simulators, pricing: https://docs.aws.amazon.com/braket/latest/developerguide/braket-devices.html , https://docs.aws.amazon.com/braket/latest/developerguide/choose-a-simulator.html , https://aws.amazon.com/braket/pricing/
