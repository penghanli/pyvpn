package com.penghanli.pyvpn;

import java.math.BigInteger;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.regex.Pattern;

public final class NodeProfile {
    private static final Pattern FINGERPRINT = Pattern.compile("[0-9a-f]{64}");
    private static final BigInteger MIN_INT = BigInteger.valueOf(Integer.MIN_VALUE);
    private static final BigInteger MAX_INT = BigInteger.valueOf(Integer.MAX_VALUE);

    private final String id;
    private final String name;
    private final String serverHost;
    private final int controlPort;
    private final String token;
    private final String certificateFingerprint;

    public NodeProfile(
            String id,
            String name,
            String serverHost,
            int controlPort,
            String token,
            String certificateFingerprint
    ) {
        this.id = requireId(id);
        this.serverHost = normalizeHost(serverHost);
        this.name = normalizeName(name, this.serverHost);
        if (controlPort < 1 || controlPort > 65535) {
            throw new IllegalArgumentException("控制端口必须在 1 到 65535 之间");
        }
        this.controlPort = controlPort;
        this.token = normalizeToken(token);
        this.certificateFingerprint = normalizeFingerprint(certificateFingerprint);
    }

    public static NodeProfile create(
            String name,
            String serverHost,
            int controlPort,
            String token,
            String certificateFingerprint
    ) {
        return new NodeProfile(
                UUID.randomUUID().toString(),
                name,
                serverHost,
                controlPort,
                token,
                certificateFingerprint
        );
    }

    public static NodeProfile fromMap(Map<String, Object> value) {
        return new NodeProfile(
                string(value, "id"),
                string(value, "name"),
                string(value, "server_host"),
                integer(value, "control_port"),
                string(value, "token"),
                string(value, "cert_fingerprint")
        );
    }

    public Map<String, Object> toMap() {
        LinkedHashMap<String, Object> result = new LinkedHashMap<>();
        result.put("id", id);
        result.put("name", name);
        result.put("server_host", serverHost);
        result.put("control_port", controlPort);
        result.put("token", token);
        result.put("cert_fingerprint", certificateFingerprint);
        return result;
    }

    private static String requireId(String value) {
        String normalized = value == null ? "" : value.trim();
        if (normalized.isEmpty() || normalized.length() > 80) {
            throw new IllegalArgumentException("节点 ID 无效");
        }
        return normalized;
    }

    private static String normalizeName(String value, String fallback) {
        String normalized = value == null ? "" : value.trim();
        if (normalized.isEmpty()) {
            normalized = fallback;
        }
        if (normalized.length() > 80 || containsControlCharacter(normalized)) {
            throw new IllegalArgumentException("节点名称无效");
        }
        return normalized;
    }

    private static String normalizeHost(String value) {
        String normalized = value == null ? "" : value.trim();
        if (normalized.isEmpty()
                || normalized.length() > 253
                || normalized.contains("://")
                || normalized.contains("/")
                || normalized.contains("\\")
                || normalized.chars().anyMatch(Character::isWhitespace)
                || containsControlCharacter(normalized)) {
            throw new IllegalArgumentException("请输入有效的服务器 IP 或域名");
        }
        return normalized;
    }

    public static String normalizeToken(String value) {
        String normalized = value == null ? "" : value.trim();
        if (normalized.regionMatches(true, 0, "PYVPN_TOKEN=", 0, "PYVPN_TOKEN=".length())) {
            normalized = normalized.substring("PYVPN_TOKEN=".length()).trim();
        }
        if (normalized.length() >= 2) {
            char first = normalized.charAt(0);
            char last = normalized.charAt(normalized.length() - 1);
            if ((first == '\'' && last == '\'') || (first == '"' && last == '"')) {
                normalized = normalized.substring(1, normalized.length() - 1).trim();
            }
        }
        if (normalized.isEmpty() || normalized.length() > 4096 || containsControlCharacter(normalized)) {
            throw new IllegalArgumentException("Token 不能为空，且不能包含控制字符");
        }
        return normalized;
    }

    public static String normalizeFingerprint(String value) {
        String normalized = value == null ? "" : value.trim().toLowerCase(Locale.ROOT);
        if (normalized.startsWith("sha256:")) {
            normalized = normalized.substring("sha256:".length());
        }
        normalized = normalized.replace(":", "").replace(" ", "");
        if (!FINGERPRINT.matcher(normalized).matches()) {
            throw new IllegalArgumentException("证书指纹必须是 sha256: 后跟 64 位十六进制字符");
        }
        return "sha256:" + normalized;
    }

    private static boolean containsControlCharacter(String value) {
        return value.chars().anyMatch(character -> Character.isISOControl(character));
    }

    private static String string(Map<String, Object> value, String key) {
        Object result = value.get(key);
        if (!(result instanceof String text)) {
            throw new IllegalArgumentException("节点配置缺少字段: " + key);
        }
        return text;
    }

    private static int integer(Map<String, Object> value, String key) {
        Object result = value.get(key);
        if (result instanceof BigInteger integer) {
            if (integer.compareTo(MIN_INT) < 0 || integer.compareTo(MAX_INT) > 0) {
                throw new IllegalArgumentException("节点配置字段无效: " + key);
            }
            return integer.intValue();
        }
        if (result instanceof Byte || result instanceof Short
                || result instanceof Integer || result instanceof Long) {
            long number = ((Number) result).longValue();
            if (number >= Integer.MIN_VALUE && number <= Integer.MAX_VALUE) {
                return (int) number;
            }
        }
        throw new IllegalArgumentException("节点配置字段无效: " + key);
    }

    public String id() {
        return id;
    }

    public String name() {
        return name;
    }

    public String serverHost() {
        return serverHost;
    }

    public int controlPort() {
        return controlPort;
    }

    public String token() {
        return token;
    }

    public String certificateFingerprint() {
        return certificateFingerprint;
    }

    public String endpoint() {
        return serverHost + ":" + controlPort;
    }

    @Override
    public String toString() {
        return name;
    }
}
