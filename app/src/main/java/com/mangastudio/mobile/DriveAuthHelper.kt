package com.mangastudio.mobile

import android.app.Activity
import android.webkit.JavascriptInterface
import androidx.activity.result.ActivityResultLauncher
import androidx.activity.result.IntentSenderRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import com.google.android.gms.auth.api.identity.AuthorizationRequest
import com.google.android.gms.auth.api.identity.AuthorizationResult
import com.google.android.gms.auth.api.identity.Identity
import com.google.android.gms.common.api.Scope

/**
 * DriveAuthHelper - Login do Google (Google Identity Services) para ler o Google Drive.
 *
 * Pede só a permissão de LEITURA do Drive. O token de acesso vai direto para o Python
 * (mobile_gdrive.set_token) e nunca passa pelo JavaScript da página.
 * Requisito: cliente OAuth "Android" no Google Cloud com o pacote com.mangastudio.mobile e o
 * SHA-1 da chave FIXA de assinatura do APK (Secrets ANDROID_KEYSTORE_* do GitHub).
 * Regra de Ouro: Coeso, desacoplado e estritamente < 300 linhas.
 */
class DriveAuthHelper(
    private val activity: AppCompatActivity,
    private val onResult: (ok: Boolean, message: String) -> Unit
) {
    companion object {
        const val DRIVE_READ_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
    }

    // Registrado na construção (antes do onStart da Activity), como o Android exige.
    private val consentLauncher: ActivityResultLauncher<IntentSenderRequest> =
        activity.registerForActivityResult(ActivityResultContracts.StartIntentSenderForResult()) { res ->
            if (res.resultCode != Activity.RESULT_OK) {
                onResult(false, "Login do Google cancelado.")
                return@registerForActivityResult
            }
            try {
                val result = Identity.getAuthorizationClient(activity).getAuthorizationResultFromIntent(res.data)
                deliver(result)
            } catch (e: Exception) {
                onResult(false, "Falha no login do Google: ${e.message}")
            }
        }

    /** Pede o token. Se já houve consentimento antes, volta sem mostrar tela. */
    fun connect() {
        val request = AuthorizationRequest.builder()
            .setRequestedScopes(listOf(Scope(DRIVE_READ_SCOPE)))
            .build()
        Identity.getAuthorizationClient(activity)
            .authorize(request)
            .addOnSuccessListener { result ->
                val pending = result.pendingIntent
                if (result.hasResolution() && pending != null) {
                    try {
                        consentLauncher.launch(IntentSenderRequest.Builder(pending.intentSender).build())
                    } catch (e: Exception) {
                        onResult(false, "Não foi possível abrir o login do Google: ${e.message}")
                    }
                } else {
                    deliver(result)
                }
            }
            .addOnFailureListener { e ->
                onResult(false, "Falha no login do Google: ${e.message}")
            }
    }

    private fun deliver(result: AuthorizationResult) {
        val token = result.accessToken
        if (token.isNullOrBlank()) {
            onResult(false, "O Google não devolveu acesso ao Drive.")
            return
        }
        try {
            if (!Python.isStarted()) {
                Python.start(AndroidPlatform(activity.applicationContext))
            }
            Python.getInstance().getModule("mobile_gdrive").callAttr("set_token", token)
            onResult(true, "Google Drive conectado.")
        } catch (e: Exception) {
            onResult(false, "Erro ao entregar o acesso ao motor: ${e.message}")
        }
    }
}

/** Ponte chamada pela página (window.MangaDrive.connect()). */
class DriveBridge(private val activity: Activity, private val helper: DriveAuthHelper) {
    @JavascriptInterface
    fun connect() {
        activity.runOnUiThread { helper.connect() }
    }

    @JavascriptInterface
    fun isAvailable(): Boolean = true
}
