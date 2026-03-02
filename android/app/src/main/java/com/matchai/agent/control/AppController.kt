package com.matchai.agent.control

import android.content.Context
import android.util.Log
import com.matchai.agent.CommandResult
import com.matchai.agent.shizuku.ShizukuManager
import kotlinx.coroutines.delay

class AppController(
    private val shizuku: ShizukuManager,
    private val context: Context,
) {
    companion object {
        private const val TAG = "AppController"

        /** Map of common natural-language app names to package names. */
        val APP_MAP = mapOf(
            // Arabic names
            "واتساب" to "com.whatsapp",
            "وتساب" to "com.whatsapp",
            "تيليجرام" to "org.telegram.messenger",
            "تلجرام" to "org.telegram.messenger",
            "يوتيوب" to "com.google.android.youtube",
            "كروم" to "com.android.chrome",
            "الكاميرا" to "com.android.camera2",
            "المعرض" to "com.google.android.apps.photos",
            "الإعدادات" to "com.android.settings",
            "الرسائل" to "com.android.mms",
            "الهاتف" to "com.android.dialer",
            "جوجل" to "com.google.android.googlequicksearchbox",
            "خرائط" to "com.google.android.apps.maps",
            "إنستغرام" to "com.instagram.android",
            "انستقرام" to "com.instagram.android",
            "سناب شات" to "com.snapchat.android",
            "سناب" to "com.snapchat.android",
            "تويتر" to "com.twitter.android",
            "تيك توك" to "com.zhiliaoapp.musically",
            "نتفليكس" to "com.netflix.mediaclient",
            "سبوتيفاي" to "com.spotify.music",
            "يوتيوب ميوزك" to "com.google.android.apps.youtube.music",
            "أمازون" to "com.amazon.mShop.android.shopping",
            "جي مايل" to "com.google.android.gm",
            "الملاحظات" to "com.google.android.keep",
            "الساعة" to "com.google.android.deskclock",
            "الحاسبة" to "com.google.android.calculator",
            // English names
            "whatsapp" to "com.whatsapp",
            "telegram" to "org.telegram.messenger",
            "youtube" to "com.google.android.youtube",
            "chrome" to "com.android.chrome",
            "camera" to "com.android.camera2",
            "gallery" to "com.google.android.apps.photos",
            "photos" to "com.google.android.apps.photos",
            "settings" to "com.android.settings",
            "messages" to "com.android.mms",
            "phone" to "com.android.dialer",
            "google" to "com.google.android.googlequicksearchbox",
            "maps" to "com.google.android.apps.maps",
            "instagram" to "com.instagram.android",
            "snapchat" to "com.snapchat.android",
            "twitter" to "com.twitter.android",
            "tiktok" to "com.zhiliaoapp.musically",
            "netflix" to "com.netflix.mediaclient",
            "spotify" to "com.spotify.music",
            "gmail" to "com.google.android.gm",
            "keep" to "com.google.android.keep",
            "clock" to "com.google.android.deskclock",
            "calculator" to "com.google.android.calculator",
            "facebook" to "com.facebook.katana",
        )
    }

    /**
     * Open an app by natural name or package name.
     */
    suspend fun openApp(nameOrPackage: String): CommandResult {
        val pkg = resolvePackageName(nameOrPackage)
        Log.i(TAG, "Opening app: $nameOrPackage → $pkg")

        // Try monkey launcher
        val result = shizuku.executeShellCommand(
            "monkey -p $pkg -c android.intent.category.LAUNCHER 1"
        )
        if (result.success) return result

        // Fallback: am start with resolved activity
        val activityResult = shizuku.executeShellCommand(
            "am start -n \$(cmd package resolve-activity --brief -c android.intent.category.LAUNCHER $pkg | tail -1)"
        )
        return activityResult
    }

    suspend fun forceStop(packageName: String): CommandResult {
        Log.i(TAG, "Force stopping: $packageName")
        return shizuku.executeShellCommand("am force-stop $packageName")
    }

    fun getInstalledApps(): CommandResult {
        // This runs synchronously — only for metadata
        return CommandResult(success = true, installedApps = getInstalledPackages())
    }

    fun getInstalledPackages(): List<String> {
        return try {
            val pm = context.packageManager
            pm.getInstalledApplications(0)
                .filter { it.packageName != context.packageName }
                .map { "${it.loadLabel(pm)} (${it.packageName})" }
                .sorted()
        } catch (e: Exception) {
            emptyList()
        }
    }

    suspend fun getRunningApps(): CommandResult {
        return shizuku.executeShellCommand("am list-tasks --miniinfo")
    }

    fun resolvePackageName(nameOrPackage: String): String {
        // Direct package name (contains dot)
        if (nameOrPackage.contains(".") && nameOrPackage.length > 5) {
            return nameOrPackage
        }
        // Look up in map (case-insensitive)
        val lower = nameOrPackage.lowercase().trim()
        return APP_MAP.entries
            .firstOrNull { (key, _) -> key.lowercase() == lower || lower.contains(key.lowercase()) }
            ?.value ?: nameOrPackage
    }
}
