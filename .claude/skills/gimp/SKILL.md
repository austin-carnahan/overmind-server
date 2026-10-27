---
name: gimp
description: "General GIMP 3.2 knowledge for editing a live document through the GIMP Agent MCP tools: layers, groups and blend modes, selections, masks and channels, paths, color adjustments, GEGL filters, transforms, PDB procedure calls, rendering and measuring results, and saving XCF or exporting. Use for any GIMP or .xcf task, including when another skill (e.g. interior-scene-editing) does the domain reasoning. Not for model inference (segmentation, inpainting): those are Cerebrate tools."
license: Apache-2.0
metadata:
  upstream: "LevyBytes/AI-SKILL-gimp @ 10b82859 (adapted; see UPSTREAM.md)"
---

# GIMP

Edit the user's real GIMP document through the GIMP Agent MCP tools (`gimp_*`; Buckminster sees them as
`gimp_gimp_*`, Claude Code as `mcp__gimp__gimp_*`). Everything here works through those tools unless a
section says it is environment-dependent.

## Working rules

1. **Start with `gimp_status`**, then `gimp_list_images`. Address images and layers by integer id from
   `gimp_image_info`, which returns the whole layer tree (groups and their children). Never guess an id,
   and never touch an image you weren't asked to work on. Ids change when a document is reopened:
   find layers again by name.
2. **Keep the document editable.** New content goes on new, named layers; related layers go in a group;
   repairs go in the group of what they repair. Use masks rather than erasing, and pass-through groups
   when a member uses a blend mode meant for what's below. Don't merge, flatten or apply a mask unless
   the result must be baked. Keep the original photo as a hidden, untouched layer.
3. **Look, then measure.** `gimp_render` after each meaningful step (`region` to zoom, `layer_id` to
   isolate one layer). A render answers "does it look right"; `gimp_measure` answers "is it correct"
   (`bbox` for placement, `color` for a pixel, `histogram`/`dominant` for tone). Before a risky edit take
   `gimp_snapshot`; `gimp_render_compare` then shows before, after and a pixel diff.
4. **One logical edit, one undo step.** `gimp_edit_batch` groups up to 100 `layer`/`select`/`text`/
   `path`/`layer_mask`/`apply_filter` steps under one Ctrl+Z (not automatic rollback). PDB calls can't
   go in a batch; `gimp_pdb_call` makes each call its own undo group.
5. **Discover before calling.** `gimp_pdb_search` then `gimp_pdb_describe` before any PDB procedure you
   haven't used; `gimp_filter_search`/`gimp_filter_describe` before a GEGL filter. Menu labels are not
   procedure names.
6. **Save the XCF master** (`gimp_export` to `.xcf`); export delivery formats separately. Don't overwrite
   an existing file unless asked.
7. **Finish with evidence:** the XCF path, exports, which layers remain editable, what you measured, and
   anything still needing a human look.

A flattened image (PNG, JPEG, a generated picture) has no semantic layers. Segmentation can lift out
visible regions, but hidden pixels aren't there: decomposing a flat image is always a partial recovery.

## Context router

| Topic | Open when | Read |
| --- | --- | --- |
| Tool surface | Choosing which `gimp_*` tool does a job, calling PDB procedures, known gaps and failure modes. **Read first.** | [Tool surface](references/tool-surface.md) |
| PDB calls | Calling a procedure through `gimp_pdb_call`: argument conventions and verified examples for layers, groups, selections, transforms, colors. | [PDB calls](references/pdb-calls.md) |
| Layers and Layer Modes | Organizing layers or groups, opacity and alpha, blend modes (Multiply, Divide, Pass through, ...). | [Layers and Layer Modes](references/layers-and-modes.md) |
| Selections | Creating, combining, feathering, growing or inverting selections. | [Selections](references/selections.md) |
| Layer Masks, Channels, and Quick Mask | Layer masks, selections stored in channels. | [Layer Masks, Channels, and Quick Mask](references/masks-and-channels.md) |
| Paths | Bezier paths, path to/from selection, stroking. | [Paths](references/paths.md) |
| Colors and Adjustments | Levels, curves, hue/saturation, desaturate, ICC profiles. | [Colors and Adjustments](references/colors-and-adjustments.md) |
| Filters | Filter categories and GEGL operations. | [Filters](references/filters.md) |
| File Formats and Export | Opening, saving XCF, exporting PNG/JPEG. | [File Formats and Export](references/file-formats-and-export.md) |
| Tools Overview | Naming a GIMP tool or its shortcut (when explaining to a person). | [Tools Overview](references/tools-overview.md) |
| Interface and Workflow | GIMP's windows, docks, undo history, image mode and encoding (when explaining to a person). | [Interface and Workflow](references/interface-and-workflow.md) |

Menu paths and shortcuts in these references describe GIMP's interface, for explaining to a person or
finding the matching operation; agents act through the tools.

Check [docs.gimp.org](https://docs.gimp.org/) when a reference and the installed GIMP disagree, and trust
`gimp_pdb_describe` over any example.
