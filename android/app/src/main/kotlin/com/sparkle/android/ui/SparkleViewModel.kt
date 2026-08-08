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
import com.sparkle.android.data.ClipCreationSource
import com.sparkle.android.data.ClipDraft
import com.sparkle.android.data.ConnectionState
import com.sparkle.android.data.Note
import com.sparkle.android.data.Project
import com.sparkle.android.data.RemoteSnapshot
import com.sparkle.android.data.Screen
import com.sparkle.android.data.SparkleApi
import com.sparkle.android.data.SparklePreferences
import com.sparkle.android.data.Tag
import com.sparkle.android.data.Task
import com.sparkle.android.data.UploadSelection
import java.io.IOException
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

class SparkleViewModel(application: Application) : AndroidViewModel(application) {
    private val preferences = SparklePreferences(application)
    private val mainHandler = Handler(Looper.getMainLooper())
    private val executor: ExecutorService = Executors.newSingleThreadExecutor()
    private var refreshInFlight = false

    var baseUrl by mutableStateOf(preferences.baseUrl)
        private set
    var screen by mutableStateOf<Screen>(Screen.Home)
        private set
    var clips by mutableStateOf<List<Clip>>(emptyList())
        private set
    var categories by mutableStateOf<List<Category>>(emptyList())
        private set
    var tags by mutableStateOf<List<Tag>>(emptyList())
        private set
    var tasks by mutableStateOf<List<Task>>(emptyList())
        private set
    var notes by mutableStateOf<List<Note>>(emptyList())
        private set
    var projects by mutableStateOf<List<Project>>(emptyList())
        private set
    var tasksNotesTab by mutableStateOf(0)
        private set
    var query by mutableStateOf("")
    var selectedCategory by mutableStateOf<String?>(null)
        private set
    var selectedTags by mutableStateOf<Set<String>>(emptySet())
        private set
    var editorSource by mutableStateOf<ClipCreationSource?>(null)
        private set
    var connectionState by mutableStateOf(initialConnectionState())
        private set
    var isBusy by mutableStateOf(false)
        private set
    var errorMessage by mutableStateOf<String?>(null)
        private set

    private var api: SparkleApi? = SparkleApi.fromBaseUrl(baseUrl)
    private var returnHomeAfterConnection = false

    init {
        if (api != null) refresh()
    }

    fun refresh(silent: Boolean = false) {
        val currentApi = api
        if (currentApi == null) {
            connectionState = ConnectionState.Unconfigured
            return
        }
        if (isBusy || refreshInFlight) return
        refreshInFlight = true
        if (!silent) {
            isBusy = true
            errorMessage = null
            connectionState = ConnectionState.Checking
        }
        executor.execute {
            try {
                val snapshot = currentApi.loadSnapshot()
                mainHandler.post {
                    refreshInFlight = false
                    applySnapshot(snapshot)
                    if (!silent) isBusy = false
                    connectionState = ConnectionState.Connected
                    if (returnHomeAfterConnection) {
                        returnHomeAfterConnection = false
                        screen = Screen.Home
                    }
                }
            } catch (error: Throwable) {
                postFailure(error, silent)
            }
        }
    }

    fun onAppResumed() {
        if (api != null && !isBusy) refresh(silent = true)
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
        returnHomeAfterConnection = true
        refresh()
    }

    fun clearConnection() {
        preferences.clearBaseUrl()
        baseUrl = ""
        api = null
        clips = emptyList()
        categories = emptyList()
        tags = emptyList()
        tasks = emptyList()
        notes = emptyList()
        projects = emptyList()
        query = ""
        clearFilters()
        returnHomeAfterConnection = false
        errorMessage = null
        connectionState = ConnectionState.Unconfigured
        goToHome()
    }

    fun createClip(draft: ClipDraft, upload: UploadSelection? = null) {
        val currentApi = requireApi() ?: return
        isBusy = true
        errorMessage = null
        connectionState = ConnectionState.Checking
        executor.execute {
            try {
                val changedClip = if (upload != null) {
                    currentApi.uploadLocalClip(getApplication<Application>().contentResolver, upload, draft)
                } else {
                    currentApi.createClip(draft)
                }
                val snapshot = currentApi.loadSnapshot()
                mainHandler.post {
                    applySnapshot(snapshot)
                    isBusy = false
                    connectionState = ConnectionState.Connected
                    editorSource = null
                    screen = Screen.Detail(changedClip.id)
                }
            } catch (error: Throwable) {
                postFailure(error)
            }
        }
    }

    fun updateClip(clipId: Int, draft: ClipDraft) {
        mutateClip { currentApi -> currentApi.updateClip(clipId, draft) }
    }

    fun toggleTask(taskId: Int) {
        val currentApi = requireApi() ?: return
        isBusy = true
        errorMessage = null
        executor.execute {
            try {
                currentApi.toggleTask(taskId)
                postSnapshot(currentApi.loadSnapshot())
            } catch (error: Throwable) {
                postFailure(error)
            }
        }
    }

    fun deleteCategory(categoryId: Int) {
        val currentApi = requireApi() ?: return
        isBusy = true
        errorMessage = null
        connectionState = ConnectionState.Checking
        executor.execute {
            try {
                currentApi.deleteCategory(categoryId)
                postSnapshot(currentApi.loadSnapshot())
            } catch (error: Throwable) {
                postFailure(error)
            }
        }
    }

    fun updateNote(noteId: Int, title: String, body: String?) {
        if (title.isBlank()) {
            errorMessage = "メモのタイトルを入力してください。"
            return
        }
        val currentApi = requireApi() ?: return
        isBusy = true
        errorMessage = null
        connectionState = ConnectionState.Checking
        executor.execute {
            try {
                currentApi.updateNote(noteId, title.trim(), body?.trim()?.takeIf { it.isNotEmpty() })
                val snapshot = currentApi.loadSnapshot()
                mainHandler.post {
                    applySnapshot(snapshot)
                    isBusy = false
                    connectionState = ConnectionState.Connected
                    tasksNotesTab = 1
                    screen = Screen.TasksNotes
                }
            } catch (error: Throwable) {
                postFailure(error)
            }
        }
    }

    fun updateProject(projectId: Int, name: String, description: String?) {
        if (name.isBlank()) {
            errorMessage = "プロジェクト名を入力してください。"
            return
        }
        val currentApi = requireApi() ?: return
        isBusy = true
        errorMessage = null
        connectionState = ConnectionState.Checking
        executor.execute {
            try {
                currentApi.updateProject(projectId, name.trim(), description?.trim()?.takeIf { it.isNotEmpty() })
                val snapshot = currentApi.loadSnapshot()
                mainHandler.post {
                    applySnapshot(snapshot)
                    isBusy = false
                    connectionState = ConnectionState.Connected
                    screen = Screen.ProjectDetail(projectId)
                }
            } catch (error: Throwable) {
                postFailure(error)
            }
        }
    }

    fun openDetail(clipId: Int) {
        errorMessage = null
        editorSource = null
        screen = Screen.Detail(clipId)
    }

    fun beginCreate(source: ClipCreationSource = ClipCreationSource()) {
        errorMessage = null
        editorSource = source
        screen = Screen.Editor(null)
    }

    fun beginEdit(clipId: Int) {
        errorMessage = null
        editorSource = null
        screen = Screen.Editor(clipId)
    }

    fun openSettings() {
        errorMessage = null
        screen = Screen.Settings
    }

    fun goToHome() {
        errorMessage = null
        editorSource = null
        screen = Screen.Home
        refresh()
    }

    fun openTasksNotes(tab: Int = 0) {
        errorMessage = null
        tasksNotesTab = tab.coerceIn(0, 1)
        screen = Screen.TasksNotes
        refresh()
    }

    fun openProjects() {
        errorMessage = null
        screen = Screen.Projects
        refresh()
    }

    fun openProject(projectId: Int) {
        errorMessage = null
        screen = Screen.ProjectDetail(projectId)
    }

    fun openProjectEditor(projectId: Int) {
        errorMessage = null
        screen = Screen.ProjectEditor(projectId)
    }

    fun openNoteEditor(noteId: Int) {
        errorMessage = null
        tasksNotesTab = 1
        screen = Screen.NoteEditor(noteId)
    }

    fun goBack() {
        val currentScreen = screen
        when (currentScreen) {
            is Screen.Detail, is Screen.Editor, Screen.Settings -> goToHome()
            is Screen.ProjectDetail -> openProjects()
            is Screen.ProjectEditor -> openProject(currentScreen.projectId)
            is Screen.NoteEditor -> openTasksNotes(tab = 1)
            else -> goToHome()
        }
    }

    fun selectCategory(categoryName: String?) {
        selectedCategory = categoryName
    }

    fun toggleTag(tagName: String) {
        selectedTags = if (tagName in selectedTags) selectedTags - tagName else selectedTags + tagName
    }

    fun clearFilters() {
        selectedCategory = null
        selectedTags = emptySet()
    }

    fun clearError() {
        errorMessage = null
    }

    fun clip(clipId: Int): Clip? = clips.firstOrNull { it.id == clipId }

    fun categoryName(categoryId: Int?): String? =
        categories.firstOrNull { it.id == categoryId }?.name

    fun thumbnailUrl(raw: String?): String? = api?.thumbnailRequestUrl(raw) ?: raw

    fun visibleClips(): List<Clip> {
        val normalizedQuery = query.trim().lowercase()
        return clips.filter { clip ->
            val matchesCategory = selectedCategory == null || categoryName(clip.categoryId) == selectedCategory
            val matchesTags = selectedTags.all { wanted -> clip.tags.any { it.name == wanted } }
            if (!matchesCategory || !matchesTags) return@filter false
            if (normalizedQuery.isBlank()) return@filter true
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

    fun project(projectId: Int): Project? = projects.firstOrNull { it.id == projectId }

    fun note(noteId: Int): Note? = notes.firstOrNull { it.id == noteId }

    fun projectClips(projectId: Int): List<Clip> = clips.filter { projectId in it.projectIds }

    fun projectTasks(projectId: Int): List<Task> = tasks.filter { it.projectId == projectId }

    fun projectNotes(projectId: Int): List<Note> = notes.filter { projectId in it.projectIds }

    private fun mutateClip(operation: (SparkleApi) -> Clip) {
        val currentApi = requireApi() ?: return
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

    private fun requireApi(): SparkleApi? {
        val currentApi = api
        if (currentApi == null) {
            errorMessage = "先にPC接続設定を登録してください。"
            connectionState = ConnectionState.Unconfigured
        }
        return currentApi
    }

    private fun postSnapshot(snapshot: RemoteSnapshot) {
        mainHandler.post {
            applySnapshot(snapshot)
            isBusy = false
            connectionState = ConnectionState.Connected
            if (returnHomeAfterConnection) {
                returnHomeAfterConnection = false
                screen = Screen.Home
            }
        }
    }

    private fun applySnapshot(snapshot: RemoteSnapshot) {
        clips = snapshot.clips
        categories = snapshot.categories
        if (selectedCategory != null && categories.none { it.name == selectedCategory }) {
            selectedCategory = null
        }
        tags = snapshot.tags
        tasks = snapshot.tasks
        notes = snapshot.notes
        projects = snapshot.projects
    }

    private fun postFailure(error: Throwable, silent: Boolean = false) {
        mainHandler.post {
            refreshInFlight = false
            isBusy = false
            returnHomeAfterConnection = false
            val message = when (error) {
                is ApiException -> "PC APIに接続できません（HTTP ${error.statusCode}）。"
                is IOException -> "PCに接続できません。Tailscale接続とURLを確認してください。"
                else -> "PCデータを読み込めませんでした。URLとPCの状態を確認してください。"
            }
            if (!silent) errorMessage = message
            connectionState = ConnectionState.Unavailable(message)
        }
    }

    private fun initialConnectionState(): ConnectionState =
        if (baseUrl.isBlank()) ConnectionState.Unconfigured else ConnectionState.Checking

    override fun onCleared() {
        executor.shutdownNow()
        super.onCleared()
    }
}
