# Journiv SQLite → PostgreSQL Migration

This migration addresses data loss issues caused by concurrent SQLite access from multiple pods. PostgreSQL provides proper concurrent access handling.

## Migration Overview

### Current Issues
- **Concurrent SQLite access**: 3 services (app, celery-worker, celery-beat) all access same SQLite file
- **Data corruption**: SQLite not designed for multi-pod concurrent writes
- **Version mismatch**: App (0.1.0-beta.21) vs Celery services (latest)

### Solution
- **PostgreSQL 15**: Proper database for concurrent access
- **Fresh start**: New database (existing data likely corrupted)
- **Automated backups**: Daily pg_dump cron job
- **Standardized versions**: All services → 0.1.0-beta.21

## Files Created/Modified

### New Files
- `postgres.yaml` - PostgreSQL StatefulSet with 5Gi PVC
- `postgres-service.yaml` - PostgreSQL ClusterIP service
- `postgres-backup.yaml` - Daily backup CronJob
- `setup-postgres-secrets.sh` - Doppler secrets setup script
- `backup-sqlite.sh` - SQLite backup script
- `test-postgres-migration.sh` - Migration validation script

### Modified Files
- `external-secret.yaml` - Added PostgreSQL secret mappings
- `app.yaml` - Updated DB_DRIVER, DATABASE_URL, ENVIRONMENT
- `celery-worker.yaml` - Updated image version, DB_DRIVER, DATABASE_URL
- `celery-beat.yaml` - Updated image version, DB_DRIVER, DATABASE_URL
- `kustomization.yaml` - Added new PostgreSQL resources

## Migration Steps

### Step 1: Backup Existing Data (Optional)
```bash
./apps/journiv/backup-sqlite.sh
```
Backs up current SQLite database to `/tmp/journiv-backup-*/`

### Step 2: Setup Doppler Secrets
```bash
./apps/journiv/setup-postgres-secrets.sh
```
Sets up required PostgreSQL secrets in Doppler (project: `talos-homelab`, config: `prd`):
- `JOURNIV_POSTGRES_USER` (journiv)
- `JOURNIV_POSTGRES_PASSWORD` (random 32 char)
- `JOURNIV_POSTGRES_DB` (journiv)
- `JOURNIV_POSTGRES_HOST` (postgres.journiv.svc.cluster.local)
- `JOURNIV_DATABASE_URL` (constructed connection string)

**Note**: Wait 1-2 minutes for Doppler → Kubernetes sync

### Step 3: Deploy Changes
Commit and push changes. Flux will automatically deploy:
```bash
git add apps/journiv/
git commit -m "feat: migrate journiv from SQLite to PostgreSQL"
git push
```

### Step 4: Monitor Deployment
```bash
./apps/journiv/test-postgres-migration.sh
```

Monitor Flux sync:
```bash
flux get kustomizations apps
flux logs --kind=Kustomization --name=apps --tail=50
```

### Step 5: Verify Functionality
1. Check all pods are running:
   ```bash
   kubectl get pods -n journiv
   ```

2. Test PostgreSQL connection:
   ```bash
   kubectl exec -n journiv deployment/journiv-app -- env | grep DATABASE
   ```

3. Check application logs:
   ```bash
   kubectl logs -n journiv deployment/journiv-app --tail=50
   ```

4. Access web interface: `https://journiv.ts.net`

## Rollback Procedure

If issues occur, revert to SQLite:

1. Revert deployment changes:
   ```bash
   git revert HEAD  # If migration commit is latest
   git push
   ```

2. Manual rollback (if needed):
   - Delete PostgreSQL StatefulSet: `kubectl delete -n journiv statefulset/postgres`
   - Keep PVC for investigation
   - Restore SQLite backup if needed

## PostgreSQL Configuration

### Resources
- **CPU**: 100m request, 500m limit
- **Memory**: 256Mi request, 1Gi limit
- **Storage**: 5Gi PVC using `local-path` storage class

### Security
- Runs as UID 999 (PostgreSQL default)
- Proper health checks with `pg_isready`
- Secrets managed via ExternalSecret/Doppler

### Backups
- **Schedule**: Daily at 2 AM
- **Location**: Same PVC as app data (`journiv-data`)
- **Retention**: Manual (7 days recommended)

## Post-Migration Validation

✅ All 3 services running simultaneously  
✅ No database corruption errors in logs  
✅ PostgreSQL responsive (<100ms queries)  
✅ Daily backups successful  
✅ Application performance stable  

## Troubleshooting

### PostgreSQL Not Starting
```bash
kubectl describe -n journiv statefulset/postgres
kubectl logs -n journiv postgres-0
kubectl get pvc -n journiv
```

### Application Can't Connect
```bash
kubectl exec -n journiv deployment/journiv-app -- env | grep DATABASE
kubectl exec -n journiv postgres-0 -- pg_isready -U journiv
```

### ExternalSecret Not Syncing
```bash
kubectl get externalsecrets -n journiv journiv-secrets -o yaml
kubectl get secrets -n journiv journiv-secrets -o yaml | grep -A5 "stringData:"
```

## Expected Timeline
- **Day 1**: Secret setup & initial deployment (2-3h)
- **Day 2**: Application updates & testing (2-3h)
- **Day 3**: Monitoring & backup validation (1h)
- **Total**: 5-7 hours over 3 days

## Notes
- Fresh start recommended due to likely SQLite corruption
- PostgreSQL provides better long-term stability
- Backups start automatically after deployment
- Monitor resource usage (4CPU/16GB cluster)