package com.mangastudio.mobile

import android.app.Activity
import android.content.ContentValues
import android.net.Uri
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.webkit.URLUtil
import android.widget.Toast
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL

/**
 * DownloadHelper - Salva CBZ/ZIP gerados pelo servidor local na pasta Download/MangaStudio.
 * A WebView não baixa arquivos sozinha; sem isto os botões de download não faziam nada.
 * Regra de Ouro: Coeso, modular e estritamente < 300 linhas.
 */
object DownloadHelper {

    private const val SUBFOLDER = "MangaStudio"

    fun download(activity: Activity, url: String, contentDisposition: String?, mimeType: String?) {
        val name = URLUtil.guessFileName(url, contentDisposition, mimeType)
        Toast.makeText(activity, "Baixando $name...", Toast.LENGTH_SHORT).show()

        Thread {
            val message = try {
                val conn = URL(withToken(url)).openConnection() as HttpURLConnection
                conn.connectTimeout = 10_000
                conn.readTimeout = 300_000
                try {
                    if (conn.responseCode != 200) throw IOException("HTTP ${conn.responseCode}")
                    conn.inputStream.use { save(activity, name, it) }
                } finally {
                    conn.disconnect()
                }
                "Salvo em Download/$SUBFOLDER/$name"
            } catch (e: Exception) {
                "Falha ao baixar $name: ${e.localizedMessage}"
            }
            activity.runOnUiThread { Toast.makeText(activity, message, Toast.LENGTH_LONG).show() }
        }.start()
    }

    /** Downloads saem da WebView sem cookie; anexamos o token da sessão para o servidor aceitar. */
    private fun withToken(url: String): String {
        val uri = Uri.parse(url)
        if (uri.host != "127.0.0.1" && uri.host != "localhost") return url
        if (uri.getQueryParameter("token") != null) return url
        return uri.buildUpon().appendQueryParameter("token", MangaServerService.sessionToken).build().toString()
    }

    private fun save(activity: Activity, name: String, input: InputStream) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val values = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, name)
                // octet-stream evita que o Android troque ".cbz" por ".zip"
                put(MediaStore.Downloads.MIME_TYPE, "application/octet-stream")
                put(MediaStore.Downloads.RELATIVE_PATH, "${Environment.DIRECTORY_DOWNLOADS}/$SUBFOLDER")
            }
            val resolver = activity.contentResolver
            val target = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)
                ?: throw IOException("Não foi possível criar o arquivo em Downloads")
            resolver.openOutputStream(target)?.use { input.copyTo(it) }
                ?: throw IOException("Não foi possível gravar em Downloads")
        } else {
            @Suppress("DEPRECATION")
            val dir = File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS), SUBFOLDER)
            dir.mkdirs()
            FileOutputStream(File(dir, name)).use { input.copyTo(it) }
        }
    }
}
