package com.sparkle.android.data

import android.net.Uri

data class Tag(
    val id: Int,
    val name: String,
)

data class Category(
    val id: Int,
    val name: String,
)

data class Clip(
    val id: Int,
    val url: String,
    val title: String?,
    val thumbnailUrl: String?,
    val comment: String?,
    val categoryId: Int?,
    val isFavorite: Boolean,
    val createdAt: String,
    val clipType: String,
    val fileRef: String?,
    val fileSize: Long?,
    val isFolder: Boolean,
    val projectIds: List<Int>,
    val tags: List<Tag>,
) {
    val displayTitle: String
        get() = title?.trim()?.takeIf { it.isNotEmpty() } ?: url
}

data class ClipSummary(
    val id: Int,
    val title: String?,
    val url: String,
    val thumbnailUrl: String?,
    val comment: String?,
    val tags: List<Tag>,
) {
    val displayTitle: String
        get() = title?.trim()?.takeIf { it.isNotEmpty() } ?: url
}

data class Task(
    val id: Int,
    val title: String,
    val isDone: Boolean,
    val clipId: Int?,
    val dueDate: String?,
    val priority: Int?,
    val createdAt: String,
    val projectId: Int?,
    val clip: ClipSummary?,
)

data class Note(
    val id: Int,
    val title: String,
    val body: String?,
    val isDone: Boolean,
    val createdAt: String,
    val updatedAt: String,
    val clips: List<ClipSummary>,
    val projectIds: List<Int>,
)

data class Project(
    val id: Int,
    val name: String,
    val description: String?,
    val isDone: Boolean,
    val createdAt: String,
)

data class ClipDraft(
    val url: String,
    val title: String?,
    val comment: String?,
    val category: String?,
    val tags: List<String>,
)

data class UploadSelection(
    val uri: Uri,
    val displayName: String,
    val mimeType: String?,
)

data class ClipCreationSource(
    val url: String = "",
    val title: String? = null,
    val upload: UploadSelection? = null,
)

data class UrlMetadata(
    val url: String,
    val title: String?,
)

sealed interface SharedTitleResolution {
    data object Idle : SharedTitleResolution
    data class Loading(val url: String) : SharedTitleResolution
    data class Resolved(val url: String, val title: String) : SharedTitleResolution
    data class Unavailable(val url: String) : SharedTitleResolution
}

data class RemoteSnapshot(
    val clips: List<Clip>,
    val categories: List<Category>,
    val tags: List<Tag>,
    val tasks: List<Task>,
    val notes: List<Note>,
    val projects: List<Project>,
)

data class AppSettings(
    val taskAutoDelete: String = "1w",
    val autoCreateNoteOnProject: Boolean = false,
)

enum class TaskAutoDeleteOption(val value: String, val label: String) {
    ThreeDays("3d", "3日後"),
    OneWeek("1w", "1週間後"),
    OneMonth("1m", "1か月後"),
    Never("never", "自動削除しない"),
    ;

    companion object {
        fun fromValue(value: String?): TaskAutoDeleteOption =
            values().firstOrNull { it.value == value } ?: OneWeek
    }
}

enum class ClipSortMode(val label: String) {
    DateDesc("最近追加した順"),
    Title("アルファベット順（タイトル）"),
    RecentOpened("最近開いた順"),
    Random("ランダム"),
}

enum class StatusFilter(val label: String) {
    All("すべて"),
    InProgress("進行中"),
    Completed("完了済み"),
}

sealed interface ConnectionState {
    data object Unconfigured : ConnectionState
    data object Checking : ConnectionState
    data object Connected : ConnectionState
    data class Unavailable(val reason: String) : ConnectionState
}

sealed interface Screen {
    data object Home : Screen
    data object TasksNotes : Screen
    data object Projects : Screen
    data class ProjectDetail(val projectId: Int) : Screen
    data class ProjectEditor(val projectId: Int?) : Screen
    data class TaskEditor(val taskId: Int?) : Screen
    data class NoteEditor(val noteId: Int?) : Screen
    data class Detail(val clipId: Int) : Screen
    data class Editor(val clipId: Int?) : Screen
    data object AppSettings : Screen
    data object Settings : Screen
}

class ApiException(
    val statusCode: Int,
    message: String,
) : Exception(message)
