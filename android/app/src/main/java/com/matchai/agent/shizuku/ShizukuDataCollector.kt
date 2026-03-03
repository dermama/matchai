package com.matchai.agent.shizuku

import android.content.Context
import android.util.Log
import com.matchai.agent.CommandResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.*

/**
 * ShizukuDataCollector — Deep device intelligence layer.
 *
 * Uses Shizuku's ADB-level access to collect rich structured data
 * about the current screen, foreground app, UI elements, and system state.
 * This rich data is sent to the server so the AI can make precise decisions
 * WITHOUT needing screenshot analysis as primary method.
 *
 * Screenshot analysis is only a FALLBACK when structured data is insufficient.
 */
class ShizukuDataCollector(
    private val shizuku: ShizukuManager,
    private val context: Context,
) {
    companion object {
        private const val TAG = "ShizukuDataCollector"
    }

    // ─── Primary Data Collection: Full Device State ────────────────────────────

    /**
     * Master method: collect ALL available device intelligence in one shot.
     * Returns a rich DeviceState object ready to be sent to the AI server.
     */
    suspend fun collectFullDeviceState(): DeviceState = withContext(Dispatchers.IO) {
        Log.i(TAG, "🔍 Collecting full device state via Shizuku...")

        // Run all queries in parallel via coroutines
        val foregroundResult      = getForegroundApp()
        val uiTreeResult          = getUIHierarchy()
        val windowsResult         = getWindowsList()
        val runningAppsResult     = getRunningTasks()
        val notificationsResult   = getActiveNotifications()
        val inputMethodResult     = getActiveInputMethod()
        val systemInfoResult      = getSystemInfo()
        val focusedWindowResult   = getFocusedWindow()

        DeviceState(
            foregroundApp       = foregroundResult,
            uiHierarchy         = uiTreeResult,
            windows             = windowsResult,
            runningTasks        = runningAppsResult,
            activeNotifications = notificationsResult,
            activeInputMethod   = inputMethodResult,
            systemInfo          = systemInfoResult,
            focusedWindow       = focusedWindowResult,
        )
    }

    // ─── Foreground App Info ───────────────────────────────────────────────────

    /**
     * Get the currently foreground (visible) app with full detail.
     * Returns: package name, activity name, app label, version, etc.
     */
    suspend fun getForegroundApp(): ForegroundAppInfo {
        // Get the top activity (most reliable method)
        val topActivity = shizuku.executeShellCommand(
            "dumpsys activity activities | grep -E 'mCurrentFocus|mFocusedApp|topActivity' | head -5"
        )

        // Get focused package via window manager
        val focusedPkg = shizuku.executeShellCommand(
            "dumpsys window windows | grep -E 'mCurrentFocus|mFocusedApp' | head -3"
        )

        // Get activity stack top
        val activityStack = shizuku.executeShellCommand(
            "dumpsys activity | grep 'mResumedActivity' | head -3"
        )

        // Parse package name from output
        val packageName = parsePackageName(
            topActivity.output + "\n" + focusedPkg.output + "\n" + activityStack.output
        )

        // Get detailed app info if we have a package
        val appInfo = if (packageName.isNotEmpty()) {
            getAppDetails(packageName)
        } else AppDetails()

        Log.d(TAG, "Foreground app: $packageName | ${appInfo.label}")

        return ForegroundAppInfo(
            packageName    = packageName,
            activityName   = parseActivityName(activityStack.output),
            appLabel       = appInfo.label,
            versionName    = appInfo.versionName,
            versionCode    = appInfo.versionCode,
            rawDumpsys     = topActivity.output.take(500),
        )
    }

    // ─── UI Hierarchy (XML Tree) ───────────────────────────────────────────────

    /**
     * Dump the complete UI hierarchy of the current screen.
     * Returns structured data with all visible UI elements.
     * Much faster and more reliable than screenshot OCR.
     */
    suspend fun getUIHierarchy(): UIHierarchyInfo {
        // Dump UI XML to file
        val dumpResult = shizuku.executeShellCommand(
            "uiautomator dump /sdcard/matchai_ui.xml 2>&1"
        )

        if (!dumpResult.success && !dumpResult.output.contains("dumped")) {
            // Fallback: use accessibility dump
            val accDump = shizuku.executeShellCommand(
                "dumpsys accessibility | grep -A5 'Window:' | head -50"
            )
            return UIHierarchyInfo(
                available = false,
                elements  = emptyList(),
                rawText   = accDump.output,
            )
        }

        // Read the XML file
        val xmlContent = shizuku.executeShellCommand(
            "cat /sdcard/matchai_ui.xml"
        )

        // Cleanup
        shizuku.executeShellCommand("rm -f /sdcard/matchai_ui.xml")

        // Parse XML to extract UI elements
        val elements = parseUIXml(xmlContent.output)

        Log.d(TAG, "UI Hierarchy: ${elements.size} elements found")

        return UIHierarchyInfo(
            available = xmlContent.output.isNotEmpty(),
            rawXml    = xmlContent.output.take(8000),  // Limit size
            elements  = elements,
            rawText   = elements.joinToString("\n") {
                "[${it.type}] '${it.text}' @ (${it.x},${it.y}) ${if (it.clickable) "[clickable]" else ""}"
            },
        )
    }

    // ─── Window Information ────────────────────────────────────────────────────

    /**
     * Get all visible windows with their details.
     * Useful to understand overlapping dialogs, popups, keyboards, etc.
     */
    suspend fun getWindowsList(): List<WindowInfo> {
        val result = shizuku.executeShellCommand(
            "dumpsys window windows | grep -E 'Window #|mOwnerUid|Requested|mBaseLayer|isVisible' | head -80"
        )

        return result.output.lines()
            .filter { it.contains("Window #") }
            .map { line ->
                WindowInfo(
                    title = line.trim(),
                    visible = true,
                )
            }
    }

    // ─── Running Tasks ─────────────────────────────────────────────────────────

    /**
     * Get list of running/recent tasks (app stack).
     */
    suspend fun getRunningTasks(): List<RunningTaskInfo> {
        val result = shizuku.executeShellCommand(
            "am stack list 2>/dev/null | head -30"
        )
        val altResult = shizuku.executeShellCommand(
            "dumpsys activity recents | grep 'Recent #' | head -15"
        )

        return (result.output + "\n" + altResult.output)
            .lines()
            .filter { it.isNotBlank() }
            .take(10)
            .map { RunningTaskInfo(description = it.trim()) }
    }

    // ─── Active Notifications ──────────────────────────────────────────────────

    /**
     * Get all active notifications with their text content.
     * Helps AI understand what alerts/messages the user has.
     */
    suspend fun getActiveNotifications(): List<NotificationInfo> {
        val result = shizuku.executeShellCommand(
            "dumpsys notification | grep -A3 'NotificationRecord{' | head -60"
        )

        return result.output
            .lines()
            .filter { it.contains("NotificationRecord") || it.contains("android.title") || it.contains("android.text") }
            .map { NotificationInfo(content = it.trim()) }
            .take(20)
    }

    // ─── Input Method ──────────────────────────────────────────────────────────

    /**
     * Check if keyboard is visible and which input method is active.
     * Important for knowing if a text field is focused.
     */
    suspend fun getActiveInputMethod(): InputMethodInfo {
        val result = shizuku.executeShellCommand(
            "dumpsys input_method | grep -E 'mInputShown|mCurrentInputMethodId|mCurId' | head -5"
        )
        val isKeyboardShown = result.output.contains("mInputShown=true")
        return InputMethodInfo(
            keyboardVisible = isKeyboardShown,
            rawInfo = result.output.take(200),
        )
    }

    // ─── Focused Window ───────────────────────────────────────────────────────

    suspend fun getFocusedWindow(): String {
        val result = shizuku.executeShellCommand(
            "dumpsys window | grep mCurrentFocus | head -1"
        )
        return result.output.trim()
    }

    // ─── System Info ──────────────────────────────────────────────────────────

    /**
     * Collect relevant system state: battery, memory, display, etc.
     */
    suspend fun getSystemInfo(): SystemStateInfo {
        val battery   = shizuku.executeShellCommand("dumpsys battery | grep -E 'level:|status:|plugged:' | head -3")
        val memory    = shizuku.executeShellCommand("cat /proc/meminfo | grep -E 'MemTotal|MemFree|MemAvailable' | head -3")
        val display   = shizuku.executeShellCommand("dumpsys display | grep -E 'mDisplayWidth|mDisplayHeight|DisplayName' | head -3")
        val wifi      = shizuku.executeShellCommand("dumpsys wifi | grep -E 'mNetworkInfo|mWifiInfo|SSID' | head -5")

        return SystemStateInfo(
            battery = battery.output.trim(),
            memory  = memory.output.trim(),
            display = display.output.trim(),
            wifi    = wifi.output.trim(),
        )
    }

    // ─── Package Deep Dive ─────────────────────────────────────────────────────

    /**
     * Get comprehensive information about a specific package.
     * Useful before interacting with an app to understand its structure.
     */
    suspend fun getAppDetails(packageName: String): AppDetails {
        val result = shizuku.executeShellCommand(
            "dumpsys package $packageName | grep -E 'versionName|versionCode|applicationInfo|firstInstall|lastUpdate' | head -10"
        )

        val labelResult = shizuku.executeShellCommand(
            "pm list packages -f | grep $packageName | head -1"
        )

        val activities = shizuku.executeShellCommand(
            "pm dump $packageName | grep 'Activity ' | head -20"
        )

        return AppDetails(
            label          = extractPackageLabel(packageName),
            versionName    = extractField(result.output, "versionName="),
            versionCode    = extractField(result.output, "versionCode="),
            activities     = activities.output.lines().take(10).map { it.trim() },
        )
    }

    /**
     * Get list of ALL installed packages with labels — used for app resolution.
     */
    suspend fun getAllInstalledApps(): List<InstalledApp> {
        val result = shizuku.executeShellCommand("pm list packages -3 --show-versioncode")
        val systemResult = shizuku.executeShellCommand(
            "pm list packages -s | grep -E 'whatsapp|telegram|youtube|chrome|camera|phone|settings|dialer|maps|gmail|photos'"
        )

        val allOutput = result.output + "\n" + systemResult.output

        return allOutput.lines()
            .filter { it.startsWith("package:") }
            .map { line ->
                val pkg = line.removePrefix("package:").split(" ").first().trim()
                InstalledApp(
                    packageName = pkg,
                    label = extractPackageLabel(pkg),
                )
            }
            .distinctBy { it.packageName }
    }

    // ─── Real-time Screen Text ─────────────────────────────────────────────────

    /**
     * Get all visible text on screen using UIAutomator dump and parse.
     * Primary alternative to screenshot OCR.
     */
    suspend fun getScreenText(): String {
        val hierarchy = getUIHierarchy()
        return hierarchy.elements
            .filter { it.text.isNotBlank() }
            .joinToString("\n") { "[${it.type}] ${it.text}" }
    }

    /**
     * Find clickable elements on screen that match a search term.
     * Used by AI to find where to tap without needing screenshot coordinates.
     */
    suspend fun findClickableElement(searchText: String): UIElement? {
        val hierarchy = getUIHierarchy()
        val lower = searchText.lowercase()
        return hierarchy.elements.firstOrNull { element ->
            element.clickable && (
                element.text.lowercase().contains(lower) ||
                element.contentDescription.lowercase().contains(lower) ||
                element.resourceId.lowercase().contains(lower)
            )
        }
    }

    // ─── Structured Payload for Server ────────────────────────────────────────

    /**
     * Build the complete JSON payload to send to the server for AI analysis.
     * This replaces the need for screenshot as primary data source.
     */
    suspend fun buildServerPayload(includeScreenshot: Boolean = false): Map<String, Any> {
        val state = collectFullDeviceState()

        return mapOf(
            "foreground_app" to mapOf(
                "package" to state.foregroundApp.packageName,
                "activity" to state.foregroundApp.activityName,
                "label" to state.foregroundApp.appLabel,
                "version" to state.foregroundApp.versionName,
            ),
            "screen_elements" to state.uiHierarchy.elements.take(50).map { el ->
                mapOf(
                    "type" to el.type,
                    "text" to el.text,
                    "content_desc" to el.contentDescription,
                    "resource_id" to el.resourceId,
                    "x" to el.x,
                    "y" to el.y,
                    "width" to el.width,
                    "height" to el.height,
                    "clickable" to el.clickable,
                    "editable" to el.editable,
                    "scrollable" to el.scrollable,
                    "checked" to el.checked,
                )
            },
            "screen_text" to state.uiHierarchy.rawText.take(2000),
            "keyboard_visible" to state.activeInputMethod.keyboardVisible,
            "focused_window" to state.focusedWindow,
            "notifications" to state.activeNotifications.take(10).map { it.content },
            "battery" to state.systemInfo.battery,
            "has_screenshot" to includeScreenshot,
        )
    }

    // ─── XML Parser ───────────────────────────────────────────────────────────

    private fun parseUIXml(xml: String): List<UIElement> {
        if (xml.isBlank()) return emptyList()

        val elements = mutableListOf<UIElement>()
        val nodePattern = Regex(
            """<node[^>]*text="([^"]*)"[^>]*content-desc="([^"]*)"[^>]*resource-id="([^"]*)"[^>]*class="([^"]*)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*clickable="([^"]*)"[^>]*enabled="([^"]*)"[^>]*focusable="([^"]*)"[^>]*scrollable="([^"]*)"[^>]*checked="([^"]*)"[^>]*[^/]*/>""",
            RegexOption.DOT_MATCHES_ALL
        )
        val simplePattern = Regex("""bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"""")

        // Simple line-by-line parsing for robustness
        xml.lines().forEach { line ->
            if (!line.contains("<node")) return@forEach

            val text = extractAttr(line, "text")
            val contentDesc = extractAttr(line, "content-desc")
            val resourceId = extractAttr(line, "resource-id")
            val className = extractAttr(line, "class").substringAfterLast(".")
            val clickable = extractAttr(line, "clickable") == "true"
            val editable = extractAttr(line, "editable") == "true" ||
                    className.contains("EditText", ignoreCase = true)
            val scrollable = extractAttr(line, "scrollable") == "true"
            val checked = extractAttr(line, "checked") == "true"

            // Parse bounds [x1,y1][x2,y2]
            val boundsMatch = Regex("""\[(\d+),(\d+)\]\[(\d+),(\d+)\]""").find(line)
            val (x1, y1, x2, y2) = boundsMatch?.destructured?.let {
                listOf(
                    it.component1().toIntOrNull() ?: 0,
                    it.component2().toIntOrNull() ?: 0,
                    it.component3().toIntOrNull() ?: 0,
                    it.component4().toIntOrNull() ?: 0,
                )
            } ?: listOf(0, 0, 0, 0)

            // Center coordinates
            val cx = (x1 + x2) / 2
            val cy = (y1 + y2) / 2

            if (text.isNotBlank() || contentDesc.isNotBlank() || clickable || editable) {
                elements.add(
                    UIElement(
                        type = simplifyClassName(className),
                        text = text,
                        contentDescription = contentDesc,
                        resourceId = resourceId,
                        x = cx, y = cy,
                        width = x2 - x1, height = y2 - y1,
                        clickable = clickable,
                        editable = editable,
                        scrollable = scrollable,
                        checked = checked,
                    )
                )
            }
        }

        return elements
    }

    // ─── Helpers ──────────────────────────────────────────────────────────────

    private fun extractAttr(line: String, attr: String): String {
        val pattern = Regex("""$attr="([^"]*)"""")
        return pattern.find(line)?.groupValues?.get(1) ?: ""
    }

    private fun simplifyClassName(cls: String): String = when {
        cls.contains("Button", true)   -> "Button"
        cls.contains("EditText", true) -> "TextField"
        cls.contains("TextView", true) -> "Text"
        cls.contains("Image", true)    -> "Image"
        cls.contains("RecyclerView", true) || cls.contains("ListView", true) -> "List"
        cls.contains("Switch", true)   -> "Switch"
        cls.contains("CheckBox", true) -> "Checkbox"
        cls.contains("Tab", true)      -> "Tab"
        cls.contains("Scroll", true)   -> "ScrollContainer"
        cls.contains("Linear", true) || cls.contains("Frame", true) || cls.contains("Relative", true) -> "Container"
        else -> cls.ifBlank { "View" }
    }

    private fun parsePackageName(output: String): String {
        // Match patterns like: com.android.chrome, mCurrentFocus=Window{... com.app/...}
        val patterns = listOf(
            Regex("""mCurrentFocus=Window\{[^}]* ([a-z][a-zA-Z0-9._]+)/"""),
            Regex("""mResumedActivity: ActivityRecord\{[^}]* ([a-z][a-zA-Z0-9._]+)/"""),
            Regex("""mFocusedApp=ActivityRecord\{[^}]* ([a-z][a-zA-Z0-9._]+)/"""),
            Regex("""([a-z][a-zA-Z0-9]{2,}\.[a-zA-Z0-9._]{2,})/[A-Z]"""),
        )
        for (pattern in patterns) {
            val match = pattern.find(output)
            if (match != null) return match.groupValues[1]
        }
        return ""
    }

    private fun parseActivityName(output: String): String {
        val match = Regex("""([a-z][a-zA-Z0-9._]+/[.A-Za-z0-9_$]+)""").find(output)
        return match?.groupValues?.get(1) ?: ""
    }

    private fun extractField(text: String, key: String): String {
        val idx = text.indexOf(key)
        if (idx == -1) return ""
        val start = idx + key.length
        val end = Regex("""[\s,\n]""").find(text, start)?.range?.first ?: text.length
        return text.substring(start, minOf(end, text.length)).trim()
    }

    private fun extractPackageLabel(packageName: String): String {
        // Use PM to get app label
        return try {
            val pm = context.packageManager
            val info = pm.getApplicationInfo(packageName, 0)
            pm.getApplicationLabel(info).toString()
        } catch (e: Exception) {
            // Derive from package name as fallback
            packageName.substringAfterLast(".").replaceFirstChar { it.uppercase() }
        }
    }
}

// ─── Data Classes ─────────────────────────────────────────────────────────────

data class DeviceState(
    val foregroundApp: ForegroundAppInfo,
    val uiHierarchy: UIHierarchyInfo,
    val windows: List<WindowInfo>,
    val runningTasks: List<RunningTaskInfo>,
    val activeNotifications: List<NotificationInfo>,
    val activeInputMethod: InputMethodInfo,
    val systemInfo: SystemStateInfo,
    val focusedWindow: String,
)

data class ForegroundAppInfo(
    val packageName: String = "",
    val activityName: String = "",
    val appLabel: String = "",
    val versionName: String = "",
    val versionCode: String = "",
    val rawDumpsys: String = "",
)

data class UIHierarchyInfo(
    val available: Boolean = false,
    val rawXml: String = "",
    val rawText: String = "",
    val elements: List<UIElement> = emptyList(),
)

data class UIElement(
    val type: String,
    val text: String,
    val contentDescription: String = "",
    val resourceId: String = "",
    val x: Int, val y: Int,
    val width: Int, val height: Int,
    val clickable: Boolean = false,
    val editable: Boolean = false,
    val scrollable: Boolean = false,
    val checked: Boolean = false,
)

data class WindowInfo(
    val title: String,
    val visible: Boolean,
)

data class RunningTaskInfo(val description: String)

data class NotificationInfo(val content: String)

data class InputMethodInfo(
    val keyboardVisible: Boolean,
    val rawInfo: String = "",
)

data class SystemStateInfo(
    val battery: String = "",
    val memory: String = "",
    val display: String = "",
    val wifi: String = "",
)

data class AppDetails(
    val label: String = "",
    val versionName: String = "",
    val versionCode: String = "",
    val activities: List<String> = emptyList(),
)

data class InstalledApp(
    val packageName: String,
    val label: String,
)
