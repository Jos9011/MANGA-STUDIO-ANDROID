package com.mangastudio.mobile

import android.annotation.SuppressLint
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.webkit.*
import android.widget.LinearLayout
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import java.net.HttpURLConnection
import java.net.URL
import org.json.JSONObject

/**
 * MainActivity - Janela principal do app mobile com WebView, upload de arquivos e carregamento rápido.
 * Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
 */
class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private lateinit var loadingLayout: LinearLayout

    private val SERVER_URL = "http://127.0.0.1:5000"
    /** Primeira carga leva o token; o servidor grava um cookie e as próximas requisições já vão autenticadas. */
    private val startUrl get() = "$SERVER_URL/?token=${MangaServerService.sessionToken}"
    private var fileChooserCallback: ValueCallback<Array<Uri>>? = null
    private val mainHandler = Handler(Looper.getMainLooper())

    /** Login do Google Drive: o resultado volta para a página em window.onDriveAuthResult(ok, msg). */
    private val driveAuth = DriveAuthHelper(this) { ok, message ->
        mainHandler.post {
            if (::webView.isInitialized) {
                webView.evaluateJavascript(
                    "window.onDriveAuthResult && window.onDriveAuthResult($ok, ${JSONObject.quote(message)})", null
                )
            }
        }
    }

    private val filePickerLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == RESULT_OK) {
            val clipData = result.data?.clipData
            val dataUri = result.data?.data
            val uris = when {
                clipData != null -> Array(clipData.itemCount) { clipData.getItemAt(it).uri }
                dataUri != null -> arrayOf(dataUri)
                else -> null
            }
            fileChooserCallback?.onReceiveValue(uris)
        } else {
            fileChooserCallback?.onReceiveValue(null)
        }
        fileChooserCallback = null
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        webView = findViewById(R.id.webView)
        loadingLayout = findViewById(R.id.loadingLayout)

        setupWebView()

        PermissionHelper.requestNotificationPermission(this)
        if (!PermissionHelper.hasStoragePermission(this)) {
            PermissionHelper.requestStoragePermission(this)
        }

        MangaServerService.start(applicationContext)
        waitForServerReady()
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun setupWebView() {
        webView.isVerticalScrollBarEnabled = true
        webView.isHorizontalScrollBarEnabled = false
        webView.overScrollMode = View.OVER_SCROLL_IF_CONTENT_SCROLLS

        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = true
            allowContentAccess = true
            loadWithOverviewMode = true
            useWideViewPort = true
            builtInZoomControls = true
            displayZoomControls = false
            mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
        }

        webView.addJavascriptInterface(DriveBridge(this, driveAuth), "MangaDrive")

        webView.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                loadingLayout.visibility = View.GONE
                webView.visibility = View.VISIBLE
            }

            override fun onReceivedError(view: WebView?, request: WebResourceRequest?, error: WebResourceError?) {
                super.onReceivedError(view, request, error)
                if (request?.isForMainFrame == true) {
                    mainHandler.postDelayed({ webView.loadUrl(startUrl) }, 1500)
                }
            }
        }

        webView.setDownloadListener { url, _, contentDisposition, mimeType, _ ->
            DownloadHelper.download(this, url, contentDisposition, mimeType)
        }

        webView.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(
                wv: WebView?,
                filePathCallback: ValueCallback<Array<Uri>>?,
                fileChooserParams: FileChooserParams?
            ): Boolean {
                fileChooserCallback?.onReceiveValue(null)
                fileChooserCallback = filePathCallback
                val allowMultiple = fileChooserParams?.mode == FileChooserParams.MODE_OPEN_MULTIPLE
                val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE)
                    type = "*/*"
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    if (allowMultiple) {
                        putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
                    }
                }
                try {
                    filePickerLauncher.launch(intent)
                } catch (e: Exception) {
                    fileChooserCallback = null
                    return false
                }
                return true
            }
        }
    }


    private fun waitForServerReady() {
        Thread {
            var ready = false
            var attempts = 0
            while (!ready && attempts < 30) {
                attempts++
                try {
                    val conn = URL("$SERVER_URL/api/health").openConnection() as HttpURLConnection
                    conn.connectTimeout = 800
                    conn.readTimeout = 800
                    if (conn.responseCode == 200) {
                        ready = true
                    }
                    conn.disconnect()
                } catch (_: Exception) {}

                if (!ready) {
                    Thread.sleep(600)
                }
            }

            mainHandler.post {
                if (ready) {
                    webView.loadUrl(startUrl)
                } else {
                    Toast.makeText(this, "Aguardando inicialização do motor...", Toast.LENGTH_SHORT).show()
                    webView.loadUrl(startUrl)
                }
            }
        }.start()
    }

    override fun onBackPressed() {
        if (webView.canGoBack()) {
            webView.goBack()
        } else {
            super.onBackPressed()
        }
    }
}
