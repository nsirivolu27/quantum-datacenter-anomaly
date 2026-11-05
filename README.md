# Sentinel Lab

**Inside a data center, one second at a time.**

Follow one server: watch its GPU readings, trace its network traffic, and see how
access controls and integrity checks protect its files.

![Sentinel Lab: an illustrated walkthrough of a data center server](docs/assets/sentinel-lab-preview.png)

## Explore

- [Inside the data center](site/index.html) — GPU metrics, traffic, and unusual activity.
- [The security story](site/security.html) — access controls, changed files, and evidence.

Open either HTML file in a browser to try the interactive examples. The examples
run in the page; they do not connect to a running data center.

## Behind the walkthrough

The local lab combines simulated GPU readings with Zeek network logs,
OpenCanary decoy events, and file-integrity checks. The original classical and
quantum anomaly-detection research is also included.

[Local experiments](docs/09-local-security-lab.md) ·
[Data security and integrity](docs/13-data-security-and-integrity.md) ·
[Recorded results](docs/security-results.md) ·
[Research lessons](docs/README.md)

The [AWS architecture](docs/12-aws-architecture.md) is a proposal, not deployed.

MIT licensed.
