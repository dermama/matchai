package com.matchai.agent.control

import android.util.Log
import com.matchai.agent.CommandResult
import com.matchai.agent.shizuku.ShizukuManager
import kotlinx.coroutines.delay

class TouchController(private val shizuku: ShizukuManager) {

    companion object { private const val TAG = "TouchController" }

    suspend fun tap(x: Int, y: Int): CommandResult {
        Log.d(TAG, "tap($x, $y)")
        return shizuku.executeShellCommand("input tap $x $y")
    }

    suspend fun swipe(x1: Int, y1: Int, x2: Int, y2: Int, durationMs: Int = 300): CommandResult {
        Log.d(TAG, "swipe($x1,$y1 → $x2,$y2 ${durationMs}ms)")
        return shizuku.executeShellCommand("input swipe $x1 $y1 $x2 $y2 $durationMs")
    }

    suspend fun longPress(x: Int, y: Int): CommandResult {
        Log.d(TAG, "longPress($x, $y)")
        return shizuku.executeShellCommand("input swipe $x $y $x $y 1000")
    }

    suspend fun doubleTap(x: Int, y: Int): CommandResult {
        shizuku.executeShellCommand("input tap $x $y")
        delay(100)
        return shizuku.executeShellCommand("input tap $x $y")
    }

    suspend fun pressBack(): CommandResult =
        shizuku.executeShellCommand("input keyevent KEYCODE_BACK")

    suspend fun pressHome(): CommandResult =
        shizuku.executeShellCommand("input keyevent KEYCODE_HOME")

    suspend fun pressRecents(): CommandResult =
        shizuku.executeShellCommand("input keyevent KEYCODE_APP_SWITCH")

    suspend fun openNotifications(): CommandResult =
        shizuku.executeShellCommand("cmd statusbar expand-notifications")

    suspend fun closeNotifications(): CommandResult =
        shizuku.executeShellCommand("cmd statusbar collapse")

    suspend fun scrollDown(x: Int = 540, startY: Int = 1400, endY: Int = 400): CommandResult =
        swipe(x, startY, x, endY, 400)

    suspend fun scrollUp(x: Int = 540, startY: Int = 400, endY: Int = 1400): CommandResult =
        swipe(x, startY, x, endY, 400)

    suspend fun pressKey(keycode: String): CommandResult =
        shizuku.executeShellCommand("input keyevent $keycode")

    suspend fun pressEnter(): CommandResult = pressKey("KEYCODE_ENTER")
    suspend fun pressSearch(): CommandResult = pressKey("KEYCODE_SEARCH")
}
