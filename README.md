# ThGit

東方Projectのセーブ・リプレイをGitで同期し、起動前後に保存するPython製ランチャーです。
Linuxではゲーム本体だけWineで実行し、Windowsでは直接実行します。Python版にPowerShellは不要です。

**開発中です。初回は既存データを別途バックアップして試してください。**
現在の対象は `th06`・`th07`・`th08`・`th09`。実機のWine互換性・vpatch・音声・入力・GPU環境は
別途動作確認が必要です。ゲーム本体やパッチは付属しません。

## 構成

- Python 3.11以上: 設定、バックアップ、同期、ランチャー、ショートカット。
- ホストのGit: 履歴と認証。Wine内のGit/Pythonは使いません。
- Linux: 32-bitアプリ対応Wine、作品別の `WINEPREFIX`。
- Windows: Python + Git for Windows + pywin32（pipで自動インストール）。
- `flake.nix` / `flake.lock`: x86_64 Linux向けPython・Git・OpenSSH・Wineを固定。
- ソースのGitリポジトリ、セーブ用Gitリポジトリ、ゲーム本体、Wine prefixは別々に管理。

同期対象は各作品の `score.dat` と `replay/*.rpy` です。`*.cfg` は端末固有として扱い、
登録時の `--sync-config` 指定で同期できます。実行ファイル・ゲームの `.dat`・Wine prefixは同期しません。
設定同期の切り替えは、両端末を同期済みにしてから両方の `config.toml` を編集してください。

## Linux / Nix

Nixの `nix-command` と `flakes` を有効にしてから、ソースディレクトリで実行します。

```sh
nix run . -- doctor
nix run . -- init --remote git@github.com:YOUR_NAME/YOUR_PRIVATE_SAVES.git
nix run . -- add th06 "$HOME/Games/東方紅魔郷"
nix run . -- run th06
```

リモートは空、またはPython版のセーブ専用形式を使います。初期化時に既存リモートのHEADから
ブランチ名を取得します。ブランチを選ぶ場合は `init --branch NAME` を指定します。
ローカルのみで始める場合は `init`、その後 `sync --offline` / `run th06 --offline` を使えます。
後から `git -C <セーブリポジトリ> remote add origin URL` でリモートを追加できます。

ショートカットを作る場合は、GCで消えないようにパッケージをインストールしてください。

```sh
nix profile install .
thgit shortcut th06
```

Linuxはアプリケーションメニューに `.desktop` を作成します。エラーが見えるよう端末付きで起動します。
prefixは初回ゲーム起動時に `wineboot -u` で初期化されます。ゲームフォルダは書き込み可能な場所に置きます。
`nix develop` 自体は設定やprefixを変更しません。

flakeでGPUドライバ・画面・音声をすべて供給できるわけではありません。
NixOSでは使用するWineに応じた32-bit graphicsの設定を確認してください。
非NixOSではホストドライバとの接続（nixGL等）が必要な場合があります。
DLL override・追加ランタイム・ロケールなどの作品固有調整は今回の自動設定の対象外です。
Wineを更新する際はprefixとセーブをバックアップしてください。

## Windows（PowerShell不要）

Python 3.11以上とGit for Windowsをインストールして、コマンドプロンプトで実行します。

```bat
py -m pip install .
thgit doctor
thgit init --remote git@github.com:YOUR_NAME/YOUR_PRIVATE_SAVES.git
thgit add th06 "D:\Games\東方紅魔郷"
thgit run th06
thgit shortcut th06
```

`thgit` がPATHにない場合は `py -m thgit ...` でも実行できます。
ショートカット生成時はPythonのScriptsディレクトリをPATHに追加してください。
Windowsのショートカットはデスクトップの `.lnk` です。NixはWindowsネイティブ側には不要です。
exe単体配布はこのPRでは行わず、`pyproject.toml` からインストールします。

両OSとも、事前にGitの `user.name` / `user.email` とSSHまたはcredential helperを設定してください。
ThGit自身は認証情報を保存せず、同期中の対話認証を無効にしています。認証エラーはホストのGitで解決します。

## 通常の操作

```sh
thgit sync                  # 直接起動などで残った変更も保存・同期
thgit run th06              # 起動前同期 → ゲーム → 終了後同期
thgit run th06 --offline    # 通信なし。終了後もローカルにはコミット
thgit add th07 /path/to/game --sync-config
thgit add th08 /path/to/game --exe custom-launcher.exe
thgit doctor
```

登録時は `vpatch.exe` があれば優先し、なければ `thXX.exe` を使います。
非標準の実行ファイル名は `--exe` で指定してください。登録した実行ファイルは `config.toml` に保存されます。
Linuxは同一prefixの `wineserver -w`、WindowsはJob Objectで子プロセスを含めて終了を待ちます。
ゲームと無関係な常駐アプリは作品用prefixで動かさないでください。

全操作をセーブリポジトリ単位でロックし、ThGitからの同時プレイ・同期を防ぎます。
**同期中やThGitからのプレイ中に、別の方法でゲームを起動しないでください。**
外部からの起動はロックに従わないため、完全には防げません。

## 保存先

| 内容 | Linuxのデフォルト | Windowsのデフォルト |
|---|---|---|
| 設定 | `~/.config/thgit/config.toml` | `%LOCALAPPDATA%\thgit\config.toml` |
| セーブGit | `~/.local/share/thgit/saves/` | `%LOCALAPPDATA%\thgit\data\saves\` |
| prefix | `~/.local/share/thgit/prefixes/<作品ID>/` | 使用しません |
| バックアップ・ログ・状態 | `~/.local/state/thgit/` | `%LOCALAPPDATA%\thgit\state\` |

LinuxのXDG環境変数に対応します。共通オプション `thgit --home PATH ...` で全体の保存先を変更できます。
ローカル設定の絶対パスはGitへ送信しません。バックアップは処理ごとに作成され、自動削除しません。
容量を確認して、不要になった古いバックアップを手動で整理してください。

## 同期・競合・復旧

1. 前回配置したデータのハッシュとゲーム側の現状を比較し、変更をセーブGitに取り込みます。
2. コピー・削除の前に両方のデータをバックアップし、ネットワークに関係なくコミットします。
3. fetch後、統合可能な変更をmergeします。バイナリ競合ならmergeをabortして停止します。
4. 統合済みセーブをゲーム側へ配置し、pushします。新しい変更がなくても未送信コミットを再送します。

通信・認証・push失敗時はエラーで停止し、ローカルのコミットとゲームのデータを保持します。
ネットワークなしで続ける場合は明示的に `--offline` を指定してください。
自動 `reset --hard origin/...` やforce pushは行いません。

初回にゲーム側とセーブリポジトリ側に異なるデータがある場合、または直接起動と手動編集が競合した場合は、
両方を残して停止します。内容を確認してから、**作品単位**で採用する側を選べます。

```sh
thgit resolve-local th06 --take game
# または
thgit resolve-local th06 --take repository
thgit sync
```

リモート履歴同士の競合は、セーブリポジトリで手動解決してください。
`resolve-local` はリモートの履歴競合を解決するコマンドではありません。

```sh
git -C <セーブリポジトリ> merge origin/<ブランチ名>
# 競合した各ファイルで採用するデータを確認し、配置してから:
git -C <セーブリポジトリ> add -- <解決したファイル>
git -C <セーブリポジトリ> commit
thgit sync
```

ThGitがクラッシュ・強制終了した場合はsession markerが残り、次回の同期を止めます。
**ゲームとprefix内のプロセスがすべて終了したことを確認してから**実行します。

```sh
thgit recover --confirm-stopped
thgit sync --offline
```

これで前回終了時に回収できなかった変更も取り込めます。ログはstate配下の `thgit.log` に保存されます。

## 旧PowerShell版からの移行

旧スクリプトは `thgit.ps1` に残しています。旧説明は [legacy-powershell.md](docs/legacy-powershell.md) にあります。
旧版とPython版ではリポジトリ内の配置が異なるため、**同じリモートに混在させないでください**。

1. 旧ゲームフォルダ群と旧リポジトリをバックアップし、すべてのゲームを終了します。
2. Python版用の空リモートを作り、`thgit init --remote URL` を実行します。
3. `thgit migrate <旧ゲーム群の親フォルダ>` で対応作品を登録し、現在のセーブをローカルへコミットします。
4. `thgit sync` で送信し、新しいショートカットを作ります。
5. 他のPCもPython版へ移行し、旧PSショートカットからの同期は止めます。

`migrate` は旧Gitの履歴・設定・本体を変更せず、現在のセーブを新形式へ取り込みます。
過去の履歴は旧リポジトリに残り、新形式へは変換しません。
対象外作品や非標準のexe名は自動移行せず、対応作品なら `add --exe` を使えます。
既に登録済みの作品がある場合は停止します。設定だけ保存済みになった移行を再開する場合は `sync --offline` を使います。

## 開発・検証

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
# またはLinux:
nix develop
PYTHONPATH=src python -m unittest discover -s tests -v
nix flake check
```

CIではLinux/Windows・Python 3.11/3.13でテストし、Nixのビルドもチェックします。
テストはローカルのbare Gitリポジトリで二台間同期、競合保持、オフラインからの再送、移行を検証します。
Windows CIでは実際のJob Objectで「親が先に終了する子プロセス」の終了待ちも確認します。
ゲーム本体を使う実機テストは自動テストに含みません。

NixのlockはNixOS 26.05の固定スナップショットです。初期lockのrevision/hashは
[Nix本体のflake.lock](https://github.com/NixOS/nix/blob/master/flake.lock) のnixpkgs入力を使用しています。
更新は `nix flake update nixpkgs` 後に `nix flake check` と実機起動で確認してください。

本ツールは上海アリス幻樂団およびZUN氏とは関係のない非公式ツールです。MIT License。
