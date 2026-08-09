package com.sparkle.android.ui

import android.app.ActivityManager
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.Base64
import android.util.LruCache
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.clickable
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Image
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.launch
import kotlinx.coroutines.runInterruptible
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger

@Composable
fun SparkleThumbnail(
    url: String?,
    modifier: Modifier = Modifier
        .fillMaxWidth()
        .height(132.dp),
    preserveImageAspectRatio: Boolean = false,
    contentDescription: String? = null,
    allowUncachedLoad: Boolean = true,
    allowCachedLoad: Boolean = true,
    decodeMaxDimensionPx: Int? = null,
    manualLoadEnabled: Boolean = false,
    showManualLabel: Boolean = true,
) {
    val context = LocalContext.current.applicationContext
    ThumbnailRepository.configure(context)
    var manualLoadRequested by remember(url) { mutableStateOf(false) }
    val shouldLoad = allowUncachedLoad || manualLoadRequested
    var bitmap by remember(url, decodeMaxDimensionPx) {
        mutableStateOf(url?.let { ThumbnailRepository.memory(it, decodeMaxDimensionPx) })
    }
    LaunchedEffect(url, shouldLoad, allowCachedLoad, decodeMaxDimensionPx) {
        if (url == null) {
            bitmap = null
            return@LaunchedEffect
        }
        if (bitmap == null) {
            bitmap = ThumbnailRepository.memory(url, decodeMaxDimensionPx)
        }
        if (bitmap == null && allowCachedLoad) {
            bitmap = ThumbnailRepository.loadCached(context, url, decodeMaxDimensionPx)
        }
        if (bitmap == null && shouldLoad) {
            bitmap = ThumbnailRepository.load(context, url, decodeMaxDimensionPx)
        }
    }
    val shape = MaterialTheme.shapes.medium
    val imageModifier = if (preserveImageAspectRatio) {
        modifier.aspectRatio(
            bitmap?.let { loaded ->
                loaded.width.toFloat() / loaded.height.toFloat()
            } ?: (16f / 9f),
        )
    } else {
        modifier
    }
    if (bitmap != null) {
        Image(
            bitmap = bitmap!!.asImageBitmap(),
            contentDescription = contentDescription,
            contentScale = if (preserveImageAspectRatio) ContentScale.Fit else ContentScale.Crop,
            modifier = imageModifier
                .clip(shape)
                .border(1.dp, MaterialTheme.colorScheme.outlineVariant, shape),
        )
    } else if (manualLoadEnabled && !manualLoadRequested && url != null) {
        val manualLoadLabel = "タップしてサムネイルを表示"
        val thumbnailDescription = contentDescription
        Box(
            modifier = imageModifier
                .clip(shape)
                .background(MaterialTheme.colorScheme.surfaceVariant)
                .border(1.dp, MaterialTheme.colorScheme.outlineVariant, shape)
                .clickable(
                    role = Role.Button,
                    onClickLabel = manualLoadLabel,
                    onClick = { manualLoadRequested = true },
                )
                .semantics {
                    this.contentDescription = listOfNotNull(thumbnailDescription, manualLoadLabel).joinToString("。")
                },
            contentAlignment = Alignment.Center,
        ) {
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                modifier = Modifier.padding(horizontal = 8.dp, vertical = 6.dp),
            ) {
                Icon(
                    Icons.Default.Image,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                if (showManualLabel) {
                    Text(
                        "タップして表示",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    } else {
        Box(
            modifier = imageModifier
                .clip(shape)
                .background(MaterialTheme.colorScheme.surfaceVariant)
                .border(1.dp, MaterialTheme.colorScheme.outlineVariant, shape),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                Icons.Default.Image,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

suspend fun preloadCachedThumbnail(
    context: Context,
    url: String,
    decodeMaxDimensionPx: Int?,
) {
    ThumbnailRepository.loadCached(context, url, decodeMaxDimensionPx)
}

fun pinThumbnail(url: String, decodeMaxDimensionPx: Int?) {
    ThumbnailRepository.pin(url, decodeMaxDimensionPx)
}

fun unpinThumbnail(url: String, decodeMaxDimensionPx: Int?) {
    ThumbnailRepository.unpin(url, decodeMaxDimensionPx)
}

private object ThumbnailRepository {
    private const val MAX_CONCURRENT_LOADS = 3
    private const val MAX_CONCURRENT_CACHE_READS = 2
    private val loadScope = CoroutineScope(
        SupervisorJob() + Dispatchers.IO.limitedParallelism(MAX_CONCURRENT_LOADS),
    )
    private val cachedLoadScope = CoroutineScope(
        SupervisorJob() + Dispatchers.IO.limitedParallelism(MAX_CONCURRENT_CACHE_READS),
    )
    private val inFlight = ConcurrentHashMap<String, InFlight>()
    private val cachedInFlight = ConcurrentHashMap<String, InFlight>()

    private class InFlight(val deferred: Deferred<Bitmap?>) {
        val consumers = AtomicInteger(1)
    }

    fun memory(rawUrl: String, maxDimensionPx: Int?): Bitmap? =
        ThumbnailCache.memory(rawUrl, maxDimensionPx)

    fun configure(context: Context) {
        ThumbnailCache.configure(context)
    }

    fun pin(rawUrl: String, maxDimensionPx: Int?) {
        ThumbnailCache.pin(rawUrl, maxDimensionPx)
    }

    fun unpin(rawUrl: String, maxDimensionPx: Int?) {
        ThumbnailCache.unpin(rawUrl, maxDimensionPx)
    }

    suspend fun loadCached(context: Context, rawUrl: String, maxDimensionPx: Int?): Bitmap? {
        configure(context)
        memory(rawUrl, maxDimensionPx)?.let { return it }
        val key = ThumbnailCache.bitmapCacheKey(rawUrl, maxDimensionPx)
        val request = cachedInFlight.compute(key) { _, existing ->
            if (existing != null) {
                existing.consumers.incrementAndGet()
                existing
            } else {
                InFlight(
                    cachedLoadScope.async {
                        ThumbnailCache.loadCached(context, rawUrl, maxDimensionPx)
                    },
                )
            }
        } ?: return null
        try {
            return request.deferred.await()
        } finally {
            release(cachedInFlight, key, request)
        }
    }

    suspend fun load(context: Context, rawUrl: String, maxDimensionPx: Int?): Bitmap? {
        configure(context)
        memory(rawUrl, maxDimensionPx)?.let { return it }
        val key = ThumbnailCache.bitmapCacheKey(rawUrl, maxDimensionPx)
        val request = inFlight.compute(key) { _, existing ->
            if (existing != null) {
                existing.consumers.incrementAndGet()
                existing
            } else {
                InFlight(
                    loadScope.async {
                        runInterruptible {
                            ThumbnailCache.load(context, rawUrl, maxDimensionPx)
                        }
                    },
                )
            }
        } ?: return null
        try {
            return request.deferred.await()
        } finally {
            release(inFlight, key, request)
        }
    }

    private fun release(
        requests: ConcurrentHashMap<String, InFlight>,
        key: String,
        request: InFlight,
    ) {
        if (request.consumers.decrementAndGet() == 0 && requests.remove(key, request)) {
            if (!request.deferred.isCompleted) request.deferred.cancel()
        }
    }
}

private object ThumbnailCache {
    private const val BYTES_PER_MIB = 1024 * 1024
    private const val DEFAULT_MEMORY_CACHE_BYTES = 16 * BYTES_PER_MIB
    private const val DEFAULT_HOT_CACHE_BYTES = 8 * BYTES_PER_MIB
    private const val DEFAULT_PINNED_CACHE_BYTES = 8 * BYTES_PER_MIB
    private const val DISK_CACHE_BYTES = 64L * 1024 * 1024
    private const val MAX_ENTRY_BYTES = 8L * 1024 * 1024
    private const val MAX_BITMAP_DIMENSION = 1280
    private const val MIN_BITMAP_DIMENSION = 240

    private val cacheLock = Any()
    private val memoryCache = object : LruCache<String, Bitmap>(DEFAULT_MEMORY_CACHE_BYTES) {
        override fun sizeOf(key: String, value: Bitmap): Int = value.allocationByteCount
    }
    private val hotCache = object : LruCache<String, Bitmap>(DEFAULT_HOT_CACHE_BYTES) {
        override fun sizeOf(key: String, value: Bitmap): Int = value.allocationByteCount
    }
    private val pinnedCache = object : LruCache<String, Bitmap>(DEFAULT_PINNED_CACHE_BYTES) {
        override fun sizeOf(key: String, value: Bitmap): Int = value.allocationByteCount
    }
    private val pinnedReferences = mutableMapOf<String, Int>()
    private val resizedWriteScope = CoroutineScope(
        SupervisorJob() + Dispatchers.IO.limitedParallelism(1),
    )
    private val resizedWrites = mutableSetOf<String>()
    private var configuredMemoryClassMb: Int? = null

    fun configure(context: Context) {
        val activityManager = context.getSystemService(ActivityManager::class.java)
        val memoryClassMb = activityManager?.memoryClass ?: 128
        val isLowRamDevice = activityManager?.isLowRamDevice == true
        synchronized(cacheLock) {
            if (configuredMemoryClassMb == memoryClassMb) return
            configuredMemoryClassMb = memoryClassMb

            val totalBudgetMiB = when {
                isLowRamDevice -> 32
                memoryClassMb < 192 -> 48
                memoryClassMb < 256 -> 64
                memoryClassMb < 512 -> 96
                else -> 128
            }
            val pinnedBudgetMiB = totalBudgetMiB / 2
            val recentBudgetMiB = totalBudgetMiB / 4
            val generalBudgetMiB = totalBudgetMiB - pinnedBudgetMiB - recentBudgetMiB
            memoryCache.resize(generalBudgetMiB * BYTES_PER_MIB)
            hotCache.resize(recentBudgetMiB * BYTES_PER_MIB)
            pinnedCache.resize(pinnedBudgetMiB * BYTES_PER_MIB)
        }
    }

    fun memory(rawUrl: String, maxDimensionPx: Int?): Bitmap? = synchronized(cacheLock) {
        val key = bitmapCacheKey(rawUrl, maxDimensionPx)
        pinnedCache.get(key)?.let { return@synchronized it }
        hotCache.get(key)?.let { return@synchronized it }
        memoryCache.get(key)?.also { hotCache.put(key, it) }
    }

    fun pin(rawUrl: String, maxDimensionPx: Int?) = synchronized(cacheLock) {
        val key = bitmapCacheKey(rawUrl, maxDimensionPx)
        val references = (pinnedReferences[key] ?: 0) + 1
        pinnedReferences[key] = references
        if (references > 1) return@synchronized

        val bitmap = pinnedCache.get(key) ?: hotCache.get(key) ?: memoryCache.get(key)
        if (bitmap != null) {
            pinnedCache.put(key, bitmap)
            hotCache.remove(key)
            memoryCache.remove(key)
        }
    }

    fun unpin(rawUrl: String, maxDimensionPx: Int?) = synchronized(cacheLock) {
        val key = bitmapCacheKey(rawUrl, maxDimensionPx)
        val references = pinnedReferences[key] ?: return@synchronized
        if (references > 1) {
            pinnedReferences[key] = references - 1
            return@synchronized
        }
        pinnedReferences.remove(key)
        val bitmap = pinnedCache.remove(key)
        if (bitmap != null) {
            memoryCache.put(key, bitmap)
            hotCache.put(key, bitmap)
        }
    }

    fun load(context: Context, rawUrl: String, maxDimensionPx: Int?): Bitmap? {
        loadCached(context, rawUrl, maxDimensionPx)?.let { return it }

        val bitmapKey = bitmapCacheKey(rawUrl, maxDimensionPx)
        val sourceKey = sourceCacheKey(rawUrl)
        val decodeMaxDimension = normalizedMaxDimension(maxDimensionPx)

        val cacheDirectory = File(context.cacheDir, "sparkle-thumbnails").apply { mkdirs() }
        val cacheFile = File(cacheDirectory, sourceKey)
        val resizedFile = resizedCacheFile(cacheDirectory, sourceKey, decodeMaxDimension)

        val temporaryFile = File(cacheDirectory, "$sourceKey.${UUID.randomUUID()}.tmp")
        return try {
            if (!downloadTo(rawUrl, temporaryFile)) return null
            val bitmap = decodeBitmap(temporaryFile, decodeMaxDimension) ?: return null
            if (temporaryFile.length() <= MAX_ENTRY_BYTES) {
                if (!temporaryFile.renameTo(cacheFile)) {
                    temporaryFile.delete()
                }
            } else {
                temporaryFile.delete()
            }
            scheduleResizedCache(cacheDirectory, resizedFile, bitmap)
            trimDiskCache(cacheDirectory)
            putMemory(bitmapKey, bitmap)
            bitmap
        } finally {
            temporaryFile.delete()
        }
    }

    fun loadCached(context: Context, rawUrl: String, maxDimensionPx: Int?): Bitmap? {
        val bitmapKey = bitmapCacheKey(rawUrl, maxDimensionPx)
        val decodeMaxDimension = normalizedMaxDimension(maxDimensionPx)
        memory(rawUrl, maxDimensionPx)?.let { return it }

        val cacheDirectory = File(context.cacheDir, "sparkle-thumbnails").apply { mkdirs() }
        val sourceKey = sourceCacheKey(rawUrl)
        val cacheFile = File(cacheDirectory, sourceKey)
        val resizedFile = resizedCacheFile(cacheDirectory, sourceKey, decodeMaxDimension)

        if (resizedFile.isFile) {
            val resized = decodeBitmap(resizedFile, decodeMaxDimension)
            if (resized != null) {
                resizedFile.setLastModified(System.currentTimeMillis())
                putMemory(bitmapKey, resized)
                return resized
            }
            resizedFile.delete()
        }
        if (!cacheFile.isFile) return null

        val cached = decodeBitmap(cacheFile, decodeMaxDimension)
        if (cached == null) {
            cacheFile.delete()
            return null
        }
        cacheFile.setLastModified(System.currentTimeMillis())
        putMemory(bitmapKey, cached)
        scheduleResizedCache(cacheDirectory, resizedFile, cached)
        return cached
    }

    private fun putMemory(key: String, bitmap: Bitmap) {
        synchronized(cacheLock) {
            if (pinnedReferences.containsKey(key)) {
                pinnedCache.put(key, bitmap)
                hotCache.remove(key)
                memoryCache.remove(key)
            } else {
                memoryCache.put(key, bitmap)
                hotCache.put(key, bitmap)
            }
        }
    }

    private fun resizedCacheFile(directory: File, sourceKey: String, maxDimension: Int): File =
        File(directory, "$sourceKey-$maxDimension.webp")

    private fun scheduleResizedCache(directory: File, target: File, bitmap: Bitmap) {
        val targetKey = target.absolutePath
        synchronized(cacheLock) {
            if (!resizedWrites.add(targetKey)) return
        }
        resizedWriteScope.launch {
            try {
                writeResizedCache(directory, target, bitmap)
            } finally {
                synchronized(cacheLock) { resizedWrites.remove(targetKey) }
            }
        }
    }

    @Suppress("DEPRECATION")
    private fun writeResizedCache(directory: File, target: File, bitmap: Bitmap) {
        val temporaryFile = File(directory, "${target.name}.${UUID.randomUUID()}.tmp")
        try {
            val compressed = FileOutputStream(temporaryFile).use { output ->
                bitmap.compress(Bitmap.CompressFormat.WEBP, 88, output)
            }
            if (!compressed || temporaryFile.length() <= 0L || temporaryFile.length() > MAX_ENTRY_BYTES) return
            if (target.isFile) target.delete()
            if (!temporaryFile.renameTo(target)) return
            trimDiskCache(directory)
        } finally {
            temporaryFile.delete()
        }
    }

    private fun downloadTo(rawUrl: String, destination: File): Boolean {
        return try {
            if (rawUrl.startsWith("data:")) {
                val encoded = rawUrl.substringAfter(',', "")
                if (encoded.isBlank()) return false
                if (encoded.length.toLong() > MAX_ENTRY_BYTES * 2) return false
                val bytes = Base64.decode(encoded, Base64.DEFAULT)
                if (bytes.size > MAX_ENTRY_BYTES) return false
                FileOutputStream(destination).use { it.write(bytes) }
                true
            } else {
                val connection = (URL(rawUrl).openConnection() as HttpURLConnection).apply {
                    connectTimeout = 10_000
                    readTimeout = 10_000
                    useCaches = true
                    setRequestProperty("Accept", "image/*")
                }
                try {
                    if (connection.responseCode !in 200..299) return false
                    connection.inputStream.use { input ->
                        FileOutputStream(destination).use { output ->
                            val buffer = ByteArray(32 * 1024)
                            var total = 0L
                            while (true) {
                                val count = input.read(buffer)
                                if (count < 0) break
                                total += count
                                if (total > MAX_ENTRY_BYTES) return false
                                output.write(buffer, 0, count)
                            }
                        }
                    }
                    true
                } finally {
                    connection.disconnect()
                }
            }
        } catch (_: Exception) {
            false
        }
    }

    private fun decodeBitmap(file: File, maxDimension: Int): Bitmap? {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.absolutePath, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        val options = BitmapFactory.Options().apply {
            inSampleSize = sampleSize(bounds.outWidth, bounds.outHeight, maxDimension)
            inPreferredConfig = Bitmap.Config.ARGB_8888
        }
        return BitmapFactory.decodeFile(file.absolutePath, options)
    }

    private fun sampleSize(width: Int, height: Int, maxDimension: Int): Int {
        val largestDimension = maxOf(width, height)
        var sample = 1
        while (largestDimension / (sample * 2) >= maxDimension) {
            sample *= 2
        }
        return sample
    }

    private fun trimDiskCache(directory: File) {
        val files = directory.listFiles { file -> file.isFile && !file.name.endsWith(".tmp") }.orEmpty()
        var total = files.sumOf { it.length() }
        if (total <= DISK_CACHE_BYTES) return
        files.sortedBy { it.lastModified() }.forEach { file ->
            if (total <= DISK_CACHE_BYTES) return@forEach
            total -= file.length()
            file.delete()
        }
    }

    fun bitmapCacheKey(rawUrl: String, maxDimensionPx: Int?): String =
        "${sourceCacheKey(rawUrl)}-${normalizedMaxDimension(maxDimensionPx)}"

    private fun sourceCacheKey(rawUrl: String): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(rawUrl.toByteArray(Charsets.UTF_8))
        return buildString(digest.size * 2) {
            digest.forEach { byte -> append("%02x".format(byte.toInt() and 0xff)) }
        }
    }

    private fun normalizedMaxDimension(maxDimensionPx: Int?): Int =
        maxDimensionPx?.coerceIn(MIN_BITMAP_DIMENSION, MAX_BITMAP_DIMENSION) ?: MAX_BITMAP_DIMENSION
}
