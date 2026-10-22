# Security Policy

## Supported versions

Security fixes are applied to the latest released version of Ally Legal Flex.
Older versions are not maintained; please reproduce an issue on the current
release before reporting it.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Use GitHub's private reporting channel instead: open the repository's
**Security** tab and choose **Report a vulnerability**
(GitHub Security Advisories). If that channel is unavailable, contact the
maintainer through the address listed on the repository profile and ask for a
private channel before sending details.

A useful report includes:

- the version and platform (Windows/macOS, Word build),
- which local service or file is involved (3000 task pane, 8083 analysis,
  8084 policy, 8085 model settings, or a file on disk),
- reproduction steps and the impact you believe it has.

Please do not include real API keys, customer contracts, or other personal data
in a report. Use synthetic values.

## What is in scope

- The four local services started by `Start-Ally.cmd` / `Start-Ally.command`
  and how they validate requests.
- The browser side of the add-in (task pane, Config pane) and how it handles
  model output and stored settings.
- The setup and packaging scripts, including download verification.
- Exposure of local files: model configuration, policies, contract index,
  embeddings cache, and logs.

## What is out of scope

- Vulnerabilities in desktop Word, Office.js, WebView2, or the model service you
  configure.
- Attacks that require code execution as the same operating-system user who is
  already running the add-in. Local secrets are readable by that user by design
  (see the known limitations in the security review).
- Findings that require the user to install a modified copy of this project.

## Known limitations

These are documented, accepted risks rather than undisclosed vulnerabilities:

- Model API keys are stored in plain text in `model_config.json`.
- The task pane is served by webpack-dev-server over a locally trusted
  development certificate.
- Contract text is sent to the model service the user configures.

See [docs/security-audit.md](docs/security-audit.md) for details and the plan.
