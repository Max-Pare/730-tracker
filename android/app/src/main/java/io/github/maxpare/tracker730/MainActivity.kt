// SPDX-License-Identifier: AGPL-3.0-or-later
package io.github.maxpare.tracker730

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.AddCircle
import androidx.compose.material.icons.filled.Dashboard
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.automirrored.filled.ReceiptLong
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.core.content.IntentCompat
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import io.github.maxpare.tracker730.data.Format
import io.github.maxpare.tracker730.ui.components.LoadingBox
import io.github.maxpare.tracker730.ui.screens.AccountScreen
import io.github.maxpare.tracker730.ui.screens.AccountViewModel
import io.github.maxpare.tracker730.ui.screens.ArchiveScreen
import io.github.maxpare.tracker730.ui.screens.ArchiveViewModel
import io.github.maxpare.tracker730.ui.screens.AuthScreen
import io.github.maxpare.tracker730.ui.screens.CaptureScreen
import io.github.maxpare.tracker730.ui.screens.CaptureViewModel
import io.github.maxpare.tracker730.ui.screens.DashboardScreen
import io.github.maxpare.tracker730.ui.screens.DashboardViewModel
import io.github.maxpare.tracker730.ui.screens.ReceiptScreen
import io.github.maxpare.tracker730.ui.screens.ReceiptViewModel
import io.github.maxpare.tracker730.ui.screens.RecoveryCodeScreen
import io.github.maxpare.tracker730.ui.screens.ServerSetupScreen
import io.github.maxpare.tracker730.ui.theme.TrackerTheme

class MainActivity : ComponentActivity() {
    private val container by lazy { (application as TrackerApp).container }
    private val appVm: AppViewModel by viewModels {
        viewModelFactory { initializer { AppViewModel(container) } }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        if (savedInstanceState == null) handleShare(intent)
        setContent {
            TrackerTheme {
                Surface(color = MaterialTheme.colorScheme.background) {
                    Root(appVm, container)
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleShare(intent)
    }

    private fun handleShare(intent: Intent?) {
        val uris: List<Uri> = when (intent?.action) {
            Intent.ACTION_SEND -> listOfNotNull(IntentCompat.getParcelableExtra(intent, Intent.EXTRA_STREAM, Uri::class.java))
            Intent.ACTION_SEND_MULTIPLE -> IntentCompat.getParcelableArrayListExtra(intent, Intent.EXTRA_STREAM, Uri::class.java).orEmpty()
            else -> emptyList()
        }
        if (uris.isNotEmpty()) appVm.addShared(uris)
    }
}

private object Routes {
    const val DASHBOARD = "dashboard"
    const val ARCHIVE = "archive?status={status}"
    const val CAPTURE = "capture"
    const val ACCOUNT = "account"
    const val RECEIPT = "receipt/{id}"
    const val NEW_RECEIPT = "receipt-new"
    fun archive(status: String? = null) = if (status == null) "archive" else "archive?status=$status"
    fun receipt(id: String) = "receipt/$id"
}

private inline fun <reified VM : ViewModel> factory(crossinline create: () -> VM): ViewModelProvider.Factory =
    viewModelFactory { initializer { create() } }

@Composable
private fun Root(appVm: AppViewModel, container: AppContainer) {
    val state by appVm.state.collectAsStateWithLifecycle()
    when {
        state.recoveryCode != null -> RecoveryCodeScreen(state.recoveryCode!!) { appVm.recoveryCodeShown() }
        state.phase == Phase.Loading -> LoadingBox()
        state.phase == Phase.NeedsServer -> ServerSetupScreen(state, appVm)
        state.phase == Phase.NeedsLogin -> AuthScreen(state, appVm)
        else -> MainShell(state, appVm, container)
    }
}

private data class Tab(val route: String, val nav: String, val label: Int, val icon: ImageVector)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun MainShell(state: AppState, appVm: AppViewModel, container: AppContainer) {
    val nav = rememberNavController()
    val backStack by nav.currentBackStackEntryAsState()
    val route = backStack?.destination?.route
    val snackbar = remember { SnackbarHostState() }
    val tabs = listOf(
        Tab(Routes.DASHBOARD, Routes.DASHBOARD, R.string.nav_dashboard, Icons.Default.Dashboard),
        Tab(Routes.ARCHIVE, Routes.archive(), R.string.nav_archive, Icons.AutoMirrored.Filled.ReceiptLong),
        Tab(Routes.CAPTURE, Routes.CAPTURE, R.string.nav_add, Icons.Default.AddCircle),
        Tab(Routes.ACCOUNT, Routes.ACCOUNT, R.string.nav_account, Icons.Default.Person),
    )
    val isDetail = route == Routes.RECEIPT || route == Routes.NEW_RECEIPT

    LaunchedEffect(state.sharedUris) { if (state.sharedUris.isNotEmpty()) nav.navigateTab(Routes.CAPTURE) }
    LaunchedEffect(state.error) { state.error?.let { snackbar.showSnackbar(it); appVm.clearMessages() } }

    Scaffold(
        topBar = {
            if (isDetail) TopAppBar(
                title = { Text(stringResource(R.string.app_name)) },
                navigationIcon = {
                    IconButton(onClick = { nav.popBackStack() }) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = stringResource(R.string.back))
                    }
                },
            )
        },
        bottomBar = {
            if (!isDetail) NavigationBar {
                tabs.forEach { t ->
                    NavigationBarItem(
                        selected = route == t.route,
                        onClick = { nav.navigateTab(t.nav) },
                        icon = { Icon(t.icon, contentDescription = null) },
                        label = { Text(stringResource(t.label)) },
                    )
                }
            }
        },
        snackbarHost = { SnackbarHost(snackbar) },
    ) { padding ->
        Box(Modifier.padding(padding)) {
            NavHost(nav, startDestination = Routes.DASHBOARD) {
                composable(Routes.DASHBOARD) {
                    val vm: DashboardViewModel = viewModel(factory = factory { DashboardViewModel(container) })
                    DashboardScreen(
                        vm,
                        onOpenReceipt = { nav.navigate(Routes.receipt(it)) },
                        onOpenDrafts = { nav.navigateTab(Routes.archive("bozza")) },
                        onAdd = { nav.navigateTab(Routes.CAPTURE) },
                    )
                }
                composable(
                    Routes.ARCHIVE,
                    arguments = listOf(navArgument("status") { type = NavType.StringType; nullable = true; defaultValue = null }),
                ) { entry ->
                    val vm: ArchiveViewModel = viewModel(factory = factory { ArchiveViewModel(container) })
                    ArchiveScreen(vm, state.meta, entry.arguments?.getString("status")) { nav.navigate(Routes.receipt(it)) }
                }
                composable(Routes.CAPTURE) {
                    val vm: CaptureViewModel = viewModel(factory = factory { CaptureViewModel(container) })
                    CaptureScreen(
                        vm,
                        shared = state.sharedUris,
                        onSharedConsumed = { appVm.consumeShared() },
                        onDone = { res ->
                            val msg = Format.documents(res.created.size) + if (res.errors.isEmpty()) "" else " · " + res.errors.joinToString("; ") { "${it.filename}: ${it.message}" }
                            when {
                                res.created.size == 1 -> nav.navigate(Routes.receipt(res.created[0].id))
                                res.created.isNotEmpty() -> nav.navigateTab(Routes.archive("bozza"))
                            }
                            appVm.clearMessages()
                            if (res.errors.isNotEmpty() || res.created.size > 1) {
                                appVm.showNotice(msg)
                            }
                        },
                        onManual = { nav.navigate(Routes.NEW_RECEIPT) },
                    )
                }
                composable(Routes.ACCOUNT) {
                    val vm: AccountViewModel = viewModel(factory = factory { AccountViewModel(container, appVm) })
                    AccountScreen(state, appVm, vm)
                }
                composable(Routes.RECEIPT, arguments = listOf(navArgument("id") { type = NavType.StringType })) { entry ->
                    val id = entry.arguments?.getString("id")!!
                    val vm: ReceiptViewModel = viewModel(key = "receipt-$id", factory = factory { ReceiptViewModel(container, id) })
                    ReceiptScreen(vm, state.meta, state.profile, onClose = { nav.popBackStack() }, onCreated = {})
                }
                composable(Routes.NEW_RECEIPT) {
                    val vm: ReceiptViewModel = viewModel(key = "receipt-new", factory = factory { ReceiptViewModel(container, null) })
                    ReceiptScreen(vm, state.meta, state.profile, onClose = { nav.popBackStack() }, onCreated = { id ->
                        nav.navigate(Routes.receipt(id)) { popUpTo(Routes.NEW_RECEIPT) { inclusive = true } }
                    })
                }
            }
        }
    }
    LaunchedEffect(state.notice) { state.notice?.let { snackbar.showSnackbar(it); appVm.clearMessages() } }
}

private fun NavHostController.navigateTab(route: String) = navigate(route) {
    popUpTo(graph.findStartDestination().id) { saveState = true }
    launchSingleTop = true
    restoreState = !route.startsWith("archive")
}
