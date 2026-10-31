# Audiobookshelf

Flux deploys Audiobookshelf through the media-server Kustomization. Listenarr
manages downloads and imports; Audiobookshelf provides the listening interface.

## Initial Setup

After the changes are pushed and Flux reconciles:

1. Open `https://audiobookshelf.ratfish-company.ts.net` and create a
   password-protected administrator account before sharing access.
2. Add a book library with folder `/data/media/audiobooks`, then scan it.
3. Keep `storeMetadataWithItem` and `storeCoverWithItem` disabled (the defaults).
   Audiobookshelf stores its generated metadata and covers on its own PVC.
4. Check book matches before fetching metadata. In particular, verify the
   existing Kingdom of Ash download, which was associated with Throne of Glass
   in Listenarr, before trusting its imported folder and filename.

Only `media/audiobooks` from the existing `mediaserver-rwo-pvc` is mounted,
read-only, at the same path used by Listenarr. This lets Audiobookshelf index
and stream the books without modifying them or exposing the download folders.
Do not enable uploads, source-file tagging, deletion, or podcast downloads;
these require writable media storage and are outside this deployment's scope.

The 1Gi config PVC contains SQLite, accounts, settings, and listening progress.
The separate 5Gi metadata PVC contains covers, metadata, backups, and streaming
scratch files. Back up both PVCs. Temporary OS files use a disk-backed `emptyDir`.
The image includes FFmpeg, so no additional transcoding container is required.

The initial CPU request is 100m, with a one-core limit for indexing/transcoding.
Memory requests 512Mi with a 1Gi limit. Measure a full library scan and concurrent
playback before adjusting these values. The server runs as UID/GID 1000 with a
read-only root filesystem; `/config`, `/metadata`, and `/tmp` remain writable.
