# CodeAtlas

CodeAtlas is a local-first repository intelligence workbench. Point it at any codebase and it produces:

- dependency sketches for Python and JS/TS projects
- hotspot ranking based on file size, TODO pressure, fan-in/fan-out, and structural warnings
- git-aware churn scoring when the target is a git repository
- documentation drift detection for broken local file references
- a built-in dashboard served with the Python standard library

The project is intentionally dependency-light so it can run in constrained environments.

## Why this could matter

Most code intelligence tooling is either too shallow, too expensive, or too hosted. CodeAtlas aims at a useful middle ground:

- instant local scans
- plain JSON output for automation
- a presentable UI for architecture reviews and team handoffs
- zero external services required

## Quick Start

```bash
cd /root/codeatlas
PYTHONPATH=src python3 -m codeatlas.cli scan .
PYTHONPATH=src python3 -m codeatlas.cli demo --port 8123
```

Then open `http://127.0.0.1:8123`.

## CLI

```bash
codeatlas scan /path/to/repo
codeatlas scan /path/to/repo --json --output report.json
codeatlas scan /path/to/repo --markdown --output report.md
codeatlas scan /path/to/repo --sarif --output report.sarif
codeatlas compare baseline.json /path/to/repo
codeatlas changes /path/to/repo --base main --head HEAD --markdown
codeatlas owners /path/to/repo
codeatlas serve /path/to/repo --port 9000
codeatlas demo
```

## What it analyzes

### Repository Signals

- file counts, line counts, language mix
- Python import relationships
- JS/TS import and `require()` relationships
- TODO, FIXME, HACK, and NOTE markers
- overly large files and dense dependency hubs
- git churn hotspots using local commit history
- broken local references inside docs
- CODEOWNERS-based ownership overlays when a repository defines them

### Output

`scan` returns either a human-readable summary or machine-readable JSON. `serve` hosts a single-page dashboard with:

- topline metrics
- ranked hotspots
- TODO feed
- lightweight dependency visualization
- interactive file drilldown with inline source preview
- ownership load table driven by `CODEOWNERS`

### CI And Review Workflows

- `--sarif` exports findings into a format that GitHub code scanning and other CI systems can ingest.
- `compare` lets you diff a stored baseline report against the current working tree to spot new TODOs, new documentation drift, and worsening hotspots.
- `changes` narrows the report to files touched between two git refs, which is useful for pull request review.
- hotspot and changed-file views inherit `CODEOWNERS` assignments so review surfaces show likely owners.
- `owners` prints owner-by-owner load and their hottest files.

### GitHub Actions

The repository includes [codeatlas.yml](/root/codeatlas/.github/workflows/codeatlas.yml), which:

- runs the test suite on `push` and `pull_request`
- uploads a SARIF report to GitHub code scanning
- writes a focused changed-file report into the PR job summary

## Roadmap

- richer parsers for more languages
- plugin system for custom heuristics
- inline code ownership and blame overlays
- commit range analysis for pull requests

## Development

```bash
cd /root/codeatlas
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## License

MIT
