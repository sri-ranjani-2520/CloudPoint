# CloudPoint Phase 7 — Quality, Accessibility, and Release Readiness

This record follows the clarified eight-phase roadmap. Phase 7 is local implementation and verification only; it is not a deployment approval or independent audit.

## Scope and status

| Requirement | Local status | Evidence and remaining verification |
|---|---|---|
| Student submission, validation, persistence, and confirmation | Pass locally | WSGI/SQLite API lifecycle test and dependency-free fake DOM/API tests. No deployed-service test. |
| Tracking current state and limiting student response fields | Pass locally | Lifecycle test observes an administrator rejection; API privacy regression tests and student UI test verify text rendering. |
| Admin authentication, logout, and protected direct requests | Pass locally | API tests use local scrypt account/session and SQLite; missing/forged tokens and revoked sessions are rejected. |
| Search, category/status filters, pagination, detail, and rejection updates | Pass locally | API tests run against SQLite; DynamoDB tests use a fake table; admin UI tests use fake DOM/API. No real DynamoDB test. |
| Dashboard totals/status counts | Pass locally | SQLite grouped-count tests and DynamoDB fake tests check current status distribution and sum invariant. Phase 6 DynamoDB scan consistency/cost limitations remain. |
| Correlation IDs, safe logs, and controlled errors | Pass locally | API tests cover response IDs and failure metadata; captured logs are checked for sensitive values. |
| Responsive layout and accessibility checks | Pass locally; assistive technology remains unverified | Real Chrome testing covered populated student/admin pages at 320px, 375px, 768px, and 1440px. HTML labels, feedback descriptions/live regions, focus styles, narrow-screen CSS, contained table scrolling, and reduced-motion rules are present and checked. Screen-reader and broader assistive-technology validation remain pending. |
| IAM, authorization, CORS, limits, and sensitive-data review | Local review complete; AWS pending | Runtime policy and template checks are local; API authorization is behavior-tested. Deployment-role policy is not defined in the repository. Effective deployed IAM, HTTPS, CORS path, and throttling remain unverified. |
| Backup, recovery, deployment, and rollback | Design documented; operationally incomplete | DynamoDB is retained on stack deletion, but point-in-time recovery/backups are not configured and no restore has been tested. RPO/RTO remain owner decisions. A paired immutable-release and maintenance-window rollback design, prerequisites, and cost categories are documented in `PHASE6_7_AUDIT_REMEDIATION.md`; no release bundle format, selector, rollback command, or rollback exercise exists. Deployment is guarded and cleanup is protected. |
| Setup/deployment/configuration/limitations documentation | Pass locally | See `LOCAL_DEVELOPMENT.md`, `API_CONTRACTS.md`, README, and this record. Deployment instructions remain unexecuted. |

**Phase 7 status: partially complete.** Local essential workflow, previously recorded real Chrome checks, and code-level security checks pass. The targeted CSS remediation records layout containment for `.table-scroll`, a narrow-screen `min-width: 0` override for `.admin-page`, and a student header navigation wrap at narrow widths. Offline JSON/template and PowerShell syntax checks are available, but no CloudFormation validator is installed. The latest student header CSS change has not been rechecked in Chrome. The release/rollback and backup/recovery design is documented, but the exit criterion that the deployment can be operated and recovered is not met until account-specific operations, an implemented and exercised backup/restore and paired rollback, and broader screen-reader/assistive-technology validation are completed. This browser verification was local only; it was not AWS or production verification.

## Real-browser verification

Local Chrome verification was performed with an administrator logged in and 30 varied complaints populated. The student page and administrator login page were also checked at 375px. The test used an isolated temporary SQLite database and local test credentials; no AWS services or real personal data were used.

The targeted CSS changes under verification were:

- Layout containment for `.table-scroll` so the complaint table scrolls within its intended container.
- A narrow-screen `min-width: 0` override for `.admin-page` to prevent the page layout from expanding beyond the viewport.

Measured administrator page results after the fix:

| Viewport | Document `scrollWidth` | Result |
|---:|---:|---|
| 320px | 305px | No document-level horizontal overflow |
| 375px | 360px | No document-level horizontal overflow |
| 768px | 753px | No document-level horizontal overflow |
| 1440px | 1425px | No document-level horizontal overflow |

Before the fix, the populated 375px administrator page measured a document `scrollWidth` of 1004px against a 375px viewport. After the fix, the table remained horizontally scrollable inside `.table-scroll` without widening the document.

Chrome verified search, category filtering, pagination, complaint details, status updates, rejection controls, keyboard focus, detail focus management, loading/error feedback, and logout. Student submission and tracking were also exercised locally, including safe rendering of user-controlled text.

Local verification results:

- Python tests: 88 passed (current full local run).
- Administrator UI tests: 9 passed (current direct Node run).
- Student UI tests: 5 passed.
- JavaScript syntax checks: passed. The `node --test` wrapper is blocked here by `spawn EPERM`; direct execution of both test files passes.
- Python compilation: passed.
- `git diff --check`: passed.

The Chrome screenshots and measured viewport results above are earlier local evidence. They do not cover the latest narrow-screen student header CSS change and should be repeated before treating responsive browser verification as current.

Browser evidence: [phase7-admin-375.png](artifacts/phase7-admin-375.png)

This is local Chrome/browser evidence only. It does not verify AWS deployment, CloudFormation, IAM, CloudFront, backups, rollback, billing controls, screen-reader compatibility, or production behavior.

## Test classification

- `tests/test_api.py`: application integration tests invoke the actual WSGI routes, service code, auth implementation, and isolated local SQLite repository. They do not call a deployed service.
- `tests/test_dynamodb_repository.py`: repository contract tests use an in-memory fake table; they do not call DynamoDB.
- `tests/admin_ui.test.cjs` and `tests/student_ui.test.cjs`: JavaScript UI behavior against a dependency-free fake DOM and fake API. They do not execute a browser engine.
- `tests/test_foundation.py`: local SQLite/configuration/application foundation tests.
- `tests/test_infrastructure.py`: JSON/template assertions and offline PowerShell pagination helper tests. Deployment and cleanup scripts are not executed against AWS.

## Security and deployment review

- Administrative endpoints validate bearer sessions on the server. The local integration scenario verifies access after login and rejection after logout. It does not validate API Gateway or Lambda permissions in an account.
- The Lambda runtime role in the template scopes table operations to the complaint table, secret retrieval to the session secret, and log writes to the application log group. No dedicated deployment IAM policy is included; deployment operators must use a separately reviewed identity with only required actions and account/region constraints.
- The template disables API Gateway CORS for the intended same-origin CloudFront architecture. CloudFront routes the browser API on the same HTTPS origin, forwards the Authorization and Content-Type headers, and disables API caching. This is template-level only; deployed routing and headers need verification.
- API request size is capped at 16 KiB; individual fields, list/search query values, cursor, and page size have server-side validation. Frontend length attributes support usability but do not replace backend validation.
- Student tracking omits student name and registration number. UI inserts complaint text through `textContent`; fake DOM tests fail on any `innerHTML` assignment.
- Login lockout is process-local; API Gateway throttling is best-effort. Neither is a distributed abuse control or a spending cap.
- CloudWatch log retention is set to 14 days and alarms are defined for Lambda errors/throttles and API 5xx. Alarm delivery actions are absent. Operators must arrange least-privilege access and an actual monitoring/response process.

## Backup and recovery posture

The CloudFormation table has `DeletionPolicy: Retain` and `UpdateReplacePolicy: Retain`. This protects the table from stack deletion/replacement; it is **not a backup** and does not protect against accidental item changes, corruption, or loss of the AWS account/region. The template does not enable DynamoDB point-in-time recovery, create on-demand backups, define a backup vault, or establish recovery point/time objectives. No restore procedure has been tested.

Before production use, the owner must approve a backup policy and retention target, configure an approved backup/PITR mechanism, document who can initiate and restore backups, and test a restore into an isolated table. Record actual RPO/RTO only after that exercise. Do not delete or replace the retained table as a recovery experiment.

## Deployment, rollback, and cleanup posture

The deployment procedure requires an expected account ID, explicit region, verified tagged artifact bucket, verified CloudPoint stack ownership, and a separate `-UpdateExisting` opt-in. It checks for stale frontend objects and refuses to upload when unrecognized assets exist. The procedure was not run.

The cleanup script requires `-Execute`, `-ApproveDestructive`, and `ShouldProcess`; verifies account, region, stack/bucket ownership, complete frontend and multipart inventories, and retained-table policy before deletion. It retains the complaint table and does not delete the artifact bucket. Secrets Manager deletion recovery windows and artifact ZIP storage can continue to incur charges. The cleanup script was not run.

No dedicated rollback command is provided. CloudFormation may roll back a failed stack update, but that does not provide a tested application-level rollback for a successful backend update followed by a failed frontend publish. Releases are not atomic: frontend files upload individually and deployment may stop after the stack changes. A production runbook must preserve the exact previous template, package object key, frontend manifest, parameter values, and deployment version, then define and test an approved rollback that restores both backend and frontend together. Current scripts do not expose a supported previous-package selector; manual CloudFormation changes would require separate review and approval. Do not describe rollback as tested or recoverable until an isolated exercise succeeds.

## Required manual and AWS-dependent checks

1. In an approved non-production browser deployment, inspect widths at 320, 375, 768, and desktop sizes; test 200% zoom and horizontal complaint-table scrolling.
2. Complete student and administrator workflows using keyboard only. Check visible focus, logical focus order, detail open/close behavior, form validation announcements, busy/result messages, and session expiry.
3. Review with a screen reader and at least one supported browser/assistive-technology combination. Confirm that labels, table structure, status announcements, and error descriptions are understandable.
4. After deployment approval, verify CloudFront HTTPS/same-origin API routing, effective runtime IAM and separately reviewed deployment IAM, throttling behavior, log retention/content, alarm metric dimensions/states, and operator read access. No such AWS verification occurred here.
5. Approve and test backup/restore and release rollback in an isolated environment before real student data is accepted.

No AWS API calls or resource operations were made for this phase. Phase 6 AWS-dependent completion remains pending. Phase 8 is not started.
