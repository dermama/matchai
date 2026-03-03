package com.matchai.agent.control

import android.util.Log
import com.matchai.agent.CommandResult
import com.matchai.agent.shizuku.ShizukuManager

class SystemController(private val shizuku: ShizukuManager) {

    companion object { private const val TAG = "SystemController" }

    suspend fun setVolume(level: Int): CommandResult {
        val clamped = level.coerceIn(0, 15)
        return shizuku.executeShellCommand(
            "media volume --stream 3 --set $clamped"
        )
    }

    suspend fun toggleWifi(): CommandResult {
        val stateResult = shizuku.executeShellCommand("cmd wifi status")
        val enabled = stateResult.output?.contains("Wifi is enabled") == true
        return shizuku.executeShellCommand(
            if (enabled) "svc wifi disable" else "svc wifi enable"
        )
    }

    suspend fun enableWifi(): CommandResult = shizuku.executeShellCommand("svc wifi enable")
    suspend fun disableWifi(): CommandResult = shizuku.executeShellCommand("svc wifi disable")

    suspend fun toggleBluetooth(): CommandResult {
        val stateResult = shizuku.executeShellCommand("settings get global bluetooth_on")
        val enabled = stateResult.output?.trim() == "1"
        return shizuku.executeShellCommand(
            if (enabled) "svc bluetooth disable" else "svc bluetooth enable"
        )
    }

    suspend fun toggleFlashlight(): CommandResult {
        // Toggle via camera2 API shell trick
        return shizuku.executeShellCommand(
            "cmd media_session volume --stream 0 --adj same"
        ).let {
            // Use hardware keys approach
            shizuku.executeShellCommand("input keyevent KEYCODE_CAMERA")
        }
    }

    suspend fun setBrightness(level: Int): CommandResult {
        val clamped = level.coerceIn(0, 255)
        shizuku.executeShellCommand("settings put system screen_brightness_mode 0")
        return shizuku.executeShellCommand("settings put system screen_brightness $clamped")
    }

    suspend fun getBatteryInfo(): CommandResult {
        val result = shizuku.executeShellCommand("dumpsys battery")
        return result.copy(output = parseBattery(result.output ?: ""))
    }

    suspend fun getStorageInfo(): CommandResult {
        return shizuku.executeShellCommand("df -h /sdcard")
    }

    suspend fun clearNotifications(): CommandResult {
        return shizuku.executeShellCommand(
            "service call notification 1"
        )
    }

    suspend fun getWifiInfo(): CommandResult {
        return shizuku.executeShellCommand("cmd wifi list-networks")
    }

    suspend fun setAirplaneMode(enabled: Boolean): CommandResult {
        val value = if (enabled) 1 else 0
        shizuku.executeShellCommand("settings put global airplane_mode_on $value")
        return shizuku.executeShellCommand(
            "am broadcast -a android.intent.action.AIRPLANE_MODE --ez state $enabled"
        )
    }

    suspend fun adjustSystemSetting(key: String, value: String, namespace: String = "system"): CommandResult {
        return shizuku.executeShellCommand("settings put $namespace $key $value")
    }

    private fun parseBattery(raw: String): String {
        val lines = raw.lines()
        val level = lines.firstOrNull { it.contains("level:") }?.trim() ?: ""
        val status = lines.firstOrNull { it.contains("status:") }?.trim() ?: ""
        val plugged = lines.firstOrNull { it.contains("plugged:") }?.trim() ?: ""
        return "$level | $status | $plugged"
    }
}
