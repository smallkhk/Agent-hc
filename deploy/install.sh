#!/usr/bin/env bash
# One-command install / update on a fresh Ubuntu 22.04 or 24.04 VPS.
#
#   curl -fsSL https://raw.githubusercontent.com/smallkhk/Agent-hc/claude/new-session-ij0chs/deploy/install.sh | sudo bash
#
# No domain needed: it uses this server's free sslip.io name (1.2.3.4 → handcam.1-2-3-4.sslip.io, no account),
# so the server's plain address stays free for any other site. If port 3000 is taken, it picks a free port.
# To use your own domain instead, add it at the end:  ... | sudo bash -s -- handcam.example.com
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
if [ -z "$DOMAIN" ] && [ -f "$DIR/.env" ]; then # re-run: keep the address chosen the first time
  DOMAIN=$(grep -E '^PUBLIC_URL=' "$DIR/.env" | sed -E 's|^PUBLIC_URL=https?://([^/:]+).*|\1|' || true)
fi
if [ -z "$DOMAIN" ]; then # free name that always points at this server: 1.2.3.4 → handcam.1-2-3-4.sslip.io
  ip=$(curl -4 -fsS --max-time 10 https://ifconfig.me || true)
  [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "could not find this server's IPv4 address; give a domain instead"
  DOMAIN="${ip//./-}.sslip.io"
fi
# the bare sslip.io name is the server's own address: keep it for other sites, use handcam.<ip>.sslip.io
if [[ "$DOMAIN" =~ ^[0-9]+-[0-9]+-[0-9]+-[0-9]+\.sslip\.io$ ]]; then DOMAIN="handcam.$DOMAIN"; fi
echo "Hand Cam address: https://$DOMAIN"
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
.venv/bin/pip install -q --no-deps rapidocr_onnxruntime==1.4.4  # offline text reading (deps are in requirements)
.venv/bin/pip uninstall -y -q opencv-python 2>/dev/null || true  # never next to opencv-python-headless

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

# Port for the app (nginx forwards to it). Keep it unless another program already listens there.
listeners() { ss -ltnpH "sport = :$1" 2>/dev/null | grep -o 'pid=[0-9]*' | cut -d= -f2 | sort -u; }
ours() { [ "$(readlink -f "/proc/$1/cwd" 2>/dev/null)" = "$(readlink -f "$DIR")" ]; }
port=$(getenv PORT); port=${port:-3000}
taken=0
for pid in $(listeners "$port"); do ours "$pid" || taken=1; done
if [ "$taken" = 1 ]; then
  for p in $(seq 3100 3999); do
    if [ -z "$(ss -ltnH "sport = :$p" 2>/dev/null)" ]; then
      echo "port $port is used by another program: Hand Cam will use port $p"; port=$p; break
    fi
  done
fi
setenv PORT "$port"
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

# Our site file sorts last ("zz-") so it never becomes nginx's catch-all for the server's plain address;
# it answers only on $DOMAIN and other sites on this server are left alone.
site=/etc/nginx/sites-available/zz-handcam
rm -f /etc/nginx/sites-enabled/handcam /etc/nginx/sites-available/handcam # name used by older versions
mkdir -p /var/www/certbot
# Older versions switched off nginx's default site. If it serves a real site (not the nginx welcome page), restore it.
if [ -f /etc/nginx/sites-available/default ] && [ ! -e /etc/nginx/sites-enabled/default ] &&
   [ -n "$(find /var/www/html -mindepth 1 ! -name 'index.nginx-debian.html' 2>/dev/null | head -1)" ]; then
  ln -s /etc/nginx/sites-available/default /etc/nginx/sites-enabled/default
  if nginx -t -q 2>/dev/null; then echo "restored your existing site (nginx default site)"; else rm -f /etc/nginx/sites-enabled/default; fi
fi
if [ "$SKIP_TLS" = 1 ]; then
  step "HTTPS skipped (HANDCAM_SKIP_TLS=1)"
elif [ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
  step "HTTPS certificate for $DOMAIN"
  my_ip=$(curl -4 -fsS https://ifconfig.me || true)
  dns_ip=$(getent ahostsv4 "$DOMAIN" | awk 'NR==1 {print $1}' || true)
  if [ -n "$my_ip" ] && [ "$dns_ip" != "$my_ip" ]; then
    die "$DOMAIN points to '${dns_ip:-nothing}', but this server is $my_ip.
Point the domain at $my_ip, wait a few minutes, then run this again."
  fi
  # temporary plain-HTTP site so Let's Encrypt can check the domain
  printf 'server {\n  listen 80;\n  server_name %s;\n  location /.well-known/acme-challenge/ { root /var/www/certbot; }\n}\n' \
    "$DOMAIN" > "$site"
  ln -sf "$site" /etc/nginx/sites-enabled/zz-handcam
  nginx -t -q || die "nginx rejected its config (see above)"
  systemctl reload nginx
  certbot certonly --webroot -w /var/www/certbot -d "$DOMAIN" -n --agree-tos --register-unsafely-without-email \
    --deploy-hook "systemctl reload nginx" ||
    die "no HTTPS certificate yet (see the certbot message above).
If it says 'too many certificates', Let's Encrypt's weekly quota for $DOMAIN's parent domain is used up
by other people: wait a few hours and run this command again. Everything else is already installed."
fi
if [ "$SKIP_TLS" != 1 ]; then
  sed -e "s/handcam.example.com/$DOMAIN/g" -e "s/127.0.0.1:3000/127.0.0.1:$port/" deploy/nginx/handcam.conf > "$site"
  if [ ! -s /proc/net/if_inet6 ]; then sed -i '/listen \[::\]/d' "$site"; fi # no IPv6 on this server
  ln -sf "$site" /etc/nginx/sites-enabled/zz-handcam
  nginx -t -q || die "nginx rejected its config (see above)"
  systemctl reload nginx
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
# stop a manual preview of the API (started by hand from $DIR, not by PM2) so PM2 can take the port
for pid in $(listeners "$port"); do
  if ours "$pid" && ! tr '\0' '\n' < "/proc/$pid/environ" 2>/dev/null | grep -q '^pm_id='; then kill "$pid"; fi
done
npm run -s bot:deploy || die "Discord rejected the bot login: check DISCORD_TOKEN and DISCORD_CLIENT_ID in $DIR/.env"
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
