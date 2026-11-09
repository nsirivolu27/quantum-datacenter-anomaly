# Project site

`index.html` is a single self-contained page describing the lab: architecture map,
scenario timeline, finding taxonomy, use case tree, trust boundaries, verification,
and the proposed AWS mapping. It loads fonts from Google Fonts and nothing else.

Deploy as a static site. On Vercel, import the repository, set the root directory to
`site`, framework preset "Other", no build command, output directory `.`. Keep the
numbers on the page in step with `docs/security-results.md` when runs change.
