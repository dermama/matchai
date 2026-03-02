package com.matchai.agent.accessibility

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.content.Intent
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import android.util.Log

/**
 * AgentAccessibilityService — Provides screen content reading capability.
 * Complements Shizuku for deeper UI understanding.
 */
class AgentAccessibilityService : AccessibilityService() {

    companion object {
        private const val TAG = "AccessibilityService"
        var instance: AgentAccessibilityService? = null
            private set
    }

    override fun onServiceConnected() {
        instance = this
        Log.i(TAG, "✅ Accessibility Service connected")

        serviceInfo = serviceInfo.apply {
            feedbackType = AccessibilityServiceInfo.FEEDBACK_GENERIC
            flags = AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS or
                    AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS or
                    AccessibilityServiceInfo.FLAG_REQUEST_FILTER_KEY_EVENTS
            eventTypes = AccessibilityEvent.TYPES_ALL_MASK
            notificationTimeout = 100
        }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        // Events processed on demand, no continuous processing needed
    }

    override fun onInterrupt() {
        Log.w(TAG, "⚠️ Accessibility Service interrupted")
    }

    override fun onDestroy() {
        instance = null
        super.onDestroy()
    }

    /** Get all visible text on screen. */
    fun getScreenText(): String {
        val root = rootInActiveWindow ?: return ""
        val sb = StringBuilder()
        extractText(root, sb)
        return sb.toString()
    }

    private fun extractText(node: AccessibilityNodeInfo, sb: StringBuilder) {
        if (!node.text.isNullOrEmpty()) {
            sb.append(node.text).append("\n")
        }
        if (!node.contentDescription.isNullOrEmpty()) {
            sb.append("[${node.contentDescription}]\n")
        }
        for (i in 0 until node.childCount) {
            node.getChild(i)?.let { extractText(it, sb) }
        }
    }

    /** Find a node by text content. */
    fun findNodeByText(text: String): AccessibilityNodeInfo? {
        val root = rootInActiveWindow ?: return null
        return root.findAccessibilityNodeInfosByText(text)?.firstOrNull()
    }

    /** Get bounds of a node in screen coordinates. */
    fun getNodeBounds(node: AccessibilityNodeInfo): android.graphics.Rect {
        val rect = android.graphics.Rect()
        node.getBoundsInScreen(rect)
        return rect
    }
}
