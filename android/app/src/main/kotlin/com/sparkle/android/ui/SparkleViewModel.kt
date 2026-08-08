package com.sparkle.android.ui

import android.app.Application
import android.os.Handler
import android.os.Looper
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import com.sparkle.android.data.ApiException
import com.sparkle.android.data.Category
import com.sparkle.android.data.Clip
import com.sparkle.android.data.ClipDraft
import com.sparkle.android.data.ConnectionState
import com.sparkle.android.data.LibraryFilter
import com.sparkle.android.data.RemoteSnapshot
import com.sparkle.android.data.Screen
import com.sparkle.android.data.SparkleApi
import com.sparkle.android.data.SparklePreferences
import com.sparkle.android.data.Tag
import java.io.IOException
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class SparkleViewModel(application: Application) : AndroidViewModel(application) {
    private val preferences = SparklePreferences(application)
    private val mainHandler = Handler(Looper.getMainLooper())
    private val executor: ExecutorService = Executors.newSingleThreadExecutor()

    var baseUrl by mutableStateOf(preferences.baseUrl)
        private set
    var screen by mutableStateOf<Screen>(Screen.Library)
        private set
    var clips by mutableStateOf<List<Clip>>(emptyList())
        private set
    var categories by mutableStateOf<List<Category>>(emptyList())
        private set
    var tags by mutableStateOf<List<Tag>>(emptyList())
        private set
    var query by mutableStateOf("")
    var filter by mutableStateOf<LibraryFilter>(LibraryFilter.All)
        private set
    var connectionState by mutableStateOf<ConnectionState>(initialConnectionState())
        private set
    var isBusy by mutableStateOf(false)
        private set
    var errorMessage by mutableStateOf<String?>(null)
        private set

    private var api: SparkleApi? = SparkleApi.fromBaseUrl(baseUrl)

    init {
        if (api != null) refresh()
    }

    fun refresh() {
        val currentApi = api
        if (currentApi == null) {
            connectionState = ConnectionState.Unconfigured
            return
        }
        isBusy = true
        errorMessage = null
        connectionState = ConnectionState.Checking
        executor.execute {
            try {
                val snapshot = currentApi.loadSnapshot()
                postSnapshot(snapshot)
            } catch (error: Throwable) {
                postFailure(error)
            }
        }
    }

    fun saveConnection(rawBaseUrl: String) {
        val normalized = SparkleApi.normalizeBaseUrl(rawBaseUrl)
        if (normalized == null) {
            errorMessage = "HTTPS形式のPC URLを入力してください。例: https://sparkle.example.ts.net"
            connectionState = ConnectionState.Unavailable("接続先URLが未設定です")
            return
        }
        preferences.saveBaseUrl(normalized)
        baseUrl = normalized
        api = SparkleApi.fromBaseUrl(normalized)
        refresh()
    }

    fun clearConnection() {
        preferences.clearBaseUrl()
        baseUrl = ""
        api = null
        clips = emptyList()
        categories = emptyList()
        tags = emptyList()
        query = ""
        filter = LibraryFilter.All
        errorMessage = null
        connectionState = ConnectionState.Unconfigured
        screen = Screen.Library
    }

    fun createClip(draft: ClipDraft) {
        mutate { currentApi -> currentApi.createClip(draft) }
    }

    fun updateClip(clipId: Int, draft: ClipDraft) {
        mutate { currentApi -> currentApi.updateClip(clipId, draft) }
    }

    fun openDetail(clipId: Int) {
        errorMessage = null
        screen = Screen.Detail(clipId)
    }

    fun beginCreate() {
        errorMessage = null
        screen = Screen.Editor(null)
    }

    fun beginEdit(clipId: Int) {
        errorMessage = null
        screen = Screen.Editor(clipId)
    }

    fun openSettings() {
        errorMessage = null
        screen = Screen.Settings
    }

    fun goToLibrary() {
        errorMessage = null
        screen = Screen.Library
    }

    fun chooseFilter(nextFilter: LibraryFilter) {
        filter = nextFilter
        screen = Screen.Library
    }

    fun clearError() {
        errorMessage = null
    }

    fun clip(clipId: Int): Clip? = clips.firstOrNull { it.id == clipId }

    fun categoryName(categoryId: Int?): String? =
        categories.firstOrNull { it.id == categoryId }?.name

    fun visibleClips(): List<Clip> {
        val normalizedQuery = query.trim().lowercase()
        return clips.filter { clip ->
            val matchesFilter = when (val currentFilter = filter) {
                LibraryFilter.All -> true
                is LibraryFilter.Category -> categoryName(clip.categoryId) == currentFilter.name
                is LibraryFilter.Tag -> clip.tags.any { it.name == currentFilter.name }
            }
            if (!matchesFilter || normalizedQuery.isBlank()) return@filter matchesFilter
            val searchable = buildString {
                append(clip.displayTitle)
                append('\n')
                append(clip.url)
                append('\n')
                append(clip.comment.orEmpty())
                append('\n')
                append(categoryName(clip.categoryId).orEmpty())
                append('\n')
                append(clip.tags.joinToString(" ") { it.name })
            }.lowercase()
            searchable.contains(normalizedQuery)
        }
    }

    private fun mutate(operation: (SparkleApi) -> Clip) {
        val currentApi = api
        if (currentApi == null) {
            errorMessage = "先に設定からPC接続先を登録してください。"
            return
        }
        isBusy = true
        errorMessage = null
        connectionState = ConnectionState.Checking
        executor.execute {
            try {
                val changedClip = operation(currentApi)
                val snapshot = currentApi.loadSnapshot()
                mainHandler.post {
                    applySnapshot(snapshot)
                    isBusy = false
                    connectionState = ConnectionState.Connected
                    screen = Screen.Detail(changedClip.id)
                }
            } catch (error: Throwable) {
                postFailure(error)
            }
        }
    }

    private fun postSnapshot(snapshot: RemoteSnapshot) {
        mainHandler.post {
            applySnapshot(snapshot)
            isBusy = false
            connectionState = ConnectionState.Connected
        }
    }

    private fun applySnapshot(snapshot: RemoteSnapshot) {
        clips = snapshot.clips
        categories = snapshot.categories
        tags = snapshot.tags
    }

    private fun postFailure(error: Throwable) {
        mainHandler.post {
            isBusy = false
            val message = when (error) {
                is ApiException -> "PC APIに接続できません（HTTP ${error.statusCode}）。"
                is IOException -> "PCに接続できません。Tailscale接続とURLを確認してください。"
                else -> "PCデータを読み込めませんでした。URLとPCの状態を確認してください。"
            }
            errorMessage = message
            connectionState = ConnectionState.Unavailable(message)
        }
    }

    private fun initialConnectionState(): ConnectionState =
        if (baseUrl.isBlank()) {
            ConnectionState.Unconfigured
        } else {
            ConnectionState.Checking
        }

    override fun onCleared() {
        executor.shutdownNow()
        super.onCleared()
    }
}
