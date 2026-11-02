---
name: garmin-recipe-authoring
description: Create or revise a reusable batch recipe in the local recipes directory, sync its per-serving Garmin custom food, and log a known recipe when asked.
---

# Garmin recipe authoring

1. Check `recipes/` for a plausible existing dish and read its file before estimating or creating a duplicate. The local YAML is canonical; follow `recipes/README.md` for fields and the known-recipe logging path. A packaged/catalog food needs no recipe; a genuinely one-off composite belongs in `garmin-one-off-food-logging`.
2. For a new or revised batch, record the user's ingredients and yield, calculate `nutrition_total`, then divide by servings for `nutrition_per_serving`. Document consequential assumptions (ingredient form, cup-to-gram conversion, added salt/oil, yield uncertainty); mark placeholders as uncertain. Do not treat a recipe-creation request as permission to log a meal.
3. Sync a derived Garmin custom food per serving, including fiber and sodium when reasonably estimated. **Garmin `createCustomFood` rejects fractional calories** (verified HTTP 400 for 221.5 kcal even though the tool schema accepts a number). Use a whole-number kcal in Garmin; where the recipe's calories are estimates, round the per-serving value and keep the local batch total equal to that rounded value times servings. For authoritative values that cannot be changed, preserve the local figure and document Garmin's rounding difference. Do not let the derived food override the local recipe.
4. If a creation response is an unexpected error string or otherwise ambiguous, inspect the raw result and search `getCustomFoods` before retrying to avoid duplicates. Save the returned food and serving IDs in the YAML. Read back the custom food and compare serving size, calories, macros, fiber, and sodium with the canonical file; log a serving only when requested and verify the meal afterward.
