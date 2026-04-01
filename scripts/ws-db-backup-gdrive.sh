#!/usr/bin/env bash
# ws-db-backup-gdrive.sh — Daily PostgreSQL full backup → gzip → Google Drive
set -euo pipefail

# ─── Config ─────────────────────────────────────────────────────────────────
DOCKER_CONTAINER="ws-infra-postgres-1"
PGUSER="joneshong"
PGDATABASE="workshop"
RCLONE="/opt/homebrew/bin/rclone"
GDRIVE_REMOTE="gdrive"
GDRIVE_PATH="backups/workshop-db"
MAX_BACKUPS=4

BACKUP_DIR="$(mktemp -d /tmp/ws-db-backup-XXXXXX)"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_FILE="${BACKUP_DIR}/workshop-db-${TIMESTAMP}.sql.gz"
DRY_RUN=false

# ─── Logging ─────────────────────────────────────────────────────────────────
log() {
    echo "[db-backup] $(date '+%Y-%m-%d %H:%M:%S') $*"
}

# ─── Error notification + exit ───────────────────────────────────────────────
die() {
    local msg="$1"
    log "ERROR: $msg"
    ~/workshop/scripts/workshop-notify.sh "DB Backup Failed" "$msg" \
        --category scheduler --severity warning 2>/dev/null || true
    exit 1
}

# ─── Cleanup trap ────────────────────────────────────────────────────────────
cleanup() {
    if [[ -d "$BACKUP_DIR" ]]; then
        log "Cleaning up temp dir: $BACKUP_DIR"
        rm -rf "$BACKUP_DIR"
    fi
}
trap cleanup EXIT

# ─── Parse args ──────────────────────────────────────────────────────────────
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        *) die "Unknown argument: $arg" ;;
    esac
done

if $DRY_RUN; then
    log "=== DRY-RUN MODE — no actual backup or upload will occur ==="
fi

# ─── Pre-flight checks ───────────────────────────────────────────────────────
log "Pre-flight: checking Docker container '$DOCKER_CONTAINER' is running..."
if ! docker ps --format '{{.Names}}' | grep -q "^${DOCKER_CONTAINER}$"; then
    die "Docker container '$DOCKER_CONTAINER' is not running"
fi
log "Pre-flight: container is running."

log "Pre-flight: checking rclone at '$RCLONE'..."
if [[ ! -x "$RCLONE" ]]; then
    die "rclone not found or not executable at '$RCLONE'"
fi
log "Pre-flight: rclone OK."

# ─── Dump ────────────────────────────────────────────────────────────────────
if $DRY_RUN; then
    log "[DRY-RUN] Would run: docker exec $DOCKER_CONTAINER pg_dump -U $PGUSER -d $PGDATABASE --no-owner --no-acl | gzip -9 > $BACKUP_FILE"
else
    log "Starting pg_dump for database '$PGDATABASE'..."
    docker exec "$DOCKER_CONTAINER" \
        pg_dump -U "$PGUSER" -d "$PGDATABASE" --no-owner --no-acl \
        | gzip -9 > "$BACKUP_FILE"
    log "pg_dump complete: $BACKUP_FILE"
fi

# ─── Sanity check ────────────────────────────────────────────────────────────
if $DRY_RUN; then
    log "[DRY-RUN] Would verify backup file is > 1KB"
else
    FILESIZE=$(stat -f%z "$BACKUP_FILE" 2>/dev/null || stat -c%s "$BACKUP_FILE")
    if [[ "$FILESIZE" -lt 1024 ]]; then
        die "Backup file is suspiciously small (${FILESIZE} bytes < 1KB): $BACKUP_FILE"
    fi
    log "Sanity check passed: file size ${FILESIZE} bytes."
fi

# ─── Upload ──────────────────────────────────────────────────────────────────
REMOTE_DEST="${GDRIVE_REMOTE}:${GDRIVE_PATH}"

if $DRY_RUN; then
    log "[DRY-RUN] Would run: $RCLONE copy $BACKUP_FILE $REMOTE_DEST/"
else
    log "Uploading to $REMOTE_DEST/..."
    "$RCLONE" copy "$BACKUP_FILE" "${REMOTE_DEST}/"
    log "Upload complete."
fi

# ─── Verify upload ───────────────────────────────────────────────────────────
REMOTE_FILENAME="$(basename "$BACKUP_FILE")"

if $DRY_RUN; then
    log "[DRY-RUN] Would verify upload: $RCLONE ls ${REMOTE_DEST}/$REMOTE_FILENAME"
else
    log "Verifying upload..."
    if ! "$RCLONE" ls "${REMOTE_DEST}/" | grep -q "$REMOTE_FILENAME"; then
        die "Upload verification failed — '$REMOTE_FILENAME' not found on remote"
    fi
    log "Upload verified: $REMOTE_FILENAME"
fi

# ─── Rotate old backups ──────────────────────────────────────────────────────
if $DRY_RUN; then
    log "[DRY-RUN] Would list $REMOTE_DEST/ and delete oldest if count > $MAX_BACKUPS"
else
    log "Checking backup rotation (max $MAX_BACKUPS)..."

    # List all matching backup files, sorted by name (name encodes timestamp, so alphabetical = chronological)
    REMOTE_FILES=$("$RCLONE" lsf "${REMOTE_DEST}/" --include "workshop-db-*.sql.gz" | sort)
    REMOTE_COUNT=$(echo "$REMOTE_FILES" | grep -c . || true)

    log "Found $REMOTE_COUNT backup(s) on remote."

    if [[ "$REMOTE_COUNT" -gt "$MAX_BACKUPS" ]]; then
        DELETE_COUNT=$(( REMOTE_COUNT - MAX_BACKUPS ))
        log "Rotating: deleting $DELETE_COUNT oldest backup(s)..."

        echo "$REMOTE_FILES" | head -n "$DELETE_COUNT" | while read -r old_file; do
            log "Deleting old backup: $old_file"
            "$RCLONE" deletefile "${REMOTE_DEST}/${old_file}"
        done

        log "Rotation complete."
    else
        log "No rotation needed."
    fi
fi

# ─── Done ────────────────────────────────────────────────────────────────────
log "=== Backup completed successfully. File: $(basename "$BACKUP_FILE") ==="
