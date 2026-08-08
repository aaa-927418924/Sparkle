package com.sparkle.android.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val SparkleLightColors = lightColorScheme(
    primary = Color(0xFFB95113),
    onPrimary = Color.White,
    primaryContainer = Color(0xFFFFDBBE),
    onPrimaryContainer = Color(0xFF3A0A00),
    secondary = Color(0xFF6B5D54),
    onSecondary = Color.White,
    secondaryContainer = Color(0xFFF3DED2),
    onSecondaryContainer = Color(0xFF251A14),
    background = Color(0xFFFFF8F5),
    surface = Color(0xFFFFF8F5),
    surfaceVariant = Color(0xFFF5DED3),
    onSurfaceVariant = Color(0xFF51443D),
)

private val SparkleDarkColors = darkColorScheme(
    primary = Color(0xFFFFB68A),
    onPrimary = Color(0xFF5A1A00),
    primaryContainer = Color(0xFF7D2E08),
    onPrimaryContainer = Color(0xFFFFDBBE),
    secondary = Color(0xFFD6C2B6),
    onSecondary = Color(0xFF392D27),
    secondaryContainer = Color(0xFF51433B),
    onSecondaryContainer = Color(0xFFF3DED2),
    background = Color(0xFF17120F),
    surface = Color(0xFF17120F),
    surfaceVariant = Color(0xFF51433B),
    onSurfaceVariant = Color(0xFFD6C2B6),
)

@Composable
fun SparkleTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = if (isSystemInDarkTheme()) SparkleDarkColors else SparkleLightColors,
        typography = Typography(),
        content = content,
    )
}
