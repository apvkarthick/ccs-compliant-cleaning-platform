# CCS Compliant Cleaning Platform

FastAPI + Celery + PyMuPDF backend for the Compliant Cleaning Supplies document distribution and rebranding system.

## Droplet

- Host: `209.38.93.174`
- App path: `/opt/apps/ccs-platform`
- Services: `ccs-api`, `ccs-worker`, `redis-server`, `nginx`

## Local Sync

```powershell
scp -i "O:\downloads-nov-2018\python-self-programs\aws\digitaloceannxai-private.pem" -r "E:\claude\ccs-compliant-cleaning-platform\*" root@209.38.93.174:/opt/apps/ccs-platform/
ssh -i "O:\downloads-nov-2018\python-self-programs\aws\digitaloceannxai-private.pem" root@209.38.93.174 "bash /opt/apps/ccs-platform/deploy/deploy.sh"
```

## GitHub Actions Secrets

Add these repository secrets before enabling CI/CD:

- `DROPLET_HOST`: `209.38.93.174`
- `DROPLET_USER`: `root`
- `DROPLET_SSH_KEY`: private key content for the matching public key in `/root/.ssh/authorized_keys`

Keep application credentials only on the droplet in `/opt/apps/ccs-platform/.env`; do not commit them.
