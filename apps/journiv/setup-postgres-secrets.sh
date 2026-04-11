#!/bin/bash
# Script to set up PostgreSQL secrets in Doppler for journiv migration
# Requires Doppler CLI to be installed and configured

set -e

echo "Setting up PostgreSQL secrets for journiv migration..."

# Generate random password for PostgreSQL
POSTGRES_PASSWORD=$(openssl rand -base64 32)

# Check if Doppler is authenticated
if ! doppler me >/dev/null 2>&1; then
	echo "Error: Doppler CLI is not authenticated."
	echo "Please run: doppler login"
	exit 1
fi

# Check current project and config
echo "Current Doppler authentication:"
doppler me

echo ""
echo "Checking current Doppler project and config..."
CURRENT_PROJECT=$(doppler configure get project --plain 2>/dev/null || echo "")
CURRENT_CONFIG=$(doppler configure get config --plain 2>/dev/null || echo "")

if [ -n "$CURRENT_PROJECT" ] && [ -n "$CURRENT_CONFIG" ]; then
	echo "Currently configured:"
	echo "  Project: $CURRENT_PROJECT"
	echo "  Config: $CURRENT_CONFIG"
else
	echo "No project/config configured locally."
fi

echo ""
echo "Based on your homelab setup, you should use:"
echo "  Project: talos-homelab"
echo "  Config: prd"
echo ""
echo "If this is incorrect, press Ctrl+C now."
echo "Otherwise, press Enter to continue..."
read

# Set secrets in Doppler
echo ""
echo "Setting secrets in Doppler (project: talos-homelab, config: prd)..."
doppler secrets set -p talos-homelab -c prd JOURNIV_POSTGRES_USER=journiv
doppler secrets set -p talos-homelab -c prd JOURNIV_POSTGRES_PASSWORD="$POSTGRES_PASSWORD"
doppler secrets set -p talos-homelab -c prd JOURNIV_POSTGRES_DB=journiv
doppler secrets set -p talos-homelab -c prd JOURNIV_POSTGRES_HOST="postgres.journiv.svc.cluster.local"

# Construct DATABASE_URL
DATABASE_URL="postgresql://journiv:${POSTGRES_PASSWORD}@postgres.journiv.svc.cluster.local:5432/journiv"
doppler secrets set -p talos-homelab -c prd JOURNIV_DATABASE_URL="$DATABASE_URL"

echo ""
echo "Secrets have been set in Doppler:"
echo ""
echo "JOURNIV_POSTGRES_USER=journiv"
echo "JOURNIV_POSTGRES_PASSWORD=******** (32 char random)"
echo "JOURNIV_POSTGRES_DB=journiv"
echo "JOURNIV_POSTGRES_HOST=postgres.journiv.svc.cluster.local"
echo "JOURNIV_DATABASE_URL=$DATABASE_URL"
echo ""
echo "Verifying secrets were set..."
doppler secrets -p talos-homelab -c prd | grep -i journiv

echo ""
echo "The ExternalSecret will automatically sync these to Kubernetes."
echo "Wait 1-2 minutes for synchronization, then deploy the PostgreSQL migration."
