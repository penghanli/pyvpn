package com.penghanli.pyvpn;

import android.Manifest;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.net.VpnService;
import android.os.Build;
import android.os.Bundle;
import android.text.method.HideReturnsTransformationMethod;
import android.text.method.PasswordTransformationMethod;
import android.view.View;
import android.widget.AdapterView;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;
import java.util.ArrayList;
import java.util.List;

public final class MainActivity extends Activity {
    private static final int REQUEST_VPN_PERMISSION = 100;
    private static final int REQUEST_NOTIFICATION_PERMISSION = 101;

    private NodeStore nodeStore;
    private Spinner nodeSpinner;
    private TextView endpointText;
    private TextView statusText;
    private Button connectButton;
    private Button editButton;
    private Button deleteButton;
    private List<NodeProfile> nodes = new ArrayList<>();
    private String pendingNodeId;
    private boolean receiverRegistered;

    private final BroadcastReceiver stateReceiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            updateRuntimeState();
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        nodeStore = new NodeStore(this);
        nodeSpinner = findViewById(R.id.nodeSpinner);
        endpointText = findViewById(R.id.endpointText);
        statusText = findViewById(R.id.statusText);
        connectButton = findViewById(R.id.connectButton);
        Button addButton = findViewById(R.id.addButton);
        editButton = findViewById(R.id.editButton);
        deleteButton = findViewById(R.id.deleteButton);

        nodeSpinner.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
            @Override
            public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                if (position < 0 || position >= nodes.size()) {
                    return;
                }
                NodeProfile selected = nodes.get(position);
                try {
                    NodeProfile active = nodeStore.active();
                    if (active == null || !active.id().equals(selected.id())) {
                        nodeStore.setActive(selected.id());
                    }
                    endpointText.setText(selected.endpoint());
                    updateRuntimeState();
                } catch (RuntimeException exception) {
                    showStorageError(exception);
                }
            }

            @Override
            public void onNothingSelected(AdapterView<?> parent) {
                endpointText.setText(R.string.no_nodes);
            }
        });

        connectButton.setOnClickListener(view -> handleConnectButton());
        addButton.setOnClickListener(view -> showNodeDialog(null));
        editButton.setOnClickListener(view -> {
            NodeProfile selected = selectedNode();
            if (selected != null) {
                showNodeDialog(selected);
            }
        });
        deleteButton.setOnClickListener(view -> confirmDeleteSelected());

        requestNotificationPermission();
        refreshNodes();
        updateRuntimeState();
    }

    @Override
    @SuppressLint("UnspecifiedRegisterReceiverFlag")
    protected void onStart() {
        super.onStart();
        IntentFilter filter = new IntentFilter(VpnRuntimeState.ACTION_CHANGED);
        // The signature permission protects this overload on every supported API level.
        registerReceiver(
                stateReceiver,
                filter,
                VpnRuntimeState.INTERNAL_PERMISSION,
                null
        );
        receiverRegistered = true;
    }

    @Override
    protected void onResume() {
        super.onResume();
        refreshNodes();
        updateRuntimeState();
    }

    @Override
    protected void onStop() {
        if (receiverRegistered) {
            unregisterReceiver(stateReceiver);
            receiverRegistered = false;
        }
        super.onStop();
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != REQUEST_VPN_PERMISSION) {
            return;
        }
        if (resultCode == RESULT_OK && pendingNodeId != null) {
            startVpn(pendingNodeId);
        } else if (resultCode != RESULT_OK) {
            Toast.makeText(this, "需要允许 Android VPN 连接", Toast.LENGTH_LONG).show();
        }
        pendingNodeId = null;
    }

    private void handleConnectButton() {
        VpnRuntimeState.Snapshot runtime = VpnRuntimeState.read(this);
        if (VpnRuntimeState.CONNECTING.equals(runtime.state())
                || VpnRuntimeState.STOPPING.equals(runtime.state())) {
            startService(PyVpnService.disconnectIntent(this));
            return;
        }

        NodeProfile selected = selectedNode();
        if (selected == null) {
            showNodeDialog(null);
            return;
        }
        if (VpnRuntimeState.CONNECTED.equals(runtime.state())
                && selected.id().equals(runtime.nodeId())) {
            startService(PyVpnService.disconnectIntent(this));
            return;
        }

        pendingNodeId = selected.id();
        Intent permissionIntent = VpnService.prepare(this);
        if (permissionIntent == null) {
            startVpn(selected.id());
            pendingNodeId = null;
        } else {
            startActivityForResult(permissionIntent, REQUEST_VPN_PERMISSION);
        }
    }

    private void startVpn(String nodeId) {
        Intent intent = PyVpnService.connectIntent(this, nodeId);
        startForegroundService(intent);
    }

    private void refreshNodes() {
        try {
            NodeProfile active = nodeStore.active();
            nodes = nodeStore.list();
            ArrayAdapter<NodeProfile> adapter = new ArrayAdapter<>(
                    this,
                    android.R.layout.simple_spinner_item,
                    nodes
            );
            adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
            nodeSpinner.setAdapter(adapter);

            int selectedIndex = 0;
            if (active != null) {
                for (int index = 0; index < nodes.size(); index++) {
                    if (nodes.get(index).id().equals(active.id())) {
                        selectedIndex = index;
                        break;
                    }
                }
            }
            if (!nodes.isEmpty()) {
                nodeSpinner.setSelection(selectedIndex, false);
                endpointText.setText(nodes.get(selectedIndex).endpoint());
            } else {
                endpointText.setText(R.string.no_nodes);
            }
            boolean hasNode = !nodes.isEmpty();
            connectButton.setEnabled(hasNode);
            editButton.setEnabled(hasNode);
            deleteButton.setEnabled(hasNode);
        } catch (RuntimeException exception) {
            showStorageError(exception);
        }
    }

    private void updateRuntimeState() {
        VpnRuntimeState.Snapshot runtime = VpnRuntimeState.read(this);
        statusText.setText(runtime.message());
        int color;
        if (VpnRuntimeState.CONNECTED.equals(runtime.state())) {
            color = getColor(R.color.connected);
        } else if (VpnRuntimeState.ERROR.equals(runtime.state())) {
            color = getColor(R.color.error);
        } else if (VpnRuntimeState.CONNECTING.equals(runtime.state())
                || VpnRuntimeState.STOPPING.equals(runtime.state())) {
            color = getColor(R.color.warning);
        } else {
            color = getColor(R.color.text_primary);
        }
        statusText.setTextColor(color);

        NodeProfile selected = selectedNode();
        if (selected == null) {
            connectButton.setText(R.string.connect);
            connectButton.setEnabled(false);
            return;
        }
        connectButton.setEnabled(true);
        if (VpnRuntimeState.CONNECTING.equals(runtime.state())
                || VpnRuntimeState.STOPPING.equals(runtime.state())) {
            connectButton.setText(R.string.cancel_connection);
        } else if (VpnRuntimeState.CONNECTED.equals(runtime.state())) {
            connectButton.setText(selected.id().equals(runtime.nodeId())
                    ? R.string.disconnect : R.string.switch_and_connect);
        } else {
            connectButton.setText(R.string.connect);
        }
    }

    private NodeProfile selectedNode() {
        int position = nodeSpinner == null ? -1 : nodeSpinner.getSelectedItemPosition();
        return position >= 0 && position < nodes.size() ? nodes.get(position) : null;
    }

    private void showNodeDialog(NodeProfile existing) {
        View content = getLayoutInflater().inflate(R.layout.dialog_node, null);
        EditText nameInput = content.findViewById(R.id.nodeNameInput);
        EditText hostInput = content.findViewById(R.id.serverHostInput);
        EditText portInput = content.findViewById(R.id.controlPortInput);
        EditText tokenInput = content.findViewById(R.id.tokenInput);
        EditText fingerprintInput = content.findViewById(R.id.fingerprintInput);
        CheckBox showToken = content.findViewById(R.id.showTokenCheck);

        tokenInput.setTransformationMethod(PasswordTransformationMethod.getInstance());
        showToken.setOnCheckedChangeListener((button, checked) -> {
            tokenInput.setTransformationMethod(checked
                    ? HideReturnsTransformationMethod.getInstance()
                    : PasswordTransformationMethod.getInstance());
            tokenInput.setSelection(tokenInput.length());
        });

        if (existing != null) {
            nameInput.setText(existing.name());
            hostInput.setText(existing.serverHost());
            portInput.setText(String.valueOf(existing.controlPort()));
            tokenInput.setText(existing.token());
            fingerprintInput.setText(existing.certificateFingerprint());
        }

        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle(existing == null ? R.string.add_node : R.string.edit_node)
                .setView(content)
                .setNegativeButton(R.string.cancel, null)
                .setPositiveButton(R.string.save, null)
                .create();
        dialog.setOnShowListener(ignored -> dialog.getButton(AlertDialog.BUTTON_POSITIVE)
                .setOnClickListener(view -> {
                    try {
                        int port = Integer.parseInt(portInput.getText().toString().trim());
                        NodeProfile profile = existing == null
                                ? NodeProfile.create(
                                        nameInput.getText().toString(),
                                        hostInput.getText().toString(),
                                        port,
                                        tokenInput.getText().toString(),
                                        fingerprintInput.getText().toString())
                                : new NodeProfile(
                                        existing.id(),
                                        nameInput.getText().toString(),
                                        hostInput.getText().toString(),
                                        port,
                                        tokenInput.getText().toString(),
                                        fingerprintInput.getText().toString());
                        nodeStore.save(profile, true);
                        dialog.dismiss();
                        refreshNodes();
                        updateRuntimeState();
                    } catch (NumberFormatException exception) {
                        portInput.setError("请输入有效端口");
                    } catch (IllegalArgumentException | IllegalStateException exception) {
                        Toast.makeText(this, exception.getMessage(), Toast.LENGTH_LONG).show();
                    }
                }));
        dialog.show();
    }

    private void confirmDeleteSelected() {
        NodeProfile selected = selectedNode();
        if (selected == null) {
            return;
        }
        new AlertDialog.Builder(this)
                .setMessage(getString(R.string.confirm_delete, selected.name()))
                .setNegativeButton(R.string.cancel, null)
                .setPositiveButton(R.string.delete_node, (dialog, which) -> {
                    VpnRuntimeState.Snapshot runtime = VpnRuntimeState.read(this);
                    if (selected.id().equals(runtime.nodeId())
                            && !VpnRuntimeState.DISCONNECTED.equals(runtime.state())) {
                        startService(PyVpnService.disconnectIntent(this));
                    }
                    try {
                        nodeStore.delete(selected.id());
                        refreshNodes();
                        updateRuntimeState();
                    } catch (RuntimeException exception) {
                        showStorageError(exception);
                    }
                })
                .show();
    }

    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(
                    new String[]{Manifest.permission.POST_NOTIFICATIONS},
                    REQUEST_NOTIFICATION_PERMISSION
            );
        }
    }

    private void showStorageError(RuntimeException exception) {
        statusText.setText(exception.getMessage());
        statusText.setTextColor(getColor(R.color.error));
        connectButton.setEnabled(false);
        editButton.setEnabled(false);
        deleteButton.setEnabled(false);
    }
}
