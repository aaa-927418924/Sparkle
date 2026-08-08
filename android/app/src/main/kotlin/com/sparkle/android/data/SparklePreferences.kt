package com.sparkle.android.data

import android.content.Context

class SparklePreferences(context: Context) {
    private val preferences = context.getSharedPreferences(PREFERENCES_NAME, Context.MODE_PRIVATE)

    var baseUrl: String
        get() = preferences.getString(KEY_BASE_URL, "") ?: ""
        private set(value) {
            preferences.edit().putString(KEY_BASE_URL, value).apply()
        }

    fun saveBaseUrl(value: String) {
        baseUrl = value
    }

    fun clearBaseUrl() {
        preferences.edit().remove(KEY_BASE_URL).apply()
    }

    fun clipSortMode(): ClipSortMode = runCatching {
        ClipSortMode.valueOf(preferences.getString(KEY_CLIP_SORT_MODE, ClipSortMode.DateDesc.name).orEmpty())
    }.getOrDefault(ClipSortMode.DateDesc)

    fun saveClipSortMode(mode: ClipSortMode) {
        preferences.edit().putString(KEY_CLIP_SORT_MODE, mode.name).apply()
    }

    private companion object {
        const val PREFERENCES_NAME = "sparkle_android_preferences"
        const val KEY_BASE_URL = "pc_base_url"
        const val KEY_CLIP_SORT_MODE = "clip_sort_mode"
    }
}
