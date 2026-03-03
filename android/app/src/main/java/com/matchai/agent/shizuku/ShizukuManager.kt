package com.matchai.agent.shizuku

import android.content.Context
import android.content.pm.PackageManager
import android.util.Log
import com.matchai.agent.CommandResult
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import rikka.shizuku.Shizuku

/**
 * ShizukuManager — Core bridge to ADB-level permissions.
 * All privileged operations flow through here.
 */
class ShizukuManager(private val context: Context) {

    companion object {
        private const val TAG = "Shizuku"
        private const val REQUEST_CODE = 1001
    }

    fun isShizukuAvailable(): Boolean {
        return try {
            Shizuku.pingBinder() &&
                Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED
        } catch (e: Exception) {
            false
        }
    }

    fun requestPermission(callback: (Boolean) -> Unit) {
        if (!Shizuku.pingBinder()) {
            callback(false)
            return
        }
        if (Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED) {
            callback(true)
            return
        }
        val listener = object : Shizuku.OnRequestPermissionResultListener {
            override fun onRequestPermissionResult(requestCode: Int, grantResult: Int) {
                Shizuku.removeRequestPermissionResultListener(this)
                callback(grantResult == PackageManager.PERMISSION_GRANTED)
            }
        }
        Shizuku.addRequestPermissionResultListener(listener)
        Shizuku.requestPermission(REQUEST_CODE)
    }

    /**
     * Execute any ADB shell command via Shizuku.
     * This is the primary method for all device control operations.
     */
    suspend fun executeShellCommand(command: String): CommandResult {
        return withContext(Dispatchers.IO) {
            Log.d(TAG, "$ $command")
            try {
                if (!isShizukuAvailable()) {
                    return@withContext CommandResult(
                        success = false,
                        error = "Shizuku not available"
                    )
                }

                val process = Shizuku.newProcess(
                    arrayOf("sh", "-c", command),
                    null as Array<String>?,
                    null as String?
                )

                val output = process.inputStream.bufferedReader().readText()
                val error = process.errorStream.bufferedReader().readText()
                val exitCode = process.waitFor()

                Log.d(TAG, "Exit: $exitCode | Out: ${output.take(100)}")

                CommandResult(
                    success = exitCode == 0,
                    output = output.trim(),
                    error = if (error.isBlank()) null else error.trim(),
                )
            } catch (e: Exception) {
                Log.e(TAG, "Shell command error: ${e.message}")
                CommandResult(success = false, error = e.message)
            }
        }
    }

    /**
     * Execute multiple commands in sequence.
     */
    suspend fun executeCommands(vararg commands: String): List<CommandResult> {
        return commands.map { executeShellCommand(it) }
    }
}
