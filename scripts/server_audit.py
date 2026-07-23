"""
CCS platform server audit — local Python script.
Usage: python scripts/server_audit.py
"""

import subprocess
import sys

HOST = "root@209.38.93.174"
KEY = r"O:\downloads-nov-2018\python-self-programs\aws\digitaloceannxai-private.pem"

REMOTE = r"""
python3 - <<'PYEOF'
import subprocess, shutil, os
from datetime import datetime, timezone

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return r.stdout.strip()

print("=" * 50)
print(f" CCS PLATFORM — SERVER AUDIT")
print(f" {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
print("=" * 50)

# Uptime / load
print("\n[UPTIME & LOAD]")
print(run("uptime"))

# Memory
print("\n[MEMORY]")
mem = {}
for line in open("/proc/meminfo"):
    k, v = line.split(":")
    mem[k.strip()] = int(v.strip().split()[0])
total_gb = mem["MemTotal"] / 1024 / 1024
used_gb  = (mem["MemTotal"] - mem["MemAvailable"]) / 1024 / 1024
avail_gb = mem["MemAvailable"] / 1024 / 1024
pct = used_gb / total_gb * 100
print(f"  Total:     {total_gb:.1f} GB")
print(f"  Used:      {used_gb:.1f} GB  ({pct:.0f}%)")
print(f"  Available: {avail_gb:.1f} GB")
swap = mem.get("SwapTotal", 0)
print(f"  Swap:      {'none' if swap == 0 else f'{swap/1024/1024:.1f} GB'}")

# Disk
print("\n[DISK]")
st = os.statvfs("/")
total_d = st.f_blocks * st.f_frsize / 1e9
used_d  = (st.f_blocks - st.f_bfree) * st.f_frsize / 1e9
free_d  = st.f_bavail * st.f_frsize / 1e9
print(f"  Total: {total_d:.0f} GB   Used: {used_d:.1f} GB   Free: {free_d:.0f} GB  ({used_d/total_d*100:.0f}%)")

# CPU
print("\n[CPU]")
print(f"  Cores: {os.cpu_count()}")
load = open("/proc/loadavg").read().split()[:3]
print(f"  Load avg (1m / 5m / 15m): {' / '.join(load)}")

# Services
print("\n[SERVICES]")
for svc in ["ccs-api", "ccs-worker", "ccs-beat", "nginx", "redis"]:
    r = subprocess.run(["systemctl", "is-active", svc], capture_output=True, text=True)
    status = r.stdout.strip()
    icon = "✓" if status == "active" else "✗"
    print(f"  {icon}  {svc:<20} {status}")

# Top processes by memory
print("\n[TOP PROCESSES by memory]")
lines = run("ps aux --sort=-%mem --no-headers").splitlines()[:8]
for line in lines:
    parts = line.split(None, 10)
    user, pid, cpu, mem_pct = parts[0], parts[1], parts[2], parts[3]
    cmd = parts[10][:55] if len(parts) > 10 else ""
    print(f"  PID {pid:<7} CPU {cpu:>5}%  MEM {mem_pct:>5}%  {cmd}")

# Celery errors
print("\n[CELERY ERRORS — last 50 log lines]")
result = run("journalctl -u ccs-worker --no-pager -n 50 --output=short 2>/dev/null")
errors = [l for l in result.splitlines() if any(x in l for x in ("ERROR", "WARN", "Traceback", "Exception"))]
if errors:
    for e in errors[-5:]:
        print(f"  {e}")
else:
    print("  (none)")

# Recent deploys
print("\n[DEPLOY TIMESTAMPS]")
result = run("ls -lt /opt/apps/ccs-platform/")
for line in result.splitlines()[1:7]:
    print(f"  {line}")

print("\n" + "=" * 50)
PYEOF
"""

def main():
    cmd = [
        "ssh",
        "-i", KEY,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        HOST,
        REMOTE,
    ]
    try:
        result = subprocess.run(cmd, capture_output=False, text=True)
        sys.exit(result.returncode)
    except FileNotFoundError:
        print("ERROR: ssh not found. Ensure Git Bash / OpenSSH is on PATH.")
        sys.exit(1)

if __name__ == "__main__":
    main()
