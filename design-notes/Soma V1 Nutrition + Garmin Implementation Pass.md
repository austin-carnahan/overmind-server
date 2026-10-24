Refine Soma's Garmin/nutrition workflow into a usable V1. Keep this pass practical and compact; prefer existing Garmin/OpenClaw capabilities over new services or infrastructure.

## Goals

By the end of this pass, Soma should be able to:

- maintain reusable local recipes;
- turn recipes into Garmin-compatible custom foods;
- log ordinary meals with low friction;
- read and, when explicitly requested, update calorie/macro goals;
- create/schedule workouts in Garmin and verify they reach the watch;
- perform useful native analysis across Garmin nutrition, expenditure, weight, body-composition, and training data.

Do not add Grafana, a separate nutrition service, a new database, or a custom analytics backend during this pass.

## 1. Establish recipe persistence and conventions

Create a small persistent recipe area in Soma's OpenClaw workspace, e.g.:

```text
recipes/
  README.md
  <recipe-name>.yaml
```

Use one structured file per recipe.

Each recipe should support:

- name;
- ingredient list with quantities/units;
- total batch yield;
- serving definition;
- total nutrition;
- per-serving nutrition;
- useful nutrients beyond basic macros where available, especially fiber and sodium;
- Garmin custom-food ID/name if one has been created;
- notes about uncertainty or ingredient assumptions when relevant.

Keep the local recipe definition canonical. Garmin custom foods are derived logging representations, not the source recipe.

Add a concise section to Soma's `AGENTS.md` describing the recipe and food-logging workflow so Soma knows when to use local recipes, Garmin catalog foods, and quick estimates.

## 2. Expand and verify Garmin nutrition tools

Inspect the live Garmin MCP tool catalog and enable the useful missing nutrition tools if available.

Priorities include:

```text
get_custom_foods
get_custom_food_serving_units
create_custom_food
log_custom_food
update_custom_food
upsert_and_log
get_nutrition_daily_settings
set_nutrition_daily_settings
```

Do not assume tool names solely from documentation; verify them against the deployed MCP.

Avoid enabling destructive/admin-style tools unless they are actually useful.

## 3. Define and test food-logging workflows

Develop a simple decision flow Soma can follow:

```text
known Garmin/catalog food
→ search + structured log

known local recipe
→ read recipe → use/update Garmin custom food → log appropriate portion

recurring food not yet stored
→ estimate/derive nutrition → save local recipe or reusable custom food as appropriate

one-off or uncertain meal
→ reasonable quick estimate → log with uncertainty understood
```

Prefer useful approximation over burdensome manual tracking, but do not present estimates as exact.

Test several realistic cases, including:
- a simple packaged/catalog food;
- a conversationally described meal;
- a reusable recipe such as a smoothie;
- a non-whole serving/partial portion.

Refine the workspace convention or `AGENTS.md` only where testing exposes a real gap.

## 4. Test calorie and macro goal management

Verify Soma can read the current Garmin nutrition targets.

Test whether the MCP can update:
- daily calorie target;
- protein target;
- carbohydrate target;
- fat target.

Only change real goals when explicitly requested.

Verify all resulting values in Garmin Connect after writing them.

Document any Garmin constraints, normalization behavior, or mismatches between target calories and macro-derived calories.

## 5. Test workout creation end-to-end

Have Soma create a simple structured workout through the Garmin MCP.

Then:
1. create it in Garmin Connect;
2. schedule it;
3. sync the Forerunner;
4. verify it appears correctly on the watch;
5. confirm important structure survives, such as exercise/step order, sets/reps, rest, duration, or other applicable fields.

Document the minimum reliable workflow for future workout creation.

## 6. Test Soma's native analysis capability

Before building a separate analytics layer, test how useful Soma is with the Garmin data already available.

Examples:

- calorie intake vs estimated expenditure;
- 7/14/28-day energy-balance trends;
- rolling weight trend;
- body-fat trend, treated cautiously;
- protein/macronutrient consistency;
- training frequency and recent activity;
- whether observed weight change broadly agrees with estimated energy balance;
- obvious missing-data or logging inconsistencies.

The goal is to determine what Soma can already do well as an LLM over Garmin MCP data.

Prefer rolling trends over single-day interpretation. Treat wearable expenditure, body-fat estimates, and food estimates as noisy signals rather than exact measurements.

## Scope boundaries

Defer for later:

- USDA or another dedicated ingredient nutrition service;
- Grafana or another dashboard;
- a custom nutrition database;
- a separate analytics pipeline;
- richer recipe applications;
- automated goal-changing behavior.

## Finish

Report back with:

- files/conventions created;
- `AGENTS.md` additions;
- Garmin tools enabled;
- tested food-logging workflows;
- recipe/custom-food behavior;
- calorie/macro goal read/write results;
- workout creation/watch-sync results;
- examples of native analysis Soma handled well or poorly;
- any Garmin limitations that materially affect the design;
- recommended next steps only where actual testing revealed a need.