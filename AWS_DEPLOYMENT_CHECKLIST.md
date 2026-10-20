# CloudPoint AWS Deployment Checklist

**Current state: prepared for review; not deployed.** The repository has not provisioned or modified AWS resources as part of this audit. Passing local tests does not mean the CloudFormation stack has been accepted by AWS or that the live application has been verified.

## Important cost boundary

Do not run the deployment script with `-Execute` until the AWS account owner explicitly approves the account, region, permissions, and possible charges. CloudFront, Secrets Manager, API requests, Lambda, DynamoDB reads/writes, logging, data transfer, and retained S3 artifacts can incur charges. Free-tier eligibility is not a guarantee of zero cost. Creating the separate Lambda artifact bucket is also an AWS resource and is not automated by this project.

The following are intentionally **not** done: AWS account login, artifact-bucket creation, CloudFormation deployment, administrator provisioning, live requests, or cleanup. No AWS resources should be created just to complete this local readiness review.

## Before an approved deployment

- [ ] Install and verify AWS CLI v2, Python, and Windows PowerShell on the deployment machine.
- [ ] Confirm the intended AWS account ID and region, and review current pricing and account eligibility.
- [ ] Have the account owner create/approve a private, encrypted artifact bucket with all S3 Block Public Access settings enabled. The deployment script verifies bucket ownership, region, encryption, public-access block, and CloudPoint ownership tags.
- [ ] Review the deployment identity's IAM permissions. The runtime role is scoped in the template, but this repository does not provide a complete deployment-role policy.
- [ ] Review `infra/cloudpoint.template.json` and `scripts/deploy.ps1`. The deployment script requires `-Execute`; an existing stack additionally requires `-UpdateExisting`.
- [ ] Run the AWS CloudFormation template validation gate in the intended account/region. When the deployment script is explicitly executed, it calls `aws cloudformation validate-template` before uploading the Lambda package or requesting stack creation/update. This validation call is not a deployment, but it does require AWS CLI access.
- [ ] Run the Windows PowerShell tests in `tests/test_infrastructure.py`; eight script behavior tests were skipped in the audit environment because PowerShell was unavailable.
- [ ] Review `RECOVERY_RUNBOOK.md`; approve data retention, backup/restore, alarm notification, and rollback procedures. Table retention is not a backup; atomic frontend/backend rollback is not implemented.
- [ ] Agree on a test-only dataset and an authorized administrator credential provisioning plan.

## After deployment is separately approved

- [ ] Verify the HTTPS frontend and same-origin API routing.
- [ ] Test student submission, generated complaint ID, tracking, administrator login/logout, dashboard counts, search/filter/pagination, status changes, and rejection reasons.
- [ ] Verify unauthorized administrator requests fail and inspect CloudWatch logs/alarms.
- [ ] Confirm effective IAM permissions and ensure no real student data is used until acceptance checks pass.
- [ ] Configure and test backups and recovery in an isolated environment; document the tested rollback procedure.
- [ ] Review ongoing charges and remove only resources explicitly approved for removal. The complaint table is retained by policy, and the separate artifact bucket/artifacts are not deleted by the cleanup script.

## Known operational limitations

- A first-time stack that ends in `ROLLBACK_COMPLETE` is not handled by the cleanup script. Do not improvise deletion commands; follow `RECOVERY_RUNBOOK.md` and obtain approval for a reviewed recovery path.
- A failed frontend upload or CloudFront invalidation can leave a mixed release; automatic atomic release rollback is not implemented. Follow `RECOVERY_RUNBOOK.md` before repairing it.
- The cleanup script refuses versioned frontend buckets and unexpected objects rather than attempting broad deletion.
- The three CloudWatch alarms have no notification actions configured because no notification recipient has been approved.
- Dashboard counts and admin search use DynamoDB scans, which are suitable only for a small prototype and may become slower/costlier as data grows.
