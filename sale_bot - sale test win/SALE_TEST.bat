@echo off
setlocal
cd /d "%~dp0"
title sale_bot - sale test win

:menu
cls
echo ========================================
echo   sale_bot - sale test win
 echo ========================================
echo.
echo   1. First setup
 echo   2. Run code tests
 echo   3. Run one marketplace scan
 echo   4. Run continuously
 echo   5. Open config.yaml
 echo   6. Open .env
 echo   0. Exit
 echo.
set /p choice=Select: 

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
echo Finished. Press any key to return to menu.
echo ========================================
pause >nul
goto menu
