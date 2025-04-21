#!/bin/bash
set -e

# Display the current settings
echo "🔧 Starting with PUID: ${PUID}, PGID: ${PGID}"

# Create group if it doesn't exist
if ! getent group ${PGID} > /dev/null; then
    echo "📂 Creating group with GID: ${PGID}"
    groupadd -g ${PGID} appgroup
fi

# Create or modify user
if ! getent passwd ${PUID} > /dev/null; then
    echo "👤 Creating user with UID: ${PUID}"
    useradd -u ${PUID} -g ${PGID} -d /app -s /bin/bash appuser
else
    echo "👤 Modifying user with UID: ${PUID}"
    usermod -g ${PGID} $(getent passwd ${PUID} | cut -d: -f1)
fi

# Set ownership of app files
echo "📁 Setting correct ownership for app files"
chown -R ${PUID}:${PGID} /app

# Run the command as the specified user
echo "🚀 Starting application as UID ${PUID}, GID ${PGID}"
exec gosu ${PUID}:${PGID} "$@"
