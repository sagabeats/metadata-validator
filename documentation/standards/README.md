# Standards

Implementation quality rules for this repository. Architecture decisions live in
[architecture/](../architecture/); contract facts live in
[reference/](../reference/).

## Contents

- [Contributing](CONTRIBUTING.md) — branches, commits, code style, and how to add a signature or a container format.
- [Testing](TESTING.md) — what CI verifies, what it does not, and the manual checks that are not optional.

## The shape of this codebase

Two files, no package, no build step, no test suite. That is deliberate for a
tool this size, and it sets the standards:

| Property                           | Consequence for a change                                                 |
| ---------------------------------- | ------------------------------------------------------------------------- |
| One module holds all the logic     | Never duplicate detection logic into `server.py`                          |
| No test suite                      | Verification is manual and must be described in the pull request           |
| CI publishes on merge, gates nothing | Review is the only gate before production                                |
| Dense explanatory comments          | Match them. Explain *why*, not *what*                                     |

## Code style

Follow the file you are editing. Concretely:

- **Comments explain reasoning.** The existing comments record why a lookbehind
  exists, why `Header()` is load-bearing, why `ilst` is resolved after the walk.
  A comment restating the code adds nothing; a comment recording a decision
  prevents its removal.
- **Type hints on public functions.** `from __future__ import annotations` is
  already imported, so use modern syntax.
- **Standard library first.** Container parsing and stripping are pure stdlib and
  should stay that way. A new runtime dependency needs justifying in the pull
  request.
- **Degrade, do not raise.** Parsers stop on malformed input and return what they
  have. See [architecture/SECURITY.md](../architecture/SECURITY.md).
- **Line length around 88 characters**, matching the existing files.
- **Section banners** — the `# ---` comment rules — separate concerns in
  `ai_metadata_check.py`. Put new code in the right section.

## References

- [Contributing](CONTRIBUTING.md)
- [Testing](TESTING.md)
- [Architecture](../architecture/README.md)
- [Reference](../reference/README.md)
- [Documentation index](../README.md)
