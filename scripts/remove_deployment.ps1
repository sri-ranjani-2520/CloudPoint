[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory = $true)]
    [ValidateLength(1, 46)]
    [ValidatePattern('^[A-Za-z][A-Za-z0-9-]*$')]
    [string] $StackName,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d{12}$')]
    [string] $ExpectedAccountId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9]+(-[a-z0-9]+)+-[0-9]+$')]
    [string] $Region,

    [switch] $ApproveDestructive,
    [switch] $Execute
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not $Execute -or -not $ApproveDestructive) {
    Write-Host 'No AWS operations were run. Cleanup requires both -Execute and the separate -ApproveDestructive opt-in.'
    return
}
if (-not $PSCmdlet.ShouldProcess("CloudPoint stack '$StackName' in account '$ExpectedAccountId' region '$Region'", 'Delete verified CloudPoint frontend objects and application stack')) {
    return
}
if (-not (Get-Command aws -ErrorAction SilentlyContinue)) { throw 'AWS CLI v2 is required.' }

. (Join-Path $PSScriptRoot 'aws_safety.ps1')
. (Join-Path $PSScriptRoot 's3_enumeration.ps1')
Assert-AwsIdentity -ExpectedAccountId $ExpectedAccountId -Region $Region
$stack = Get-CloudPointStack -StackName $StackName -ExpectedAccountId $ExpectedAccountId -Region $Region
if ($null -eq $stack) { throw 'The CloudPoint stack does not exist. No cleanup was performed.' }

$outputMap = @{}
foreach ($output in $stack.Outputs) { $outputMap[$output.OutputKey] = $output.OutputValue }
$bucketName = $outputMap.FrontendBucketName
Assert-S3BucketOwnership -BucketName $bucketName -ExpectedAccountId $ExpectedAccountId -Region $Region -Purpose 'FrontendHosting'

$versioningJson = & aws s3api get-bucket-versioning --bucket $bucketName --expected-bucket-owner $ExpectedAccountId --region $Region --output json 2>$null
if ($LASTEXITCODE -ne 0) { throw 'Frontend bucket versioning could not be verified. No cleanup was performed.' }
$versioning = $versioningJson | ConvertFrom-Json
if ($versioning.Status -eq 'Enabled' -or $versioning.Status -eq 'Suspended') {
    throw 'Versioned frontend buckets require a reviewed version-cleanup plan. No objects were deleted.'
}

$fetchObjectPage = {
    param($ContinuationToken)
    $arguments = @('s3api', 'list-objects-v2', '--bucket', $bucketName, '--expected-bucket-owner', $ExpectedAccountId, '--region', $Region, '--max-keys', '1000', '--no-paginate', '--output', 'json')
    if ($null -ne $ContinuationToken) { $arguments += @('--continuation-token', $ContinuationToken) }
    $response = & aws @arguments 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'S3 object listing failed.' }
    return ($response -join "`n")
}.GetNewClosure()
$fetchMultipartPage = {
    param($KeyMarker, $UploadIdMarker)
    $arguments = @('s3api', 'list-multipart-uploads', '--bucket', $bucketName, '--expected-bucket-owner', $ExpectedAccountId, '--region', $Region, '--max-uploads', '1000', '--no-paginate', '--output', 'json')
    if ($null -ne $KeyMarker) { $arguments += @('--key-marker', $KeyMarker) }
    if ($null -ne $UploadIdMarker) { $arguments += @('--upload-id-marker', $UploadIdMarker) }
    $response = & aws @arguments 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'S3 multipart-upload listing failed.' }
    return ($response -join "`n")
}.GetNewClosure()
$frontendSource = Join-Path (Resolve-Path (Join-Path $PSScriptRoot '..')).Path 'frontend'
if (-not (Test-Path -LiteralPath $frontendSource -PathType Container)) {
    throw 'The checked-in frontend manifest is unavailable. No cleanup was performed.'
}
$allowedKeys = @(Get-ChildItem -LiteralPath $frontendSource -File -Recurse | ForEach-Object {
    $_.FullName.Substring($frontendSource.Length).TrimStart('\', '/') -replace '\\', '/'
})
if ($allowedKeys.Count -eq 0) { throw 'The checked-in frontend manifest is empty. No cleanup was performed.' }
$inventory = Get-VerifiedFrontendInventory -FetchObjectPage $fetchObjectPage -FetchMultipartPage $fetchMultipartPage -AllowedKeys $allowedKeys
$objectKeys = @($inventory.Objects | ForEach-Object { $_.Key })

foreach ($key in $objectKeys) {
    & aws s3api delete-object --bucket $bucketName --key $key --expected-bucket-owner $ExpectedAccountId --region $Region --output json
    if ($LASTEXITCODE -ne 0) { throw 'Deleting a verified frontend object failed; the CloudFormation stack was not deleted.' }
}

& aws cloudformation delete-stack --stack-name $StackName --region $Region
if ($LASTEXITCODE -ne 0) { throw 'CloudFormation did not accept the verified CloudPoint stack deletion.' }
& aws cloudformation wait stack-delete-complete --stack-name $StackName --region $Region
if ($LASTEXITCODE -ne 0) { throw 'CloudFormation did not finish deleting the application stack.' }

Write-Host 'The frontend, API, Lambda, IAM role, and log group were removed with the stack.'
Write-Host 'The DynamoDB table is retained by policy. The session secret may remain pending deletion under Secrets Manager recovery behavior.'
Write-Host 'The separate Lambda artifact bucket and its uploaded ZIP objects were not deleted.'
