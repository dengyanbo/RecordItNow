# Security policy

## What RIN does with your data

RIN captures **everything visible on your screen** and **audio from your
microphone** while recording. All of it stays on your local machine
unless you explicitly enable an LLM provider that uses a hosted API
(OpenAI, Azure OpenAI, or GitHub Copilot CLI). Even then, only the
*summarised text* of a capture is sent to the LLM, never the raw PNG or
MP4 file.

There is currently no telemetry and no analytics. Starting in v0.9.0 RIN can check GitHub for new releases (single outbound HTTPS request to api.github.com once every 24 hours), but it never downloads or installs anything automatically — you click through to the browser and run the installer manually. Disable the check in Settings → About if you don't want it.

## Where secrets live

- API keys for OpenAI / Azure OpenAI are stored in the Windows Credential
  Manager via the `keyring` package — never written to `config.toml`.
- Captures and reports live under `%LOCALAPPDATA%\RIN\` (or the path
  pointed to by the `RIN_DATA_DIR` environment variable).

## Reporting a vulnerability

**Please do not file a public GitHub issue for security bugs.**

Instead, file a private advisory:
<https://github.com/dengyanbo/RecordItNow/security/advisories/new>

If you cannot use GitHub Security Advisories, email the maintainer via
the address listed on their GitHub profile.

A few specific things we'd really like to hear about:

- Anything that exfiltrates capture files (PNG / MP4) over the network
  without an explicit configured LLM provider.
- Anything that exfiltrates secrets from `keyring` (API keys, DPAPI
  blobs).
- Path-traversal / code-execution in the install script, prefetch
  script, or release zip.
- An LLM provider implementation that leaks one user's data into
  another user's session.

## Supported versions

We support the most recent **0.x** minor release line. Older versions
will not receive security fixes — please update.

| Version | Supported |
|---------|-----------|
| 0.8.x   | ✅ |
| ≤ 0.7.x | ❌ |

## Acknowledgements

Researchers who report a verified issue get a credit line in
`CHANGELOG.md` and the GitHub Release notes (or anonymised, if
preferred).
