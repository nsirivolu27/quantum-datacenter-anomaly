# Sentinel Lab

**Inside a data center, one second at a time.**

Follow one server: watch its GPU readings, trace its network traffic, and see how
access controls and integrity checks protect its files.

## Try the interactive books

Nothing to install. Open a book and try the examples in your browser.

- [Inside the data center](https://nsirivolu27.github.io/quantum-datacenter-anomaly/site/) — GPU metrics, traffic, and unusual activity.
- [The security story](https://nsirivolu27.github.io/quantum-datacenter-anomaly/site/security.html) — access controls, changed files, and evidence.

The examples use simulated inputs and run in the page. They do not connect to a
running data center. Hashing and evidence-sealing examples use browser WebCrypto.

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
