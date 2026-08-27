#!/usr/bin/env bash
# Regenerate Flux bootstrap components from an exact, verified Flux release.
set -euo pipefail

version="${1:?usage: scripts/sync-flux-components.sh vX.Y.Z [output-path]}"
output="${2:-cluster/flux-system/gotk-components.yaml}"

if [[ ! "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([+-][0-9A-Za-z.-]+)?$ ]]; then
  echo "Invalid Flux release tag: $version" >&2
  exit 2
fi

case "$(uname -m)" in
  x86_64) architecture="amd64" ;;
  aarch64|arm64) architecture="arm64" ;;
  *) echo "Unsupported architecture: $(uname -m)" >&2; exit 2 ;;
esac

release="${version#v}"
archive="flux_${release}_linux_${architecture}.tar.gz"
base_url="https://github.com/fluxcd/flux2/releases/download/${version}"
temporary_directory="$(mktemp -d)"
trap 'rm -rf "$temporary_directory"' EXIT

curl --fail --location --silent --show-error \
  "${base_url}/flux_${release}_checksums.txt" \
  --output "${temporary_directory}/checksums.txt"
expected_checksum="$(python3 - "${temporary_directory}/checksums.txt" "$archive" <<'PY'
import pathlib
import sys

for line in pathlib.Path(sys.argv[1]).read_text().splitlines():
    fields = line.split()
    if len(fields) == 2 and fields[1].lstrip("*") == sys.argv[2]:
        print(fields[0])
        break
PY
)"
if [[ ! "$expected_checksum" =~ ^[0-9a-f]{64}$ ]]; then
  echo "No valid checksum found for ${archive}" >&2
  exit 1
fi

curl --fail --location --silent --show-error \
  "${base_url}/${archive}" \
  --output "${temporary_directory}/${archive}"
printf '%s  %s\n' "$expected_checksum" "${temporary_directory}/${archive}" | sha256sum --check --status

tar --extract --gzip --file "${temporary_directory}/${archive}" --directory "$temporary_directory" flux
chmod 0755 "${temporary_directory}/flux"
mkdir -p "$(dirname "$output")"
"${temporary_directory}/flux" install \
  --version "$version" \
  --namespace flux-system \
  --components-extra image-reflector-controller,image-automation-controller \
  --export > "$output"

# The output must retain the repository's required image automation components
# and identify the requested Flux distribution version.
python3 - "$output" "$version" <<'PY'
import pathlib
import sys

content = pathlib.Path(sys.argv[1]).read_text()
components = "# Components: source-controller,kustomize-controller,helm-controller,notification-controller,image-reflector-controller,image-automation-controller"
if components not in content or f"app.kubernetes.io/version: {sys.argv[2]}" not in content:
    raise SystemExit("generated Flux bundle does not match the required components/version")
PY
printf 'Wrote verified Flux %s components to %s\n' "$version" "$output"
