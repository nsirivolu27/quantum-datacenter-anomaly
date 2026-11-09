# Proposed AWS architecture

**Status: proposed, not deployed.** Nothing in this repository reads from or
writes to AWS. No account was configured, no resource was created, and no
deployment template exists. This page describes how AWS services could host the
lab from [the local security lab](09-local-security-lab.md) and
[data security and integrity](13-data-security-and-integrity.md), and it lists
what is still missing in code before any of it could run.

AWS facts below were checked against the official documentation linked at the
end on 2026-11-04. The local integration interfaces and the S3, KMS, and Systems
Manager corrections were reviewed on 2026-11-05. Service behavior changes, so
re-check before building.

## How to read this page

1. [The idea in one paragraph](#the-idea-in-one-paragraph)
2. [What exists today](#what-exists-today)
3. [The picture](#the-picture)
4. [Who may do what](#who-may-do-what)
5. [One service at a time](#one-service-at-a-time), each with the same three parts: what it does here, what to watch out for, what is missing
6. [How data moves](#how-data-moves)
7. [What changes in the code](#what-changes-in-the-code)
8. [Limits](#limits) and [references](#official-references)

## The idea in one paragraph

Three machines sit in a private network with no internet gateway. The
**workload** instance runs the GPU work and the traffic generator. The
**monitoring** instance runs Zeek, the Python collector, and the rule packs. The
**decoy** instance runs OpenCanary and nothing else. They reach AWS services only
through private endpoints. GPU numbers go to CloudWatch, logs go to CloudWatch
Logs, artifacts and evidence go to S3 under version locks, signatures come from
KMS, and CloudTrail records who did what. People get in through Session Manager,
not SSH. The rules that decide what is an anomaly stay exactly where they are
today: in `framework.py` on the monitoring instance.

## What exists today

| Item | Actual state |
|---|---|
| CloudWatch loader (`src/qdc_anomaly/data/cloudwatch.py`) | Does not exist. Older text in lessons 2 and 8 described it as present; both lessons now say so. `qdc score --input` reads any CSV with the expected columns. |
| Amazon Braket examples (lesson 8) | Code snippets only. The device ARNs are historical examples, the S3 destination is a placeholder, and nothing in `src/` calls Braket. |
| `boto3` in `pyproject.toml` | Listed under the optional `aws` extra. No module imports it. |
| Local security package | `Authenticator` and `ArtifactBackend` interfaces exist, with local HMAC and directory implementations only. Inventory schema 2 supports optional locations. No cloud signing or storage. |

Everything below is a design. The "Missing" lines are the work list.

## The picture

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

Subnets separate blast radius and routing. They are not access control. Security
groups, IAM policies, bucket policies, and KMS key policies are what decide who
may do what.

## Who may do what

Four roles, and none of them share credentials. The publisher is a person or a CI
job outside the VPC, never an instance inside it.

| Role | Runs where | Allowed | Explicitly not allowed |
|---|---|---|---|
| workload | Workload instance | Read specific artifact versions (`s3:GetObjectVersion`). Publish its own metrics and logs (`cloudwatch:PutMetricData`, `logs:PutLogEvents`). Decrypt those objects (`kms:Decrypt` on the storage key). | Write artifacts, manifests, evidence, or audit. `kms:Sign` or `kms:GenerateMac`. Approve anything. |
| collector | Monitoring instance | Read Zeek, OpenCanary, and GPU sources. Create evidence and audit batch objects, conditionally. Sign evidence (`kms:Sign` or `kms:GenerateMac` on the evidence key). | Delete evidence or replace existing keys. Write artifacts or manifests. |
| publisher / approver | A person or CI job outside the VPC | `s3:PutObject` to artifacts and manifests. `kms:Sign` on the manifest key. Write the approval audit record. | Run as an instance role inside the VPC. Delete audit history. |
| auditor | Anywhere with read access | `s3:GetObject` and `s3:GetObjectVersion` on required objects. `kms:Verify` or `kms:VerifyMac`, `kms:GetPublicKey`. Read CloudTrail and CloudWatch. | Any write. |

Two facts shape this table.

- An instance role is a per host identity, not a per process one. Its credentials
  are served by the instance metadata service (use IMDSv2) to anything on that
  host. If the worker and collector ever share a host, they share its role.
  Separate instances, or ECS task roles with container access to IMDS blocked,
  are how to keep them apart.
- The workload must never hold `kms:Sign` on the manifest key or write access to
  the approved pointer, so it cannot approve its own baseline. No role inside the
  VPC may delete audit objects.

All roles use temporary STS credentials. No long lived access keys.

Missing: policy documents; a credential provider setting in configuration; a
test that the workload role is denied `PutObject` on manifests.

## One service at a time

### A. Amazon EC2: the three machines

What runs where:

| Component today | Proposed placement | Notes |
|---|---|---|
| `lab/worker.py` traffic generator | Workload instance | Same fixed peers, now other instances or private DNS names instead of Compose service names. |
| `lab/simulator.py` GPU samples | Workload instance, initial option | Stays simulated and labeled `simulated: true` as today. |
| Real GPU metrics | Separate future option | A GPU instance family (G6, G6e, P5 for example) with the NVIDIA driver, or an AMI that ships it. The CloudWatch agent's `nvidia_gpu` section or the DCGM exporter then replaces the simulator. Nothing else in this design needs it. |
| Zeek | Monitoring instance, or on the workload host | See section C. |
| OpenCanary | Decoy instance in its own subnet | Only the HTTP decoy, as in `lab/opencanary.conf`. |
| Python detection and correlation (`lab/collector.py`, `lab/framework.py`, `security/`) | Monitoring instance | Reads local or mirrored sensor output plus CloudWatch, writes findings and evidence. |

Watch out for: no instance has a public IP, so software arrives through a
prepared AMI or from an S3 bucket you control through the gateway endpoint.
Private subnets cannot reach package registries without a NAT gateway or a proxy,
and either of those is one more thing to secure.

Missing: an AMI or user data build that installs the package; a systemd unit per
role; an EC2 variant of `lab/settings.json` that names peers by private DNS.

### B. Amazon VPC: the private network

What it does here:

- One VPC, no internet gateway, three private subnets (workload, monitoring,
  decoy), each with its own route table.
- Security groups do the real work. The workload may reach the API peer, the
  receiver, and the decoy on their service ports and nothing else. The decoy
  accepts from the workload subnet only. The monitoring instance accepts VXLAN
  (UDP 4789) from mirror sources and nothing else inbound. Egress is limited to
  the declared peer ports, the endpoint security groups on 443, and the S3
  managed prefix list on 443.
- Interface endpoints (PrivateLink) for CloudWatch Logs (`logs`), CloudWatch
  (`monitoring`), KMS, STS, `ssm`, and `ssmmessages`. A gateway endpoint for S3
  in every route table. Endpoint policies can narrow which buckets or keys are
  reachable through them.

Watch out for:

- A broad allow to the whole VPC CIDR would defeat the peer restrictions.
- Network ACLs are a coarse backstop only. They cannot reference prefix lists, so
  if you use them, the S3 prefix list must be allowed by CIDR range.
- Private DNS must be on for the default service hostnames to resolve to the
  endpoints.
- `ec2messages` is a legacy endpoint that depends on region and agent version,
  not a universal requirement. See section I.

Missing: everything. No VPC definition exists in this repository, and the request
for this document excluded generating one.

### C. Network collection: three ways to see traffic

| Option | What it gives | Fit with the current code |
|---|---|---|
| Host local Zeek on the workload instance | The same `conn.log` as today, same latency, same fields. | `adapters.py` reads it unchanged once the path is set. The preferred first step. |
| VPC Traffic Mirroring to a dedicated sensor | Packet copies of the workload network interface, VXLAN encapsulated, delivered to an interface, NLB, or Gateway Load Balancer endpoint. Zeek on the sensor must decapsulate VXLAN (listen on UDP 4789). | The output is the same log, so `adapters.py` still works, but timing and drop behavior must be validated before claiming it matches the local lab. |
| VPC Flow Logs | Per flow metadata (addresses, ports, protocol, packets, bytes, start and end, action) to CloudWatch Logs, S3, or Firehose. No payload, no Zeek style connection state. | Does not fit the seconds level rules: `port-spread` uses 20 second windows, `periodic-connection` needs individual connection timestamps, correlation uses a 5 second window. Flow Logs are extra evidence, not a replacement. |

Watch out for, with mirroring: it is out of band, so it observes and never
blocks, and it cannot decrypt TLS. Mirrored traffic counts against the source's
bandwidth and is dropped first under pressure. Not every instance type can be a
source. ARP, DHCP, IMDS, and NTP are not mirrored.

Watch out for, with Flow Logs: aggregation is 10 minutes by default, 1 minute as
an option (Nitro instances report at 1 minute or less). Delivery typically lags
about 5 minutes to CloudWatch Logs and about 10 minutes to S3. Flow Logs do not
include mirrored traffic.

Missing: a `FlowLogAdapter` if Flow Logs are ever used; a sensor AMI with Zeek
configured for VXLAN; a validation script that compares mirrored and host local
`conn.log` for the same traffic cycle.

### D. Amazon CloudWatch: where the numbers and logs go

What flows in:

- GPU measurements. Simulated samples become custom metrics with a dimension such
  as `source=simulated`, keeping the label the code already carries. Real
  measurements come from the CloudWatch agent's `nvidia_gpu` section, which runs
  on Linux hosts with the NVIDIA driver and `nvidia-smi` installed and publishes
  metrics prefixed `nvidia_smi_` (including `utilization_gpu`, `memory_used`,
  `temperature_gpu`, `power_draw`) with `index`, `name`, and `arch` dimensions.
  The agent documentation lists this section for Linux only.
- Zeek and OpenCanary logs through the agent's log collection, one log group per
  source, keeping the original JSON line and its own timestamp.
- Application findings and source health signals (`health` in the snapshot) as a
  structured log stream from the collector.

Watch out for:

- Identity and time must survive the trip. The collector joins records by
  `node_id`, worker IP, and event time, and keeps `generated_at` separate from
  observation time. Publishing must keep those fields, not swap in ingestion time.
- CloudWatch has no idea whether a job is approved. `job_approved` still has to
  come from a scheduler or identity source.
- CloudWatch does not run the Python rule packs. Threshold alarms are possible,
  but the cross source rules stay in `framework.py` on the monitoring instance.
  A container or Lambda version is not proposed here.

Missing: a `CloudWatchMetricAdapter` and `CloudWatchLogsAdapter` implementing the
`SourceAdapter` protocol; the agent configuration files; the `data/cloudwatch.py`
loader for the benchmark CLI, which would read metric data into the `qdc score`
CSV layout.

### E. Amazon S3: four buckets, each locked differently

| Bucket | Holds | Controls |
|---|---|---|
| artifacts | Approved datasets, model artifacts, configuration | Versioning on. SSE-KMS with the storage key. Block Public Access on. Bucket policy: writes only from the publisher role, reads from the workload and collector roles. Manifests name the exact object version id, so "approved" means a specific version, never "latest". |
| manifests | Baseline manifests and the approved pointer | Same, plus writes allowed only to the approver role. Object Lock in compliance mode on manifest versions if retention is justified. |
| evidence | Sealed evidence exports | The collector writes unique keys with conditional creation and has no delete permission. Object Lock in governance mode with a chosen retention; legal hold for anything under review. |
| audit | Exported audit batches and CloudTrail logs, in separate prefixes | Application audit batches are new objects, never in place JSONL appends. The auditor reads. Deletion and lifecycle respect retention. CloudTrail writes its own prefix through its service policy. |

Watch out for:

- Object Lock needs versioning on. It protects specific object versions from
  deletion or overwrite for the retention period. Compliance mode cannot be
  shortened by anyone; governance mode can be bypassed by principals with
  `s3:BypassGovernanceRetention`.
- Object Lock does not stop new versions from being written, and it does not make
  the newest version trustworthy. That is exactly why the approved pointer from
  lesson 13 is still needed: the pointer names which manifest version is approved,
  and the manifest names which artifact versions are approved.
- `PutObject` permission alone does not stop someone writing another version at
  an existing key. The evidence writer must use `If-None-Match: *`, enforced by
  bucket policy, with unique keys and retention controls. See
  [conditional writes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html).

Missing: an `S3ArtifactBackend` implementing `security.backends.ArtifactBackend`,
with a relative path to bucket and version map built from the inventory; remote
manifest and pointer persistence; audit and evidence uploads; CLI wiring;
retention and concurrency decisions. The local backend rejects S3 locations, and
inventory loading still requires a local root, so a remote only inventory also
needs loader work.

### F. AWS IAM: the permissions behind the role table

The role table above is the design. Two details matter when writing the policies:

- Reading an explicit version requires `s3:GetObjectVersion`; an unversioned read
  uses `s3:GetObject`. See
  [GetObject permissions](https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObject.html).
- IAM does not understand this project's manifest. Limiting a role to exactly the
  approved versions needs separately maintained policy conditions or a controlled
  artifact service. The application must still verify the approved manifest before
  it consumes any bytes.

Missing: see the role table.

### G. AWS KMS: encryption and signatures are two different keys

- A symmetric key (`SYMMETRIC_DEFAULT`) for SSE-KMS on the buckets. Writers get
  `kms:GenerateDataKey`, readers get `kms:Decrypt`. Symmetric keys encrypt and
  decrypt; they do not sign.
- A signing key for manifests and evidence. Two options:
  - An asymmetric key pair with key usage `SIGN_VERIFY` (RSA or ECC). `kms:Sign`
    and `kms:Verify` are separate permissions, and the public key can be exported
    with `GetPublicKey` for offline verification.
  - A KMS HMAC key used through `GenerateMac` and `VerifyMac`. The key material
    never leaves KMS. The message limit is 4,096 bytes, so the input would be the
    SHA-256 digest of the canonical manifest or bundle, not the document itself.
    The same digest first approach works for RSA and ECC `Sign` when
    `MessageType` is `DIGEST`. See the [Sign API](https://docs.aws.amazon.com/kms/latest/APIReference/API_Sign.html).

Why this is better than the local setup: locally, anyone who can read
`integrity.key` can both create and verify tags, and that file is the weak point.
In KMS nobody can read the private key or HMAC material. The key policy decides
which role may sign (publisher for manifests, collector for evidence) and which
may verify (auditor, workload), and every `Sign` call is a CloudTrail event tied
to a role. Separating signing from the workload becomes a policy statement
instead of a file permission.

What does not change: a valid signature proves who signed and that the content is
unchanged. It does not prove the approved content was correct or that a sensor
measured truthfully. Encryption alone says nothing about approval.

Missing: a `KmsAuthenticator` implementing `security.authenticators.Authenticator`
(`algorithm`, `key_id`, `sign`, `verify`). `integrity.authenticate` and
`verify_authenticated` already delegate to that interface using canonical bytes;
`LocalHmacAuthenticator` is the only implementation. The KMS adapter would hash
inside `sign` and `verify` and label that format with a distinct algorithm name,
since digest first KMS HMAC is not the existing raw document HMAC format. The
compatibility field `auth.mac` would hold a hex encoded tag or signature. Key
selection must come from trusted configuration, never from an untrusted
document's key id. No KMS calls or configuration are implemented.

### H. AWS CloudTrail: the record of who did what

What it does here: a trail covering management events records IAM policy
changes, KMS key policy changes, bucket policy changes, role assumptions, and
every `kms:Sign`.

Watch out for:

- S3 object reads and writes are data events and are not logged by default. They
  must be enabled with event selectors (or advanced event selectors for field
  filtering) on the artifacts, manifests, evidence, and audit buckets, and they
  are billed separately. Without data events, "who read this dataset" has no
  answer.
- Log file integrity validation, when enabled, delivers signed digest files next
  to the logs. That produces the material; the validation still has to be run
  (`aws cloudtrail validate-logs`) against the files in their original S3
  location.
- CloudTrail validates CloudTrail's own logs. It does not authenticate this
  project's evidence bundles or audit JSONL; those rely on the KMS signature from
  section G.

Missing: nothing in code; this is account configuration. The auditor runbook
should include the validate-logs command and which buckets have data events on.

### I. AWS Systems Manager: how people get in

What it does here: Session Manager replaces SSH. No inbound port, no key pair,
no public IP. Parameter Store or Run Command distributes `settings.json`
changes; today's "restart the Compose service after a Python change" becomes a
Run Command or a new AMI.

Watch out for:

- Private instances need SSM Agent on the AMI, an instance role that includes
  `AmazonSSMManagedInstanceCore`, and reachable `ssm` and `ssmmessages` endpoints
  over HTTPS, which with no internet gateway means the interface endpoints from
  section B.
- `ec2messages` is supported only in regions launched before 2024, and agents
  from 3.3.40.0 prefer `ssmmessages` when available. Check the chosen agent and
  region rather than requiring all three. See the
  [agent endpoint reference](https://docs.aws.amazon.com/systems-manager/latest/userguide/systems-manager-setting-up-messageAPIs.html).
- Session logging to CloudWatch Logs or S3 is optional and needs extra
  permissions.

Missing: an AMI with the agent; a decision on session logging; a parameter layout
for configuration.

### J. Optional: Amazon Braket

Braket extends the quantum detector research in lessons 5 through 8. It is not
part of the telemetry, network, or integrity path, and nothing above depends on
it. If used, it runs from the benchmark CLI, outside the VPC, under a separate
role with `braket:CreateQuantumTask` and write access to a results bucket. The
PennyLane plugin is `amazon-braket-pennylane-plugin` with the `braket.aws.qubit`
device.

Watch out for: device availability changes. The official device page currently
lists managed simulators SV1 and DM1 and QPUs from several providers, with ARNs
that differ from the examples in lesson 8, and TN1 is no longer listed among
current simulators. Read the device list and the pricing page before planning a
run rather than copying any ARN or cost figure from this repository.

Missing: a Braket device option in `QuantumConfig`, result handling for
`s3_destination_folder`, and a recorded run in `results.md`.

## How data moves

**Telemetry.** The workload publishes GPU samples (simulated, or agent collected
for the real option) to CloudWatch with source identity and event time. The
collector reads them through a CloudWatch adapter into `TelemetryBatch.gpu`.

**Network.** Zeek on the workload host or on a mirror sensor writes `conn.log`.
OpenCanary writes its event log on the decoy. Both ship to CloudWatch Logs and
stay on local disk for the collector's seconds level reads. Flow Logs, if enabled,
land in S3 as a slower, aggregated second opinion.

**Artifacts.** The publisher uploads a dataset or model, records its version id,
builds the manifest, signs it with the manifest key, and uploads the manifest and
the signed pointer. The workload reads only the versions the pointer's manifest
names and verifies the signature before use. Step by step:

```text
publisher: PutObject artifact  ->  version id V
publisher: build manifest N (asset ids, version ids, sha256)  ->  kms:Sign(digest)  ->  PutObject manifest N
publisher: pointer {baseline_version: N, manifest_sha256}  ->  kms:Sign  ->  PutObject approved.json (new version)
workload : GetObject approved.json  ->  kms:Verify  ->  GetObject manifest N  ->  compare digest, kms:Verify
workload : GetObject artifact @ V  ->  sha256 == manifest entry  ->  consume those bytes
auditor  : same reads, kms:Verify, plus CloudTrail data events for who wrote what
```

**Evidence.** The collector exports a snapshot, seals it (digest plus `kms:Sign`
by the collector role), writes it to the evidence bucket under Object Lock, and
appends the audit record. The auditor verifies with `kms:Verify` and replays with
`python -m qdc_anomaly.lab replay`.

## What changes in the code

| Existing boundary | AWS counterpart | Change needed |
|---|---|---|
| `SourceAdapter.read(CollectionContext)` | CloudWatch metrics and logs adapters | New adapter classes; `Collector` signature unchanged. |
| `TelemetryBatch` and rule packs | Unchanged | None. Rules run on the monitoring instance. |
| `storage.append_event` for evidence files | Local disk plus upload of sealed exports | Upload step after `seal_evidence`. |
| `security.assets.AssetInventory` | Exact S3 bucket and object version bindings | Optional schema 2 `location` exists; remote only inventory loading and cloud configuration are missing. |
| `security.authenticators.Authenticator` | KMS Sign/Verify or GenerateMac/VerifyMac | Interface exists; implement a KMS adapter with explicit algorithm and digest semantics. Only local HMAC ships. |
| `security.backends.ArtifactBackend` | S3 reads, conditional writes, digests, listing | Interface exists; implement an S3 adapter with version binding and cloud error handling. Only local directory storage ships. |
| `security.store.GuardedStore` | Same policy decisions over a supplied backend | Injection exists; IAM enforcement and caller authentication remain future work. |
| `security.integrity.BaselineStore` | Remote manifests and approval pointer | Still filesystem based; needs persistence and concurrency work. The artifact interface alone does not move these files. |
| `security.audit.AuditLog` | Local JSONL plus uploaded batch objects | Upload, retention, and write once controls are missing; the schema can stay. |
| `python -m qdc_anomaly.security verify` | Auditor job | The CLI builds local implementations only; cloud configuration and wiring are missing. |

## Limits

- Running this proposal needs account configuration, images, and policies that do
  not exist here. Local interfaces are implemented; the cloud adapters and
  deployment work in the "Missing" lines are not.
- Mirrored traffic must be compared with host local capture before any claim that
  findings match the local lab. Expect differences in timing and drops.
- Flow Logs cannot support the current seconds level rules without a redesign and
  a new validation cycle.
- The GPU path stays simulated until a GPU instance, driver, and collector are set
  up and the adapter is validated against real units (MB versus MiB, sampling
  period semantics).
- An instance role is a host identity. Process level attribution of a GPU
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
