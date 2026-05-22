Start-Transcript -Path "C:\gp-setup-transcript.txt" -Force
try {
    $SqlDataDrive = "${sql_data_drive}"
    $SqlLogDrive  = "${sql_log_drive}"
    $DsnName      = "${dsn_name}"
    $SaPassword   = "${admin_password}"
    $UserName     = "${user_username}"
    $UserPassword = "${user_password}"

    # ============================================================
    # 1. Create additional RDP user
    # ============================================================
    Write-Output "Creating RDP user: $UserName"
    net user $UserName $UserPassword /add /y
    net localgroup "Remote Desktop Users" $UserName /add
    net localgroup "Administrators" $UserName /add
    Write-Output "User $UserName created and added to RDP + Administrators."

    # ============================================================
    # 2. Initialize and format attached data disks (LUN 2 & 3)
    # ============================================================
    Write-Output "Initializing data disks..."

    # Get raw (uninitialized) disks - these are the fresh empty disks we attached
    $RawDisks = Get-Disk | Where-Object { $_.PartitionStyle -eq 'RAW' } | Sort-Object Number

    if ($RawDisks.Count -ge 2) {
        # First raw disk = SQL Data (LUN 2)
        $DataDisk = $RawDisks[0]
        Write-Output "Formatting Data Disk (Disk $($DataDisk.Number)) as $($SqlDataDrive):\"
        Initialize-Disk -Number $DataDisk.Number -PartitionStyle GPT -PassThru |
            New-Partition -UseMaximumSize -DriveLetter $SqlDataDrive |
            Format-Volume -FileSystem NTFS -NewFileSystemLabel "SQLData" -AllocationUnitSize 65536 -Confirm:$false

        # Second raw disk = SQL Log (LUN 3)
        $LogDisk = $RawDisks[1]
        Write-Output "Formatting Log Disk (Disk $($LogDisk.Number)) as $($SqlLogDrive):\"
        Initialize-Disk -Number $LogDisk.Number -PartitionStyle GPT -PassThru |
            New-Partition -UseMaximumSize -DriveLetter $SqlLogDrive |
            Format-Volume -FileSystem NTFS -NewFileSystemLabel "SQLLog" -AllocationUnitSize 65536 -Confirm:$false
    } elseif ($RawDisks.Count -eq 1) {
        # Only one raw disk found - use it for data, log stays on image disk
        $DataDisk = $RawDisks[0]
        Write-Output "Formatting single raw disk as $($SqlDataDrive):\"
        Initialize-Disk -Number $DataDisk.Number -PartitionStyle GPT -PassThru |
            New-Partition -UseMaximumSize -DriveLetter $SqlDataDrive |
            Format-Volume -FileSystem NTFS -NewFileSystemLabel "SQLData" -AllocationUnitSize 65536 -Confirm:$false
    } else {
        Write-Output "WARNING: No raw disks found. Skipping disk init."
    }

    # Create SQL directories
    $DataPath = "$($SqlDataDrive):\SQLData"
    $LogPath  = "$($SqlLogDrive):\SQLLog"
    New-Item -ItemType Directory -Path $DataPath -Force | Out-Null
    New-Item -ItemType Directory -Path $LogPath -Force | Out-Null
    Write-Output "Created directories: $DataPath, $LogPath"

    # ============================================================
    # 3. Enable Mixed Mode Authentication on SQL Server
    # ============================================================
    Write-Output "Enabling SQL Server Mixed Mode Authentication..."

    # Set registry for mixed mode (LoginMode = 2)
    $SqlRegPath = "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server\MSSQL14.MSSQLSERVER\MSSQLServer"
    if (Test-Path $SqlRegPath) {
        Set-ItemProperty -Path $SqlRegPath -Name "LoginMode" -Value 2
        Write-Output "Mixed mode enabled via registry (MSSQL14)."
    } else {
        # Try other common SQL versions
        $SqlPaths = Get-ChildItem "HKLM:\SOFTWARE\Microsoft\Microsoft SQL Server" -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match "MSSQL\d+\.MSSQLSERVER" }
        foreach ($p in $SqlPaths) {
            $MSSQLServerPath = Join-Path $p.PSPath "MSSQLServer"
            if (Test-Path $MSSQLServerPath) {
                Set-ItemProperty -Path $MSSQLServerPath -Name "LoginMode" -Value 2
                Write-Output "Mixed mode enabled via registry ($($p.PSChildName))."
            }
        }
    }

    # Restart SQL Server to apply mixed mode
    Write-Output "Restarting SQL Server..."
    Restart-Service -Name "MSSQLSERVER" -Force
    Start-Sleep -Seconds 15
    Write-Output "SQL Server restarted."

    # ============================================================
    # 4. Enable SA login and set password
    # ============================================================
    Write-Output "Enabling SA login and setting password..."

    # Use sqlcmd since we're using Windows Auth at this point
    $SqlCmd = "ALTER LOGIN [sa] ENABLE; ALTER LOGIN [sa] WITH PASSWORD = N'$SaPassword';"
    sqlcmd -S localhost -Q $SqlCmd -E
    Write-Output "SA login enabled and password set."

    # ============================================================
    # 5. Configure SQL Server default data/log paths
    # ============================================================
    Write-Output "Setting SQL Server default data/log paths..."

    $SetPaths = @"
EXEC xp_instance_regwrite N'HKEY_LOCAL_MACHINE', N'Software\Microsoft\MSSQLServer\MSSQLServer', N'DefaultData', REG_SZ, N'$DataPath';
EXEC xp_instance_regwrite N'HKEY_LOCAL_MACHINE', N'Software\Microsoft\MSSQLServer\MSSQLServer', N'DefaultLog', REG_SZ, N'$LogPath';
"@
    sqlcmd -S localhost -Q $SetPaths -E
    Write-Output "SQL default paths set to Data=$DataPath, Log=$LogPath"

    # Restart SQL again to apply path changes
    Restart-Service -Name "MSSQLSERVER" -Force
    Start-Sleep -Seconds 10

    # ============================================================
    # 6. Create 32-bit ODBC DSN for Dynamics GP (localhost)
    # ============================================================
    Write-Output "Creating 32-bit System DSN: $DsnName"

    $OdbcIniPath     = "HKLM:\SOFTWARE\WOW6432Node\ODBC\ODBC.INI\$DsnName"
    $OdbcSourcesPath = "HKLM:\SOFTWARE\WOW6432Node\ODBC\ODBC.INI\ODBC Data Sources"

    if (-not (Test-Path $OdbcIniPath)) {
        New-Item -Path $OdbcIniPath -Force | Out-Null
    }

    # Point to localhost since SQL is on the same VM
    Set-ItemProperty -Path $OdbcIniPath -Name "Driver"     -Value "C:\Windows\SysWOW64\sqlncli11.dll"
    Set-ItemProperty -Path $OdbcIniPath -Name "Server"     -Value "localhost"
    Set-ItemProperty -Path $OdbcIniPath -Name "LastUser"   -Value "sa"
    Set-ItemProperty -Path $OdbcIniPath -Name "Trusted_Connection" -Value "No"

    # Dynamics GP required settings
    Set-ItemProperty -Path $OdbcIniPath -Name "AnsiNPW"        -Value "Yes"
    Set-ItemProperty -Path $OdbcIniPath -Name "QuotedId"       -Value "Yes"
    Set-ItemProperty -Path $OdbcIniPath -Name "AutoTranslate"  -Value "No"

    # Register in ODBC Data Sources
    if (-not (Test-Path $OdbcSourcesPath)) {
        New-Item -Path $OdbcSourcesPath -Force | Out-Null
    }
    Set-ItemProperty -Path $OdbcSourcesPath -Name $DsnName -Value "SQL Server Native Client 11.0"

    Write-Output "32-bit DSN '$DsnName' created pointing to localhost with SQL Auth."

    # ============================================================
    # 7. Test ODBC connection with SA credentials
    # ============================================================
    Write-Output "Testing ODBC connection to localhost..."
    $ConnectionString = "Driver={SQL Server Native Client 11.0};Server=localhost;Database=master;Uid=sa;Pwd=$SaPassword;"
    $Conn = New-Object System.Data.Odbc.OdbcConnection($ConnectionString)
    $Conn.Open()
    Write-Output "ODBC Connection successful (SQL Auth)."
    $Conn.Close()

    Write-Output "=== Post-deploy setup complete ==="

} catch {
    Write-Output "ERROR: $($_.Exception.Message)"
    $_.Exception.Message | Out-File "C:\gp-setup-err.txt"
    Stop-Transcript
    exit 1
}
Stop-Transcript
