#!/usr/bin/env bash
# Grandway backup: PostgreSQL dump FIRST, then the media volume.
#
# Usage (as root):
#   /opt/grandway/deploy/backup.sh [label]      # label defaults to "scheduled"
#   /opt/grandway/deploy/backup.sh "pre-v1.0.1" # before an upgrade
#
# Ordering is deliberate. The file ledger never deletes bytes, so a database
# snapshot taken BEFORE the media tar can at worst leave orphan files in the
# tar that no row references — harmless. The reverse order can produce a
# database row pointing at bytes the tar does not hold, which restores as
# UPLOADED_FILES_FILE_BYTES_MISSING (404). See deploy.md §17 (Backup and restore).
#
# Only "*-scheduled.*" artefacts are pruned; a labelled backup (a pre-upgrade
# snapshot) is kept until a human removes it.
#
# Environment overrides: BACKUP_DIR, DB_NAME, MEDIA_ROOT, KEEP_DAYS.

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/grandway}"
DB_NAME="${DB_NAME:-grandway}"
MEDIA_ROOT="${MEDIA_ROOT:-/var/lib/grandway/media}"
KEEP_DAYS="${KEEP_DAYS:-14}"
LABEL="${1:-scheduled}"

case "$LABEL" in
    *[!A-Za-z0-9._-]*|"")
        echo "backup.sh: label may contain only A-Z a-z 0-9 . _ - (got '$LABEL')" >&2
        exit 2
        ;;
esac

if [ "$(id -u)" -ne 0 ]; then
    echo "backup.sh: run as root (needs to read $MEDIA_ROOT and write $BACKUP_DIR)" >&2
    exit 1
fi

umask 077
install -d -m 0700 -o root -g root "$BACKUP_DIR"

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DB_DUMP="$BACKUP_DIR/db-$STAMP-$LABEL.dump"
MEDIA_TAR="$BACKUP_DIR/media-$STAMP-$LABEL.tar.gz"
MANIFEST="$BACKUP_DIR/manifest-$STAMP-$LABEL.sha256"

# 1. Database, custom format (pg_restore-able, compressed, selective).
runuser -u postgres -- pg_dump -Fc "$DB_NAME" > "$DB_DUMP"

# 2. Media volume, preserving the 0640/0750 permission bits.
tar -C "$(dirname "$MEDIA_ROOT")" -cpzf "$MEDIA_TAR" "$(basename "$MEDIA_ROOT")"

# 3. Checksums, so a copy taken off-host can be verified with `sha256sum -c`.
(cd "$BACKUP_DIR" && sha256sum "$(basename "$DB_DUMP")" "$(basename "$MEDIA_TAR")" > "$MANIFEST")

# 4. Prune scheduled artefacts only.
find "$BACKUP_DIR" -maxdepth 1 -type f \
    \( -name 'db-*-scheduled.dump' -o -name 'media-*-scheduled.tar.gz' -o -name 'manifest-*-scheduled.sha256' \) \
    -mtime +"$KEEP_DAYS" -delete

echo "backup complete: $(du -h "$DB_DUMP" | cut -f1) database, $(du -h "$MEDIA_TAR" | cut -f1) media, manifest $MANIFEST"
echo "$DB_DUMP $MEDIA_TAR"
