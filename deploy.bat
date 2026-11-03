@echo off
setlocal

echo ========================================================
echo         F.A.S.T. v2.0 Production Server Deployment
echo ========================================================
echo Target Server: myown-deploy (72.15.24.46:58221)
echo Working Dir:   /var/www/fast
echo Domain:        https://fast.wonkproject.com
echo.

set SERVER=myown-deploy

REM One unified command that detects if /var/www/fast is already initialized:
REM If not initialized: clones repo, runs setup_production.sh (provisions venv, Nginx config, and PM2).
REM If already initialized: pulls git, clears appraisal caches, updates pip, restarts PM2.

set "REMOTE_COMMAND=if [ ! -d /var/www/fast ]; then echo '>>> Initializing /var/www/fast for first-time deployment...' && sudo mkdir -p /var/www/fast && sudo chown -R deploy:www-data /var/www/fast && git clone https://github.com/drbier/ResearchEval.git /var/www/fast && sudo bash /var/www/fast/setup_production.sh; else echo '>>> Updating existing /var/www/fast deployment...' && cd /var/www/fast && git checkout -f && git pull && mkdir -p data/appraisals && rm -f data/appraisals/*.json && venv/bin/pip install -r requirements.txt && sudo bash /var/www/fast/setup_production.sh; fi"

echo Executing deployment pipeline...
echo.
echo (If prompted, please enter your server sudo credentials)
echo.

ssh -t %SERVER% "%REMOTE_COMMAND%"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================================
    echo  SUCCESS: F.A.S.T. v2.0 deployed and live!
    echo  Access URL: https://fast.wonkproject.com
    echo ========================================================
) else (
    echo.
    echo ========================================================
    echo  ERROR: Deployment encountered an issue (Exit Code: %ERRORLEVEL%)
    echo ========================================================
)

echo.
pause
