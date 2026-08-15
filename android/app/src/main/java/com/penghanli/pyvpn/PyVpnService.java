package com.penghanli.pyvpn;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ServiceInfo;
import android.graphics.drawable.Icon;
import android.net.VpnService;
import android.os.Build;
import android.os.IBinder;
import android.os.ParcelFileDescriptor;
import com.penghanli.pyvpn.protocol.PyVpnProtocolException;
import com.penghanli.pyvpn.protocol.SessionConfig;
import java.net.ConnectException;
import java.net.SocketTimeoutException;
import java.net.UnknownHostException;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;
import javax.net.ssl.SSLException;

public final class PyVpnService extends VpnService {
    public static final String ACTION_CONNECT = "com.penghanli.pyvpn.CONNECT";
    public static final String ACTION_DISCONNECT = "com.penghanli.pyvpn.DISCONNECT";
    public static final String EXTRA_NODE_ID = "node_id";

    private static final String CHANNEL_ID = "pyvpn_connection";
    private static final int NOTIFICATION_ID = 1001;
    private static final String CLIENT_PREFERENCES = "pyvpn_client";
    private static final String CLIENT_ID_KEY = "client_id";

    private final ExecutorService lifecycleExecutor = Executors.newSingleThreadExecutor();
    private final AtomicInteger generation = new AtomicInteger();
    private volatile PyVpnConnection connection;
    private volatile String requestedNodeId;

    public static Intent connectIntent(Context context, String nodeId) {
        return new Intent(context, PyVpnService.class)
                .setAction(ACTION_CONNECT)
                .putExtra(EXTRA_NODE_ID, nodeId);
    }

    public static Intent disconnectIntent(Context context) {
        return new Intent(context, PyVpnService.class).setAction(ACTION_DISCONNECT);
    }

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent == null ? null : intent.getAction();
        if (ACTION_DISCONNECT.equals(action)) {
            requestDisconnect();
            return START_NOT_STICKY;
        }
        if (!ACTION_CONNECT.equals(action)) {
            stopSelf(startId);
            return START_NOT_STICKY;
        }

        String nodeId = intent.getStringExtra(EXTRA_NODE_ID);
        NodeProfile node = nodeId == null ? new NodeStore(this).active() : new NodeStore(this).get(nodeId);
        if (node == null) {
            publishState(VpnRuntimeState.ERROR, "找不到要连接的节点", null);
            stopSelf(startId);
            return START_NOT_STICKY;
        }
        requestedNodeId = node.id();
        startConnection(node, startId);
        return START_NOT_STICKY;
    }

    private void startConnection(NodeProfile node, int startId) {
        int request = generation.incrementAndGet();
        PyVpnConnection previous = connection;
        if (previous != null) {
            previous.stop();
        }

        String initialMessage = "正在连接 " + node.name();
        publishState(VpnRuntimeState.CONNECTING, initialMessage, node.id());
        startForegroundNotification(initialMessage);

        lifecycleExecutor.execute(() -> {
            if (request != generation.get()) {
                return;
            }
            PyVpnConnection next = new PyVpnConnection(
                    this,
                    node,
                    clientId(),
                    new PyVpnConnection.Listener() {
                        @Override
                        public void onStage(String message) {
                            if (request == generation.get()) {
                                publishState(VpnRuntimeState.CONNECTING, message, node.id());
                                updateNotification(message);
                            }
                        }

                        @Override
                        public void onConnected(SessionConfig session) {
                            if (request == generation.get()) {
                                String message = "已连接 " + node.name();
                                publishState(VpnRuntimeState.CONNECTED, message, node.id());
                                updateNotification(message);
                            }
                        }
                    }
            );
            if (request != generation.get()) {
                next.stop();
                return;
            }
            connection = next;
            if (request != generation.get()) {
                next.stop();
                connection = null;
                return;
            }
            try {
                next.run();
                if (request == generation.get()) {
                    publishState(VpnRuntimeState.DISCONNECTED, "未连接", null);
                }
            } catch (Throwable failure) {
                if (request == generation.get()) {
                    publishState(VpnRuntimeState.ERROR, userMessage(failure), node.id());
                }
            } finally {
                if (connection == next) {
                    connection = null;
                }
                if (request == generation.get()) {
                    stopForeground(STOP_FOREGROUND_REMOVE);
                    stopSelfResult(startId);
                }
            }
        });
    }

    private void requestDisconnect() {
        int request = generation.incrementAndGet();
        PyVpnConnection active = connection;
        if (active != null) {
            publishState(VpnRuntimeState.STOPPING, "正在断开", requestedNodeId);
            active.stop();
        }
        lifecycleExecutor.execute(() -> {
            if (request == generation.get()) {
                requestedNodeId = null;
                publishState(VpnRuntimeState.DISCONNECTED, "未连接", null);
                stopForeground(STOP_FOREGROUND_REMOVE);
                stopSelf();
            }
        });
    }

    ParcelFileDescriptor establishTunnel(NodeProfile node, SessionConfig session) {
        Builder builder = new Builder()
                .setSession("pyvpn · " + node.name())
                .setMtu(session.mtu())
                .addAddress(session.clientVip(), 32)
                .addRoute("0.0.0.0", 0)
                .addDnsServer(session.dns())
                .setBlocking(true);
        return builder.establish();
    }

    @Override
    public void onRevoke() {
        requestDisconnect();
        super.onRevoke();
    }

    @Override
    public void onDestroy() {
        generation.incrementAndGet();
        PyVpnConnection active = connection;
        if (active != null) {
            active.stop();
        }
        lifecycleExecutor.shutdownNow();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return super.onBind(intent);
    }

    private String clientId() {
        SharedPreferences preferences = getSharedPreferences(
                CLIENT_PREFERENCES,
                Context.MODE_PRIVATE
        );
        String existing = preferences.getString(CLIENT_ID_KEY, null);
        if (existing != null && !existing.isEmpty()) {
            return existing;
        }
        String created = UUID.randomUUID().toString();
        preferences.edit().putString(CLIENT_ID_KEY, created).apply();
        return created;
    }

    private void createNotificationChannel() {
        NotificationManager manager = getSystemService(NotificationManager.class);
        NotificationChannel channel = new NotificationChannel(
                CHANNEL_ID,
                getString(R.string.notification_channel),
                NotificationManager.IMPORTANCE_LOW
        );
        channel.setDescription("pyvpn VPN connection status");
        manager.createNotificationChannel(channel);
    }

    private void startForegroundNotification(String message) {
        Notification notification = buildNotification(message);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            startForeground(
                    NOTIFICATION_ID,
                    notification,
                    ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
            );
        } else {
            startForeground(NOTIFICATION_ID, notification);
        }
    }

    private void updateNotification(String message) {
        NotificationManager manager = getSystemService(NotificationManager.class);
        manager.notify(NOTIFICATION_ID, buildNotification(message));
    }

    private Notification buildNotification(String message) {
        PendingIntent openApp = PendingIntent.getActivity(
                this,
                0,
                new Intent(this, MainActivity.class),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
        PendingIntent disconnect = PendingIntent.getService(
                this,
                1,
                disconnectIntent(this),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE
        );
        Notification.Action disconnectAction = new Notification.Action.Builder(
                Icon.createWithResource(this, R.drawable.ic_vpn_notification),
                getString(R.string.notification_disconnect),
                disconnect
        ).build();
        return new Notification.Builder(this, CHANNEL_ID)
                .setSmallIcon(R.drawable.ic_vpn_notification)
                .setContentTitle("pyvpn")
                .setContentText(message)
                .setContentIntent(openApp)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setCategory(Notification.CATEGORY_SERVICE)
                .addAction(disconnectAction)
                .build();
    }

    private void publishState(String state, String message, String nodeId) {
        VpnRuntimeState.write(this, state, message, nodeId);
    }

    private static String userMessage(Throwable failure) {
        Throwable cause = failure;
        while (cause.getCause() != null && !(cause instanceof PyVpnProtocolException)) {
            cause = cause.getCause();
        }
        String detail = cause.getMessage();
        if (cause instanceof PyVpnProtocolException && detail != null && !detail.isEmpty()) {
            return detail;
        }
        if (cause instanceof UnknownHostException) {
            return "无法解析服务器地址";
        }
        if (cause instanceof ConnectException) {
            return "无法连接服务器，请检查 IP、端口和防火墙";
        }
        if (cause instanceof SocketTimeoutException) {
            return "连接服务器超时，请检查网络和防火墙";
        }
        if (cause instanceof SSLException) {
            return "TLS 控制连接失败：" + safeDetail(detail);
        }
        if (cause instanceof SecurityException) {
            return "Android 拒绝创建 VPN：" + safeDetail(detail);
        }
        return "VPN 连接失败：" + safeDetail(detail);
    }

    private static String safeDetail(String detail) {
        return detail == null || detail.trim().isEmpty() ? "未知错误" : detail;
    }
}
