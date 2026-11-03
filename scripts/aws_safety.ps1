Set-StrictMode -Version Latest

function Assert-AwsIdentity {
    param(
        [Parameter(Mandatory = $true)][string] $ExpectedAccountId,
        [Parameter(Mandatory = $true)][string] $Region
    )

    if ($ExpectedAccountId -notmatch '^\d{12}$') {
        throw 'ExpectedAccountId must be a 12-digit AWS account ID.'
    }
    if ($Region -notmatch '^[a-z0-9]+(-[a-z0-9]+)+-[0-9]+$') {
        throw 'Region must be an explicit AWS region name.'
    }

    $account = (& aws sts get-caller-identity --region $Region --query Account --output text 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $account -notmatch '^\d{12}$') {
        throw 'AWS caller identity could not be verified. No resource changes were made.'
    }
    if ($account -ne $ExpectedAccountId) {
        throw 'The active AWS account does not match ExpectedAccountId. No resource changes were made.'
    }
}

function Assert-S3BucketOwnership {
    param(
        [Parameter(Mandatory = $true)][string] $BucketName,
        [Parameter(Mandatory = $true)][string] $ExpectedAccountId,
        [Parameter(Mandatory = $true)][string] $Region,
        [Parameter(Mandatory = $true)][string] $Purpose
    )

    $null = & aws s3api head-bucket --bucket $BucketName --expected-bucket-owner $ExpectedAccountId --region $Region 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw 'The S3 bucket does not exist, is inaccessible, or is not owned by ExpectedAccountId.'
    }

    $location = & aws s3api get-bucket-location --bucket $BucketName --expected-bucket-owner $ExpectedAccountId --region $Region --query LocationConstraint --output text 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'The S3 bucket region could not be verified.' }
    if ($location -eq 'None' -or [string]::IsNullOrWhiteSpace([string]$location)) { $location = 'us-east-1' }
    if ($location -ne $Region) { throw 'The S3 bucket is not in the requested deployment region.' }

    $tagJson = & aws s3api get-bucket-tagging --bucket $BucketName --expected-bucket-owner $ExpectedAccountId --region $Region --output json 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'The S3 bucket ownership markers could not be verified.' }
    $tagging = $tagJson | ConvertFrom-Json
    $tagMap = @{}
    foreach ($tag in $tagging.TagSet) { $tagMap[$tag.Key] = $tag.Value }
    if (
        $tagMap.CloudPointProject -ne 'CloudPoint' -or
        $tagMap.CloudPointPurpose -ne $Purpose -or
        $tagMap.CloudPointOwnerAccount -ne $ExpectedAccountId
    ) {
        throw 'The S3 bucket lacks the required CloudPoint ownership markers.'
    }

    $encryptionJson = & aws s3api get-bucket-encryption --bucket $BucketName --expected-bucket-owner $ExpectedAccountId --region $Region --output json 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'The S3 bucket encryption configuration could not be verified.' }
    $encryption = $encryptionJson | ConvertFrom-Json
    if (-not $encryption.ServerSideEncryptionConfiguration.Rules) {
        throw 'The S3 bucket must have default server-side encryption enabled.'
    }

    $publicAccessJson = & aws s3api get-public-access-block --bucket $BucketName --expected-bucket-owner $ExpectedAccountId --region $Region --output json 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'The S3 bucket public-access block could not be verified.' }
    $publicAccess = $publicAccessJson | ConvertFrom-Json
    $block = $publicAccess.PublicAccessBlockConfiguration
    if (-not ($block.BlockPublicAcls -and $block.IgnorePublicAcls -and $block.BlockPublicPolicy -and $block.RestrictPublicBuckets)) {
        throw 'The S3 bucket must block all public access.'
    }
}

function Get-CloudPointStack {
    param(
        [Parameter(Mandatory = $true)][string] $StackName,
        [Parameter(Mandatory = $true)][string] $ExpectedAccountId,
        [Parameter(Mandatory = $true)][string] $Region
    )

    $previousErrorAction = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $result = & aws cloudformation describe-stacks --stack-name $StackName --region $Region --output json 2>&1
        $exitCode = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorAction
    }
    if ($exitCode -ne 0) {
        $message = $result -join "`n"
        if ($message -match 'ValidationError' -and $message -match 'does not exist') { return $null }
        throw 'CloudFormation stack metadata could not be read. Ownership was not established.'
    }

    try { $stack = ($result | ConvertFrom-Json).Stacks | Select-Object -First 1 }
    catch { throw 'CloudFormation returned malformed stack metadata. Ownership was not established.' }
    if (-not $stack -or $stack.StackName -ne $StackName) {
        throw 'CloudFormation returned an unexpected stack. Ownership was not established.'
    }
    if ($stack.StackStatus -notin @('CREATE_COMPLETE', 'UPDATE_COMPLETE', 'UPDATE_ROLLBACK_COMPLETE')) {
        throw 'The stack is not in a stable, supported state. Ownership was not established.'
    }

    $stackArn = [regex]::Match([string]$stack.StackId, '^arn:[^:]+:cloudformation:([^:]+):(\d{12}):stack/')
    if (-not $stackArn.Success) {
        throw 'The stack ARN is malformed. Ownership was not established.'
    }
    if ($stackArn.Groups[1].Value -ne $Region -or $stackArn.Groups[2].Value -ne $ExpectedAccountId) {
        throw 'The stack account or region does not match the requested deployment target.'
    }

    $tagMap = @{}
    foreach ($tag in $stack.Tags) { $tagMap[$tag.Key] = $tag.Value }
    if (
        $tagMap.CloudPointProject -ne 'CloudPoint' -or
        $tagMap.CloudPointPurpose -ne 'ServerlessApplication' -or
        $tagMap.CloudPointOwnerAccount -ne $ExpectedAccountId
    ) {
        throw 'The stack lacks the required CloudPoint ownership markers.'
    }

    $outputMap = @{}
    foreach ($output in $stack.Outputs) { $outputMap[$output.OutputKey] = $output.OutputValue }
    foreach ($key in @('FrontendBucketName', 'DynamoDBTableName', 'CloudFrontDistributionId')) {
        if ([string]::IsNullOrWhiteSpace([string]$outputMap[$key])) {
            throw 'The stack is missing a required CloudPoint output. Ownership was not established.'
        }
    }

    $resourceJson = & aws cloudformation list-stack-resources --stack-name $StackName --region $Region --output json 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'CloudFormation resource metadata could not be verified.' }
    $resourceSet = ($resourceJson | ConvertFrom-Json).StackResourceSummaries
    $frontendResource = $resourceSet | Where-Object { $_.LogicalResourceId -eq 'FrontendBucket' -and $_.ResourceType -eq 'AWS::S3::Bucket' } | Select-Object -First 1
    $tableResource = $resourceSet | Where-Object { $_.LogicalResourceId -eq 'ComplaintsTable' -and $_.ResourceType -eq 'AWS::DynamoDB::Table' } | Select-Object -First 1
    if (-not $frontendResource -or $frontendResource.PhysicalResourceId -ne $outputMap.FrontendBucketName) {
        throw 'The frontend bucket output does not match the verified CloudPoint stack resource.'
    }
    if (-not $tableResource -or $tableResource.PhysicalResourceId -ne $outputMap.DynamoDBTableName) {
        throw 'The DynamoDB table output does not match the verified CloudPoint stack resource.'
    }

    $templateJson = & aws cloudformation get-template --stack-name $StackName --template-stage Processed --region $Region --output json 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'The deployed template could not be checked for data retention.' }
    $templateEnvelope = $templateJson | ConvertFrom-Json
    $deployedTemplate = $templateEnvelope.TemplateBody
    if ($deployedTemplate -is [string]) { $deployedTemplate = $deployedTemplate | ConvertFrom-Json }
    $deployedTable = $deployedTemplate.Resources.ComplaintsTable
    if ($deployedTable.DeletionPolicy -ne 'Retain' -or $deployedTable.UpdateReplacePolicy -ne 'Retain') {
        throw 'The deployed stack does not guarantee complaint-table retention. Cleanup was refused.'
    }
    return $stack
}
