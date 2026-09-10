# Travel ROM Sync

Goal: maintain a small offline cache on the Fire TV rather than a second canonical library.

Future interface idea:

```text
travel-rom-sync <device>
```

It should sync only titles tagged/selected for travel and preserve matching save files where desired.

No sync command is implemented. Define save ownership and conflict handling before bidirectional updates; selected ROM copies are client caches.
