#!/usr/bin/env bash
# CCS platform server audit — run locally to check droplet health
# Usage: bash scripts/server_audit.sh
# Requires SSH key at O:/downloads-nov-2018/python-self-programs/aws/digitaloceannxai-private.pem

HOST="root@209.38.93.174"
KEY="O:/downloads-nov-2018/python-self-programs/aws/digitaloceannxai-private.pem"

ssh -i "$KEY" -o StrictHostKeyChecking=no "$HOST" '
echo "========================================="
echo " CCS PLATFORM — SERVER AUDIT"
echo " $(date)"
echo "========================================="

echo ""
echo "--- UPTIME & LOAD ---"
uptime

echo ""
echo "--- MEMORY ---"
free -h

echo ""
echo "--- DISK ---"
df -h /

echo ""
echo "--- DROPLET SPEC ---"
echo "CPUs: $(nproc)"
echo "RAM:  $(awk "/MemTotal/ {printf \"%.1f GB\", \$2/1024/1024}" /proc/meminfo)"

echo ""
echo "--- SERVICES ---"
for svc in ccs-api ccs-worker ccs-beat nginx redis; do
  status=$(systemctl is-active $svc 2>/dev/null || echo "not-found")
  printf "  %-20s %s\n" "$svc" "$status"
done

echo ""
echo "--- TOP PROCESSES (by memory) ---"
ps aux --sort=-%mem --no-headers | head -8 | awk "{printf \"  %-10s %5s%% MEM  %5s%% CPU  %s\n\", \$1, \$4, \$3, \$11}"

echo ""
echo "--- CELERY RECENT ERRORS (last 20 lines) ---"
journalctl -u ccs-worker --no-pager -n 20 --output=short 2>/dev/null | grep -E "ERROR|WARN|Traceback|Exception" | tail -10 || echo "  (none)"

echo ""
echo "--- RECENT DEPLOYS ---"
ls -lt /opt/apps/ccs-platform/ | head -6

echo "========================================="
'
