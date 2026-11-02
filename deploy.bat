@echo off
setlocal

echo ========================================================
echo         F.A.S.T. v2.0 Production Server Deployment
echo ========================================================
echo Target Server: myown-deploy (72.15.24.46:58221)
echo Working Dir:   /var/www/fast
echo.

set SERVER=myown-deploy
set "REMOTE_COMMAND=cd /var/www/fast && git checkout -f && git pull && mkdir -p data/appraisals && rm -f data/appraisals/*.json && venv/bin/pip install -r requirements.txt && sudo -u www-data pm2 restart fast --update-env && sudo -u www-data pm2 status fast"

echo Executing remote deployment pipeline...
echo 1. Pulling latest codebase updates from git
echo 2. Purging legacy .json appraisal caches in data/appraisals/
echo 3. Synchronizing Python virtual environment dependencies
echo 4. Restarting PM2 service with updated ecosystem config (max_memory_restart: 2G)
echo.
echo (If prompted, please enter your server SSH/sudo credentials)
echo.

ssh -t %SERVER% "%REMOTE_COMMAND%"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================================
    echo  SUCCESS: F.A.S.T. v2.0 deployed and restarted cleanly!
    echo ========================================================
) else (
    echo.
    echo ========================================================
    echo  ERROR: Deployment encountered an issue (Exit Code: %ERRORLEVEL%)
    echo ========================================================
)

echo.
pause
