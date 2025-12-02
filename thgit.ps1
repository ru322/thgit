# SPDX-License-Identifier: MIT
# Copyright (c) 2025 ru322
<#
.SYNOPSIS
    東方Project データ同期・管理ツール (thgit)
.DESCRIPTION
    Git/GitHubを利用して東方Projectのセーブデータ、リプレイ、設定ファイルを
    複数PC間で同期・管理するためのPowerShellスクリプト
    
    配置場所: ゲームフォルダ群の親フォルダ
    構成:
    - thgit.ps1          : このスクリプト
    - .git/              : Gitリポジトリ
    - .gitignore         : 同期対象ファイルの管理
    - .gitattributes     : バイナリファイル設定
    - .thgit-setup       : セットアップ完了マーカー
    - 東方紅魔郷/        : ゲームフォルダ（ユーザーデータを直接管理）
    - 東方永夜抄/        : ゲームフォルダ
#>

param(
    [string]$GamePath
)

# スクリプトのディレクトリを取得（リポジトリルート）
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$MarkerPath = Join-Path $ScriptDir ".thgit-setup"

# --- ユーティリティ関数 ---

# ログファイルパス
$LogFilePath = Join-Path $ScriptDir "thgit.log"

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] $Message"
    Write-Host "[thgit] $Message"
    
    # ファイルにも記録
    try {
        Add-Content -Path $LogFilePath -Value $logMessage -Encoding UTF8
    } catch {
        # ログ書き込み失敗は無視
    }
}

function Test-Online {
    try {
        $result = Test-Connection -ComputerName "github.com" -Count 1 -Quiet -ErrorAction SilentlyContinue
        return $result
    } catch {
        return $false
    }
}

function Test-GitInstalled {
    try {
        $null = Get-Command git -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

function Install-Git {
    Write-Log "Gitがインストールされていません。wingetでインストールします..."
    try {
        winget install --id Git.Git -e --source winget
        Write-Log "Gitのインストールが完了しました。"
        Write-Log "環境変数を反映するため、このスクリプトを再実行してください。"
        Read-Host "Enterキーを押して終了"
        exit 0
    } catch {
        Write-Log "Gitのインストールに失敗しました: $_"
        Read-Host "Enterキーを押して終了"
        exit 1
    }
}

function Find-GameFolders {
    # サブフォルダからthxx.exeを探す
    $gameFolders = @()
    
    Get-ChildItem -Path $ScriptDir -Directory | ForEach-Object {
        $folder = $_
        $thExes = Get-ChildItem -Path $folder.FullName -Filter "th*.exe" -ErrorAction SilentlyContinue | 
                  Where-Object { $_.Name -match "^th[0-9]+\.exe$" }
        
        if ($thExes) {
            $targetExe = $thExes[0].FullName
            
            # vpatch.exeがあれば優先
            $vpatch = Join-Path $folder.FullName "vpatch.exe"
            if (Test-Path $vpatch) {
                $targetExe = $vpatch
            }
            
            $gameFolders += @{
                Path = $folder.FullName
                Name = $folder.Name
                GameId = $thExes[0].BaseName
                TargetExe = $targetExe
            }
        }
    }
    
    return $gameFolders
}

function Get-TargetExe {
    param([string]$FolderPath)
    
    # vpatch.exe を優先
    $vpatch = Join-Path $FolderPath "vpatch.exe"
    if (Test-Path $vpatch) {
        return $vpatch
    }
    
    # thxx.exe を探す
    $thExes = Get-ChildItem -Path $FolderPath -Filter "th*.exe" -ErrorAction SilentlyContinue | 
              Where-Object { $_.Name -match "^th[0-9]+\.exe$" }
    if ($thExes) {
        return $thExes[0].FullName
    }
    
    return $null
}

function New-Shortcut {
    param(
        [string]$ShortcutPath,
        [string]$TargetPath,
        [string]$Arguments,
        [string]$WorkingDirectory,
        [string]$IconLocation
    )
    
    try {
        $WshShell = New-Object -ComObject WScript.Shell
        $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
        $Shortcut.TargetPath = $TargetPath
        $Shortcut.Arguments = $Arguments
        $Shortcut.WorkingDirectory = $WorkingDirectory
        if ($IconLocation) {
            $Shortcut.IconLocation = "$IconLocation,0"
        }
        $Shortcut.Save()
    } catch {
        Write-Log "ショートカット作成エラー: $_"
    }
}

function New-Backup {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $backupDir = Join-Path $ScriptDir "_backup_$timestamp"
    
    Write-Log "バックアップを作成中: $backupDir"
    
    # ゲームフォルダのユーザーデータをバックアップ
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    
    $gameFolders = Find-GameFolders
    foreach ($game in $gameFolders) {
        $gameBackupDir = Join-Path $backupDir $game.Name
        New-Item -ItemType Directory -Path $gameBackupDir -Force | Out-Null
        
        # score.dat, replay/, *.cfg をコピー
        $scoreDat = Join-Path $game.Path "score.dat"
        if (Test-Path $scoreDat) {
            Copy-Item -Path $scoreDat -Destination $gameBackupDir -Force
        }
        
        $replayDir = Join-Path $game.Path "replay"
        if (Test-Path $replayDir) {
            Copy-Item -Path $replayDir -Destination $gameBackupDir -Recurse -Force
        }
        
        Get-ChildItem -Path $game.Path -Filter "*.cfg" -ErrorAction SilentlyContinue | ForEach-Object {
            Copy-Item -Path $_.FullName -Destination $gameBackupDir -Force
        }
    }
    
    Write-Log "バックアップ完了"
}

function Initialize-GitIgnore {
    $gitignorePath = Join-Path $ScriptDir ".gitignore"
    
    if (-not (Test-Path $gitignorePath)) {
        $content = @"
# 全てを無視
*

# ユーザーデータのみを追跡
!.gitignore
!.gitattributes

# thgit.log は除外
thgit.log

!*/
!*/score.dat
!*/replay/
!*/replay/**
!*/*.cfg
"@
        $content | Out-File -FilePath $gitignorePath -Encoding UTF8
        Write-Log ".gitignoreを作成しました"
    }
}

function Initialize-GitAttributes {
    $gitattributesPath = Join-Path $ScriptDir ".gitattributes"
    
    if (-not (Test-Path $gitattributesPath)) {
        $content = @"
# 全てのファイルをバイナリとして扱う
* binary
"@
        $content | Out-File -FilePath $gitattributesPath -Encoding UTF8
        Write-Log ".gitattributesを作成しました"
    }
}

# --- セットアップフェーズ ---

function Invoke-Setup {
    Write-Log "=== 初回セットアップを開始します ==="
    
    # 1. Git確認・インストール
    if (-not (Test-GitInstalled)) {
        Install-Git
    }
    Write-Log "Git: OK"
    
    # 2. Gitリポジトリの初期化
    $gitDir = Join-Path $ScriptDir ".git"
    if (-not (Test-Path $gitDir)) {
        Write-Log "Gitリポジトリを初期化中..."
        Push-Location $ScriptDir
        try {
            git init
            
            # リモートリポジトリ登録
            $remoteUrl = Read-Host "リモートリポジトリのURLを入力してください"
            if ($remoteUrl) {
                git remote add origin $remoteUrl
                Write-Log "リモートリポジトリを登録しました: $remoteUrl"
            }
        } finally {
            Pop-Location
        }
    } else {
        Write-Log "既存のGitリポジトリを使用します"
    }
    
    # 3. .gitignore / .gitattributes の作成
    Initialize-GitIgnore
    Initialize-GitAttributes
    
    # 4. 初回同期（Pull）
    if (Test-Online) {
        Write-Log "リモートからデータを取得中..."
        Push-Location $ScriptDir
        try {
            $pullResult = git pull origin master 2>&1
            $pullExitCode = $LASTEXITCODE
            
            if ($pullExitCode -ne 0) {
                # コンフリクト検出
                $status = git status --porcelain 2>$null
                if ($status -match "^UU|^AA|^DD") {
                    Write-Log "競合が発生しました。"
                    Write-Log "リモート優先: サーバーのデータで上書き"
                    Write-Log "ローカル優先: 現在のデータを維持"
                    $choice = Read-Host "どちらを優先しますか？ (R: リモート / L: ローカル) [R]"
                    
                    if ($choice -eq "L" -or $choice -eq "l") {
                        # ローカル優先
                        git checkout --ours .
                        git add .
                        git commit -m "Resolve conflict: keep local"
                        Write-Log "ローカルのデータを維持しました"
                    } else {
                        # リモート優先（デフォルト）
                        New-Backup
                        git fetch origin
                        git reset --hard origin/master
                        Write-Log "リモートのデータで上書きしました"
                    }
                }
            } else {
                Write-Log "同期完了"
            }
        } finally {
            Pop-Location
        }
    } else {
        Write-Log "オフラインのため、同期をスキップします"
    }
    
    # 5. ゲームフォルダの探索とショートカット作成
    $gameFolders = Find-GameFolders
    
    if ($gameFolders.Count -eq 0) {
        Write-Log "警告: ゲームフォルダが見つかりませんでした"
        Write-Log "thxx.exe を含むフォルダを配置してから再実行してください"
    } else {
        Write-Log "検出したゲーム: $($gameFolders.Count) 個"
        
        $desktopPath = [Environment]::GetFolderPath("Desktop")
        $scriptPath = Join-Path $ScriptDir "thgit.ps1"
        
        foreach ($game in $gameFolders) {
            Write-Log "  - $($game.Name) ($($game.GameId))"
            
            # ショートカット作成
            $shortcutName = "$($game.Name).lnk"
            $arguments = "-ExecutionPolicy Bypass -File `"$scriptPath`" -GamePath `"$($game.Path)`""
            
            $desktopShortcut = Join-Path $desktopPath $shortcutName
            New-Shortcut -ShortcutPath $desktopShortcut -TargetPath "powershell.exe" -Arguments $arguments -WorkingDirectory $ScriptDir -IconLocation $game.TargetExe
        }
        
        Write-Log "デスクトップにショートカットを作成しました"
    }
    
    # 6. セットアップ完了マーカー作成
    "setup-complete" | Out-File -FilePath $MarkerPath -Encoding UTF8
    
    Write-Log "=== セットアップ完了 ==="
    Write-Log "デスクトップのショートカットからゲームを起動してください"
    Read-Host "Enterキーを押して終了"
}

# --- ランチャーフェーズ ---

function Invoke-PreSync {
    # オンライン判定
    if (-not (Test-Online)) {
        Write-Log "オフラインモードで起動します"
        return $true
    }
    
    Write-Log "同期中..."
    Push-Location $ScriptDir
    try {
        # Pull実行
        $pullResult = git pull origin master 2>&1
        $pullExitCode = $LASTEXITCODE
        
        if ($pullExitCode -eq 0) {
            Write-Log "同期完了"
            return $true
        }
        
        # コンフリクト検出
        $status = git status --porcelain
        if ($status -match "^UU|^AA|^DD") {
            Write-Log "競合が発生しました。リモート優先で解決します..."
            
            # バックアップ作成
            New-Backup
            
            # リモートに強制同期
            git fetch origin
            git reset --hard origin/master
            Write-Log "リモートのデータで上書きしました"
            return $true
        }
        
        # その他のエラー
        Write-Log "Pull中にエラーが発生しました: $pullResult"
        return $true
        
    } finally {
        Pop-Location
    }
}

function Invoke-Game {
    param([string]$FolderPath)
    
    $targetExe = Get-TargetExe -FolderPath $FolderPath
    if (-not $targetExe) {
        Write-Log "エラー: ゲーム実行ファイルが見つかりません"
        return
    }
    
    Write-Log "ゲームを起動します: $(Split-Path -Leaf $targetExe)"
    Start-Process -FilePath $targetExe -WorkingDirectory $FolderPath -Wait
    Write-Log "ゲームが終了しました"
    
    # ファイル書き込み完了を待機
    Write-Log "データ保存を待機中..."
    Start-Sleep -Seconds 2
}

function Invoke-PostSync {
    Push-Location $ScriptDir
    try {
        # 変更検知
        $status = git status --porcelain
        if (-not $status) {
            Write-Log "変更はありません"
            return
        }
        
        Write-Log "変更を検出しました"
        
        # オンライン判定
        if (-not (Test-Online)) {
            Write-Log "オフラインのため、次回起動時に同期します"
            return
        }
        
        # Commit（リトライ付き）
        $timestamp = Get-Date -Format "yyyy/MM/dd HH:mm:ss"
        $commitMessage = "AutoSave: $timestamp @ $env:COMPUTERNAME"
        
        $maxRetries = 3
        $retryCount = 0
        $addSuccess = $false
        
        while (-not $addSuccess -and $retryCount -lt $maxRetries) {
            $retryCount++
            
            # git add 実行
            $addResult = git add -A 2>&1
            $addExitCode = $LASTEXITCODE
            
            if ($addExitCode -eq 0) {
                $addSuccess = $true
            } else {
                Write-Log "git add 失敗 (試行 $retryCount/$maxRetries): $addResult"
                if ($retryCount -lt $maxRetries) {
                    Write-Log "リトライまで待機中..."
                    Start-Sleep -Seconds 2
                }
            }
        }
        
        if (-not $addSuccess) {
            Write-Log "エラー: ファイルのステージングに失敗しました"
            Write-Log "ファイルがロックされている可能性があります。次回起動時に再試行します。"
            return
        }
        
        # ステージされた変更があるか確認
        $stagedStatus = git diff --cached --name-only
        if (-not $stagedStatus) {
            Write-Log "ステージされた変更がありません"
            return
        }
        
        git commit -m $commitMessage
        Write-Log "コミット完了: $commitMessage"
        
        # Push
        Write-Log "アップロード中..."
        $pushResult = git push origin master 2>&1
        $pushExitCode = $LASTEXITCODE
        
        if ($pushExitCode -eq 0) {
            Write-Log "アップロード完了"
        } else {
            Write-Log "エラー: プッシュに失敗しました"
            Write-Log "$pushResult"
            Write-Log "手動で 'git push origin master' を実行してください"
        }
        
    } finally {
        Pop-Location
    }
}

function Invoke-Launcher {
    param([string]$FolderPath)
    
    $folderName = Split-Path -Leaf $FolderPath
    Write-Log "=== thgit ランチャー: $folderName ==="
    
    # 起動前同期
    $syncOk = Invoke-PreSync
    if (-not $syncOk) {
        Write-Log "同期に失敗しました"
    }
    
    # ゲーム起動
    Invoke-Game -FolderPath $FolderPath
    
    # 終了後同期
    Invoke-PostSync
    
    Write-Log "=== 終了 ==="
}

# --- メイン処理 ---

if (Test-Path $MarkerPath) {
    # 通常ランチャーモード
    if ($GamePath) {
        if (Test-Path $GamePath) {
            Invoke-Launcher -FolderPath $GamePath
        } else {
            Write-Log "エラー: 指定されたゲームフォルダが見つかりません: $GamePath"
            Read-Host "Enterキーを押して終了"
        }
    } else {
        Write-Log "エラー: ゲームフォルダが指定されていません"
        Write-Log "ショートカットから起動するか、-GamePath パラメータを指定してください"
        Read-Host "Enterキーを押して終了"
    }
} else {
    # 初回セットアップモード
    Invoke-Setup
}
