# CloudPoint Deployment Readiness Audit

**Audit date:** 2026-10-19
**Scope:** Static review of the checked-in AWS template, deployment scripts, application adapters, frontend/API path alignment, documentation, and automated tests. A follow-up hardening change adds an AWS CloudFormation template-validation gate before artifact upload.
**Deployment status:** Not deployed. No AWS resources were created or modified during this audit.

## Summary

The repository contains the main serverless architecture and local checks for CloudPoint. The code and infrastructure definition are promising, but this audit does **not** certify the stack as deployable because CloudFormation/AWS validation and deployed end-to-end tests have not been performed.

## Checks performed

- Parsed `infra/cloudpoint.template.json` as JSON and checked resource/parameter references using the repository's infrastructure tests.
- Ran `python -m unittest discover -s tests -v` after the follow-up hardening change: **91 passed, 8 skipped**. The skipped checks require Windows PowerShell, which was unavailable in the audit environment.
- Ran `python -m compileall -q cloudpoint tools tests`: passed.
- Ran `node --test tests/student_ui.test.cjs tests/admin_ui.test.cjs`: **14 passed**.
- Ran `python -m compileall -q cloudpoint tools tests`: passed.
- Parsed the CloudFormation JSON: passed; 23 resources and 3 parameters were found. Added a regression test for the CloudFront API origin request policy header-list shape.
- Simulated the deployment script's Lambda ZIP layout: `cloudpoint/lambda_adapter.py` and `cloudpoint/__init__.py` are at the expected package paths.
- The frontend publisher assigns explicit MIME types for JPEG/JPG, PNG, WebP, SVG, ICO, and JSON assets instead of sending these through the generic binary fallback. The MIME behavior has a regression test.
- Added a guarded `aws cloudformation validate-template` check before the deployment script uploads the Lambda artifact or requests stack creation/update. A failed validation now stops the script before those changes.
- Confirmed AWS Lambda's `python3.14` runtime identifier is listed in current AWS runtime documentation.

These checks validate local code and template structure only. The new AWS template-validation gate is implemented but was not run here. The checks do not validate AWS service acceptance, account permissions, pricing, or live behavior.

## Deployment and cleanup script review (static; not executed)

- `scripts/deploy.ps1` has a default no-op unless `-Execute` is supplied, then uses PowerShell `ShouldProcess`; it checks the active AWS account, explicit region, and artifact-bucket ownership/region/tags/encryption/public-access block before uploading the Lambda package. Existing-stack updates require the explicit `-UpdateExisting` switch.
- `scripts/remove_deployment.ps1` requires both `-Execute` and `-ApproveDestructive`, then uses `ShouldProcess`; it verifies account and stack ownership, refuses versioned frontend buckets, fully enumerates frontend objects and multipart uploads, and refuses unexpected keys before deleting known frontend objects. It intentionally does not delete the separate artifact bucket or its Lambda ZIPs, and the DynamoDB table has a Retain policy.
- **Recovery limitation documented:** `Get-CloudPointStack` only accepts `CREATE_COMPLETE`, `UPDATE_COMPLETE`, and `UPDATE_ROLLBACK_COMPLETE`. If a first-time stack creation ends in `ROLLBACK_COMPLETE`, the cleanup script refuses to process it. `RECOVERY_RUNBOOK.md` now describes a safe review/approval workflow for this state; it does not automate deletion or recovery.
- The deployment script uploads the Lambda ZIP before CloudFormation create/update. If CloudFormation rejects the template or deployment, the uploaded content-addressed ZIP may remain in the artifact bucket. This is not data loss, but it can leave storage costs and requires deliberate retention/cleanup.
- Frontend assets are uploaded after the CloudFormation stack reaches a complete state. If a later frontend upload or CloudFront invalidation fails, the release may be mixed; no automatic atomic release rollback is implemented.
- These are static findings from reading the scripts; no AWS CLI commands or PowerShell deployment/cleanup scripts were executed.

## Deployment prerequisites / remaining gates

1. **Deployment tooling:** The deployment script requires AWS CLI v2, Python, and Windows PowerShell. The target operator's Windows machine must have these installed and verified.
2. **Artifact bucket:** A suitable existing private S3 artifact bucket must be created separately and its name supplied to the deployment script. The script checks account ownership before upload; the stack template does not create this bucket.
3. **Deployment identity:** Review and approve least-privilege permissions for the human/CI deployment identity. The repository scopes the Lambda runtime role, but does not define a complete deployment-role policy.
4. **Administrator provisioning:** After the DynamoDB table exists, provision an administrator using `python -m tools.create_admin --dynamodb` with approved AWS credentials. This writes to the target table and must only be done with explicit authorization.
5. **CloudFormation validation:** The deployment script now runs `aws cloudformation validate-template` before artifact upload and stack changes. This check was not executed during this audit because AWS CLI was unavailable; verify it in the intended account/region before provisioning. `cfn-lint` was also unavailable in the audit environment.
6. **PowerShell script tests:** Re-run the eight skipped infrastructure/script tests in Windows PowerShell before using the deployment or cleanup scripts.
7. **Cost review:** Confirm account eligibility, region-specific pricing, CloudFront transfer, API Gateway requests, Lambda, DynamoDB scans, Secrets Manager, and CloudWatch charges. Free-tier eligibility is not a spending cap and zero cost is not guaranteed.
8. **Operational readiness:** Approve a backup and restore policy and test restore in an isolated environment. DynamoDB retention on stack deletion is not a backup. Define and test rollback: the current script does not provide a supported previous-package rollback selector or an atomic frontend/backend release.
9. **Post-deployment acceptance (only after separately approved deployment):** Verify HTTPS, browser-to-API routing, admin authorization, complaint submit/track/status update, dashboard counts, logs and alarm behavior, and effective IAM permissions. Do not use real student data until these checks are complete.

## Security / cost observations

- The frontend bucket is configured private with public-access blocking and encryption; CloudFront provides the HTTPS front door and same-origin API routing.
- API responses are configured not to be cached by CloudFront.
- The Lambda role's DynamoDB and Secrets Manager permissions are resource-scoped in the template.
- CloudWatch alarms are defined for Lambda errors/throttles and API Gateway 5xx responses, but no alarm notification actions are configured.
- Dashboard counts and administrator search use DynamoDB scans. This is reasonable only for a small prototype; scan latency and read cost increase with data volume.
- The DynamoDB complaints table is retained on stack deletion/replacement, but backup/restore is not configured.
- The cleanup procedure can leave the artifact bucket and uploaded Lambda ZIPs in place; retained storage and Secrets Manager recovery windows can continue to incur charges.

## Recommendation

Treat the repository as **locally tested and statically reviewed, but not AWS-validated**. The frontend MIME-type gap found during this audit has been fixed and covered by a regression test. Keep the current feature scope frozen. Before any deployment, complete the tooling, artifact bucket, deployment IAM, administrator-provisioning, CloudFormation validation, PowerShell test, cost, backup, and rollback gates above. Do not execute deployment or cleanup scripts without explicit account-owner approval.
