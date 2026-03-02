package com.matchai.agent

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import androidx.core.content.ContextCompat

/** Automatically restart AgentService on device boot. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.action) {
            Intent.ACTION_BOOT_COMPLETED,
            Intent.ACTION_MY_PACKAGE_REPLACED -> {
                Log.i("BootReceiver", "Boot detected, starting AgentService")
                ContextCompat.startForegroundService(
                    context,
                    Intent(context, AgentService::class.java)
                )
            }
        }
    }
}
