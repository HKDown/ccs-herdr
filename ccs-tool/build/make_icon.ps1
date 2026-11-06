Add-Type -AssemblyName System.Drawing
$size = 256
$bmp = New-Object System.Drawing.Bitmap($size, $size)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
$bg = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(18, 20, 28))
$g.FillRectangle($bg, 0, 0, $size, $size)
$accent = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(64, 224, 120))
$pen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(64, 224, 120), 10)
$g.DrawRectangle($pen, 14, 14, 228, 228)
$font = New-Object System.Drawing.Font('Consolas', 86, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
$fmt = New-Object System.Drawing.StringFormat
$fmt.Alignment = [System.Drawing.StringAlignment]::Center
$fmt.LineAlignment = [System.Drawing.StringAlignment]::Center
$g.DrawString('ccs', $font, $accent, (New-Object System.Drawing.RectangleF(0, 0, $size, $size)), $fmt)
$g.Dispose()
$bmp.Save('build\icon.png', [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
$png = [System.IO.File]::ReadAllBytes('build\icon.png')
$ms = New-Object System.IO.MemoryStream
$bw = New-Object System.IO.BinaryWriter($ms)
$bw.Write([uint16]0); $bw.Write([uint16]1); $bw.Write([uint16]1)
$bw.Write([byte]0); $bw.Write([byte]0); $bw.Write([byte]0); $bw.Write([byte]0)
$bw.Write([uint16]1); $bw.Write([uint16]32)
$bw.Write([uint32]$png.Length); $bw.Write([uint32]22)
$bw.Write($png)
$bw.Flush()
[System.IO.File]::WriteAllBytes('build\ccs.ico', $ms.ToArray())
Get-Item build\ccs.ico | Select-Object Name, Length | Out-String
