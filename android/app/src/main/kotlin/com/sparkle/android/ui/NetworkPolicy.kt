package com.sparkle.android.ui

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
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
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner

data class NetworkPolicy(
    val isConnected: Boolean,
    val isCellular: Boolean,
    val isMetered: Boolean,
    val isDataSaverEnabled: Boolean,
) {
    val restrictThumbnails: Boolean
        get() = isCellular || isDataSaverEnabled

    /** Videos auto-load only on connected Wi-Fi while Data Saver is off. */
    val allowVideoAutoLoad: Boolean
        get() = isConnected && !isCellular && !isDataSaverEnabled

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
    private val applicationContext = context.applicationContext
    private val connectivityManager = context.getSystemService(ConnectivityManager::class.java)
    private val mainHandler = Handler(Looper.getMainLooper())

    class Registration(
        val networkCallback: ConnectivityManager.NetworkCallback,
        val dataSaverReceiver: BroadcastReceiver,
    )

    fun current(): NetworkPolicy {
        val capabilities = connectivityManager.activeNetwork
            ?.let(connectivityManager::getNetworkCapabilities)
        val isConnected = capabilities != null
        val isCellular = capabilities?.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) == true
        val isMetered = isConnected && connectivityManager.isActiveNetworkMetered
        val isDataSaverEnabled = connectivityManager.restrictBackgroundStatus !=
            ConnectivityManager.RESTRICT_BACKGROUND_STATUS_DISABLED
        return NetworkPolicy(
            isConnected = isConnected,
            isCellular = isCellular,
            isMetered = isMetered,
            isDataSaverEnabled = isDataSaverEnabled,
        )
    }

    fun register(listener: (NetworkPolicy) -> Unit): Registration {
        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) = dispatch(listener)

            override fun onCapabilitiesChanged(network: Network, networkCapabilities: NetworkCapabilities) =
                dispatch(listener)

            override fun onLost(network: Network) = dispatch(listener)
        }
        val dataSaverReceiver = object : BroadcastReceiver() {
            override fun onReceive(context: Context?, intent: Intent?) {
                if (intent?.action == ConnectivityManager.ACTION_RESTRICT_BACKGROUND_CHANGED) {
                    dispatch(listener)
                }
            }
        }
        connectivityManager.registerDefaultNetworkCallback(callback)
        ContextCompat.registerReceiver(
            applicationContext,
            dataSaverReceiver,
            IntentFilter(ConnectivityManager.ACTION_RESTRICT_BACKGROUND_CHANGED),
            ContextCompat.RECEIVER_EXPORTED,
        )
        dispatch(listener)
        return Registration(callback, dataSaverReceiver)
    }

    fun unregister(registration: Registration) {
        runCatching { connectivityManager.unregisterNetworkCallback(registration.networkCallback) }
        runCatching { applicationContext.unregisterReceiver(registration.dataSaverReceiver) }
    }

    private fun dispatch(listener: (NetworkPolicy) -> Unit) {
        val update = { listener(current()) }
        if (Looper.myLooper() == Looper.getMainLooper()) update() else mainHandler.post(update)
    }
}

@Composable
fun rememberNetworkPolicy(): NetworkPolicy {
    val context = LocalContext.current.applicationContext
    val lifecycleOwner = LocalLifecycleOwner.current
    val monitor = remember(context) { NetworkPolicyMonitor(context) }
    var policy by remember(monitor) { mutableStateOf(monitor.current()) }
    DisposableEffect(monitor, lifecycleOwner) {
        val registration = monitor.register { policy = it }
        val lifecycleObserver = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                policy = monitor.current()
            }
        }
        lifecycleOwner.lifecycle.addObserver(lifecycleObserver)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(lifecycleObserver)
            monitor.unregister(registration)
        }
    }
    return policy
}
