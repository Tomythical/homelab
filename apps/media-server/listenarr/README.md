# Listenarr

Flux deploys this app through the parent media-server Kustomization. It follows
Sonarr/Radarr's single-replica Recreate strategy, shared media storage, and
Tailscale ingress pattern. The image is pinned to a version and digest because
upstream currently publishes only canary releases.

## Initial Setup

After merging and Flux reconciliation:

1. Open `https://listenarr.ratfish-company.ts.net` and configure authentication.
2. Change the default root folder from `/app` to `/data/media/audiobooks`, with
   filesystem case sensitivity set to `Sensitive`. Set the output path to the
   same directory before adding books. The upstream `/app` default is not
   writable by the non-root container user.
3. Configure SABnzbd using host `sabnzbd.media-server.svc.cluster.local`, port
   `8080`, and URL base `/sabnzbd`, with its existing API key. Use a dedicated
   audiobook category that downloads beneath `/data/sabnzbd/complete`.
4. Add indexers in Listenarr and test the download/import workflow. Do not assume
   Prowlarr application sync supports Listenarr.

Both downloads and the library use the existing `mediaserver-rwo-pvc` mounted
once at `/data`, keeping paths consistent with SABnzbd and allowing hardlinks
within that filesystem. The init container creates only the audiobook folder;
it does not recursively change permissions on the shared media library.

If books were added before correcting the default root, update their stored
destinations too. On canary-1.5.10, retrying a blocked import can leave it stuck
at `ImportPending`; manual import with the `copy` action can register the
existing download without deleting its source. Verify the book match first.

The separate 1Gi config PVC at `/app/config` persists SQLite, authentication,
cache, and logs. Use SABnzbd for downloads: Listenarr's direct-download feature
stages files on this small config volume and can exhaust it. Back up this PVC
before upgrading the pre-release application.
