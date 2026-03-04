package com.matchai.agent

import android.app.AlertDialog
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.matchai.agent.network.ServerClient
import com.matchai.agent.shizuku.ShizukuManager
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import rikka.shizuku.Shizuku

class MainActivity : AppCompatActivity() {

    private lateinit var shizukuManager: ShizukuManager
    private lateinit var tvStatus: TextView
    private lateinit var tvLog: TextView
    private lateinit var etServerUrl: EditText
    private lateinit var etDeviceSecret: EditText
    private lateinit var btnSaveConfig: Button
    private lateinit var scrollView: ScrollView
    private val logBuffer = StringBuilder()

    private val logReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            val msg = intent.getStringExtra("message") ?: return
            log(msg)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        tvStatus = findViewById(R.id.tv_status)
        tvLog = findViewById(R.id.tv_log)
        scrollView = findViewById(R.id.scroll_log)
        etServerUrl = findViewById(R.id.et_server_url)
        etDeviceSecret = findViewById(R.id.et_device_secret)
        btnSaveConfig = findViewById(R.id.btn_save_config)

        shizukuManager = ShizukuManager(this)

        // Load existing config
        loadConfig()

        // Start agent service
        startAgentService()

        // UI buttons
        findViewById<View>(R.id.btn_start).setOnClickListener { startAgentService() }
        findViewById<View>(R.id.btn_check_shizuku).setOnClickListener { checkShizuku() }
        findViewById<View>(R.id.btn_accessibility).setOnClickListener { openAccessibilitySettings() }
        btnSaveConfig.setOnClickListener { saveConfig() }

        // Periodic status update
        lifecycleScope.launch {
            while (true) {
                updateStatus()
                delay(3000)
            }
        }

        log("🤖 Matchai Agent initialized")
        log("🌐 Server: ${BuildConfig.SERVER_URL}")
    }

    override fun onResume() {
        super.onResume()
        try {
            ContextCompat.registerReceiver(
                this, 
                logReceiver, 
                IntentFilter("com.matchai.agent.LOG_UPDATE"), 
                ContextCompat.RECEIVER_NOT_EXPORTED
            )
        } catch (e: Exception) {}
    }

    override fun onPause() {
        super.onPause()
        try {
            unregisterReceiver(logReceiver)
        } catch (e: Exception) {}
    }

    private fun startAgentService() {
        val intent = Intent(this, AgentService::class.java)
        ContextCompat.startForegroundService(this, intent)
        log("⏳ Requesting Agent Service to start...")
    }


    private fun checkShizuku() {
        when {
            !Shizuku.pingBinder() -> {
                log("❌ Shizuku is not running. Please start Shizuku first.")
                AlertDialog.Builder(this)
                    .setTitle("Shizuku غير نشط")
                    .setMessage("يرجى تثبيت وتفعيل تطبيق Shizuku أولاً.\n\nلتفعيله:\n1. افتح تطبيق Shizuku\n2. اتبع التعليمات لتفعيل ADB اللاسلكي\n3. عد لهذا التطبيق")
                    .setPositiveButton("تم") { d, _ -> d.dismiss() }
                    .show()
            }
            Shizuku.checkSelfPermission() != android.content.pm.PackageManager.PERMISSION_GRANTED -> {
                log("⚠️ Requesting Shizuku permission...")
                shizukuManager.requestPermission { granted ->
                    if (granted) log("✅ Shizuku permission granted!")
                    else log("❌ Shizuku permission denied")
                }
            }
            else -> log("✅ Shizuku is active and permission granted!")
        }
    }

    private fun openAccessibilitySettings() {
        val intent = Intent(android.provider.Settings.ACTION_ACCESSIBILITY_SETTINGS)
        startActivity(intent)
        log("📱 Opening Accessibility Settings...")
    }

    private fun updateStatus() {
        val shizukuOk = shizukuManager.isShizukuAvailable()
        val statusText = if (shizukuOk) "🟢 Shizuku Active" else "🔴 Shizuku Inactive"
        tvStatus.text = statusText
    }

    private fun loadConfig() {
        val prefs = getSharedPreferences("matchai_prefs", MODE_PRIVATE)
        val url = prefs.getString("server_url", BuildConfig.SERVER_URL)
        val secret = prefs.getString("device_secret", BuildConfig.DEVICE_SECRET)
        etServerUrl.setText(url)
        etDeviceSecret.setText(secret)
    }

    private fun saveConfig() {
        val url = etServerUrl.text.toString().trim()
        val secret = etDeviceSecret.text.toString().trim()

        if (url.isEmpty()) {
            log("❌ Server URL cannot be empty")
            return
        }

        getSharedPreferences("matchai_prefs", MODE_PRIVATE).edit().apply {
            putString("server_url", url)
            putString("device_secret", secret)
            apply()
        }

        log("✅ Config saved. Restarting service...")
        startAgentService()
    }

    fun log(message: String) {
        runOnUiThread {
            val timestamp = java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.getDefault())
                .format(java.util.Date())
            logBuffer.append("[$timestamp] $message\n")
            tvLog.text = logBuffer.toString()
            scrollView.post { scrollView.fullScroll(View.FOCUS_DOWN) }
        }
    }
}
