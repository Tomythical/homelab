#!/bin/bash
# Backup existing SQLite database before PostgreSQL migration

set -e

echo "Backing up existing journiv SQLite database..."

# Get the journiv-app pod name
POD_NAME=$(kubectl get pods -n journiv -l app=journiv-app -o jsonpath='{.items[0].metadata.name}')

if [ -z "$POD_NAME" ]; then
	echo "Error: Could not find journiv-app pod"
	exit 1
fi

# Create backup directory
BACKUP_DIR="/tmp/journiv-backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

echo "Backing up from pod: $POD_NAME"
echo "Backup directory: $BACKUP_DIR"

# Copy SQLite database and related files
echo "Copying SQLite database files..."
kubectl cp journiv/"$POD_NAME":/data/journiv.db "$BACKUP_DIR/journiv.db"
kubectl cp journiv/"$POD_NAME":/data/journiv.db-shm "$BACKUP_DIR/journiv.db-shm" 2>/dev/null || true
kubectl cp journiv/"$POD_NAME":/data/journiv.db-wal "$BACKUP_DIR/journiv.db-wal" 2>/dev/null || true

# Check file sizes
echo ""
echo "Backup complete. File sizes:"
ls -lh "$BACKUP_DIR/"

# Create a checksum for verification
echo ""
echo "Creating checksums..."
md5sum "$BACKUP_DIR/journiv.db" >"$BACKUP_DIR/checksums.md5"
if [ -f "$BACKUP_DIR/journiv.db-shm" ]; then
	md5sum "$BACKUP_DIR/journiv.db-shm" >>"$BACKUP_DIR/checksums.md5"
fi
if [ -f "$BACKUP_DIR/journiv.db-wal" ]; then
	md5sum "$BACKUP_DIR/journiv.db-wal" >>"$BACKUP_DIR/checksums.md5"
fi

echo ""
echo "Checksums:"
cat "$BACKUP_DIR/checksums.md5"

echo ""
echo "Backup completed successfully!"
echo "Files saved to: $BACKUP_DIR"
echo ""
echo "You can restore if needed with:"
echo "  kubectl cp $BACKUP_DIR/journiv.db journiv/<pod-name>:/data/journiv.db"
