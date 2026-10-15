#!/usr/bin/env bash
# Run as root through Cloud Assistant on the existing Ubuntu ECS.
# stunnel terminates TLS only; SSH host keys and public-key authentication are unchanged.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run as root.' >&2; exit 2; }
config_dir=/etc/doorhandle-ssh-tls
override=/etc/systemd/system/ssh.socket.d/zz-doorhandle-ssh-tls.conf
backup=/var/lib/doorhandle-ssh-tls/backup-$(date -u +%Y%m%dT%H%M%SZ)
install -d -m 0700 "$backup"
systemctl cat ssh.socket > "$backup/ssh.socket.txt"
if [[ -f "$override" ]]; then cp -a "$override" "$backup/socket-override.conf"; fi
if ! command -v stunnel4 >/dev/null; then
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends stunnel4 > "$backup/package-install.log" 2>&1
fi
id stunnel4 >/dev/null
install -d -o root -g stunnel4 -m 0750 "$config_dir"
if [[ ! -f "$config_dir/server.key" ]]; then
    umask 077
    openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days 365 \
        -subj '/CN=doorhandle-ssh.local' -addext 'subjectAltName=DNS:doorhandle-ssh.local' \
        -addext 'extendedKeyUsage=serverAuth' \
        -keyout "$config_dir/server.key" -out "$config_dir/server.crt" 2> "$backup/certificate.log"
fi
chown root:stunnel4 "$config_dir/server.key" "$config_dir/server.crt"
chmod 0640 "$config_dir/server.key" "$config_dir/server.crt"
cat > "$config_dir/stunnel.conf" <<'CONF'
foreground = yes
syslog = no
pid =
sslVersionMin = TLSv1.2
cert = /etc/doorhandle-ssh-tls/server.crt
key = /etc/doorhandle-ssh-tls/server.key
[ssh]
accept = 0.0.0.0:443
connect = 127.0.0.1:22
TIMEOUTconnect = 10
TIMEOUTidle = 3600
TIMEOUTclose = 0
CONF
chmod 0640 "$config_dir/stunnel.conf"
chown root:stunnel4 "$config_dir/stunnel.conf"
cat > /etc/systemd/system/doorhandle-ssh-tls.service <<'UNIT'
[Unit]
Description=TLS transport for the existing DoorHandle SSH service
After=network-online.target ssh.socket
Wants=network-online.target
Requires=ssh.socket
[Service]
Type=simple
User=stunnel4
Group=stunnel4
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=strict
ExecStart=/usr/bin/stunnel4 /etc/doorhandle-ssh-tls/stunnel.conf
Restart=on-failure
RestartSec=3
[Install]
WantedBy=multi-user.target
UNIT
install -d -m 0755 /etc/systemd/system/ssh.socket.d
cat > "$override" <<'SOCKET'
[Socket]
ListenStream=
ListenStream=0.0.0.0:22
ListenStream=[::]:22
BindIPv6Only=ipv6-only
SOCKET
restore_ports() {
    systemctl stop doorhandle-ssh-tls.service || true
    if [[ -f "$backup/socket-override.conf" ]]; then
        cp -a "$backup/socket-override.conf" "$override"
    else
        rm -f "$override"
    fi
    systemctl daemon-reload
    systemctl stop ssh.service ssh.socket || true
    systemctl start ssh.socket ssh.service
}
trap 'restore_ports; echo "TLS setup failed; original SSH listeners restored." >&2' ERR
systemctl daemon-reload
systemctl stop ssh.service ssh.socket
systemctl start ssh.socket ssh.service
ssh-keyscan -T 5 -t ed25519 -p 22 127.0.0.1 > "$backup/local-ssh-hostkey" 2> "$backup/local-ssh-check.log"
test -s "$backup/local-ssh-hostkey"
systemctl enable doorhandle-ssh-tls.service >/dev/null
systemctl restart doorhandle-ssh-tls.service
systemctl is-active --quiet ssh.service
systemctl is-active --quiet doorhandle-ssh-tls.service
tls_ok=false
for attempt in 1 2 3 4 5; do
    if openssl s_client -connect 127.0.0.1:443 -servername doorhandle-ssh.local \
        -CAfile "$config_dir/server.crt" -verify_return_error -verify_hostname doorhandle-ssh.local \
        -brief </dev/null > "$backup/local-tls-check.log" 2>&1; then
        tls_ok=true
        break
    fi
    sleep 1
done
[[ "$tls_ok" == true ]]
trap - ERR
printf 'SSH_TLS_READY\n'
openssl x509 -in "$config_dir/server.crt" -noout -fingerprint -sha256
printf 'PUBLIC_CERT_DER_BASE64 '
openssl x509 -in "$config_dir/server.crt" -outform DER | base64 -w0
printf '\n'
