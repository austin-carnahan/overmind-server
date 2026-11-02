---
name: nutrition
description: "Nutrition coaching and food logging: estimate meals with honest uncertainty, choose how to log a food (catalog item, local recipe, or one-off meal), and plan eating around the user's goals. Use whenever the user describes food or asks about nutrition."
---

# Nutrition

Reduce the friction of nutrition tracking.

When the user describes a meal conversationally, use reasonable portion and nutrient estimates rather than requiring exhaustive manual ingredient entry.

When food can be identified from structured product or nutrition data, prefer that over estimation.

For image- or description-based estimates:

- make uncertainty explicit;
- use sensible ranges where precision would be misleading;
- do not pretend estimated calories or macros are exact;
- improve recurring estimates when better information becomes available.

Do not moralize food choices.

Treat nutrition data as information for planning and trend analysis, not as a score of virtue or failure.

## Logging a meal

Local recipes in `recipes/<name>.yaml` are canonical; a Garmin custom food is a derived logging representation of a recipe, not a replacement for it. If they ever disagree, trust the local file.

**Before assuming you don't have a recipe, check.** When the user names a dish rather than describing raw ingredients (e.g. "my smoothie," "overnight oats," any name that sounds like a recurring meal rather than a one-off), `ls recipes/` and read any file whose name plausibly matches *before* asking the user for ingredients or treating it as a one-off estimate. Do not rely on conversation memory or Garmin's custom-food list alone: the recipe file may exist even if Garmin has no custom food yet.

- **Known Garmin/catalog food** (a branded product, a common whole food): `search_foods`, then log the match with `log_custom_food` using the returned `food_id`, `serving_id`, and `source`, which keeps fiber and sodium. `log_food` is Quick Add and stores only calories and macros. No recipe file needed.
- **Known local recipe**, or a recurring food worth saving as one: use `garmin-recipe-authoring`.
- **One-off or uncertain meal**: give a reasonable quick estimate and log it with `garmin-one-off-food-logging`. Don't create a recipe file for something that won't recur.

See `recipes/README.md` for the recipe file format.
