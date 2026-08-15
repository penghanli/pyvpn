package com.penghanli.pyvpn.protocol;

import java.util.Arrays;
import java.util.Base64;
import java.util.Map;

public final class DirectionKey {
    private final byte[] key;
    private final byte[] salt;

    public DirectionKey(byte[] key, byte[] salt) throws PyVpnProtocolException {
        if (key.length != 32) {
            throw new PyVpnProtocolException("invalid tunnel key length");
        }
        if (salt.length != 4) {
            throw new PyVpnProtocolException("invalid tunnel salt length");
        }
        this.key = key.clone();
        this.salt = salt.clone();
    }

    public static DirectionKey fromMap(Map<String, Object> value) throws PyVpnProtocolException {
        try {
            byte[] key = Base64.getDecoder().decode(requireString(value, "key"));
            byte[] salt = Base64.getDecoder().decode(requireString(value, "salt"));
            return new DirectionKey(key, salt);
        } catch (IllegalArgumentException exception) {
            throw new PyVpnProtocolException("invalid base64 tunnel key", exception);
        }
    }

    private static String requireString(Map<String, Object> value, String key)
            throws PyVpnProtocolException {
        Object result = value.get(key);
        if (!(result instanceof String text)) {
            throw new PyVpnProtocolException("missing tunnel key field: " + key);
        }
        return text;
    }

    public byte[] key() {
        return key.clone();
    }

    public byte[] nonce(long sequence) throws PyVpnProtocolException {
        if (sequence <= 0) {
            throw new PyVpnProtocolException("invalid packet sequence number");
        }
        byte[] nonce = Arrays.copyOf(salt, 12);
        for (int index = 0; index < 8; index++) {
            nonce[11 - index] = (byte) (sequence >>> (index * 8));
        }
        return nonce;
    }
}
