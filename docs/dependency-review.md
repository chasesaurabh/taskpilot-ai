# Dependency review for v0.1.0

Reviewed 2026-08-29 against the four open Dependabot pull requests. The recommendations are
deliberately conservative for the release candidate.

| PR | Change | Evidence | Recommendation |
| --- | --- | --- | --- |
| #1 | Python container 3.12 → 3.14 | Existing CI passed, but the package, local setup, and supported runtime are explicitly Python 3.12. Optional provider/checkpoint compatibility was not validated on 3.14. | Defer until a deliberate runtime-matrix change. |
| #2 | Node build image 24 → 26 | Backend and frontend jobs passed; the container-build job failed. Documentation and CI intentionally standardize on Node 24. | Do not merge. Revisit after the container toolchain supports Node 26. |
| #3 | nginx 1.29 → 1.31 | All CI jobs passed and the runtime image has no custom native modules. The release branch adopts 1.31 and revalidates the Docker demo. | Accept through the release branch after final Docker validation. |
| #4 | Rich 15, structlog 26, mypy 2 | All CI jobs passed. Their relevant breaking changes are compatible with Python 3.12, but none is required to make v0.1.0 credible. Updating three major ranges together increases release-candidate variance. | Defer until after v0.1.0 and split runtime from development-tool upgrades. |

CI now performs Python and production npm dependency audits. CodeQL scans Python and
JavaScript/TypeScript on pull requests, main, and a weekly schedule. These checks add different
evidence from formatting/tests and are therefore not ceremonial duplicates.
