# Next Actions

Current priority: finish M2a review/remediation safely.

## Immediate sequence
1. Ask user for current local `git status --short`, `git branch --show-current`, and `git log -1 --oneline`; do not assume the local tree has synchronized with remote README commit `0cba422`.
2. Inspect the untracked `cls` file before deleting or retaining it.
3. Protect local uncommitted M2a changes. Agree a safe fetch/rebase or other synchronization plan; do not reset or discard work.
4. Ask Antigravity to remediate every item in `ISSUES_AND_RISKS.md` without committing or pushing.
5. Review actual diffs, not only agent summaries.
6. Run:
   ```powershell
   .\.venv\Scripts\python.exe -m ruff check src/agentic_trading/market_data tests/test_market_data_models.py tests/test_market_data_quality.py
   .\.venv\Scripts\python.exe -B -m pytest -v -p no:cacheprovider
   .\.venv\Scripts\python.exe -m compileall -q -f src tests
   git diff --check
   ```
7. Confirm CI lint scope and inspect the full CI workflow.
8. Obtain explicit user approval before committing/pushing the M2a code.
9. Push only to `feature/reliable-foundation`; verify GitHub Actions, including Python 3.11.
10. Ask Claude Free for an independent audit of the exact pushed commit; resolve findings.
11. Update README and project-memory docs with actual outcomes, commit SHA, CI evidence, and remaining risks.

## Do not
- Do not merge to `main`.
- Do not enable live trading or add live order placement.
- Do not commit secrets or personal data.
- Do not treat 63 local passing tests as proof of Python 3.11 CI compatibility.
- Do not mark M2a complete until review findings are resolved and CI passes.
