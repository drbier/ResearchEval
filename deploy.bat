@echo off
setlocal

echo ========================================================
echo               F.A.S.T. Server Deployment
echo ========================================================
echo Target: myown-deploy (72.15.24.46:58221)
echo.

set SERVER=myown-deploy
set "REMOTE_COMMAND=cd /var/www/fast && git checkout -f && git pull && venv/bin/pip install -r requirements.txt && sudo -u www-data pm2 restart fast --update-env"

echo Executing remote deployment commands...
echo (If prompted, please enter your server SSH/sudo password)
echo.

ssh -t %SERVER% "%REMOTE_COMMAND%"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================================
    echo  SUCCESS: F.A.S.T. successfully updated and restarted!
    echo ========================================================
) else (
    echo.
    echo ========================================================
    echo  ERROR: Deployment encountered an issue (Exit Code: %ERRORLEVEL%)
    echo ========================================================
)

echo.
pause

