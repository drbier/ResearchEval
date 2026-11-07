# F.A.C.T. (ResearchEval) Production Server Setup & Deployment Guide

This document is for the system administrator / technical lead to provision, configure, and maintain the production deployment of **F.A.C.T. v2.0 (ResearchEval)**.

---

## 1. System Coordinates & Architecture Overview

| Parameter | Production Value |
| :--- | :--- |
| **Server Hostname / IP** | `72.15.24.46` |
| **SSH Port** | `58221` *(custom port)* |
| **Primary Deployment User** | `deploy` *(or administrative user `drb`)* |
| **Local SSH Key Path** | `~/.ssh/id_ed25519_deploy` (or `~/.ssh/id_ed25519_drb`) |
| **Application Directory** | `/var/www/fact` |
| **Public Domain** | `https://fact.wonkproject.com` |
| **Internal App Port** | `127.0.0.1:3008` |
| **Process Manager** | PM2 running under user `www-data` |
| **Reverse Proxy** | Nginx with SSL termination via Let's Encrypt |
| **Git Repository** | `https://github.com/drbier/ResearchEval.git` |

---

## 2. Root Cause of Current User Blocker

When running the automated client deployment script (`deploy.bat`), SSH authentication succeeds via the public key, but the script halts at:

```bash
sudo mkdir -p /var/www/fact && sudo chown -R deploy:www-data /var/www/fact ...
```

The user is prompted for the remote Linux `sudo` password for user `deploy` and does not have it.

### Required Administrative Fix:
To allow autonomous continuous deployment without interactive password stalls, configure passwordless sudo for user `deploy` (see **Section 6**), or reset the `deploy` user password:
```bash
sudo passwd deploy
```

---

## 3. Quick Automated Provisioning (Option A)

If you have root or `drb` administrative SSH access to `72.15.24.46:58221`:

```bash
# 1. Connect to the server
ssh -p 58221 drb@72.15.24.46
# (or as root)

# 2. Clone the repository if not already present
sudo mkdir -p /var/www/fact
sudo chown -R deploy:www-data /var/www/fact
sudo git clone https://github.com/drbier/ResearchEval.git /var/www/fact

# 3. Run the automated provisioning script
cd /var/www/fact
sudo bash setup_production.sh
```

The `setup_production.sh` script automatically:
1. Creates directory trees (`data/uploads`, `data/appraisals`, `data/cache`) with write permissions.
2. Initializes the Python virtual environment at `/var/www/fact/venv`.
3. Installs all pip dependencies from `requirements.txt`.
4. Copies the production `GEMINI_API_KEY` from sibling app `/var/www/homeowonk/.env` if present.
5. Deploys `/etc/nginx/sites-available/fact.wonkproject.com` and enables it.
6. Starts and saves the PM2 worker process `fact` under `www-data`.

---

## 4. Manual Step-by-Step Installation (Option B)

If you prefer to configure each layer manually:

### Step 4.1: System Packages & Python Environment
Ensure Python 3.10+ and build tools are present:
```bash
sudo apt update
sudo apt install -y python3-venv python3-pip build-essential libgl1
```

Initialize directory and permissions:
```bash
sudo mkdir -p /var/www/fact
sudo chown -R deploy:www-data /var/www/fact
sudo chmod -R 775 /var/www/fact
```

Clone the code and create the virtual environment:
```bash
cd /var/www/fact
git clone https://github.com/drbier/ResearchEval.git .
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
```

### Step 4.2: Data Directories & Permissions
```bash
mkdir -p /var/www/fact/data/uploads /var/www/fact/data/appraisals /var/www/fact/data/cache
chmod -R 777 /var/www/fact/data/uploads /var/www/fact/data/appraisals /var/www/fact/data/cache
```

### Step 4.3: Environment Configuration (`.env`)
Create `/var/www/fact/.env`:
```env
PORT=3008
ENVIRONMENT=production
PYTHONPATH=.
GEMINI_API_KEY=YOUR_GEMINI_API_KEY_HERE
```
> **Tip:** You can reuse the working Gemini API key from the existing HomeoWonk instance on this server:
> ```bash
> grep "GEMINI_API_KEY" /var/www/homeowonk/.env | sudo tee -a /var/www/fact/.env
> ```

Lock down `.env` permissions:
```bash
sudo chown deploy:www-data /var/www/fact/.env
sudo chmod 660 /var/www/fact/.env
```

### Step 4.4: Nginx Configuration
Create `/etc/nginx/sites-available/fact.wonkproject.com`:

```nginx
server {
    server_name fact.wonkproject.com;

    # Allow manuscript uploads up to 50MB
    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:3008;
        proxy_http_version 1.1;

        # WebSocket & Server-Sent Events (SSE) support
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';

        # Standard Proxy Headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Disable cache buffering for real-time responsiveness
        proxy_buffering off;
        proxy_cache_bypass $http_upgrade;

        # Generous timeouts for Deep Audit & LLM Appraisal
        proxy_connect_timeout 120s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
    }

    listen 8443 ssl;
    ssl_certificate /etc/letsencrypt/live/owen.wonkproject.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/owen.wonkproject.com/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
}

server {
    if ($host = fact.wonkproject.com) {
        return 301 https://$host$request_uri;
    }

    listen 8080;
    server_name fact.wonkproject.com;
    return 404;
}
```

Enable and reload Nginx:
```bash
sudo ln -sf /etc/nginx/sites-available/fact.wonkproject.com /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

> **Note on Ports & SSL:** This host runs Nginx SSL on port `8443` (redirecting from `8080` or mapped externally via firewall/NAT). The SSL certificates reuse the existing certificate bundle at `/etc/letsencrypt/live/owen.wonkproject.com/`. If a distinct certificate for `fact.wonkproject.com` is preferred, run:
> ```bash
> sudo certbot --nginx -d fact.wonkproject.com
> ```

---

## 5. PM2 Daemon Registration

The application uses PM2 to run FastAPI with Uvicorn in the background as a managed daemon under user `www-data`:

```bash
cd /var/www/fact

# Start via PM2 ecosystem configuration
sudo -u www-data pm2 start ecosystem.config.cjs

# Persist daemon across server reboots
sudo -u www-data pm2 save
```

Verify PM2 status:
```bash
sudo -u www-data pm2 status fact
sudo -u www-data pm2 logs fact --lines 30
```

---

## 6. Sudoers Configuration for User `deploy` (Prevents Future Lockouts)

To allow the user to run `deploy.bat` from their workstation without needing to enter a password for Nginx and PM2 reloads, add a sudoers rule:

Create `/etc/sudoers.d/deploy-fact`:
```bash
sudo visudo -f /etc/sudoers.d/deploy-fact
```

Insert the following lines:
```sudoers
# Allow deploy user to manage /var/www/fact and restart PM2 / Nginx without password
deploy ALL=(ALL) NOPASSWD: /bin/bash /var/www/fact/setup_production.sh
deploy ALL=(ALL) NOPASSWD: /usr/bin/systemctl reload nginx
deploy ALL=(ALL) NOPASSWD: /usr/sbin/nginx -t
deploy ALL=(www-data) NOPASSWD: /usr/bin/pm2 restart fact *
deploy ALL=(www-data) NOPASSWD: /usr/bin/pm2 reload fact *
deploy ALL=(www-data) NOPASSWD: /usr/bin/pm2 status *
deploy ALL=(www-data) NOPASSWD: /usr/bin/pm2 logs fact *
```

Ensure correct permissions on the sudoers file:
```bash
sudo chmod 0440 /etc/sudoers.d/deploy-fact
```

---

## 7. Ongoing Deployment Workflow (Client Machine)

Once the above configuration is in place, future application updates require only executing the local batch script:

```cmd
D:\SSD-Drive\Antigravity\FACT\deploy.bat
```

This automatically pulls the latest Git commits, reinstalls dependencies, flushes ephemeral caches, and reloads PM2 with zero downtime.

---

## 8. Diagnostic & Troubleshooting Quick Reference

| Action | Command |
| :--- | :--- |
| **Check PM2 process status** | `sudo -u www-data pm2 status` |
| **View live application logs** | `sudo -u www-data pm2 logs fact` |
| **Restart application service** | `sudo -u www-data pm2 restart fact --update-env` |
| **Test direct backend listener** | `curl -I http://127.0.0.1:3008/` |
| **Test Nginx config syntax** | `sudo nginx -t` |
| **Reload Nginx reverse proxy** | `sudo systemctl reload nginx` |
| **Check directory permissions** | `ls -la /var/www/fact/data/` |
| **Inspect error logs** | `sudo tail -n 50 /var/log/nginx/error.log` |
