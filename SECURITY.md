# Security Policy

Agentic Trading Lab is experimental software. Do not connect it to a live trading workflow or rely on it for financial decisions.

## Reporting a vulnerability
Please do not publish exploitable details, credentials, access tokens, or personal financial information in a public issue. Contact the repository owner privately through the contact options on the GitHub profile and include:
- A concise description and affected path or version.
- Reproduction steps that do not expose real credentials or account data.
- Potential impact and any suggested mitigation.

Please allow time for investigation before publicly disclosing a vulnerability.

## Credential handling
- Never commit `.env` files, API keys, API secrets, access tokens, cookies, or account exports.
- Keep local callback servers bound to localhost.
- Use least-privilege credentials and read-only broker permissions.
- Revoke and rotate credentials immediately if exposure is suspected.
- Do not paste secrets into issues, pull requests, logs, or AI prompts.

## Scope and limitations
This policy covers security issues in this repository. It is not a guarantee that the software is secure, audited, or suitable for production use.
