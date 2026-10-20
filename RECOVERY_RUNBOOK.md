# CloudPoint deployment recovery runbook

**Scope:** Local preparation for an explicitly approved AWS deployment. This document does not authorize deployment, cleanup, or deletion. Do not create AWS resources just to test this runbook.

## Before any deployment

- Confirm the target AWS account ID, region, stack name, and artifact bucket with the account owner.
- Review `AWS_DEPLOYMENT_CHECKLIST.md`, the current CloudFormation template, and the exact script parameters.
- Keep a copy of the exact source ZIP and record the content-addressed Lambda artifact key produced by the deployment script.
- Agree on a test-only dataset, an administrator provisioning plan, a backup/restore policy, and a maximum acceptable cost before creating resources.

## If first-time CloudFormation creation ends in `ROLLBACK_COMPLETE`

1. Stop. Do not rerun deployment or improvise a stack deletion command.
2. In the CloudFormation console, select the exact stack in the confirmed account and region. Review **Events** from newest to oldest to identify the first resource failure and the rollback outcome.
3. Record the stack name, stack ID, failing logical resource, failure reason, and any physical resource IDs. Do not paste credentials or secret values into logs or tickets.
4. Check whether the failed attempt left a content-addressed ZIP in the separate artifact bucket. Do not delete it until its ownership and use have been checked.
5. Have the account owner approve a recovery path based on the actual events and remaining resources. The current `remove_deployment.ps1` intentionally refuses `ROLLBACK_COMPLETE`; it is not a recovery tool for that state.
6. After the recovery is reviewed, fix the root cause locally, rerun applicable tests/lint, and only then plan a new deployment attempt.

## If the stack is complete but frontend publishing or CloudFront invalidation fails

- Treat the release as potentially incomplete or mixed. Do not announce the application as ready.
- Keep the stack and current assets in place while reviewing the deployment output and CloudFront status.
- Confirm the deployed stack, bucket ownership, expected frontend manifest, and artifact key before choosing a repair. The deployment script does not provide atomic frontend/backend release rollback or a general previous-version selector.
- After the repair is approved, publish the intended frontend release and verify the site, same-origin `/api` requests, and browser behavior before accepting the release.

## Before using `remove_deployment.ps1`

- Cleanup is destructive and requires both `-Execute` and `-ApproveDestructive`; PowerShell `ShouldProcess` confirmation also applies.
- Verify account, region, stack identity, frontend bucket ownership/tags, public-access block, encryption, and that the bucket is not versioned. The script refuses unexpected object keys and multipart-upload inventory failures.
- **Known limitation:** the script deletes verified frontend objects before CloudFormation stack deletion completes, because the stack owns the bucket and a non-empty bucket can prevent deletion. If deletion later fails, the frontend may be unavailable until the approved recovery is completed.
- The DynamoDB complaints table is retained by policy. The separate artifact bucket and Lambda ZIPs are not deleted by this script. The Secrets Manager secret may remain pending deletion according to its recovery settings. These resources may continue to incur charges.
- Do not run cleanup as a troubleshooting shortcut. First identify the failure and obtain explicit account-owner approval.

## After an approved deployment

Verify HTTPS frontend delivery and same-origin API routing; student submission and tracking; administrator login/logout, authorization, search/filter/pagination, dashboard counts, status updates and rejection reasons; CloudWatch logs/alarms; and effective IAM permissions. Use test-only records. Configure and test backups and restoration separately; DynamoDB retention is not a backup.

## Failed initial CloudFormation creation

If initial stack creation ends in `ROLLBACK_COMPLETE`, do not rerun deployment
or use the normal cleanup script. The standard safety helper intentionally
rejects this state. First inspect the CloudFormation stack events and identify
the root cause. Any deletion or recovery must be reviewed against the expected
AWS account, region, stack ownership tags, and retained DynamoDB data. Do not
delete the retained complaint table or the separate artifact bucket as part
of routine stack recovery. No recovery action should be taken until the
account and potential charges have been checked.
