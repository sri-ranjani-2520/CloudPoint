Set-StrictMode -Version Latest

function Get-S3PageValue {
    param(
        [Parameter(Mandatory = $true)][object] $Page,
        [Parameter(Mandatory = $true)][string] $Name,
        [switch] $Required
    )

    $value = $null
    if ($Page -is [System.Collections.IDictionary]) {
        if ($Page.Contains($Name)) { $value = $Page[$Name] }
    } elseif ($Page.PSObject -and $Page.PSObject.Properties[$Name]) {
        $value = $Page.PSObject.Properties[$Name].Value
    }
    if ($null -ne $value) {
        if ($value -is [array]) { return ,$value }
        return $value
    }
    if ($Required) { throw 'S3 returned a malformed listing page.' }
    return $null
}

function Test-S3PageProperty {
    param([Parameter(Mandatory = $true)][object] $Page, [Parameter(Mandatory = $true)][string] $Name)
    if ($Page -is [System.Collections.IDictionary]) { return $Page.Contains($Name) }
    return [bool]($Page.PSObject -and $Page.PSObject.Properties[$Name])
}

function ConvertTo-S3ListingPage {
    param([Parameter(Mandatory = $true)][object] $Response)

    try {
        if ($Response -is [string]) { $page = $Response | ConvertFrom-Json -ErrorAction Stop }
        else { $page = $Response }
    } catch {
        throw 'S3 returned malformed listing JSON.'
    }
    if ($null -eq $page) { throw 'S3 returned a malformed listing page.' }
    $truncated = Get-S3PageValue -Page $page -Name 'IsTruncated' -Required
    if ($truncated -isnot [bool]) { throw 'S3 returned a malformed pagination flag.' }
    return $page
}

function Get-S3ObjectInventory {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][scriptblock] $FetchPage)

    $items = [System.Collections.Generic.List[object]]::new()
    $seenTokens = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    $token = $null
    $pages = 0
    while ($true) {
        try { $response = & $FetchPage $token }
        catch { throw 'S3 object enumeration failed; cleanup was refused.' }
        $page = ConvertTo-S3ListingPage -Response $response
        $pages++
        $contents = Get-S3PageValue -Page $page -Name 'Contents'
        if ((Test-S3PageProperty -Page $page -Name 'Contents') -and $null -eq $contents) {
            throw 'S3 returned a malformed object list.'
        }
        if ($null -ne $contents) {
            if ($contents -is [string] -or $contents -is [System.Collections.IDictionary]) { throw 'S3 returned a malformed object list.' }
            foreach ($item in @($contents)) {
                $key = Get-S3PageValue -Page $item -Name 'Key' -Required
                if ($key -isnot [string] -or [string]::IsNullOrWhiteSpace($key)) {
                    throw 'S3 returned an invalid object key.'
                }
                $items.Add($item)
            }
        }
        if (-not (Get-S3PageValue -Page $page -Name 'IsTruncated' -Required)) { break }
        $next = Get-S3PageValue -Page $page -Name 'NextContinuationToken' -Required
        if ($next -isnot [string] -or [string]::IsNullOrWhiteSpace($next) -or -not $seenTokens.Add($next)) {
            throw 'S3 object pagination did not advance; cleanup was refused.'
        }
        $token = $next
    }
    return [pscustomobject]@{ Items = $items.ToArray(); Pages = $pages }
}

function Get-S3MultipartUploadInventory {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][scriptblock] $FetchPage)

    $items = [System.Collections.Generic.List[object]]::new()
    $seenTokens = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    $keyMarker = $null
    $uploadIdMarker = $null
    $pages = 0
    while ($true) {
        try { $response = & $FetchPage $keyMarker $uploadIdMarker }
        catch { throw 'S3 multipart-upload enumeration failed; cleanup was refused.' }
        $page = ConvertTo-S3ListingPage -Response $response
        $pages++
        $uploads = Get-S3PageValue -Page $page -Name 'Uploads'
        if ((Test-S3PageProperty -Page $page -Name 'Uploads') -and $null -eq $uploads) {
            throw 'S3 returned a malformed multipart-upload list.'
        }
        if ($null -ne $uploads) {
            if ($uploads -is [string] -or $uploads -is [System.Collections.IDictionary]) { throw 'S3 returned a malformed multipart-upload list.' }
            foreach ($item in @($uploads)) { $items.Add($item) }
        }
        if (-not (Get-S3PageValue -Page $page -Name 'IsTruncated' -Required)) { break }
        $nextKey = Get-S3PageValue -Page $page -Name 'NextKeyMarker' -Required
        $nextUpload = Get-S3PageValue -Page $page -Name 'NextUploadIdMarker' -Required
        if (
            $nextKey -isnot [string] -or [string]::IsNullOrWhiteSpace($nextKey) -or
            $nextUpload -isnot [string] -or [string]::IsNullOrWhiteSpace($nextUpload)
        ) { throw 'S3 multipart pagination returned incomplete markers; cleanup was refused.' }
        $marker = $nextKey + "`n" + $nextUpload
        if (-not $seenTokens.Add($marker)) { throw 'S3 multipart pagination did not advance; cleanup was refused.' }
        $keyMarker = $nextKey
        $uploadIdMarker = $nextUpload
    }
    return [pscustomobject]@{ Items = $items.ToArray(); Pages = $pages }
}

function Get-VerifiedFrontendInventory {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][scriptblock] $FetchObjectPage,
        [Parameter(Mandatory = $true)][scriptblock] $FetchMultipartPage,
        [Parameter(Mandatory = $true)][string[]] $AllowedKeys
    )

    # Complete both independent read-only listings before validating content.
    $objects = Get-S3ObjectInventory -FetchPage $FetchObjectPage
    $uploads = Get-S3MultipartUploadInventory -FetchPage $FetchMultipartPage
    if ($uploads.Items.Count -gt 0) {
        throw 'The frontend bucket has incomplete multipart uploads. Review and abort them separately; no objects were deleted.'
    }
    $allowed = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    foreach ($key in $AllowedKeys) { $null = $allowed.Add($key) }
    $unexpected = @($objects.Items | Where-Object { -not $allowed.Contains([string]$_.Key) })
    if ($unexpected.Count -gt 0) {
        throw 'The frontend bucket contains objects outside the current frontend manifest. Review them separately; no objects were deleted.'
    }
    return [pscustomobject]@{ Objects = $objects.Items; ObjectPages = $objects.Pages; UploadPages = $uploads.Pages }
}
