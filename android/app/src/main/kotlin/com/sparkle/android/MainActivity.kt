package com.sparkle.android

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.Category
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material.icons.filled.Label
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.OpenInNew
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.Wifi
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.NavigationDrawerItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.FloatingActionButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.sparkle.android.data.Category
import com.sparkle.android.data.Clip
import com.sparkle.android.data.ClipDraft
import com.sparkle.android.data.ConnectionState
import com.sparkle.android.data.LibraryFilter
import com.sparkle.android.data.Screen
import com.sparkle.android.ui.SparkleTheme
import com.sparkle.android.ui.SparkleViewModel
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            SparkleTheme {
                SparkleRoot()
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SparkleRoot(viewModel: SparkleViewModel = viewModel()) {
    val drawerState = androidx.compose.material3.rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    val closeDrawer = { scope.launch { drawerState.close() } }

    BackHandler(enabled = drawerState.isOpen) { closeDrawer() }
    BackHandler(enabled = drawerState.isClosed && viewModel.screen !is Screen.Library) {
        viewModel.goToLibrary()
    }

    ModalNavigationDrawer(
        drawerState = drawerState,
        drawerContent = {
            SparkleDrawer(
                viewModel = viewModel,
                onSelectAll = {
                    viewModel.chooseFilter(LibraryFilter.All)
                    closeDrawer()
                },
                onSelectCategory = { category ->
                    viewModel.chooseFilter(LibraryFilter.Category(category.name))
                    closeDrawer()
                },
                onSelectTag = { tag ->
                    viewModel.chooseFilter(LibraryFilter.Tag(tag))
                    closeDrawer()
                },
                onSettings = {
                    viewModel.openSettings()
                    closeDrawer()
                },
            )
        },
    ) {
        when (val currentScreen = viewModel.screen) {
            Screen.Library -> LibraryScreen(
                viewModel = viewModel,
                onOpenMenu = { scope.launch { drawerState.open() } },
                onOpenSettings = viewModel::openSettings,
            )
            is Screen.Detail -> DetailScreen(
                viewModel = viewModel,
                clipId = currentScreen.clipId,
            )
            is Screen.Editor -> EditorScreen(
                viewModel = viewModel,
                clipId = currentScreen.clipId,
            )
            Screen.Settings -> SettingsScreen(
                viewModel = viewModel,
                onOpenMenu = { scope.launch { drawerState.open() } },
            )
        }
    }
}

@Composable
private fun SparkleDrawer(
    viewModel: SparkleViewModel,
    onSelectAll: () -> Unit,
    onSelectCategory: (Category) -> Unit,
    onSelectTag: (String) -> Unit,
    onSettings: () -> Unit,
) {
    ModalDrawerSheet(
        modifier = Modifier
            .fillMaxHeight()
            .widthIn(min = 280.dp, max = 360.dp),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp, vertical = 20.dp)
                .navigationBarsPadding(),
        ) {
            Text("Sparkle", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            Text(
                "PCのクリップを安全に閲覧・編集",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(18.dp))
            ConnectionStatusCard(viewModel.connectionState)
            Spacer(Modifier.height(20.dp))

            NavigationDrawerItem(
                label = { Text("すべてのクリップ") },
                selected = viewModel.screen is Screen.Library && viewModel.filter == LibraryFilter.All,
                onClick = onSelectAll,
                icon = { Icon(Icons.Default.Link, contentDescription = null) },
                modifier = Modifier.padding(vertical = 2.dp),
            )
            Spacer(Modifier.height(18.dp))
            DrawerSectionTitle("カテゴリ")
            if (viewModel.categories.isEmpty()) {
                DrawerEmptyText("PCからカテゴリを読み込むと表示されます")
            } else {
                viewModel.categories.forEach { category ->
                    NavigationDrawerItem(
                        label = { Text(category.name, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                        selected = viewModel.filter == LibraryFilter.Category(category.name),
                        onClick = { onSelectCategory(category) },
                        icon = { Icon(Icons.Default.Category, contentDescription = null) },
                        modifier = Modifier.padding(vertical = 2.dp),
                    )
                }
            }
            Spacer(Modifier.height(18.dp))
            DrawerSectionTitle("タグ")
            if (viewModel.tags.isEmpty()) {
                DrawerEmptyText("PCからタグを読み込むと表示されます")
            } else {
                viewModel.tags.forEach { tag ->
                    NavigationDrawerItem(
                        label = { Text(tag.name, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                        selected = viewModel.filter == LibraryFilter.Tag(tag.name),
                        onClick = { onSelectTag(tag.name) },
                        icon = { Icon(Icons.Default.Label, contentDescription = null) },
                        modifier = Modifier.padding(vertical = 2.dp),
                    )
                }
            }
            Spacer(Modifier.height(18.dp))
            HorizontalDivider()
            Spacer(Modifier.height(12.dp))
            NavigationDrawerItem(
                label = { Text("PC接続設定") },
                selected = viewModel.screen is Screen.Settings,
                onClick = onSettings,
                icon = { Icon(Icons.Default.Settings, contentDescription = null) },
                modifier = Modifier.padding(vertical = 2.dp),
            )
        }
    }
}

@Composable
private fun DrawerSectionTitle(title: String) {
    Text(
        title,
        style = MaterialTheme.typography.labelLarge,
        color = MaterialTheme.colorScheme.primary,
        modifier = Modifier.padding(start = 16.dp, bottom = 4.dp),
    )
}

@Composable
private fun DrawerEmptyText(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun LibraryScreen(
    viewModel: SparkleViewModel,
    onOpenMenu: () -> Unit,
    onOpenSettings: () -> Unit,
) {
    val visibleClips = viewModel.visibleClips()
    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("クリップ")
                        if (viewModel.filter !is LibraryFilter.All) {
                            Text(
                                filterLabel(viewModel.filter),
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                },
                navigationIcon = {
                    IconButton(
                        onClick = onOpenMenu,
                        modifier = Modifier.semantics { contentDescription = "メニューを開く" },
                    ) {
                        Icon(Icons.Default.Menu, contentDescription = null)
                    }
                },
                actions = {
                    ConnectionStatusIcon(viewModel.connectionState)
                    IconButton(
                        onClick = viewModel::refresh,
                        enabled = !viewModel.isBusy,
                        modifier = Modifier.semantics { contentDescription = "PCから更新" },
                    ) {
                        Icon(Icons.Default.Refresh, contentDescription = null)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
            )
        },
        floatingActionButton = {
            FloatingActionButton(
                onClick = viewModel::beginCreate,
                modifier = Modifier.navigationBarsPadding(),
            ) {
                Icon(Icons.Default.Add, contentDescription = "クリップを作成")
            }
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            ConnectionBanner(
                state = viewModel.connectionState,
                onRetry = viewModel::refresh,
                onSettings = onOpenSettings,
            )
            viewModel.errorMessage?.let { message ->
                ErrorBanner(message = message, onDismiss = viewModel::clearError)
            }
            OutlinedTextField(
                value = viewModel.query,
                onValueChange = { viewModel.query = it },
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 8.dp),
                label = { Text("クリップを検索") },
                leadingIcon = { Icon(Icons.Default.Search, contentDescription = null) },
                singleLine = true,
            )

            when {
                viewModel.isBusy && viewModel.clips.isEmpty() -> LoadingState()
                viewModel.baseUrl.isBlank() -> UnconfiguredState(onSettings)
                viewModel.clips.isEmpty() && viewModel.connectionState is ConnectionState.Unavailable ->
                    UnavailableState(onSettings, viewModel::refresh)
                visibleClips.isEmpty() -> EmptySearchState()
                else -> LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 96.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    items(visibleClips, key = { it.id }) { clip ->
                        ClipCard(
                            clip = clip,
                            categoryName = viewModel.categoryName(clip.categoryId),
                            onClick = { viewModel.openDetail(clip.id) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun ClipCard(
    clip: Clip,
    categoryName: String?,
    onClick: () -> Unit,
) {
    Card(
        onClick = onClick,
        modifier = Modifier
            .fillMaxWidth()
            .semantics { contentDescription = "クリップ ${clip.displayTitle}" },
        shape = MaterialTheme.shapes.large,
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
            Row(verticalAlignment = Alignment.Top) {
                Text(
                    clip.displayTitle,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                if (clip.isFavorite) {
                    Icon(
                        Icons.Default.Star,
                        contentDescription = "お気に入り",
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(20.dp),
                    )
                }
            }
            Text(
                clip.url,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.primary,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            clip.comment?.trim()?.takeIf { it.isNotEmpty() }?.let { comment ->
                Text(
                    comment,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            val metadata = listOfNotNull(categoryName, clip.tags.joinToString(" · ") { it.name }.takeIf { it.isNotBlank() })
            if (metadata.isNotEmpty()) {
                Text(
                    metadata.joinToString("  •  "),
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DetailScreen(viewModel: SparkleViewModel, clipId: Int) {
    val clip = viewModel.clip(clipId)
    val context = LocalContext.current
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("クリップ詳細") },
                navigationIcon = {
                    IconButton(
                        onClick = viewModel::goToLibrary,
                        modifier = Modifier.semantics { contentDescription = "クリップ一覧へ戻る" },
                    ) {
                        Icon(Icons.Default.ArrowBack, contentDescription = null)
                    }
                },
                actions = {
                    if (clip != null) {
                        IconButton(
                            onClick = { viewModel.beginEdit(clip.id) },
                            modifier = Modifier.semantics { contentDescription = "クリップを編集" },
                        ) {
                            Icon(Icons.Default.Edit, contentDescription = null)
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
            )
        },
    ) { padding ->
        if (clip == null) {
            EmptyState(
                icon = Icons.Default.ErrorOutline,
                title = "クリップが見つかりません",
                message = "PC側で削除された可能性があります。",
                modifier = Modifier.padding(padding),
            )
            return@Scaffold
        }
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(18.dp),
        ) {
            viewModel.errorMessage?.let { message ->
                ErrorBanner(message = message, onDismiss = viewModel::clearError)
            }
            Text(
                clip.displayTitle,
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Bold,
            )
            Text(
                clip.url,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.primary,
            )
            OutlinedButton(
                onClick = { openClipUrl(context, clip.url) },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Icon(Icons.Default.OpenInNew, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text("リンクを開く")
            }
            HorizontalDivider()
            DetailField("カテゴリ", viewModel.categoryName(clip.categoryId) ?: "未設定")
            DetailField("タグ", clip.tags.joinToString("、") { it.name }.ifBlank { "未設定" })
            DetailField("保存日時", clip.createdAt.take(19).replace('T', ' '))
            Text("コメント", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(
                clip.comment?.takeIf { it.isNotBlank() } ?: "コメントはありません。",
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
private fun DetailField(label: String, value: String) {
    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
        Text(label, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
        Text(value, style = MaterialTheme.typography.bodyLarge)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun EditorScreen(viewModel: SparkleViewModel, clipId: Int?) {
    val existingClip = clipId?.let(viewModel::clip)
    var url by remember(clipId) { mutableStateOf(existingClip?.url.orEmpty()) }
    var title by remember(clipId) { mutableStateOf(existingClip?.title.orEmpty()) }
    var comment by remember(clipId) { mutableStateOf(existingClip?.comment.orEmpty()) }
    var category by remember(clipId) { mutableStateOf(viewModel.categoryName(existingClip?.categoryId).orEmpty()) }
    var tags by remember(clipId) { mutableStateOf(existingClip?.tags?.joinToString(", ") { it.name }.orEmpty()) }
    var validationError by remember(clipId) { mutableStateOf<String?>(null) }
    val urlFocusRequester = remember(clipId) { FocusRequester() }

    LaunchedEffect(validationError) {
        if (validationError != null && clipId == null) urlFocusRequester.requestFocus()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(if (clipId == null) "クリップを作成" else "クリップを編集") },
                navigationIcon = {
                    IconButton(
                        onClick = { if (clipId == null) viewModel.goToLibrary() else viewModel.openDetail(clipId) },
                        modifier = Modifier.semantics { contentDescription = "編集をキャンセル" },
                    ) {
                        Icon(Icons.Default.ArrowBack, contentDescription = null)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp, vertical = 8.dp)
                .navigationBarsPadding(),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Text(
                "変更はPC API経由で保存されます。Android側にはクリップDBを保存しません。",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            viewModel.errorMessage?.let { message ->
                ErrorBanner(message = message, onDismiss = viewModel::clearError)
            }
            validationError?.let { error ->
                ErrorBanner(message = error, onDismiss = { validationError = null })
            }
            OutlinedTextField(
                value = url,
                onValueChange = { url = it; validationError = null },
                modifier = Modifier
                    .fillMaxWidth()
                    .focusRequester(urlFocusRequester),
                label = { Text("URL") },
                leadingIcon = { Icon(Icons.Default.Link, contentDescription = null) },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                readOnly = existingClip != null,
                supportingText = if (existingClip != null) {
                    { Text("既存クリップのURLは変更できません。") }
                } else null,
                singleLine = true,
            )
            OutlinedTextField(
                value = title,
                onValueChange = { title = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("タイトル") },
                singleLine = false,
                maxLines = 3,
            )
            OutlinedTextField(
                value = comment,
                onValueChange = { comment = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("コメント") },
                minLines = 4,
            )
            OutlinedTextField(
                value = category,
                onValueChange = { category = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("カテゴリ") },
                supportingText = { Text("新しい名前を入力するとPC側で作成されます。") },
                singleLine = true,
            )
            OutlinedTextField(
                value = tags,
                onValueChange = { tags = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("タグ") },
                supportingText = { Text("カンマ区切りで入力") },
                singleLine = false,
                maxLines = 3,
            )
            Button(
                onClick = {
                    if (clipId == null && url.trim().isBlank()) {
                        validationError = "URLを入力してください。"
                    } else {
                        val draft = ClipDraft(
                            url = url.trim(),
                            title = title.trim().takeIf { it.isNotEmpty() },
                            comment = comment.trim().takeIf { it.isNotEmpty() },
                            category = category.trim().takeIf { it.isNotEmpty() },
                            tags = tags.split(',').map(String::trim).filter(String::isNotEmpty),
                        )
                        if (clipId == null) viewModel.createClip(draft) else viewModel.updateClip(clipId, draft)
                    }
                },
                enabled = !viewModel.isBusy,
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (viewModel.isBusy) {
                    CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                    Spacer(Modifier.width(8.dp))
                }
                Text(if (clipId == null) "PCに保存" else "変更を保存")
            }
            Spacer(Modifier.height(28.dp))
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SettingsScreen(viewModel: SparkleViewModel, onOpenMenu: () -> Unit) {
    var inputUrl by remember(viewModel.baseUrl) { mutableStateOf(viewModel.baseUrl) }
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("PC接続設定") },
                navigationIcon = {
                    IconButton(
                        onClick = onOpenMenu,
                        modifier = Modifier.semantics { contentDescription = "メニューを開く" },
                    ) {
                        Icon(Icons.Default.Menu, contentDescription = null)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp, vertical = 10.dp)
                .navigationBarsPadding(),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(
                "SparkleのPC APIに接続します。PCがクリップDBの唯一の所有者で、Android側にはDBの複製を作りません。",
                style = MaterialTheme.typography.bodyLarge,
            )
            Card(
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Row(Modifier.padding(16.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Icon(Icons.Default.Wifi, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                    Text(
                        "Tailscale Serveで公開したHTTPS URLを入力してください。例: https://sparkle.example.ts.net",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
            }
            viewModel.errorMessage?.let { message ->
                ErrorBanner(message = message, onDismiss = viewModel::clearError)
            }
            OutlinedTextField(
                value = inputUrl,
                onValueChange = { inputUrl = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("PC API URL") },
                placeholder = { Text("https://sparkle.example.ts.net") },
                leadingIcon = { Icon(Icons.Default.Link, contentDescription = null) },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                supportingText = { Text("認証情報は保存せず、URLだけを端末の設定に保存します。") },
                singleLine = true,
            )
            ConnectionStatusCard(viewModel.connectionState)
            ConnectionBanner(
                state = viewModel.connectionState,
                onRetry = viewModel::refresh,
                onSettings = null,
            )
            Button(
                onClick = { viewModel.saveConnection(inputUrl) },
                enabled = !viewModel.isBusy,
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (viewModel.isBusy) {
                    CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                    Spacer(Modifier.width(8.dp))
                }
                Text("保存して接続確認")
            }
            OutlinedButton(
                onClick = {
                    inputUrl = ""
                    viewModel.clearConnection()
                },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text("接続設定を消去")
            }
        }
    }
}

@Composable
private fun ConnectionStatusCard(state: ConnectionState) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Row(
            modifier = Modifier.padding(14.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            ConnectionStatusIcon(state)
            Column {
                Text("PC接続状態", style = MaterialTheme.typography.labelMedium)
                Text(statusLabel(state), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            }
        }
    }
}

@Composable
private fun ConnectionStatusIcon(state: ConnectionState) {
    val (icon, tint) = when (state) {
        ConnectionState.Unconfigured -> Icons.Default.CloudOff to MaterialTheme.colorScheme.onSurfaceVariant
        ConnectionState.Checking -> Icons.Default.Refresh to MaterialTheme.colorScheme.primary
        ConnectionState.Connected -> Icons.Default.CheckCircle to Color(0xFF2E7D32)
        is ConnectionState.Unavailable -> Icons.Default.CloudOff to MaterialTheme.colorScheme.error
    }
    Icon(icon, contentDescription = statusLabel(state), tint = tint, modifier = Modifier.size(22.dp))
}

@Composable
private fun ConnectionBanner(
    state: ConnectionState,
    onRetry: (() -> Unit)?,
    onSettings: (() -> Unit)?,
) {
    if (state is ConnectionState.Connected) return
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                ConnectionStatusIcon(state)
                Text(statusLabel(state), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            }
            when (state) {
                ConnectionState.Unconfigured -> Text("PC URLを設定すると、クリップを読み込めます。")
                ConnectionState.Checking -> Text("PC APIに接続しています…")
                is ConnectionState.Unavailable -> Text(state.reason)
                ConnectionState.Connected -> Unit
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                onSettings?.let { action -> TextButton(onClick = action) { Text("接続設定") } }
                onRetry?.let { action -> TextButton(onClick = action, enabled = state !is ConnectionState.Checking) { Text("再試行") } }
            }
        }
    }
}

@Composable
private fun ErrorBanner(message: String, onDismiss: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 4.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer),
    ) {
        Row(
            modifier = Modifier.padding(start = 14.dp, end = 4.dp, top = 10.dp, bottom = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Icon(Icons.Default.ErrorOutline, contentDescription = "エラー", tint = MaterialTheme.colorScheme.error)
            Text(message, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
            TextButton(onClick = onDismiss) { Text("閉じる") }
        }
    }
}

@Composable
private fun LoadingState() {
    EmptyState(
        icon = Icons.Default.Refresh,
        title = "PCから読み込み中",
        message = "クリップ、カテゴリ、タグを取得しています。",
        showProgress = true,
    )
}

@Composable
private fun UnconfiguredState(onSettings: () -> Unit) {
    EmptyState(
        icon = Icons.Default.CloudOff,
        title = "PCが未接続です",
        message = "左メニューのPC接続設定からTailscale URLを登録してください。",
        action = { Button(onClick = onSettings) { Text("接続設定を開く") } },
    )
}

@Composable
private fun UnavailableState(onSettings: () -> Unit, onRetry: () -> Unit) {
    EmptyState(
        icon = Icons.Default.CloudOff,
        title = "PCを利用できません",
        message = "PCが起動中か、Tailscale接続とURLが正しいか確認してください。",
        action = {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = onRetry) { Text("再試行") }
                Button(onClick = onSettings) { Text("設定") }
            }
        },
    )
}

@Composable
private fun EmptySearchState() {
    EmptyState(
        icon = Icons.Default.Search,
        title = "該当するクリップがありません",
        message = "検索語やメニューの絞り込みを変更してください。",
    )
}

@Composable
private fun EmptyState(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    title: String,
    message: String,
    modifier: Modifier = Modifier,
    showProgress: Boolean = false,
    action: (@Composable () -> Unit)? = null,
) {
    Box(
        modifier = modifier
            .fillMaxSize()
            .padding(28.dp),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (showProgress) {
                CircularProgressIndicator(modifier = Modifier.size(36.dp))
            } else {
                Icon(icon, contentDescription = null, modifier = Modifier.size(42.dp), tint = MaterialTheme.colorScheme.primary)
            }
            Text(title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
            Text(
                message,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.widthIn(max = 340.dp),
            )
            action?.invoke()
        }
    }
}

private fun statusLabel(state: ConnectionState): String = when (state) {
    ConnectionState.Unconfigured -> "未接続"
    ConnectionState.Checking -> "接続確認中"
    ConnectionState.Connected -> "PC接続中"
    is ConnectionState.Unavailable -> "PC未接続"
}

private fun filterLabel(filter: LibraryFilter): String = when (filter) {
    LibraryFilter.All -> "すべて"
    is LibraryFilter.Category -> "カテゴリ: ${filter.name}"
    is LibraryFilter.Tag -> "タグ: ${filter.name}"
}

private fun openClipUrl(context: Context, rawUrl: String) {
    val uri = Uri.parse(rawUrl)
    val intent = Intent(Intent.ACTION_VIEW, uri)
    context.startActivity(intent)
}
