# Homelab GitOps Repository - Agent Guidelines

This repository manages a homelab Kubernetes cluster using Flux for GitOps. The codebase primarily consists of Kubernetes manifests organized using Kustomize, with Flux managing deployments.

## Build/Lint/Test Commands

### Kubernetes Manifest Validation
```bash
# Validate YAML syntax for all manifests
find apps/ -name "*.yaml" -type f | xargs yamllint

# Validate Kustomize builds
for app in apps/*/; do
  if [ -f "${app}kustomization.yaml" ]; then
    kustomize build "$app" --load-restrictor LoadRestrictionsNone
  fi
done

# Validate specific app
kustomize build apps/journiv --load-restrictor LoadRestrictionsNone

# Check Flux reconciliation status
flux get kustomizations -A
flux get sources -A
```

### Helm Chart Validation
```bash
# Lint Helm releases
helm lint apps/n8n/ --strict --values-file <(echo '{}')
```

### Container Image Building
```bash
# Build custom Docker images (examples)
docker build -t ghcr.io/tomythical/whisper:latest apps/n8n/whisper/
docker build -t ghcr.io/tomythical/instaloader:latest apps/n8n/instaloader/
```

### Secret Management
```bash
# Validate ExternalSecret configurations
kubectl apply --dry-run=client -f apps/journiv/external-secret.yaml
```

## Code Style Guidelines

### General Structure
- **Repository Organization**: Apps under `apps/`, cluster configuration under `cluster/`, infrastructure under `infra/`
- **Namespace Strategy**: Each major application gets its own namespace
- **Resource Files**: Use `.yaml` extension, not `.yml`

### YAML/Manifest Formatting
- **Indentation**: 2 spaces (no tabs)
- **Quotes**: Use double quotes for string values in manifests
- **Ordering**: Follow standard Kubernetes manifest ordering:
  1. apiVersion, kind, metadata
  2. spec
  3. status (when applicable)
- **Annotations/Labels**: Include standard labels for Flux/app management
- **Comments**: Use sparingly, mainly for non-obvious configurations

### Naming Conventions
- **Resources**: Use kebab-case for resource names (e.g., `homepage`, `media-server`)
- **Labels**: Use `app.kubernetes.io/*` label scheme where applicable
- **ConfigMaps/Secrets**: Name after their purpose (e.g., `jellyfin-config`, `journiv-secrets`)
- **PersistentVolumes**: Use descriptive names with `-pvc` suffix (e.g., `mediaserver-rwo-pvc`)

### Kustomize Usage
- **Structure**: Each app has its own directory with `kustomization.yaml`
- **Base/Overlays**: Use single-level structure with all resources in app directory
- **Common Labels**: Apply namespace and common labels in kustomization
- **Dependencies**: Specify namespace in kustomization.yaml

### Security Best Practices
- **Security Context**: Always include pod/container securityContext
- **Non-root**: Run containers as non-root user (UID 1000)
- **Resource Limits**: Define requests/limits for all containers
- **Secrets**: Use ExternalSecrets with Doppler for secret management
- **Probes**: Include readiness/liveness probes for all services

### Error Handling & Validation
- **Dry-run**: Always test manifests with `--dry-run=client` before applying
- **Health Checks**: Implement comprehensive health endpoints for custom services
- **Resource Validation**: Use `kubectl apply --validate=true`
- **Flux Validation**: Check Flux reconciliation logs for issues

### Import/Export Patterns
- **ConfigMaps**: Use `envFrom` for environment variables
- **Secrets**: Reference via `secretKeyRef` or `envFrom`
- **Volumes**: Mount ConfigMaps as files for configuration
- **Cross-namespace**: Use fully qualified names for cross-namespace references

### Type Definitions
- **API Versions**: Use stable API versions when available
- **Resource Types**: Prefer Deployment over StatefulSet unless stateful required
- **Service Types**: Use ClusterIP unless external access needed (then Ingress)

### Flux-Specific Guidelines
- **Helm Releases**: Use HelmRelease CRDs for Helm charts
- **GitRepository**: Configure with 1-minute interval for rapid updates
- **Kustomizations**: Use 10-minute intervals with prune enabled
- **Dependencies**: Define explicit `dependsOn` relationships
- **Source Control**: All manifests must be in Git (no manual kubectl apply)

### Custom Container Development
- **Base Images**: Use slim variants (e.g., `python:3.14-slim`)
- **Health Endpoints**: Include `/health` endpoint for readiness/liveness probes
- **Resource Efficiency**: Request minimal resources, set appropriate limits
- **Logging**: Use structured logging with appropriate log levels

### Monitoring & Observability
- **ServiceMonitors**: Include for Prometheus scraping when applicable
- **Labels**: Include `release: kube-prometheus-stack` for ServiceMonitors
- **Metrics**: Expose standard metrics endpoints on port 9090
- **Logging**: Ensure logs are captured by cluster logging solution

### Deployment Patterns
- **Rolling Updates**: Use `RollingUpdate` strategy with revision history limits
- **Replica Count**: Typically 1 replica for homelab services
- **Storage**: Use `local-path` storage class for local persistence
- **Networking**: Use Tailscale for secure external access via Ingress

### Testing Strategy
- **Integration Testing**: Test manifests in development cluster first
- **Validation**: Use `kustomize build` to validate manifests
- **GitOps**: Rely on Flux for deployment validation
- **Rollback**: Use Git revert for rollbacks (never kubectl rollback)

## Development Workflow

1. **Local Testing**: Build and validate manifests locally
2. **Git Commit**: Commit changes to feature branch
3. **PR Creation**: Create pull request with description of changes
4. **Automated Validation**: Wait for Flux to reconcile changes
5. **Monitoring**: Check application health and logs
6. **Documentation**: Update relevant documentation if needed

## Tool Configuration

- **Renovate**: Automated dependency updates (see renovate.json)
- **Flux**: GitOps operator with 1-minute sync interval
- **Kustomize**: Manifest management and overlays
- **External Secrets**: Secret management with Doppler integration
- **Tailscale**: Secure networking and Ingress controller

## Common Commands Reference

```bash
# Apply manifests locally (testing)
kustomize build apps/journiv | kubectl apply -f -

# Check Flux status
flux get kustomizations
flux logs --kind=Kustomization --name=apps

# View application logs
kubectl logs -n journiv deployment/journiv-app

# Port forward for local testing
kubectl port-forward -n media-server svc/jellyfin 8096:8096

# Check resource usage
kubectl top pods -A
```

## Notes for AI Agents

- This is a production homelab - test changes carefully
- Always follow GitOps principles - no manual kubectl apply
- Secrets are managed via ExternalSecrets - never commit secrets
- Storage uses local-path provisioner - ensure PVCs are appropriate size
- Networking uses Tailscale - ensure Ingress configurations are correct
- Monitor resource usage - homelab has limited resources. This is a running on a single node 4cpu and 16Gb machine

## Current Architecture Analysis
### Repository Structure
- Repository Organization: Apps under apps/, cluster configuration under cluster/, infrastructure under infra/
- GitOps Pattern: Flux manages deployments with Kustomize overlays
- Source Control: All manifests are versioned in Git, no manual kubectl apply

### Infrastructure Components
- Flux Sources: Managed in infra/flux-sources/ (GitRepository/HelmRepository resources)
- Infrastructure Apps: Located in infra/ directory (MetalLB, Tailscale, local-path-provisioner, etc.)
- Namespace Management: Namespace definitions in infra/namespaces/
- Cluster Configuration: Flux kustomizations in cluster/flux-system/

### Application Deployment Patterns
- App Structure: Each application has its own directory under apps/ with kustomization.yaml
- Namespace Strategy: Applications deployed to specific namespaces (e.g., media-server, journiv)
- Resource Organization: All related manifests (deployments, services, configs) in app directory
- Common Patterns: Use of ConfigMaps for configuration, PersistentVolumeClaims for storage

### Networking & Security
- Tailscale Integration: Currently uses Tailscale operator for secure networking (Helm chart in infra/tailscale/)
- External Access: Tailscale provides VPN-based secure access to services
- Pod Security: Namespace-level pod security labels applied
- External Secrets: Doppler integration for secret management via ExternalSecrets

### Flux Configuration
- Flux System: Main Flux configuration in cluster/flux-system/
- Kustomization Hierarchy:
  - infra.yaml → manages infrastructure components
  - apps.yaml → manages application deployments
  - namespaces.yaml → manages namespace creation
- Sync Intervals: Infrastructure (10m), applications (10m) with dependencies defined
- Source References: All kustomizations reference the main GitRepository source

### Resource Management
- Cluster Resources: Single node with 4 CPU cores and 16GB RAM
- Storage: Uses local-path storage class provisioner
- Monitoring: kube-prometheus-stack installed for monitoring
- Load Balancing: MetalLB configured for LoadBalancer services

### Key Integration Points
1. External Secrets: Secrets managed via Doppler, referenced via ExternalSecret CRDs
2. Helm Charts: Some components use Helm (Tailscale operator, metrics-server)
3. Kustomize Overlays: Most applications use raw YAML with Kustomize patches
4. Flux Dependencies: Explicit dependsOn relationships ensure proper deployment order
5. Pod Security: Namespace labels enforce pod security standards
