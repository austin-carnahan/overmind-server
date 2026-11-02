---
name: garmin-workouts
description: "Author Garmin Connect workouts through the raw workout model (upload_workout) when the helpers can't express them: interface choice, the validated DTO structure, repeat groups and end conditions, targets, exercise catalog resolution, and read-back validation."
---

# Garmin workout authoring

Validated 2026-10-07 with Garmin MCP upload_workout and get_workout_by_id. Test ID: 1722888261. This validates Connect library read-back, not watch execution.

## Interface choice

create_strength_workout is a narrow convenience helper: rep-based exercises, each separately wrapped in its own repeat group when sets > 1, with rest. Use it when independent rep-based sets describe the intent. Use lower-level upload_workout for multi-exercise circuits, timed holds, lap-button completion, unusual sequencing, or richer conditions. These helper limits are not limits of Garmin Connect.

## Raw model

A workout has sportType and workoutSegments. A segment has segmentOrder, sportType, and workoutSteps; children are ExecutableStepDTO or RepeatGroupDTO, which itself owns workoutSteps (possibly nested). One group containing three children with numberOfIterations 2 means 1→2→3 then 1→2→3. Exercise work uses stepType ID 3, interval; group uses ID 6, repeat. Other template step types: warmup 1, cooldown 2, recovery 4, rest 5. The group MUST have numberOfIterations, endCondition {conditionTypeId: 7, conditionTypeKey: "iterations"}, and matching endConditionValue. The installed MCP upload description warns omission of ID 7 silently corrupts the repeat count. The strength-circuit template in the referenced source illustrates DTO structure but omits this required group condition: follow the stricter upload rule. For mismatched ID/key pairs, the numeric ID governs.

End condition determines completion, separate from intensity targetType. End-condition IDs: 1 lap.button; 2 time (seconds); 3 distance (meters); 4 calories; 5 power; 6 heart.rate; 7 iterations; 8 fixed.rest; 9 fixed.repetition; 10 reps; 11 training.peaks.tss. Only reps, time, lap.button, and iterations were tested in strength here; do not assume other conditions work for every sport/watch. A step with no intensity target uses targetType {workoutTargetTypeId: 1, workoutTargetTypeKey: "no.target"}. The upload description says an HR target uses ID 4 heart.rate.zone: named zone via zoneNumber 1–5, or custom bpm range via step-level targetValueOne/targetValueTwo, without zoneNumber. HR targets were not tested here.

Strength movements use exact canonical category + exerciseName keys. Unknown exerciseName can be accepted but stored empty; invalid category can return HTTP 400. Resolve against https://connect.garmin.com/web-data/exercises/Exercises.json, shaped categories[CATEGORY].exercises[EXERCISE_NAME] (47 categories when checked). Keep Austin's preferred label/cues in description. For unusual ring/band/hang work, do not guess: choose a semantically correct catalog pair or ask Austin to create the step in Connect once, then read it back with get_workout_by_id. This MCP provides no exercise lookup helper; python-garminconnect find()/resolve() are not callable here. The ~300 KB catalog exceeds convenient web_fetch limits. Refresh/filter from shell, for example:

~~~sh
curl -fsSL 'https://connect.garmin.com/web-data/exercises/Exercises.json' -o /tmp/garmin-exercises.json
python3 -c 'import json; c=json.load(open("/tmp/garmin-exercises.json"))["categories"]; print(list(c["PLANK"]["exercises"]))'
~~~

A workspace cache is optional, but refresh it from the URL before relying on it for new/unusual movements.

## Successfully uploaded test payload

This exact workout_data was passed to upload_workout and returned workout ID 1722888261. Its category/name pairs were checked in Garmin's catalog.

~~~json
{
  "workoutName": "TEST - repeat group validation",
  "description": "Validation only: two rounds of push-ups, timed plank, and lap-button air squats.",
  "sportType": {"sportTypeId": 5, "sportTypeKey": "strength_training"},
  "workoutSegments": [{
    "segmentOrder": 1,
    "sportType": {"sportTypeId": 5, "sportTypeKey": "strength_training"},
    "workoutSteps": [{
      "type": "RepeatGroupDTO", "stepOrder": 1,
      "stepType": {"stepTypeId": 6, "stepTypeKey": "repeat"},
      "numberOfIterations": 2,
      "endCondition": {"conditionTypeId": 7, "conditionTypeKey": "iterations"},
      "endConditionValue": 2,
      "workoutSteps": [
        {
          "type": "ExecutableStepDTO", "stepOrder": 1,
          "stepType": {"stepTypeId": 3, "stepTypeKey": "interval"},
          "description": "Push-ups — 8 reps",
          "endCondition": {"conditionTypeId": 10, "conditionTypeKey": "reps"},
          "endConditionValue": 8,
          "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"},
          "category": "PUSH_UP", "exerciseName": "PUSH_UP"
        },
        {
          "type": "ExecutableStepDTO", "stepOrder": 2,
          "stepType": {"stepTypeId": 3, "stepTypeKey": "interval"},
          "description": "Plank — hold 30 seconds",
          "endCondition": {"conditionTypeId": 2, "conditionTypeKey": "time"},
          "endConditionValue": 30,
          "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"},
          "category": "PLANK", "exerciseName": "PLANK"
        },
        {
          "type": "ExecutableStepDTO", "stepOrder": 3,
          "stepType": {"stepTypeId": 3, "stepTypeKey": "interval"},
          "description": "Air squats — press lap when done",
          "endCondition": {"conditionTypeId": 1, "conditionTypeKey": "lap.button"},
          "endConditionValue": 0,
          "targetType": {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target"},
          "category": "SQUAT", "exerciseName": "AIR_SQUAT"
        }
      ]
    }]
  }]
}
~~~

Read-back: strength_training, one segment, one repeat step with repeat_count 2, end_condition iterations, value 2, and three children. Push-ups: PUSH_UP/PUSH_UP, reps 8. Plank: PLANK/PLANK, time 30 seconds. Air squats: SQUAT/AIR_SQUAT, lap.button. Garmin's curated read-back numbers child orders 2, 3, 4 rather than the submitted local orders 1, 2, 3; it omits the lap-button end_condition_value (submitted 0) and does not expose no.target targetType. Hierarchy, canonical identifiers, and completion conditions persisted. Underlying target fields and watch execution are not verified. The test remains unscheduled in Austin's library, not sent to a device.

## Repeatable procedure

1. Clarify sequence, rounds, completion condition per step, and whether a library workout or calendar entry is desired. Check get_workouts for an existing duplicate.
2. Select helper or raw interface; sketch the segment/group hierarchy. Resolve exact exercise pairs; distinguish each endCondition from targetType. Start from MCP resources workout://templates/strength-circuit and workout://reference/structure when accessible, and enforce the upload description's stricter ID-7 repeat rule even if the template omits it.
3. Submit upload_workout({workout_data: ...}) and record the returned ID. Success alone proves neither semantics nor persistence.
4. Call get_workout_by_id and compare sport, segment/group nesting, repeat count, child order, category/exerciseName, descriptions, conditions/values, and target fields where exposed. Treat omitted fields as unverified rather than assuming they survived.
5. Only when asked, schedule a validated workout via schedule_workout. Scheduling creates a calendar entry, not watch delivery; Send to Device is a separate manual Connect step. Do not schedule validation tests unless specifically requested.

Primary references:
- https://github.com/Taxuspt/garmin_mcp
- https://github.com/cyberjunky/python-garminconnect/blob/master/garminconnect/workout.py
- https://github.com/cyberjunky/python-garminconnect/blob/master/README.md
- https://connect.garmin.com/web-data/exercises/Exercises.json
