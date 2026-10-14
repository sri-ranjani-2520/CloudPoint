# CloudPoint API, Frontend, and AWS Adapter Contracts

This document describes the implemented HTTP API, authentication behavior, and storage access patterns. The WSGI app uses SQLite locally or the DynamoDB adapter through the API Gateway HTTP API v2 Lambda adapter. No AWS resources are created by the application.

## Common response behavior

All implemented API responses use JSON and include an `X-Request-Id` response header. API Gateway's request ID is echoed only after it passes a bounded safe-character check; otherwise the application uses the Lambda invocation ID or generates a random request ID. Errors use a stable envelope:

```json
{"error":{"code":"validation_error","message":"Request validation failed.","details":{"category":"Select an approved category."}}}
```

Field details contain validation messages, not submitted values. Malformed WSGI and API Gateway events return `400`; an unsupported content type returns `415`; oversized request bodies return `413`; known routes with unsupported methods return `405` with `Allow`; unknown routes return `404`; unexpected persistence failures return a generic `500` and do not include exception text, paths, credentials, or complaint contents.

## Public student routes

### `GET /health`

Returns `200` with `{"status":"ok"}`.

### `POST /api/complaints`

Public submission. Requires `Content-Type: application/json` and the string fields `student_name`, `registration_number`, `title`, `category`, `description`, and `location`. Categories and field lengths are validated server-side. The body limit is 16 KiB. Success returns `201` with a generated complaint ID and confirmation message.

### `GET /api/complaints/{complaint_id}`

Public tracking. Malformed IDs return `400`; unknown valid IDs return `404`. Success returns only `complaint_id`, `title`, `category`, `description`, `location`, `status`, and `created_at`. `rejection_reason` is included only when the current status is `Rejected`. Student name, registration number, modification timestamp, administrator data, session data, and DynamoDB search attributes are not returned.

## Administrator authentication

Admin login uses pre-provisioned accounts with scrypt password hashes and issues a cryptographically random, HMAC-SHA-256-signed 30-minute bearer token. Local development uses a high-entropy `CLOUDPOINT_SESSION_SECRET` of at least 32 characters in ignored `.env` or the process environment. The deployment template instead provisions a generated Secrets Manager value, sets only `CLOUDPOINT_SESSION_SECRET_ARN` in Lambda configuration, and grants the Lambda role `secretsmanager:GetSecretValue` on that single secret ARN. The value is read at Lambda initialization and kept in that execution environment's memory. It is not passed through CloudFormation parameters or exposed in Lambda environment configuration. Only a SHA-256 digest of the random token ID is stored. Send the complete token as `Authorization: Bearer <access_token>`. Logout deletes the stored session, immediately revoking the token. Expired tokens are rejected and removed when presented. Passwords, hashes, and tokens are not logged or returned except for the one-time login response containing the access token.

The CloudFormation `SessionSecretRevision` parameter is copied into a Lambda environment variable. Changing it changes the Lambda configuration and can cause execution environments to be replaced, but does not guarantee immediate termination of every old environment. The handler fetches the Secrets Manager value only while constructing its cached application in each environment; changing the stored secret alone does not refresh an already initialized handler. For rotation, pause traffic, update the secret, deploy a new unique revision, verify a new login/token and rejection of a pre-rotation token, then restore traffic. If rollout is partial or rolled back, keep traffic paused, restore a known matching secret value, use another approved revision update, and re-test before reopening traffic. A token signed under the other key will not validate after rollback. The scripts do not automate traffic pausing or rotation.

There are no cookies, so the API does not use cookie-based authentication and has no cookie CSRF token. Browser clients must keep the bearer token out of URLs and persistent logs. Public deployments require HTTPS. Login lockout permits five failed attempts per username before a 15-minute lockout in a process. This local/prototype throttle is not distributed across Lambda execution environments; production API Gateway throttling and abuse controls must be configured before public launch. This implementation is not a claim of production-ready identity management.

Create local credentials interactively with `python -m tools.create_admin`. For an already existing DynamoDB table, `python -m tools.create_admin --dynamodb` writes the administrator item there and requires the optional `boto3` package and configured AWS credentials. The utility never provisions AWS resources. Administrator credential records are not available through any public API.

### `POST /api/admin/login`

Public route used only to obtain a session. Request:

```json
{"username":"admin","password":"provided interactively by the administrator"}
```

Success returns `200`:

```json
{"access_token":"<opaque random token>","token_type":"Bearer","expires_in":1800}
```

Malformed JSON returns `400`; invalid credentials and locked accounts return the same `401 authentication_failed` response.

### `POST /api/admin/logout`

Requires a valid bearer token. Returns `200` with a confirmation after revocation. Missing, invalid, expired, or revoked credentials return `401` with `WWW-Authenticate: Bearer`.

## Protected administrator routes

Every route below requires a valid bearer token. Requests without a valid session return `401`; there is no browser-supplied administrator identifier. Session storage failures return generic `500` responses.

### `GET /api/admin/dashboard`

Returns `200` with `total` and one count for each supported status: `Submitted`, `Under Review`, `In Progress`, `Resolved`, and `Rejected`. Counts are computed from persisted complaint records on each request.

SQLite computes all counts in one grouped query. DynamoDB scans all table pages on each dashboard request with `ConsistentRead=true` and counts only complaint items, excluding administrator and session records. Each individual item read is strongly consistent, but DynamoDB does not provide snapshot isolation for a multi-page scan. Concurrent writes can therefore make the result a temporally mixed view; every valid complaint observed contributes once to both `total` and exactly one status count, so the status counts sum to `total`. The full scan runs on every dashboard load, consumes reads for the scanned table (strongly consistent reads cost more than eventual reads), and can increase latency and cost with table size. This strategy is for the documented small workload; review before growth makes the scan unsuitable.

### `GET /api/admin/complaints`

Accepts optional query parameters:

| Parameter | Meaning |
|---|---|
| `category` | Exact approved category filter |
| `status` | Exact approved status filter |
| `search` | Up to 160 characters; case-insensitive substring over title and registration number, or exact complaint ID when ID-shaped |
| `limit` | Page size, default 25, maximum 100 |
| `cursor` | Opaque continuation cursor from the previous response |

Filters combine. Unknown or repeated query parameters, invalid filters, malformed cursors, or invalid page sizes return `400`. Success returns `200`:

```json
{"items":[{"complaint_id":"CP-...","title":"...","registration_number":"...","category":"Infrastructure","status":"Submitted","created_at":"...","modified_at":"..."}],"next_cursor":"... or null"}
```

The list deliberately omits the full description and student name. DynamoDB scan pages can contain fewer items than requested, including an empty page, while still returning `next_cursor`; continue until it is null.

### `GET /api/admin/complaints/{complaint_id}`

Returns `200` with the full stored complaint fields needed for management, including student name, registration number, description, location, status, timestamps, and rejection reason when present. Malformed IDs return `400`; unknown IDs return `404`.

### `PATCH /api/admin/complaints/{complaint_id}/status`

Accepts only `status` and optional `rejection_reason`:

```json
{"status":"Rejected","rejection_reason":"Reviewed and declined."}
```

Any supported status may be selected, consistent with the README's initial transition policy. A nonblank reason of at most 1000 characters is required for `Rejected`; moving to any other status clears the current rejection reason. Invalid statuses, missing/blank/oversized rejection reasons, or extra properties return `400` without changing the record. Unknown complaint IDs return `404`; a concurrent DynamoDB modification returns `409`. Success returns `200` with the updated complaint. Creation time and other complaint fields are preserved, modification time changes, and subsequent tracking and dashboard requests read the current persisted status.

## Administrator interface

The local interface is served at `/admin.html`. It uses the routes above without introducing a separate frontend authorization mechanism. The bearer token exists only in page memory, is sent in the `Authorization` header, and is lost when the page is refreshed or closed. A protected-route `401` returns the interface to sign-in. Complaint content is rendered as text. Listing filters combine and use the API's opaque cursor for next/previous paging; the interface does not persist credentials or complaint records in browser storage.

## API Gateway HTTP API v2 adapter

`cloudpoint.lambda_adapter.lambda_handler` maps API Gateway payload format `2.0` into the same WSGI application. `isBase64Encoded` must be a JSON boolean when present; omission defaults to `false`. String, numeric, and null values return a structured `400`. The adapter does not provision or modify AWS resources. Its default handler requires `CLOUDPOINT_DYNAMODB_TABLE`; region configuration uses `CLOUDPOINT_AWS_REGION` or the runtime `AWS_REGION`; AWS credentials come from the runtime role/provider chain.

## Browser/API routing and CORS

The deployment template places a CloudFront HTTPS distribution in front of both the private S3 origin and API Gateway. Browser code uses the relative `/api` base path; CloudFront forwards `/api/*` and `/health*` to API Gateway, and the browser keeps the same origin for static files and API requests. API Gateway `CorsConfiguration` is intentionally absent, which prevents wildcard CORS and avoids a browser preflight for this same-origin design. Direct cross-origin browser calls to the API Gateway URL are not supported. CORS is not an authorization control; protected routes still validate the signed session. The CloudFront API behavior does not cache responses and forwards only `Authorization`, `Content-Type`, and query strings.

The prepared HTTPS origin is CloudFront's AWS-provided hostname; there is no custom domain or Route 53 dependency. CloudFront also applies viewer HTTPS redirection and response security headers. The template sets best-effort API Gateway rate/burst limits on the login route and default routes; AWS throttling is not a hard abuse or cost cap. The deployment scripts require an expected AWS account ID and explicit region, verify CloudPoint stack tags/ARN/outputs and S3 ownership markers before changes, and require a separate `-UpdateExisting` opt-in for an existing stack. Cleanup has a distinct destructive opt-in. These settings exist in the local CloudFormation template only and have not been deployed or verified in AWS.

The application emits JSON operation events with `request_id`, a fixed operation name, outcome, and exception class for failures. Successful complaint submission and status updates are also recorded by operation and request ID. Request bodies, complaint IDs, names, registration numbers, rejection text, passwords, authorization headers, tokens, and exception messages are omitted. The local WSGI server suppresses its default request-line logs because tracking paths contain bearer-like complaint IDs. The template defines five-minute CloudWatch alarms on Lambda `Errors`, Lambda `Throttles`, and API Gateway HTTP API `5xx`; each moves to `ALARM` on any nonzero metric value in its evaluation period. Missing metrics are treated as non-breaching. The alarms have no notification actions configured, so operators must have read access and actively monitor alarm state. Runtime IAM remains scoped to log writes; operator read permissions must be configured and reviewed separately. These template settings and CloudWatch behavior are unverified until an approved deployment.

## SQLite and DynamoDB storage contract

SQLite stores administrator and revocable session records in separate local tables alongside complaints. DynamoDB continues to use the pre-existing table with string partition key `complaint_id` and no sort key or GSI. Complaint IDs remain direct keys. The same table uses reserved `ADMIN#<normalized username>` and `SESSION#<sha256 token digest>` key prefixes for administrator and session items; each has a `record_type`. Existing complaint items without `record_type` are treated as complaints for backward compatibility. Complaint IDs begin with `CP-`, so these reserved keys cannot collide with valid complaint IDs. Admin listing and dashboard scans filter out internal records.

| Access pattern | DynamoDB operation |
|---|---|
| Complaint submit/read/status update | Conditional `PutItem`, consistent `GetItem`, conditional `UpdateItem` |
| Administrator lookup | Consistent `GetItem` on `ADMIN#username` |
| Session create/read/revoke | Conditional `PutItem`, consistent `GetItem`, `DeleteItem` on `SESSION#digest` |
| Admin list/search/category/status filters | Paginated `Scan` with server-side filters |
| Dashboard counts | Full paginated scan projecting complaint ID and status |

Title and registration search uses lowercase indexed-on-write attributes plus `contains` in a scan; it is not full-text search and consumes reads proportional to scanned data. The README's small workload triggers remain operational review points, not quotas or a cost guarantee. DynamoDB scans and multi-page dashboard counts are not a point-in-time snapshot; concurrent updates can produce a transiently mixed count. Direct adapter use requires a table with the documented string partition key to pre-exist; the prepared CloudFormation template defines it for a new deployment. Deployment IAM, billing controls, API Gateway throttling, HTTPS hosting, and cleanup remain unverified until an approved deployment and review.
