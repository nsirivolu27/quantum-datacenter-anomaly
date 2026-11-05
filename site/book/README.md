# Where Does My Picture Go?

[Read the book](https://nsirivolu27.github.io/quantum-datacenter-anomaly/site/book/) ·
[Print the book](https://nsirivolu27.github.io/quantum-datacenter-anomaly/site/book/where-does-my-picture-go.pdf)

A complete 32-page book for children ages 5–7 to read with a grown-up. Maya sends
a whale picture to Grandpa. Pip, a pretend packet, guides an imagined journey
through the computers and people that help it arrive safely.

The book has eight original illustrations and twelve browser activities. Pages
1–24 tell the story; 25–29 add a safety conversation, glossary, and activities;
30–32 contain reading guidance and primary references. Print on Letter or A4
with **Fit** selected. The PDF uses landscape pages and includes paper activities.

## Editing the book

- `book.json` is the shared manuscript for both editions.
- `book.css` and `book.js` provide responsive page turns and browser activities.
- `build.py` produces `index.html` and `where-does-my-picture-go.pdf` from the
  manuscript. Authoring requires Python, ReportLab, and Pillow; readers install
  nothing. The PDF embeds Bitstream Vera fonts bundled with ReportLab.
- `assets/` contains the eight publication images. `illustration-briefs.json`
  keeps the full art direction for each image. All assets the book needs are
  included in this directory.

The complete HTML story is present before JavaScript runs. Without JavaScript,
readers can scroll through it; with JavaScript, Next/Back, an all-pages menu,
keyboard arrows, and optional device read-aloud are available. No server, account,
analytics, API key, or personal-data entry is used. Read-aloud may use a local or
provider-backed browser voice; a local English voice is preferred when available.

## Teaching boundaries

This is a fictional story about real concepts. The activities do not run the lab,
inspect hardware, authenticate users, or encrypt files. The GPU picture represents
parallel calculation. The lock represents encryption. The picture comparison
represents change detection against a trusted reference. None is a production
security mechanism. The grown-up guide explains the limits and links the sources.

The book connects the repository's GPU telemetry, traffic monitoring, and integrity
experiments without changing their detection rules or claiming cloud deployment.

## Edition verification

For this edition, all 32 browser pages were checked at desktop and 390-pixel phone
widths, with no horizontal overflow. All twelve activities were exercised,
including alternate answers and reset controls. The read-aloud start/stop control
was checked; voice availability and sound depend on the reader's device.
All 32 PDF pages were rendered for a visual layout check, and the PDF text was
checked against the manuscript. Source links appear in both editions.
