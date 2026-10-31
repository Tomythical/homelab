# Listenarr

Flux deploys this app through the parent media-server Kustomization. It follows
Sonarr/Radarr's single-replica Recreate strategy, shared media storage, and
Tailscale ingress pattern. The image is pinned to a version and digest because
upstream currently publishes only canary releases.

## Initial Setup

After merging and Flux reconciliation:

1. Open `https://listenarr.ratfish-company.ts.net` and configure authentication.
2. Set the audiobook library root to `/data/media/audiobooks`.
3. Configure SABnzbd using host `sabnzbd.media-server.svc.cluster.local`, port
   `8080`, and URL base `/sabnzbd`, with its existing API key. Use a dedicated
   audiobook category that downloads beneath `/data/sabnzbd/complete`.
4. Add indexers in Listenarr and test the download/import workflow. Do not assume
   Prowlarr application sync supports Listenarr.

Both downloads and the library use the existing `mediaserver-rwo-pvc` mounted
once at `/data`, keeping paths consistent with SABnzbd and allowing hardlinks
within that filesystem. The init container creates only the audiobook folder;
it does not recursively change permissions on the shared media library.

The separate 1Gi config PVC at `/app/config` persists SQLite, authentication,
cache, and logs. Use SABnzbd for downloads: Listenarr's direct-download feature
stages files on this small config volume and can exhaust it. Back up this PVC
before upgrading the pre-release application.
