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
import kotlinx.coroutines.*
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
        textController = TextController(shizukuManager)
        appController = AppController(shizukuManager, this)
        systemController = SystemController(shizukuManager)

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
                "screenshot" -> handleScreenshot(command)
                "tap" -> touchController.tap(
                    command.params["x"]!!.jsonPrimitive.int,
                    command.params["y"]!!.jsonPrimitive.int,
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
                "type_text" -> textController.typeText(
                    command.params["text"]!!.jsonPrimitive.content
                )
                "type_clipboard" -> textController.typeViaClipboard(
                    command.params["text"]!!.jsonPrimitive.content
                )
                "clear_field" -> textController.clearField()
                "back" -> touchController.pressBack()
                "home" -> touchController.pressHome()
                "recents" -> touchController.pressRecents()
                "open_app" -> appController.openApp(
                    command.params["app_name"]?.jsonPrimitive?.content
                        ?: command.params["package_name"]!!.jsonPrimitive.content
                )
                "force_stop_app" -> appController.forceStop(
                    command.params["package_name"]!!.jsonPrimitive.content
                )
                "list_apps" -> appController.getInstalledApps()
                "open_notifications" -> touchController.openNotifications()
                "clear_notifications" -> systemController.clearNotifications()
                "set_volume" -> systemController.setVolume(
                    command.params["level"]!!.jsonPrimitive.int
                )
                "toggle_wifi" -> systemController.toggleWifi()
                "toggle_bluetooth" -> systemController.toggleBluetooth()
                "toggle_flashlight" -> systemController.toggleFlashlight()
                "set_brightness" -> systemController.setBrightness(
                    command.params["level"]!!.jsonPrimitive.int
                )
                "get_battery" -> systemController.getBatteryInfo()
                "get_storage" -> systemController.getStorageInfo()
                "get_running_apps" -> appController.getRunningApps()
                "shell_command" -> shizukuManager.executeShellCommand(
                    command.params["command"]!!.jsonPrimitive.content
                )
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
                commandId = command.commandId,
                taskId = command.taskId,
                success = result.success,
                screenshotB64 = result.screenshotB64 ?: "",
                installedApps = result.installedApps,
                deviceInfo = buildDeviceInfo(),
                output = result.output ?: "",
                error = result.error ?: "",
            )
        } catch (e: Exception) {
            Log.e(TAG, "Failed to send result: ${e.message}")
        }
    }

    private suspend fun handleScreenshot(command: ServerClient.Command): CommandResult {
        val b64 = screenController.captureBase64()
        val apps = appController.getInstalledApps().installedApps.take(50)
        return CommandResult(
            success = b64.isNotEmpty(),
            screenshotB64 = b64,
            installedApps = apps,
        )
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
