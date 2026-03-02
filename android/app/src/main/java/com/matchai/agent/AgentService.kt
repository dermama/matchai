package com.matchai.agent

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import com.matchai.agent.control.*
import com.matchai.agent.network.ServerClient
import com.matchai.agent.shizuku.ShizukuManager
import com.matchai.agent.shizuku.ShizukuDataCollector
import com.matchai.agent.shizuku.UIElement
import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.int

/**
 * AgentService — The heart of the Android agent.
 * Runs as a foreground service, polls the server, and dispatches commands
 * to the appropriate controllers.
 */
class AgentService : Service() {

    companion object {
        private const val TAG = "MatchaiAgent"
        private const val CHANNEL_ID = "matchai_agent"
        private const val NOTIF_ID = 1001
    }

    private val serviceScope = CoroutineScope(Dispatchers.IO + SupervisorJob())

    private lateinit var shizukuManager: ShizukuManager
    private lateinit var serverClient: ServerClient
    private lateinit var screenController: ScreenController
    private lateinit var touchController: TouchController
    private lateinit var textController: TextController
    private lateinit var appController: AppController
    private lateinit var systemController: SystemController
    private lateinit var dataCollector: ShizukuDataCollector  // Primary data source

    private var isRunning = false

    // ─── Lifecycle ────────────────────────────────────────────────────────────

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        startForeground(NOTIF_ID, buildNotification("🔄 Connecting..."))

        shizukuManager = ShizukuManager(this)
        serverClient = ServerClient(BuildConfig.SERVER_URL, BuildConfig.DEVICE_SECRET)
        screenController = ScreenController(shizukuManager, this)
        touchController = TouchController(shizukuManager)
        textController = TextController(shizukuManager, this)
        appController = AppController(shizukuManager, this)
        systemController = SystemController(shizukuManager)
        dataCollector   = ShizukuDataCollector(shizukuManager, this)

        Log.i(TAG, "AgentService created | Server: ${BuildConfig.SERVER_URL}")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!isRunning) {
            isRunning = true
            serviceScope.launch { runAgent() }
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        isRunning = false
        serviceScope.cancel()
        super.onDestroy()
    }

    // ─── Agent Loop ───────────────────────────────────────────────────────────

    private suspend fun runAgent() {
        // Register device with server
        registerWithServer()

        Log.i(TAG, "▶ Starting command poll loop")
        updateNotification("🟢 Active — Waiting for commands")

        while (isRunning) {
            try {
                val response = serverClient.pollForCommand()
                if (response?.hasCommand == true) {
                    val command = response.command!!
                    Log.i(TAG, "📥 Received command: ${command.action} [${command.commandId}]")
                    updateNotification("⚡ Executing: ${command.action}")
                    executeCommand(command)
                    updateNotification("🟢 Active — Waiting for commands")
                }
            } catch (e: CancellationException) {
                break
            } catch (e: Exception) {
                Log.e(TAG, "Poll error: ${e.message}")
                delay(5000) // Wait before retry
            }
        }
    }

    private suspend fun registerWithServer() {
        try {
            val screenSize = screenController.getScreenSize()
            serverClient.registerDevice(
                deviceId = android.os.Build.MODEL,
                androidVersion = android.os.Build.VERSION.RELEASE,
                shizukuActive = shizukuManager.isShizukuAvailable(),
                screenWidth = screenSize.first,
                screenHeight = screenSize.second,
            )
            Log.i(TAG, "✅ Registered with server")
        } catch (e: Exception) {
            Log.e(TAG, "❌ Registration failed: ${e.message}")
        }
    }

    // ─── Command Dispatcher ────────────────────────────────────────────────────

    private suspend fun executeCommand(command: ServerClient.Command) {
        val result = try {
            when (command.action) {

                // ── PRIMARY: Collect full structured device state (NO screenshot needed) ──
                "collect_state" -> handleCollectState(command)

                // ── SECONDARY: Screenshot (fallback for visual analysis) ──
                "screenshot" -> handleScreenshot(command)

                // ── UI Element Search via Shizuku ──
                "find_element" -> handleFindElement(
                    command.params["text"]!!.jsonPrimitive.content
                )
                "get_screen_text" -> {
                    val text = dataCollector.getScreenText()
                    CommandResult(success = true, output = text)
                }
                "get_ui_tree" -> {
                    val hierarchy = dataCollector.getUIHierarchy()
                    CommandResult(success = hierarchy.available, output = hierarchy.rawText)
                }
                "get_foreground_app" -> {
                    val fg = dataCollector.getForegroundApp()
                    CommandResult(success = true, output = "${fg.appLabel} (${fg.packageName}) | ${fg.activityName}")
                }
                "get_app_details" -> {
                    val pkg = command.params["package_name"]!!.jsonPrimitive.content
                    val details = dataCollector.getAppDetails(pkg)
                    CommandResult(success = true, output = "${details.label} v${details.versionName} | Activities: ${details.activities.take(5)}")
                }
                "get_all_apps" -> {
                    val apps = dataCollector.getAllInstalledApps()
                    val list = apps.joinToString("\n") { "${it.label}: ${it.packageName}" }
                    CommandResult(success = true, output = list, installedApps = apps.map { "${it.label} (${it.packageName})" })
                }

                // ── Touch Controls ──
                "tap" -> touchController.tap(
                    command.params["x"]!!.jsonPrimitive.int,
                    command.params["y"]!!.jsonPrimitive.int,
                )
                "tap_element" -> handleTapElement(
                    command.params["text"]!!.jsonPrimitive.content
                )
                "swipe" -> touchController.swipe(
                    command.params["x1"]!!.jsonPrimitive.int,
                    command.params["y1"]!!.jsonPrimitive.int,
                    command.params["x2"]!!.jsonPrimitive.int,
                    command.params["y2"]!!.jsonPrimitive.int,
                    command.params["duration_ms"]?.jsonPrimitive?.int ?: 300,
                )
                "long_press" -> touchController.longPress(
                    command.params["x"]!!.jsonPrimitive.int,
                    command.params["y"]!!.jsonPrimitive.int,
                )
                "double_tap" -> touchController.doubleTap(
                    command.params["x"]!!.jsonPrimitive.int,
                    command.params["y"]!!.jsonPrimitive.int,
                )
                "scroll_down" -> touchController.scrollDown()
                "scroll_up"   -> touchController.scrollUp()

                // ── Text Input ──
                "type_text" -> textController.typeText(
                    command.params["text"]!!.jsonPrimitive.content
                )
                "type_clipboard" -> textController.typeViaClipboard(
                    command.params["text"]!!.jsonPrimitive.content
                )
                "clear_field" -> textController.clearField()

                // ── Navigation ──
                "back" -> touchController.pressBack()
                "home" -> touchController.pressHome()
                "recents" -> touchController.pressRecents()
                "press_enter" -> touchController.pressEnter()

                // ── App Management ──
                "open_app" -> appController.openApp(
                    command.params["app_name"]?.jsonPrimitive?.content
                        ?: command.params["package_name"]!!.jsonPrimitive.content
                )
                "force_stop_app" -> appController.forceStop(
                    command.params["package_name"]!!.jsonPrimitive.content
                )
                "list_apps" -> appController.getInstalledApps()

                // ── Notifications ──
                "open_notifications" -> touchController.openNotifications()
                "close_notifications" -> touchController.closeNotifications()
                "clear_notifications" -> systemController.clearNotifications()

                // ── System Settings ──
                "set_volume"     -> systemController.setVolume(command.params["level"]!!.jsonPrimitive.int)
                "toggle_wifi"    -> systemController.toggleWifi()
                "toggle_bluetooth" -> systemController.toggleBluetooth()
                "toggle_flashlight" -> systemController.toggleFlashlight()
                "set_brightness" -> systemController.setBrightness(command.params["level"]!!.jsonPrimitive.int)
                "get_battery"    -> systemController.getBatteryInfo()
                "get_storage"    -> systemController.getStorageInfo()
                "get_running_apps" -> appController.getRunningApps()

                // ── Raw ADB ──
                "shell_command" -> shizukuManager.executeShellCommand(
                    command.params["command"]!!.jsonPrimitive.content
                )

                // ── Wait ──
                "wait" -> {
                    delay(command.params["ms"]?.jsonPrimitive?.int?.toLong() ?: 1000L)
                    CommandResult(success = true, output = "waited")
                }

                else -> CommandResult(success = false, error = "Unknown action: ${command.action}")
            }
        } catch (e: Exception) {
            Log.e(TAG, "Command execution error: ${e.message}", e)
            CommandResult(success = false, error = e.message ?: "Execution error")
        }

        // Send result back to server
        try {
            serverClient.sendResult(
                commandId         = command.commandId,
                taskId            = command.taskId,
                success           = result.success,
                screenshotB64     = result.screenshotB64 ?: "",
                // Primary: structured Shizuku data (from collect_state)
                structuredDataJson = if (command.action == "collect_state") result.output ?: "" else "",
                installedApps     = result.installedApps,
                deviceInfo        = buildDeviceInfo(),
                output            = if (command.action != "collect_state") result.output ?: "" else "",
                error             = result.error ?: "",
            )
        } catch (e: Exception) {
            Log.e(TAG, "Failed to send result: ${e.message}")
        }

    }

    /**
     * PRIMARY data collection: full structured device state via Shizuku.
     * Sends UI hierarchy, foreground app, elements, keyboard state.
     * Screenshot is ALSO captured if include_screenshot=true in params.
     */
    private suspend fun handleCollectState(command: ServerClient.Command): CommandResult {
        val includeScreenshot = command.params["include_screenshot"]?.jsonPrimitive?.booleanOrNull ?: false
        val payload = dataCollector.buildServerPayload(includeScreenshot = includeScreenshot)

        val screenshotB64 = if (includeScreenshot) screenController.captureBase64() else ""
        val apps = dataCollector.getAllInstalledApps().take(60).map { "${it.label} (${it.packageName})" }

        // Serialize payload to JSON string for the output field
        val payloadJson = buildJsonObject {
            payload.forEach { (k, v) ->
                when (v) {
                    is String  -> put(k, v)
                    is Boolean -> put(k, v)
                    is Int     -> put(k, v)
                    is List<*> -> put(k, buildJsonArray { v.forEach { item ->
                        when (item) {
                            is String -> add(item)
                            is Map<*, *> -> add(buildJsonObject {
                                @Suppress("UNCHECKED_CAST")
                                (item as Map<String, Any>).forEach { (mk, mv) ->
                                    when (mv) {
                                        is String  -> put(mk, mv)
                                        is Boolean -> put(mk, mv)
                                        is Int     -> put(mk, mv)
                                        else       -> put(mk, mv.toString())
                                    }
                                }
                            })
                            else -> add(item.toString())
                        }
                    }})
                    else -> put(k, v.toString())
                }
            }
        }.toString()

        return CommandResult(
            success       = true,
            output        = payloadJson,
            screenshotB64 = screenshotB64,
            installedApps = apps,
        )
    }

    /** FALLBACK: screenshot-only collection. */
    private suspend fun handleScreenshot(command: ServerClient.Command): CommandResult {
        val b64 = screenController.captureBase64()
        val apps = appController.getInstalledApps().installedApps.take(50)
        return CommandResult(
            success = b64.isNotEmpty(),
            screenshotB64 = b64,
            installedApps = apps,
        )
    }

    /** Find a UI element by text and tap it directly (no screenshot needed). */
    private suspend fun handleFindElement(searchText: String): CommandResult {
        val element = dataCollector.findClickableElement(searchText)
        return if (element != null) {
            CommandResult(success = true, output = "Found '${element.text}' at (${element.x}, ${element.y}) — tapping")
                .also { touchController.tap(element.x, element.y) }
        } else {
            CommandResult(success = false, error = "Element '$searchText' not found on screen")
        }
    }

    /** Tap a UI element by searching for its text. */
    private suspend fun handleTapElement(text: String): CommandResult {
        val element = dataCollector.findClickableElement(text)
        return if (element != null) {
            touchController.tap(element.x, element.y)
            CommandResult(success = true, output = "Tapped '${element.text}' at (${element.x}, ${element.y})")
        } else {
            CommandResult(success = false, error = "Element '$text' not found — try tap with coordinates instead")
        }
    }

    private fun buildDeviceInfo(): Map<String, String> = mapOf(
        "model" to android.os.Build.MODEL,
        "android" to android.os.Build.VERSION.RELEASE,
        "sdk" to android.os.Build.VERSION.SDK_INT.toString(),
        "shizuku" to shizukuManager.isShizukuAvailable().toString(),
    )

    // ─── Notification ─────────────────────────────────────────────────────────

    private fun createNotificationChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Matchai Agent",
            NotificationManager.IMPORTANCE_LOW,
        ).apply { description = "AI Agent running in background" }
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun buildNotification(status: String): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("🤖 Matchai Agent")
            .setContentText(status)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setOngoing(true)
            .setSilent(true)
            .build()
    }

    private fun updateNotification(status: String) {
        getSystemService(NotificationManager::class.java)
            .notify(NOTIF_ID, buildNotification(status))
    }
}

/** Simple result data class for command execution. */
data class CommandResult(
    val success: Boolean,
    val output: String? = null,
    val error: String? = null,
    val screenshotB64: String? = null,
    val installedApps: List<String> = emptyList(),
)
