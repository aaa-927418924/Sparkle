package com.sparkle.android

import android.content.Context
import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.OpenableColumns
import android.webkit.MimeTypeMap
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.staggeredgrid.LazyVerticalStaggeredGrid
import androidx.compose.foundation.lazy.staggeredgrid.StaggeredGridCells
import androidx.compose.foundation.lazy.staggeredgrid.items
import androidx.compose.foundation.lazy.staggeredgrid.rememberLazyStaggeredGridState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowBack
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.CalendarToday
import androidx.compose.material.icons.filled.Category
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material.icons.filled.Folder
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.Label
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.filled.OpenInNew
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Sort
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.Wifi
import androidx.compose.material3.Button
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.NavigationDrawerItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.FloatingActionButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.sparkle.android.data.Category
import com.sparkle.android.data.Clip
import com.sparkle.android.data.ClipCreationSource
import com.sparkle.android.data.ClipDraft
import com.sparkle.android.data.ClipSortMode
import com.sparkle.android.data.ConnectionState
import com.sparkle.android.data.Note
import com.sparkle.android.data.Project
import com.sparkle.android.data.Screen
import com.sparkle.android.data.StatusFilter
import com.sparkle.android.data.Task
import com.sparkle.android.data.TaskAutoDeleteOption
import com.sparkle.android.data.UploadSelection
import com.sparkle.android.ui.SparkleTheme
import com.sparkle.android.ui.SparkleThumbnail
import com.sparkle.android.ui.SparkleVideoPreview
import com.sparkle.android.ui.SparkleViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.util.Locale
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset

class MainActivity : ComponentActivity() {
    private var pendingShare by mutableStateOf<ClipCreationSource?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        pendingShare = parseShareIntent(this, intent)
        enableEdgeToEdge()
        setContent {
            SparkleTheme {
                SparkleRoot(
                    pendingShare = pendingShare,
                    onShareConsumed = { pendingShare = null },
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        pendingShare = parseShareIntent(this, intent)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SparkleRoot(
    pendingShare: ClipCreationSource?,
    onShareConsumed: () -> Unit,
    viewModel: SparkleViewModel = viewModel(),
) {
    val drawerState = androidx.compose.material3.rememberDrawerState(DrawerValue.Closed)
    val scope = androidx.compose.runtime.rememberCoroutineScope()
    val closeDrawer = { scope.launch { drawerState.close() } }
    val context = androidx.compose.ui.platform.LocalContext.current
    val filePicker = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri ?: return@rememberLauncherForActivityResult
        viewModel.beginCreate(ClipCreationSource(upload = selectionForUri(context, uri)))
    }
    val openFilePicker = { filePicker.launch(arrayOf("*/*")) }

    val lifecycleOwner = LocalLifecycleOwner.current
    LaunchedEffect(lifecycleOwner, viewModel) {
        lifecycleOwner.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            viewModel.onAppResumed()
            while (true) {
                delay(2_000L)
                viewModel.refresh(silent = true)
            }
        }
    }

    LaunchedEffect(pendingShare) {
        pendingShare?.let {
            viewModel.beginCreate(it)
            onShareConsumed()
        }
    }

    BackHandler(enabled = drawerState.isOpen) { closeDrawer() }
    BackHandler(enabled = drawerState.isClosed && viewModel.screen !is Screen.Home) {
        viewModel.goBack()
    }

    ModalNavigationDrawer(
        drawerState = drawerState,
        drawerContent = {
            SparkleDrawer(
                viewModel = viewModel,
                onHome = {
                    viewModel.goToHome()
                    closeDrawer()
                },
                onTasksNotes = {
                    viewModel.openTasksNotes()
                    closeDrawer()
                },
                onProjects = {
                    viewModel.openProjects()
                    closeDrawer()
                },
                onSettings = {
                    viewModel.openSettings()
                    closeDrawer()
                },
                onAppSettings = {
                    viewModel.openAppSettings()
                    closeDrawer()
                },
            )
        },
    ) {
        when (val currentScreen = viewModel.screen) {
            Screen.Home -> HomeScreen(
                viewModel = viewModel,
                onOpenMenu = { scope.launch { drawerState.open() } },
                onOpenSettings = viewModel::openSettings,
                onPickFile = openFilePicker,
            )
            Screen.TasksNotes -> TasksNotesScreen(
                viewModel = viewModel,
                onOpenMenu = { scope.launch { drawerState.open() } },
            )
            Screen.Projects -> ProjectsScreen(
                viewModel = viewModel,
                onOpenMenu = { scope.launch { drawerState.open() } },
            )
            is Screen.ProjectDetail -> ProjectDetailScreen(viewModel, currentScreen.projectId)
            is Screen.ProjectEditor -> ProjectEditorScreen(viewModel, currentScreen.projectId)
            is Screen.TaskEditor -> TaskEditorScreen(viewModel, currentScreen.taskId)
            is Screen.NoteEditor -> NoteEditorScreen(viewModel, currentScreen.noteId)
            is Screen.Detail -> DetailScreen(viewModel, currentScreen.clipId)
            is Screen.Editor -> EditorScreen(
                viewModel = viewModel,
                clipId = currentScreen.clipId,
                onOpenMenu = { scope.launch { drawerState.open() } },
                onOpenSettings = viewModel::openSettings,
                onPickFile = openFilePicker,
            )
            Screen.Settings -> SettingsScreen(
                viewModel = viewModel,
                onOpenMenu = { scope.launch { drawerState.open() } },
            )
            Screen.AppSettings -> AppSettingsScreen(
                viewModel = viewModel,
                onOpenMenu = { scope.launch { drawerState.open() } },
            )
        }
    }
}

@Composable
private fun SparkleDrawer(
    viewModel: SparkleViewModel,
    onHome: () -> Unit,
    onTasksNotes: () -> Unit,
    onProjects: () -> Unit,
    onSettings: () -> Unit,
    onAppSettings: () -> Unit,
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
            Spacer(Modifier.height(18.dp))
            ConnectionStatusCard(viewModel.connectionState)
            Spacer(Modifier.height(20.dp))
            NavigationDrawerItem(
                label = { Text("ホーム") },
                selected = viewModel.screen is Screen.Home || viewModel.screen is Screen.Detail || viewModel.screen is Screen.Editor,
                onClick = onHome,
                icon = { Icon(Icons.Default.Home, contentDescription = null) },
                modifier = Modifier.padding(vertical = 2.dp),
            )
            NavigationDrawerItem(
                label = { Text("タスク・メモ") },
                selected = viewModel.screen is Screen.TasksNotes,
                onClick = onTasksNotes,
                icon = { Icon(Icons.Default.CheckCircle, contentDescription = null) },
                modifier = Modifier.padding(vertical = 2.dp),
            )
            NavigationDrawerItem(
                label = { Text("プロジェクト") },
                selected = viewModel.screen is Screen.Projects || viewModel.screen is Screen.ProjectDetail || viewModel.screen is Screen.ProjectEditor,
                onClick = onProjects,
                icon = { Icon(Icons.Default.Folder, contentDescription = null) },
                modifier = Modifier.padding(vertical = 2.dp),
            )
            Spacer(Modifier.height(18.dp))
            HorizontalDivider()
            Spacer(Modifier.height(12.dp))
            NavigationDrawerItem(
                label = { Text("アプリ設定") },
                selected = viewModel.screen is Screen.AppSettings,
                onClick = onAppSettings,
                icon = { Icon(Icons.Default.Settings, contentDescription = null) },
                modifier = Modifier.padding(vertical = 2.dp),
            )
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

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
private fun HomeScreen(
    viewModel: SparkleViewModel,
    onOpenMenu: () -> Unit,
    onOpenSettings: () -> Unit,
    onPickFile: () -> Unit,
) {
    val visibleClips = viewModel.visibleClips()
    val gridState = rememberLazyStaggeredGridState()
    var clipActionTarget by remember { mutableStateOf<Clip?>(null) }
    var clipDeleteTarget by remember { mutableStateOf<Clip?>(null) }
    LaunchedEffect(viewModel.clipSortMode) {
        gridState.scrollToItem(0)
    }
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("ホーム") },
                navigationIcon = {
                    IconButton(onClick = onOpenMenu, modifier = Modifier.semantics { contentDescription = "メニューを開く" }) {
                        Icon(Icons.Default.Menu, contentDescription = null)
                    }
                },
                actions = {
                    ConnectionStatusIcon(viewModel.connectionState)
                    IconButton(onClick = viewModel::refresh, enabled = !viewModel.isBusy, modifier = Modifier.semantics { contentDescription = "PCから更新" }) {
                        Icon(Icons.Default.Refresh, contentDescription = null)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
            )
        },
        floatingActionButton = {
            FloatingActionButton(onClick = onPickFile, modifier = Modifier.navigationBarsPadding()) {
                Icon(Icons.Default.AttachFile, contentDescription = "スマホのファイルからクリップを作成")
            }
        },
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            ConnectionBanner(viewModel.connectionState, viewModel::refresh, onOpenSettings)
            viewModel.errorMessage?.let { ErrorBanner(it, viewModel::clearError) }
            CategoryFilterRow(viewModel)
            OutlinedTextField(
                value = viewModel.query,
                onValueChange = { viewModel.query = it },
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp).padding(top = 8.dp),
                placeholder = { Text("クリップを検索", modifier = Modifier.padding(start = 4.dp)) },
                leadingIcon = { Icon(Icons.Default.Search, contentDescription = null, modifier = Modifier.padding(start = 4.dp)) },
                shape = RoundedCornerShape(28.dp),
                singleLine = true,
            )
            HomeClipControls(viewModel)
            ActiveTagFilters(viewModel)
            when {
                viewModel.isBusy && viewModel.clips.isEmpty() -> LoadingState()
                viewModel.baseUrl.isBlank() -> UnconfiguredState(onOpenSettings)
                viewModel.clips.isEmpty() && viewModel.connectionState is ConnectionState.Unavailable ->
                    UnavailableState(onOpenSettings, viewModel::refresh)
                visibleClips.isEmpty() -> EmptySearchState()
                else -> BoxWithConstraints(Modifier.weight(1f).fillMaxWidth()) {
                    val columns = when {
                        maxWidth >= 900.dp -> 4
                        maxWidth >= 600.dp -> 3
                        else -> 2
                    }
                    LazyVerticalStaggeredGrid(
                        columns = StaggeredGridCells.Fixed(columns),
                        state = gridState,
                        modifier = Modifier.fillMaxSize(),
                        contentPadding = PaddingValues(start = 12.dp, end = 12.dp, bottom = 96.dp),
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                        verticalItemSpacing = 10.dp,
                    ) {
                        items(visibleClips, key = { it.id }) { clip ->
                            ClipCard(
                                clip = clip,
                                categoryName = viewModel.categoryName(clip.categoryId),
                                thumbnailUrl = viewModel.thumbnailUrl(clip.thumbnailUrl),
                                selectedTags = viewModel.selectedTags,
                                onToggleTag = viewModel::toggleTag,
                                onClick = { viewModel.openDetail(clip.id) },
                                onLongClick = { clipActionTarget = clip },
                            )
                        }
                    }
                }
            }
        }
    }
    clipActionTarget?.let { clip ->
        ClipActionDialog(
            clip = clip,
            onDismiss = { clipActionTarget = null },
            onToggleFavorite = {
                clipActionTarget = null
                viewModel.toggleFavorite(clip.id)
            },
            onDelete = {
                clipActionTarget = null
                clipDeleteTarget = clip
            },
        )
    }
    clipDeleteTarget?.let { clip ->
        DeleteConfirmationDialog(
            title = "クリップを削除",
            message = "「${clip.displayTitle}」を削除します。",
            confirmLabel = "クリップを削除",
            enabled = !viewModel.isBusy,
            onDismiss = { clipDeleteTarget = null },
            onConfirm = {
                clipDeleteTarget = null
                viewModel.deleteClip(clip.id)
            },
        )
    }
}

@Composable
private fun HomeClipControls(viewModel: SparkleViewModel) {
    var sortExpanded by remember { mutableStateOf(false) }
    val controlHeight = 40.dp
    val controlShape = RoundedCornerShape(20.dp)
    Row(
        modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Spacer(Modifier.width(16.dp))
        FilterChip(
            selected = viewModel.favoritesOnly,
            onClick = viewModel::toggleFavoritesOnly,
            modifier = Modifier.height(controlHeight),
            shape = controlShape,
            leadingIcon = { Icon(Icons.Default.Star, contentDescription = null) },
            label = { Text("お気に入り") },
        )
        Box {
            OutlinedButton(
                onClick = { sortExpanded = true },
                modifier = Modifier.height(controlHeight).width(296.dp),
                shape = controlShape,
            ) {
                Icon(Icons.Default.Sort, contentDescription = null)
                Spacer(Modifier.width(6.dp))
                Text(viewModel.clipSortMode.label)
            }
            DropdownMenu(expanded = sortExpanded, onDismissRequest = { sortExpanded = false }) {
                ClipSortMode.values().forEach { mode ->
                    DropdownMenuItem(
                        text = { Text(mode.label) },
                        onClick = {
                            sortExpanded = false
                            viewModel.selectClipSortMode(mode)
                        },
                    )
                }
            }
        }
        Spacer(Modifier.width(16.dp))
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun CategoryFilterRow(viewModel: SparkleViewModel) {
    var deleteTarget by remember { mutableStateOf<Category?>(null) }
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text("カテゴリ", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(start = 16.dp, top = 6.dp))
        LazyRow(contentPadding = PaddingValues(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            item {
                Box(
                    modifier = Modifier.height(48.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    FilterChip(
                        selected = viewModel.selectedCategory == null,
                        onClick = { viewModel.selectCategory(null) },
                        label = { Text("すべて") },
                    )
                }
            }
            items(viewModel.categories, key = { it.id }) { category ->
                CategoryFilterChip(
                    name = category.name,
                    selected = viewModel.selectedCategory == category.name,
                    enabled = !viewModel.isBusy,
                    onClick = { viewModel.selectCategory(category.name) },
                    onLongClick = { deleteTarget = category },
                )
            }
        }
    }
    deleteTarget?.let { category ->
        AlertDialog(
            onDismissRequest = { deleteTarget = null },
            title = { Text("カテゴリを削除") },
            text = { Text("「" + category.name + "」を削除します。既存クリップのカテゴリ設定も解除されます。") },
            confirmButton = {
                TextButton(
                    onClick = {
                        deleteTarget = null
                        viewModel.deleteCategory(category.id)
                    },
                    enabled = !viewModel.isBusy,
                ) {
                    Text("削除")
                }
            },
            dismissButton = {
                TextButton(onClick = { deleteTarget = null }) { Text("キャンセル") }
            },
        )
    }
}

@Composable
private fun CategoryFilterChip(
    name: String,
    selected: Boolean,
    enabled: Boolean,
    onClick: () -> Unit,
    onLongClick: () -> Unit,
) {
    Box(
        modifier = Modifier
            .height(48.dp)
            .combinedClickable(
                enabled = enabled,
                role = Role.Button,
                onClickLabel = "カテゴリで絞り込む",
                onLongClickLabel = "カテゴリを削除",
                onClick = onClick,
                onLongClick = onLongClick,
            ),
        contentAlignment = Alignment.Center,
    ) {
        Surface(
            modifier = Modifier.height(32.dp),
            shape = MaterialTheme.shapes.small,
            color = if (selected) MaterialTheme.colorScheme.secondaryContainer else MaterialTheme.colorScheme.surface,
            contentColor = if (selected) MaterialTheme.colorScheme.onSecondaryContainer else MaterialTheme.colorScheme.onSurface,
            border = if (selected) null else BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
        ) {
            Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text(
                    name,
                    modifier = Modifier.padding(horizontal = 16.dp),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@Composable
private fun ActiveTagFilters(viewModel: SparkleViewModel) {
    if (viewModel.selectedTags.isEmpty()) return
    Row(
        modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 2.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("タグ:", style = MaterialTheme.typography.labelMedium)
        viewModel.selectedTags.forEach { tag ->
            FilterChip(
                selected = true,
                onClick = { viewModel.toggleTag(tag) },
                label = { Text(tag) },
                trailingIcon = { Icon(Icons.Default.Clear, contentDescription = "タグ絞り込みを解除") },
            )
        }
        TextButton(onClick = viewModel::clearFilters) { Text("すべて解除") }
    }
}

@Composable
@OptIn(ExperimentalFoundationApi::class)
private fun ClipCard(
    clip: Clip,
    categoryName: String?,
    thumbnailUrl: String?,
    selectedTags: Set<String>,
    onToggleTag: (String) -> Unit,
    onClick: () -> Unit,
    onLongClick: () -> Unit,
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .combinedClickable(
                role = Role.Button,
                onClickLabel = "クリップを開く",
                onLongClickLabel = "クリップの操作",
                onClick = onClick,
                onLongClick = onLongClick,
            )
            .semantics { contentDescription = "クリップ ${clip.displayTitle}" },
        shape = MaterialTheme.shapes.large,
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
    ) {
        Column(modifier = Modifier.padding(10.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
            Box {
                SparkleThumbnail(
                    url = thumbnailUrl,
                    modifier = Modifier.fillMaxWidth(),
                    preserveImageAspectRatio = true,
                    contentDescription = "${clip.displayTitle}のサムネイル",
                )
                if (clip.isFavorite) {
                    Icon(
                        Icons.Default.Star,
                        contentDescription = "お気に入り",
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.padding(8.dp).size(20.dp).align(Alignment.TopEnd).background(MaterialTheme.colorScheme.surface.copy(alpha = 0.85f), CircleShape),
                    )
                }
            }
            Text(clip.displayTitle, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(clip.url, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary, maxLines = 2, overflow = TextOverflow.Ellipsis)
            categoryName?.let { Text(it, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis) }
            clip.comment?.trim()?.takeIf { it.isNotEmpty() }?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
            if (clip.tags.isNotEmpty()) {
                Row(modifier = Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                    clip.tags.forEach { tag ->
                        FilterChip(
                            selected = tag.name in selectedTags,
                            onClick = { onToggleTag(tag.name) },
                            label = { Text(tag.name, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun ClipActionDialog(
    clip: Clip,
    onDismiss: () -> Unit,
    onToggleFavorite: () -> Unit,
    onDelete: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("クリップの操作") },
        text = {
            Text(clip.displayTitle, maxLines = 3, overflow = TextOverflow.Ellipsis)
        },
        confirmButton = {
            Column(horizontalAlignment = Alignment.End) {
                TextButton(onClick = onToggleFavorite) {
                    Icon(Icons.Default.Star, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text(if (clip.isFavorite) "お気に入りから外す" else "お気に入りに追加")
                }
                TextButton(onClick = onDelete) {
                    Icon(Icons.Default.Delete, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text("クリップを削除")
                }
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("キャンセル") } },
    )
}

@Composable
private fun DeleteConfirmationDialog(
    title: String,
    message: String,
    confirmLabel: String,
    enabled: Boolean,
    onDismiss: () -> Unit,
    onConfirm: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { Text(message) },
        confirmButton = {
            TextButton(onClick = onConfirm, enabled = enabled) { Text(confirmLabel) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("キャンセル") } },
    )
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
private fun TasksNotesScreen(viewModel: SparkleViewModel, onOpenMenu: () -> Unit) {
    var selectedTab by remember { mutableStateOf(viewModel.tasksNotesTab) }
    var taskDeleteTarget by remember { mutableStateOf<Task?>(null) }
    var noteDeleteTarget by remember { mutableStateOf<Note?>(null) }
    val visibleTasks = viewModel.visibleTasks()
    val visibleNotes = viewModel.visibleNotes()
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("タスク・メモ") },
                navigationIcon = {
                    IconButton(onClick = onOpenMenu, modifier = Modifier.semantics { contentDescription = "メニューを開く" }) {
                        Icon(Icons.Default.Menu, contentDescription = null)
                    }
                },
                actions = {
                    ConnectionStatusIcon(viewModel.connectionState)
                    IconButton(
                        onClick = { if (selectedTab == 0) viewModel.openTaskEditor(null) else viewModel.openNoteEditor(null) },
                        modifier = Modifier.semantics { contentDescription = if (selectedTab == 0) "タスクを追加" else "メモを追加" },
                    ) {
                        Icon(Icons.Default.Add, contentDescription = null)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
            )
        },
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            ConnectionBanner(viewModel.connectionState, viewModel::refresh, null)
            TabRow(selectedTabIndex = selectedTab) {
                Tab(selected = selectedTab == 0, onClick = { selectedTab = 0 }, text = { Text("タスク") }, icon = { Icon(Icons.Default.CheckCircle, contentDescription = null) })
                Tab(selected = selectedTab == 1, onClick = { selectedTab = 1 }, text = { Text("メモ") }, icon = { Icon(Icons.Default.Description, contentDescription = null) })
            }
            StatusFilterRow(
                selected = if (selectedTab == 0) viewModel.taskFilter else viewModel.noteFilter,
                onSelect = { if (selectedTab == 0) viewModel.selectTaskFilter(it) else viewModel.selectNoteFilter(it) },
            )
            if (viewModel.isBusy && viewModel.tasks.isEmpty() && viewModel.notes.isEmpty()) {
                LoadingState()
            } else if (selectedTab == 0) {
                if (visibleTasks.isEmpty()) {
                    EmptyState(Icons.Default.CheckCircle, "タスクはありません", "PC側で作成したタスクがここに表示されます。")
                } else {
                    LazyColumn(contentPadding = PaddingValues(16.dp, 16.dp, 16.dp, 28.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        items(visibleTasks, key = { it.id }) { task ->
                            TaskCard(
                                task = task,
                                onToggle = { viewModel.toggleTask(task.id) },
                                onClick = { viewModel.openTaskEditor(task.id) },
                                onLongClick = { taskDeleteTarget = task },
                                highlighted = viewModel.isHighestPriorityTask(task),
                            )
                        }
                    }
                }
            } else if (visibleNotes.isEmpty()) {
                EmptyState(Icons.Default.Description, "メモはありません", "PC側で作成したメモがここに表示されます。")
            } else {
                LazyColumn(contentPadding = PaddingValues(16.dp, 16.dp, 16.dp, 28.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    items(visibleNotes, key = { it.id }) { note ->
                        NoteCard(
                            note = note,
                            onClick = { viewModel.openNoteEditor(note.id) },
                            onLongClick = { noteDeleteTarget = note },
                        )
                    }
                }
            }
        }
    }
    taskDeleteTarget?.let { task ->
        DeleteConfirmationDialog(
            title = "タスクを削除",
            message = "「${task.title}」を削除します。",
            confirmLabel = "タスクを削除",
            enabled = !viewModel.isBusy,
            onDismiss = { taskDeleteTarget = null },
            onConfirm = {
                taskDeleteTarget = null
                viewModel.deleteTask(task.id)
            },
        )
    }
    noteDeleteTarget?.let { note ->
        DeleteConfirmationDialog(
            title = "メモを削除",
            message = "「${note.title}」を削除します。",
            confirmLabel = "メモを削除",
            enabled = !viewModel.isBusy,
            onDismiss = { noteDeleteTarget = null },
            onConfirm = {
                noteDeleteTarget = null
                viewModel.deleteNote(note.id)
            },
        )
    }
}

@Composable
private fun StatusFilterRow(selected: StatusFilter, onSelect: (StatusFilter) -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        StatusFilter.values().forEach { filter ->
            FilterChip(selected = selected == filter, onClick = { onSelect(filter) }, label = { Text(filter.label) })
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun TaskCard(
    task: Task,
    onToggle: () -> Unit,
    onClick: () -> Unit = {},
    onLongClick: () -> Unit = {},
    highlighted: Boolean = false,
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .combinedClickable(
                role = Role.Button,
                onClickLabel = "タスクを編集",
                onLongClickLabel = "タスクを削除",
                onClick = onClick,
                onLongClick = onLongClick,
            ),
        border = if (highlighted) BorderStroke(2.dp, MaterialTheme.colorScheme.primary) else null,
        colors = if (highlighted) {
            CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)
        } else {
            CardDefaults.cardColors()
        },
    ) {
        Row(modifier = Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Checkbox(checked = task.isDone, onCheckedChange = { onToggle() })
            Column(verticalArrangement = Arrangement.spacedBy(5.dp), modifier = Modifier.weight(1f)) {
                Text(task.title, style = MaterialTheme.typography.titleMedium, textDecoration = if (task.isDone) TextDecoration.LineThrough else TextDecoration.None)
                task.clip?.let { Text("関連クリップ: ${it.displayTitle}", style = MaterialTheme.typography.bodySmall) }
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    task.dueDate?.takeIf { it.isNotBlank() }?.let { Text("期限 ${it.take(10)}", style = MaterialTheme.typography.labelMedium) }
                    task.priority?.let { Text("優先度 $it", style = MaterialTheme.typography.labelMedium) }
                }
                if (task.notes.isNotEmpty()) {
                    Text("関連メモ ${task.notes.size}件", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                }
            }
        }
    }
}

@Composable
private fun NoteCard(note: Note, onClick: () -> Unit, onLongClick: () -> Unit = {}) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .combinedClickable(
                role = Role.Button,
                onClickLabel = "メモを編集",
                onLongClickLabel = "メモを削除",
                onClick = onClick,
                onLongClick = onLongClick,
            ),
    ) {
        Column(modifier = Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
            Text(note.title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, textDecoration = if (note.isDone) TextDecoration.LineThrough else TextDecoration.None)
            note.body?.takeIf { it.isNotBlank() }?.let { Text(it, style = MaterialTheme.typography.bodyMedium, maxLines = 5, overflow = TextOverflow.Ellipsis) }
            if (note.clips.isNotEmpty()) {
                Text("関連クリップ: " + note.clips.joinToString("、") { it.displayTitle }, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
            note.task?.let { Text("関連タスク: ${it.title}", style = MaterialTheme.typography.bodySmall) }
            Text("更新 ${formatDate(note.updatedAt)}", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
private fun ProjectsScreen(viewModel: SparkleViewModel, onOpenMenu: () -> Unit) {
    var deleteTarget by remember { mutableStateOf<Project?>(null) }
    val visibleProjects = viewModel.visibleProjects()
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("プロジェクト") },
                navigationIcon = {
                    IconButton(onClick = onOpenMenu, modifier = Modifier.semantics { contentDescription = "メニューを開く" }) {
                        Icon(Icons.Default.Menu, contentDescription = null)
                    }
                },
                actions = {
                    ConnectionStatusIcon(viewModel.connectionState)
                    IconButton(onClick = { viewModel.openProjectEditor(null) }, modifier = Modifier.semantics { contentDescription = "新規プロジェクト" }) {
                        Icon(Icons.Default.Add, contentDescription = null)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
            )
        },
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {
            StatusFilterRow(selected = viewModel.projectFilter, onSelect = viewModel::selectProjectFilter)
            if (visibleProjects.isEmpty()) {
                EmptyState(Icons.Default.Folder, "プロジェクトはありません", "PC側で作成したプロジェクトがここに表示されます。", Modifier.weight(1f))
            } else {
                LazyColumn(modifier = Modifier.weight(1f).fillMaxWidth(), contentPadding = PaddingValues(16.dp, 8.dp, 16.dp, 28.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    items(visibleProjects, key = { it.id }) { project ->
                        ProjectCard(
                            project = project,
                            clipCount = viewModel.projectClips(project.id).size,
                            taskCount = viewModel.projectTasks(project.id).size,
                            noteCount = viewModel.projectNotes(project.id).size,
                            clipThumbnails = viewModel.projectClips(project.id)
                                .mapNotNull { viewModel.thumbnailUrl(it.thumbnailUrl) }
                                .take(3),
                            onClick = { viewModel.openProject(project.id) },
                            onEdit = { viewModel.openProjectEditor(project.id) },
                            onToggle = { viewModel.toggleProject(project.id) },
                            onLongClick = { deleteTarget = project },
                        )
                    }
                }
            }
        }
    }
    deleteTarget?.let { project ->
        DeleteConfirmationDialog(
            title = "プロジェクトを削除",
            message = "「${project.name}」を削除します。関連項目のリンクは解除されます。",
            confirmLabel = "プロジェクトを削除",
            enabled = !viewModel.isBusy,
            onDismiss = { deleteTarget = null },
            onConfirm = {
                deleteTarget = null
                viewModel.deleteProject(project.id)
            },
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ProjectCard(
    project: Project,
    clipCount: Int,
    taskCount: Int,
    noteCount: Int,
    clipThumbnails: List<String>,
    onClick: () -> Unit,
    onEdit: () -> Unit,
    onToggle: () -> Unit,
    onLongClick: () -> Unit,
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .combinedClickable(
                role = Role.Button,
                onClickLabel = "プロジェクトを開く",
                onLongClickLabel = "プロジェクトを削除",
                onClick = onClick,
                onLongClick = onLongClick,
            ),
    ) {
        Column(modifier = Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(7.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Checkbox(checked = project.isDone, onCheckedChange = { onToggle() })
                ProjectPreviewIcon(clipThumbnails)
                Text(project.name, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                if (project.isDone) Text("完了", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                IconButton(onClick = onEdit, modifier = Modifier.semantics { contentDescription = "${project.name}を編集" }) {
                    Icon(Icons.Default.Edit, contentDescription = null)
                }
            }
            project.description?.takeIf { it.isNotBlank() }?.let { Text(it, style = MaterialTheme.typography.bodyMedium, maxLines = 3, overflow = TextOverflow.Ellipsis) }
            Text("クリップ $clipCount ・ タスク $taskCount ・ メモ $noteCount", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun ProjectPreviewIcon(clipThumbnails: List<String>) {
    Box(modifier = Modifier.size(width = 56.dp, height = 46.dp)) {
        Icon(
            Icons.Default.Folder,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(34.dp).align(Alignment.BottomStart),
        )
        clipThumbnails.forEachIndexed { index, thumbnail ->
            SparkleThumbnail(
                url = thumbnail,
                modifier = Modifier
                    .size(width = 30.dp, height = 21.dp)
                    .align(Alignment.TopStart)
                    .offset(x = (16 + index * 8).dp, y = (index * 3).dp),
                contentDescription = null,
            )
        }
    }
}

private enum class ProjectLinkMode(val dialogTitle: String) {
    Clips("クリップを紐づける"),
    Tasks("タスクを紐づける"),
    Notes("メモを紐づける"),
}

@Composable
private fun ProjectLinkButton(
    label: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    onClick: () -> Unit,
) {
    OutlinedButton(onClick = onClick, modifier = Modifier.fillMaxWidth()) {
        Icon(icon, contentDescription = null)
        Spacer(Modifier.width(8.dp))
        Text(label)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ProjectDetailScreen(viewModel: SparkleViewModel, projectId: Int) {
    val project = viewModel.project(projectId)
    var linkMode by remember(projectId) { mutableStateOf<ProjectLinkMode?>(null) }
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(project?.name ?: "プロジェクト") },
                navigationIcon = {
                    IconButton(onClick = viewModel::openProjects, modifier = Modifier.semantics { contentDescription = "プロジェクト一覧へ戻る" }) {
                        Icon(Icons.Default.ArrowBack, contentDescription = null)
                    }
                },
                actions = {
                    if (project != null) {
                        IconButton(onClick = { viewModel.openProjectEditor(project.id) }, modifier = Modifier.semantics { contentDescription = "プロジェクトを編集" }) {
                            Icon(Icons.Default.Edit, contentDescription = null)
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
            )
        },
    ) { padding ->
        if (project == null) {
            EmptyState(Icons.Default.ErrorOutline, "プロジェクトが見つかりません", "PC側で削除された可能性があります。", Modifier.padding(padding))
            return@Scaffold
        }
        LazyColumn(modifier = Modifier.fillMaxSize().padding(padding), contentPadding = PaddingValues(16.dp, 8.dp, 16.dp, 28.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            project.description?.takeIf { it.isNotBlank() }?.let { item { Text(it, style = MaterialTheme.typography.bodyLarge) } }
            item {
                Column(
                    modifier = Modifier.fillMaxWidth(),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    ProjectLinkButton("クリップを紐づける", Icons.Default.Link) { linkMode = ProjectLinkMode.Clips }
                    ProjectLinkButton("タスクを紐づける", Icons.Default.CheckCircle) { linkMode = ProjectLinkMode.Tasks }
                    ProjectLinkButton("メモを紐づける", Icons.Default.Description) { linkMode = ProjectLinkMode.Notes }
                }
            }
            item { SectionHeading("クリップ") }
            val projectClips = viewModel.projectClips(projectId)
            if (projectClips.isEmpty()) item { Text("関連するクリップはありません。", color = MaterialTheme.colorScheme.onSurfaceVariant) }
            else items(projectClips, key = { "clip-${it.id}" }) { clip ->
                ProjectClipRow(clip, viewModel.thumbnailUrl(clip.thumbnailUrl), onClick = { viewModel.openDetail(clip.id) })
            }
            item { SectionHeading("タスク") }
            val projectTasks = viewModel.projectTasks(projectId)
            if (projectTasks.isEmpty()) item { Text("関連するタスクはありません。", color = MaterialTheme.colorScheme.onSurfaceVariant) }
            else items(projectTasks, key = { "task-${it.id}" }) { task ->
                TaskCard(
                    task = task,
                    onToggle = { viewModel.toggleTask(task.id) },
                    onClick = { viewModel.openTaskEditor(task.id) },
                    highlighted = viewModel.isHighestPriorityTask(task),
                )
            }
            item { SectionHeading("メモ") }
            val projectNotes = viewModel.projectNotes(projectId)
            if (projectNotes.isEmpty()) item { Text("関連するメモはありません。", color = MaterialTheme.colorScheme.onSurfaceVariant) }
            else items(projectNotes, key = { "note-${it.id}" }) { note -> NoteCard(note, onClick = { viewModel.openNoteEditor(note.id) }) }
        }
    }
    linkMode?.let { mode ->
        if (project == null) return@let
        ProjectLinksDialog(
            viewModel = viewModel,
            projectId = project.id,
            mode = mode,
            onDismiss = { linkMode = null },
            onSave = { clipIds, taskIds, noteIds ->
                linkMode = null
                viewModel.saveProjectLinks(project.id, clipIds, taskIds, noteIds)
            },
        )
    }
}

@Composable
private fun ProjectLinksDialog(
    viewModel: SparkleViewModel,
    projectId: Int,
    mode: ProjectLinkMode,
    onDismiss: () -> Unit,
    onSave: (Set<Int>, Set<Int>, Set<Int>) -> Unit,
) {
    var clipIds by remember(projectId) { mutableStateOf(viewModel.projectClips(projectId).map { it.id }.toSet()) }
    var taskIds by remember(projectId) { mutableStateOf(viewModel.projectTasks(projectId).map { it.id }.toSet()) }
    var noteIds by remember(projectId) { mutableStateOf(viewModel.projectNotes(projectId).map { it.id }.toSet()) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(mode.dialogTitle) },
        text = {
            Column(
                modifier = Modifier.heightIn(max = 520.dp).verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                when (mode) {
                    ProjectLinkMode.Clips -> {
                        LinkSectionTitle("クリップ")
                        if (viewModel.clips.isEmpty()) {
                            Text("クリップはありません。", color = MaterialTheme.colorScheme.onSurfaceVariant)
                        } else {
                            viewModel.clips.forEach { clip ->
                                LinkCheckboxRow(
                                    label = clip.displayTitle,
                                    checked = clip.id in clipIds,
                                    onCheckedChange = { checked -> clipIds = if (checked) clipIds + clip.id else clipIds - clip.id },
                                )
                            }
                        }
                    }
                    ProjectLinkMode.Tasks -> {
                        LinkSectionTitle("タスク")
                        if (viewModel.tasks.isEmpty()) {
                            Text("タスクはありません。", color = MaterialTheme.colorScheme.onSurfaceVariant)
                        } else {
                            viewModel.tasks.forEach { task ->
                                LinkCheckboxRow(
                                    label = task.title,
                                    checked = task.id in taskIds,
                                    onCheckedChange = { checked -> taskIds = if (checked) taskIds + task.id else taskIds - task.id },
                                )
                            }
                        }
                    }
                    ProjectLinkMode.Notes -> {
                        LinkSectionTitle("メモ")
                        if (viewModel.notes.isEmpty()) {
                            Text("メモはありません。", color = MaterialTheme.colorScheme.onSurfaceVariant)
                        } else {
                            viewModel.notes.forEach { note ->
                                LinkCheckboxRow(
                                    label = note.title,
                                    checked = note.id in noteIds,
                                    onCheckedChange = { checked -> noteIds = if (checked) noteIds + note.id else noteIds - note.id },
                                )
                            }
                        }
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { onSave(clipIds, taskIds, noteIds) }, enabled = !viewModel.isBusy) { Text("保存") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("キャンセル") } },
    )
}

@Composable
private fun LinkSectionTitle(title: String) {
    Text(title, style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(top = 10.dp))
}

@Composable
private fun LinkCheckboxRow(label: String, checked: Boolean, onCheckedChange: (Boolean) -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Checkbox(checked = checked, onCheckedChange = onCheckedChange)
        Text(label, modifier = Modifier.weight(1f), maxLines = 2, overflow = TextOverflow.Ellipsis)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ProjectEditorScreen(viewModel: SparkleViewModel, projectId: Int?) {
    val project = projectId?.let(viewModel::project)
    var name by remember(projectId) { mutableStateOf(project?.name.orEmpty()) }
    var description by remember(projectId) { mutableStateOf(project?.description.orEmpty()) }
    var validationError by remember(projectId) { mutableStateOf<String?>(null) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(if (projectId == null) "新規プロジェクト" else "プロジェクトを編集") },
                navigationIcon = {
                    IconButton(
                        onClick = { projectId?.let(viewModel::openProject) ?: viewModel.openProjects() },
                        modifier = Modifier.semantics { contentDescription = "プロジェクト一覧へ戻る" },
                    ) {
                        Icon(Icons.Default.ArrowBack, contentDescription = null)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
            )
        },
    ) { padding ->
        if (projectId != null && project == null) {
            EmptyState(Icons.Default.ErrorOutline, "プロジェクトが見つかりません", "PC側で削除された可能性があります。", Modifier.padding(padding))
            return@Scaffold
        }
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp, vertical = 10.dp)
                .navigationBarsPadding(),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Text("プロジェクトの変更はPC API経由で保存されます。", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            viewModel.errorMessage?.let { ErrorBanner(it, viewModel::clearError) }
            validationError?.let { ErrorBanner(it) { validationError = null } }
            OutlinedTextField(
                value = name,
                onValueChange = { name = it; validationError = null },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("プロジェクト名") },
                singleLine = true,
            )
            OutlinedTextField(
                value = description,
                onValueChange = { description = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("説明") },
                minLines = 5,
            )
            Button(
                onClick = {
                    if (name.trim().isBlank()) {
                        validationError = "プロジェクト名を入力してください。"
                    } else {
                        viewModel.saveProject(projectId, name, description)
                    }
                },
                enabled = !viewModel.isBusy,
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (viewModel.isBusy) {
                    CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                    Spacer(Modifier.width(8.dp))
                }
                Text(if (projectId == null) "プロジェクトを作成" else "変更を保存")
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun TaskEditorScreen(viewModel: SparkleViewModel, taskId: Int?) {
    val task = taskId?.let(viewModel::task)
    var title by remember(taskId) { mutableStateOf(task?.title.orEmpty()) }
    var dueDate by remember(taskId) { mutableStateOf(task?.dueDate?.take(10).orEmpty()) }
    var priority by remember(taskId) { mutableStateOf(task?.priority?.toString().orEmpty()) }
    var linkedNoteIds by remember(taskId) { mutableStateOf(task?.notes?.map { it.id }?.toSet().orEmpty()) }
    var validationError by remember(taskId) { mutableStateOf<String?>(null) }
    var showDatePicker by remember(taskId) { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(if (taskId == null) "タスクを追加" else "タスクを編集") },
                navigationIcon = {
                    IconButton(onClick = { viewModel.openTasksNotes(tab = 0) }, modifier = Modifier.semantics { contentDescription = "タスク一覧へ戻る" }) {
                        Icon(Icons.Default.ArrowBack, contentDescription = null)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
            )
        },
    ) { padding ->
        if (taskId != null && task == null) {
            EmptyState(Icons.Default.ErrorOutline, "タスクが見つかりません", "PC側で削除された可能性があります。", Modifier.padding(padding))
            return@Scaffold
        }
        Column(
            modifier = Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 10.dp).navigationBarsPadding(),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Text("タスクの変更はPC API経由で保存されます。", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            viewModel.errorMessage?.let { ErrorBanner(it, viewModel::clearError) }
            validationError?.let { ErrorBanner(it) { validationError = null } }
            OutlinedTextField(value = title, onValueChange = { title = it; validationError = null }, modifier = Modifier.fillMaxWidth(), label = { Text("タスク名") }, singleLine = true)
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OutlinedButton(
                    onClick = { showDatePicker = true },
                    enabled = !viewModel.isBusy,
                    modifier = Modifier.weight(1f),
                ) {
                    Icon(Icons.Default.CalendarToday, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text(if (dueDate.isBlank()) "期限を設定" else "期限: $dueDate")
                }
                if (dueDate.isNotBlank()) {
                    TextButton(onClick = { dueDate = "" }, enabled = !viewModel.isBusy) {
                        Text("解除")
                    }
                }
            }
            OutlinedTextField(value = priority, onValueChange = { priority = it.filter(Char::isDigit).take(1) }, modifier = Modifier.fillMaxWidth(), label = { Text("優先度") }, supportingText = { Text("1〜5、空欄は未設定") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), singleLine = true)
            Text("関連メモ", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            if (viewModel.notes.isEmpty()) {
                Text("関連付けられるメモはありません。", color = MaterialTheme.colorScheme.onSurfaceVariant)
            } else {
                Column(modifier = Modifier.heightIn(max = 280.dp).verticalScroll(rememberScrollState())) {
                    viewModel.notes.forEach { note ->
                        LinkCheckboxRow(
                            label = note.title,
                            checked = note.id in linkedNoteIds,
                            onCheckedChange = { checked -> linkedNoteIds = if (checked) linkedNoteIds + note.id else linkedNoteIds - note.id },
                        )
                    }
                }
            }
            Button(
                onClick = {
                    if (title.trim().isBlank()) {
                        validationError = "タスク名を入力してください。"
                    } else {
                        val priorityValue = priority.trim().takeIf { it.isNotEmpty() }?.toIntOrNull()
                        if (priorityValue != null && priorityValue !in 1..5) {
                            validationError = "優先度は1〜5で入力してください。"
                        } else {
                            viewModel.saveTask(taskId, title, dueDate, priorityValue, linkedNoteIds)
                        }
                    }
                },
                enabled = !viewModel.isBusy,
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (viewModel.isBusy) {
                    CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                    Spacer(Modifier.width(8.dp))
                }
                Text(if (taskId == null) "タスクを追加" else "変更を保存")
            }
        }
    }
    if (showDatePicker) {
        val datePickerState = rememberDatePickerState(initialSelectedDateMillis = dueDateToMillis(dueDate))
        DatePickerDialog(
            onDismissRequest = { showDatePicker = false },
            confirmButton = {
                TextButton(
                    onClick = {
                        datePickerState.selectedDateMillis?.let { dueDate = millisToDueDate(it) }
                        showDatePicker = false
                    },
                ) {
                    Text("決定")
                }
            },
            dismissButton = {
                TextButton(onClick = { showDatePicker = false }) { Text("キャンセル") }
            },
        ) {
            DatePicker(state = datePickerState, showModeToggle = false)
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun NoteEditorScreen(viewModel: SparkleViewModel, noteId: Int?) {
    val note = viewModel.note(noteId)
    var title by remember(noteId) { mutableStateOf(note?.title.orEmpty()) }
    var body by remember(noteId) { mutableStateOf(note?.body.orEmpty()) }
    var linkedTaskIds by remember(noteId) { mutableStateOf(note?.taskIds?.toSet().orEmpty()) }
    var validationError by remember(noteId) { mutableStateOf<String?>(null) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(if (noteId == null) "メモを追加" else "メモを編集") },
                navigationIcon = {
                    IconButton(onClick = { viewModel.openTasksNotes(tab = 1) }, modifier = Modifier.semantics { contentDescription = "メモ一覧へ戻る" }) {
                        Icon(Icons.Default.ArrowBack, contentDescription = null)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
            )
        },
    ) { padding ->
        if (noteId != null && note == null) {
            EmptyState(Icons.Default.ErrorOutline, "メモが見つかりません", "PC側で削除された可能性があります。", Modifier.padding(padding))
            return@Scaffold
        }
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp, vertical = 10.dp)
                .navigationBarsPadding(),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Text("メモの変更はPC API経由で保存されます。", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            viewModel.errorMessage?.let { ErrorBanner(it, viewModel::clearError) }
            validationError?.let { ErrorBanner(it) { validationError = null } }
            OutlinedTextField(
                value = title,
                onValueChange = { title = it; validationError = null },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("タイトル") },
                singleLine = true,
            )
            OutlinedTextField(
                value = body,
                onValueChange = { body = it },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("本文") },
                minLines = 8,
            )
            Text("関連タスク", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            if (viewModel.tasks.isEmpty()) {
                Text("関連付けられるタスクはありません。", color = MaterialTheme.colorScheme.onSurfaceVariant)
            } else {
                Column(modifier = Modifier.heightIn(max = 280.dp).verticalScroll(rememberScrollState())) {
                    viewModel.tasks.forEach { task ->
                        LinkCheckboxRow(
                            label = task.title,
                            checked = task.id in linkedTaskIds,
                            onCheckedChange = { checked -> linkedTaskIds = if (checked) linkedTaskIds + task.id else linkedTaskIds - task.id },
                        )
                    }
                }
            }
            Button(
                onClick = {
                    if (title.trim().isBlank()) {
                        validationError = "メモのタイトルを入力してください。"
                    } else {
                        viewModel.saveNote(noteId, title, body, linkedTaskIds)
                    }
                },
                enabled = !viewModel.isBusy,
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (viewModel.isBusy) {
                    CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                    Spacer(Modifier.width(8.dp))
                }
                Text(if (noteId == null) "メモを追加" else "変更を保存")
            }
        }
    }
}

@Composable
private fun SectionHeading(title: String) {
    Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(top = 8.dp))
}

@Composable
private fun ProjectClipRow(clip: Clip, thumbnailUrl: String?, onClick: () -> Unit) {
    Card(onClick = onClick, modifier = Modifier.fillMaxWidth()) {
        Row(modifier = Modifier.padding(10.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            SparkleThumbnail(url = thumbnailUrl, modifier = Modifier.size(width = 84.dp, height = 64.dp), contentDescription = "${clip.displayTitle}のサムネイル")
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(clip.displayTitle, style = MaterialTheme.typography.titleSmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Text(clip.url, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DetailScreen(viewModel: SparkleViewModel, clipId: Int) {
    val clip = viewModel.clip(clipId)
    val context = androidx.compose.ui.platform.LocalContext.current
    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("クリップ詳細") },
                navigationIcon = {
                    IconButton(onClick = viewModel::goToHome, modifier = Modifier.semantics { contentDescription = "ホームへ戻る" }) {
                        Icon(Icons.Default.ArrowBack, contentDescription = null)
                    }
                },
                actions = {
                    if (clip != null) {
                        IconButton(onClick = { viewModel.beginEdit(clip.id) }, modifier = Modifier.semantics { contentDescription = "クリップを編集" }) {
                            Icon(Icons.Default.Edit, contentDescription = null)
                        }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
            )
        },
    ) { padding ->
        if (clip == null) {
            EmptyState(Icons.Default.ErrorOutline, "クリップが見つかりません", "PC側で削除された可能性があります。", Modifier.padding(padding))
            return@Scaffold
        }
        Column(modifier = Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            viewModel.errorMessage?.let { ErrorBanner(it, viewModel::clearError) }
            viewModel.fileActionMessage?.let { FileActionBanner(it, viewModel::clearFileActionMessage) }
            if (clip.clipType == "local") {
                LocalFileDetail(viewModel, clip, context)
            } else {
                SparkleThumbnail(url = viewModel.thumbnailUrl(clip.thumbnailUrl), modifier = Modifier.fillMaxWidth().height(210.dp), contentDescription = "${clip.displayTitle}のサムネイル")
            }
            Text(clip.displayTitle, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
            if (clip.clipType == "local") {
                DetailField("ファイル名", localFileName(clip))
                clip.fileSize?.let { DetailField("サイズ", formatFileSize(it)) }
            } else {
                Text(clip.url, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.primary)
            }
            if (clip.url.startsWith("http://") || clip.url.startsWith("https://")) {
                OutlinedButton(onClick = { openClipUrl(context, clip.url) }, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Default.OpenInNew, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text("リンクを開く")
                }
            }
            HorizontalDivider()
            DetailField("カテゴリ", viewModel.categoryName(clip.categoryId) ?: "未設定")
            DetailField("タグ", clip.tags.joinToString("、") { it.name }.ifBlank { "未設定" })
            DetailField("保存日時", formatDate(clip.createdAt))
            DetailField("種別", if (clip.clipType == "local") "ファイル" else "URL")
            Text("コメント", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(clip.comment?.takeIf { it.isNotBlank() } ?: "コメントはありません。", style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
private fun LocalFileDetail(
    viewModel: SparkleViewModel,
    clip: Clip,
    context: Context,
) {
    val fileName = localFileName(clip)
    val mimeType = localFileMimeType(clip)
    val fileUrl = viewModel.localFileUrl(clip.id)
    var isPreparingPreview by remember(clip.id) { mutableStateOf(false) }

    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        when {
            clip.isFolder -> Card(
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Row(
                    modifier = Modifier.padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Icon(Icons.Default.Folder, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                    Text("フォルダはAndroid上でプレビュー・ダウンロードできません。", style = MaterialTheme.typography.bodyMedium)
                }
            }
            localFileKind(clip) == LocalFileKind.Image && fileUrl != null -> SparkleThumbnail(
                url = fileUrl,
                modifier = Modifier.fillMaxWidth().height(240.dp),
                contentDescription = "${clip.displayTitle}のファイルプレビュー",
            )
            localFileKind(clip) == LocalFileKind.Text -> LocalTextPreview(viewModel, clip.id)
            localFileKind(clip) == LocalFileKind.Video && fileUrl != null -> SparkleVideoPreview(fileUrl, mimeType)
            else -> Card(
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Row(
                    modifier = Modifier.padding(16.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Icon(Icons.Default.AttachFile, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                    Text("この形式は、端末の対応アプリでプレビューできます。", style = MaterialTheme.typography.bodyMedium)
                }
            }
        }

        if (!clip.isFolder) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                if (localFileKind(clip) == LocalFileKind.Other) {
                    OutlinedButton(
                        onClick = {
                            isPreparingPreview = true
                            viewModel.prepareLocalFilePreview(clip.id, fileName, mimeType) { path, preparedMimeType ->
                                isPreparingPreview = false
                                if (!openLocalFile(context, path, preparedMimeType ?: mimeType)) {
                                    viewModel.showFileActionMessage("このファイルを開ける対応アプリがありません。")
                                }
                            }
                        },
                        enabled = fileUrl != null && !viewModel.fileActionBusy,
                        modifier = Modifier.weight(1f),
                    ) {
                        if (isPreparingPreview) {
                            CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                        } else {
                            Icon(Icons.Default.OpenInNew, contentDescription = null)
                        }
                        Spacer(Modifier.width(8.dp))
                        Text("対応アプリでプレビュー")
                    }
                }
                Button(
                    onClick = { viewModel.downloadLocalFile(clip.id, fileName, mimeType) },
                    enabled = fileUrl != null && !viewModel.fileActionBusy,
                    modifier = Modifier.weight(1f),
                ) {
                    Icon(Icons.Default.Download, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text("ダウンロード")
                }
            }
        }
    }
}

@Composable
private fun LocalTextPreview(viewModel: SparkleViewModel, clipId: Int) {
    val state by produceState<LocalTextPreviewState>(
        initialValue = LocalTextPreviewState.Loading,
        key1 = clipId,
        key2 = viewModel.baseUrl,
    ) {
        value = try {
            LocalTextPreviewState.Loaded(withContext(Dispatchers.IO) { viewModel.loadTextPreview(clipId) })
        } catch (_: Throwable) {
            LocalTextPreviewState.Failed
        }
    }
    when (state) {
        LocalTextPreviewState.Loading -> Card(modifier = Modifier.fillMaxWidth()) {
            Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp)
                Text("テキストを読み込んでいます…")
            }
        }
        is LocalTextPreviewState.Loaded -> Card(
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
            modifier = Modifier.fillMaxWidth(),
        ) {
            SelectionContainer {
                Text(
                    (state as LocalTextPreviewState.Loaded).text.ifBlank { "（内容が空です）" },
                    modifier = Modifier.padding(14.dp),
                    style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace),
                )
            }
        }
        LocalTextPreviewState.Failed -> Card(
            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("テキストプレビューを取得できませんでした。", modifier = Modifier.padding(14.dp))
        }
    }
}

private enum class LocalFileKind {
    Image,
    Text,
    Video,
    Other,
}

private sealed interface LocalTextPreviewState {
    data object Loading : LocalTextPreviewState
    data class Loaded(val text: String) : LocalTextPreviewState
    data object Failed : LocalTextPreviewState
}

private fun localFileKind(clip: Clip): LocalFileKind = when (localFileExtension(clip).orEmpty()) {
    in setOf("png", "jpg", "jpeg", "gif", "webp", "bmp", "ico") -> LocalFileKind.Image
    in setOf("txt", "md", "json", "csv", "log", "xml", "yaml", "yml", "toml", "ini", "cfg", "conf", "py", "js", "ts", "html", "css", "java", "c", "cpp", "h", "rs", "go", "rb", "php", "sh", "bat", "sql") -> LocalFileKind.Text
    in setOf("mp4", "webm", "ogg", "mov", "avi", "mkv") -> LocalFileKind.Video
    else -> LocalFileKind.Other
}

private fun localFileExtension(clip: Clip): String? {
    val source = clip.url.substringBefore('?').substringAfterLast('/').substringAfterLast('\\')
    return source.substringAfterLast('.', "").lowercase(Locale.ROOT).takeIf { it.isNotBlank() && it.length <= 10 }
}

private fun localFileName(clip: Clip): String {
    val source = clip.url.substringBefore('?').substringAfterLast('/').substringAfterLast('\\')
    val extension = localFileExtension(clip)
    val title = clip.title?.trim().takeIf { !it.isNullOrBlank() } ?: source.ifBlank { "sparkle-file" }
    val withExtension = if (extension != null && !title.lowercase(Locale.ROOT).endsWith(".$extension")) {
        "$title.$extension"
    } else {
        title
    }
    return withExtension
        .replace(Regex("[<>:\"/\\\\|?*]"), "_")
        .trim()
        .trimEnd('.')
        .take(180)
        .ifBlank { "sparkle-file" }
}

private fun localFileMimeType(clip: Clip): String? =
    localFileExtension(clip)?.let { MimeTypeMap.getSingleton().getMimeTypeFromExtension(it) }

private fun openLocalFile(context: Context, path: String, mimeType: String?): Boolean {
    val file = File(path)
    if (!file.isFile) return false
    val uri = runCatching {
        FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
    }.getOrNull() ?: return false
    val intent = Intent(Intent.ACTION_VIEW).apply {
        setDataAndType(uri, mimeType ?: "application/octet-stream")
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
    }
    return try {
        context.startActivity(intent)
        true
    } catch (_: ActivityNotFoundException) {
        false
    } catch (_: SecurityException) {
        false
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
private fun EditorScreen(
    viewModel: SparkleViewModel,
    clipId: Int?,
    onOpenMenu: () -> Unit,
    onOpenSettings: () -> Unit,
    onPickFile: () -> Unit,
) {
    val existingClip = clipId?.let(viewModel::clip)
    val source = if (clipId == null) viewModel.editorSource else null
    var url by remember(clipId, source) { mutableStateOf(source?.url.orEmpty().ifBlank { existingClip?.url.orEmpty() }) }
    var title by remember(clipId, source) {
        mutableStateOf(
            source?.title.orEmpty()
                .ifBlank { source?.upload?.displayName.orEmpty() }
                .ifBlank { existingClip?.title.orEmpty() },
        )
    }
    var comment by remember(clipId, source) { mutableStateOf(existingClip?.comment.orEmpty()) }
    var category by remember(clipId, source) { mutableStateOf(viewModel.categoryName(existingClip?.categoryId).orEmpty()) }
    var tags by remember(clipId, source) { mutableStateOf(existingClip?.tags?.joinToString(", ") { it.name }.orEmpty()) }
    var validationError by remember(clipId, source) { mutableStateOf<String?>(null) }
    val upload = source?.upload

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(if (clipId == null) "クリップを作成" else "クリップを編集") },
                navigationIcon = {
                    if (clipId == null) {
                        IconButton(onClick = onOpenMenu, modifier = Modifier.semantics { contentDescription = "メニューを開く" }) {
                            Icon(Icons.Default.Menu, contentDescription = null)
                        }
                    } else {
                        IconButton(onClick = { viewModel.openDetail(clipId) }, modifier = Modifier.semantics { contentDescription = "編集をキャンセル" }) {
                            Icon(Icons.Default.ArrowBack, contentDescription = null)
                        }
                    }
                },
                actions = {
                    if (viewModel.baseUrl.isBlank()) TextButton(onClick = onOpenSettings) { Text("設定") }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
            )
        },
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 8.dp).navigationBarsPadding(), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Text("変更はPC API経由で保存されます。Android側にはクリップDBを保存しません。", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            viewModel.errorMessage?.let { ErrorBanner(it, viewModel::clearError) }
            validationError?.let { ErrorBanner(it) { validationError = null } }
            if (upload != null) {
                Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer), modifier = Modifier.fillMaxWidth()) {
                    Row(modifier = Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Icon(Icons.Default.AttachFile, contentDescription = null)
                        Text(upload.displayName, modifier = Modifier.weight(1f), maxLines = 2, overflow = TextOverflow.Ellipsis)
                    }
                }
                OutlinedButton(onClick = onPickFile, modifier = Modifier.fillMaxWidth()) {
                    Icon(Icons.Default.AttachFile, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text("別のファイルを選択")
                }
            } else {
                OutlinedTextField(
                    value = url,
                    onValueChange = { url = it; validationError = null },
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text("URL") },
                    leadingIcon = { Icon(Icons.Default.Link, contentDescription = null) },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                    readOnly = existingClip != null,
                    supportingText = if (existingClip != null) { { Text("既存クリップのURLは変更できません。") } } else { { Text("ブラウザの共有から受け取ったURLを編集できます。") } },
                    singleLine = true,
                )
            }
            OutlinedTextField(value = title, onValueChange = { title = it }, modifier = Modifier.fillMaxWidth(), label = { Text("タイトル") }, maxLines = 3)
            OutlinedTextField(value = comment, onValueChange = { comment = it }, modifier = Modifier.fillMaxWidth(), label = { Text("コメント") }, minLines = 4)
            OutlinedTextField(value = category, onValueChange = { category = it }, modifier = Modifier.fillMaxWidth(), label = { Text("カテゴリ") }, supportingText = { Text("新しい名前を入力するとPC側で作成されます。") }, singleLine = true)
            OutlinedTextField(value = tags, onValueChange = { tags = it }, modifier = Modifier.fillMaxWidth(), label = { Text("タグ") }, supportingText = { Text("カンマ区切りで入力") }, maxLines = 3)
            Button(
                onClick = {
                    if (upload == null && url.trim().isBlank()) {
                        validationError = "共有URLを入力するか、ファイルを選択してください。"
                    } else {
                        viewModel.createClip(
                            draft = ClipDraft(
                                url = url.trim(),
                                title = title.trim().takeIf { it.isNotEmpty() },
                                comment = comment.trim().takeIf { it.isNotEmpty() },
                                category = category.trim().takeIf { it.isNotEmpty() },
                                tags = tags.split(',').map(String::trim).filter(String::isNotEmpty),
                            ),
                            upload = upload,
                        )
                    }
                },
                enabled = !viewModel.isBusy,
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (viewModel.isBusy) {
                    CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                    Spacer(Modifier.width(8.dp))
                }
                Text(if (clipId == null) "保存" else "変更を保存")
            }
            Spacer(Modifier.height(28.dp))
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AppSettingsScreen(viewModel: SparkleViewModel, onOpenMenu: () -> Unit) {
    val settings = viewModel.appSettings
    var deleteExpanded by remember { mutableStateOf(false) }
    val canEdit = viewModel.baseUrl.isNotBlank() && !viewModel.isBusy
    val deleteOption = TaskAutoDeleteOption.fromValue(settings.taskAutoDelete)

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("アプリ設定") },
                navigationIcon = {
                    IconButton(onClick = onOpenMenu, modifier = Modifier.semantics { contentDescription = "メニューを開く" }) {
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
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Text(
                "タスクとプロジェクトに関する設定をPCと共有します。変更は保存した直後からPC側の処理にも反映されます。",
                style = MaterialTheme.typography.bodyLarge,
            )
            ConnectionBanner(viewModel.connectionState, viewModel::refreshAppSettings, viewModel::openSettings)
            viewModel.errorMessage?.let { ErrorBanner(it, viewModel::clearError) }

            Text("タスクの設定", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            AppSettingSwitchRow(
                title = "タスク作成時に同名の空メモを自動作成",
                checked = settings.autoCreateNoteOnTask,
                enabled = canEdit,
                onCheckedChange = { checked ->
                    viewModel.updateAppSetting("auto_create_note_on_task", checked.toString())
                },
            )
            Text("完了したタスクを自動削除", style = MaterialTheme.typography.bodyLarge)
            Box {
                OutlinedButton(
                    onClick = { deleteExpanded = true },
                    enabled = canEdit,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(deleteOption.label, modifier = Modifier.weight(1f))
                    Icon(Icons.Default.ArrowBack, contentDescription = null, modifier = Modifier.size(18.dp).rotate(270f))
                }
                DropdownMenu(
                    expanded = deleteExpanded,
                    onDismissRequest = { deleteExpanded = false },
                ) {
                    TaskAutoDeleteOption.values().forEach { option ->
                        DropdownMenuItem(
                            text = { Text(option.label) },
                            onClick = {
                                deleteExpanded = false
                                viewModel.updateAppSetting("task_auto_delete", option.value)
                            },
                        )
                    }
                }
            }

            Text("プロジェクトの設定", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            AppSettingSwitchRow(
                title = "プロジェクト作成時に同名の空メモを自動作成",
                checked = settings.autoCreateNoteOnProject,
                enabled = canEdit,
                onCheckedChange = { checked ->
                    viewModel.updateAppSetting("auto_create_note_on_project", checked.toString())
                },
            )
        }
    }
}

@Composable
private fun AppSettingSwitchRow(
    title: String,
    checked: Boolean,
    enabled: Boolean,
    onCheckedChange: (Boolean) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(title, modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodyLarge)
        Switch(checked = checked, onCheckedChange = onCheckedChange, enabled = enabled)
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
                    IconButton(onClick = onOpenMenu, modifier = Modifier.semantics { contentDescription = "メニューを開く" }) {
                        Icon(Icons.Default.Menu, contentDescription = null)
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent),
            )
        },
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding).verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 10.dp).navigationBarsPadding(), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Text("SparkleのPC APIに接続します。PCがクリップDBの唯一の所有者で、Android側にはDBの複製を作りません。", style = MaterialTheme.typography.bodyLarge)
            Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer), modifier = Modifier.fillMaxWidth()) {
                Row(Modifier.padding(16.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Icon(Icons.Default.Wifi, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                    Text("Tailscale Serveで公開したHTTPS URLを入力してください。", style = MaterialTheme.typography.bodyMedium)
                }
            }
            viewModel.errorMessage?.let { ErrorBanner(it, viewModel::clearError) }
            OutlinedTextField(value = inputUrl, onValueChange = { inputUrl = it }, modifier = Modifier.fillMaxWidth(), label = { Text("PC API URL") }, placeholder = { Text("https://sparkle.example.ts.net") }, leadingIcon = { Icon(Icons.Default.Link, contentDescription = null) }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri), supportingText = { Text("認証情報は保存せず、URLだけを端末の設定に保存します。") }, singleLine = true)
            ConnectionStatusCard(viewModel.connectionState)
            ConnectionBanner(viewModel.connectionState, viewModel::refresh, null)
            Button(onClick = { viewModel.saveConnection(inputUrl) }, enabled = !viewModel.isBusy, modifier = Modifier.fillMaxWidth()) {
                if (viewModel.isBusy) {
                    CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                    Spacer(Modifier.width(8.dp))
                }
                Text("保存して接続確認")
            }
            OutlinedButton(onClick = { inputUrl = ""; viewModel.clearConnection() }, modifier = Modifier.fillMaxWidth()) { Text("接続設定を消去") }
        }
    }
}

@Composable
private fun ConnectionStatusCard(state: ConnectionState) {
    Card(modifier = Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
        Row(modifier = Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
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
private fun ConnectionBanner(state: ConnectionState, onRetry: (() -> Unit)?, onSettings: (() -> Unit)?) {
    if (state is ConnectionState.Connected) return
    Card(modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                ConnectionStatusIcon(state)
                Text(statusLabel(state), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            }
            when (state) {
                ConnectionState.Unconfigured -> Text("PC URLを設定すると、PCのデータを読み込めます。")
                ConnectionState.Checking -> Text("PC APIに接続しています…")
                is ConnectionState.Unavailable -> Text(state.reason)
                ConnectionState.Connected -> Unit
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                onSettings?.let { TextButton(onClick = it) { Text("接続設定") } }
                onRetry?.let { TextButton(onClick = it, enabled = state !is ConnectionState.Checking) { Text("再試行") } }
            }
        }
    }
}

@Composable
private fun ErrorBanner(message: String, onDismiss: () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer)) {
        Row(modifier = Modifier.padding(start = 14.dp, end = 4.dp, top = 10.dp, bottom = 10.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Icon(Icons.Default.ErrorOutline, contentDescription = "エラー", tint = MaterialTheme.colorScheme.error)
            Text(message, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
            TextButton(onClick = onDismiss) { Text("閉じる") }
        }
    }
}

@Composable
private fun FileActionBanner(message: String, onDismiss: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer),
    ) {
        Row(
            modifier = Modifier.padding(start = 14.dp, end = 4.dp, top = 10.dp, bottom = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Icon(Icons.Default.CheckCircle, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
            Text(message, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
            TextButton(onClick = onDismiss) { Text("閉じる") }
        }
    }
}

@Composable
private fun LoadingState() {
    EmptyState(Icons.Default.Refresh, "PCから読み込み中", "クリップ、タスク、メモ、プロジェクトを取得しています。", showProgress = true)
}

@Composable
private fun UnconfiguredState(onSettings: () -> Unit) {
    EmptyState(Icons.Default.CloudOff, "PCが未接続です", "PC接続設定からTailscale URLを登録してください。", action = { Button(onClick = onSettings) { Text("接続設定を開く") } })
}

@Composable
private fun UnavailableState(onSettings: () -> Unit, onRetry: () -> Unit) {
    EmptyState(
        Icons.Default.CloudOff,
        "PCを利用できません",
        "PCが起動中か、Tailscale接続とURLが正しいか確認してください。",
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
    EmptyState(Icons.Default.Search, "該当するクリップがありません", "検索語、カテゴリ、タグの絞り込みを変更してください。")
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
    Box(modifier = modifier.fillMaxSize().padding(28.dp), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (showProgress) CircularProgressIndicator(modifier = Modifier.size(36.dp))
            else Icon(icon, contentDescription = null, modifier = Modifier.size(42.dp), tint = MaterialTheme.colorScheme.primary)
            Text(title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
            Text(message, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.widthIn(max = 340.dp))
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

private fun formatDate(value: String): String = value.take(19).replace('T', ' ')

private fun formatFileSize(bytes: Long): String {
    if (bytes < 1024) return "$bytes B"
    val units = listOf("KB", "MB", "GB", "TB")
    var value = bytes.toDouble()
    var unit = units.first()
    for (candidate in units) {
        value /= 1024.0
        unit = candidate
        if (value < 1024.0 || candidate == units.last()) break
    }
    return "%.1f %s".format(Locale.ROOT, value, unit)
}

private fun dueDateToMillis(value: String): Long? = runCatching {
    LocalDate.parse(value).atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli()
}.getOrNull()

private fun millisToDueDate(value: Long): String =
    Instant.ofEpochMilli(value).atZone(ZoneOffset.UTC).toLocalDate().toString()

private fun openClipUrl(context: Context, rawUrl: String) {
    context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(rawUrl)))
}

private fun selectionForUri(context: Context, uri: Uri): UploadSelection {
    val displayName = context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
        ?.use { cursor ->
            if (cursor.moveToFirst()) cursor.getString(cursor.getColumnIndexOrThrow(OpenableColumns.DISPLAY_NAME)) else null
        }
        ?.takeIf { it.isNotBlank() }
        ?: uri.lastPathSegment?.substringAfterLast('/')?.takeIf { it.isNotBlank() }
        ?: "shared-file"
    return UploadSelection(uri, displayName, context.contentResolver.getType(uri))
}

private fun parseShareIntent(context: Context, intent: Intent?): ClipCreationSource? {
    if (intent == null || intent.action !in setOf(Intent.ACTION_SEND, Intent.ACTION_SEND_MULTIPLE)) return null
    val sharedUri = if (Build.VERSION.SDK_INT >= 33) {
        intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)
            ?: intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM, Uri::class.java)?.firstOrNull()
    } else {
        @Suppress("DEPRECATION")
        intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM)
    }
    if (sharedUri != null) {
        return ClipCreationSource(title = intent.getStringExtra(Intent.EXTRA_SUBJECT), upload = selectionForUri(context, sharedUri))
    }
    val sharedText = intent.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString()?.trim().orEmpty()
    if (sharedText.isBlank()) return null
    val sharedUrl = Regex("https?://[^\\s]+", RegexOption.IGNORE_CASE)
        .find(sharedText)
        ?.value
        ?.trimEnd('.', ',', ')', ']', '}', '>')
        ?: sharedText
    return ClipCreationSource(url = sharedUrl, title = intent.getStringExtra(Intent.EXTRA_SUBJECT))
}
