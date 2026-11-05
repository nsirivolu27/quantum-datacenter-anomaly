# GPU metrics and data center security

The question studied here is whether resource measurements and network evidence
can help distinguish expected work, equipment problems, and activity that needs
security investigation. GPU measurements describe hardware use. They do not
identify the owner of a job or determine whether it is authorized.

## What the measurements mean

| Measurement | What to examine | What it cannot establish alone |
|---|---|---|
| GPU utilization | How busy the GPU is during a sampling interval; compare with the scheduled workload. | Whether the workload is malicious or useful. |
| GPU memory used | Device memory occupied by workloads; compare with job requirements and capacity. | Which data is stored there or whether it was accessed without permission. |
| Temperature | GPU temperature in °C; compare with load, cooling conditions, and hardware limits. | Whether overheating was caused intentionally. |
| Power draw | Watts consumed; compare with workload and configured power limits. | Whether high consumption is unauthorized. |

NVIDIA documents GPU utilization as activity during a sampling period rather than
a percentage of theoretical computing performance. Supported measurements and
their behavior depend on the device and environment. Use the actual collector's
units, including MB versus MiB, rather than assuming they are interchangeable.
See [NVIDIA System Management Interface](https://docs.nvidia.com/deploy/nvidia-smi/index.html).

This lab uses a Python simulator for all four measurements. Its temperature,
utilization, and transfer thresholds are teaching parameters, not universal
hardware limits. It does not read the machine's GPU or run a GPU workload.

## Why network evidence matters

Zeek's connection log records network endpoints, timing, ports, protocol, byte
counts, and connection state. Those fields support questions about which systems
communicated and whether a pattern changed. They do not establish what data was
stolen. In particular, this project's combined byte count includes both directions
and must not be described as bytes exfiltrated. See the
[Zeek 8.0.11 connection-log reference](https://docs.zeek.org/en/v8.0.11/logs/conn.html).

OpenCanary supplies an independent signal when a worker contacts a decoy service.
The lab's policy says the approved workload has no reason to contact that service.
A hit is therefore worth investigating, while its cause still needs explanation.
OpenCanary's own capabilities and deployment requirements are documented in its
[official repository](https://github.com/thinkst/opencanary).

## What each experiment establishes

| Experiment | Evidence generated | Supported interpretation |
|---|---|---|
| Approved training load | High simulated utilization, approved job flag, normal API requests | High utilization can be expected behavior. |
| Cooling fault | High temperature, normal network path | An operational anomaly can exist without a security event. |
| Decoy probes | Several connection attempts and an OpenCanary HTTP event | The worker attempted access outside the declared workload policy. Closed-port attempts do not mean successful intrusion. |
| Repeating connections | Regular requests to an unapproved internal test receiver | A beacon-like pattern is present. Benign polling can look similar. |
| Unapproved compute and transfer | High utilization without an approved job, plus a larger network transfer | Two signals overlap in time and worker identity. Investigate job attribution and destination ownership. |
| Sustained volume | Several large transfers to one unapproved peer inside a minute | Volume is unusual for the declared workload. Byte counts include both directions and say nothing about content. |

These interpretations are specific to the controlled experiments. The receiver
accepts dummy data; the simulator does not execute malicious code. The job flag
is synthetic ground truth supplied by the experiment, not verified scheduler data.

## How anomaly detection is used

The existing QDC feature builder summarizes ten GPU samples using mean, standard
deviation, and trend for each measurement. An Isolation Forest compares that
window with synthetic normal and approved-load reference windows. Its output is
an anomaly score, not a probability of attack. It can miss a cooling fault, and
ordinary workload transitions can produce unusual scores.

Separate rules evaluate temperature, job attribution, port diversity, repeated
connections, and decoy contact. A second rule pack correlates unapproved simulated
GPU use with a sufficiently large connection within five seconds. This requires
the configured GPU node and worker source IP to match. It does not link a network
socket to a GPU process, so it cannot prove that the same process did both things.

## What data security would additionally require

This lab demonstrates observation and investigation. It does not implement access
control for datasets, verify data integrity, or encrypt stored data. A deployment
would also need answers to these questions:

- Which user or service submitted the job, and may it read this dataset?
- Which process or container owns the GPU allocation and network connection?
- Can workloads reach only their intended storage, APIs, and other workloads?
- Where are access decisions and file/object reads recorded?
- How are model files, training data, credentials, and evidence protected at rest
  and in transit?

These are design requirements beyond what utilization and flow measurements can
prove. Avoid claiming that a lack of alerts demonstrates that data is safe.

A local, explicitly limited answer to the integrity and access-policy parts of
this list is implemented in `src/qdc_anomaly/security/` and described in
[data security and integrity](13-data-security-and-integrity.md). Identity
there is a simulated label, enforcement covers only calls made through the
guarded store, and encryption is still not implemented.

## Moving from simulation to hardware

NVIDIA DCGM provides GPU telemetry and health-related capabilities. Its exporter
can expose GPU measurements for Prometheus collection. Replacing the simulator
would require a supported GPU/driver setup and an adapter that preserves timestamps,
device identity, units, and missing-value behavior. Job authorization would need
a separate scheduler or identity source. See
[DCGM feature overview](https://docs.nvidia.com/datacenter/dcgm/latest/user-guide/feature-overview.html)
and [DCGM Exporter installation](https://docs.nvidia.com/datacenter/dcgm/latest/installation/install-dcgm-exporter.html).

GPU partitioning is another separate concern. On supported hardware, NVIDIA MIG
provides separate compute and memory resources for instances. It is not enabled
or tested by this lab. See the
[NVIDIA MIG introduction](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/introduction.html).
