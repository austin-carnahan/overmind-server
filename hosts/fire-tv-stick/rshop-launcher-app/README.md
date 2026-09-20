# rshop-launcher-app

A minimal trampoline Android app whose only job is to launch R-Shop's
`MainActivity` and finish. Unlike `retroarch-launcher-app/`, this one
passes **no special launch arguments** -- R-Shop needs none. It exists
solely because R-Shop's own manifest doesn't declare
`LEANBACK_LAUNCHER`, so it has no tile on Fire TV's actual TV-apps home
row (it's still reachable via Projectivy's "Mobile Apps"/All Apps list
under its own icon). This gives it a proper one.

See the "R-Shop bugs and workarounds" section in `../README.md` for the
full story, including the separate (and more important) onboarding
bypass, which this launcher has nothing to do with.

## Rebuild

Identical process to `retroarch-launcher-app/` -- same toolchain, same
lack of Gradle/Android Studio project, just a different target component
(`com.retro.rshop/com.retro.rshop.MainActivity`, no extras) and package
name (`com.homeserver.rshoplaunch`). See that directory's README for the
full step-by-step; only `AndroidManifest.xml` and
`TrampolineActivity.java` differ.
