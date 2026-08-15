package com.penghanli.pyvpn;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import com.penghanli.pyvpn.protocol.MiniJson;
import com.penghanli.pyvpn.protocol.PyVpnProtocolException;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.KeyStore;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

public final class NodeStore {
    private static final String PREFERENCES = "pyvpn_profiles";
    private static final String PAYLOAD_KEY = "encrypted_payload";
    private static final String KEY_ALIAS = "pyvpn-profile-key-v1";
    private static final byte FORMAT_VERSION = 1;

    private final SharedPreferences preferences;

    public NodeStore(Context context) {
        preferences = context.getApplicationContext()
                .getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE);
    }

    public synchronized List<NodeProfile> list() {
        return new ArrayList<>(load().nodes);
    }

    public synchronized NodeProfile active() {
        StoreData data = load();
        if (data.activeNodeId == null) {
            return null;
        }
        return find(data.nodes, data.activeNodeId);
    }

    public synchronized NodeProfile get(String nodeId) {
        return find(load().nodes, nodeId);
    }

    public synchronized void save(NodeProfile profile, boolean makeActive) {
        StoreData data = load();
        ArrayList<NodeProfile> nodes = new ArrayList<>(data.nodes);
        int existingIndex = indexOf(nodes, profile.id());
        if (existingIndex >= 0) {
            nodes.set(existingIndex, profile);
        } else {
            nodes.add(profile);
        }
        String activeId = data.activeNodeId;
        if (activeId == null || makeActive) {
            activeId = profile.id();
        }
        write(new StoreData(activeId, nodes));
    }

    public synchronized void setActive(String nodeId) {
        StoreData data = load();
        if (find(data.nodes, nodeId) == null) {
            throw new IllegalArgumentException("节点不存在");
        }
        write(new StoreData(nodeId, data.nodes));
    }

    public synchronized void delete(String nodeId) {
        StoreData data = load();
        ArrayList<NodeProfile> nodes = new ArrayList<>(data.nodes);
        int index = indexOf(nodes, nodeId);
        if (index < 0) {
            return;
        }
        nodes.remove(index);
        String activeId = data.activeNodeId;
        if (nodeId.equals(activeId)) {
            activeId = nodes.isEmpty() ? null : nodes.get(0).id();
        }
        write(new StoreData(activeId, nodes));
    }

    private StoreData load() {
        String encrypted = preferences.getString(PAYLOAD_KEY, null);
        if (encrypted == null || encrypted.isEmpty()) {
            return new StoreData(null, Collections.emptyList());
        }
        try {
            byte[] plaintext = decrypt(Base64.getDecoder().decode(encrypted));
            Map<String, Object> root = MiniJson.parseObject(
                    new String(plaintext, StandardCharsets.UTF_8));
            Object version = root.get("version");
            if (!(version instanceof Number) || ((Number) version).intValue() != 1) {
                throw new IllegalArgumentException("不支持的节点配置版本");
            }
            String activeId = root.get("active_node_id") instanceof String
                    ? (String) root.get("active_node_id") : null;
            Object rawNodes = root.get("nodes");
            if (!(rawNodes instanceof List<?> values)) {
                throw new IllegalArgumentException("节点配置格式无效");
            }
            ArrayList<NodeProfile> nodes = new ArrayList<>();
            for (Object value : values) {
                if (!(value instanceof Map<?, ?> map)) {
                    throw new IllegalArgumentException("节点配置格式无效");
                }
                nodes.add(NodeProfile.fromMap(castMap(map)));
            }
            if (activeId != null && find(nodes, activeId) == null) {
                activeId = nodes.isEmpty() ? null : nodes.get(0).id();
            }
            return new StoreData(activeId, nodes);
        } catch (GeneralSecurityException | PyVpnProtocolException | IllegalArgumentException exception) {
            throw new IllegalStateException("无法读取节点配置，请清除应用数据后重新添加节点", exception);
        }
    }

    private void write(StoreData data) {
        LinkedHashMap<String, Object> root = new LinkedHashMap<>();
        root.put("version", 1);
        root.put("active_node_id", data.activeNodeId);
        ArrayList<Object> nodes = new ArrayList<>();
        for (NodeProfile profile : data.nodes) {
            nodes.add(profile.toMap());
        }
        root.put("nodes", nodes);
        try {
            byte[] plaintext = MiniJson.stringify(root).getBytes(StandardCharsets.UTF_8);
            String encoded = Base64.getEncoder().encodeToString(encrypt(plaintext));
            if (!preferences.edit().putString(PAYLOAD_KEY, encoded).commit()) {
                throw new IllegalStateException("无法保存节点配置");
            }
        } catch (GeneralSecurityException exception) {
            throw new IllegalStateException("无法加密节点配置", exception);
        }
    }

    private byte[] encrypt(byte[] plaintext) throws GeneralSecurityException {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey());
        byte[] iv = cipher.getIV();
        byte[] ciphertext = cipher.doFinal(plaintext);
        ByteBuffer output = ByteBuffer.allocate(2 + iv.length + ciphertext.length);
        output.put(FORMAT_VERSION);
        output.put((byte) iv.length);
        output.put(iv);
        output.put(ciphertext);
        return output.array();
    }

    private byte[] decrypt(byte[] payload) throws GeneralSecurityException {
        if (payload.length < 2 || payload[0] != FORMAT_VERSION) {
            throw new GeneralSecurityException("unsupported encrypted profile format");
        }
        int ivLength = payload[1] & 0xff;
        if (ivLength < 12 || payload.length <= 2 + ivLength) {
            throw new GeneralSecurityException("invalid encrypted profile payload");
        }
        byte[] iv = new byte[ivLength];
        byte[] ciphertext = new byte[payload.length - 2 - ivLength];
        System.arraycopy(payload, 2, iv, 0, iv.length);
        System.arraycopy(payload, 2 + ivLength, ciphertext, 0, ciphertext.length);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(), new GCMParameterSpec(128, iv));
        return cipher.doFinal(ciphertext);
    }

    private SecretKey getOrCreateKey() throws GeneralSecurityException {
        KeyStore keyStore = KeyStore.getInstance("AndroidKeyStore");
        try {
            keyStore.load(null);
        } catch (java.io.IOException exception) {
            throw new GeneralSecurityException("could not load Android Keystore", exception);
        }
        if (keyStore.containsAlias(KEY_ALIAS)) {
            return (SecretKey) keyStore.getKey(KEY_ALIAS, null);
        }
        KeyGenerator generator = KeyGenerator.getInstance(
                KeyProperties.KEY_ALGORITHM_AES,
                "AndroidKeyStore"
        );
        generator.init(new KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT
        )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .setUserAuthenticationRequired(false)
                .build());
        return generator.generateKey();
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> castMap(Map<?, ?> value) {
        return (Map<String, Object>) value;
    }

    private static int indexOf(List<NodeProfile> nodes, String nodeId) {
        for (int index = 0; index < nodes.size(); index++) {
            if (nodes.get(index).id().equals(nodeId)) {
                return index;
            }
        }
        return -1;
    }

    private static NodeProfile find(List<NodeProfile> nodes, String nodeId) {
        int index = indexOf(nodes, nodeId);
        return index < 0 ? null : nodes.get(index);
    }

    private static final class StoreData {
        private final String activeNodeId;
        private final List<NodeProfile> nodes;

        private StoreData(String activeNodeId, List<NodeProfile> nodes) {
            this.activeNodeId = activeNodeId;
            this.nodes = new ArrayList<>(nodes);
        }
    }
}
