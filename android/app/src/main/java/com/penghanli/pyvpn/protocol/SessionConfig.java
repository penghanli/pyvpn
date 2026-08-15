package com.penghanli.pyvpn.protocol;

import java.math.BigInteger;
import java.util.List;
import java.util.Map;

public final class SessionConfig {
    private static final BigInteger MAX_UNSIGNED_LONG = BigInteger.ONE.shiftLeft(64).subtract(BigInteger.ONE);
    private static final BigInteger MIN_INT = BigInteger.valueOf(Integer.MIN_VALUE);
    private static final BigInteger MAX_INT = BigInteger.valueOf(Integer.MAX_VALUE);

    private final long sessionId;
    private final String clientVip;
    private final String serverVip;
    private final String dns;
    private final int mtu;
    private final String udpHost;
    private final int udpPort;
    private final TunnelCipher clientToServerCipher;
    private final TunnelCipher serverToClientCipher;

    private SessionConfig(
            long sessionId,
            String clientVip,
            String serverVip,
            String dns,
            int mtu,
            String udpHost,
            int udpPort,
            TunnelCipher clientToServerCipher,
            TunnelCipher serverToClientCipher
    ) {
        this.sessionId = sessionId;
        this.clientVip = clientVip;
        this.serverVip = serverVip;
        this.dns = dns;
        this.mtu = mtu;
        this.udpHost = udpHost;
        this.udpPort = udpPort;
        this.clientToServerCipher = clientToServerCipher;
        this.serverToClientCipher = serverToClientCipher;
    }

    public static SessionConfig fromAccept(Map<String, Object> message, String fallbackHost)
            throws PyVpnProtocolException {
        if (!"accept".equals(message.get("type")) || integer(message, "version") != 1) {
            throw new PyVpnProtocolException("server did not send an accept frame");
        }
        BigInteger sessionValue = bigInteger(message, "session_id");
        if (sessionValue.signum() < 0 || sessionValue.compareTo(MAX_UNSIGNED_LONG) > 0) {
            throw new PyVpnProtocolException("invalid session id");
        }

        String clientVip = string(message, "client_vip").split("/", 2)[0];
        String serverVip = string(message, "server_vip");
        List<Object> dnsValues = list(message, "dns");
        if (dnsValues.isEmpty() || !(dnsValues.get(0) instanceof String dns)) {
            throw new PyVpnProtocolException("accept frame did not include DNS");
        }
        int mtu = message.containsKey("mtu") ? integer(message, "mtu") : 1280;
        if (mtu < 576 || mtu > 9000) {
            throw new PyVpnProtocolException("invalid tunnel MTU");
        }

        Map<String, Object> endpoint = map(message, "udp_endpoint");
        Object hostValue = endpoint.get("host");
        String udpHost = hostValue instanceof String ? ((String) hostValue).trim() : fallbackHost;
        if (udpHost.isEmpty() || "0.0.0.0".equals(udpHost) || "::".equals(udpHost)) {
            udpHost = fallbackHost;
        }
        int udpPort = integer(endpoint, "port");
        if (udpPort < 1 || udpPort > 65535) {
            throw new PyVpnProtocolException("invalid UDP endpoint port");
        }

        Map<String, Object> crypto = map(message, "crypto");
        if (!"chacha20-poly1305".equals(crypto.get("aead"))) {
            throw new PyVpnProtocolException("unsupported tunnel AEAD");
        }
        DirectionKey clientToServer = DirectionKey.fromMap(map(crypto, "c2s"));
        DirectionKey serverToClient = DirectionKey.fromMap(map(crypto, "s2c"));

        Ipv4Packet.parseAddress(clientVip);
        Ipv4Packet.parseAddress(serverVip);
        Ipv4Packet.parseAddress(dns);

        return new SessionConfig(
                sessionValue.longValue(),
                clientVip,
                serverVip,
                dns,
                mtu,
                udpHost,
                udpPort,
                new TunnelCipher(clientToServer),
                new TunnelCipher(serverToClient)
        );
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> map(Map<String, Object> value, String key)
            throws PyVpnProtocolException {
        Object result = value.get(key);
        if (!(result instanceof Map<?, ?>)) {
            throw new PyVpnProtocolException("invalid object in accept frame: " + key);
        }
        return (Map<String, Object>) result;
    }

    @SuppressWarnings("unchecked")
    private static List<Object> list(Map<String, Object> value, String key)
            throws PyVpnProtocolException {
        Object result = value.get(key);
        if (!(result instanceof List<?>)) {
            throw new PyVpnProtocolException("invalid list in accept frame: " + key);
        }
        return (List<Object>) result;
    }

    private static String string(Map<String, Object> value, String key)
            throws PyVpnProtocolException {
        Object result = value.get(key);
        if (!(result instanceof String text) || text.trim().isEmpty()) {
            throw new PyVpnProtocolException("invalid string in accept frame: " + key);
        }
        return text;
    }

    private static int integer(Map<String, Object> value, String key)
            throws PyVpnProtocolException {
        BigInteger result = bigInteger(value, key);
        if (result.compareTo(MIN_INT) < 0 || result.compareTo(MAX_INT) > 0) {
            throw new PyVpnProtocolException("integer is out of range in accept frame: " + key);
        }
        return result.intValue();
    }

    private static BigInteger bigInteger(Map<String, Object> value, String key)
            throws PyVpnProtocolException {
        Object result = value.get(key);
        if (result instanceof BigInteger integer) {
            return integer;
        }
        if (result instanceof Byte || result instanceof Short
                || result instanceof Integer || result instanceof Long) {
            return BigInteger.valueOf(((Number) result).longValue());
        }
        throw new PyVpnProtocolException("invalid integer in accept frame: " + key);
    }

    public long sessionId() {
        return sessionId;
    }

    public String clientVip() {
        return clientVip;
    }

    public String serverVip() {
        return serverVip;
    }

    public String dns() {
        return dns;
    }

    public int mtu() {
        return mtu;
    }

    public String udpHost() {
        return udpHost;
    }

    public int udpPort() {
        return udpPort;
    }

    public TunnelCipher clientToServerCipher() {
        return clientToServerCipher;
    }

    public TunnelCipher serverToClientCipher() {
        return serverToClientCipher;
    }
}
