# CodeAtlas

CodeAtlas is a local-first repository intelligence workbench. Point it at any codebase and it produces:

- dependency sketches for Python and JS/TS projects
- hotspot ranking based on file size, TODO pressure, fan-in/fan-out, and structural warnings
- git-aware churn scoring when the target is a git repository
- documentation drift detection for broken local file references
- config-driven structural rules and dependency cycle detection
- lightweight code health scoring and security/manifest risk detection
- duplicate code cluster detection across files
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
codeatlas reviewers /path/to/repo --base auto --head HEAD
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
- config-defined architectural rule violations and local dependency cycles
- lightweight code health metrics and secret / manifest risk findings
- duplicate code clusters across multiple files

### Output

`scan` returns either a human-readable summary or machine-readable JSON. `serve` hosts a single-page dashboard with:

- topline metrics
- ranked hotspots
- TODO feed
- lightweight dependency visualization
- interactive file drilldown with inline source preview
- ownership load table driven by `CODEOWNERS`
- client-side filtering and display limits for hotspots, TODOs, and graph nodes
- blame authors, reviewer hints, and security feed panels
- duplicate-code clusters in report output

### Configuration

CodeAtlas auto-loads `codeatlas.json` from the repository root, and also accepts a hidden variant with the same schema. The initial schema is intentionally small:

```json
{
  "rules": [
    {
      "name": "ui-must-not-import-db",
      "from": ["src/ui/"],
      "to": ["src/db/"],
      "severity": "warning",
      "message": "UI must not depend on DB"
    }
  ]
}
```

This lets you encode simple architectural boundaries and have them appear in text, Markdown, JSON, and SARIF output.

You can also define coarse-grained layers:

```json
{
  "layers": [
    {
      "name": "ui",
      "paths": ["src/ui/"],
      "may_depend_on": ["domain"],
      "message": "UI must stay above domain"
    },
    {
      "name": "domain",
      "paths": ["src/domain/"]
    },
    {
      "name": "infra",
      "paths": ["src/infra/"]
    }
  ]
}
```

If `ui` imports `infra`, CodeAtlas reports a structural violation even if the raw import itself resolves successfully.

Security findings are configurable too:

```json
{
  "security": {
    "ignore_paths": ["tests/"],
    "ignore_kinds": ["possible-secret"],
    "min_severity": "warning"
  }
}
```

This is useful when test fixtures intentionally contain fake credentials or risky calls.

### CI And Review Workflows

- `--sarif` exports findings into a format that GitHub code scanning and other CI systems can ingest.
- `compare` lets you diff a stored baseline report against the current working tree to spot new TODOs, new documentation drift, and worsening hotspots.
- `changes` narrows the report to files touched between two git refs, which is useful for pull request review.
- `changes` and `reviewers` accept `--base auto`, which prefers `GITHUB_BASE_REF`, then `origin/main`, `main`, `origin/master`, `master`, and finally `HEAD~1`. If no committed diff is found, they fall back to uncommitted worktree files.
- hotspot and changed-file views inherit `CODEOWNERS` assignments so review surfaces show likely owners.
- `owners` prints owner-by-owner load and their hottest files.
- `reviewers` suggests reviewer candidates from `CODEOWNERS` and git blame on the changed surface.
- `scan` now also reports structural rule violations and dependency cycles when the repo defines `codeatlas.json`.

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
