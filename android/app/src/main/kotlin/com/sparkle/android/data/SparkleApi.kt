package com.sparkle.android.data

import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL

class SparkleApi private constructor(
    private val baseUrl: String,
) {
    fun loadSnapshot(): RemoteSnapshot {
        val categories = getArray("/categories").map(::parseCategory)
        val tags = getArray("/tags").map(::parseTag)
        val clips = getArray("/clips").map(::parseClip)
        return RemoteSnapshot(clips = clips, categories = categories, tags = tags)
    }

    fun checkHealth(): Boolean {
        val response = request("GET", "/health")
        return response.optString("status") == "ok" && response.optString("app") == "Sparkle"
    }

    fun createClip(draft: ClipDraft): Clip =
        parseClip(request("POST", "/clips", draft.toCreateJson()))

    fun updateClip(clipId: Int, draft: ClipDraft): Clip =
        parseClip(request("PUT", "/clips/$clipId", draft.toUpdateJson()))

    private fun getArray(path: String): List<JSONObject> {
        val array = requestArray("GET", path)
        return buildList(array.length()) {
            for (index in 0 until array.length()) {
                add(array.getJSONObject(index))
            }
        }
    }

    private fun requestArray(method: String, path: String): JSONArray {
        val response = requestRaw(method, path, null)
        return JSONArray(response)
    }

    private fun request(method: String, path: String, body: JSONObject? = null): JSONObject {
        return JSONObject(requestRaw(method, path, body))
    }

    private fun requestRaw(method: String, path: String, body: JSONObject?): String {
        val connection = (URL(baseUrl + path).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = TIMEOUT_MS
            readTimeout = TIMEOUT_MS
            useCaches = false
            setRequestProperty("Accept", "application/json")
            if (body != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
            }
        }

        return try {
            if (body != null) {
                connection.outputStream.use { output ->
                    output.writer(Charsets.UTF_8).use { writer -> writer.write(body.toString()) }
                }
            }
            val status = connection.responseCode
            if (status !in 200..299) {
                throw ApiException(status, "PC API returned HTTP $status")
            }
            connection.inputStream.bufferedReader(Charsets.UTF_8).use { it.readText() }
        } catch (error: ApiException) {
            throw error
        } catch (error: IOException) {
            throw IOException("PCに接続できません", error)
        } finally {
            connection.disconnect()
        }
    }

    private fun parseCategory(json: JSONObject): Category =
        Category(id = json.optInt("id"), name = json.optString("name"))

    private fun parseTag(json: JSONObject): Tag =
        Tag(id = json.optInt("id"), name = json.optString("name"))

    private fun parseClip(json: JSONObject): Clip {
        val tagsJson = json.optJSONArray("tags") ?: JSONArray()
        val tags = buildList(tagsJson.length()) {
            for (index in 0 until tagsJson.length()) {
                add(parseTag(tagsJson.getJSONObject(index)))
            }
        }
        return Clip(
            id = json.optInt("id"),
            url = json.optString("url"),
            title = nullableString(json, "title"),
            thumbnailUrl = nullableString(json, "thumbnail_url"),
            comment = nullableString(json, "comment"),
            categoryId = nullableInt(json, "category_id"),
            isFavorite = json.optBoolean("is_favorite"),
            createdAt = json.optString("created_at"),
            clipType = json.optString("clip_type", "url"),
            fileRef = nullableString(json, "file_ref"),
            tags = tags,
        )
    }

    companion object {
        private const val TIMEOUT_MS = 10_000

        fun fromBaseUrl(rawBaseUrl: String): SparkleApi? {
            val normalized = normalizeBaseUrl(rawBaseUrl) ?: return null
            return SparkleApi(normalized)
        }

        fun normalizeBaseUrl(rawBaseUrl: String): String? {
            val candidate = rawBaseUrl.trim().trimEnd('/')
            if (candidate.isBlank()) return null
            return try {
                val uri = URI(candidate)
                val path = uri.path.orEmpty()
                if (uri.scheme != "https" || uri.host.isNullOrBlank() || path.contains("//")) {
                    null
                } else {
                    candidate
                }
            } catch (_: Exception) {
                null
            }
        }

        private fun nullableString(json: JSONObject, key: String): String? {
            if (!json.has(key) || json.isNull(key)) return null
            return json.optString(key).takeIf { it.isNotBlank() }
        }

        private fun nullableInt(json: JSONObject, key: String): Int? {
            if (!json.has(key) || json.isNull(key)) return null
            return json.optInt(key)
        }
    }
}

private fun ClipDraft.toCreateJson(): JSONObject = JSONObject().apply {
    put("url", url.trim())
    putNullable("title", title)
    putNullable("comment", comment)
    putNullable("category", category)
    put("tags", JSONArray(tags.map(String::trim).filter(String::isNotEmpty).distinct()))
}

private fun ClipDraft.toUpdateJson(): JSONObject = JSONObject().apply {
    putNullable("title", title)
    putNullable("comment", comment)
    putNullable("category", category)
    put("tags", JSONArray(tags.map(String::trim).filter(String::isNotEmpty).distinct()))
}

private fun JSONObject.putNullable(key: String, value: String?) {
    put(key, value?.takeIf { it.isNotBlank() } ?: JSONObject.NULL)
}
