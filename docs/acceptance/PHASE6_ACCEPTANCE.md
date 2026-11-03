# CloudPoint Phase 6 — Dashboard Counts and Operational Visibility

This record follows the project owner's clarified eight-phase roadmap. It preserves useful local acceptance evidence from the earlier, conflicting six-phase roadmap but does not treat that earlier final-acceptance scope as the current Phase 6 objective.

## Current Phase 6 requirements

The owner-defined Phase 6 requires:

1. Correct complaint totals and counts by current status.
2. A counting strategy appropriate to expected volume, with consistency behavior documented.
3. CloudWatch alarms for elevated errors, throttling, and failures.
4. Request correlation IDs and structured logs that exclude sensitive contents.
5. Review of log retention and operational access.
6. Safe operational information to investigate failed submissions and status updates.

**Exit criteria:** Dashboard counts meet agreed consistency needs, and operators can detect and investigate service failures.

## Findings before this implementation

- SQLite already calculated status totals in one grouped query.
- DynamoDB already paginated a full-table scan and requested strongly consistent reads, but the cost and lack of scan snapshot isolation needed clearer documentation and regression coverage for mixed statuses/internal records.
- The Lambda adapter did not forward the API Gateway request ID to the WSGI application; responses had no correlation header.
- Application errors logged only free-form operation/error-class text, without request IDs. Complaint data was not included, but operators could not join a failed request to a log event. The local WSGI server's default access log includes request paths, which can include complaint IDs.
- The CloudFormation template had a 14-day log group but no CloudWatch metric alarms.

## Implemented and locally verified

| Requirement | Implementation and evidence | Status |
|---|---|---|
| Dashboard totals and status counts | SQLite grouped query; DynamoDB full paginated scan. API and repository tests verify mixed statuses, internal-record exclusion, and `total == sum(status counts)`. | Pass locally |
| Consistency and volume behavior | DynamoDB requests `ConsistentRead=true` on each scan page. No point-in-time snapshot is promised across pages; concurrent writes can produce a mixed-time view. Every valid observed complaint contributes once to total and one current status. Strong reads and a full scan per dashboard load are retained for the small workload and documented as cost/latency limits. | Documented and tested locally; growth review still required |
| Correlation IDs | API Gateway request ID is accepted only if safe and bounded; otherwise Lambda invocation ID or a generated UUID is used. WSGI responses return `X-Request-Id`. Tests cover propagation and unsafe ID replacement. | Pass locally |
| Structured, privacy-safe operation logs | JSON events identify fixed operation, request ID, success/failure, and exception class. Complaint content, identifiers, student details, credentials, tokens, exception messages, and filesystem paths are omitted. Submission/update failure and success paths are covered. Default local WSGI access-line logging is suppressed to avoid logging tracking IDs in request paths. | Pass locally |
| CloudWatch alarms | Template defines five-minute sum alarms for Lambda `Errors`, Lambda `Throttles`, and API Gateway HTTP API `5xx`; any nonzero value breaches. | Template and structural tests pass locally; not deployed |
| Retention and operational access | Existing log retention is 14 days. Lambda runtime role writes logs but cannot read logs or alarm state; separate least-privilege operator read access is required. Alarms have no notification actions, so operators must monitor their state; no notification service was added. | Template reviewed; account operator access and monitoring unverified |

## Preserved prior local acceptance evidence

The previous Phase 6 attempt used an outdated six-phase roadmap where Phase 6 meant final acceptance/documentation. Its useful local workflow evidence remains relevant to the overall project:

| Earlier scenario | Local evidence | Result |
|---|---|---|
| Student submission, validation, unique ID, tracking privacy | `tests/test_api.py`, `tests/test_foundation.py` | Pass in local tests |
| Admin authentication and direct authorization | `tests/test_api.py`, `tests/test_dynamodb_repository.py` | Pass in local tests |
| Admin filters, pagination, details, status/rejection updates, dashboard | `tests/test_api.py`, `tests/test_dynamodb_repository.py`, `tests/admin_ui.test.cjs` | Pass against SQLite and local DynamoDB/UI fakes |
| Student/admin UI behavior | `tests/admin_ui.test.cjs` | Pass in fake DOM/API tests; not a real browser run |
| API/config/deployment/cleanup documentation | `../../API_CONTRACTS.md`, `../../LOCAL_DEVELOPMENT.md`, deployment scripts | Documented and structurally tested; deployment scripts not executed |
| Search/count and cost limitations | `../../API_CONTRACTS.md`, `../../LOCAL_DEVELOPMENT.md`, `../../README.md` | Documented; actual cost unverified |

The former six-phase roadmap's deployed final-acceptance and billing criteria are not reassigned to Phase 7 or 8 here. Their owner-defined scopes have not been provided and remain pending in `../../README.md`.

## AWS-dependent verification still pending

No AWS resource was deployed or changed for this work. Local tests establish application behavior and inspect the template; they do not verify CloudFormation acceptance, metric publication/dimensions, actual alarm states, deployed log retention, operator IAM, or cost. The alarms have no notification action and are not a hard cost-control mechanism.

After the template receives independent review and deployment is explicitly approved, in the intended account and region:

1. Validate and deploy the reviewed stack using the protected deployment procedure.
2. Generate synthetic Lambda errors, throttles where safely feasible, and API 5xx responses; confirm the matching CloudWatch metric dimensions and alarm transitions.
3. Confirm `X-Request-Id` appears in successful and failed responses, then find matching structured Lambda log events. Verify no request body, authorization value, student data, complaint ID, or exception text is present.
4. Verify the 14-day retention policy and give operators only the CloudWatch read permissions needed for logs and alarm state. Establish a human monitoring/notification procedure separately; no SNS integration is configured.
5. Review current CloudWatch and DynamoDB charges. A full strongly consistent scan per dashboard request has read cost that grows with the scanned table; alarms do not cap spending.

Do not use real student data for this validation.

## Commands and results

Results for this implementation are recorded in the task completion report. The intended local checks are:

- `python -m unittest discover -s tests -v`
- `python -m compileall -q cloudpoint tools tests`
- `git diff --check`
- `node --check frontend/static/admin.js`
- `node tests/admin_ui.test.cjs`
- Python standard-library parse of `infra/cloudpoint.template.json`

Passing local checks do not establish deployed AWS behavior.
