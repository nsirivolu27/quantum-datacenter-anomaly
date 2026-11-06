# Project site

[Where Does My Picture Go?](https://nsirivolu27.github.io/quantum-datacenter-anomaly/site/book/)
is a 32-page read-together children's book for ages 5–7, with eight illustrations,
twelve interactive activities, a glossary, and a grown-up guide with sources.
The matching [printable edition](https://nsirivolu27.github.io/quantum-datacenter-anomaly/site/book/where-does-my-picture-go.pdf)
includes paper versions of the activities. Its manuscript and edition files are
in `book/`; see `book/README.md` for editing notes.

Two interactive picture books, each a self-contained page: the telemetry
walkthrough (`index.html`) and the security walkthrough (`security.html`).
Examples run in the browser with simulated inputs; hashing and HMAC sealing use
WebCrypto. Fonts load from Google Fonts.

GitHub Pages publishes the `local-security-lab` branch from `/ (root)`:

- [Inside the data center](https://nsirivolu27.github.io/quantum-datacenter-anomaly/site/)
- [The security story](https://nsirivolu27.github.io/quantum-datacenter-anomaly/site/security.html)
- [Sentinel Ops console](https://nsirivolu27.github.io/quantum-datacenter-anomaly/site/ops/) (`ops/index.html`)

Sentinel Ops draws its 3D view with the Canvas 2D API and no libraries. Detection
rules and thresholds match `src/qdc_anomaly/lab`; AWS services are the mapping in
`docs/12-aws-architecture.md`, not a deployment. Attacker traffic uses the
documentation ranges 203.0.113.0/24 and 198.51.100.0/24.

The root `.nojekyll` file keeps these HTML pages unchanged during publishing.
Future pushes to this branch update the hosted pages. Publishing from `main`
later requires changing the branch in Settings > Pages; the URLs stay the same.

The browser examples explain the lab; they do not run its containers or read live
sensor data. Keep descriptions and verification claims aligned with
`docs/security-results.md` when runs change.
