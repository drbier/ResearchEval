@echo off
setlocal

echo ========================================================
echo         F.A.C.T. v2.0 Production Server Deployment
echo ========================================================
echo Target Server: myown-deploy (72.15.24.46:58221)
echo Working Dir:   /var/www/fact
echo Domain:        https://fact.wonkproject.com
echo.

set SERVER=myown-deploy

REM One unified command that detects if /var/www/fact is already initialized:
REM If not initialized: clones repo, runs setup_production.sh (provisions venv, Nginx config, and PM2).
REM If already initialized: pulls git, clears appraisal caches, updates pip, restarts PM2.

set "REMOTE_COMMAND=if [ ! -d /var/www/fact/.git ]; then echo '>>> Initializing /var/www/fact for first-time deployment...' && sudo mkdir -p /var/www/fact && sudo chown -R deploy:www-data /var/www/fact && git clone https://github.com/drbier/ResearchEval.git /var/www/fact && sudo bash /var/www/fact/setup_production.sh; else echo '>>> Updating existing /var/www/fact deployment...' && cd /var/www/fact && git checkout -f && git pull origin main && mkdir -p data/appraisals data/uploads data/cache && rm -f data/appraisals/*.json && ( [ -d venv ] || python3 -m venv venv ) && venv/bin/pip install -q --upgrade pip && venv/bin/pip install -q -r requirements.txt && sudo -u www-data pm2 restart fact --update-env; fi"

echo Executing deployment pipeline...
echo.
echo (Zero-password deployment)
echo.

ssh -t %SERVER% "%REMOTE_COMMAND%"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================================
    echo  SUCCESS: F.A.C.T. v2.0 deployed and live!
    echo  Access URL: https://fact.wonkproject.com
    echo ========================================================
) else (
    echo.
    echo ========================================================
    echo  ERROR: Deployment encountered an issue (Exit Code: %ERRORLEVEL%)
    echo ========================================================
)

echo.
pause
