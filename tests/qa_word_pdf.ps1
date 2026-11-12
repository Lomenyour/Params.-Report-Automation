param([Parameter(Mandatory=$true)][string]$InputDocx,
      [Parameter(Mandatory=$true)][string]$OutputPdf)
$ErrorActionPreference='Stop'
$wordInput=[IO.Path]::GetFullPath($InputDocx)
$wordOutput=[IO.Path]::GetFullPath($OutputPdf)
if (-not (Test-Path -LiteralPath $wordInput -PathType Leaf)) { throw 'DOCX is missing.' }
if ($wordInput -eq $wordOutput) { throw 'Output must differ from input.' }
$wordApplication=$null
$wordDocument=$null
try {
    $wordApplication=New-Object -ComObject Word.Application
    $wordApplication.Visible=$false
    $wordApplication.DisplayAlerts=0
    $wordApplication.AutomationSecurity=3
    $wordDocument=$wordApplication.Documents.Open($wordInput,$false,$true,$false)
    $wordDocument.Repaginate()
    $wordPages=$wordDocument.ComputeStatistics(2)
    $wordDocument.ExportAsFixedFormat($wordOutput,17)
    Write-Output "PASS: installed Word opened DOCX without repair and exported $wordPages pages."
}
finally {
    if ($null -ne $wordDocument) {
        $wordDocument.Close(0)
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($wordDocument)
    }
    if ($null -ne $wordApplication) {
        $wordApplication.Quit(0)
        [void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($wordApplication)
    }
}
