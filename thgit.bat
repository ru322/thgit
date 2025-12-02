@echo off
chcp 65001 >nul
REM thgit - 東方Project データ同期ツール ランチャー
REM このバッチファイルをダブルクリックして実行してください

powershell -ExecutionPolicy Bypass -NoExit -Command "& {$OutputEncoding = [Console]::OutputEncoding = [Text.Encoding]::UTF8; . '%~dp0thgit.ps1'}"
