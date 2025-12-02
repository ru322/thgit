@echo off
REM thgit - 東方Project データ同期ツール ランチャー
REM このバッチファイルをダブルクリックして実行してください

powershell -ExecutionPolicy Bypass -NoExit -File "%~dp0thgit.ps1"
