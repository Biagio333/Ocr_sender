package com.example.ocr_sender

import android.app.*
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.DashPathEffect
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.Rect
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.*
import android.util.DisplayMetrics
import android.util.Log
import android.view.View
import android.view.WindowManager
import androidx.core.app.NotificationCompat
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.Text
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import org.json.JSONArray
import org.json.JSONObject
import org.opencv.android.OpenCVLoader
import org.opencv.android.Utils
import org.opencv.core.Core
import org.opencv.core.Mat
import org.opencv.core.Scalar
import org.opencv.core.Size
import org.opencv.imgproc.Imgproc
import java.io.OutputStreamWriter
import java.io.PrintWriter
import java.net.Socket
import java.util.concurrent.Executors
import kotlin.random.Random

class MediaProjectionService : Service() {

    private var mediaProjection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var imageReader: ImageReader? = null
    private val handler = Handler(Looper.getMainLooper())
    private val recognizer = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
    private var ocrBusy = false

    private var windowManager: WindowManager? = null
    private var overlayView: OverlayView? = null
    private var showOverlay = false

    private val socketExecutor = Executors.newSingleThreadExecutor()
    private var socket: Socket? = null
    private var writer: PrintWriter? = null

    private var configJson: JSONObject? = null
    
    // Struttura per i template OpenCV
    data class OpenCVTemplate(val name: String, val mat: Mat)
    private val loadedTemplatesBoard = mutableListOf<OpenCVTemplate>()
    private val loadedTemplatesHero = mutableListOf<OpenCVTemplate>()
    private var coveredCardTemplate: OpenCVTemplate? = null
    private var dealerButtonTemplate: OpenCVTemplate? = null

    data class PokerCard(
        val id: Int,
        val displayName: String,
        val rect: Rect,
        val type: String = "card",
        val sourceLabel: String? = null
    )
    data class OcrItem(
        val id: Int,
        val text: String,
        val rect: Rect,
        val level: String,
        val sourceLabel: String? = null
    )
    data class OcrRegion(val label: String, val rect: Rect)

    companion object {
        const val EXTRA_RESULT_CODE = "EXTRA_RESULT_CODE"
        const val EXTRA_DATA = "EXTRA_DATA"
        const val EXTRA_SHOW_OVERLAY = "EXTRA_SHOW_OVERLAY"
        
        private const val CHANNEL_ID = "MediaProjectionChannel"
        private const val TAG = "OCR_SENDER_debug"
        private const val SOCKET_PORT = 5000
        private const val SOCKET_HOST = "127.0.0.1"
        private const val CAPTURE_INTERVAL_MS = 500L
        private const val NOTIFICATION_ID = 1
        
        private const val OVERLAY_Y_OFFSET = -70

        // Preprocessing OCR
        private const val OCR_PRE_SCALE_FACTOR = 1.75f
        private const val OCR_GREEN_HUE_MIN = 35.0
        private const val OCR_GREEN_SATURATION_MIN = 40.0
        private const val OCR_GREEN_VALUE_MIN = 40.0
        private const val OCR_GREEN_HUE_MAX = 85.0
        private const val OCR_GREEN_SATURATION_MAX = 255.0
        private const val OCR_GREEN_VALUE_MAX = 255.0
        private val OCR_GREEN_HSV_LOWER = Scalar(
            OCR_GREEN_HUE_MIN,
            OCR_GREEN_SATURATION_MIN,
            OCR_GREEN_VALUE_MIN
        )
        private val OCR_GREEN_HSV_UPPER = Scalar(
            OCR_GREEN_HUE_MAX,
            OCR_GREEN_SATURATION_MAX,
            OCR_GREEN_VALUE_MAX
        )

        // Soglie OpenCV Match Template (TM_SQDIFF_NORMED: 0.0 = match perfetto)
        private const val OPENCV_MATCH_THRESHOLD = 0.06
        private const val COVERED_CARD_MATCH_THRESHOLD = 0.12
        private const val DEALER_BUTTON_MATCH_THRESHOLD = 0.14
        private const val COVERED_CARD_MIN_DISTANCE_PX = 100
        
        // Fattore di scala per le carte in mano (Hero)
        private const val HERO_CARD_SCALE_FACTOR = 1.16
    }

    override fun onCreate() {
        super.onCreate()
        if (!OpenCVLoader.initDebug()) {
            Log.e(TAG, "OpenCV NON inizializzato!")
        } else {
            Log.d(TAG, "OpenCV inizializzato con successo")
        }
        loadConfigAndTemplates()
        createNotificationChannel()
        windowManager = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        connectToSocket()
    }

    private fun loadConfigAndTemplates() {
        try {
            val jsonName = "Poker_star_Redmi A5_720x1640_android"
            val jsonString = assets.open("$jsonName.json").bufferedReader().use { it.readText() }
            configJson = JSONObject(jsonString)

            val cardsPath = "$jsonName/cards_board"
            assets.list(cardsPath)?.forEach { fileName ->
                if (fileName.endsWith(".png")) {
                    val mat = loadGrayTemplate("$cardsPath/$fileName") ?: return@forEach
                    
                    // Template per il board (scala 1:1)
                    loadedTemplatesBoard.add(OpenCVTemplate(fileName.removeSuffix(".png"), mat.clone()))
                    
                    // Template per l'Hero (scalati)
                    val heroMat = Mat()
                    val newSize = Size(mat.cols() * HERO_CARD_SCALE_FACTOR, mat.rows() * HERO_CARD_SCALE_FACTOR)
                    Imgproc.resize(mat, heroMat, newSize, 0.0, 0.0, Imgproc.INTER_LINEAR)
                    loadedTemplatesHero.add(OpenCVTemplate(fileName.removeSuffix(".png"), heroMat))
                    
                    mat.release()
                }
            }

            coveredCardTemplate = loadGrayTemplate("$jsonName/covered_card/covered_card.png")
                ?.let { OpenCVTemplate("covered_card", it) }
            dealerButtonTemplate = loadGrayTemplate("$jsonName/dealer_button/dealer_button.png")
                ?.let { OpenCVTemplate("dealer_button", it) }

            Log.d(
                TAG,
                "Caricati ${loadedTemplatesBoard.size} template OpenCV (Board e Hero), covered=${coveredCardTemplate != null}, dealer=${dealerButtonTemplate != null}"
            )
        } catch (e: Exception) {
            Log.e(TAG, "Errore caricamento templates: ${e.message}")
        }
    }

    private fun loadGrayTemplate(assetPath: String): Mat? {
        val raw = assets.open(assetPath).use { BitmapFactory.decodeStream(it) } ?: return null
        return try {
            val mat = Mat()
            Utils.bitmapToMat(raw, mat)
            Imgproc.cvtColor(mat, mat, Imgproc.COLOR_RGBA2GRAY)
            mat
        } finally {
            raw.recycle()
        }
    }

    private fun connectToSocket() {
        socketExecutor.execute {
            try {
                if (socket == null || socket?.isClosed == true || writer == null) {
                    try {
                        writer?.close()
                    } catch (_: Exception) {
                    }
                    try {
                        socket?.close()
                    } catch (_: Exception) {
                    }
                    socket = Socket()
                    socket?.connect(java.net.InetSocketAddress(SOCKET_HOST, SOCKET_PORT), 2000)
                    writer = PrintWriter(OutputStreamWriter(socket?.getOutputStream(), "UTF-8"), true)
                    Log.d(TAG, "Socket connessa a $SOCKET_HOST:$SOCKET_PORT")
                }
            } catch (e: Exception) {
                Log.w(TAG, "Connessione socket fallita: ${e.message}")
                socket = null; writer = null
                handler.postDelayed({ connectToSocket() }, 5000)
            }
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val resultCode = intent?.getIntExtra(EXTRA_RESULT_CODE, Activity.RESULT_CANCELED) ?: Activity.RESULT_CANCELED
        val data = intent?.getParcelableExtra<Intent>(EXTRA_DATA)
        showOverlay = intent?.getBooleanExtra(EXTRA_SHOW_OVERLAY, false) ?: false

        if (resultCode == Activity.RESULT_OK && data != null) {
            if (showOverlay) initOverlay()
            val notification = createNotification()
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
            } else {
                startForeground(NOTIFICATION_ID, notification)
            }
            handler.postDelayed({
                val mpManager = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
                mediaProjection = mpManager.getMediaProjection(resultCode, data)
                if (mediaProjection != null) {
                    setupProjection()
                    startCaptureLoop()
                } else { stopSelf() }
            }, 500)
        }
        return START_NOT_STICKY
    }

    private fun initOverlay() {
        if (overlayView == null) {
            overlayView = OverlayView(this)
            val params = WindowManager.LayoutParams(
                WindowManager.LayoutParams.MATCH_PARENT, WindowManager.LayoutParams.MATCH_PARENT,
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY else @Suppress("DEPRECATION") WindowManager.LayoutParams.TYPE_PHONE,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
                PixelFormat.TRANSLUCENT
            )
            windowManager?.addView(overlayView, params)
        }
    }

    private fun setupProjection() {
        val metrics = DisplayMetrics()
        @Suppress("DEPRECATION")
        windowManager?.defaultDisplay?.getRealMetrics(metrics)
        imageReader = ImageReader.newInstance(metrics.widthPixels, metrics.heightPixels, PixelFormat.RGBA_8888, 2)
        mediaProjection?.registerCallback(object : MediaProjection.Callback() {
            override fun onStop() {
                virtualDisplay?.release(); virtualDisplay = null; mediaProjection = null
            }
        }, handler)
        virtualDisplay = mediaProjection?.createVirtualDisplay("OCR_Capture", metrics.widthPixels, metrics.heightPixels, metrics.densityDpi, DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, imageReader?.surface, null, null)
    }

    private fun startCaptureLoop() {
        handler.post(object : Runnable {
            override fun run() {
                if (mediaProjection == null) return
                captureAndProcess()
                handler.postDelayed(this, CAPTURE_INTERVAL_MS)
            }
        })
    }

    private fun captureAndProcess() {
        val image = try { imageReader?.acquireLatestImage() } catch (e: Exception) { null } ?: return
        if (ocrBusy) { image.close(); return }
        ocrBusy = true

        try {
            val plane = image.planes[0]
            val buffer = plane.buffer
            val pixelStride = plane.pixelStride
            val rowStride = plane.rowStride
            val rowPadding = rowStride - (pixelStride * image.width)
            val bitmap = Bitmap.createBitmap(image.width + rowPadding / pixelStride, image.height, Bitmap.Config.ARGB_8888)
            bitmap.copyPixelsFromBuffer(buffer)
            val screen = Bitmap.createBitmap(bitmap, 0, 0, image.width, image.height)
            bitmap.recycle()
            val processingStartedAt = SystemClock.elapsedRealtime()

            Thread {
                var ocrBitmap: Bitmap? = null
                try {
                    val pokerCards = mutableListOf<PokerCard>()
                    val searchRects = mutableListOf<Rect>()
                    val ocrRegions = mutableListOf<OcrRegion>()
                    
                    configJson?.let { config ->
                        val shapes = config.getJSONArray("shapes")
                        val scaleX = screen.width.toFloat() / config.getInt("imageWidth")
                        val scaleY = screen.height.toFloat() / config.getInt("imageHeight")

                        ocrRegions += collectPlayerOcrRegions(shapes, scaleX, scaleY)
                        collectTableOcrRegions(shapes, scaleX, scaleY).forEach { region ->
                            if (ocrRegions.none { it.label == region.label }) {
                                ocrRegions.add(region)
                            }
                        }
                        searchRects += ocrRegions.map { it.rect }

                        // Carte sul tavolo
                        val labelsBoard = listOf("carte_tavolo_1", "carte_tavolo_2", "carte_tavolo_3", "carte_tavolo_4", "carte_tavolo_5")
                        labelsBoard.forEachIndexed { idx, label ->
                            findRectByLabel(shapes, label, scaleX, scaleY)?.let { rect ->
                                searchRects.add(rect)
                                matchCardOpenCV(screen, rect, loadedTemplatesBoard)?.let { name ->
                                    pokerCards.add(PokerCard(idx, name, rect))
                                }
                            }
                        }
                        
                        // Carte in mano (Hero)
                        val labelsHero = listOf("carte_hero_1", "carte_hero_2")
                        labelsHero.forEachIndexed { idx, label ->
                            findRectByLabel(shapes, label, scaleX, scaleY)?.let { rect ->
                                searchRects.add(rect)
                                matchCardOpenCV(screen, rect, loadedTemplatesHero)?.let { name ->
                                    pokerCards.add(PokerCard(10 + idx, name, rect))
                                }
                            }
                        }

                        findRectByLabel(shapes, "dealer_button", scaleX, scaleY)?.let { rect ->
                            searchRects.add(rect)
                            dealerButtonTemplate?.let { template ->
                                matchSingleTemplate(screen, rect, template, DEALER_BUTTON_MATCH_THRESHOLD)?.let { foundRect ->
                                    pokerCards.add(PokerCard(1000, template.name, foundRect, "dealer_button", "dealer_button"))
                                }
                            }
                        }

                        (0..5).forEach { playerIndex ->
                            val dealerLabel = "player_${playerIndex}_bet_and_dealer"
                            findRectByLabel(shapes, dealerLabel, scaleX, scaleY)?.let { rect ->
                                searchRects.add(rect)
                                dealerButtonTemplate?.let { template ->
                                    matchSingleTemplate(screen, rect, template, DEALER_BUTTON_MATCH_THRESHOLD)?.let { foundRect ->
                                        pokerCards.add(
                                            PokerCard(
                                                1000 + playerIndex,
                                                template.name,
                                                foundRect,
                                                "dealer_button",
                                                dealerLabel
                                            )
                                        )
                                    }
                                }
                            }
                        }

                        (1..5).forEach { playerIndex ->
                            val coveredLabel = "player_${playerIndex}_covered_card"
                            findRectByLabel(shapes, coveredLabel, scaleX, scaleY)?.let { rect ->
                                searchRects.add(rect)
                                coveredCardTemplate?.let { template ->
                                    matchSingleTemplate(screen, rect, template, COVERED_CARD_MATCH_THRESHOLD)?.let { foundRect ->
                                        pokerCards.add(
                                            PokerCard(
                                                1100 + playerIndex,
                                                template.name,
                                                foundRect,
                                                "covered_card",
                                                coveredLabel
                                            )
                                        )
                                    }
                                }
                            }
                        }
                    }

                    val scaledForOcr = Bitmap.createScaledBitmap(
                        screen,
                        (screen.width * OCR_PRE_SCALE_FACTOR).toInt(),
                        (screen.height * OCR_PRE_SCALE_FACTOR).toInt(),
                        true
                    )
                    ocrBitmap = preprocessOcrBitmap(scaledForOcr)
                    scaledForOcr.takeIf { it !== ocrBitmap && !it.isRecycled }?.recycle()

                    val visionText = Tasks.await(recognizer.process(InputImage.fromBitmap(ocrBitmap, 0)))
                    val extracted = extractOcrItems(visionText, OCR_PRE_SCALE_FACTOR)
                    val ocrItems = assignLabelsToOcrItems(extracted.first, ocrRegions)
                    val processingElapsedMs = SystemClock.elapsedRealtime() - processingStartedAt

                    handler.post {
                        if (showOverlay) {
                            overlayView?.updateAll(
                                ocrItems,
                                pokerCards,
                                searchRects,
                                processingElapsedMs
                            )
                        }
                        sendCombinedJson(ocrItems, pokerCards, ocrRegions, processingElapsedMs)
                    }
                } catch (e: Exception) {
                    Log.e(TAG, "Error: ${e.message}")
                } finally {
                    ocrBitmap?.takeIf { it !== screen && !it.isRecycled }?.recycle()
                    ocrBusy = false
                    screen.recycle()
                }
            }.start()
        } finally { image.close() }
    }

    private fun buildGraySourceMat(screen: Bitmap, rect: Rect): Pair<Mat, Rect>? {
        val safe = clampRectToBitmap(rect, screen) ?: return null
        if (safe.width() < 10 || safe.height() < 10) return null

        val crop = Bitmap.createBitmap(screen, safe.left, safe.top, safe.width(), safe.height())
        val sourceMat = Mat()
        Utils.bitmapToMat(crop, sourceMat)
        Imgproc.cvtColor(sourceMat, sourceMat, Imgproc.COLOR_RGBA2GRAY)
        crop.recycle()
        return sourceMat to safe
    }

    private fun clampRectToBitmap(rect: Rect, bitmap: Bitmap): Rect? {
        val safe = Rect(
            maxOf(0, rect.left),
            maxOf(0, rect.top),
            minOf(bitmap.width, rect.right),
            minOf(bitmap.height, rect.bottom)
        )
        if (safe.width() < 10 || safe.height() < 10) return null
        return safe
    }

    private fun collectPlayerOcrRegions(shapes: JSONArray, scaleX: Float, scaleY: Float): List<OcrRegion> {
        val regions = mutableListOf<OcrRegion>()
        val seenLabels = linkedSetOf<String>()

        for (i in 0 until shapes.length()) {
            val shape = shapes.getJSONObject(i)
            val label = shape.optString("label")
            if (!isPlayerOcrLabel(label) || !seenLabels.add(label)) continue

            findRectByLabel(shapes, label, scaleX, scaleY)?.let { rect ->
                regions.add(OcrRegion(label, rect))
            }
        }

        return regions
    }

    private fun collectTableOcrRegions(shapes: JSONArray, scaleX: Float, scaleY: Float): List<OcrRegion> {
        val labels = listOf(
            "pot",
            "Pot",
            "pulsanti0",
            "select_amount_button",
            "select_amount_value",
            "select_amount_plus",
            "select_amount_minus",
        )
        return labels.mapNotNull { label ->
            findRectByLabel(shapes, label, scaleX, scaleY)?.let { rect ->
                OcrRegion(label, rect)
            }
        }
    }

    private fun isPlayerOcrLabel(label: String): Boolean {
        if (!label.startsWith("player_")) return false
        return label.endsWith("_name") || label.endsWith("_stack") || label.contains("_bet")
    }

    private fun assignLabelsToOcrItems(items: List<OcrItem>, regions: List<OcrRegion>): List<OcrItem> {
        return items.map { item ->
            val topLeftX = item.rect.left
            val topLeftY = item.rect.top
            val bestRegion = regions.firstOrNull { region ->
                region.rect.contains(topLeftX, topLeftY)
            }

            if (bestRegion != null) item.copy(sourceLabel = bestRegion.label) else item
        }
    }

    private fun removeGreenBeforeOcr(source: Bitmap): Bitmap {
        val result = source.copy(Bitmap.Config.ARGB_8888, true)
        val rgbaMat = Mat()
        val rgbMat = Mat()
        val hsvMat = Mat()
        val maskMat = Mat()

        return try {
            Utils.bitmapToMat(result, rgbaMat)
            Imgproc.cvtColor(rgbaMat, rgbMat, Imgproc.COLOR_RGBA2RGB)
            Imgproc.cvtColor(rgbMat, hsvMat, Imgproc.COLOR_RGB2HSV)
            Core.inRange(hsvMat, OCR_GREEN_HSV_LOWER, OCR_GREEN_HSV_UPPER, maskMat)
            // Neutralizza il feltro verde senza "bruciare" troppo i dettagli scuri.
            rgbaMat.setTo(Scalar(210.0, 210.0, 210.0, 255.0), maskMat)
            Utils.matToBitmap(rgbaMat, result)
            result
        } finally {
            rgbaMat.release()
            rgbMat.release()
            hsvMat.release()
            maskMat.release()
        }
    }

    private fun preprocessOcrBitmap(source: Bitmap): Bitmap {
        val noGreen = removeGreenBeforeOcr(source)
        val result = Bitmap.createBitmap(noGreen.width, noGreen.height, Bitmap.Config.ARGB_8888)
        val rgbaMat = Mat()
        val grayMat = Mat()
        val contrastMat = Mat()
        val blurMat = Mat()
        val sharpenedMat = Mat()
        val clahe = Imgproc.createCLAHE(1.8, Size(8.0, 8.0))

        return try {
            Utils.bitmapToMat(noGreen, rgbaMat)
            Imgproc.cvtColor(rgbaMat, grayMat, Imgproc.COLOR_RGBA2GRAY)
            clahe.apply(grayMat, contrastMat)
            Imgproc.GaussianBlur(contrastMat, blurMat, Size(3.0, 3.0), 0.0)
            Core.addWeighted(contrastMat, 1.35, blurMat, -0.35, 0.0, sharpenedMat)
            Imgproc.cvtColor(sharpenedMat, rgbaMat, Imgproc.COLOR_GRAY2RGBA)
            Utils.matToBitmap(rgbaMat, result)
            result
        } finally {
            if (!noGreen.isRecycled) {
                noGreen.recycle()
            }
            rgbaMat.release()
            grayMat.release()
            contrastMat.release()
            blurMat.release()
            sharpenedMat.release()
        }
    }

    private fun matchCardOpenCV(screen: Bitmap, rect: Rect, templates: List<OpenCVTemplate>): String? {
        val (sourceMat, _) = buildGraySourceMat(screen, rect) ?: return null

        var bestName: String? = null
        var minVal = 1.0

        for (t in templates) {
            if (t.mat.cols() > sourceMat.cols() || t.mat.rows() > sourceMat.rows()) continue
            
            val result = Mat()
            Imgproc.matchTemplate(sourceMat, t.mat, result, Imgproc.TM_SQDIFF_NORMED)
            val mmr = Core.minMaxLoc(result)
            
            if (mmr.minVal < minVal) {
                minVal = mmr.minVal
                bestName = t.name
            }
            result.release()
        }
        sourceMat.release()

        return if (minVal < OPENCV_MATCH_THRESHOLD) {
            Log.d(TAG, "OpenCV TROVATA: $bestName ($minVal)")
            bestName
        } else null
    }

    private fun matchSingleTemplate(
        screen: Bitmap,
        rect: Rect,
        template: OpenCVTemplate,
        threshold: Double
    ): Rect? {
        val (sourceMat, safe) = buildGraySourceMat(screen, rect) ?: return null
        try {
            if (template.mat.cols() > sourceMat.cols() || template.mat.rows() > sourceMat.rows()) return null

            val result = Mat()
            return try {
                Imgproc.matchTemplate(sourceMat, template.mat, result, Imgproc.TM_SQDIFF_NORMED)
                val mmr = Core.minMaxLoc(result)
                if (mmr.minVal >= threshold) return null
                val x = mmr.minLoc.x.toInt()
                val y = mmr.minLoc.y.toInt()
                Rect(
                    safe.left + x,
                    safe.top + y,
                    safe.left + x + template.mat.cols(),
                    safe.top + y + template.mat.rows()
                )
            } finally {
                result.release()
            }
        } finally {
            sourceMat.release()
        }
    }

    private fun matchMultipleTemplates(
        screen: Bitmap,
        rect: Rect,
        template: OpenCVTemplate,
        threshold: Double
    ): List<Rect> {
        val (sourceMat, safe) = buildGraySourceMat(screen, rect) ?: return emptyList()
        try {
            if (template.mat.cols() > sourceMat.cols() || template.mat.rows() > sourceMat.rows()) return emptyList()

            val result = Mat()
            return try {
                Imgproc.matchTemplate(sourceMat, template.mat, result, Imgproc.TM_SQDIFF_NORMED)
                val detections = mutableListOf<Rect>()
                val minDistanceX = maxOf(8, template.mat.cols() / 2)
                val minDistanceY = maxOf(8, template.mat.rows() / 2)

                for (row in 0 until result.rows()) {
                    for (col in 0 until result.cols()) {
                        val score = result.get(row, col)?.firstOrNull() ?: continue
                        if (score > threshold) continue

                        val candidate = Rect(
                            safe.left + col,
                            safe.top + row,
                            safe.left + col + template.mat.cols(),
                            safe.top + row + template.mat.rows()
                        )
                        val isDuplicate = detections.any {
                            kotlin.math.abs(it.left - candidate.left) < minDistanceX &&
                                kotlin.math.abs(it.top - candidate.top) < minDistanceY
                        }
                        if (!isDuplicate) {
                            detections.add(candidate)
                        }
                    }
                }
                detections
            } finally {
                result.release()
            }
        } finally {
            sourceMat.release()
        }
    }

    private fun deduplicateNearbyRects(rects: List<Rect>, minDistancePx: Int): List<Rect> {
        val kept = mutableListOf<Rect>()
        rects.forEach { candidate ->
            val candidateCenterX = candidate.exactCenterX()
            val candidateCenterY = candidate.exactCenterY()
            val isNearExisting = kept.any { existing ->
                val dx = existing.exactCenterX() - candidateCenterX
                val dy = existing.exactCenterY() - candidateCenterY
                val distance = kotlin.math.sqrt(dx * dx + dy * dy)
                distance < minDistancePx
            }
            if (!isNearExisting) {
                kept.add(candidate)
            }
        }
        return kept
    }

    private fun findRectByLabel(shapes: JSONArray, label: String, scaleX: Float, scaleY: Float): Rect? {
        for (i in 0 until shapes.length()) {
            val shape = shapes.getJSONObject(i)
            if (shape.getString("label") == label) {
                val pts = shape.getJSONArray("points")
                val x1 = (pts.getJSONArray(0).getDouble(0) * scaleX).toInt()
                val y1 = (pts.getJSONArray(0).getDouble(1) * scaleY).toInt()
                val x2 = (pts.getJSONArray(1).getDouble(0) * scaleX).toInt()
                val y2 = (pts.getJSONArray(1).getDouble(1) * scaleY).toInt()
                return Rect(minOf(x1, x2), minOf(y1, y2), maxOf(x1, x2), maxOf(y1, y2))
            }
        }
        return null
    }

    private fun extractOcrItems(
        visionText: Text,
        scaleFactor: Float,
        offset: Rect = Rect(0, 0, 0, 0),
        startId: Int = 100
    ): Pair<List<OcrItem>, Int> {
        val items = mutableListOf<OcrItem>()
        var nextId = startId

        visionText.textBlocks.forEach { block ->
            var blockAdded = false
            block.lines.forEach { line ->
                var lineAdded = false
                line.elements.forEach { element ->
                    val cleanText = sanitizeOcrText(element.text)
                    val box = translateRect(scaleRectDown(element.boundingBox, scaleFactor), offset)
                    if (cleanText.isNotEmpty() && box != null) {
                        items.add(OcrItem(nextId++, cleanText, box, "element"))
                        lineAdded = true
                        blockAdded = true
                    }
                }

                if (!lineAdded) {
                    val cleanText = sanitizeOcrText(line.text)
                    val box = translateRect(scaleRectDown(line.boundingBox, scaleFactor), offset)
                    if (cleanText.isNotEmpty() && box != null) {
                        items.add(OcrItem(nextId++, cleanText, box, "line"))
                        blockAdded = true
                    }
                }
            }

            if (!blockAdded) {
                val cleanText = sanitizeOcrText(block.text)
                val box = translateRect(scaleRectDown(block.boundingBox, scaleFactor), offset)
                if (cleanText.isNotEmpty() && box != null) {
                    items.add(OcrItem(nextId++, cleanText, box, "block"))
                }
            }
        }

        return items to nextId
    }

    private fun sanitizeOcrText(text: String): String {
        return text.trim().replace("€", "E")
    }

    private fun scaleRectDown(rect: Rect?, scaleFactor: Float): Rect? {
        if (rect == null) return null
        if (scaleFactor == 1.0f) return Rect(rect)
        return Rect(
            (rect.left / scaleFactor).toInt(),
            (rect.top / scaleFactor).toInt(),
            (rect.right / scaleFactor).toInt(),
            (rect.bottom / scaleFactor).toInt()
        )
    }

    private fun translateRect(rect: Rect?, offset: Rect): Rect? {
        if (rect == null) return null
        return Rect(
            rect.left + offset.left,
            rect.top + offset.top,
            rect.right + offset.left,
            rect.bottom + offset.top
        )
    }


    private fun sendCombinedJson(
        ocrItems: List<OcrItem>,
        pokerCards: List<PokerCard>,
        ocrRegions: List<OcrRegion>,
        processingElapsedMs: Long
    ) {
        try {
            val root = JSONObject()
            root.put("timestamp", System.currentTimeMillis())
            root.put("processing_elapsed_ms", processingElapsedMs)

            root.put("players", buildPlayersJson(ocrItems, pokerCards))
            root.put("table", buildTableJson(ocrItems, pokerCards, ocrRegions))
            
            val jsonStr = root.toString()
            Log.d(TAG, "Invio JSON: $jsonStr")
            
            socketExecutor.execute { 
                try {
                    val currentWriter = writer
                    if (currentWriter == null || socket == null || socket?.isClosed == true) {
                        connectToSocket()
                        return@execute
                    }

                    currentWriter.println(jsonStr)
                    currentWriter.flush()

                    if (currentWriter.checkError()) {
                        Log.w(TAG, "Errore writer socket, riconnessione in corso")
                        try {
                            currentWriter.close()
                        } catch (_: Exception) {
                        }
                        try {
                            socket?.close()
                        } catch (_: Exception) {
                        }
                        socket = null
                        writer = null
                        connectToSocket()
                    }
                } catch (e: Exception) {
                    Log.w(TAG, "Invio socket fallito: ${e.message}")
                    try {
                        writer?.close()
                    } catch (_: Exception) {
                    }
                    try {
                        socket?.close()
                    } catch (_: Exception) {
                    }
                    socket = null
                    writer = null
                    connectToSocket()
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Errore invio JSON: ${e.message}")
        }
    }

    private fun rectToJson(rect: Rect): JSONObject {
        return JSONObject().apply {
            put("left", rect.left)
            put("top", rect.top)
            put("right", rect.right)
            put("bottom", rect.bottom)
        }
    }

    private fun pokerCardToJson(card: PokerCard): JSONObject {
        return JSONObject().apply {
            put("name", card.displayName)
            put("type", card.type)
            put("rect", rectToJson(card.rect))
        }
    }

    private fun ocrItemToJson(item: OcrItem): JSONObject {
        return JSONObject().apply {
            put("name", item.text)
            put("rect", rectToJson(item.rect))
        }
    }

    private data class MeasuredOcrItem(
        val text: String,
        val rect: Rect,
        val x: Int,
        val y: Int,
        val w: Int,
        val h: Int,
        val cx: Float,
    )

    private fun measureOcrItem(item: OcrItem): MeasuredOcrItem {
        val rect = item.rect
        return MeasuredOcrItem(
            text = item.text,
            rect = rect,
            x = rect.left,
            y = rect.top,
            w = rect.width(),
            h = rect.height(),
            cx = rect.exactCenterX(),
        )
    }

    private fun clusterButtonItems(roiItems: List<OcrItem>): List<List<MeasuredOcrItem>> {
        val measuredItems = roiItems.map { measureOcrItem(it) }.sortedBy { it.cx }
        val clusters = mutableListOf<MutableList<MeasuredOcrItem>>()
        val clusterCenters = mutableListOf<Float>()
        val clusterWidths = mutableListOf<Float>()

        for (item in measuredItems) {
            var nearestIndex = -1
            var nearestDistance: Float? = null

            clusters.forEachIndexed { index, cluster ->
                val distance = kotlin.math.abs(item.cx - clusterCenters[index])
                val tolerance = maxOf(45f, (clusterWidths[index] + item.w) / 1.5f)
                if (distance <= tolerance && (nearestDistance == null || distance < nearestDistance!!)) {
                    nearestIndex = index
                    nearestDistance = distance
                }
            }

            if (nearestIndex < 0) {
                clusters += mutableListOf(item)
                clusterCenters += item.cx
                clusterWidths += item.w.toFloat()
                continue
            }

            val cluster = clusters[nearestIndex]
            cluster += item
            clusterCenters[nearestIndex] = cluster.map { it.cx }.average().toFloat()
            clusterWidths[nearestIndex] = cluster.map { it.w.toFloat() }.average().toFloat()
        }

        return clusters
    }

    private fun labelForAmountControl(roiLabel: String): String {
        val normalized = roiLabel.lowercase()
        return when {
            normalized.contains("minus") -> "-"
            normalized.contains("plus") -> "+"
            normalized.contains("button") -> "raise"
            else -> roiLabel
        }
    }

    private fun buttonJson(
        label: String,
        roiLabel: String,
        buttonRect: Rect,
        ocrRect: Rect? = null
    ): JSONObject {
        val clickRect = if (ocrRect != null) {
            val padX = maxOf(1, (ocrRect.width() * 0.10 / 2.0).toInt())
            val padY = maxOf(1, (ocrRect.height() * 0.10 / 2.0).toInt())
            Rect(
                maxOf(buttonRect.left, ocrRect.left - padX),
                maxOf(buttonRect.top, ocrRect.top - padY),
                minOf(buttonRect.right, ocrRect.right + padX),
                minOf(buttonRect.bottom, ocrRect.bottom + padY)
            )
        } else {
            buttonRect
        }
        val safeClickRect = if (clickRect.width() > 0 && clickRect.height() > 0) clickRect else buttonRect
        val clickX = Random.nextInt(safeClickRect.left, safeClickRect.right.coerceAtLeast(safeClickRect.left + 1))
        val clickY = Random.nextInt(safeClickRect.top, safeClickRect.bottom.coerceAtLeast(safeClickRect.top + 1))
        return JSONObject().apply {
            put("label", label)
            put("roi_label", roiLabel)
            put("button_rect", rectToJson(buttonRect))
            put("click_rect", rectToJson(safeClickRect))
            put("click_point", JSONObject().apply {
                put("x", clickX)
                put("y", clickY)
            })
            if (ocrRect != null) {
                put("ocr_rect", rectToJson(ocrRect))
                put("ocr_rect_area", ocrRect.width() * ocrRect.height())
            } else {
                put("ocr_rect", JSONObject.NULL)
                put("ocr_rect_area", 0)
            }
        }
    }

    private fun parseActionButtonCluster(items: List<MeasuredOcrItem>, roiLabel: String): JSONObject? {
        val ordered = items.sortedWith(compareBy<MeasuredOcrItem> { it.y }.thenBy { it.x })
        val fullText = ordered.joinToString(" ") { it.text }.trim()
        if (fullText.isBlank()) {
            return null
        }

        val minX = ordered.minOf { it.x }
        val minY = ordered.minOf { it.y }
        val maxX = ordered.maxOf { it.x + it.w }
        val maxY = ordered.maxOf { it.y + it.h }
        val ocrRect = Rect(minX, minY, maxX, maxY)
        val expandRatio = 0.10f
        val padX = maxOf(1, ((ocrRect.width() * expandRatio) / 2f).toInt())
        val padY = maxOf(1, ((ocrRect.height() * expandRatio) / 2f).toInt())
        val buttonRect = Rect(
            maxOf(0, ocrRect.left - padX),
            maxOf(0, ocrRect.top - padY),
            ocrRect.right + padX,
            ocrRect.bottom + padY
        )
        return buttonJson(
            label = fullText,
            roiLabel = roiLabel,
            buttonRect = buttonRect,
            ocrRect = ocrRect
        )
    }

    private fun buildActionButtonsJson(ocrItems: List<OcrItem>): JSONArray {
        val buttons = JSONArray()
        val groups = ocrItems
            .filter { (it.sourceLabel ?: "").startsWith("pulsanti", ignoreCase = true) }
            .groupBy { it.sourceLabel ?: "pulsanti" }

        for ((roiLabel, items) in groups.toSortedMap()) {
            for (cluster in clusterButtonItems(items)) {
                val parsed = parseActionButtonCluster(cluster, roiLabel)
                if (parsed != null) {
                    buttons.put(parsed)
                }
            }
        }
        return buttons
    }

    private fun buildAmountButtonsJson(ocrItems: List<OcrItem>, ocrRegions: List<OcrRegion>): JSONArray {
        val buttons = JSONArray()
        val regions = ocrRegions
            .filter {
                val label = it.label.lowercase()
                label.startsWith("select_amount") && !label.endsWith("value")
            }
            .sortedBy { it.label }

        for (region in regions) {
            val items = ocrItems.filter { it.sourceLabel == region.label }
            if (region.label.equals("select_amount_button", ignoreCase = true)) {
                val clusters = clusterButtonItems(items)
                var addedCluster = false
                for (cluster in clusters) {
                    val parsed = parseActionButtonCluster(cluster, region.label)
                    if (parsed != null) {
                        buttons.put(parsed)
                        addedCluster = true
                    }
                }
                if (addedCluster) {
                    continue
                }
            }

            val ordered = items.sortedWith(compareBy<OcrItem> { it.rect.top }.thenBy { it.rect.left })
            val fullText = ordered.joinToString(" ") { it.text }.trim()
            val ocrRect = if (ordered.isNotEmpty()) {
                Rect(
                    ordered.minOf { it.rect.left },
                    ordered.minOf { it.rect.top },
                    ordered.maxOf { it.rect.right },
                    ordered.maxOf { it.rect.bottom }
                )
            } else {
                null
            }
            buttons.put(
                buttonJson(
                    label = if (fullText.isNotBlank()) fullText else labelForAmountControl(region.label),
                    roiLabel = region.label,
                    buttonRect = region.rect,
                    ocrRect = ocrRect
                )
            )
        }

        return buttons
    }

    private fun readAmountValueText(ocrItems: List<OcrItem>): String {
        return ocrItems
            .filter { (it.sourceLabel ?: "").equals("select_amount_value", ignoreCase = true) }
            .sortedWith(compareBy<OcrItem> { it.rect.left }.thenBy { it.rect.top })
            .joinToString(" ") { it.text }
            .trim()
    }

    private fun isLikelyPreActionButtons(
        availableActions: JSONArray,
        amountButtons: JSONArray,
        amountValueText: String
    ): Boolean {
        if (availableActions.length() == 0 || availableActions.length() > 2) return false

        val labels = mutableListOf<String>()
        var maxHeight = 0
        var maxWidth = 0
        for (i in 0 until availableActions.length()) {
            val button = availableActions.optJSONObject(i) ?: continue
            val label = button.optString("label").lowercase().replace(Regex("[^a-z0-9]"), "")
            labels.add(label)
            val rect = button.optJSONObject("button_rect")
            val left = rect?.optInt("left") ?: 0
            val right = rect?.optInt("right") ?: left
            val top = rect?.optInt("top") ?: 0
            val bottom = rect?.optInt("bottom") ?: top
            maxHeight = maxOf(maxHeight, bottom - top)
            maxWidth = maxOf(maxWidth, right - left)
        }

        val shortcutCount = (0 until amountButtons.length()).count { index ->
            val button = amountButtons.optJSONObject(index) ?: return@count false
            val roiLabel = button.optString("roi_label").lowercase()
            if (roiLabel != "select_amount_button") return@count false
            val label = button.optString("label").trim().lowercase()
            val ocrRectArea = button.optInt("ocr_rect_area", 0)
            label.isNotBlank() && label != "raise" || ocrRectArea > 0
        }

        val labelsLookLikePreactions = labels.any { it.contains("checkfold") } || (
            labels.size == 2 &&
                labels.any { it.contains("fold") } &&
                labels.any { it.contains("chiama") || it.contains("call") || it == "check" }
            )
        val labelsLookLikeMetaControls = labels.any {
            it.startsWith("tornaagiocare") || it.startsWith("rientra") || it.startsWith("sitout")
        }
        val hasRealRaisePanel = amountValueText.isNotBlank() || shortcutCount >= 2
        if (labelsLookLikeMetaControls && !hasRealRaisePanel) return true
        if (
            !hasRealRaisePanel &&
            labels.isNotEmpty() &&
            labels.size <= 2 &&
            labels.all {
                it.contains("fold") ||
                    it.contains("check") ||
                    it.contains("call") ||
                    it.contains("chiama") ||
                    it.contains("passa")
            }
        ) {
            return true
        }
        return maxHeight <= 24 && maxWidth <= 130 && labelsLookLikePreactions && !hasRealRaisePanel
    }

    private fun hasRealRaisePanel(
        amountButtons: JSONArray,
        amountValueText: String
    ): Boolean {
        if (amountValueText.isNotBlank()) return true

        var shortcutCount = 0
        for (index in 0 until amountButtons.length()) {
            val button = amountButtons.optJSONObject(index) ?: continue
            when (button.optString("roi_label").lowercase()) {
                "select_amount_button" -> {
                    shortcutCount += 1
                    val label = button.optString("label").trim().lowercase()
                    if (label.isNotBlank() && label != "raise") {
                        return true
                    }
                }
                "select_amount_plus", "select_amount_minus" -> {
                    shortcutCount += 1
                }
            }
        }
        return shortcutCount >= 3
    }

    private fun buildPlayersJson(ocrItems: List<OcrItem>, pokerCards: List<PokerCard>): JSONArray {
        val groupedByPlayer = ocrItems
            .mapNotNull { item ->
                val label = item.sourceLabel ?: return@mapNotNull null
                val playerIndex = extractPlayerIndex(label) ?: return@mapNotNull null
                playerIndex to item
            }
            .groupBy({ it.first }, { it.second })
        val cardsByPlayer = pokerCards
            .mapNotNull { card ->
                val label = card.sourceLabel ?: return@mapNotNull null
                val playerIndex = extractPlayerIndex(label) ?: return@mapNotNull null
                playerIndex to card
            }
            .groupBy({ it.first }, { it.second })

        return JSONArray().apply {
            (groupedByPlayer.keys + cardsByPlayer.keys).sorted().forEach { playerIndex ->
                val playerItems = groupedByPlayer[playerIndex].orEmpty()
                val playerCards = cardsByPlayer[playerIndex].orEmpty()
                val fieldTexts = playerItems
                    .groupBy { classifyOcrLabel(it.sourceLabel) ?: "unknown" }
                    .mapValues { (_, items) -> items.sortForReading().joinToString(" ") { it.text }.trim() }

                put(JSONObject().apply {
                    put("player_index", playerIndex)
                    put("name", fieldTexts["name"] ?: "")
                    put("stack", fieldTexts["stack"] ?: "")
                    put("bet", fieldTexts["bet"] ?: "")
                    put("covered_card", playerCards.firstOrNull { it.type == "covered_card" }?.let { pokerCardToJson(it) } ?: JSONObject.NULL)
                    put("dealer_button", playerCards.firstOrNull { it.type == "dealer_button" }?.let { pokerCardToJson(it) } ?: JSONObject.NULL)
                })
            }
        }
    }

    private fun buildTableJson(
        ocrItems: List<OcrItem>,
        pokerCards: List<PokerCard>,
        ocrRegions: List<OcrRegion>
    ): JSONObject {
        val tableOcrItems = ocrItems.filter { classifyOcrLabel(it.sourceLabel) == "pot" }
        val boardCards = pokerCards.filter { it.id in 0..4 }
        val heroCards = pokerCards.filter { it.id in 10..11 }
        val rawAvailableActions = buildActionButtonsJson(ocrItems)
        val amountButtons = buildAmountButtonsJson(ocrItems, ocrRegions)
        val amountValueText = readAmountValueText(ocrItems)
        val availableActions = if (isLikelyPreActionButtons(rawAvailableActions, amountButtons, amountValueText)) {
            JSONArray()
        } else {
            rawAvailableActions
        }
        val heroToAct = availableActions.length() > 0 || hasRealRaisePanel(amountButtons, amountValueText)

        return JSONObject().apply {
            put("pot", tableOcrItems.sortForReading().joinToString(" ") { it.text }.trim())
            put("board_cards", JSONArray().apply {
                boardCards.forEach { put(pokerCardToJson(it)) }
            })
            put("hero_cards", JSONArray().apply {
                heroCards.forEach { put(pokerCardToJson(it)) }
            })
            put("available_actions", availableActions)
            put("amount_buttons", amountButtons)
            put("amount_value_text", amountValueText)
            put("hero_to_act", heroToAct)
        }
    }

    private fun extractPlayerIndex(label: String): Int? {
        val match = Regex("""player_(\d+)""").find(label) ?: return null
        return match.groupValues.getOrNull(1)?.toIntOrNull()
    }

    private fun classifyOcrLabel(label: String?): String? {
        if (label == null) return null
        return when {
            label.endsWith("_name") -> "name"
            label.endsWith("_stack") -> "stack"
            label.contains("_bet") -> "bet"
            label.equals("pot", ignoreCase = true) -> "pot"
            else -> null
        }
    }

    private fun List<OcrItem>.sortForReading(): List<OcrItem> {
        return sortedWith(
            compareBy<OcrItem> { it.rect.left }
                .thenBy { it.rect.top }
                .thenBy { it.id }
        )
    }

    private fun createNotification(): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID).setContentTitle("Poker OpenCV Active").setSmallIcon(android.R.drawable.ic_menu_camera).build()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(CHANNEL_ID, "OCR", NotificationManager.IMPORTANCE_LOW)
            getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
        }
    }

    override fun onDestroy() {
        overlayView?.let { windowManager?.removeView(it) }
        virtualDisplay?.release(); imageReader?.close(); mediaProjection?.stop(); recognizer.close()
        socketExecutor.shutdownNow()
        loadedTemplatesBoard.forEach { it.mat.release() }
        loadedTemplatesHero.forEach { it.mat.release() }
        coveredCardTemplate?.mat?.release()
        dealerButtonTemplate?.mat?.release()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private class OverlayView(context: Context) : View(context) {
        private val textPaint = Paint().apply { color = Color.YELLOW; textSize = 24f; style = Paint.Style.FILL; textAlign = Paint.Align.CENTER; isFakeBoldText = true; setShadowLayer(3f, 0f, 0f, Color.BLACK) }
        private val outlinePaint = Paint().apply { color = Color.BLACK; textSize = 24f; style = Paint.Style.STROKE; strokeWidth = 4f; textAlign = Paint.Align.CENTER; isFakeBoldText = true }
        private val ocrBoxPaint = Paint().apply { color = Color.CYAN; style = Paint.Style.STROKE; strokeWidth = 3f }
        private val cardPaint = Paint().apply { color = Color.GREEN; style = Paint.Style.STROKE; strokeWidth = 4f }
        private val searchAreaPaint = Paint().apply { color = Color.RED; style = Paint.Style.STROKE; strokeWidth = 1f; pathEffect = DashPathEffect(floatArrayOf(10f, 10f), 0f) }
        private val hudPaint = Paint().apply { color = Color.WHITE; textSize = 34f; style = Paint.Style.FILL; isFakeBoldText = true; setShadowLayer(4f, 0f, 0f, Color.BLACK) }
        private var pokerCards = listOf<PokerCard>()
        private var searchRects = listOf<Rect>()
        private var ocrItems = listOf<OcrItem>()
        private var processingElapsedMs = 0L

        fun updateAll(items: List<OcrItem>, cards: List<PokerCard>, searches: List<Rect>, elapsedMs: Long) {
            this.ocrItems = items
            this.pokerCards = cards
            this.searchRects = searches
            this.processingElapsedMs = elapsedMs
            postInvalidate()
        }

        override fun onDraw(canvas: Canvas) {
            super.onDraw(canvas)
            val off = OVERLAY_Y_OFFSET.toFloat()
            canvas.drawText("Table: ${processingElapsedMs} ms", 24f, 48f, hudPaint)
            
            ocrItems.forEach { item ->
                val rect = item.rect
                canvas.drawRect(rect.left.toFloat(), rect.top.toFloat() + off, rect.right.toFloat(), rect.bottom.toFloat() + off, ocrBoxPaint)
                val labelY = (rect.top - 8).toFloat() + off
                canvas.drawText(item.text, rect.centerX().toFloat(), labelY, outlinePaint)
                canvas.drawText(item.text, rect.centerX().toFloat(), labelY, textPaint)
            }

            searchRects.forEach { r -> canvas.drawRect(r.left.toFloat(), r.top.toFloat() + off, r.right.toFloat(), r.bottom.toFloat() + off, searchAreaPaint) }
            pokerCards.forEach { card ->
                canvas.drawRect(card.rect.left.toFloat(), card.rect.top.toFloat() + off, card.rect.right.toFloat(), card.rect.bottom.toFloat() + off, cardPaint)
                canvas.drawText(card.displayName, card.rect.centerX().toFloat(), card.rect.top.toFloat() - 10f + off, outlinePaint)
                canvas.drawText(card.displayName, card.rect.centerX().toFloat(), card.rect.top.toFloat() - 10f + off, textPaint)
            }
        }
    }
}
