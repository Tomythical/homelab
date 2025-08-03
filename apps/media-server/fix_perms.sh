#!/usr/bin/env bash
# fix-perms-no-sudo.sh – assumes `abc:abc` can already chown inside pod

set -euo pipefail
IFS=$'\n\t'

NAMESPACE="${1:-media-server}"
LABEL_BASE="app.kubernetes.io/name=k8s-mediaserver"
USER="abc"
GROUP="abc"
declare -A VOLUMES=(["radarr"]="/movies" ["sonarr"]="/tv")
declare -A DEPLOY_KEYS=(["radarr"]="app=radarr" ["sonarr"]="app=sonarr")

echo

for APP in "${!VOLUMES[@]}"; do
  VPATH="${VOLUMES[$APP]}"
  KEY="${DEPLOY_KEYS[$APP]}"

  echo "🛠 Ensuring permissions for $APP"
  POD=$(kubectl get pods -n "$NAMESPACE" -l "${LABEL_BASE},${KEY}" \
    -o jsonpath='{.items[0].metadata.name}')
  [ -z "$POD" ] && echo "[!] Pod not found for $APP, skipping." && continue

  echo " • Pod: $POD"
  echo " • Running: chown -R $USER:$GROUP $VPATH"
  kubectl exec -n "$NAMESPACE" "$POD" -- chown -R "$USER":"$GROUP" "$VPATH"
  echo " ✅ $VPATH now owned by $USER:$GROUP"
  echo
done
