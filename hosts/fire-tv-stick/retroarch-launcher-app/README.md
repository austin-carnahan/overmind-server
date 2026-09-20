# retroarch-launcher-app

A minimal trampoline Android app. Its only job: launch RetroArch's
`RetroActivityFuture` with `-e CONFIGFILE
/storage/emulated/0/RetroArch/config/retro_fix2.cfg`, then close itself.
This exists because a plain tap on RetroArch's own icon has no way to
pass that argument, and RetroArch 1.22.2 needs it — see the "RetroArch
OK-button fix" section in `../README.md` for why.

No Gradle, no Android Studio project — built directly with the Android
SDK command-line tools, since the whole app is one Activity and a
manifest.

## Rebuild

Requires the Android SDK build-tools and a JDK (both come with Android
Studio; this was built against build-tools 34.0.0 and `android-29.jar`,
but any reasonably recent version of either should work).

```sh
cd retroarch-launcher-app
ANDROID_JAR=~/Library/Android/sdk/platforms/android-29/android.jar
BUILD_TOOLS=~/Library/Android/sdk/build-tools/34.0.0

# 1. Compile the Java source
mkdir -p build/classes
javac -source 8 -target 8 -bootclasspath "$ANDROID_JAR" \
  -d build/classes src/com/homeserver/retroarchlaunch/TrampolineActivity.java

# 2. Convert to DEX
"$BUILD_TOOLS/d8" --output build/ \
  build/classes/com/homeserver/retroarchlaunch/TrampolineActivity.class \
  --lib "$ANDROID_JAR"

# 3. Compile + link resources and manifest into an unsigned APK
mkdir -p build/compiled_res
"$BUILD_TOOLS/aapt2" compile --dir res -o build/compiled_res/res.zip
"$BUILD_TOOLS/aapt2" link -o build/app_unsigned.apk -I "$ANDROID_JAR" \
  --manifest AndroidManifest.xml -R build/compiled_res/res.zip --auto-add-overlay

# 4. Add the DEX into the APK
cp build/app_unsigned.apk build/app_with_dex.apk
(cd build && zip app_with_dex.apk classes.dex)

# 5. Zipalign + sign (self-signed; the key just needs to be consistent
#    across installs of *this* app, it doesn't need to match RetroArch's)
keytool -genkeypair -v -keystore debug.keystore -alias retroarch-fix \
  -keyalg RSA -keysize 2048 -validity 10000 -storepass android -keypass android \
  -dname "CN=Fire TV Stick Provisioning, OU=Home, O=Home, L=Home, S=Home, C=US"
# (skip keytool if debug.keystore already exists locally -- it's gitignored)

"$BUILD_TOOLS/zipalign" -f -p 4 build/app_with_dex.apk build/app_aligned.apk
"$BUILD_TOOLS/apksigner" sign --ks debug.keystore --ks-pass pass:android \
  --key-pass pass:android --ks-key-alias retroarch-fix \
  --out build/RetroArchLauncher_signed.apk build/app_aligned.apk

# 6. Install
adb install build/RetroArchLauncher_signed.apk
```

If the path to the fixed config (`retro_fix2.cfg`) ever changes,
update the `CONFIGFILE` extra in `src/.../TrampolineActivity.java` and
rebuild.
