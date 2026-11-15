package com.mangastudio.mobile

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform

/**
 * MangaServerService - Mantém o servidor Python ativo em segundo plano enquanto processa mangás.
 * Regra de Ouro: Coeso, modular e estritamente < 300 linhas.
 */
class MangaServerService : Service() {

    private val CHANNEL_ID = "manga_studio_service_channel"
    private val NOTIF_ID = 2026
    private var serverThread: Thread? = null

    companion object {
        var isServerReady = false
            private set

        fun start(context: Context) {
            val intent = Intent(context, MangaServerService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }
    }

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        startForeground(NOTIF_ID, buildNotification("Iniciando servidor local..."))
        startPythonServer()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Manga Studio Motor de Tradução",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Mantém o serviço de IA e edição de mangás ativo"
            }
            val manager = getSystemService(NotificationManager::class.java)
            manager?.createNotificationChannel(channel)
        }
    }

    private fun buildNotification(text: String): Notification {
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("Manga Studio Mobile")
            .setContentText(text)
            .setSmallIcon(android.R.drawable.ic_menu_agenda)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .build()
    }

    private fun startPythonServer() {
        serverThread = Thread {
            try {
                if (!Python.isStarted()) {
                    Python.start(AndroidPlatform(applicationContext))
                }
                val py = Python.getInstance()
                val serverMod = py.getModule("mobile_server")
                isServerReady = true

                updateNotification("Pronto para traduzir mangás")
                serverMod.callAttr("start_server", 5000)
            } catch (e: Exception) {
                e.printStackTrace()
                isServerReady = false
                updateNotification("Erro no servidor: ${e.localizedMessage}")
            }
        }.apply {
            isDaemon = true
            name = "MangaPythonServerThread"
            start()
        }
    }

    private fun updateNotification(text: String) {
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(NOTIF_ID, buildNotification(text))
    }

    override fun onDestroy() {
        super.onDestroy()
        serverThread?.interrupt()
        serverThread = null
        isServerReady = false
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
