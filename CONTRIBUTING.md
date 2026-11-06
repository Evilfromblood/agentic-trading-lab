# Contributing

Thank you for considering a contribution to Agentic Trading Lab. The project is experimental and its architecture may change.

## Before you start
1. Read the root README and the relevant version-specific README.
2. Check existing issues before starting substantial work.
3. For a large change, open an issue to discuss the design first.
4. Never include API keys, access tokens, account data, or other secrets in commits, issues, logs, or screenshots.

## Development principles
- Prefer small, focused pull requests.
- Keep external services behind explicit interfaces.
- Make tests deterministic; mock network and broker calls.
- Document data sources, assumptions, timestamps, and known limitations.
- Keep broker integrations read-only unless a future project decision explicitly changes the safety model.
- Do not describe simulated results as real trading performance.

## Pull requests
Include:
- The problem being addressed and the proposed change.
- Relevant tests and their results.
- Configuration or migration changes.
- Security, data-quality, and financial-risk implications.
- Documentation updates where behaviour or setup changes.

Do not submit real credentials or private financial information. Maintainers may request changes before merging.
