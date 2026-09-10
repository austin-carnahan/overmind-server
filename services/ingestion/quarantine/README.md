# Quarantine

**Status:** PROPOSED — see [status legend](../../../design-notes/README.md#status-legend).
This repository directory contains documentation only.

Runtime quarantine lives within the appropriate typed Inbox workflow, for
example a pending-review state inside `/var/spool/overmind/media/movies` or a
quarantined romset batch under `media/romsets`. There is no separate quarantine
directory; a record may represent the pending state without making a second
payload copy.

Hold candidates for failed scans, unexpected types, questionable archives,
validation failures, unknown ROM hashes, or required review. Clients never index
quarantine. Moving a file into the inbox does not make it trusted.
