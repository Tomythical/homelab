# Monitoring Notifications

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
