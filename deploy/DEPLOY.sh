#!/bin/bash
# FinTrack — Production Deployment Guide
# ========================================
# Run this guide step-by-step on a fresh Ubuntu 22.04/24.04 server.
# All commands assume you are logged in as a non-root sudo user.

# ═══════════════════════════════════════════════════════════════
# STEP 1 — System dependencies
# ═══════════════════════════════════════════════════════════════

sudo apt update && sudo apt upgrade -y

sudo apt install -y \
    python3.11 python3.11-venv python3.11-dev \
    postgresql postgresql-contrib \
    redis-server \
    nginx \
    certbot python3-certbot-nginx \
    build-essential libpq-dev \
    git curl

# ═══════════════════════════════════════════════════════════════
# STEP 2 — Create a dedicated system user (recommended)
# ═══════════════════════════════════════════════════════════════

sudo useradd --system --no-create-home --shell /bin/false fintrack
# OR use www-data if you prefer

# ═══════════════════════════════════════════════════════════════
# STEP 3 — PostgreSQL database setup
# ═══════════════════════════════════════════════════════════════

sudo -u postgres psql <<'SQL'
CREATE DATABASE fintrack_db;
CREATE USER fintrack_user WITH PASSWORD 'STRONG_DB_PASSWORD_HERE';
ALTER ROLE fintrack_user SET client_encoding TO 'utf8';
ALTER ROLE fintrack_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE fintrack_user SET timezone TO 'Asia/Tashkent';
GRANT ALL PRIVILEGES ON DATABASE fintrack_db TO fintrack_user;
\q
SQL

# ═══════════════════════════════════════════════════════════════
# STEP 4 — Application setup
# ═══════════════════════════════════════════════════════════════

# Clone or upload your project
# git clone https://github.com/your/fintrack.git /srv/fintrack
# OR scp -r ./fintrack_mobile user@server:/srv/fintrack

APP_DIR=/srv/fintrack

# Create Python virtual environment
python3.11 -m venv $APP_DIR/venv
source $APP_DIR/venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r $APP_DIR/requirements.txt

# ═══════════════════════════════════════════════════════════════
# STEP 5 — Environment configuration
# ═══════════════════════════════════════════════════════════════

# Copy the example and fill in real values
cp $APP_DIR/.env.example $APP_DIR/.env

# Generate a strong secret key
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(50))"

# Edit .env — MINIMUM required changes:
cat > $APP_DIR/.env << 'ENV'
SECRET_KEY=REPLACE_WITH_OUTPUT_OF_ABOVE_COMMAND
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

DATABASE_URL=postgresql://fintrack_user:STRONG_DB_PASSWORD_HERE@localhost:5432/fintrack_db
REDIS_URL=redis://127.0.0.1:6379/1

LANGUAGE_CODE=uz
TIME_ZONE=Asia/Tashkent

# AI providers — add at least one key
GROQ_API_KEY=
OPENAI_API_KEY=
GEMINI_API_KEY=

SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=True

RATE_LIMIT_ENABLED=True
IDLE_LOGOUT_ENABLED=False
LOG_LEVEL=WARNING
ENV

chmod 600 $APP_DIR/.env

# ═══════════════════════════════════════════════════════════════
# STEP 6 — Django setup
# ═══════════════════════════════════════════════════════════════

cd $APP_DIR
source venv/bin/activate

# Run migrations
python manage.py migrate --noinput

# Collect static files into staticfiles/
python manage.py collectstatic --noinput

# Run Django's deployment checks — fix any warnings before going live
python manage.py check --deploy

# Create a superuser (optional — can also use seed_demo)
python manage.py createsuperuser

# ═══════════════════════════════════════════════════════════════
# STEP 7 — File permissions
# ═══════════════════════════════════════════════════════════════

# All project files readable by fintrack user
sudo chown -R fintrack:www-data $APP_DIR
sudo chmod -R 750 $APP_DIR

# Media uploads writable
sudo chmod -R 775 $APP_DIR/media
sudo mkdir -p $APP_DIR/media

# Static files readable by Nginx
sudo chmod -R 755 $APP_DIR/staticfiles

# ═══════════════════════════════════════════════════════════════
# STEP 8 — Gunicorn systemd service
# ═══════════════════════════════════════════════════════════════

# Edit deploy/fintrack.service — replace /path/to/ with $APP_DIR
sed -i "s|/path/to/fintrack_mobile|$APP_DIR|g" $APP_DIR/deploy/fintrack.service
sed -i "s|/path/to/venv|$APP_DIR/venv|g"       $APP_DIR/deploy/fintrack.service

sudo cp $APP_DIR/deploy/fintrack.service /etc/systemd/system/fintrack.service
sudo systemctl daemon-reload
sudo systemctl enable fintrack
sudo systemctl start fintrack

# Verify it's running
sudo systemctl status fintrack
# Should show: Active: active (running)

# Check socket was created
ls -la /run/fintrack/gunicorn.sock

# ═══════════════════════════════════════════════════════════════
# STEP 9 — Nginx configuration
# ═══════════════════════════════════════════════════════════════

# Edit the Nginx config — replace yourdomain.com and /path/to/
sed -i "s|/path/to/fintrack_mobile|$APP_DIR|g" $APP_DIR/deploy/nginx.conf
# Also replace yourdomain.com with your actual domain

sudo cp $APP_DIR/deploy/nginx.conf /etc/nginx/sites-available/fintrack
sudo ln -sf /etc/nginx/sites-available/fintrack /etc/nginx/sites-enabled/

# Remove default Nginx site
sudo rm -f /etc/nginx/sites-enabled/default

# Test config
sudo nginx -t

# ═══════════════════════════════════════════════════════════════
# STEP 10 — SSL with Let's Encrypt
# ═══════════════════════════════════════════════════════════════

# First, start Nginx without SSL (comment out the HTTPS server block temporarily)
sudo systemctl start nginx

# Get certificate
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com

# Certbot will automatically update the Nginx config with SSL settings
# Auto-renewal is set up by certbot automatically

# Reload Nginx
sudo systemctl reload nginx

# ═══════════════════════════════════════════════════════════════
# STEP 11 — Redis setup
# ═══════════════════════════════════════════════════════════════

# Start Redis
sudo systemctl enable redis-server
sudo systemctl start redis-server

# Test Redis
redis-cli ping  # Should return: PONG

# Optional: secure Redis (bind to localhost only — default on Ubuntu)
# /etc/redis/redis.conf: bind 127.0.0.1 ::1

# ═══════════════════════════════════════════════════════════════
# STEP 12 — Firewall
# ═══════════════════════════════════════════════════════════════

sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw --force enable
sudo ufw status

# ═══════════════════════════════════════════════════════════════
# STEP 13 — Final verification
# ═══════════════════════════════════════════════════════════════

echo "Services status:"
sudo systemctl status fintrack  --no-pager -l
sudo systemctl status nginx     --no-pager
sudo systemctl status redis     --no-pager

echo ""
echo "Test the application:"
echo "  curl -I https://yourdomain.com"
echo "  Should return: HTTP/2 200 or HTTP/2 301"

echo ""
echo "Django deployment check:"
cd $APP_DIR && source venv/bin/activate && python manage.py check --deploy

# ═══════════════════════════════════════════════════════════════
# MAINTENANCE COMMANDS
# ═══════════════════════════════════════════════════════════════
#
# Deploy new code:
#   git pull
#   source venv/bin/activate
#   pip install -r requirements.txt
#   python manage.py migrate --noinput
#   python manage.py collectstatic --noinput
#   sudo systemctl restart fintrack
#   sudo systemctl reload nginx
#
# View logs:
#   sudo journalctl -u fintrack -f
#   sudo tail -f /var/log/nginx/fintrack_error.log
#
# Backup database:
#   pg_dump -U fintrack_user fintrack_db > backup_$(date +%Y%m%d).sql
#
# Restore database:
#   psql -U fintrack_user fintrack_db < backup_YYYYMMDD.sql
