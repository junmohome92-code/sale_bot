@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title sale_bot - sale test win

:menu
cls
echo ========================================
echo        sale_bot - sale test win
echo ========================================
echo.
echo   1. 최초 설치
echo   2. 코드 테스트
echo   3. 중고마켓 실제 검색 1회
echo   4. 계속 실행
echo   5. 검색 설정 열기 ^(config.yaml^)
echo   6. 텔레그램/디스코드 설정 열기 ^(.env^)
echo   0. 종료
echo.
set /p choice=번호를 선택하세요: 

if "%choice%"=="1" goto setup
if "%choice%"=="2" goto test
if "%choice%"=="3" goto once
if "%choice%"=="4" goto run
if "%choice%"=="5" goto config
if "%choice%"=="6" goto env
if "%choice%"=="0" exit /b 0
goto menu

:setup
call powershell -NoProfile -ExecutionPolicy Bypass -File ".\win.ps1" setup
goto done

:test
call powershell -NoProfile -ExecutionPolicy Bypass -File ".\win.ps1" test
goto done

:once
call powershell -NoProfile -ExecutionPolicy Bypass -File ".\win.ps1" once
goto done

:run
call powershell -NoProfile -ExecutionPolicy Bypass -File ".\win.ps1" run
goto done

:config
if not exist "config.yaml" copy /Y "config.example.yaml" "config.yaml" >nul
start "" notepad "config.yaml"
goto menu

:env
if not exist ".env" copy /Y ".env.example" ".env" >nul
start "" notepad ".env"
goto menu

:done
echo.
echo ========================================
echo 작업이 끝났습니다. 아무 키나 누르면 메뉴로 돌아갑니다.
echo ========================================
pause >nul
goto menu
