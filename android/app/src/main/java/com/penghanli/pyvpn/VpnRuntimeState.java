package com.penghanli.pyvpn;

import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;

public final class VpnRuntimeState {
    public static final String ACTION_CHANGED = "com.penghanli.pyvpn.STATE_CHANGED";
    public static final String INTERNAL_PERMISSION = "com.penghanli.pyvpn.permission.INTERNAL";
    public static final String DISCONNECTED = "disconnected";
    public static final String CONNECTING = "connecting";
    public static final String CONNECTED = "connected";
    public static final String STOPPING = "stopping";
    public static final String ERROR = "error";

    private static final String PREFERENCES = "pyvpn_runtime";
    private static final String KEY_STATE = "state";
    private static final String KEY_MESSAGE = "message";
    private static final String KEY_NODE_ID = "node_id";

    private VpnRuntimeState() {}

    public static Snapshot read(Context context) {
        SharedPreferences preferences = context.getSharedPreferences(
                PREFERENCES,
                Context.MODE_PRIVATE
        );
        return new Snapshot(
                preferences.getString(KEY_STATE, DISCONNECTED),
                preferences.getString(KEY_MESSAGE, "未连接"),
                preferences.getString(KEY_NODE_ID, null)
        );
    }

    static void write(Context context, String state, String message, String nodeId) {
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)
                .edit()
                .putString(KEY_STATE, state)
                .putString(KEY_MESSAGE, message)
                .putString(KEY_NODE_ID, nodeId)
                .apply();
        Intent changed = new Intent(ACTION_CHANGED);
        changed.setPackage(context.getPackageName());
        context.sendBroadcast(changed, INTERNAL_PERMISSION);
    }

    public static final class Snapshot {
        private final String state;
        private final String message;
        private final String nodeId;

        private Snapshot(String state, String message, String nodeId) {
            this.state = state == null ? DISCONNECTED : state;
            this.message = message == null ? "" : message;
            this.nodeId = nodeId;
        }

        public String state() {
            return state;
        }

        public String message() {
            return message;
        }

        public String nodeId() {
            return nodeId;
        }
    }
}
