package com.homeserver.retroarchlaunch;

import android.app.Activity;
import android.content.ComponentName;
import android.content.Intent;
import android.os.Bundle;
import android.widget.Toast;

public class TrampolineActivity extends Activity {
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        try {
            Intent intent = new Intent();
            intent.setComponent(new ComponentName(
                "com.retroarch.ra32",
                "com.retroarch.browser.retroactivity.RetroActivityFuture"
            ));
            intent.putExtra("CONFIGFILE", "/storage/emulated/0/RetroArch/config/retro_fix2.cfg");
            intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(intent);
        } catch (Exception e) {
            Toast.makeText(this, "Failed to launch RetroArch: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
        finish();
    }
}
