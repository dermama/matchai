package com.matchai.agent.control

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.util.Log
import com.matchai.agent.CommandResult
import com.matchai.agent.shizuku.ShizukuManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext

class TextController(
    private val shizuku: ShizukuManager,
    private val context: Context? = null,
) {
    companion object { private const val TAG = "TextController" }

    /**
     * Type ASCII/English text via ADB input.
     * For Arabic or special chars, use typeViaClipboard.
     */
    suspend fun typeText(text: String): CommandResult {
        Log.d(TAG, "typeText: ${text.take(30)}")
        // Escape special shell chars
        val escaped = text
            .replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\"", "\\\"")
            .replace(" ", "%s")
            .replace("&", "\\&")
        return shizuku.executeShellCommand("input text '$escaped'")
    }

    /**
     * Type any text (including Arabic/Unicode) by setting clipboard then pasting.
     * Most reliable method for multilingual text.
     */
    suspend fun typeViaClipboard(text: String): CommandResult {
        Log.d(TAG, "typeViaClipboard: ${text.take(30)}")
        return withContext(Dispatchers.Main) {
            try {
                // Set clipboard content
                val cm = context?.getSystemService(Context.CLIPBOARD_SERVICE) as? ClipboardManager
                if (cm != null) {
                    cm.setPrimaryClip(ClipData.newPlainText("matchai", text))
                } else {
                    // Fallback: use ADB clipboard command
                    val escaped = text.replace("'", "\\'")
                    shizuku.executeShellCommand(
                        "am broadcast -a clipper.set -e text '$escaped'"
                    )
                }
                delay(150)

                // Paste (Ctrl+V)
                withContext(Dispatchers.IO) {
                    shizuku.executeShellCommand(
                        "input keyevent --longpress KEYCODE_CTRL_LEFT KEYCODE_V"
                    )
                }
                CommandResult(success = true, output = "pasted via clipboard")
            } catch (e: Exception) {
                CommandResult(success = false, error = e.message)
            }
        }
    }

    suspend fun clearField(): CommandResult {
        // Select all then delete
        shizuku.executeShellCommand(
            "input keyevent --longpress KEYCODE_CTRL_LEFT KEYCODE_A"
        )
        delay(100)
        return shizuku.executeShellCommand("input keyevent KEYCODE_DEL")
    }

    suspend fun selectAll(): CommandResult =
        shizuku.executeShellCommand(
            "input keyevent --longpress KEYCODE_CTRL_LEFT KEYCODE_A"
        )

    suspend fun copySelected(): CommandResult =
        shizuku.executeShellCommand(
            "input keyevent --longpress KEYCODE_CTRL_LEFT KEYCODE_C"
        )
}
