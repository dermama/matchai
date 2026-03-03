package com.matchai.agent.control

import android.util.Log
import com.matchai.agent.CommandResult
import com.matchai.agent.shizuku.ShizukuManager
import kotlinx.coroutines.delay

/**
 * GestureController — Complex multi-step gesture sequences.
 * Supports pinch, multi-point, macros, and pattern gestures.
 */
class GestureController(private val shizuku: ShizukuManager) {

    companion object { private const val TAG = "GestureController" }

    // ─── Zoom Gestures ─────────────────────────────────────────────────────────

    /** Pinch zoom in (spread fingers) centered at x,y */
    suspend fun pinchZoomIn(cx: Int, cy: Int, spread: Int = 300): CommandResult {
        Log.d(TAG, "pinchZoomIn at ($cx,$cy) spread=$spread")
        // Execute first finger movement, brief delay, then second
        shizuku.executeShellCommand(
            "input swipe ${cx - spread/4} $cy ${cx - spread} $cy 400"
        )
        delay(50)
        return shizuku.executeShellCommand(
            "input swipe ${cx + spread/4} $cy ${cx + spread} $cy 400"
        )
    }

    /** Pinch zoom out (bring fingers together) */
    suspend fun pinchZoomOut(cx: Int, cy: Int, spread: Int = 300): CommandResult {
        Log.d(TAG, "pinchZoomOut at ($cx,$cy)")
        shizuku.executeShellCommand(
            "input swipe ${cx - spread} $cy ${cx - spread/4} $cy 400"
        )
        delay(50)
        return shizuku.executeShellCommand(
            "input swipe ${cx + spread} $cy ${cx + spread/4} $cy 400"
        )
    }

    // ─── Multi-direction Swipes ────────────────────────────────────────────────

    suspend fun swipeLeft(startX: Int = 900, y: Int = 960, distance: Int = 600): CommandResult {
        return shizuku.executeShellCommand("input swipe $startX $y ${startX - distance} $y 300")
    }

    suspend fun swipeRight(startX: Int = 180, y: Int = 960, distance: Int = 600): CommandResult {
        return shizuku.executeShellCommand("input swipe $startX $y ${startX + distance} $y 300")
    }

    suspend fun swipeDownFromTop(): CommandResult {
        // Pull down notification shade from very top
        return shizuku.executeShellCommand("input swipe 540 50 540 900 300")
    }

    suspend fun swipeUpFromBottom(): CommandResult {
        // Swipe up from bottom for gesture navigation
        return shizuku.executeShellCommand("input swipe 540 1850 540 900 250")
    }

    // ─── Fling (fast scroll) ──────────────────────────────────────────────────

    suspend fun flingUp(x: Int = 540): CommandResult {
        return shizuku.executeShellCommand("input swipe $x 1400 $x 200 150")
    }

    suspend fun flingDown(x: Int = 540): CommandResult {
        return shizuku.executeShellCommand("input swipe $x 200 $x 1600 150")
    }

    // ─── Macro System ─────────────────────────────────────────────────────────

    data class GestureStep(
        val type: String,       // tap, swipe, wait, key
        val x: Int = 0, val y: Int = 0,
        val x2: Int = 0, val y2: Int = 0,
        val duration: Int = 300,
        val keycode: String = "",
        val waitMs: Long = 0,
    )

    /**
     * Execute a macro: a sequence of gestures with precise timing.
     * Used for complex multi-step UI interactions.
     */
    suspend fun executeMacro(
        steps: List<GestureStep>,
        name: String = "macro",
    ): CommandResult {
        Log.i(TAG, "▶ Executing macro '$name' (${steps.size} steps)")
        var lastResult = CommandResult(success = true, output = "started")

        for ((index, step) in steps.withIndex()) {
            Log.d(TAG, "Macro step ${index+1}/${steps.size}: ${step.type}")
            lastResult = when (step.type) {
                "tap"      -> shizuku.executeShellCommand("input tap ${step.x} ${step.y}")
                "swipe"    -> shizuku.executeShellCommand(
                    "input swipe ${step.x} ${step.y} ${step.x2} ${step.y2} ${step.duration}"
                )
                "key"      -> shizuku.executeShellCommand("input keyevent ${step.keycode}")
                "wait"     -> {
                    delay(step.waitMs)
                    CommandResult(success = true, output = "waited ${step.waitMs}ms")
                }
                "long_tap" -> shizuku.executeShellCommand(
                    "input swipe ${step.x} ${step.y} ${step.x} ${step.y} 1200"
                )
                else -> CommandResult(success = false, error = "Unknown step type: ${step.type}")
            }
            if (!lastResult.success) {
                Log.w(TAG, "Macro step ${index+1} failed: ${lastResult.error}")
            }
        }
        return lastResult.copy(output = "Macro '$name' completed ${steps.size} steps")
    }

    // ─── Common Pre-built Macros ───────────────────────────────────────────────

    /** Take a screenshot using hardware buttons */
    suspend fun takeScreenshotHardware(): CommandResult {
        return executeMacro(
            name = "hardware_screenshot",
            steps = listOf(
                GestureStep("key", keycode = "KEYCODE_POWER"),
                GestureStep("wait", waitMs = 50),
                GestureStep("key", keycode = "KEYCODE_VOLUME_DOWN"),
            )
        )
    }

    /** Force-unlock screen if device is locked */
    suspend fun unlockScreen(): CommandResult {
        return executeMacro(
            name = "unlock_screen",
            steps = listOf(
                GestureStep("key", keycode = "KEYCODE_WAKEUP"),
                GestureStep("wait", waitMs = 500),
                GestureStep("swipe", x = 540, y = 1800, x2 = 540, y2 = 800, duration = 300),
            )
        )
    }

    /** Multi-select items in a list (long press first, then tap others) */
    suspend fun multiSelectItems(positions: List<Pair<Int,Int>>): CommandResult {
        if (positions.isEmpty()) return CommandResult(success = false, error = "No positions")
        val steps = mutableListOf(
            GestureStep("long_tap", x = positions[0].first, y = positions[0].second)
        )
        for (pos in positions.drop(1)) {
            steps.add(GestureStep("wait", waitMs = 200))
            steps.add(GestureStep("tap", x = pos.first, y = pos.second))
        }
        return executeMacro(steps, "multi_select_${positions.size}")
    }
}
