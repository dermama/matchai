package com.matchai.agent.shizuku

import android.util.Log
import com.matchai.agent.CommandResult
import kotlinx.coroutines.delay
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull

/**
 * AppInspector — Deep app inspection via Shizuku/ADB.
 * Provides structured data about any installed app:
 * activities, services, permissions, state, and waiting for app events.
 */
class AppInspector(private val shizuku: ShizukuManager) {

    companion object { private const val TAG = "AppInspector" }

    // ─── App Structure ─────────────────────────────────────────────────────────

    /** Get all declared activities of a package. */
    suspend fun getAppActivities(packageName: String): List<String> {
        val result = shizuku.executeShellCommand(
            "pm dump $packageName | grep -A1 'Activity of' | grep 'name=' | head -30"
        )
        return result.output?.lines()?.filter { it.contains("name=") }
            ?.map { it.substringAfter("name=").trim() } ?: emptyList()
    }

    /** Get all services of a package. */
    suspend fun getAppServices(packageName: String): List<String> {
        val result = shizuku.executeShellCommand(
            "pm dump $packageName | grep 'Service{' | head -20"
        )
        return result.output?.lines()?.filter { it.isNotBlank() }?.map { it.trim() } ?: emptyList()
    }

    /** Get declared permissions of a package. */
    suspend fun getAppPermissions(packageName: String): List<String> {
        val result = shizuku.executeShellCommand(
            "pm dump $packageName | grep 'permission:' | head -30"
        )
        return result.output?.lines()?.filter { it.contains("permission:") }
            ?.map { it.substringAfter("permission:").trim() } ?: emptyList()
    }

    /** Grant a permission to an app (requires Shizuku with ADB privileges). */
    suspend fun grantPermission(packageName: String, permission: String): CommandResult {
        Log.i(TAG, "Granting $permission to $packageName")
        return shizuku.executeShellCommand("pm grant $packageName $permission")
    }

    /** Revoke a permission from an app. */
    suspend fun revokePermission(packageName: String, permission: String): CommandResult {
        return shizuku.executeShellCommand("pm revoke $packageName $permission")
    }

    // ─── App State ─────────────────────────────────────────────────────────────

    /** Check if an app is currently installed. */
    suspend fun isInstalled(packageName: String): Boolean {
        val result = shizuku.executeShellCommand("pm path $packageName 2>&1")
        return result.output?.contains("package:") == true
    }

    /** Check if an app is currently running in foreground or background. */
    suspend fun isRunning(packageName: String): Boolean {
        val result = shizuku.executeShellCommand(
            "ps | grep $packageName | grep -v grep"
        )
        return result.output?.trim()?.isNotEmpty() == true
    }

    /** Get app version information. */
    suspend fun getVersionInfo(packageName: String): Map<String, String> {
        val result = shizuku.executeShellCommand(
            "dumpsys package $packageName | grep -E 'versionName|versionCode|firstInstallTime|lastUpdateTime' | head -5"
        )
        val info = mutableMapOf<String, String>()
        result.output?.lines()?.forEach { line ->
            val trimmed = line.trim()
            when {
                trimmed.startsWith("versionName=") -> info["version_name"] = trimmed.substringAfter("=")
                trimmed.startsWith("versionCode=") -> info["version_code"] = trimmed.substringAfter("=").split(" ").first()
                trimmed.startsWith("firstInstallTime=") -> info["first_install"] = trimmed.substringAfter("=")
                trimmed.startsWith("lastUpdateTime=") -> info["last_update"] = trimmed.substringAfter("=")
            }
        }
        return info
    }

    /** Get the APK path of an app. */
    suspend fun getApkPath(packageName: String): String {
        val result = shizuku.executeShellCommand("pm path $packageName")
        return result.output?.removePrefix("package:")?.trim() ?: ""
    }

    /** Get memory usage of a running app. */
    suspend fun getMemoryUsage(packageName: String): CommandResult {
        return shizuku.executeShellCommand(
            "dumpsys meminfo $packageName | head -20"
        )
    }

    // ─── App Data Inspection ───────────────────────────────────────────────────

    /** Read SharedPreferences file (requires root or Shizuku ADB equivalent). */
    suspend fun readSharedPrefs(packageName: String, prefFileName: String): CommandResult {
        val path = "/data/data/$packageName/shared_prefs/${prefFileName}.xml"
        return shizuku.executeShellCommand("cat '$path' 2>&1")
    }

    /** List all SharedPreferences files for an app. */
    suspend fun listSharedPrefs(packageName: String): CommandResult {
        return shizuku.executeShellCommand(
            "ls /data/data/$packageName/shared_prefs/ 2>&1"
        )
    }

    /** Get app's database files list. */
    suspend fun listDatabases(packageName: String): CommandResult {
        return shizuku.executeShellCommand(
            "ls /data/data/$packageName/databases/ 2>/dev/null"
        )
    }

    // ─── App Launch & Control ──────────────────────────────────────────────────

    /** Launch a specific activity within an app. */
    suspend fun launchActivity(packageName: String, activityName: String): CommandResult {
        val fullActivity = if (activityName.startsWith("."))
            "$packageName$activityName" else activityName
        return shizuku.executeShellCommand(
            "am start -n '$packageName/$fullActivity' 2>&1"
        )
    }

    /** Send a broadcast intent to an app. */
    suspend fun sendBroadcast(action: String, packageName: String? = null, extras: Map<String, String> = emptyMap()): CommandResult {
        var cmd = "am broadcast -a '$action'"
        if (packageName != null) cmd += " -p '$packageName'"
        extras.forEach { (key, value) -> cmd += " -e '$key' '$value'" }
        return shizuku.executeShellCommand("$cmd 2>&1")
    }

    /** Clear app data (like factory reset for the app). */
    suspend fun clearAppData(packageName: String): CommandResult {
        Log.w(TAG, "Clearing data for $packageName")
        return shizuku.executeShellCommand("pm clear $packageName 2>&1")
    }

    // ─── Reactive Waiting ─────────────────────────────────────────────────────

    /**
     * Wait until a specific app becomes the foreground app.
     * Returns true if it appeared within the timeout.
     */
    suspend fun waitUntilAppInForeground(
        packageName: String,
        timeoutMs: Long = 10000,
        pollIntervalMs: Long = 500,
    ): Boolean = withContext(Dispatchers.IO) {
        val result = withTimeoutOrNull(timeoutMs) {
            while (true) {
                val fg = shizuku.executeShellCommand(
                    "dumpsys activity | grep 'mResumedActivity' | head -1"
                )
                if (fg.output?.contains(packageName) == true) {
                    return@withTimeoutOrNull true
                }
                kotlinx.coroutines.delay(pollIntervalMs)
            }
            false
        }
        result ?: false
    }

    /**
     * Wait for the screen/app to become idle (stop changing).
     * Useful after app launches to know it's ready for interaction.
     */
    suspend fun waitUntilIdle(
        packageName: String,
        stableMs: Long = 1000,
        timeoutMs: Long = 8000,
    ): Boolean = withContext(Dispatchers.IO) {
        var lastDump = ""
        var stableStart = 0L
        val deadline = System.currentTimeMillis() + timeoutMs

        while (System.currentTimeMillis() < deadline) {
            val dump = shizuku.executeShellCommand(
                "dumpsys activity activities | grep -E '$packageName|mCurrentFocus' | head -5"
            ).output

            if (dump == lastDump) {
                if (stableStart == 0L) stableStart = System.currentTimeMillis()
                if (System.currentTimeMillis() - stableStart >= stableMs) {
                    Log.d(TAG, "$packageName is idle after ${System.currentTimeMillis() - stableStart}ms")
                    return@withContext true
                }
            } else {
                stableStart = 0L
                lastDump = dump ?: ""
            }
            kotlinx.coroutines.delay(300)
        }
        false
    }

    /**
     * Watch for a specific activity to appear (popup, dialog, etc.)
     */
    suspend fun watchForActivity(
        activityName: String,
        timeoutMs: Long = 5000,
    ): Boolean = withContext(Dispatchers.IO) {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val fg = shizuku.executeShellCommand(
                "dumpsys activity | grep 'mCurrentFocus' | head -1"
            )
            if (fg.output?.contains(activityName) == true) return@withContext true
            kotlinx.coroutines.delay(300)
        }
        false
    }

    // ─── Full App Report ───────────────────────────────────────────────────────

    /** Generate a comprehensive report about an app for AI analysis. */
    suspend fun generateAppReport(packageName: String): String {
        val versionInfo = getVersionInfo(packageName)
        val isRunningNow = isRunning(packageName)
        val memUse = if (isRunningNow) getMemoryUsage(packageName).output.orEmpty().take(200) else "not running"
        val permissions = getAppPermissions(packageName).take(10)

        return buildString {
            appendLine("=== App Report: $packageName ===")
            appendLine("Version: ${versionInfo["version_name"]} (${versionInfo["version_code"]})")
            appendLine("Running: $isRunningNow")
            appendLine("Memory: $memUse")
            appendLine("Permissions (top 10): ${permissions.joinToString(", ")}")
            appendLine("First Install: ${versionInfo["first_install"]}")
            appendLine("Last Update: ${versionInfo["last_update"]}")
        }
    }
}
