package com.sparkle.android.data

import android.content.ContentResolver
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.net.URLDecoder
import java.net.URLEncoder
import java.util.Locale
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

    fun loadAppSettings(): AppSettings = AppSettings(
        autoCreateNoteOnTask = getSetting("auto_create_note_on_task")?.toBooleanStrictOrNull() ?: false,
        taskAutoDelete = TaskAutoDeleteOption.fromValue(getSetting("task_auto_delete")).value,
        autoCreateNoteOnProject = getSetting("auto_create_note_on_project")?.toBooleanStrictOrNull() ?: false,
    )

    fun updateAppSetting(key: String, value: String): String =
        putSetting(key, value)

    private fun getSetting(key: String): String? = try {
        request("GET", "/settings/$key")
            .optString("value")
            .takeIf { it.isNotBlank() }
    } catch (error: ApiException) {
        if (error.statusCode == 404) null else throw error
    }

    private fun putSetting(key: String, value: String): String =
        request("PUT", "/settings/$key", JSONObject().put("value", value))
            .optString("value")

    fun createClip(draft: ClipDraft): Clip {
        val body = draft.toCreateJson()
        resolveThumbnailUrl(draft.url)?.let { body.put("thumbnail_url", it) }
        return parseClip(request("POST", "/clips", body))
    }

    fun updateClip(clipId: Int, draft: ClipDraft): Clip =
        parseClip(request("PUT", "/clips/$clipId", draft.toUpdateJson()))

    fun deleteClip(clipId: Int) {
        requestRaw("DELETE", "/clips/$clipId", null)
    }

    fun toggleFavorite(clipId: Int): Boolean =
        request("PATCH", "/clips/$clipId/favorite").optBoolean("is_favorite")

    fun createTask(
        title: String,
        dueDate: String?,
        priority: Int?,
        clipId: Int? = null,
        projectId: Int? = null,
    ): Task = parseTask(
        request(
            "POST",
            "/tasks",
            JSONObject().apply {
                put("title", title)
                putNullable("due_date", dueDate)
                putNullableInt("priority", priority)
                put("clip_id", clipId ?: JSONObject.NULL)
                put("project_id", projectId ?: JSONObject.NULL)
            },
        ),
    )

    fun updateTask(taskId: Int, title: String, dueDate: String?, priority: Int?): Task =
        parseTask(
            request(
                "PUT",
                "/tasks/$taskId",
                JSONObject().apply {
                    put("title", title)
                    put("due_date", dueDate ?: JSONObject.NULL)
                    put("priority", priority ?: JSONObject.NULL)
                },
            ),
        )

    fun updateTaskProject(taskId: Int, projectId: Int?): Task =
        parseTask(
            request(
                "PUT",
                "/tasks/$taskId",
                JSONObject().apply { put("project_id", projectId ?: JSONObject.NULL) },
            ),
        )

    fun toggleTask(taskId: Int): Task =
        parseTask(request("PATCH", "/tasks/$taskId/toggle"))

    fun deleteTask(taskId: Int) {
        requestRaw("DELETE", "/tasks/$taskId", null)
    }

    fun deleteCategory(categoryId: Int) {
        requestRaw("DELETE", "/categories/$categoryId", null)
    }

    fun createNote(
        title: String,
        body: String?,
        clipIds: List<Int> = emptyList(),
        taskIds: List<Int> = emptyList(),
        projectIds: List<Int> = emptyList(),
    ): Note = parseNote(
        request(
            "POST",
            "/notes",
            JSONObject().apply {
                put("title", title)
                putNullable("body", body)
                put("clip_ids", JSONArray(clipIds))
                put("task_ids", JSONArray(taskIds))
                put("project_ids", JSONArray(projectIds))
            },
        ),
    )

    fun updateNote(
        noteId: Int,
        title: String,
        body: String?,
        clipIds: List<Int>? = null,
        taskIds: List<Int>? = null,
        projectIds: List<Int>? = null,
    ): Note =
        parseNote(
            request(
                "PUT",
                "/notes/$noteId",
                JSONObject().apply {
                    put("title", title)
                    // The PC route treats JSON null as "field omitted". An
                    // empty string therefore represents an intentional clear
                    // from the Android editor.
                    put("body", body ?: "")
                    clipIds?.let { put("clip_ids", JSONArray(it)) }
                    taskIds?.let { put("task_ids", JSONArray(it)) }
                    projectIds?.let { put("project_ids", JSONArray(it)) }
                },
            ),
        )

    fun updateNoteTaskLinks(noteId: Int, taskIds: List<Int>): Note =
        parseNote(
            request(
                "PUT",
                "/notes/$noteId",
                JSONObject().apply { put("task_ids", JSONArray(taskIds)) },
            ),
        )

    fun deleteNote(noteId: Int) {
        requestRaw("DELETE", "/notes/$noteId", null)
    }

    fun createProject(name: String, description: String?): Project =
        parseProject(
            request(
                "POST",
                "/projects",
                JSONObject().apply {
                    put("name", name)
                    putNullable("description", description)
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
                    // Keep clearing the field possible through the existing
                    // PC API, whose update route ignores JSON null values.
                    put("description", description ?: "")
                },
            ),
        )

    fun toggleProject(projectId: Int): Project =
        parseProject(request("PATCH", "/projects/$projectId/toggle"))

    fun deleteProject(projectId: Int) {
        requestRaw("DELETE", "/projects/$projectId", null)
    }

    fun linkProjectClip(projectId: Int, clipId: Int): Clip =
        parseClip(request("POST", "/projects/$projectId/clips/$clipId"))

    fun unlinkProjectClip(projectId: Int, clipId: Int) {
        requestRaw("DELETE", "/projects/$projectId/clips/$clipId", null)
    }

    fun linkProjectNote(projectId: Int, noteId: Int): Note =
        parseNote(request("POST", "/projects/$projectId/notes/$noteId"))

    fun unlinkProjectNote(projectId: Int, noteId: Int) {
        requestRaw("DELETE", "/projects/$projectId/notes/$noteId", null)
    }

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

    /** Returns the PC-mediated stream URL for a local clip. */
    fun localFileUrl(clipId: Int): String = "$baseUrl/clips/$clipId/file"

    /** Loads the small text preview exposed by the existing PC API. */
    fun loadTextPreview(clipId: Int): String {
        val response = request("GET", "/clips/$clipId/text-preview")
        return response.optString("preview", response.optString("text"))
    }

    /**
     * Streams a local clip from the PC without exposing its filesystem path.
     * A preview limit keeps opening large files from filling the app cache.
     */
    fun streamLocalFile(
        clipId: Int,
        output: OutputStream,
        maxBytes: Long? = null,
    ) {
        val connection = (URL(localFileUrl(clipId)).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = TIMEOUT_MS
            readTimeout = FILE_TRANSFER_TIMEOUT_MS
            useCaches = false
            setRequestProperty("Accept", "*/*")
        }
        try {
            val status = connection.responseCode
            if (status !in 200..299) {
                throw ApiException(status, "PC API returned HTTP $status")
            }
            val contentLength = connection.contentLengthLong
            if (maxBytes != null && contentLength > maxBytes) {
                throw IOException("プレビュー対象のファイルが大きすぎます")
            }
            connection.inputStream.use { input ->
                val buffer = ByteArray(BUFFER_SIZE)
                var total = 0L
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    total += count
                    if (maxBytes != null && total > maxBytes) {
                        throw IOException("プレビュー対象のファイルが大きすぎます")
                    }
                    output.write(buffer, 0, count)
                }
            }
        } catch (error: ApiException) {
            throw error
        } catch (error: IOException) {
            throw error
        } catch (error: Exception) {
            throw IOException("ローカルファイルを取得できません", error)
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

    /** Resolves a stable remote image URL before a URL clip is created. */
    private fun resolveThumbnailUrl(rawUrl: String): String? {
        val candidate = rawUrl.trim()
        if (!candidate.startsWith("http://") && !candidate.startsWith("https://")) return null
        youtubeThumbnail(candidate)?.let { return it }

        val page = fetchHtml(candidate)
        if (page != null) {
            val (html, finalUrl) = page
            extractHtmlThumbnail(html, finalUrl)?.let { return it }
            extractFavicon(html, finalUrl)?.let { return it }
        }
        return runCatching { URI(candidate).resolve("/favicon.ico").toString() }.getOrNull()
    }

    private fun fetchHtml(rawUrl: String): Pair<String, String>? {
        val connection = (URL(rawUrl).openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = METADATA_TIMEOUT_MS
            readTimeout = METADATA_TIMEOUT_MS
            instanceFollowRedirects = true
            useCaches = true
            setRequestProperty("User-Agent", BROWSER_USER_AGENT)
            setRequestProperty("Accept", "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1")
            setRequestProperty("Accept-Encoding", "identity")
        }
        return try {
            if (connection.responseCode !in 200..299) return null
            val html = connection.inputStream.use(::readMetadataText)
            html to (connection.url?.toString() ?: rawUrl)
        } catch (_: Exception) {
            null
        } finally {
            connection.disconnect()
        }
    }

    private fun readMetadataText(input: InputStream): String {
        val output = ByteArrayOutputStream(MAX_METADATA_BYTES)
        val buffer = ByteArray(BUFFER_SIZE)
        var total = 0
        while (total < MAX_METADATA_BYTES) {
            val count = input.read(buffer)
            if (count < 0) break
            val writable = minOf(count, MAX_METADATA_BYTES - total)
            output.write(buffer, 0, writable)
            total += writable
            if (writable < count) break
        }
        return output.toString(Charsets.UTF_8.name())
    }

    private fun extractHtmlThumbnail(html: String, pageUrl: String): String? {
        val priorities = mapOf(
            "og:image" to 0,
            "og:image:url" to 1,
            "twitter:image" to 2,
            "twitter:image:src" to 3,
            "image" to 4,
        )
        var best: Pair<Int, String>? = null
        META_TAG_REGEX.findAll(html).forEach { match ->
            val attributes = parseHtmlAttributes(match.value)
            val kind = (attributes["property"] ?: attributes["name"] ?: attributes["itemprop"])
                ?.lowercase(Locale.ROOT)
                ?: return@forEach
            val content = attributes["content"] ?: return@forEach
            val priority = priorities[kind] ?: return@forEach
            val resolved = resolveResourceUrl(content, pageUrl) ?: return@forEach
            if (best == null || priority < best!!.first) best = priority to resolved
        }
        return best?.second
    }

    private fun extractFavicon(html: String, pageUrl: String): String? {
        LINK_TAG_REGEX.findAll(html).forEach { match ->
            val attributes = parseHtmlAttributes(match.value)
            val rel = attributes["rel"].orEmpty().lowercase(Locale.ROOT)
            if ("icon" in rel) {
                resolveResourceUrl(attributes["href"].orEmpty(), pageUrl)?.let { return it }
            }
        }
        return resolveResourceUrl("/favicon.ico", pageUrl)
    }

    private fun parseHtmlAttributes(tag: String): Map<String, String> =
        HTML_ATTRIBUTE_REGEX.findAll(tag).associate { match ->
            match.groupValues[1].lowercase(Locale.ROOT) to decodeHtmlEntities(match.groupValues[3])
        }

    private fun resolveResourceUrl(raw: String, pageUrl: String): String? {
        val candidate = decodeHtmlEntities(raw).trim()
        if (candidate.isBlank() || candidate.startsWith("data:")) return null
        return runCatching {
            val uri = URI(pageUrl).resolve(candidate)
            uri.takeIf { it.scheme == "http" || it.scheme == "https" }?.toString()
        }.getOrNull()
    }

    private fun youtubeThumbnail(rawUrl: String): String? {
        val uri = runCatching { URI(rawUrl) }.getOrNull() ?: return null
        val host = uri.host?.lowercase(Locale.ROOT) ?: return null
        val id = when {
            host == "youtu.be" -> uri.path.trim('/').substringBefore('/').takeIf { it.isNotBlank() }
            host == "youtube.com" || host.endsWith(".youtube.com") || host == "youtube-nocookie.com" || host.endsWith(".youtube-nocookie.com") -> {
                queryParameter(uri.rawQuery, "v")
                    ?: Regex("^/(?:shorts|embed|v)/([^/]+)").find(uri.path)?.groupValues?.getOrNull(1)
            }
            else -> null
        }
        val cleanId = id?.let { Regex("^[A-Za-z0-9_-]{11}").find(it)?.value } ?: return null
        return "https://img.youtube.com/vi/$cleanId/hqdefault.jpg"
    }

    private fun queryParameter(rawQuery: String?, name: String): String? =
        rawQuery.orEmpty().split('&').asSequence()
            .map { it.split('=', limit = 2) }
            .firstOrNull { it.firstOrNull() == name }
            ?.getOrNull(1)
            ?.let { runCatching { URLDecoder.decode(it, Charsets.UTF_8.name()) }.getOrNull() }

    private fun decodeHtmlEntities(value: String): String = value
        .replace("&amp;", "&", ignoreCase = true)
        .replace("&quot;", "\"", ignoreCase = true)
        .replace("&#39;", "'", ignoreCase = true)
        .replace("&#x27;", "'", ignoreCase = true)
        .replace("&lt;", "<", ignoreCase = true)
        .replace("&gt;", ">", ignoreCase = true)

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
        taskIds = json.optIntList("task_ids", "task_id"),
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
        private const val FILE_TRANSFER_TIMEOUT_MS = 180_000
        private const val BUFFER_SIZE = 16 * 1024
        private const val METADATA_TIMEOUT_MS = 8_000
        private const val MAX_METADATA_BYTES = 512 * 1024
        private const val BROWSER_USER_AGENT = "Mozilla/5.0 (Android) AppleWebKit/537.36 Sparkle/Android"
        private val META_TAG_REGEX = Regex("<meta\\b[^>]*>", setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL))
        private val LINK_TAG_REGEX = Regex("<link\\b[^>]*>", setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL))
        private val HTML_ATTRIBUTE_REGEX = Regex("""([A-Za-z_:][A-Za-z0-9:_.-]*)\s*=\s*(['"])(.*?)\2""", setOf(RegexOption.IGNORE_CASE, RegexOption.DOT_MATCHES_ALL))

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

private fun JSONObject.putNullableInt(key: String, value: Int?) {
    put(key, value ?: JSONObject.NULL)
}
