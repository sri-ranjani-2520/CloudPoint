[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory = $true)]
    [ValidateLength(1, 46)]
    [ValidatePattern('^[A-Za-z][A-Za-z0-9-]*$')]
    [string] $StackName,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$')]
    [string] $ArtifactBucketName,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d{12}$')]
    [string] $ExpectedAccountId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9]+(-[a-z0-9]+)+-[0-9]+$')]
    [string] $Region,

    [ValidatePattern('^[A-Za-z0-9._-]{1,64}$')]
    [string] $SessionSecretRevision = '1',

    [switch] $UpdateExisting,
    [switch] $Execute
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $Execute) {
    Write-Host 'No AWS operations were run. Supply -Execute after reviewing the account, region, artifact bucket, and cost impact.'
    return
}
if (-not $PSCmdlet.ShouldProcess("CloudPoint stack '$StackName' in account '$ExpectedAccountId' region '$Region'", 'Upload package, create/update AWS resources, publish frontend')) {
    return
}
if (-not (Get-Command aws -ErrorAction SilentlyContinue)) { throw 'AWS CLI v2 is required.' }
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'Python is required to prepare the Lambda package.' }

. (Join-Path $PSScriptRoot 'aws_safety.ps1')
. (Join-Path $PSScriptRoot 's3_enumeration.ps1')
Assert-AwsIdentity -ExpectedAccountId $ExpectedAccountId -Region $Region
Assert-S3BucketOwnership -BucketName $ArtifactBucketName -ExpectedAccountId $ExpectedAccountId -Region $Region -Purpose 'LambdaArtifacts'
$existingStack = Get-CloudPointStack -StackName $StackName -ExpectedAccountId $ExpectedAccountId -Region $Region
if ($null -ne $existingStack -and -not $UpdateExisting) {
    throw 'The stack already exists. Verify its ownership and pass -UpdateExisting to authorize an update.'
}
if ($null -eq $existingStack -and $UpdateExisting) {
    throw 'The stack does not exist. Remove -UpdateExisting to follow the new-stack path.'
}
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$templatePath = Join-Path $projectRoot 'infra/cloudpoint.template.json'
$lambdaSource = Join-Path $projectRoot 'cloudpoint'
$frontendSource = Join-Path $projectRoot 'frontend'
$frontendKeys = @(Get-ChildItem -LiteralPath $frontendSource -File -Recurse | ForEach-Object {
    $_.FullName.Substring($frontendSource.Length).TrimStart('\', '/') -replace '\\', '/'
})
if ($frontendKeys.Count -eq 0) { throw 'The frontend manifest is empty; deployment was refused.' }
$createFrontendFetcher = {
    param([string] $Bucket)
    $frontendBucketForListing = $Bucket
    return {
        param($ContinuationToken)
        $arguments = @('s3api', 'list-objects-v2', '--bucket', $frontendBucketForListing, '--expected-bucket-owner', $ExpectedAccountId, '--region', $Region, '--max-keys', '1000', '--no-paginate', '--output', 'json')
        if ($null -ne $ContinuationToken) { $arguments += @('--continuation-token', $ContinuationToken) }
        $response = & aws @arguments 2>$null
        if ($LASTEXITCODE -ne 0) { throw 'S3 object listing failed.' }
        return ($response -join "`n")
    }.GetNewClosure()
}.GetNewClosure()
$assertFrontendManifest = {
    param([string] $Bucket)
    $fetcher = & $createFrontendFetcher $Bucket
    $inventory = Get-S3ObjectInventory -FetchPage $fetcher
    $manifest = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    foreach ($key in $frontendKeys) { $null = $manifest.Add($key) }
    $unexpected = @($inventory.Items | Where-Object { -not $manifest.Contains([string]$_.Key) })
    if ($unexpected.Count -gt 0) {
        $names = ($unexpected | ForEach-Object { [string]$_.Key }) -join ', '
        throw "Frontend bucket contains stale or unrecognized object keys: $names. Review and remove only confirmed CloudPoint assets through a separately approved operation; no objects were deleted or uploaded."
    }
}.GetNewClosure()
if ($null -ne $existingStack) {
    $existingOutputs = @{}
    foreach ($output in $existingStack.Outputs) { $existingOutputs[$output.OutputKey] = $output.OutputValue }
    Assert-S3BucketOwnership -BucketName $existingOutputs.FrontendBucketName -ExpectedAccountId $ExpectedAccountId -Region $Region -Purpose 'FrontendHosting'
    & $assertFrontendManifest $existingOutputs.FrontendBucketName
}

$tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$buildId = [guid]::NewGuid().ToString('N')
$packageRoot = [System.IO.Path]::GetFullPath((Join-Path $tempRoot "cloudpoint-$buildId"))
$zipPath = Join-Path $tempRoot "cloudpoint-$buildId.zip"

if (-not $packageRoot.StartsWith($tempRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'The temporary package path is outside the system temporary directory.'
}

try {
    New-Item -ItemType Directory -Path $packageRoot | Out-Null
    $packageModuleRoot = Join-Path $packageRoot 'cloudpoint'
    New-Item -ItemType Directory -Path $packageModuleRoot | Out-Null
    Get-ChildItem -LiteralPath $lambdaSource -Filter '*.py' -File -Recurse | ForEach-Object {
        $relativePath = $_.FullName.Substring($lambdaSource.Length).TrimStart('\', '/')
        $destination = Join-Path $packageModuleRoot $relativePath
        New-Item -ItemType Directory -Path (Split-Path $destination -Parent) -Force | Out-Null
        Copy-Item -LiteralPath $_.FullName -Destination $destination
    }
    Compress-Archive -Path (Join-Path $packageRoot '*') -DestinationPath $zipPath -CompressionLevel Optimal
    $packageHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $objectKey = "cloudpoint/lambda/$packageHash.zip"

    & aws s3api put-object --bucket $ArtifactBucketName --key $objectKey --body $zipPath --expected-bucket-owner $ExpectedAccountId --region $Region --output json
    if ($LASTEXITCODE -ne 0) { throw 'Uploading the Lambda package failed.' }

    $tags = @(
        'Key=CloudPointProject,Value=CloudPoint',
        "Key=CloudPointOwnerAccount,Value=$ExpectedAccountId",
        'Key=CloudPointPurpose,Value=ServerlessApplication'
    )
    $templateUri = "file://$templatePath"
    if ($null -eq $existingStack) {
        & aws cloudformation create-stack --stack-name $StackName --region $Region --template-body $templateUri --parameters "ParameterKey=LambdaCodeBucket,ParameterValue=$ArtifactBucketName" "ParameterKey=LambdaCodeKey,ParameterValue=$objectKey" "ParameterKey=SessionSecretRevision,ParameterValue=$SessionSecretRevision" --tags $tags --capabilities CAPABILITY_IAM
        if ($LASTEXITCODE -ne 0) { throw 'CloudFormation did not accept the new stack creation.' }
        & aws cloudformation wait stack-create-complete --stack-name $StackName --region $Region
        $stackWaitSucceeded = $LASTEXITCODE -eq 0
    } else {
        $updateOutput = & aws cloudformation update-stack --stack-name $StackName --region $Region --template-body $templateUri --parameters "ParameterKey=LambdaCodeBucket,ParameterValue=$ArtifactBucketName" "ParameterKey=LambdaCodeKey,ParameterValue=$objectKey" "ParameterKey=SessionSecretRevision,ParameterValue=$SessionSecretRevision" --tags $tags --capabilities CAPABILITY_IAM 2>&1
        $updateExitCode = $LASTEXITCODE
        if ($updateExitCode -eq 0) {
            & aws cloudformation wait stack-update-complete --stack-name $StackName --region $Region
            $stackWaitSucceeded = $LASTEXITCODE -eq 0
        } elseif (($updateOutput -join "`n") -match 'No updates are to be performed') {
            $stackWaitSucceeded = $true
        } else {
            throw 'CloudFormation did not accept the explicitly authorized stack update.'
        }
    }
    if (-not $stackWaitSucceeded) { throw 'CloudFormation did not reach a complete stack state.' }

    $stack = Get-CloudPointStack -StackName $StackName -ExpectedAccountId $ExpectedAccountId -Region $Region
    if ($null -eq $stack) { throw 'CloudPoint stack could not be verified after deployment.' }
    $outputMap = @{}
    foreach ($output in $stack.Outputs) { $outputMap[$output.OutputKey] = $output.OutputValue }
    Assert-S3BucketOwnership -BucketName $outputMap.FrontendBucketName -ExpectedAccountId $ExpectedAccountId -Region $Region -Purpose 'FrontendHosting'
    & $assertFrontendManifest $outputMap.FrontendBucketName
    Get-ChildItem -LiteralPath $frontendSource -File -Recurse | ForEach-Object {
        $key = $_.FullName.Substring($frontendSource.Length).TrimStart('\', '/') -replace '\\', '/'
        $contentType = switch ([System.IO.Path]::GetExtension($_.Name).ToLowerInvariant()) {
            '.html' { 'text/html; charset=utf-8' }
            '.js' { 'text/javascript; charset=utf-8' }
            '.css' { 'text/css; charset=utf-8' }
            default { 'application/octet-stream' }
        }
        & aws s3api put-object --bucket $outputMap.FrontendBucketName --key $key --body $_.FullName --content-type $contentType --expected-bucket-owner $ExpectedAccountId --region $Region --output json
        if ($LASTEXITCODE -ne 0) { throw 'Uploading a frontend file failed.' }
    }
    & aws cloudfront create-invalidation --distribution-id $outputMap.CloudFrontDistributionId --paths '/*' --region $Region --output json
    if ($LASTEXITCODE -ne 0) { throw 'CloudFront cache invalidation failed.' }
    Write-Host "CloudPoint frontend: $($outputMap.FrontendUrl)"
    Write-Host "API Gateway endpoint (diagnostics only): $($outputMap.HttpApiUrl)"
    Write-Host "DynamoDB table: $($outputMap.DynamoDBTableName)"
    Write-Host 'DynamoDB complaint data is retained if the application stack is deleted.'
}
finally {
    if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
    $resolvedTemp = [System.IO.Path]::GetFullPath($tempRoot).TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    $resolvedPackage = [System.IO.Path]::GetFullPath($packageRoot)
    if ($resolvedPackage.StartsWith($resolvedTemp, [System.StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $resolvedPackage)) {
        Remove-Item -LiteralPath $resolvedPackage -Recurse -Force
    }
}
