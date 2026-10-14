# Local Development, Administrator UI, and AWS Deployment Preparation

## Requirements and local startup

- Python 3.10 or newer.
- Local SQLite and ordinary tests use only the Python standard library; no AWS account, network access, credentials, or resources are required.
- `boto3` is optional and is needed only for direct use of the DynamoDB adapter or administrator setup in an already existing table.

From the repository root in PowerShell:

```powershell
Copy-Item .env.example .env
python -m cloudpoint.app
```

The project root is the directory containing `README.md` and `cloudpoint`. `.env` is discovered at that root regardless of the current working directory. It accepts simple `CLOUDPOINT_*` `KEY=VALUE` entries and is never executed. Process environment variables override `.env`, which overrides defaults. The default database is `<project-root>/instance/cloudpoint.sqlite3`; relative `CLOUDPOINT_DB_PATH` values resolve from the project root. Local startup initializes SQLite and serves the WSGI application on `127.0.0.1:8000` by default. `.env` and local databases are ignored by Git.

Open `http://127.0.0.1:8000/` for student submission and tracking, or `http://127.0.0.1:8000/admin.html` for the administrator portal. Both call the API at the relative same-origin path `/api`; no separate API URL or CORS configuration is needed locally. The administrator token stays in page memory only, so refreshing the page requires signing in again. The page is not an authorization boundary: each administrative API route independently requires the existing bearer session.

For local administrator login, generate a private session signing secret and set `CLOUDPOINT_SESSION_SECRET` in `.env` or the process environment. For example, run `python -c "import secrets; print(secrets.token_urlsafe(48))"` and copy the output into your ignored `.env`. Keep the local value stable while using locally issued sessions; replacing it invalidates them. The application requires at least 32 characters and does not include a fallback secret. Deployed Lambda uses Secrets Manager instead.

Create a local administrator interactively:

```powershell
python -m tools.create_admin
```

Use a unique strong password and do not put it in shell arguments, source files, `.env`, or logs. The tool stores only a salted scrypt hash. Local admin routes use 30-minute HMAC-signed bearer sessions; only a token digest is stored and logout revokes the session. The prototype lockout is per process and is not suitable as the only public deployment abuse control.

## Implemented HTTP API

- `GET /health` returns health status.
- `POST /api/complaints` accepts validated student complaint JSON and returns a backend-generated ID.
- `GET /api/complaints/{complaint_id}` returns only student tracking fields.
- `POST /api/admin/login` verifies a provisioned account and returns a bearer token. Invalid credentials receive a generic `401`.
- `POST /api/admin/logout` requires a valid token and revokes it.
- `GET /api/admin/dashboard` returns current counts for all statuses.
- `GET /api/admin/complaints` requires authentication and supports category, status, search, cursor, and page-size query parameters.
- `GET /api/admin/complaints/{complaint_id}` returns administrative details and requires authentication.
- `PATCH /api/admin/complaints/{complaint_id}/status` validates status and rejection reason and requires authentication.

The contract, field sets, errors, and storage limitations are in `API_CONTRACTS.md`. The administrator interface is served at `/admin.html`; its token stays in page memory, and all administrator API access remains protected server-side. A browser client must keep access tokens out of URLs and persistent logs. Since authentication uses an Authorization bearer header rather than cookies, cookie-based CSRF protection is not applicable.

## AWS infrastructure prepared (not deployed)

`infra/cloudpoint.template.json` defines a private encrypted S3 frontend bucket, CloudFront HTTPS distribution with S3 Origin Access Control, API Gateway HTTP API v2, Lambda, a pay-per-request DynamoDB table, a generated Secrets Manager signing key, least-privilege Lambda IAM, and a 14-day CloudWatch log group. DynamoDB's `expires_at` TTL cleans expired session items. The table has `DeletionPolicy: Retain` and `UpdateReplacePolicy: Retain`; deleting the stack does not delete complaint data.

CloudFront routes `/api/*` and `/health*` to API Gateway and serves other paths from private S3. The browser therefore uses one HTTPS origin. API Gateway CORS is deliberately disabled; there is no wildcard origin and same-origin browser requests need no CORS headers. CloudFront forwards only `Authorization` and `Content-Type` plus query strings to the API, disables API caching, redirects viewer HTTP to HTTPS, and attaches restrictive security headers. Login receives a stricter API Gateway route throttle, with a broader default throttle for other routes. AWS throttling is best-effort and is not a hard spending or abuse cap. CORS is not authorization; backend admin session validation remains required.

CloudFront is used because the README requires HTTPS for public student information; the S3 website endpoint is not used. CloudFront and data transfer can incur charges. Check the account, region, current pricing, and budget alerts before deployment; the template does not guarantee free usage.

The deployment script requires an already-existing private, encrypted S3 artifact bucket in the selected region. Before uploading anything, it checks `sts:GetCallerIdentity` against the required expected account ID, verifies the explicit region, verifies bucket ownership with S3's expected-owner check, checks the bucket region/encryption/public-access block and ownership tags, and verifies any same-name stack's ARN, tags, region, stable status, required outputs, and matching frontend/table stack resources. The artifact bucket must be tagged `CloudPointProject=CloudPoint`, `CloudPointPurpose=LambdaArtifacts`, and `CloudPointOwnerAccount=<12-digit-account-id>`. The script never creates this bucket. After a separately approved future bucket-creation operation, create it in the target account and region, enable S3 Block Public Access and default server-side encryption, then apply those tags. The script refuses unmarked or unrelated buckets.

The script packages only `cloudpoint/*.py`, uploads with an expected-bucket-owner constraint, creates a new stack, uploads the frontend, and invalidates CloudFront. Before uploading the Lambda package or updating an existing stack, it explicitly enumerates every frontend object page and compares the keys with the current local frontend manifest. Stale or unrecognized keys stop the release and are reported; the script never deletes frontend objects. For a new stack, the same check runs after stack creation and before frontend uploads. Review reported keys and, only after separate approval, verify the account, region, ownership markers, stack output bucket, and each key. Delete only confirmed obsolete CloudPoint assets with an individual `aws s3api delete-object --bucket <verified-frontend-bucket> --key <reviewed-key> --expected-bucket-owner <expected-account-id> --region <region>` operation, then invalidate the corresponding CloudFront paths. Do not use `aws s3 sync --delete` or bulk deletion. Updating an existing verified stack additionally requires `-UpdateExisting`; that option fails if the stack is absent. Stack names must be at most 46 characters to fit generated resource names. Every AWS CLI call supplies the requested `-Region`; no CLI default region/account is trusted. New stacks receive `CloudPointProject=CloudPoint`, `CloudPointPurpose=ServerlessApplication`, and `CloudPointOwnerAccount=<account-id>` tags. Existing stacks must already have these ownership markers and matching ARN account/region.

The Lambda session signing key is generated by CloudFormation in Secrets Manager. It is not passed as a CloudFormation parameter or placed in Lambda environment values. Lambda receives only the secret ARN and has `secretsmanager:GetSecretValue` permission scoped to that secret; the application reads its value during Lambda initialization and keeps it in that execution environment's memory. Secrets Manager is an additional service with potential charges, including reads on Lambda cold starts. Check current pricing before deployment. The initial generated secret has no automatic rotation configured.

To rotate the key:

1. Schedule a maintenance window and pause API traffic using an approved edge/API change. Without a traffic pause, warm and newly initialized Lambda environments can overlap.
2. Through the approved Secrets Manager operator workflow, write a new high-entropy value as the current secret version. Never place the value in command-line arguments, source files, or logs.
3. Deploy the already verified stack with `-UpdateExisting -SessionSecretRevision <new-unique-revision>`. This changes the Lambda environment configuration; Lambda may replace execution environments, but AWS does not guarantee that every old environment is terminated immediately. The application reads the secret only while initializing its cached handler in each environment. Updating the secret alone does not refresh already initialized handlers.
4. While traffic remains paused, verify a new administrator login, use its token on a protected route, and verify that a token issued before rotation is rejected. Reopen traffic only after the new key is serving requests.
5. If rollout is partial or must be rolled back, keep traffic paused. Restore a known matching secret version and change the revision again through an approved stack update to trigger another configuration update. Re-test login, new-token access, and old-token rejection before reopening traffic. Tokens created by an environment using the other key will fail after rollback; administrators may need to log in again.

The revision value is a non-secret Lambda environment setting wired from the CloudFormation parameter. Changing it changes Lambda configuration and requests environment replacement, but it does not guarantee immediate global termination of old execution environments or invalidate tokens stored in DynamoDB by itself. The script does not pause traffic or automate secret rotation. Do not claim a completed rotation until new and old token behavior has been checked. Do not pass the key in command-line arguments, source files, or logs.

The script is non-operative by default: it returns without AWS calls unless `-Execute` is supplied, and it honors PowerShell `ShouldProcess` including `-WhatIf`. The example uses `-Confirm` to prompt explicitly. **Do not run until resource creation has been approved and cost/account checks are complete**:

```powershell
.\scripts\deploy.ps1 -StackName cloudpoint-demo -ArtifactBucketName approved-private-artifacts -ExpectedAccountId 123456789012 -Region ap-south-1 -Execute -Confirm
```

For a verified existing stack, add `-UpdateExisting` as an independent opt-in. `-SessionSecretRevision` should remain unchanged during ordinary updates; increment it only as part of a reviewed secret rotation. `-WhatIf` previews the guarded action. The script was not run as part of this implementation.

The stack does not create an administrator account. After an explicitly approved deployment, provision one into the new table with the interactive setup utility (install `requirements-aws.txt`, then set `CLOUDPOINT_DYNAMODB_TABLE` to the printed table name and `CLOUDPOINT_AWS_REGION` to the selected region before running `python -m tools.create_admin --dynamodb`). This writes a credential record and uses the normal AWS credential provider chain; it is a resource-changing operation and must be separately reviewed and approved. The password is prompted without echo and stored only as a salted scrypt hash.

Before a future deployment, independently confirm the intended account/region, current AWS pricing and free-tier eligibility, and a billing alert. The script checks the actual caller against `ExpectedAccountId`, validates the explicit region, and checks artifact-bucket ownership/security markers, but it does not verify pricing, account eligibility, budgets, or guarantee a zero bill.

`scripts/remove_deployment.ps1` requires `-Execute`, a separate `-ApproveDestructive` opt-in, and `ShouldProcess` confirmation. It checks the expected caller account and region, verifies stack ARN/tags/stable status/outputs and that the frontend bucket output matches the stack's actual bucket resource, and checks the deployed template's complaint-table `DeletionPolicy` and `UpdateReplacePolicy` are both `Retain`. It then verifies the bucket's owner, region, tags, encryption, and public-access block. With AWS CLI automatic pagination disabled, it explicitly follows every `NextContinuationToken` for object pages and every next key/upload marker pair for multipart pages. It validates JSON, requires pagination to advance, and stops on failed or malformed pages. It completes both listings and refuses versioned buckets, any incomplete multipart upload, or any object outside the current checked-in frontend manifest before issuing the first deletion. The manifest is derived from the frontend tree, so new legitimate files are supported; old/unrecognized keys require separate review and cleanup. It deletes only enumerated manifest keys, then deletes the verified stack. It never uses a stack name alone as ownership proof and never deletes the artifact bucket. The DynamoDB table is retained. Secrets Manager deletion may remain pending during its recovery window and can continue to incur charges; the artifact bucket and uploaded ZIPs also remain and may incur storage charges. Review and clean them separately only with explicit approval. Back up retained complaint data before any separately approved table deletion.

## Optional direct DynamoDB/Lambda development

The Lambda entry point is `cloudpoint.lambda_adapter.lambda_handler` and accepts API Gateway HTTP API payload format `2.0`. It invokes the same WSGI routes and repository contract. It requires a DynamoDB table with a string partition key named `complaint_id` and no sort key. The adapter itself never creates or changes a table. The CloudFormation template creates the table and stores complaint, administrator, and revocable session items under noncolliding key prefixes; see `API_CONTRACTS.md` before preparing a table or IAM policy.

Install the optional AWS dependency only when needed:

```powershell
python -m pip install -r requirements-aws.txt
```

For local/direct Lambda development, configure `CLOUDPOINT_DYNAMODB_TABLE`, `CLOUDPOINT_SESSION_SECRET`, and optionally `CLOUDPOINT_AWS_REGION` (otherwise Lambda's `AWS_REGION` is used). The deployed template instead sets `CLOUDPOINT_SESSION_SECRET_ARN`; Lambda reads the value through its scoped runtime role. Credentials come from the runtime role/provider chain, never from application source or `.env`. To provision an administrator into an existing DynamoDB table, use `python -m tools.create_admin --dynamodb` with an approved credential provider. This operation writes an item and can incur AWS usage; it does not create infrastructure. Ordinary tests use a fake table and do not need the AWS SDK, network, or credentials.

Admin search is case-insensitive substring matching for title and registration number, with exact ID lookup. List and count operations use paginated scans. A scan may return an empty page with a continuation cursor, and dashboard counts across pages are not a consistent point-in-time snapshot. Scan cost and latency rise with table size. Preserve the README's review thresholds and revisit the model before exceeding them.

## Tests

Run from the repository root:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q cloudpoint tools tests
node --check frontend/static/admin.js
node --check frontend/static/app.js
node tests/admin_ui.test.cjs
node tests/student_ui.test.cjs
```

`tests/test_api.py` includes local application integration scenarios through the WSGI router, actual validation/auth/service code, and isolated SQLite. Repository tests use an in-memory DynamoDB fake. The student and administrator UI tests use a dependency-free fake DOM/API and are not browser or deployed-service end-to-end tests. Infrastructure tests parse the JSON template and check key security and resource settings. No AWS resources are contacted.

## Security and remaining work

- Login throttling is five failed attempts per username followed by a 15-minute lockout within one application process. Lambda execution environments do not share this state. Before any public launch, configure API Gateway throttling/abuse controls and HTTPS, and review the identity/session design for the deployment threat model.
- Bearer token digests are stored in SQLite/DynamoDB and expiry is checked in application code. The deployment template enables DynamoDB TTL on `expires_at`, but TTL deletion is asynchronous; expired tokens remain rejected immediately by the application.
- The admin frontend, production distributed throttling beyond API Gateway's best-effort stage limits, deployment-role IAM review, current pricing/free-tier review, live template validation, and deployed end-to-end verification remain incomplete. Never use real student data until the HTTPS endpoint and authorization setup have been reviewed.
- No AWS resources have been provisioned or deployed by this implementation. Run no resource-changing script without explicit owner approval.

### Local security review and AWS release gates

The local security review is backed by `tests/test_api.py` and `tests/test_infrastructure.py`. It checks that every protected API route rejects missing/forged bearer tokens, student tracking omits student identity and administrator fields, application errors do not disclose storage exceptions, the deployment template has same-origin routing without API CORS, the API behavior is uncached, the HTTPS security-header policy is restrictive, login/default stage throttles are present, the runtime role is scoped, and CloudWatch log retention is 14 days. These are checks of local code and template definitions, not evidence that AWS accepted or applied those settings.

Before any public deployment, the owner must separately verify in the intended AWS account and region:

1. Billing access is available to the operators responsible for the application, and a billing alert or budget is configured with a monitored recipient.
2. Current regional prices, account eligibility, expected traffic, CloudFront transfer, Lambda duration, DynamoDB scans, Secrets Manager cold-start reads, and log storage have been reviewed. The template does not establish a spending cap or guarantee zero cost.
3. The deployed stack and effective Lambda role match the template's least-privilege intent; deployment principal permissions are also reviewed against the actions required by the deployment procedure.
4. API Gateway throttling and HTTPS behavior are active on the deployed distribution. Stage throttles are best-effort abuse controls, not a hard request or billing limit; per-process login lockout is not distributed across Lambda environments.
5. CloudWatch log group retention and actual log contents are checked after deployment to ensure student complaint text, credentials, tokens, and secret values are absent.
6. The API Gateway/Lambda integration and end-to-end student/admin workflows are validated with an approved deployment. CloudFormation/API Gateway acceptance, AWS permissions, and live billing visibility remain unverified locally.

Do not use real student information or treat the AWS-dependent review as complete until these account-specific checks are recorded. No budget resource was added to the template because its recipient, threshold, billing access, and account behavior require owner-specific configuration and approval.

## Phase 6 dashboard and operational visibility

The administrator dashboard's existing endpoint returns a total and counts by current status. SQLite calculates the counts in one grouped query. DynamoDB scans all pages with strongly consistent item reads and excludes internal administrator/session items. The aggregate is not a point-in-time snapshot: concurrent writes may make counts reflect different moments. Each valid complaint read is assigned to exactly one status, so the returned status counts sum to the total. Every dashboard refresh performs a full table scan; strongly consistent reads cost more than eventual reads, and scan cost/latency grows with table size. This is intended for the small prototype workload. Revisit the counting model before the workload grows beyond the README's operational review thresholds; no aggregate table or extra service is introduced here.

Every WSGI response includes `X-Request-Id`. In Lambda, the adapter uses a validated API Gateway request ID, with the Lambda invocation ID as fallback; direct local WSGI requests receive a generated ID unless a trusted internal request ID is supplied. Failure logs are JSON event messages with only the request ID, fixed operation name, and exception class. Successful complaint submissions and admin status updates emit operation/request-ID events. No submitted fields, complaint identifiers, credentials, tokens, authorization values, exception messages, or filesystem paths are logged. The local WSGI server's default access-line logging is disabled because it prints request paths that can contain complaint IDs.

The infrastructure template defines alarms for Lambda errors, Lambda throttles, and API Gateway HTTP API 5xx responses. Each evaluates a five-minute sum and enters `ALARM` for a nonzero value; absent metrics are treated as non-breaching. The alarms have no notification actions, so they expose alarm state for operators to monitor but do not send push alerts. No notification service was added. The existing CloudWatch log group retains logs for 14 days. The Lambda execution role can write to that log group but cannot read logs or alarm states. Configure and review separate least-privilege operator access to CloudWatch Logs and alarms in the target account. Alarm cost, permissions, metric dimensions, and runtime behavior require account-specific AWS verification; alarm state is not a cost cap.

## Phase 7 release-readiness review

The local Phase 7 acceptance record is in `PHASE7_ACCEPTANCE.md`. It documents which workflows use real local application code and SQLite, which repository/UI checks use fakes, and which browser and AWS checks remain pending. Student/admin control feedback is linked with `aria-describedby`, status feedback uses live regions, loading regions expose `aria-busy`, and the stylesheet includes narrow-screen layouts, visible focus, reduced-motion handling, and horizontal table scrolling. These code-level checks do not substitute for browser rendering, keyboard-only, screen-reader, or zoom testing.

The Phase 6–7 audit finding verification, recovery prerequisites, rollback limits, notification options, CloudFormation integration evidence, and target-account verification checklist are recorded in `PHASE6_7_AUDIT_REMEDIATION.md`. No browser, AWS CLI, SAM, or cfn-lint validator is available in the current environment. No deployment, validation API call, resource operation, or dependency installation was performed.

### Backup, recovery, and rollback limits

The template retains the DynamoDB complaints table on stack deletion or replacement. Retention is not a backup. Point-in-time recovery and automated/on-demand backup resources are not configured; restore behavior and recovery objectives have not been tested. Before production use, approve a backup policy, configure the selected backup mechanism, and exercise restoration into an isolated table. The deployment scripts do not offer a supported previous-package rollback selector and do not provide an atomic backend-plus-frontend release. Preserve the exact prior template, Lambda package, frontend manifest, parameters, and versions; define and test the rollback procedure in an approved isolated environment before relying on recovery. Do not delete the retained table during testing. See `PHASE6_7_AUDIT_REMEDIATION.md` for specific prerequisites and the target-account checklist.

Deployment and cleanup procedures remain unexecuted. Deployment checks the expected account, explicit region, artifact-bucket and stack ownership, and update opt-in; cleanup additionally requires two explicit approvals and completes inventory/retention checks before deletion. Cleanup keeps the DynamoDB table and artifact bucket; retained artifact ZIPs and Secrets Manager deletion recovery may continue to incur charges. The repository does not define a deployment IAM policy, so the operator's deployment identity needs a separate least-privilege review. The Lambda runtime policy is scoped in the template, but its effective deployed permissions are unverified.
