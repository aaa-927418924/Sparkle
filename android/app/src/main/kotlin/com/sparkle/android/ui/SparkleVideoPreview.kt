@file:androidx.annotation.OptIn(markerClass = [androidx.media3.common.util.UnstableApi::class])

package com.sparkle.android.ui

import android.content.Context
import android.net.Uri
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.database.StandaloneDatabaseProvider
import androidx.media3.datasource.DefaultHttpDataSource
import androidx.media3.datasource.cache.CacheDataSource
import androidx.media3.datasource.cache.LeastRecentlyUsedCacheEvictor
import androidx.media3.datasource.cache.SimpleCache
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.DefaultMediaSourceFactory
import androidx.media3.ui.PlayerView
import java.io.File

private const val VIDEO_CACHE_BYTES = 128L * 1024 * 1024

@Composable
fun SparkleVideoPreview(
    fileUrl: String,
    mimeType: String?,
) {
    val context = androidx.compose.ui.platform.LocalContext.current
    val player = remember(fileUrl, mimeType) {
        ExoPlayer.Builder(context)
            .setMediaSourceFactory(
                DefaultMediaSourceFactory(
                    SparkleVideoCache.dataSourceFactory(context.applicationContext),
                ),
            )
            .build()
            .apply {
                val mediaItem = MediaItem.Builder()
                    .setUri(Uri.parse(fileUrl))
                    .apply { mimeType?.let(::setMimeType) }
                    .build()
                setMediaItem(mediaItem)
                playWhenReady = true
                prepare()
            }
    }
    var playbackState by remember(player) { mutableStateOf(player.playbackState) }
    var playbackError by remember(player) { mutableStateOf<PlaybackException?>(null) }

    DisposableEffect(player) {
        val listener = object : Player.Listener {
            override fun onPlaybackStateChanged(state: Int) {
                playbackState = state
                if (state == Player.STATE_READY && player.playWhenReady) {
                    player.play()
                }
            }

            override fun onPlayerError(error: PlaybackException) {
                playbackError = error
            }
        }
        player.addListener(listener)
        onDispose {
            player.removeListener(listener)
            player.release()
        }
    }

    val isLoading = playbackError == null &&
        (playbackState == Player.STATE_IDLE || playbackState == Player.STATE_BUFFERING)
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(220.dp)
            .clip(MaterialTheme.shapes.medium)
            .background(Color.Black),
    ) {
        AndroidView(
            factory = { viewContext ->
                PlayerView(viewContext).apply {
                    setPlayer(player)
                    useController = true
                    controllerAutoShow = true
                    setShowBuffering(PlayerView.SHOW_BUFFERING_NEVER)
                }
            },
            update = { view -> view.setPlayer(player) },
            modifier = Modifier.fillMaxSize(),
        )
        if (isLoading) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .background(Color.Black.copy(alpha = 0.36f))
                    .semantics { contentDescription = "動画を読み込み中" },
                contentAlignment = Alignment.Center,
            ) {
                CircularProgressIndicator(color = Color.White)
            }
        }
        playbackError?.let {
            Card(
                modifier = Modifier.align(Alignment.Center).padding(12.dp),
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer),
                shape = RoundedCornerShape(16.dp),
            ) {
                Text(
                    "動画を再生できませんでした。PC接続とファイル形式を確認してください。",
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp),
                    color = MaterialTheme.colorScheme.onErrorContainer,
                )
            }
        }
    }
}

private object SparkleVideoCache {
    private val lock = Any()
    private var cache: SimpleCache? = null

    fun dataSourceFactory(context: Context): CacheDataSource.Factory {
        val sharedCache = synchronized(lock) {
            cache ?: SimpleCache(
                File(context.cacheDir, "sparkle-video"),
                LeastRecentlyUsedCacheEvictor(VIDEO_CACHE_BYTES),
                StandaloneDatabaseProvider(context),
            ).also { cache = it }
        }
        val upstream = DefaultHttpDataSource.Factory()
            .setConnectTimeoutMs(10_000)
            .setReadTimeoutMs(30_000)
            .setAllowCrossProtocolRedirects(false)
        return CacheDataSource.Factory()
            .setCache(sharedCache)
            .setUpstreamDataSourceFactory(upstream)
            .setFlags(CacheDataSource.FLAG_IGNORE_CACHE_ON_ERROR)
    }
}
