package com.matchai.agent.network

import android.util.Log
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.*
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

/**
 * ServerClient — Communicates with the Railway backend.
 * Uses long-polling to receive commands and POSTs results.
 */
class ServerClient(
    val serverUrl: String,
    private val deviceSecret: String,
) {
    companion object { private const val TAG = "ServerClient" }

    private val json = Json { ignoreUnknownKeys = true; isLenient = true }
    private val jsonMedia = "application/json".toMediaType()

    /** Long-polling client (waits up to 35s) */
    private val pollClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(35, TimeUnit.SECONDS)
        .writeTimeout(10, TimeUnit.SECONDS)
        .build()

    /** Regular client for POSTs */
    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .writeTimeout(10, TimeUnit.SECONDS)
        .build()

    // ─── Data classes ─────────────────────────────────────────────────────────

    @Serializable data class PollResponse(
        @kotlinx.serialization.SerialName("has_command")
        val has_command: Boolean,
        val command: Command?,
    )

    @Serializable data class Command(
        @kotlinx.serialization.SerialName("command_id")
        val commandId: String,
        @kotlinx.serialization.SerialName("task_id")
        val taskId: String,
        val action: String,
        val params: JsonObject = JsonObject(emptyMap()),
        @kotlinx.serialization.SerialName("step_id")
        val stepId: JsonElement = JsonNull,
    )

    // ─── API Methods ──────────────────────────────────────────────────────────

    suspend fun pollForCommand(): PollResponse? = withContext(Dispatchers.IO) {
        try {
            val request = Request.Builder()
                .url("$serverUrl/device/poll")
                .get()
                .header("X-Device-Secret", deviceSecret)
                .build()
            val response = pollClient.newCall(request).execute()
            if (!response.isSuccessful) return@withContext null
            val body = response.body?.string() ?: return@withContext null
            json.decodeFromString<PollResponse>(body)
        } catch (e: Exception) {
            Log.d(TAG, "Poll timeout/error (normal): ${e.message}")
            null
        }
    }

    suspend fun sendResult(
        commandId: String,
        taskId: String,
        success: Boolean,
        screenshotB64: String = "",
        structuredDataJson: String = "",  // Primary: Shizuku structured data from collect_state
        installedApps: List<String> = emptyList(),
        deviceInfo: Map<String, String> = emptyMap(),
        output: String = "",
        error: String = "",
    ) = withContext(Dispatchers.IO) {
        val payload = buildJsonObject {
            put("command_id", commandId)
            put("task_id", taskId)
            put("success", success)
            put("screenshot_b64", screenshotB64)
            // Parse and embed structured data if available
            if (structuredDataJson.isNotEmpty()) {
                try {
                    val parsedData = Json.parseToJsonElement(structuredDataJson)
                    put("structured_data", parsedData)
                } catch (e: Exception) {
                    put("structured_data", buildJsonObject { put("raw", structuredDataJson.take(500)) })
                }
            }
            put("installed_apps", buildJsonArray { installedApps.forEach { add(it) } })
            put("device_info", buildJsonObject { deviceInfo.forEach { (k, v) -> put(k, v) } })
            put("output", output)
            put("error", error)
            put("timestamp", System.currentTimeMillis())
        }
        val request = Request.Builder()
            .url("$serverUrl/device/result")
            .post(payload.toString().toRequestBody(jsonMedia))
            .header("X-Device-Secret", deviceSecret)
            .build()
        try {
            val response = client.newCall(request).execute()
            Log.d(TAG, "Result sent: ${response.code}")
        } catch (e: Exception) {
            Log.e(TAG, "Result send failed: ${e.message}")
        }
    }


    suspend fun registerDevice(
        deviceId: String,
        androidVersion: String,
        shizukuActive: Boolean,
        screenWidth: Int,
        screenHeight: Int,
    ) = withContext(Dispatchers.IO) {
        val payload = buildJsonObject {
            put("device_id", deviceId)
            put("android_version", androidVersion)
            put("shizuku_active", shizukuActive)
            put("screen_width", screenWidth)
            put("screen_height", screenHeight)
        }
        val request = Request.Builder()
            .url("$serverUrl/device/register")
            .post(payload.toString().toRequestBody(jsonMedia))
            .header("X-Device-Secret", deviceSecret)
            .build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                val errorBody = response.body?.string() ?: ""
                throw Exception("HTTP ${response.code}: $errorBody")
            }
            Log.i(TAG, "Device registered: ${response.code}")
        }
    }
}
