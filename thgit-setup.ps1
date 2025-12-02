<#
 .SYNOPSIS
 Touhou Data Sync Script With Git
 .DESCRIPTION
 東方Project(紅魔郷, 妖々夢, 永夜抄)のプレイデータをGitで管理します。
#>

# ユーザー設定領域: リモートリポジトリがある場合はここに入力してください
$remoteUrl = "" 

# Gitの存在確認とインストール
try {
    Get-Command git -ErrorAction Stop | Out-Null
} catch {
    Write-Host "Gitがインストールされていません。Winget経由でインストールします"
    winget install --id Git.Git -e --source winget
    
    # 再起動
    Write-Warning "Gitのインストールが完了しました。再び立ち上げてください。"
    exit
}

# リポジトリの初期化確認
if (-not (Test-Path ".git")) {
    Write-Host "リポジトリを初期化します"
    git init
    git branch -M main
    
    if ($remoteUrl -ne "") {
        git remote add origin $remoteUrl
        Write-Host "リモートURLが登録されました"
    } else {
        Write-Warning "リモートURLが登録されていません。バージョン管理はこのPCでのみ完結し、共有することができません"
    }
}

# 特定ファイル/フォルダのステージング
# ターゲットリスト
$targets = @("replay", "backup", "score.dat", "th08.cfg")

foreach ($item in $targets) {
    if (Test-Path $item) {
        git add $item
        Write-Host "Staged: $item"
    } else {
        # 警告にとどめる
        Write-Warning "次のアイテムが見つかりません: $item. スキップします"
    }
}

# 4. コミットおよびプッシュ
# 変更がある場合のみコミットを行う判定
$status = git status --porcelain
if ($status) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    git commit -m "Sync: $timestamp"
    
    
    $remotes = git remote
    if ($remotes) {
        Write-Host "プッシュしています"
        git push -u origin main
    } else {
        Write-Warning "リモートリポジトリが登録されていません。スキップします"
    }
} else {
    Write-Host "変更はありませんでした。"
}