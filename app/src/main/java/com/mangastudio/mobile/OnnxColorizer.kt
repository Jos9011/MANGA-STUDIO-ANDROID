package com.mangastudio.mobile

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Roda o modelo de colorização (ONNX) no celular. Chamado pelo Python (mobile_colorizer.py)
 * via Chaquopy, porque o Chaquopy não tem onnxruntime para Python.
 *
 * Entrada e saída em bytes (float32 little-endian), para a troca Python <-> Kotlin ser uma cópia só:
 * entrada (1, 5, altura, largura); saída (1, 3, altura, largura) com RGB de 0 a 1.
 */
object OnnxColorizer {
    private var env: OrtEnvironment? = null
    private var session: OrtSession? = null
    private var loadedPath: String? = null

    @JvmStatic
    @Synchronized
    fun run(modelPath: String, input: ByteArray, height: Int, width: Int): ByteArray {
        val environment = env ?: OrtEnvironment.getEnvironment().also { env = it }
        if (session == null || loadedPath != modelPath) {
            session?.close()
            val options = OrtSession.SessionOptions()
            options.setIntraOpNumThreads(Runtime.getRuntime().availableProcessors().coerceIn(1, 4))
            session = environment.createSession(modelPath, options)
            loadedPath = modelPath
        }
        val floats = ByteBuffer.wrap(input).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer()
        val shape = longArrayOf(1, 5, height.toLong(), width.toLong())
        OnnxTensor.createTensor(environment, floats, shape).use { tensor ->
            session!!.run(mapOf("input" to tensor)).use { result ->
                val out = (result.get(0) as OnnxTensor).floatBuffer
                val bytes = ByteBuffer.allocate(out.remaining() * 4).order(ByteOrder.LITTLE_ENDIAN)
                bytes.asFloatBuffer().put(out)
                return bytes.array()
            }
        }
    }

    /** Libera a memória do modelo (chamado ao terminar um capítulo). */
    @JvmStatic
    @Synchronized
    fun release() {
        session?.close()
        session = null
        loadedPath = null
    }
}
