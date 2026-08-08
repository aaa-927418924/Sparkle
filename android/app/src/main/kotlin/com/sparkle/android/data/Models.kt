package com.sparkle.android.data

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
    val tags: List<Tag>,
) {
    val displayTitle: String
        get() = title?.trim()?.takeIf { it.isNotEmpty() } ?: url
}

data class ClipDraft(
    val url: String,
    val title: String?,
    val comment: String?,
    val category: String?,
    val tags: List<String>,
)

data class RemoteSnapshot(
    val clips: List<Clip>,
    val categories: List<Category>,
    val tags: List<Tag>,
)

sealed interface ConnectionState {
    data object Unconfigured : ConnectionState
    data object Checking : ConnectionState
    data object Connected : ConnectionState
    data class Unavailable(val reason: String) : ConnectionState
}

sealed interface Screen {
    data object Library : Screen
    data class Detail(val clipId: Int) : Screen
    data class Editor(val clipId: Int?) : Screen
    data object Settings : Screen
}

sealed interface LibraryFilter {
    data object All : LibraryFilter
    data class Category(val name: String) : LibraryFilter
    data class Tag(val name: String) : LibraryFilter
}

class ApiException(
    val statusCode: Int,
    message: String,
) : Exception(message)
