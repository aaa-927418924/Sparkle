package com.sparkle.android.ui

import android.app.Application
import android.content.ContentValues
import android.os.Handler
import android.os.Looper
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.annotation.RequiresApi
import androidx.lifecycle.AndroidViewModel
import com.sparkle.android.data.ApiException
import com.sparkle.android.data.AppSettings
import com.sparkle.android.data.Category
import com.sparkle.android.data.Clip
import com.sparkle.android.data.ClipCreationSource
import com.sparkle.android.data.ClipDraft
import com.sparkle.android.data.ClipSortMode
import com.sparkle.android.data.ConnectionState
import com.sparkle.android.data.Note
import com.sparkle.android.data.Project
import com.sparkle.android.data.RemoteSnapshot
import com.sparkle.android.data.Screen
import com.sparkle.android.data.SparkleApi
import com.sparkle.android.data.SparklePreferences
import com.sparkle.android.data.SharedTitleResolution
import com.sparkle.android.data.StatusFilter
import com.sparkle.android.data.Tag
import com.sparkle.android.data.Task
import com.sparkle.android.data.UploadSelection
import java.io.File
import java.io.IOException
import java.util.UUID
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import kotlin.random.Random

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
    var appSettings by mutableStateOf(AppSettings())
        private set
    var tasksNotesTab by mutableStateOf(0)
        private set
    var query by mutableStateOf("")
    var selectedCategory by mutableStateOf<String?>(null)
        private set
    var selectedTags by mutableStateOf<Set<String>>(emptySet())
        private set
    var favoritesOnly by mutableStateOf(false)
        private set
    var clipSortMode by mutableStateOf(preferences.clipSortMode())
        private set
    var taskFilter by mutableStateOf(StatusFilter.InProgress)
        private set
    var noteFilter by mutableStateOf(StatusFilter.InProgress)
        private set
    var projectFilter by mutableStateOf(StatusFilter.InProgress)
        private set
    var editorSource by mutableStateOf<ClipCreationSource?>(null)
        private set
    var sharedTitleResolution by mutableStateOf<SharedTitleResolution>(SharedTitleResolution.Idle)
        private set
    var connectionState by mutableStateOf(initialConnectionState())
        private set
    var isBusy by mutableStateOf(false)
        private set
    var errorMessage by mutableStateOf<String?>(null)
        private set
    var fileActionMessage by mutableStateOf<String?>(null)
        private set
    var fileActionBusy by mutableStateOf(false)
        private set

    private var api: SparkleApi? = SparkleApi.fromBaseUrl(baseUrl)
    private var returnHomeAfterConnection = false
    private var sharedTitleRequestId = 0
    private val clipOpenedAt = mutableMapOf<Int, Long>()
    private val randomClipOrder = mutableMapOf<Int, Double>()
    private var homeScrolling = false
    private var pendingSnapshot: RemoteSnapshot? = null

    init {
        if (api != null) refresh()
    }

    fun refresh(silent: Boolean = false) {
        val currentApi = api
        if (currentApi == null) {
            connectionState = ConnectionState.Unconfigured
            return
        }
        if (silent && homeScrolling && screen is Screen.Home) return
        if (isBusy || refreshInFlight) return
        refreshInFlight = true
        if (!silent) {
            isBusy = true
            errorMessage = null
            connectionState = ConnectionState.Checking
            taskFilter = StatusFilter.InProgress
            noteFilter = StatusFilter.InProgress
            projectFilter = StatusFilter.InProgress
        }
        executor.execute {
            try {
                val snapshot = currentApi.loadSnapshot()
                mainHandler.post {
                    refreshInFlight = false
                    applySnapshotWhenReady(snapshot)
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
        if (api != null && !isBusy) {
            refresh(silent = true)
            if (screen is Screen.AppSettings) refreshAppSettings(silent = true)
        }
    }

    fun setHomeScrolling(scrolling: Boolean) {
        if (homeScrolling == scrolling) return
        homeScrolling = scrolling
        if (!scrolling) {
            pendingSnapshot?.also { snapshot ->
                pendingSnapshot = null
                applySnapshot(snapshot)
            }
        }
    }

    fun refreshAppSettings(silent: Boolean = false) {
        val currentApi = api
        if (currentApi == null) {
            connectionState = ConnectionState.Unconfigured
            return
        }
        if (!silent) {
            isBusy = true
            errorMessage = null
            connectionState = ConnectionState.Checking
        }
        executor.execute {
            try {
                val settings = currentApi.loadAppSettings()
                mainHandler.post {
                    appSettings = settings
                    if (!silent) isBusy = false
                    connectionState = ConnectionState.Connected
                }
            } catch (error: Throwable) {
                postFailure(error, silent)
            }
        }
    }

    fun updateAppSetting(key: String, value: String) {
        val currentApi = requireApi() ?: return
        isBusy = true
        errorMessage = null
        connectionState = ConnectionState.Checking
        executor.execute {
            try {
                currentApi.updateAppSetting(key, value)
                val settings = currentApi.loadAppSettings()
                mainHandler.post {
                    appSettings = settings
                    isBusy = false
                    connectionState = ConnectionState.Connected
                }
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
        sharedTitleRequestId += 1
        sharedTitleResolution = SharedTitleResolution.Idle
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
        sharedTitleRequestId += 1
        sharedTitleResolution = SharedTitleResolution.Idle
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
                    applySnapshotWhenReady(snapshot)
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

    fun localFileUrl(clipId: Int): String? = api?.localFileUrl(clipId)

    fun loadTextPreview(clipId: Int): String {
        return api?.loadTextPreview(clipId) ?: throw IOException("PC接続設定がありません")
    }

    fun prepareLocalFilePreview(
        clipId: Int,
        fileName: String,
        mimeType: String?,
        onReady: (path: String, mimeType: String?) -> Unit,
    ) {
        val currentApi = api ?: run {
            fileActionMessage = "先にPC接続設定を登録してください。"
            return
        }
        if (fileActionBusy) return
        fileActionBusy = true
        fileActionMessage = null
        executor.execute {
            val previewDirectory = File(getApplication<Application>().cacheDir, "sparkle-file-preview")
                .apply { mkdirs() }
            trimPreviewCache(previewDirectory)
            val target = File(previewDirectory, "${clipId}-${UUID.randomUUID()}-${sanitizeFileName(fileName)}")
            try {
                target.outputStream().use { output ->
                    currentApi.streamLocalFile(clipId, output, MAX_LOCAL_PREVIEW_BYTES)
                }
                trimPreviewCache(previewDirectory, protected = target)
                mainHandler.post {
                    fileActionBusy = false
                    onReady(target.absolutePath, mimeType)
                }
            } catch (error: Throwable) {
                target.delete()
                mainHandler.post {
                    fileActionBusy = false
                    fileActionMessage = localFileErrorMessage(error, preview = true)
                }
            }
        }
    }

    fun downloadLocalFile(clipId: Int, fileName: String, mimeType: String?) {
        val currentApi = api ?: run {
            fileActionMessage = "先にPC接続設定を登録してください。"
            return
        }
        if (fileActionBusy) return
        fileActionBusy = true
        fileActionMessage = null
        executor.execute {
            try {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    downloadToMediaStore(currentApi, clipId, fileName, mimeType)
                } else {
                    downloadToAppSpecificDirectory(currentApi, clipId, fileName)
                }
                mainHandler.post {
                    fileActionBusy = false
                    fileActionMessage = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                        "「${sanitizeFileName(fileName)}」をDownloads/Sparkleに保存しました。"
                    } else {
                        "「${sanitizeFileName(fileName)}」をアプリ専用のDownloads/Sparkleに保存しました。"
                    }
                }
            } catch (error: Throwable) {
                mainHandler.post {
                    fileActionBusy = false
                    fileActionMessage = localFileErrorMessage(error, preview = false)
                }
            }
        }
    }

    fun clearFileActionMessage() {
        fileActionMessage = null
    }

    fun showFileActionMessage(message: String) {
        fileActionMessage = message
    }

    fun updateClip(clipId: Int, draft: ClipDraft) {
        mutateClip { currentApi -> currentApi.updateClip(clipId, draft) }
    }

    fun deleteClip(clipId: Int) {
        runWorkspaceMutation(Screen.Home) { currentApi ->
            currentApi.deleteClip(clipId)
        }
    }

    fun toggleFavorite(clipId: Int) {
        runWorkspaceMutation(null) { currentApi ->
            currentApi.toggleFavorite(clipId)
        }
    }

    fun saveTask(
        taskId: Int?,
        title: String,
        dueDate: String?,
        priority: Int?,
        noteIds: Set<Int>,
    ) {
        if (title.isBlank()) {
            errorMessage = "タスク名を入力してください。"
            return
        }
        val currentApi = requireApi() ?: return
        val existingNotes = notes
        isBusy = true
        errorMessage = null
        connectionState = ConnectionState.Checking
        executor.execute {
            try {
                val savedTask = if (taskId == null) {
                    currentApi.createTask(title.trim(), dueDate?.trim()?.takeIf { it.isNotEmpty() }, priority)
                } else {
                    currentApi.updateTask(taskId, title.trim(), dueDate?.trim()?.takeIf { it.isNotEmpty() }, priority)
                }
                existingNotes.forEach { note ->
                    val desiredTaskIds = note.taskIds
                        .filter { it != savedTask.id }
                        .let { ids -> if (note.id in noteIds) ids + savedTask.id else ids }
                    if (desiredTaskIds != note.taskIds) {
                        currentApi.updateNoteTaskLinks(note.id, desiredTaskIds.distinct())
                    }
                }
                postSnapshot(currentApi.loadSnapshot()) {
                    screen = Screen.TasksNotes
                    tasksNotesTab = 0
                }
            } catch (error: Throwable) {
                postFailure(error)
            }
        }
    }

    fun deleteTask(taskId: Int) {
        runWorkspaceMutation(Screen.TasksNotes) { currentApi ->
            currentApi.deleteTask(taskId)
        }
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

    fun saveNote(noteId: Int?, title: String, body: String?, taskIds: Set<Int>) {
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
                if (noteId == null) {
                    currentApi.createNote(
                        title = title.trim(),
                        body = body?.trim()?.takeIf { it.isNotEmpty() },
                        taskIds = taskIds.toList(),
                    )
                } else {
                    currentApi.updateNote(
                        noteId = noteId,
                        title = title.trim(),
                        body = body?.trim()?.takeIf { it.isNotEmpty() },
                        taskIds = taskIds.toList(),
                    )
                }
                val snapshot = currentApi.loadSnapshot()
                mainHandler.post {
                    applySnapshotWhenReady(snapshot)
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

    fun deleteNote(noteId: Int) {
        runWorkspaceMutation(Screen.TasksNotes) { currentApi ->
            currentApi.deleteNote(noteId)
        }
    }

    fun saveProject(projectId: Int?, name: String, description: String?) {
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
                val savedProject = if (projectId == null) {
                    currentApi.createProject(name.trim(), description?.trim()?.takeIf { it.isNotEmpty() })
                } else {
                    currentApi.updateProject(projectId, name.trim(), description?.trim()?.takeIf { it.isNotEmpty() })
                }
                val snapshot = currentApi.loadSnapshot()
                mainHandler.post {
                    applySnapshotWhenReady(snapshot)
                    isBusy = false
                    connectionState = ConnectionState.Connected
                    screen = Screen.ProjectDetail(savedProject.id)
                }
            } catch (error: Throwable) {
                postFailure(error)
            }
        }
    }

    fun toggleProject(projectId: Int) {
        runWorkspaceMutation(null) { currentApi ->
            currentApi.toggleProject(projectId)
        }
    }

    fun deleteProject(projectId: Int) {
        runWorkspaceMutation(Screen.Projects) { currentApi ->
            currentApi.deleteProject(projectId)
        }
    }

    fun saveProjectLinks(projectId: Int, clipIds: Set<Int>, taskIds: Set<Int>, noteIds: Set<Int>) {
        val currentApi = requireApi() ?: return
        val currentClipIds = projectClips(projectId).map { it.id }.toSet()
        val currentTaskIds = projectTasks(projectId).map { it.id }.toSet()
        val currentNoteIds = projectNotes(projectId).map { it.id }.toSet()
        isBusy = true
        errorMessage = null
        connectionState = ConnectionState.Checking
        executor.execute {
            try {
                (clipIds - currentClipIds).forEach { currentApi.linkProjectClip(projectId, it) }
                (currentClipIds - clipIds).forEach { currentApi.unlinkProjectClip(projectId, it) }
                (noteIds - currentNoteIds).forEach { currentApi.linkProjectNote(projectId, it) }
                (currentNoteIds - noteIds).forEach { currentApi.unlinkProjectNote(projectId, it) }
                tasks.forEach { task ->
                    val shouldBelong = task.id in taskIds
                    val belongsNow = task.id in currentTaskIds
                    if (shouldBelong != belongsNow) {
                        currentApi.updateTaskProject(task.id, if (shouldBelong) projectId else null)
                    }
                }
                postSnapshot(currentApi.loadSnapshot()) {
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
        clipOpenedAt[clipId] = System.currentTimeMillis()
        screen = Screen.Detail(clipId)
    }

    fun beginCreate(source: ClipCreationSource = ClipCreationSource()) {
        errorMessage = null
        sharedTitleRequestId += 1
        sharedTitleResolution = SharedTitleResolution.Idle
        editorSource = source
        screen = Screen.Editor(null)
    }

    fun beginEdit(clipId: Int) {
        errorMessage = null
        sharedTitleRequestId += 1
        sharedTitleResolution = SharedTitleResolution.Idle
        editorSource = null
        screen = Screen.Editor(clipId)
    }

    fun resolveSharedTitle(rawUrl: String) {
        val url = rawUrl.trim()
        if (url.isBlank()) return
        val currentResolution = sharedTitleResolution
        if (currentResolution is SharedTitleResolution.Loading && currentResolution.url == url) return
        if (currentResolution is SharedTitleResolution.Resolved && currentResolution.url == url) return
        val currentApi = api
        if (currentApi == null) {
            sharedTitleResolution = SharedTitleResolution.Unavailable(url)
            return
        }
        val requestId = ++sharedTitleRequestId
        sharedTitleResolution = SharedTitleResolution.Loading(url)
        executor.execute {
            try {
                val title = currentApi.loadUrlMetadata(url).title
                    ?.trim()
                    ?.takeIf { it.isNotEmpty() }
                mainHandler.post {
                    if (requestId != sharedTitleRequestId) return@post
                    sharedTitleResolution = if (title != null) {
                        SharedTitleResolution.Resolved(url, title)
                    } else {
                        SharedTitleResolution.Unavailable(url)
                    }
                }
            } catch (_: Throwable) {
                mainHandler.post {
                    if (requestId == sharedTitleRequestId) {
                        sharedTitleResolution = SharedTitleResolution.Unavailable(url)
                    }
                }
            }
        }
    }

    fun openSettings() {
        errorMessage = null
        screen = Screen.Settings
    }

    fun openAppSettings() {
        errorMessage = null
        screen = Screen.AppSettings
        refreshAppSettings()
    }

    fun goToHome() {
        errorMessage = null
        sharedTitleRequestId += 1
        sharedTitleResolution = SharedTitleResolution.Idle
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

    fun openProjectEditor(projectId: Int?) {
        errorMessage = null
        screen = Screen.ProjectEditor(projectId)
    }

    fun openTaskEditor(taskId: Int?) {
        errorMessage = null
        screen = Screen.TaskEditor(taskId)
    }

    fun openNoteEditor(noteId: Int?) {
        errorMessage = null
        tasksNotesTab = 1
        screen = Screen.NoteEditor(noteId)
    }

    fun goBack() {
        val currentScreen = screen
        when (currentScreen) {
            is Screen.Detail, is Screen.Editor, Screen.AppSettings, Screen.Settings -> goToHome()
            is Screen.ProjectDetail -> openProjects()
            is Screen.ProjectEditor -> currentScreen.projectId?.let(::openProject) ?: openProjects()
            is Screen.TaskEditor -> openTasksNotes(tab = 0)
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

    fun toggleFavoritesOnly() {
        favoritesOnly = !favoritesOnly
    }

    fun selectClipSortMode(mode: ClipSortMode) {
        clipSortMode = mode
        preferences.saveClipSortMode(mode)
    }

    fun selectTaskFilter(filter: StatusFilter) {
        taskFilter = filter
    }

    fun selectNoteFilter(filter: StatusFilter) {
        noteFilter = filter
    }

    fun selectProjectFilter(filter: StatusFilter) {
        projectFilter = filter
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
        val filtered = clips.filter { clip ->
            val matchesCategory = selectedCategory == null || categoryName(clip.categoryId) == selectedCategory
            val matchesTags = selectedTags.all { wanted -> clip.tags.any { it.name == wanted } }
            val matchesFavorite = !favoritesOnly || clip.isFavorite
            if (!matchesCategory || !matchesTags) return@filter false
            if (!matchesFavorite) return@filter false
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
        return when (clipSortMode) {
            ClipSortMode.DateDesc -> filtered.sortedWith(compareByDescending<Clip> { it.createdAt }.thenByDescending { it.id })
            ClipSortMode.Title -> filtered.sortedWith(compareBy(String.CASE_INSENSITIVE_ORDER) { it.displayTitle })
            ClipSortMode.RecentOpened -> filtered.sortedWith(compareByDescending<Clip> { clipOpenedAt[ it.id ] ?: 0L }.thenByDescending { it.createdAt })
            ClipSortMode.Random -> filtered.sortedBy { randomClipOrder.getOrPut(it.id) { Random.nextDouble() } }
        }
    }

    fun visibleTasks(): List<Task> = tasks
        .filter { task -> taskFilter.matches(task.isDone) }
        .sortedWith(compareByDescending<Task> { it.priority ?: -1 }.thenByDescending { it.createdAt })

    fun isHighestPriorityTask(task: Task): Boolean {
        val highestPriority = tasks
            .asSequence()
            .filter { !it.isDone && it.priority != null }
            .mapNotNull { it.priority }
            .maxOrNull()
        return !task.isDone && task.priority != null && task.priority == highestPriority
    }

    fun visibleNotes(): List<Note> = notes.filter { note -> noteFilter.matches(note.isDone) }

    fun visibleProjects(): List<Project> = projects.filter { project -> projectFilter.matches(project.isDone) }

    fun project(projectId: Int): Project? = projects.firstOrNull { it.id == projectId }

    fun task(taskId: Int): Task? = tasks.firstOrNull { it.id == taskId }

    fun note(noteId: Int?): Note? = noteId?.let { id -> notes.firstOrNull { it.id == id } }

    fun projectClips(projectId: Int): List<Clip> = clips.filter { projectId in it.projectIds }

    fun projectTasks(projectId: Int): List<Task> = tasks
        .filter { it.projectId == projectId }
        .sortedWith(compareByDescending<Task> { it.priority ?: -1 }.thenByDescending { it.createdAt })

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
                    applySnapshotWhenReady(snapshot)
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

    private fun runWorkspaceMutation(destination: Screen?, operation: (SparkleApi) -> Unit) {
        val currentApi = requireApi() ?: return
        isBusy = true
        errorMessage = null
        connectionState = ConnectionState.Checking
        executor.execute {
            try {
                operation(currentApi)
                postSnapshot(currentApi.loadSnapshot()) {
                    destination?.let { screen = it }
                }
            } catch (error: Throwable) {
                postFailure(error)
            }
        }
    }

    private fun postSnapshot(snapshot: RemoteSnapshot, afterApplied: () -> Unit = {}) {
        mainHandler.post {
            applySnapshotWhenReady(snapshot)
            isBusy = false
            connectionState = ConnectionState.Connected
            if (returnHomeAfterConnection) {
                returnHomeAfterConnection = false
                screen = Screen.Home
            }
            afterApplied()
        }
    }

    private fun applySnapshotWhenReady(snapshot: RemoteSnapshot) {
        if (homeScrolling && screen is Screen.Home) {
            pendingSnapshot = snapshot
        } else {
            applySnapshot(snapshot)
        }
    }

    private fun applySnapshot(snapshot: RemoteSnapshot) {
        if (clips != snapshot.clips) clips = snapshot.clips
        if (categories != snapshot.categories) categories = snapshot.categories
        if (selectedCategory != null && snapshot.categories.none { it.name == selectedCategory }) {
            selectedCategory = null
        }
        if (tags != snapshot.tags) tags = snapshot.tags
        if (tasks != snapshot.tasks) tasks = snapshot.tasks
        if (notes != snapshot.notes) notes = snapshot.notes
        if (projects != snapshot.projects) projects = snapshot.projects
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

    @RequiresApi(Build.VERSION_CODES.Q)
    private fun downloadToMediaStore(
        currentApi: SparkleApi,
        clipId: Int,
        fileName: String,
        mimeType: String?,
    ) {
        val resolver = getApplication<Application>().contentResolver
        val values = ContentValues().apply {
            put(MediaStore.MediaColumns.DISPLAY_NAME, sanitizeFileName(fileName))
            mimeType?.let { put(MediaStore.MediaColumns.MIME_TYPE, it) }
            put(MediaStore.MediaColumns.RELATIVE_PATH, "${Environment.DIRECTORY_DOWNLOADS}/Sparkle")
            put(MediaStore.MediaColumns.IS_PENDING, 1)
        }
        val collection = MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)
        val uri = resolver.insert(collection, values)
            ?: throw IOException("Downloadsフォルダへ保存できません")
        try {
            resolver.openOutputStream(uri)?.use { output ->
                currentApi.streamLocalFile(clipId, output)
            } ?: throw IOException("保存先を開けません")
            resolver.update(
                uri,
                ContentValues().apply { put(MediaStore.MediaColumns.IS_PENDING, 0) },
                null,
                null,
            )
        } catch (error: Throwable) {
            resolver.delete(uri, null, null)
            throw error
        }
    }

    private fun downloadToAppSpecificDirectory(currentApi: SparkleApi, clipId: Int, fileName: String) {
        val root = getApplication<Application>().getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS)
            ?: throw IOException("Downloadsフォルダを利用できません")
        val directory = File(root, "Sparkle").apply { mkdirs() }
        File(directory, sanitizeFileName(fileName)).outputStream().use { output ->
            currentApi.streamLocalFile(clipId, output)
        }
    }

    private fun trimPreviewCache(directory: File, protected: File? = null) {
        val files = directory.listFiles { file -> file.isFile }.orEmpty()
        var total = files.sumOf { it.length() }
        if (total <= FILE_PREVIEW_CACHE_BYTES) return
        files.sortedBy { it.lastModified() }.forEach { file ->
            if (total <= FILE_PREVIEW_CACHE_BYTES) return@forEach
            if (file == protected) return@forEach
            total -= file.length()
            file.delete()
        }
    }

    private fun localFileErrorMessage(error: Throwable, preview: Boolean): String = when {
        error is ApiException -> "ローカルファイルを取得できません（HTTP ${error.statusCode}）。"
        error is IOException && preview && error.message?.contains("大きすぎます") == true ->
            "プレビューできるサイズを超えています。ダウンロードを試してください。"
        error is IOException -> "PCからローカルファイルを取得できません。PCとTailscale接続を確認してください。"
        else -> if (preview) "ローカルファイルをプレビューできませんでした。" else "ローカルファイルをダウンロードできませんでした。"
    }

    override fun onCleared() {
        executor.shutdownNow()
        super.onCleared()
    }
}

private const val MAX_LOCAL_PREVIEW_BYTES = 128L * 1024 * 1024
private const val FILE_PREVIEW_CACHE_BYTES = 128L * 1024 * 1024

private fun sanitizeFileName(raw: String): String {
    val sanitized = raw
        .replace(Regex("[<>:\"/\\\\|?*]"), "_")
        .trim()
        .trimEnd('.')
        .take(180)
    return sanitized.ifBlank { "sparkle-file" }
}

private fun StatusFilter.matches(isDone: Boolean): Boolean = when (this) {
    StatusFilter.All -> true
    StatusFilter.InProgress -> !isDone
    StatusFilter.Completed -> isDone
}
