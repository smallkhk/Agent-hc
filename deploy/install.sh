#!/usr/bin/env bash
# One-command install / update on a fresh Ubuntu 22.04 or 24.04 VPS.
#
#   curl -fsSL https://raw.githubusercontent.com/smallkhk/Agent-hc/claude/new-session-ij0chs/deploy/install.sh | sudo bash -s -- your-name.duckdns.org
#
# Run 1 installs everything, sets up HTTPS and writes /opt/handcam/.env with generated secrets.
# Then put your Discord and LiveKit keys in that .env and run the same command again: run 2 starts the bot,
# API and vision worker under PM2. Safe to re-run any time (updates the code, keeps .env, database and certificates).
set -euo pipefail

DOMAIN="${1:-}"
REPO="${HANDCAM_REPO:-https://github.com/smallkhk/Agent-hc.git}"
BRANCH="${HANDCAM_BRANCH:-claude/new-session-ij0chs}"
DIR="${HANDCAM_DIR:-/opt/handcam}"
SKIP_TLS="${HANDCAM_SKIP_TLS:-0}" # for testing without a public domain only
export DEBIAN_FRONTEND=noninteractive

step() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "run as root: put sudo before bash"
[ -n "$DOMAIN" ] || die "give your domain, e.g.: ... | sudo bash -s -- your-name.duckdns.org"
[[ "$DOMAIN" =~ ^[a-zA-Z0-9.-]+$ ]] || die "'$DOMAIN' is not a domain name (no https://, no slashes)"

# --- packages ----------------------------------------------------------------------------------

step "System packages (a few minutes)"
apt-get update -q
PKGS=(git curl ca-certificates openssl nginx certbot ffmpeg mysql-server redis-server software-properties-common htop)
# a package's setup step can trip once (e.g. MySQL's first start); finish it and retry once
apt-get install -y -q "${PKGS[@]}" || { sleep 5; dpkg --configure -a; apt-get install -y -q "${PKGS[@]}"; }
# Ubuntu 22.04's own python3.11 is a release candidate and 24.04 has none: use the deadsnakes build.
if ! grep -rqs deadsnakes /etc/apt/sources.list.d/; then add-apt-repository -y ppa:deadsnakes/ppa; fi
apt-get install -y -q python3.11 python3.11-venv
node_major=$(node -v 2>/dev/null | sed -E 's/^v([0-9]+).*/\1/' || true)
if [ -z "$node_major" ] || [ "$node_major" -lt 20 ]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y -q nodejs
fi
command -v pm2 >/dev/null || npm install -g --silent pm2

step "Small-server tuning"
if [ ! -f /etc/mysql/mysql.conf.d/handcam-lowmem.cnf ]; then
  printf '[mysqld]\nperformance_schema=OFF\n' > /etc/mysql/mysql.conf.d/handcam-lowmem.cnf
fi
systemctl enable --now mysql redis-server nginx
systemctl restart mysql
swap_mb=$(free -m | awk '/^Swap:/ {print $2}')
if [ "${swap_mb:-0}" -lt 2000 ] && [ ! -f /swapfile-handcam ]; then
  fallocate -l 2G /swapfile-handcam && chmod 600 /swapfile-handcam && mkswap /swapfile-handcam >/dev/null
  swapon /swapfile-handcam || true
  echo '/swapfile-handcam none swap sw 0 0' >> /etc/fstab
fi

# --- code --------------------------------------------------------------------------------------

step "App code → $DIR"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch -q origin "$BRANCH"
  git -C "$DIR" checkout -q "$BRANCH"
  git -C "$DIR" reset -q --hard "origin/$BRANCH"
else
  git clone -q -b "$BRANCH" "$REPO" "$DIR"
fi
cd "$DIR"
npm ci --no-audit --no-fund --loglevel=error
[ -x .venv/bin/python ] || python3.11 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r worker/requirements.txt

# --- config ------------------------------------------------------------------------------------

getenv() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- || true; }
setenv() { # KEY VALUE: replace the line, or append it
  if grep -qE "^$1=" .env; then sed -i "s|^$1=.*|$1=$2|" .env; else echo "$1=$2" >> .env; fi
}

step "Settings (.env)"
if [ ! -f .env ]; then
  cp .env.example .env
  setenv SESSION_SECRET "$(openssl rand -hex 32)"
  setenv WORKER_SECRET "$(openssl rand -hex 32)"
  setenv MYSQL_URL "mysql://handcam:$(openssl rand -hex 16)@localhost:3306/handcam"
  setenv STORAGE_DIR /var/handcam/recordings
  if [ "$(nproc)" -le 2 ]; then setenv RECORD_FPS 10; fi
  echo "created $DIR/.env"
fi
setenv PUBLIC_URL "https://$DOMAIN"
chmod 600 .env
mkdir -p "$(getenv STORAGE_DIR)"

step "Database"
db_pass=$(getenv MYSQL_URL | sed -E 's|^mysql://[^:]+:([^@]+)@.*|\1|')
mysql -e "CREATE DATABASE IF NOT EXISTS handcam;
  CREATE USER IF NOT EXISTS 'handcam'@'localhost' IDENTIFIED BY '$db_pass';
  ALTER USER 'handcam'@'localhost' IDENTIFIED BY '$db_pass';
  GRANT ALL ON handcam.* TO 'handcam'@'localhost';"
npm run -s db:migrate

# --- HTTPS -------------------------------------------------------------------------------------

site=/etc/nginx/sites-available/handcam
mkdir -p /var/www/certbot
rm -f /etc/nginx/sites-enabled/default
if [ "$SKIP_TLS" = 1 ]; then
  step "HTTPS skipped (HANDCAM_SKIP_TLS=1)"
elif [ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
  step "HTTPS certificate for $DOMAIN"
  my_ip=$(curl -4 -fsS https://ifconfig.me || true)
  dns_ip=$(getent ahostsv4 "$DOMAIN" | awk 'NR==1 {print $1}' || true)
  if [ -n "$my_ip" ] && [ "$dns_ip" != "$my_ip" ]; then
    die "$DOMAIN points to '${dns_ip:-nothing}', but this server is $my_ip.
Set the domain's IP to $my_ip (DuckDNS: the 'current ip' box), wait a few minutes, then run this again."
  fi
  # temporary plain-HTTP site so Let's Encrypt can check the domain
  printf 'server {\n  listen 80;\n  listen [::]:80;\n  server_name %s;\n  location /.well-known/acme-challenge/ { root /var/www/certbot; }\n}\n' \
    "$DOMAIN" > "$site"
  ln -sf "$site" /etc/nginx/sites-enabled/handcam
  nginx -t -q && systemctl reload nginx
  certbot certonly --webroot -w /var/www/certbot -d "$DOMAIN" -n --agree-tos --register-unsafely-without-email \
    --deploy-hook "systemctl reload nginx"
fi
if [ "$SKIP_TLS" != 1 ]; then
  sed "s/handcam.example.com/$DOMAIN/g" deploy/nginx/handcam.conf > "$site"
  ln -sf "$site" /etc/nginx/sites-enabled/handcam
  nginx -t -q && systemctl reload nginx
fi
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  ufw allow OpenSSH >/dev/null && ufw allow 'Nginx Full' >/dev/null
fi

# --- start -------------------------------------------------------------------------------------

missing=()
for k in DISCORD_TOKEN DISCORD_CLIENT_ID DISCORD_CLIENT_SECRET LIVEKIT_API_KEY LIVEKIT_API_SECRET; do
  [ -n "$(getenv "$k")" ] || missing+=("$k")
done
case "$(getenv LIVEKIT_URL)" in *your-project*|"") missing+=(LIVEKIT_URL) ;; esac

if [ ${#missing[@]} -gt 0 ]; then
  step "Installed. One step left: your keys"
  cat <<EOF
Open the settings file:   nano $DIR/.env
Fill in these lines (Discord Developer Portal + LiveKit Cloud):
$(printf '  %s=\n' "${missing[@]}")
Also set BRAND_NAME to your community's name if you like.
Save (Ctrl+O, Enter, Ctrl+X), then run the same install command again to start everything.
EOF
  exit 0
fi

step "Starting bot, API and vision worker"
npm run -s bot:deploy
pm2 startOrReload deploy/ecosystem.config.cjs --update-env
pm2 save
pm2 startup systemd -u root --hp /root >/dev/null
sleep 3
pm2 ls

step "Done"
cat <<EOF
Website:          https://$DOMAIN
Admin dashboard:  https://$DOMAIN/admin.html
Discord OAuth redirect to add in the Developer Portal: https://$DOMAIN/auth/callback
Next in Discord:  /handcam config alert_channel:#your-alerts-channel
Logs:             pm2 logs        Update later: run the install command again.
EOF
