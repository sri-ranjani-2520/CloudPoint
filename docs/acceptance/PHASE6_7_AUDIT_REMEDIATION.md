# CloudPoint Phase 6–7 Audit Remediation Record

This record confirms the audit findings against the current local files and identifies what can be safely concluded without AWS access. No deployment, AWS API call, resource operation, or dependency installation was performed.

## Finding status

| Finding | Confirmed state | Local remediation/result |
|---|---|---|
| P6/P7-001 — Backup/restore and recovery objectives | Confirmed. `ComplaintsTable` has `DeletionPolicy: Retain` and `UpdateReplacePolicy: Retain`; there is no `PointInTimeRecoverySpecification`, DynamoDB backup, AWS Backup plan, restore workflow, or RPO/RTO. | Documented accurately and added a regression assertion preventing retention from being described as backup. Not technically resolved; backup configuration has cost and requires explicit approval. |
| P6/P7-002 — Release rollback | Confirmed. Lambda package keys are content-addressed and uploaded to the artifact bucket, but deployment does not record a selectable known-good release. Frontend objects are uploaded to stable keys without S3 versioning or a retained frontend package. There is no rollback command. | Documented the non-atomic failure mode and minimum prerequisites. No safe end-to-end rollback was added because a durable frontend history would require versioning or retained release artifacts, both of which add storage/cost and need an approved retention policy. |
| P6/P7-003 — CloudFormation/API Gateway validation | Confirmed that no validator or AWS-side validation was run. The configured `HTTP` API, `AWS_PROXY` Lambda integration, Lambda function ARN `Fn::GetAtt`, and payload `2.0` match the documented HTTP API Lambda-proxy configuration. | Local structural test and documentation identify the expected shape. This is not CloudFormation validation: `aws`, `cfn-lint`, and `sam` are unavailable, and no CloudFormation API was called. |
| P6-004 — Alarm notification actions | Confirmed. All three alarms omit `AlarmActions` and there is no SNS topic. | Documented manual monitoring and notification options; tests now ensure no notification service is added without an approved recipient and cost decision. Not technically resolved. |
| P6/P7-005 — Billing, deployed IAM, throttling, runtime | Confirmed unverified. The template defines runtime IAM, throttling, and alarms, but there is no AWS account evidence or billing configuration in the repository. | Added a target-account verification checklist. These items remain pending AWS access and owner approval. |
| Browser accessibility/responsiveness | Confirmed incomplete. Existing UI checks use a fake DOM/API; no browser engine or browser/a11y automation package is installed. | Existing fake-DOM tests remain useful but are not represented as browser tests. Manual browser and assistive-technology checks are listed below. |

## Backup and recovery posture

### Current state

The retention policies protect the table from deletion when its CloudFormation stack is deleted or the table is replaced. They do not create a recoverable copy. PITR, scheduled/on-demand backups, backup vaults, restore permissions, restore tests, and recovery objectives are absent. If complaint data is deleted or corrupted while the table is live, there is currently no configured data-level recovery path. If the table is retained after stack deletion, it remains available as an orphaned table but the application stack/API is gone.

### Required recovery design before production use

The owner must select and approve a recovery objective before choosing the mechanism. Record a numeric **recovery point objective (RPO)** (maximum acceptable data loss) and **recovery time objective (RTO)** (maximum acceptable outage); neither is currently defined, so no numeric target is assumed here.

The minimum candidate for a continuously recoverable single-region table is DynamoDB point-in-time recovery (PITR), with the recovery window selected by the owner. If policy also requires a separately retained snapshot, evaluate scheduled/on-demand backups and their retention separately. PITR and backups are chargeable based on current AWS pricing and table/storage usage; restore can also incur temporary restored-table, read/write, logging, and data-transfer costs. Confirm current regional pricing and account eligibility before enabling either. Table retention alone is not a backup. Cross-region recovery would add replication/storage and transfer costs and is outside the current design.

Before implementation, approve: RPO/RTO; PITR versus snapshots (or both); backup retention and deletion policy; encryption/key ownership; the operator and break-glass roles; restore permissions; the restore-table cutover approach; and the budget owner. The current template binds Lambda and its IAM policy to `ComplaintsTable`; a restored-table cutover therefore needs a reviewed template change that can select a restored table without replacing or deleting the retained source.

A complete restore exercise must:

1. Preserve the source table and record the chosen recovery point; pause complaint writes for the cutover window.
2. Restore to a separate table, never over the source.
3. Validate schema/key shape, record counts, representative complaints, administrator records, and session-expiry behavior without exposing real complaint contents in logs.
4. Configure the application to use the restored table through a reviewed stack change. The current template binds Lambda and IAM directly to the CloudFormation-created table and does not support selecting a restored external table; template support for safe cutover is therefore a prerequisite.
5. Run health, student tracking, admin authorization, list/detail/update, and dashboard smoke checks against the restored table.
6. Measure achieved RPO/RTO, record the restored table ARN and data validation evidence without copying complaint data into logs, and resume traffic only after owner sign-off. Retain the source table until verification and rollback windows end.

No restore can be called operational until a backup is configured, permissions are reviewed, and this procedure is implemented and exercised in an isolated AWS environment. Enabling PITR/backups or adding restore-table support requires separate review and approval. The future cost estimate should include ongoing PITR/backup storage, retained copies, temporary restored-table capacity, and any cross-region transfer; obtain an account/region estimate before approval.

## Release preservation and rollback

The current release path checks account, region, stack and bucket ownership, and update opt-in. It hashes the Lambda ZIP into an artifact object key, then updates CloudFormation and uploads frontend files individually to stable object keys. It invalidates CloudFront after uploads. It does not persist a combined release manifest, frontend archive, previous-object versions, or a previous-release selector. If the stack update succeeds and frontend upload fails midway, clients can see a mixed release. If a frontend-only publish succeeds, there is no script-level route back to the previous frontend. CloudFormation's rollback for a failed stack update does not undo a later S3 frontend publish or create a complete application rollback.

A safe rollback implementation should use an immutable, release-ID-addressed bundle in the existing private artifact bucket. Each bundle should contain the exact Lambda ZIP, complete frontend archive, template, non-secret parameter metadata, and a manifest of SHA-256 hashes plus source revision and target stack/account/region. Never put secret values in the bundle. Stage and verify the complete bundle before changing the stack. Require the existing account, region, ownership, update opt-in, and `ShouldProcess` checks for both publish and rollback; rollback should require a separate explicit release ID and destructive-operation confirmation.

The deploy/rollback runbook should enter a controlled maintenance window before changing either tier, preserve the currently active release and its manifest, update the backend and frontend only from verified release artifacts, perform health and workflow smoke checks, invalidate CloudFront, and leave maintenance mode only after both tiers pass. If any step fails, restore both tiers from the captured known-good release and repeat smoke checks before resuming service. Since CloudFormation and S3 updates do not form one atomic transaction, the runbook must explicitly state the mixed-version risk during the maintenance window and must not claim zero-downtime atomic rollback. Avoid deleting releases as part of rollback.

This approach can reuse the existing artifact bucket and AWS services, but each retained frontend archive, Lambda package, and manifest adds S3 storage and request costs. The owner must approve a retention count/duration and cost estimate before implementation; cleanup must preserve the active and designated known-good releases and must never automatically remove an unverified release. S3 versioning is an alternative with additional retained-version storage and lifecycle complexity, not a free rollback mechanism. No release bundle format, selector, or rollback command is implemented yet. Until implementation and an isolated rollback exercise are complete, treat updates as having no supported application rollback. Do not manually delete retained complaint data during a rollback.

## CloudFormation/API Gateway integration validation

The template currently sets API protocol `HTTP`, integration type `AWS_PROXY`, integration URI to the Lambda function ARN, `IntegrationMethod` to `POST`, and `PayloadFormatVersion` to `2.0`. AWS's [HTTP API Lambda integration guide](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-develop-integrations-lambda.html) and [CloudFormation integration resource reference](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-apigatewayv2-integration.html) document this combination: HTTP API Lambda proxy integrations use a Lambda function URI and payload format `1.0` or `2.0`. The local structural assertion checks the same values.

This evidence supports the configuration shape; it does **not** establish CloudFormation schema acceptance, account/region compatibility, Lambda invoke permission behavior, or successful stack creation. No suitable local validator was found (`aws`, `cfn-lint`, and `sam` are not installed). Before deployment, run an approved offline `cfn-lint` check in a provisioned validation environment, then have an authorized owner review a CloudFormation change set/service validation in the target account and region. Do not execute the change set until separately approved.

## Alarms, notification, and billing controls

The existing Lambda Errors, Lambda Throttles, and API Gateway 5xx alarms have no actions. An operator with CloudWatch read access can inspect their state manually, but the alarms do not page or email anyone. The Lambda role only writes application logs; it does not read alarm state or send notifications.

One option is an owner-managed SNS topic with an explicitly confirmed email subscription, connected using each alarm's `AlarmActions`. CloudWatch alarm actions accept an SNS topic ARN ([CloudFormation alarm reference](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-cloudwatch-alarm.html)). The topic resource policy should allow `sns:Publish` to `cloudwatch.amazonaws.com` only when `aws:SourceAccount` and `aws:SourceArn` identify the CloudPoint account and alarms, following AWS's [CloudWatch alarm notification policy guidance](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Notify_Users_Alarm_Changes.html). Operators need least-privilege read access to alarm state/logs; the deployment principal needs permission to create/update the topic, policy, subscription, and alarm actions if these are managed in the stack. Email/SNS delivery and CloudWatch alarm usage have account/region pricing implications; check current pricing and confirm a recipient before adding the service. No SNS resource was added in this remediation.

### Target-account verification checklist (pending approval)

1. Confirm the intended AWS account and region; confirm the operators can access billing and cost data.
2. Review current prices, expected usage, and free-tier eligibility. Configure an AWS Budget or billing alert with a monitored recipient, confirm its subscription and test delivery. A budget alert is not a hard spending cap.
3. Inspect the deployed Lambda execution role's inline/attached policies and effective resource ARNs. Compare them with the template's table, secret, and log-group scope. Review the human/deployment role separately; no deploy-role policy is supplied here.
4. Inspect the deployed HTTP API `$default` stage and login route throttle settings. Test only with low-volume synthetic requests in a non-production environment. API throttles are best-effort and do not cap total spend.
5. Verify the Lambda `Errors`/`Throttles` and API Gateway `5xx` metrics with exact function/API/stage dimensions. Trigger controlled failures only in a non-production environment and confirm each alarm state.
6. Confirm the log group has 14-day retention, operator read access is limited, request IDs correlate responses and logs, and log samples contain no student data, complaint descriptions, credentials, authorization values, or secret material.
7. If notification actions are later approved, confirm SNS subscription, topic policy restrictions, delivery, alarm transitions, and ongoing costs. Document who responds to each alarm.
8. Verify CloudFront HTTPS and same-origin routing, API caching behavior, and the deployed stack's actual resources. Do not use real student data until these checks and recovery procedures pass.

## Browser and assistive-technology checks

The environment has no installed browser executable, Playwright/Puppeteer, Selenium, or axe automation. No browser or screen-reader checks ran. The local Node fake-DOM/API tests do not establish rendering or accessibility conformance. Before release, test both pages at 320, 375, 768, and desktop widths; at 200% zoom; and with keyboard-only navigation. Check focus order/visibility and detail close behavior, native and server validation announcements, busy/empty/error states, horizontal table scrolling, and screen-reader labels/status messages in the supported browser/assistive-technology pair.

## Local evidence added

`tests/test_infrastructure.py` now asserts that table retention is not mistaken for backups, the frontend has no versioning/rollback archive, and alarms have no notification actions until an approved recipient and notification design exist. These are regression checks of the current limitations, not proof that deployment or recovery works.

## Phase 7 local gap review (2026-10-10)

The environment check found PowerShell, Python, and Node.js, but no browser executable, browser automation/accessibility package, AWS CLI, `cfn-lint`, or SAM CLI. No tools or dependencies were installed. The existing UI tests use a fake DOM and remain behavioral unit tests, not browser validation. Therefore responsive rendering, keyboard-only use, focus movement, zoom, and assistive-technology behavior remain open for a browser-enabled environment.

Offline infrastructure validation available here consists of parsing the template as JSON, asserting resource relationships/properties in the Python infrastructure tests, and parsing PowerShell scripts into ASTs without executing them. These checks can detect malformed JSON/scripts and regressions in the expected template structure; they cannot establish CloudFormation schema acceptance or deployed behavior. The HTTP API Lambda proxy configuration is consistent with the documented AWS resource shape, but requires an installed offline CloudFormation validator and then separately approved target-account validation before deployment.

The release and recovery sections above now define the minimum design inputs, procedure, and cost categories. This closes the local documentation/design gap only. No rollback mechanism, backup configuration, restore workflow, or browser test has been implemented or exercised. Phase 7 remains partially complete and release readiness remains open.
