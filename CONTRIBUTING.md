# Contributing

This project welcomes contributions and suggestions.

## Branch Workflow

**All changes must go through a pull request.** Direct pushes to `main` are not allowed.

### Steps

1. **Create a feature branch** from `main`:
   ```bash
   git checkout main && git pull
   git checkout -b feat/your-feature-name
   ```

2. **Make your changes** and commit with [conventional commits](https://www.conventionalcommits.org/):
   ```bash
   git commit -m "feat: add new retrieval route"
   git commit -m "fix: correct Cypher grouping error"
   ```

3. **Push your branch** and open a pull request:
   ```bash
   git push -u origin feat/your-feature-name
   gh pr create --fill
   ```

4. **Get at least one review approval** before merging.

5. **Merge via GitHub UI** (squash-and-merge recommended for clean history).

### Branch naming conventions

| Prefix | Use for |
|--------|---------|
| `feat/` | New features |
| `fix/` | Bug fixes |
| `refactor/` | Code restructuring |
| `docs/` | Documentation only |
| `chore/` | Dependencies, CI, tooling |

### What NOT to commit

Session-specific artifacts belong on your local machine, not in the repo:
- Handover documents (`HANDOVER_*.md`)
- Analysis notes (`ANALYSIS_*.md`)
- Debug/check scripts (`debug_*.py`, `check_*.py`)
- Test output files (`*.json`, `*.txt` results)
- Benchmark results (use `benchmarks/` directory which is gitignored)

These are covered by `.gitignore`. If you need to share session notes, use a GitHub issue or discussion instead.

## Code of Conduct

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/)
or contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.