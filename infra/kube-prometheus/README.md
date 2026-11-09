# Monitoring

Alertmanager sends firing and resolved alerts to Handler using its native
Alertmanager webhook. Watchdog is excluded because it is a continuous heartbeat,
not an actionable incident. Other existing cluster alerts are forwarded too.

## Credentials

Before deploying, add `HANDLER_ALERTMANAGER_WEBHOOK_URL` to the Doppler
project/config accessible to the `doppler-auth-api` ClusterSecretStore. Set its
value to the complete `webhook_url` from the downloaded Handler credentials file,
including its query parameters. Do not commit that URL or the credentials file.

External Secrets creates `monitoring/handler-alertmanager-webhook`; Alertmanager
mounts its `url` key as a file. Missing credentials will prevent the updated
Alertmanager pod from starting, so populate Doppler before deployment.

## Grafana Login

Grafana's bootstrap credentials come from the `monitoring/grafana-admin` Secret.
External Secrets sets `admin-user` to `tomythical` and reads `admin-password` from
`GRAFANA_ADMIN_PASSWORD` in the Doppler project/config accessible to
`doppler-auth-api`. Use a unique, randomly generated password stored in a password
manager. Never commit it or paste it into shell commands.

Before merging/deploying these manifests:

1. Set `GRAFANA_ADMIN_PASSWORD` in Doppler. A missing value prevents the new Secret
   from being created and can prevent Grafana from starting after deployment.
2. Sign in to https://grafana.ratfish-company.ts.net with the existing account.
   In the profile settings, change the username to `tomythical` and change the
   password to the same value stored in Doppler.
3. Verify the new login in a private browser window before closing the existing
   session.
4. Deploy through Git/Flux, then verify the ExternalSecret and Grafana pod:

```bash
kubectl -n monitoring get externalsecret grafana-admin
kubectl -n monitoring wait --for=condition=Ready externalsecret/grafana-admin --timeout=120s
kubectl -n monitoring get pods -l app.kubernetes.io/name=grafana
```

Grafana stores existing accounts in its persistent database. Changing this
Secret or restarting Grafana does not update an existing username or password;
the Secret only controls initial account creation on an empty database. Future
password rotations must update both the Grafana account and Doppler. If the
existing login is unavailable, use Grafana's admin password recovery procedure
against the existing database. Do not delete its PVC to reset credentials.

## Direct Dashboard Editing

The Grafana sidecar dashboard provider enables `allowUiUpdates`, so existing
provisioned dashboards can be edited and saved through the UI or HTTP API.
Edits are stored in Grafana's persistent database, not in Git or the source
ConfigMaps. A changed provisioning source (for example, a chart upgrade) can
overwrite those edits. Export important customized dashboards before upgrading.

## Disk Alerts

The Talos persistent system filesystem is exported by node-exporter as `/var`.
This filesystem also backs bulk media storage. Additional alerts fire below
650 GB available for 10 minutes (warning), below 500 GB for 5 minutes (critical),
and when Kubernetes reports disk pressure for 2 minutes. Thresholds use decimal
GB. Existing chart filesystem and inode alerts remain enabled. Chart inhibition
rules suppress the matching warning while its critical alert is firing.

These thresholds intentionally warn before the node's approximately 300 GB
free-space eviction threshold. They do not stop downloads or reclaim space.

## Verification

After Flux deploys the changes:

1. Verify the ExternalSecret is Ready and Alertmanager is healthy.
2. Verify the `homelab-disk` rules are loaded in Prometheus.
3. Send a controlled test alert through Alertmanager, then resolve it. Confirm
   both notifications arrive with the iPhone locked and check Focus settings.
4. Check Alertmanager notification failures and Handler delivery history.

No emergency/repeating-until-acknowledged behavior is configured here. Configure
Handler priority behavior separately after normal delivery has been tested.
In-cluster alerting cannot report a dead node; an external missing-heartbeat
monitor remains necessary for that coverage.
