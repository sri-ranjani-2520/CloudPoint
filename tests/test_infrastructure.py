import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class InfrastructureDefinitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template_text = (PROJECT_ROOT / "infra" / "cloudpoint.template.json").read_text(encoding="utf-8")
        cls.template = json.loads(cls.template_text)
        cls.resources = cls.template["Resources"]
        cls.deploy = (PROJECT_ROOT / "scripts" / "deploy.ps1").read_text(encoding="utf-8")
        cls.cleanup = (PROJECT_ROOT / "scripts" / "remove_deployment.ps1").read_text(encoding="utf-8")
        cls.safety = (PROJECT_ROOT / "scripts" / "aws_safety.ps1").read_text(encoding="utf-8")
        cls.enumeration = (PROJECT_ROOT / "scripts" / "s3_enumeration.ps1").read_text(encoding="utf-8")

    def test_template_json_and_resource_references_are_valid(self):
        resource_names = set(self.resources)
        parameter_names = set(self.template.get("Parameters", {}))

        def walk(value):
            if isinstance(value, dict):
                if "Ref" in value:
                    target = value["Ref"]
                    if not target.startswith("AWS::"):
                        self.assertIn(target, resource_names | parameter_names)
                if "Fn::GetAtt" in value:
                    self.assertIn(value["Fn::GetAtt"][0], resource_names)
                if "Fn::Sub" in value:
                    template = value["Fn::Sub"] if isinstance(value["Fn::Sub"], str) else value["Fn::Sub"][0]
                    for target in re.findall(r"\$\{([A-Za-z][A-Za-z0-9]*)(?:\.[^}]+)?\}", template):
                        if not target.startswith("AWS::"):
                            self.assertIn(target, resource_names | parameter_names)
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(self.template)

    def test_required_phase_three_resources_and_retention_are_defined(self):
        expected_types = {
            "AWS::DynamoDB::Table",
            "AWS::Lambda::Function",
            "AWS::ApiGatewayV2::Api",
            "AWS::IAM::Role",
            "AWS::Logs::LogGroup",
            "AWS::S3::Bucket",
            "AWS::CloudFront::Distribution",
            "AWS::SecretsManager::Secret",
        }
        self.assertTrue(expected_types.issubset({item["Type"] for item in self.resources.values()}))
        table = self.resources["ComplaintsTable"]
        self.assertEqual(table["DeletionPolicy"], "Retain")
        self.assertEqual(table["UpdateReplacePolicy"], "Retain")
        self.assertEqual(table["Properties"]["BillingMode"], "PAY_PER_REQUEST")
        self.assertEqual(table["Properties"]["KeySchema"], [{"AttributeName": "complaint_id", "KeyType": "HASH"}])
        self.assertEqual(table["Properties"]["TimeToLiveSpecification"]["AttributeName"], "expires_at")

    def test_api_origin_request_policy_uses_supported_header_list_shape(self):
        policy = self.resources["ApiOriginRequestPolicy"]["Properties"]["OriginRequestPolicyConfig"]
        headers = policy["HeadersConfig"]
        self.assertEqual(headers["HeaderBehavior"], "whitelist")
        self.assertEqual(headers["Headers"], ["Authorization", "Content-Type"])
        self.assertEqual(policy["CookiesConfig"]["CookieBehavior"], "none")
        self.assertEqual(policy["QueryStringsConfig"]["QueryStringBehavior"], "all")

    def test_frontend_bucket_private_owned_and_cloudfront_api_uncached_https(self):
        bucket = self.resources["FrontendBucket"]["Properties"]
        self.assertTrue(all(bucket["PublicAccessBlockConfiguration"].values()))
        self.assertEqual(bucket["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]["ServerSideEncryptionByDefault"]["SSEAlgorithm"], "AES256")
        tags = {tag["Key"]: tag["Value"] for tag in bucket["Tags"]}
        self.assertEqual(tags["CloudPointProject"], "CloudPoint")
        self.assertEqual(tags["CloudPointPurpose"], "FrontendHosting")
        self.assertEqual(tags["CloudPointOwnerAccount"], {"Ref": "AWS::AccountId"})

        bucket_policy = self.resources["FrontendBucketPolicy"]["Properties"]["PolicyDocument"]["Statement"]
        self.assertEqual(bucket_policy[0]["Action"], "s3:GetObject")
        self.assertEqual(bucket_policy[0]["Condition"]["StringEquals"]["AWS:SourceArn"], {"Fn::Sub": "arn:${AWS::Partition}:cloudfront::${AWS::AccountId}:distribution/${FrontendDistribution}"})
        self.assertEqual(bucket_policy[1]["Condition"]["Bool"]["aws:SecureTransport"], "false")

        distribution = self.resources["FrontendDistribution"]["Properties"]["DistributionConfig"]
        self.assertEqual(distribution["DefaultCacheBehavior"]["ViewerProtocolPolicy"], "redirect-to-https")
        self.assertEqual(distribution["Origins"][0]["OriginAccessControlId"], {"Ref": "FrontendOriginAccessControl"})
        api_behavior = next(item for item in distribution["CacheBehaviors"] if item["PathPattern"] == "/api/*")
        self.assertEqual(api_behavior["ViewerProtocolPolicy"], "redirect-to-https")
        self.assertEqual(set(api_behavior["AllowedMethods"]), {"GET", "HEAD", "OPTIONS", "PUT", "PATCH", "POST", "DELETE"})
        self.assertEqual(api_behavior["CachePolicyId"], {"Ref": "ApiCachePolicy"})
        api_cache = self.resources["ApiCachePolicy"]["Properties"]["CachePolicyConfig"]
        self.assertEqual((api_cache["MinTTL"], api_cache["DefaultTTL"], api_cache["MaxTTL"]), (0, 0, 0))

    def test_lambda_runtime_iam_and_secret_read_are_scoped(self):
        function = self.resources["ApiFunction"]["Properties"]
        self.assertEqual(function["Runtime"], "python3.14")
        self.assertEqual(function["Handler"], "cloudpoint.lambda_adapter.lambda_handler")
        self.assertEqual(function["LoggingConfig"], {
            "LogFormat": "JSON",
            "ApplicationLogLevel": "INFO",
            "SystemLogLevel": "INFO",
            "LogGroup": {"Fn::Sub": "/aws/lambda/${AWS::StackName}-api"},
        })
        environment = function["Environment"]["Variables"]
        self.assertNotIn("CLOUDPOINT_SESSION_SECRET", environment)
        self.assertEqual(environment["CLOUDPOINT_SESSION_SECRET_ARN"], {"Ref": "SessionSigningSecret"})
        self.assertEqual(environment["CLOUDPOINT_SESSION_SECRET_REVISION"], {"Ref": "SessionSecretRevision"})

        secret = self.resources["SessionSigningSecret"]
        self.assertEqual(secret["Type"], "AWS::SecretsManager::Secret")
        self.assertEqual(secret["Properties"]["GenerateSecretString"]["PasswordLength"], 64)
        self.assertNotIn("CloudPointSessionSecret", self.template.get("Parameters", {}))

        statements = self.resources["LambdaExecutionRole"]["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
        secret_statement = next(item for item in statements if item.get("Sid") == "ReadOnlySessionSigningSecret")
        self.assertEqual(secret_statement["Action"], "secretsmanager:GetSecretValue")
        self.assertEqual(secret_statement["Resource"], {"Ref": "SessionSigningSecret"})
        for statement in statements:
            actions = statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
            self.assertNotIn("*", actions)
        self.assertEqual(self.resources["LambdaLogGroup"]["Properties"]["RetentionInDays"], 14)

    def test_security_review_controls_are_defined_and_have_explicit_limits(self):
        headers = self.resources["FrontendSecurityHeadersPolicy"]["Properties"]["ResponseHeadersPolicyConfig"]["SecurityHeadersConfig"]
        self.assertTrue(headers["ContentTypeOptions"]["Override"])
        self.assertEqual(headers["FrameOptions"]["FrameOption"], "DENY")
        self.assertEqual(headers["ReferrerPolicy"]["ReferrerPolicy"], "same-origin")
        self.assertEqual(headers["StrictTransportSecurity"]["AccessControlMaxAgeSec"], 63_072_000)
        csp = headers["ContentSecurityPolicy"]["ContentSecurityPolicy"]
        self.assertIn("default-src 'self'", csp)
        self.assertIn("object-src 'none'", csp)
        self.assertIn("frame-ancestors 'none'", csp)

        api = self.resources["HttpApi"]["Properties"]
        self.assertNotIn("CorsConfiguration", api)
        stage = self.resources["HttpApiStage"]["Properties"]
        self.assertEqual(stage["DefaultRouteSettings"]["ThrottlingRateLimit"], 20)
        self.assertEqual(stage["DefaultRouteSettings"]["ThrottlingBurstLimit"], 40)
        self.assertEqual(stage["RouteSettings"]["POST /api/admin/login"]["ThrottlingRateLimit"], 1)
        self.assertEqual(stage["RouteSettings"]["POST /api/admin/login"]["ThrottlingBurstLimit"], 3)
        self.assertEqual(self.resources["LambdaLogGroup"]["Properties"]["RetentionInDays"], 14)

        distribution = self.resources["FrontendDistribution"]["Properties"]["DistributionConfig"]
        api_cache = next(item for item in distribution["CacheBehaviors"] if item["PathPattern"] == "/api/*")
        self.assertEqual(api_cache["CachedMethods"], ["GET", "HEAD", "OPTIONS"])
        self.assertEqual(api_cache["CachePolicyId"], {"Ref": "ApiCachePolicy"})
        self.assertEqual(self.resources["ApiCachePolicy"]["Properties"]["CachePolicyConfig"]["DefaultTTL"], 0)

    def test_operational_alarms_cover_lambda_errors_throttles_and_api_failures(self):
        expected = {
            "LambdaErrorsAlarm": ("AWS/Lambda", "Errors", "FunctionName"),
            "LambdaThrottlesAlarm": ("AWS/Lambda", "Throttles", "FunctionName"),
            "HttpApiServerErrorsAlarm": ("AWS/ApiGateway", "5xx", "ApiId"),
        }
        for logical_id, (namespace, metric_name, dimension_name) in expected.items():
            with self.subTest(alarm=logical_id):
                alarm = self.resources[logical_id]
                self.assertEqual(alarm["Type"], "AWS::CloudWatch::Alarm")
                properties = alarm["Properties"]
                self.assertEqual(properties["Namespace"], namespace)
                self.assertEqual(properties["MetricName"], metric_name)
                self.assertIn(dimension_name, {item["Name"] for item in properties["Dimensions"]})
                self.assertEqual(properties["Period"], 300)
                self.assertEqual(properties["EvaluationPeriods"], 1)
                self.assertEqual(properties["Threshold"], 0)
                self.assertEqual(properties["ComparisonOperator"], "GreaterThanThreshold")
                self.assertEqual(properties["TreatMissingData"], "notBreaching")

        api_dimensions = {
            item["Name"]: item["Value"]
            for item in self.resources["HttpApiServerErrorsAlarm"]["Properties"]["Dimensions"]
        }
        self.assertEqual(api_dimensions, {"ApiId": {"Ref": "HttpApi"}, "Stage": "$default"})
        self.assertEqual(self.resources["LambdaLogGroup"]["Properties"]["RetentionInDays"], 14)

    def test_alarm_notifications_are_not_configured_without_an_approved_recipient(self):
        alarms = [
            resource["Properties"]
            for resource in self.resources.values()
            if resource["Type"] == "AWS::CloudWatch::Alarm"
        ]
        self.assertEqual(len(alarms), 3)
        for properties in alarms:
            self.assertNotIn("AlarmActions", properties)
            self.assertNotIn("OKActions", properties)
        self.assertNotIn("AWS::SNS::Topic", {resource["Type"] for resource in self.resources.values()})

    def test_table_retention_is_not_misrepresented_as_backup_or_restore(self):
        table = self.resources["ComplaintsTable"]
        self.assertEqual(table["DeletionPolicy"], "Retain")
        self.assertEqual(table["UpdateReplacePolicy"], "Retain")
        self.assertNotIn("PointInTimeRecoverySpecification", table["Properties"])
        resource_types = {resource["Type"] for resource in self.resources.values()}
        self.assertNotIn("AWS::DynamoDB::Backup", resource_types)
        self.assertNotIn("AWS::Backup::BackupPlan", resource_types)

    def test_frontend_release_is_not_versioned_for_rollback(self):
        frontend_bucket = self.resources["FrontendBucket"]["Properties"]
        self.assertNotIn("VersioningConfiguration", frontend_bucket)
        self.assertIn("$frontendKeys", self.deploy)
        self.assertIn("--key $key --body $_.FullName", self.deploy)
        self.assertNotIn("FrontendReleaseManifest", self.deploy)

    def test_api_uses_http_api_v2_and_tight_login_throttle(self):
        self.assertEqual(self.resources["ApiLambdaIntegration"]["Properties"]["PayloadFormatVersion"], "2.0")
        integration = self.resources["ApiLambdaIntegration"]["Properties"]
        self.assertEqual(integration["IntegrationType"], "AWS_PROXY")
        self.assertEqual(integration["IntegrationMethod"], "POST")
        self.assertEqual(integration["IntegrationUri"], {"Fn::GetAtt": ["ApiFunction", "Arn"]})
        self.assertEqual(self.resources["HttpApi"]["Properties"]["ProtocolType"], "HTTP")
        stage = self.resources["HttpApiStage"]["Properties"]
        self.assertLess(stage["RouteSettings"]["POST /api/admin/login"]["ThrottlingRateLimit"], stage["DefaultRouteSettings"]["ThrottlingRateLimit"])
        self.assertNotIn("CorsConfiguration", self.resources["HttpApi"]["Properties"])

    def test_account_region_and_artifact_ownership_preflight_precede_upload(self):
        for script in (self.deploy, self.cleanup):
            self.assertIn("$ExpectedAccountId", script)
            self.assertIn("$Region", script)
            self.assertIn("Assert-AwsIdentity -ExpectedAccountId $ExpectedAccountId -Region $Region", script)
        self.assertIn("get-caller-identity --region $Region", self.safety)
        self.assertIn("$account -ne $ExpectedAccountId", self.safety)
        self.assertIn("ExpectedAccountId must be a 12-digit AWS account ID", self.safety)
        self.assertIn("Region must be an explicit AWS region name", self.safety)
        self.assertIn("--expected-bucket-owner $ExpectedAccountId", self.safety)
        self.assertIn("get-bucket-location", self.safety)
        self.assertIn("get-bucket-encryption", self.safety)
        self.assertIn("get-public-access-block", self.safety)
        self.assertIn("CloudPointOwnerAccount", self.safety)
        self.assertIn("LambdaArtifacts", self.deploy)
        self.assertLess(self.deploy.index("Assert-S3BucketOwnership -BucketName $ArtifactBucketName"), self.deploy.index("aws s3api put-object"))
        self.assertLess(self.deploy.index("Get-CloudPointStack -StackName $StackName"), self.deploy.index("aws s3api put-object"))
        self.assertIn("'--region', $Region", self.deploy)
        self.assertIn("'--region', $Region", self.cleanup)
        for line in (self.deploy + self.cleanup + self.safety).splitlines():
            if "& aws " in line and "@arguments" not in line:
                self.assertIn("--region $Region", line, line)

    def test_aws_template_validation_precedes_artifact_upload_and_stack_changes(self):
        validation = self.deploy.index('aws cloudformation validate-template')
        upload = self.deploy.index('aws s3api put-object')
        create = self.deploy.index('aws cloudformation create-stack')
        update = self.deploy.index('aws cloudformation update-stack')
        self.assertLess(validation, upload)
        self.assertLess(validation, create)
        self.assertLess(validation, update)
        self.assertIn('No Lambda artifact was uploaded and no stack changes were requested', self.deploy)
        self.assertIn('if (-not $Execute)', self.deploy)

    def test_existing_stack_update_requires_opt_in_and_ownership_verification(self):
        self.assertIn("[switch] $UpdateExisting", self.deploy)
        self.assertIn("$null -ne $existingStack -and -not $UpdateExisting", self.deploy)
        self.assertIn("$null -eq $existingStack -and $UpdateExisting", self.deploy)
        self.assertIn("if ($message -match 'ValidationError' -and $message -match 'does not exist')", self.safety)
        self.assertIn("CloudPointPurpose", self.safety)
        self.assertIn("ServerlessApplication", self.safety)
        self.assertIn("StackId", self.safety)
        self.assertIn("CloudPointOwnerAccount", self.safety)
        self.assertIn("get-template --stack-name $StackName --template-stage Processed --region $Region", self.safety)
        self.assertIn("$deployedTable.DeletionPolicy -ne 'Retain'", self.safety)
        self.assertLess(self.deploy.index("Get-CloudPointStack -StackName $StackName"), self.deploy.index("aws cloudformation update-stack"))
        self.assertLess(self.deploy.index("Assert-S3BucketOwnership -BucketName $existingOutputs.FrontendBucketName"), self.deploy.index("aws cloudformation update-stack"))
        self.assertIn("aws cloudformation create-stack", self.deploy)
        self.assertIn("aws cloudformation update-stack", self.deploy)
        self.assertIn("if (-not $Execute)", self.deploy)

    def test_cleanup_requires_explicit_approval_and_refuses_unverified_content(self):
        self.assertIn("[switch] $ApproveDestructive", self.cleanup)
        self.assertIn("if (-not $Execute -or -not $ApproveDestructive)", self.cleanup)
        self.assertIn("ShouldProcess", self.cleanup)
        self.assertLess(self.cleanup.index("Get-CloudPointStack -StackName $StackName"), self.cleanup.index("aws s3api delete-object"))
        self.assertLess(self.cleanup.index("Assert-S3BucketOwnership"), self.cleanup.index("aws s3api delete-object"))
        self.assertLess(self.cleanup.index("Get-VerifiedFrontendInventory"), self.cleanup.index("aws s3api delete-object"))
        self.assertIn("Get-S3ObjectInventory", self.enumeration)
        self.assertIn("Get-S3MultipartUploadInventory", self.enumeration)
        self.assertIn("--no-paginate", self.cleanup)
        self.assertIn("--continuation-token", self.cleanup)
        self.assertIn("--key-marker", self.cleanup)
        self.assertIn("--upload-id-marker", self.cleanup)
        self.assertIn("'--region', $Region", self.cleanup)
        self.assertIn("get-bucket-versioning", self.cleanup)
        self.assertIn("list-multipart-uploads", self.cleanup)
        self.assertNotIn("aws s3 rm", self.cleanup)
        self.assertNotIn("ArtifactBucketName", self.cleanup)
        self.assertIn("aws cloudformation delete-stack", self.cleanup)
        self.assertLess(self.cleanup.index("Assert-AwsIdentity"), self.cleanup.index("aws s3api delete-object"))
        self.assertLess(self.cleanup.index("-ApproveDestructive", self.cleanup.index("param(")), self.cleanup.index("aws cloudformation delete-stack"))
        self.assertIn("$frontendSource", self.cleanup)

    def test_frontend_deployment_assigns_image_content_types(self):
        # CloudPoint's logo is a JPEG. Preserve its media type instead of
        # publishing it as application/octet-stream in the S3 object metadata.
        for extension, media_type in (
            ("'.jpeg'", "'image/jpeg'"),
            ("'.jpg'", "'image/jpeg'"),
            ("'.png'", "'image/png'"),
            ("'.webp'", "'image/webp'"),
            ("'.svg'", "'image/svg+xml'"),
        ):
            with self.subTest(extension=extension):
                self.assertRegex(self.deploy, re.escape(extension) + r"\s+\{\s*" + re.escape(media_type))

    def test_deployment_blocks_stale_assets_without_automatic_deletion(self):
        self.assertIn("Get-S3ObjectInventory", self.deploy)
        self.assertIn("$frontendKeys", self.deploy)
        self.assertIn("stale or unrecognized object keys", self.deploy)
        self.assertLess(self.deploy.index("& $assertFrontendManifest $existingOutputs.FrontendBucketName"), self.deploy.index("aws s3api put-object"))
        self.assertNotIn("aws s3api delete-object", self.deploy)
        self.assertNotIn("aws s3 rm", self.deploy)
        self.assertIn("'--region', $Region", self.deploy)

    def test_revision_setting_is_a_lambda_environment_value(self):
        revision = self.template["Parameters"]["SessionSecretRevision"]
        self.assertIn("Default", revision)
        environment = self.resources["ApiFunction"]["Properties"]["Environment"]["Variables"]
        self.assertEqual(environment["CLOUDPOINT_SESSION_SECRET_REVISION"], {"Ref": "SessionSecretRevision"})
        self.assertIn("reads its value during Lambda initialization", (PROJECT_ROOT / "LOCAL_DEVELOPMENT.md").read_text(encoding="utf-8"))


@unittest.skipUnless(shutil.which("powershell.exe") or shutil.which("powershell"), "Windows PowerShell is unavailable")
class S3PaginationBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        cls.helper_path = str(PROJECT_ROOT / "scripts" / "s3_enumeration.ps1").replace("'", "''")
        cls.deploy = (PROJECT_ROOT / "scripts" / "deploy.ps1").read_text(encoding="utf-8")
        cls.template_text = (PROJECT_ROOT / "infra" / "cloudpoint.template.json").read_text(encoding="utf-8")

    def run_powershell(self, body):
        command = f"$ErrorActionPreference='Stop'; . '{self.helper_path}'; {body}"
        result = subprocess.run(
            [self.powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return result.stdout

    def test_single_page_and_empty_listings(self):
        output = self.run_powershell(
            "$obj={param($token) '{\"IsTruncated\":false,\"Contents\":[{\"Key\":\"index.html\"}]}' };"
            "$mp={param($key,$upload) '{\"IsTruncated\":false}' };"
            "$r=Get-VerifiedFrontendInventory -FetchObjectPage $obj -FetchMultipartPage $mp -AllowedKeys @('index.html');"
            "if($r.Objects.Count -ne 1 -or $r.ObjectPages -ne 1 -or $r.UploadPages -ne 1){throw 'single page assertion failed'};"
            "$empty={param($token) '{\"IsTruncated\":false,\"Contents\":[]}' };"
            "$e=Get-S3ObjectInventory -FetchPage $empty; if($e.Items.Count -ne 0){throw 'empty page assertion failed'}"
        )
        self.assertNotIn("assertion failed", output)

    def test_multiple_object_and_multipart_pages_are_fully_enumerated(self):
        self.run_powershell(
            "$script:objectCalls=0; $script:uploadCalls=0;"
            "$obj={param($token) $script:objectCalls++; if($null -eq $token){'{\"IsTruncated\":true,\"NextContinuationToken\":\"next\",\"Contents\":[{\"Key\":\"index.html\"}]}' } else {'{\"IsTruncated\":false,\"Contents\":[{\"Key\":\"static/app.js\"}]}' }};"
            "$mp={param($key,$upload) $script:uploadCalls++; if($null -eq $key){'{\"IsTruncated\":true,\"NextKeyMarker\":\"k2\",\"NextUploadIdMarker\":\"u2\",\"Uploads\":[]}' } else {'{\"IsTruncated\":false,\"Uploads\":[]}' }};"
            "$r=Get-VerifiedFrontendInventory -FetchObjectPage $obj -FetchMultipartPage $mp -AllowedKeys @('index.html','static/app.js');"
            "if($script:objectCalls -ne 2 -or $script:uploadCalls -ne 2 -or $r.Objects.Count -ne 2){throw 'pagination assertion failed'}"
        )

    def test_later_unexpected_object_fails_closed_before_cleanup(self):
        self.run_powershell(
            "$script:called=0; $script:deleteCalls=0;"
            "$obj={param($token) $script:called++; if($null -eq $token){'{\"IsTruncated\":true,\"NextContinuationToken\":\"next\",\"Contents\":[]}' } else {'{\"IsTruncated\":false,\"Contents\":[{\"Key\":\"unrelated.txt\"}]}' }};"
            "$mp={param($key,$upload) '{\"IsTruncated\":false}' };"
            "try {$null=Get-VerifiedFrontendInventory -FetchObjectPage $obj -FetchMultipartPage $mp -AllowedKeys @('index.html'); $script:deleteCalls++} catch {};"
            "Write-Output 'Unexpected object rejected before cleanup.';"
            "if($script:called -ne 2 -or $script:deleteCalls -ne 0){throw 'fail-closed assertion failed'}"
        )

    def test_failed_later_page_and_repeated_tokens_fail_closed(self):
        self.run_powershell(
            "$script:calls=0; $script:deleteCalls=0;"
            "$failed={param($token) $script:calls++; if($null -eq $token){'{\"IsTruncated\":true,\"NextContinuationToken\":\"next\",\"Contents\":[]}' } else {throw 'simulated later-page failure'} };"
            "$mp={param($key,$upload) '{\"IsTruncated\":false}' };"
            "try {$null=Get-VerifiedFrontendInventory -FetchObjectPage $failed -FetchMultipartPage $mp -AllowedKeys @('index.html'); $script:deleteCalls++} catch {};"
            "Write-Output 'Failed later page rejected before cleanup.';"
            "if($script:calls -ne 2 -or $script:deleteCalls -ne 0){throw 'failure assertion failed'};"
            "$repeat={param($token) '{\"IsTruncated\":true,\"NextContinuationToken\":\"same\",\"Contents\":[]}' };"
            "$rejected=$false; try {$null=Get-S3ObjectInventory -FetchPage $repeat} catch {$rejected=$true}; if(-not $rejected){throw 'repeated token was accepted'};"
            "$malformed={param($token) '{\"IsTruncated\":\"false\"}' }; $rejected=$false; try {$null=Get-S3ObjectInventory -FetchPage $malformed} catch {$rejected=$true}; if(-not $rejected){throw 'malformed page was accepted'}"
        )

    def test_multipart_uploads_are_enumerated_on_all_pages_before_refusal(self):
        self.run_powershell(
            "$script:uploadCalls=0;"
            "$obj={param($token) '{\"IsTruncated\":false}' };"
            "$mp={param($key,$upload) $script:uploadCalls++; if($null -eq $key){'{\"IsTruncated\":true,\"NextKeyMarker\":\"k2\",\"NextUploadIdMarker\":\"u2\",\"Uploads\":[{\"UploadId\":\"one\"}]}' } else {'{\"IsTruncated\":false,\"Uploads\":[]}' }};"
            "try {$null=Get-VerifiedFrontendInventory -FetchObjectPage $obj -FetchMultipartPage $mp -AllowedKeys @('index.html'); throw 'unsafe inventory was accepted'} catch {if($_.Exception.Message -eq 'unsafe inventory was accepted'){throw}};"
            "Write-Output ('UPLOADS=' + $script:uploadCalls);"
            "if($script:uploadCalls -ne 2){throw ('multipart pagination stopped early: ' + $script:uploadCalls)}"
        )

    def test_failed_later_multipart_page_prevents_cleanup(self):
        self.run_powershell(
            "$script:uploadCalls=0; $script:deleteCalls=0;"
            "$obj={param($token) '{\"IsTruncated\":false}' };"
            "$mp={param($key,$upload) $script:uploadCalls++; if($null -eq $key){'{\"IsTruncated\":true,\"NextKeyMarker\":\"k2\",\"NextUploadIdMarker\":\"u2\",\"Uploads\":[]}' } else {throw 'later multipart page failed'} };"
            "$rejected=$false; try {$null=Get-VerifiedFrontendInventory -FetchObjectPage $obj -FetchMultipartPage $mp -AllowedKeys @('index.html'); $script:deleteCalls++} catch {$rejected=$true};"
            "Write-Output 'Failed multipart page rejected before cleanup.';"
            "if(-not $rejected -or $script:uploadCalls -ne 2 -or $script:deleteCalls -ne 0){throw 'multipart failure did not stop cleanup'}"
        )

    def test_deployment_scripts_never_put_secrets_in_cli_or_plaintext_parameter_files(self):
        self.assertNotIn("CloudPointSessionSecret", self.deploy)
        self.assertNotIn("WriteAllText", self.deploy)
        self.assertNotIn("icacls", self.deploy)
        self.assertIn("SessionSecretRevision", self.deploy)
        self.assertIn("CLOUDPOINT_SESSION_SECRET_ARN", self.template_text)

    def test_frontend_contract_and_deployment_guard_remain(self):
        html = (PROJECT_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        js = (PROJECT_ROOT / "frontend" / "static" / "app.js").read_text(encoding="utf-8")
        config = (PROJECT_ROOT / "frontend" / "static" / "config.js").read_text(encoding="utf-8")
        self.assertIn("/static/app.js", html)
        self.assertIn("/static/config.js", html)
        self.assertIn('apiBaseUrl: "/api"', config)
        self.assertIn('request("/complaints"', js)
        self.assertIn("encodeURIComponent(complaintId)", js)


if __name__ == "__main__":
    unittest.main()
