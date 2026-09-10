# Remote project work

Status: first workflow to validate after host access and storage are established.

Use a laptop IDE/SSH client to work on a project under `/mnt/substrate/projects`.
The project owns its source, documentation, temporary notes, data, and retained
outputs. It can be an independent Git checkout or a non-code collection.

Verify private access, intended user/group permissions, project execution,
repository authentication, and recovery of both committed and uncommitted work.
Give concurrent agents separate working copies and scoped execution. Do not sync
live Git working directories or databases indiscriminately between clients.

Shared notes under `/mnt/substrate/notes` may use a separate selected sync workflow.
Ordinary remote work and recovery must remain usable without Paperclip.
