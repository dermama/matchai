package com.matchai.agent.control

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Base64
import android.util.Log
import com.matchai.agent.CommandResult
import com.matchai.agent.shizuku.ShizukuManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream
import java.io.File

class ScreenController(
    private val shizuku: ShizukuManager,
    private val context: Context,
) {
    companion object {
        private const val TAG = "ScreenController"
    }

    /** Capture screen using ADB screencap and return base64. */
    suspend fun captureBase64(): String = withContext(Dispatchers.IO) {
        try {
            // Use screencap and pipe directly to base64 to avoid all /sdcard/ permission issues
            val result = shizuku.executeShellCommand("screencap -p | base64")
            if (!result.success || result.output.isNullOrBlank()) {
                Log.e(TAG, "screencap failed: ${result.error}")
                return@withContext ""
            }

            // Decode the shell base64 output into a byte array
            val cleanBase64 = result.output.replace("\n", "").replace("\r", "")
            val imageBytes = Base64.decode(cleanBase64, Base64.DEFAULT)
            
            // Decode to bitmap
            val bitmap = BitmapFactory.decodeByteArray(imageBytes, 0, imageBytes.size) ?: return@withContext ""

            // Compress for faster transmission (scale down if very large)
            val maxDim = 1080
            val scaledBitmap = if (bitmap.width > maxDim || bitmap.height > maxDim) {
                val scale = maxDim.toFloat() / maxOf(bitmap.width, bitmap.height)
                Bitmap.createScaledBitmap(
                    bitmap,
                    (bitmap.width * scale).toInt(),
                    (bitmap.height * scale).toInt(),
                    true,
                )
            } else bitmap

            // Re-encode scaled bitmap to JPEG base64
            val stream = ByteArrayOutputStream()
            scaledBitmap.compress(Bitmap.CompressFormat.JPEG, 85, stream)
            val finalB64 = Base64.encodeToString(stream.toByteArray(), Base64.NO_WRAP)

            finalB64
        } catch (e: Exception) {
            Log.e(TAG, "capture error: ${e.message}")
            ""
        }
    }

    /** Get device screen dimensions. */
    fun getScreenSize(): Pair<Int, Int> {
        return try {
            val wm = context.getSystemService(Context.WINDOW_SERVICE) as android.view.WindowManager
            val metrics = wm.currentWindowMetrics
            Pair(metrics.bounds.width(), metrics.bounds.height())
        } catch (e: Exception) {
            Pair(1080, 1920) // default
        }
    }
}
