package com.sparkle.android.ui

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.os.Handler
import android.os.Looper
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext

data class NetworkPolicy(
    val isConnected: Boolean,
    val isCellular: Boolean,
    val isMetered: Boolean,
    val isDataSaverEnabled: Boolean,
) {
    val restrictThumbnails: Boolean
        get() = !isConnected || isCellular || isMetered || isDataSaverEnabled

    /** Videos auto-load only on a connected, unmetered non-cellular network. */
    val allowVideoAutoLoad: Boolean
        get() = isConnected && !isCellular && !isMetered

    val restrictionLabel: String
        get() = when {
            !isConnected -> "ネットワーク未接続"
            isCellular -> "モバイルデータ使用中"
            isDataSaverEnabled -> "データセーバーが有効"
            isMetered -> "従量制ネットワーク使用中"
            else -> "通信制限なし"
        }
}

private class NetworkPolicyMonitor(context: Context) {
    private val connectivityManager = context.getSystemService(ConnectivityManager::class.java)
    private val mainHandler = Handler(Looper.getMainLooper())

    fun current(): NetworkPolicy {
        val capabilities = connectivityManager.activeNetwork
            ?.let(connectivityManager::getNetworkCapabilities)
        val isConnected = capabilities != null
        val isCellular = capabilities?.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) == true
        val isMetered = isConnected && connectivityManager.isActiveNetworkMetered
        val isDataSaverEnabled = connectivityManager.restrictBackgroundStatus ==
            ConnectivityManager.RESTRICT_BACKGROUND_STATUS_ENABLED
        return NetworkPolicy(
            isConnected = isConnected,
            isCellular = isCellular,
            isMetered = isMetered,
            isDataSaverEnabled = isDataSaverEnabled,
        )
    }

    fun register(listener: (NetworkPolicy) -> Unit): ConnectivityManager.NetworkCallback {
        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) = dispatch(listener)

            override fun onCapabilitiesChanged(network: Network, networkCapabilities: NetworkCapabilities) =
                dispatch(listener)

            override fun onLost(network: Network) = dispatch(listener)
        }
        connectivityManager.registerDefaultNetworkCallback(callback)
        dispatch(listener)
        return callback
    }

    fun unregister(callback: ConnectivityManager.NetworkCallback) {
        runCatching { connectivityManager.unregisterNetworkCallback(callback) }
    }

    private fun dispatch(listener: (NetworkPolicy) -> Unit) {
        val update = { listener(current()) }
        if (Looper.myLooper() == Looper.getMainLooper()) update() else mainHandler.post(update)
    }
}

@Composable
fun rememberNetworkPolicy(): NetworkPolicy {
    val context = LocalContext.current.applicationContext
    val monitor = remember(context) { NetworkPolicyMonitor(context) }
    var policy by remember(monitor) { mutableStateOf(monitor.current()) }
    DisposableEffect(monitor) {
        val callback = monitor.register { policy = it }
        onDispose { monitor.unregister(callback) }
    }
    return policy
}
