package com.matchai.agent.control

import android.util.Log
import com.matchai.agent.CommandResult
import com.matchai.agent.shizuku.ShizukuManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

/**
 * FileController — Full file system access via Shizuku.
 * Provides read, write, copy, delete, list, and media retrieval.
 */
class FileController(private val shizuku: ShizukuManager) {

    companion object {
        private const val TAG = "FileController"
        private const val TEMP_DIR = "/sdcard/matchai_temp/"
    }

    // ─── Directory Operations ──────────────────────────────────────────────────

    suspend fun listDirectory(path: String = "/sdcard/"): CommandResult {
        Log.d(TAG, "ls $path")
        return shizuku.executeShellCommand("ls -la '$path' 2>&1 | head -60")
    }

    suspend fun listDownloads(): CommandResult {
        return shizuku.executeShellCommand("ls -la /sdcard/Download/ 2>&1 | head -40")
    }

    suspend fun listDCIM(): CommandResult {
        return shizuku.executeShellCommand("ls -lt /sdcard/DCIM/Camera/ 2>&1 | head -20")
    }

    suspend fun getStorageInfo(): CommandResult {
        return shizuku.executeShellCommand("df -h /sdcard && echo '---' && du -sh /sdcard/*/  2>&1")
    }

    // ─── File Read/Write ───────────────────────────────────────────────────────

    suspend fun readTextFile(path: String, maxLines: Int = 100): CommandResult {
        return shizuku.executeShellCommand("head -n $maxLines '$path' 2>&1")
    }

    suspend fun writeTextFile(path: String, content: String): CommandResult {
        val escaped = content.replace("'", "'\\''")
        return shizuku.executeShellCommand("echo '$escaped' > '$path' 2>&1")
    }

    suspend fun appendToFile(path: String, content: String): CommandResult {
        val escaped = content.replace("'", "'\\''")
        return shizuku.executeShellCommand("echo '$escaped' >> '$path' 2>&1")
    }

    // ─── File Operations ───────────────────────────────────────────────────────

    suspend fun copyFile(src: String, dst: String): CommandResult {
        Log.d(TAG, "cp '$src' '$dst'")
        return shizuku.executeShellCommand("cp -f '$src' '$dst' 2>&1")
    }

    suspend fun moveFile(src: String, dst: String): CommandResult {
        return shizuku.executeShellCommand("mv -f '$src' '$dst' 2>&1")
    }

    suspend fun deleteFile(path: String): CommandResult {
        Log.w(TAG, "rm '$path'")
        return shizuku.executeShellCommand("rm -f '$path' 2>&1")
    }

    suspend fun createDirectory(path: String): CommandResult {
        return shizuku.executeShellCommand("mkdir -p '$path' 2>&1")
    }

    suspend fun fileExists(path: String): Boolean {
        val result = shizuku.executeShellCommand("[ -f '$path' ] && echo yes || echo no")
        return result.output.trim() == "yes"
    }

    suspend fun getFileSize(path: String): Long {
        val result = shizuku.executeShellCommand("stat -c %s '$path' 2>/dev/null || echo 0")
        return result.output.trim().toLongOrNull() ?: 0L
    }

    // ─── Media Files ───────────────────────────────────────────────────────────

    /**
     * Get the most recently taken photo as base64.
     */
    suspend fun getLatestPhoto(): CommandResult {
        // Find the newest file in DCIM/Camera
        val findResult = shizuku.executeShellCommand(
            "ls -t /sdcard/DCIM/Camera/*.jpg 2>/dev/null | head -1"
        )
        val latestPath = findResult.output.trim()
        if (latestPath.isEmpty()) {
            return CommandResult(success = false, error = "No photos found")
        }
        return shizuku.executeShellCommand(
            "base64 '$latestPath' 2>&1"
        ).let { result ->
            result.copy(output = "photo:$latestPath|${result.output}")
        }
    }

    /**
     * Get latest screenshot from Pictures/Screenshots.
     */
    suspend fun getLatestScreenshot(): CommandResult {
        val findResult = shizuku.executeShellCommand(
            "ls -t /sdcard/Pictures/Screenshots/*.png 2>/dev/null | head -1"
        )
        val path = findResult.output.trim()
        if (path.isEmpty()) {
            return CommandResult(success = false, error = "No screenshots found")
        }
        return shizuku.executeShellCommand("base64 '$path' 2>&1")
    }

    /**
     * Share a file with another app via Android intent.
     */
    suspend fun shareFileWithApp(filePath: String, targetPackage: String): CommandResult {
        val mimeGuess = when {
            filePath.endsWith(".jpg", true) || filePath.endsWith(".png", true) -> "image/*"
            filePath.endsWith(".pdf", true) -> "application/pdf"
            filePath.endsWith(".txt", true) -> "text/plain"
            else -> "*/*"
        }
        return shizuku.executeShellCommand(
            "am start -a android.intent.action.SEND " +
            "-t '$mimeGuess' " +
            "--eu android.intent.extra.STREAM 'file://$filePath' " +
            "-p '$targetPackage' " +
            "--grant-read-uri-permission 2>&1"
        )
    }

    // ─── App Data ──────────────────────────────────────────────────────────────

    suspend fun getAppDataPath(packageName: String): String {
        val result = shizuku.executeShellCommand(
            "pm path $packageName | head -1"
        )
        return result.output.removePrefix("package:").trim()
    }

    suspend fun getAppSizeInfo(packageName: String): CommandResult {
        return shizuku.executeShellCommand(
            "du -sh /data/data/$packageName/ 2>/dev/null || echo 'No access'"
        )
    }

    // ─── Temp Space Management ─────────────────────────────────────────────────

    suspend fun ensureTempDir(): CommandResult {
        return shizuku.executeShellCommand("mkdir -p $TEMP_DIR 2>&1")
    }

    suspend fun cleanTempDir(): CommandResult {
        return shizuku.executeShellCommand("rm -rf ${TEMP_DIR}* 2>&1")
    }
}
