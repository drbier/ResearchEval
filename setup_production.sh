#!/usr/bin/env bash
# ==============================================================================
# setup_production.sh - Initial Provisioning & Nginx Setup for F.A.C.T. v2.0
# Domain: fact.wonkproject.com -> 127.0.0.1:3008
# ==============================================================================

set -e

APP_DIR="/var/www/fact"
DOMAIN="fact.wonkproject.com"
PORT=3008

echo "=== [1/6] Setting directory permissions on $APP_DIR ==="
mkdir -p "$APP_DIR/data/uploads" "$APP_DIR/data/appraisals" "$APP_DIR/data/cache"
chown -R deploy:www-data "$APP_DIR"
chmod -R 775 "$APP_DIR"
chmod -R 777 "$APP_DIR/data/uploads" "$APP_DIR/data/appraisals" "$APP_DIR/data/cache"

echo "=== [2/6] Setting up Python virtual environment ==="
cd "$APP_DIR"
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi
echo "Installing and updating dependencies..."
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt

echo "=== [3/6] Configuring environment (.env) ==="
if [ ! -f "$APP_DIR/.env" ]; then
    if [ -f "/var/www/homeowonk/.env" ]; then
        echo "Copying GEMINI_API_KEY from /var/www/homeowonk/.env..."
        grep "GEMINI_API_KEY" /var/www/homeowonk/.env > "$APP_DIR/.env" || true
    fi
    if [ ! -s "$APP_DIR/.env" ]; then
        echo "Creating default .env template..."
        echo "ENVIRONMENT=production" >> "$APP_DIR/.env"
        echo "PORT=3008" >> "$APP_DIR/.env"
    fi
    chown deploy:www-data "$APP_DIR/.env"
    chmod 660 "$APP_DIR/.env"
fi

echo "=== [4/6] Creating Nginx configuration for $DOMAIN ==="
cat << 'EOF' > /etc/nginx/sites-available/fact.wonkproject.com
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
EOF

echo "Enabling Nginx site..."
ln -sf /etc/nginx/sites-available/fact.wonkproject.com /etc/nginx/sites-enabled/
nginx -t
systemctl reload nginx

echo "=== [5/6] Registering & Starting PM2 process ==="
if sudo -u www-data pm2 describe fact > /dev/null 2>&1; then
    echo "Restarting existing PM2 process 'fact'..."
    sudo -u www-data pm2 restart fact --update-env
else
    echo "Starting new PM2 process 'fact'..."
    sudo -u www-data pm2 start ecosystem.config.cjs
    sudo -u www-data pm2 save
fi

# Ensure deploy user has passwordless restart for future automatic deploy.bat updates
if [ -f /etc/sudoers.d/deploy-pm2 ] && ! grep -q "restart fact" /etc/sudoers.d/deploy-pm2; then
    echo "Configuring passwordless PM2 reload for deploy user..."
    sed -i 's/$/\, \/usr\/bin\/pm2 restart fact --update-env/' /etc/sudoers.d/deploy-pm2
fi

echo "=== [6/6] Production Deployment Status ==="
sudo -u www-data pm2 status fact

echo ""
echo "=========================================================================="
echo " SUCCESS: F.A.C.T. v2.0 is live at https://fact.wonkproject.com"
echo "=========================================================================="

