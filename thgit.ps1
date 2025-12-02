<#
.SYNOPSIS
    東方Project データ同期・管理ツール (thgit)
.DESCRIPTION
    Git/GitHubを利用して東方Projectのセーブデータ、リプレイ、設定ファイルを
    複数PC間で同期・管理するためのPowerShellスクリプト
    
    構成:
    - 共有リポジトリ: 親フォルダの .thgit に作成
    - 実データ: .thgit/thxx/ に保存
    - ゲームフォルダ: ハードリンク(ファイル)/ジャンクション(フォルダ)で接続
    - リモート: /th06/, /th07/, /th08/ の構成
#>

# スクリプトのディレクトリを取得
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ParentDir = Split-Path -Parent $ScriptDir
$RepoPath = Join-Path $ParentDir ".thgit"

# --- ユーティリティ関数 ---

function Write-Log {
    param([string]$Message)
    Write-Host "[thgit] $Message"
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

function Get-TargetExe {
    # vpatch.exe を優先
    $vpatch = Join-Path $ScriptDir "vpatch.exe"
    if (Test-Path $vpatch) {
        return $vpatch
    }
    
    # thxx.exe を探す
    $thExes = Get-ChildItem -Path $ScriptDir -Filter "th*.exe" | Where-Object { $_.Name -match "^th[0-9]+\.exe$" }
    if ($thExes) {
        return $thExes[0].FullName
    }
    
    return $null
}

function Get-GameId {
    $thExes = Get-ChildItem -Path $ScriptDir -Filter "th*.exe" | Where-Object { $_.Name -match "^th0[678]\.exe$" }
    if ($thExes) {
        return $thExes[0].BaseName
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
    
    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $TargetPath
    $Shortcut.Arguments = $Arguments
    $Shortcut.WorkingDirectory = $WorkingDirectory
    if ($IconLocation) {
        $Shortcut.IconLocation = $IconLocation
    }
    $Shortcut.Save()
}

function New-Backup {
    param([string]$GameId)
    
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $backupDir = Join-Path $ScriptDir "_backup_$timestamp"
    $gameDataDir = Join-Path $RepoPath $GameId
    
    Write-Log "バックアップを作成中: $backupDir"
    
    if (Test-Path $gameDataDir) {
        Copy-Item -Path $gameDataDir -Destination $backupDir -Recurse -Force
    }
    Write-Log "バックアップ完了"
}

function Get-SyncConfig {
    param([string]$GameId)
    
    # 1. ローカルのsync.jsonを確認（優先）
    $localSyncJson = Join-Path $ScriptDir "sync.json"
    Write-Log "sync.jsonを検索中: $localSyncJson"
    
    if (Test-Path $localSyncJson) {
        Write-Log "ローカルのsync.jsonを検出しました"
        try {
            $config = Get-Content $localSyncJson -Raw | ConvertFrom-Json
            Write-Log "sync.json読み込み成功"
            return $config
        } catch {
            Write-Log "警告: ローカルsync.jsonの解析に失敗しました: $_"
        }
    } else {
        Write-Log "ローカルにsync.jsonが見つかりません"
    }
    
    # 2. リモートからダウンロード
    $syncJsonUrl = "https://raw.githubusercontent.com/ru322/thgit/main/$GameId/sync.json"
    Write-Log "リモートからsync.jsonを取得中: $syncJsonUrl"
    
    try {
        $response = Invoke-WebRequest -Uri $syncJsonUrl -UseBasicParsing -TimeoutSec 10
        $syncConfig = $response.Content | ConvertFrom-Json
        
        # ダウンロードしたsync.jsonをローカルに保存
        $response.Content | Out-File -FilePath $localSyncJson -Encoding UTF8
        Write-Log "sync.jsonをダウンロードしてローカルに保存しました"
        
        return $syncConfig
    } catch {
        Write-Log "エラー: sync.jsonの取得に失敗しました"
        Write-Log "詳細: $_"
        Write-Log ""
        Write-Log "sync.jsonをゲームフォルダに手動で配置してください"
        Write-Log "形式例:"
        Write-Log '  {"sync-items": ["/replay", "score.dat", "th08.cfg"]}'
        Read-Host "Enterキーを押して終了"
        exit 1
    }
}

function Get-GitignoreContent {
    param([string]$GameId)
    
    $gitignoreUrl = "https://raw.githubusercontent.com/ru322/thgit/main/$GameId/dot_gitignore"
    
    try {
        $response = Invoke-WebRequest -Uri $gitignoreUrl -UseBasicParsing
        return $response.Content
    } catch {
        # デフォルトの.gitignore
        return @"
# Default .gitignore
*
!*/
!*.rpy
!*.bak
!score.dat
!*.cfg
"@
    }
}

function New-LinkItem {
    param(
        [string]$LinkPath,
        [string]$TargetPath,
        [bool]$IsDirectory
    )
    
    if ($IsDirectory) {
        # フォルダ: ジャンクション（管理者権限不要）
        cmd /c mklink /J "$LinkPath" "$TargetPath" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Log "エラー: ジャンクションの作成に失敗しました: $LinkPath"
            return $false
        }
    } else {
        # ファイル: ハードリンク（管理者権限不要、同一ドライブ必須）
        cmd /c mklink /H "$LinkPath" "$TargetPath" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Write-Log "エラー: ハードリンクの作成に失敗しました: $LinkPath"
            Write-Log "※ハードリンクは同一ドライブ内でのみ作成可能です"
            return $false
        }
    }
    return $true
}

# --- セットアップフェーズ ---

function Invoke-Setup {
    Write-Log "=== 初回セットアップを開始します ==="
    
    # Git確認・インストール
    if (-not (Test-GitInstalled)) {
        Install-Git
    }
    
    # 作品ID特定
    $gameId = Get-GameId
    if (-not $gameId) {
        Write-Log "エラー: 対象のゲーム実行ファイルが見つかりません"
        Read-Host "Enterキーを押して終了"
        exit 1
    }
    Write-Log "検出した作品: $gameId"
    
    # sync.json取得
    $syncConfig = Get-SyncConfig -GameId $gameId
    $syncItems = $syncConfig.'sync-items'
    Write-Log "同期対象: $($syncItems -join ', ')"
    
    # 共有リポジトリの確認・作成
    $isFirstSetup = -not (Test-Path $RepoPath)
    
    if ($isFirstSetup) {
        Write-Log "共有リポジトリを作成中: $RepoPath"
        New-Item -ItemType Directory -Path $RepoPath -Force | Out-Null
        Push-Location $RepoPath
        try {
            git init
            
            # リモートリポジトリ登録
            $remoteUrl = Read-Host "リモートリポジトリのURLを入力してください"
            if ($remoteUrl) {
                git remote add origin $remoteUrl
                Write-Log "リモートリポジトリを登録しました: $remoteUrl"
                
                # リモートからpull試行
                if (Test-Online) {
                    Write-Log "リモートからデータを取得中..."
                    git pull origin master 2>$null
                }
            }
        } finally {
            Pop-Location
        }
    } else {
        Write-Log "既存の共有リポジトリを使用します: $RepoPath"
        # 既存リポジトリからpull
        if (Test-Online) {
            Push-Location $RepoPath
            try {
                Write-Log "リモートからデータを取得中..."
                git pull origin master 2>$null
            } finally {
                Pop-Location
            }
        }
    }
    
    # 作品データフォルダの準備
    $gameDataDir = Join-Path $RepoPath $gameId
    if (-not (Test-Path $gameDataDir)) {
        New-Item -ItemType Directory -Path $gameDataDir -Force | Out-Null
    }
    
    # .gitignore取得・配置
    $gitignorePath = Join-Path $gameDataDir ".gitignore"
    if (-not (Test-Path $gitignorePath)) {
        $gitignoreContent = Get-GitignoreContent -GameId $gameId
        $gitignoreContent | Out-File -FilePath $gitignorePath -Encoding UTF8
        Write-Log ".gitignoreを配置しました"
    }
    
    # 同期アイテムのリンク作成
    Write-Log "リンクを作成中..."
    foreach ($item in $syncItems) {
        $isDirectory = $item.StartsWith("/")
        $itemName = $item.TmasterrimStart("/")
        
        $sourcePath = Join-Path $ScriptDir $itemName
        $targetPath = Join-Path $gameDataDir $itemName
        
        # 既にリンクの場合はスキップ
        if (Test-Path $sourcePath) {
            $itemInfo = Get-Item $sourcePath -Force
            if ($itemInfo.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                Write-Log "スキップ (既にリンク): $itemName"
                continue
            }
        }
        
        if ($isDirectory) {
            # フォルダの処理
            if (Test-Path $sourcePath) {
                # 既存フォルダを移動
                Write-Log "既存フォルダを移動: $itemName"
                if (Test-Path $targetPath) {
                    # ターゲットにも存在する場合はマージ
                    Get-ChildItem -Path $sourcePath | ForEach-Object {
                        Move-Item -Path $_.FullName -Destination $targetPath -Force
                    }
                    Remove-Item -Path $sourcePath -Force
                } else {
                    Move-Item -Path $sourcePath -Destination $targetPath -Force
                }
            } else {
                # ターゲットフォルダがなければ作成
                if (-not (Test-Path $targetPath)) {
                    New-Item -ItemType Directory -Path $targetPath -Force | Out-Null
                }
            }
            
            # ジャンクション作成
            $result = New-LinkItem -LinkPath $sourcePath -TargetPath $targetPath -IsDirectory $true
            if ($result) {
                Write-Log "ジャンクション作成: $itemName"
            }
        } else {
            # ファイルの処理
            if (Test-Path $sourcePath) {
                # 既存ファイルを移動
                Write-Log "既存ファイルを移動: $itemName"
                Move-Item -Path $sourcePath -Destination $targetPath -Force
            } elseif (-not (Test-Path $targetPath)) {
                # ターゲットファイルがなければ空ファイル作成（ゲーム起動時に作成されるため、リンクだけ作っておく）
                # ただしハードリンクは存在するファイルが必要なのでスキップ
                Write-Log "スキップ (ファイル未存在): $itemName"
                continue
            }
            
            # ハードリンク作成
            $result = New-LinkItem -LinkPath $sourcePath -TargetPath $targetPath -IsDirectory $false
            if ($result) {
                Write-Log "ハードリンク作成: $itemName"
            }
        }
    }
    
    # セットアップ完了マーカー作成
    $markerPath = Join-Path $ScriptDir ".thgit-setup"
    $gameId | Out-File -FilePath $markerPath -Encoding UTF8
    
    # ショートカット作成
    $targetExe = Get-TargetExe
    $shortcutName = "$gameId-thgit.lnk"
    $scriptPath = Join-Path $ScriptDir "thgit.ps1"
    $arguments = "-ExecutionPolicy Bypass -NoExit -File `"$scriptPath`""
    
    # デスクトップ
    $desktopPath = [Environment]::GetFolderPath("Desktop")
    $desktopShortcut = Join-Path $desktopPath $shortcutName
    New-Shortcut -ShortcutPath $desktopShortcut -TargetPath "powershell.exe" -Arguments $arguments -WorkingDirectory $ScriptDir -IconLocation $targetExe
    Write-Log "デスクトップにショートカットを作成しました"
    
    # スタートメニュー
    $startMenuPath = [Environment]::GetFolderPath("StartMenu")
    $startMenuShortcut = Join-Path $startMenuPath $shortcutName
    New-Shortcut -ShortcutPath $startMenuShortcut -TargetPath "powershell.exe" -Arguments $arguments -WorkingDirectory $ScriptDir -IconLocation $targetExe
    Write-Log "スタートメニューにショートカットを作成しました"
    
    Write-Log "=== セットアップ完了 ==="
    Write-Log "次回からはショートカットからゲームを起動してください"
    Read-Host "Enterキーを押して終了"
}

# --- ランチャーフェーズ ---

function Invoke-PreSync {
    $gameId = Get-GameId
    
    # オンライン判定
    if (-not (Test-Online)) {
        Write-Log "オフラインモードで起動します"
        return $true
    }
    
    Write-Log "同期中..."
    Push-Location $RepoPath
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
            Write-Log "競合が発生しました。"
            $choice = Read-Host "サーバー上のデータを正として上書きしますか？ (Y/N)"
            
            if ($choice -eq "Y" -or $choice -eq "y") {
                # バックアップ作成
                New-Backup -GameId $gameId
                
                # リモートに強制同期
                git fetch origin
                git reset --hard origin/master
                Write-Log "リモートのデータで上書きしました"
                return $true
            } else {
                Write-Log "警告: 同期をスキップしました。プレイ後のPush時に再度競合する可能性があります。"
                git merge --abort 2>$null
                return $true
            }
        }
        
        # その他のエラー
        Write-Log "Pull中にエラーが発生しました: $pullResult"
        return $true
        
    } finally {
        Pop-Location
    }
}

function Invoke-Game {
    $targetExe = Get-TargetExe
    if (-not $targetExe) {
        Write-Log "エラー: ゲーム実行ファイルが見つかりません"
        return
    }
    
    Write-Log "ゲームを起動します: $(Split-Path -Leaf $targetExe)"
    Start-Process -FilePath $targetExe -WorkingDirectory $ScriptDir -Wait
    Write-Log "ゲームが終了しました"
    
    # ファイル書き込み完了を待機
    Write-Log "データ保存を待機中..."
    Start-Sleep -Seconds 2
}

function Invoke-PostSync {
    Push-Location $RepoPath
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
            Write-Log "エラー: プッシュに失敗しました: $pushResult"
        }
        
    } finally {
        Pop-Location
    }
}

function Invoke-Launcher {
    Write-Log "=== thgit ランチャー ==="
    
    # 起動前同期
    $syncOk = Invoke-PreSync
    if (-not $syncOk) {
        Write-Log "同期に失敗しました"
    }
    
    # ゲーム起動
    Invoke-Game
    
    # 終了後同期
    Invoke-PostSync
    
    Write-Log "=== 終了 ==="
}

# --- メイン処理 ---

# セットアップ完了マーカーの確認
$markerPath = Join-Path $ScriptDir ".thgit-setup"

if (Test-Path $markerPath) {
    # 通常ランチャーモード
    Invoke-Launcher
} else {
    # 初回セットアップモード
    Invoke-Setup
}
