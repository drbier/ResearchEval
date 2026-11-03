# F.A.C.T. Production Server Setup — Tech Administrator Handoff Sheet

**To:** System Administrator / Technical Lead  
**From:** Dr. Bier  
**Subject:** Initial Provisioning & Sudoers Permission for F.A.C.T. v2.0 (`https://fact.wonkproject.com`)  
**Date:** November 3, 2026  

---

### Executive Summary

We are deploying **F.A.C.T. v2.0 (ResearchEval)** on our production Ubuntu server alongside HomeoWonk, OWEN, and GTSyncD. 

**The Block:** I have SSH key authentication working (`id_ed25519_deploy`), but the automated deploy script halts because it prompts for the `deploy` user's remote Linux `sudo` password, which I do not have.

**What is needed:**
1. Execute the initial 1-minute repository clone and setup script on the server.
2. Add a standard `NOPASSWD` sudoers entry for user `deploy` (identical to our HomeoWonk/OWEN setup) so my local `deploy.bat` can push updates with a single double-click.

---

### Server & Infrastructure Details

| Parameter | Value |
| :--- | :--- |
| **Server IP / Host** | `72.15.24.46` |
| **SSH Port** | `58221` |
| **Admin Login** | `drb` or `root` |
| **Deploy User** | `deploy` |
| **Destination Path** | `/var/www/fact` |
| **Production Domain** | `https://fact.wonkproject.com` |
| **Internal App Port** | `127.0.0.1:3008` (proxied by Nginx) |
| **Process Daemon** | PM2 (`fact`) under user `www-data` |
| **Git Repository** | `https://github.com/drbier/ResearchEval.git` |

---

### Step 1: Connect to Server (via custom port 58221)

```bash
ssh -p 58221 drb@72.15.24.46
# or: ssh -p 58221 root@72.15.24.46
```

---

### Step 2: One-Command Initial Deployment

Run this single block as root or with `sudo`:

```bash
# 1. Create directory and assign ownership to deploy:www-data
sudo mkdir -p /var/www/fact
sudo chown -R deploy:www-data /var/www/fact

# 2. Clone the repository
sudo git clone https://github.com/drbier/ResearchEval.git /var/www/fact

# 3. Run the automated provisioning script
cd /var/www/fact
sudo bash setup_production.sh
```

#### What `setup_production.sh` does automatically:
- Creates required runtime data directories (`data/uploads`, `data/appraisals`, `data/cache`) with write permissions.
- Provisions a dedicated Python 3 virtual environment at `/var/www/fact/venv`.
- Installs all dependencies from `requirements.txt` (`fastapi`, `uvicorn`, `pymupdf`, etc.).
- Automatically copies the active `GEMINI_API_KEY` from `/var/www/homeowonk/.env` into `/var/www/fact/.env`.
- Deploys and activates the Nginx virtual host for `fact.wonkproject.com` (configured with SSL certificates matching `owen.wonkproject.com`).
- Starts and persists the PM2 process named `fact` under user `www-data`.

---

### Step 3: Grant Passwordless Sudo to User `deploy` (Prevents Future Lockouts)

To ensure I can deploy future updates from my local machine using `deploy.bat` without hitting a sudo password block:

```bash
cat << 'EOF' | sudo tee /etc/sudoers.d/deploy-fact
# Allow deploy user to manage /var/www/fact and reload services without interactive password
deploy ALL=(ALL) NOPASSWD: /bin/bash /var/www/fact/setup_production.sh
deploy ALL=(ALL) NOPASSWD: /usr/bin/systemctl reload nginx
deploy ALL=(ALL) NOPASSWD: /usr/sbin/nginx -t
deploy ALL=(www-data) NOPASSWD: /usr/bin/pm2 restart fact *
deploy ALL=(www-data) NOPASSWD: /usr/bin/pm2 reload fact *
deploy ALL=(www-data) NOPASSWD: /usr/bin/pm2 status *
deploy ALL=(www-data) NOPASSWD: /usr/bin/pm2 logs fact *
EOF

sudo chmod 0440 /etc/sudoers.d/deploy-fact
```

*(Optional alternative: If you prefer to set a known password for `deploy`, simply run `sudo passwd deploy` and send me the password).*

---

### Step 4: Verification & Smoke Test

Check that PM2 and the internal listener are healthy:

```bash
# Check PM2 daemon status
sudo -u www-data pm2 status fact

# Test internal listener
curl -I http://127.0.0.1:3008/

# Verify public site
curl -I https://fact.wonkproject.com/
```

Once complete, please let me know so I can trigger the first test sync from my workstation!

