package com.example.ocr_sender

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat

class MainActivity : AppCompatActivity() {

    private lateinit var mediaProjectionManager: MediaProjectionManager
    private lateinit var txtStatus: TextView
    private lateinit var btnStartCapture: Button
    private var isCapturing = false

    private val screenCaptureLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
            if (result.resultCode == Activity.RESULT_OK && result.data != null) {
                startServiceWithData(result.resultCode, result.data!!)
            } else {
                txtStatus.text = "Permesso cattura negato"
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        txtStatus = findViewById(R.id.txtStatus)
        btnStartCapture = findViewById(R.id.btnStartCapture)

        mediaProjectionManager =
            getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager

        btnStartCapture.setOnClickListener {
            if (!isCapturing) {
                checkPermissionsAndStart()
            } else {
                stopCaptureService()
            }
        }
    }

    private fun checkPermissionsAndStart() {
        val captureIntent = mediaProjectionManager.createScreenCaptureIntent()
        screenCaptureLauncher.launch(captureIntent)
    }

    private fun startServiceWithData(resultCode: Int, data: Intent) {
        val serviceIntent = Intent(this, MediaProjectionService::class.java).apply {
            putExtra(MediaProjectionService.EXTRA_RESULT_CODE, resultCode)
            putExtra(MediaProjectionService.EXTRA_DATA, data)
            putExtra(MediaProjectionService.EXTRA_SHOW_OVERLAY, false)
        }
        ContextCompat.startForegroundService(this, serviceIntent)
        txtStatus.text = "Servizio OCR avviato"
        btnStartCapture.text = "Stop capture"
        isCapturing = true
    }

    private fun stopCaptureService() {
        stopService(Intent(this, MediaProjectionService::class.java))
        txtStatus.text = "Capture fermata"
        btnStartCapture.text = "Start capture"
        isCapturing = false
    }
}
