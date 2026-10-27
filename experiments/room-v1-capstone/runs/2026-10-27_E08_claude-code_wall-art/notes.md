# E08 — Wall-mounted decoration (2026-10-27_E08_claude-code_wall-art)

## Attempt

The public-domain framed landscape (W. M. Lemos) hung on the back wall's large blank stretch, right of the
small window, using E06's method: the window trim as the wall's reference rectangle.

## Observed

Attempt 1 hung it in perspective but stretched (about 2.2:1 instead of 1.58). With the window's real
proportions (1.61, measured), attempt 2 has the right shape: the nearer right edge is taller, the verticals
lean exactly as the camera's tilt predicts, and the frame sits flush with a faint shadow.

## What helped or failed

- **Measure the reference rectangle's true aspect, don't guess it:** its own two vanishing points plus the
  focal length give it. The angle between its recovered edge directions (85° here) is a sanity check.
- **The whole-room camera stays unreliable** on the back wall: the ceiling and baseboard lines disagree about
  that wall's vanishing point.
- **SAM 2.1** gave several frame-shaped candidates; the largest with its holes ignored is the frame.

## Reusable rule or open question

Placing flat items on a wall: reference rectangle → true aspect → place in its coordinates → transform-
perspective. Apply the measured aspect retroactively to E06's curtains (1.57, not 1.3).
