package com.sparkle.android.data

import android.content.ContentResolver
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.net.URLEncoder
import java.util.UUID

class SparkleApi private constructor(
    private val baseUrl: String,
) {
    fun loadSnapshot(): RemoteSnapshot {
        val categories = getArray("/categories").map(::parseCategory)
        val tags = getArray("/tags").map(::parseTag)
        val clips = getArray("/clips").map(::parseClip)
        val tasks = getArray("/tasks").map(::parseTask)
        val notes = getArray("/notes").map(::parseNote)
        val projects = getArray("/projects").map(::parseProject)
        return RemoteSnapshot(
            clips = clips,
            categories = categories,
            tags = tags,
            tasks = tasks,
            notes = notes,
            projects = projects,
        )
    }

    fun checkHealth(): Boolean {
        val response = request("GET", "/health")
        return response.optString("status") == "ok" && response.optString("app") == "Sparkle"
    }

    fun createClip(draft: ClipDraft): Clip =
        parseClip(request("POST", "/clips", draft.toCreateJson()))

    fun updateClip(clipId: Int, draft: ClipDraft): Clip =
        parseClip(request("PUT", "/clips/$clipId", draft.toUpdateJson()))

    fun toggleTask(taskId: Int): Task =
        parseTask(request("PATCH", "/tasks/$taskId/toggle"))

    fun updateNote(noteId: Int, title: String, body: String?): Note =
        parseNote(
            request(
                "PUT",
                "/notes/$noteId",
                JSONObject().apply {
                    put("title", title)
                    putNullable("body", body)
                },
            ),
        )

    fun updateProject(projectId: Int, name: String, description: String?): Project =
        parseProject(
            request(
                "PUT",
                "/projects/$projectId",
                JSONObject().apply {
                    put("name", name)
                    putNullable("description", description)
                },
            ),
        )

    fun uploadLocalClip(
        contentResolver: ContentResolver,
        selection: UploadSelection,
        draft: ClipDraft,
    ): Clip {
        val boundary = "----SparkleAndroid${UUID.randomUUID()}"
        val connection = (URL("$baseUrl/clips/local").openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = TIMEOUT_MS
            readTimeout = UPLOAD_TIMEOUT_MS
            useCaches = false
            doOutput = true
            setChunkedStreamingMode(0)
            setRequestProperty("Accept", "application/json")
            setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
        }

        return try {
            connection.outputStream.use { output ->
                writeTextPart(output, boundary, "title", draft.title.orEmpty())
                writeTextPart(output, boundary, "comment", draft.comment.orEmpty())
                writeTextPart(output, boundary, "category", draft.category.orEmpty())
                writeTextPart(output, boundary, "tags", draft.tags.joinToString(","))
                writeFilePart(output, boundary, contentResolver, selection)
                output.write("--$boundary--\r\n".toByteArray(Charsets.UTF_8))
            }
            parseClip(JSONObject(readResponse(connection)))
        } finally {
            connection.disconnect()
        }
    }

    /**
     * Converts an API thumbnail into an HTTPS URL the Android client can load.
     * External URLs go through the PC's existing thumbnail proxy so the app does
     * not need to make arbitrary non-HTTPS requests or deal with remote CORS.
     */
    fun thumbnailRequestUrl(raw: String?): String? {
        val candidate = raw?.trim().orEmpty()
        if (candidate.isBlank() || candidate.startsWith("data:")) return candidate.ifBlank { null }
        if (candidate.startsWith("/")) return baseUrl + candidate
        if (candidate.startsWith(baseUrl)) return candidate
        val encoded = URLEncoder.encode(candidate, Charsets.UTF_8.name())
        return "$baseUrl/thumbnail-proxy?url=$encoded"
    }

    private fun writeTextPart(output: OutputStream, boundary: String, name: String, value: String) {
        output.write("--$boundary\r\n".toByteArray(Charsets.UTF_8))
        output.write("Content-Disposition: form-data; name=\"$name\"\r\n\r\n".toByteArray(Charsets.UTF_8))
        output.write(value.toByteArray(Charsets.UTF_8))
        output.write("\r\n".toByteArray(Charsets.UTF_8))
    }

    private fun writeFilePart(
        output: OutputStream,
        boundary: String,
        contentResolver: ContentResolver,
        selection: UploadSelection,
    ) {
        val safeName = selection.displayName.ifBlank { "shared-file" }.replace('"', '_')
        output.write("--$boundary\r\n".toByteArray(Charsets.UTF_8))
        output.write(
            "Content-Disposition: form-data; name=\"file\"; filename=\"$safeName\"\r\n".toByteArray(Charsets.UTF_8),
        )
        output.write("Content-Type: ${selection.mimeType ?: "application/octet-stream"}\r\n\r\n".toByteArray(Charsets.UTF_8))
        val input = contentResolver.openInputStream(selection.uri)
            ?: throw IOException("共有ファイルを読み込めません")
        input.use { source ->
            val buffer = ByteArray(BUFFER_SIZE)
            while (true) {
                val count = source.read(buffer)
                if (count < 0) break
                output.write(buffer, 0, count)
            }
        }
        output.write("\r\n".toByteArray(Charsets.UTF_8))
    }

    private fun getArray(path: String): List<JSONObject> {
        val array = JSONArray(requestRaw("GET", path, null))
        return buildList(array.length()) {
            for (index in 0 until array.length()) add(array.getJSONObject(index))
        }
    }

    private fun request(method: String, path: String, body: JSONObject? = null): JSONObject =
        JSONObject(requestRaw(method, path, body))

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
            readResponse(connection)
        } catch (error: ApiException) {
            throw error
        } catch (error: IOException) {
            throw IOException("PCに接続できません", error)
        } finally {
            connection.disconnect()
        }
    }

    private fun readResponse(connection: HttpURLConnection): String {
        val status = connection.responseCode
        val stream = if (status in 200..299) connection.inputStream else connection.errorStream
        val body = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
        if (status !in 200..299) {
            throw ApiException(status, "PC API returned HTTP $status")
        }
        return body
    }

    private fun parseCategory(json: JSONObject): Category =
        Category(id = json.optInt("id"), name = json.optString("name"))

    private fun parseTag(json: JSONObject): Tag =
        Tag(id = json.optInt("id"), name = json.optString("name"))

    private fun parseClip(json: JSONObject): Clip = Clip(
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
        fileSize = nullableLong(json, "file_size"),
        isFolder = json.optBoolean("is_folder"),
        projectIds = json.optIntList("project_ids", "project_id"),
        tags = json.optJSONArray("tags").toObjectList(::parseTag),
    )

    private fun parseClipSummary(json: JSONObject): ClipSummary = ClipSummary(
        id = json.optInt("id"),
        title = nullableString(json, "title"),
        url = json.optString("url"),
        thumbnailUrl = nullableString(json, "thumbnail_url"),
        comment = nullableString(json, "comment"),
        tags = json.optJSONArray("tags").toObjectList(::parseTag),
    )

    private fun parseTask(json: JSONObject): Task = Task(
        id = json.optInt("id"),
        title = json.optString("title"),
        isDone = json.optBoolean("is_done"),
        clipId = nullableInt(json, "clip_id"),
        dueDate = nullableString(json, "due_date"),
        priority = nullableInt(json, "priority"),
        createdAt = json.optString("created_at"),
        projectId = nullableInt(json, "project_id"),
        clip = json.optJSONObject("clip")?.let(::parseClipSummary),
        notes = json.optJSONArray("notes").toObjectList { NoteSummary(it.optInt("id"), it.optString("title")) },
    )

    private fun parseNote(json: JSONObject): Note = Note(
        id = json.optInt("id"),
        title = json.optString("title"),
        body = nullableString(json, "body"),
        isDone = json.optBoolean("is_done"),
        createdAt = json.optString("created_at"),
        updatedAt = json.optString("updated_at"),
        clips = json.optJSONArray("clips").toObjectList(::parseClipSummary),
        task = json.optJSONObject("task")?.let {
            TaskSummary(it.optInt("id"), it.optString("title"), it.optBoolean("is_done"))
        },
        projectIds = json.optIntList("project_ids", "project_id"),
    )

    private fun parseProject(json: JSONObject): Project = Project(
        id = json.optInt("id"),
        name = json.optString("name"),
        description = nullableString(json, "description"),
        isDone = json.optBoolean("is_done"),
        createdAt = json.optString("created_at"),
    )

    companion object {
        private const val TIMEOUT_MS = 10_000
        private const val UPLOAD_TIMEOUT_MS = 120_000
        private const val BUFFER_SIZE = 16 * 1024

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
                if (uri.scheme != "https" || uri.host.isNullOrBlank() || path.contains("//")) null else candidate
            } catch (_: Exception) {
                null
            }
        }

        private fun nullableString(json: JSONObject, key: String): String? =
            if (!json.has(key) || json.isNull(key)) null else json.optString(key).takeIf { it.isNotBlank() }

        private fun nullableInt(json: JSONObject, key: String): Int? =
            if (!json.has(key) || json.isNull(key)) null else json.optInt(key)

        private fun nullableLong(json: JSONObject, key: String): Long? =
            if (!json.has(key) || json.isNull(key)) null else json.optLong(key)

        private fun JSONObject.optIntList(arrayKey: String, legacyKey: String): List<Int> {
            val array = optJSONArray(arrayKey)
            if (array != null) return (0 until array.length()).map { array.optInt(it) }.filter { it > 0 }
            return nullableInt(this, legacyKey)?.let(::listOf).orEmpty()
        }

        private fun <T> JSONArray?.toObjectList(parser: (JSONObject) -> T): List<T> {
            if (this == null) return emptyList()
            return buildList(length()) {
                for (index in 0 until length()) {
                    optJSONObject(index)?.let { add(parser(it)) }
                }
            }
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
