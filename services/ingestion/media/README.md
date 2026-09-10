# Media validation and promotion

**Status:** PROPOSED — see [status legend](../../../design-notes/README.md#status-legend).
No automatic import is implemented.

1. Download completes in Transmission (see [transmission](../../transmission/README.md));
   once seeding-safe, treat it as an ordinary arrival under `/var/spool/overmind/media/movies`
   or `media/tv`.
2. Keep candidates quarantined/pending review within that same media inbox folder.
3. Scan with ClamAV, inspect archives/types/sidecars, and reject unexpected payloads.
4. Run [validate-media.sh](validate-media.sh) as a container probe component.
5. Classify and import reviewed movies/TV into `/mnt/library/movies` or `tv`.
6. Add validated subtitles and refresh clients only after promotion.

Radarr/Sonarr/Bazarr are candidate integrations. Copy and verify initially.
Hardlinks require testing a compatible importer mount view; using one SSD with
separate bind mounts is insufficient. Preserve seeding downloads until eligible
for removal, and keep failed imports isolated.
Prevent post-validation writes from bypassing the gate through a shared inode.
The probe alone neither proves safety nor implements promotion.
