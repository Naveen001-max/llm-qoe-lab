# Operations

- Back up PostgreSQL with `BACKUP_DIR=/mnt/encrypted/qoe-backups ./backup_postgres.sh` from `production/` (uses `.env.production` and `docker-compose.yml`).
- Restore only to a designated recovery database after checksum verification and explicit approval.
- Run `verify_deployment.sh` after deployment.
- Backups should be encrypted, access-controlled, retained according to the approved study data policy, and restore-tested on a schedule.
