#!/bin/bash

# -----------------------------------------------------------------------------
# Database Backup Script for Jivu Farm ERP
# -----------------------------------------------------------------------------
# This script creates a point-in-time backup of the PostgreSQL database
# running inside a Docker container. It uses pg_dump for a clean, non-locking
# snapshot and stores it locally.
#
# Requirements:
#   - Docker must be installed and running.
#   - The user running this script must have permissions to execute docker commands.
# -----------------------------------------------------------------------------

# --- Configuration ---
# Get the directory of the currently executing script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# --- Dynamic variables from your environment ---
DB_CONTAINER="school-finance-db"
DB_NAME="jivu_farm_db"
DB_USER="postgres"

# --- Static variables ---
# The backup will be stored in a 'backups' subdirectory relative to the script's location
BACKUP_DIR="${SCRIPT_DIR}/backups"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}.sql"

# --- Pre-flight Checks ---
# 1. Ensure the backup directory exists
mkdir -p "${BACKUP_DIR}"
if [ ! -d "${BACKUP_DIR}" ]; then
    echo "Error: Could not create backup directory at ${BACKUP_DIR}."
    exit 1
fi

# 2. Check if the Docker container is running
if ! docker ps | grep -q "${DB_CONTAINER}"; then
    echo "Error: The database container '${DB_CONTAINER}' is not running."
    exit 1
fi

# --- Main Execution ---
echo "Starting backup of database '${DB_NAME}' from container '${DB_CONTAINER}'..."

# Execute pg_dump inside the container and redirect output to the backup file
docker exec -t "${DB_CONTAINER}" pg_dump -U "${DB_USER}" -d "${DB_NAME}" -F c -b -v -f "/tmp/${TIMESTAMP}.sql"

# Copy the backup from the container to the host
docker cp "${DB_CONTAINER}:/tmp/${TIMESTAMP}.sql" "${BACKUP_FILE}"

# Clean up the temporary file inside the container
docker exec -t "${DB_CONTAINER}" rm "/tmp/${TIMESTAMP}.sql"

# --- Verification ---
if [ -s "${BACKUP_FILE}" ]; then
    echo "✅ Backup successful!"
    echo "Snapshot saved to: ${BACKUP_FILE}"
else
    echo "❌ Backup failed. The output file is empty."
    # Clean up the empty file
    rm "${BACKUP_FILE}"
    exit 1
fi

# --- (Optional) Cleanup: Remove backups older than 7 days ---
echo "Cleaning up old backups (older than 7 days)..."
find "${BACKUP_DIR}" -type f -name "*.sql" -mtime +7 -exec rm {} \;
echo "Cleanup complete."

exit 0
