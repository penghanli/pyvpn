package com.penghanli.pyvpn.protocol;

import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.UnknownHostException;
import java.util.Arrays;

public final class Ipv4Packet {
    private Ipv4Packet() {}

    public static Info inspect(byte[] packet, int receivedLength) throws PyVpnProtocolException {
        if (receivedLength < 20 || receivedLength > packet.length) {
            throw new PyVpnProtocolException("truncated IPv4 packet");
        }
        int version = (packet[0] >>> 4) & 0x0f;
        int headerLength = (packet[0] & 0x0f) * 4;
        if (version != 4 || headerLength < 20 || headerLength > receivedLength) {
            throw new PyVpnProtocolException("invalid IPv4 header");
        }
        int totalLength = ((packet[2] & 0xff) << 8) | (packet[3] & 0xff);
        if (totalLength < headerLength || totalLength > receivedLength) {
            throw new PyVpnProtocolException("invalid IPv4 packet length");
        }
        return new Info(addressAt(packet, 12), addressAt(packet, 16), totalLength);
    }

    public static int parseAddress(String value) throws PyVpnProtocolException {
        try {
            InetAddress address = InetAddress.getByName(value);
            if (!(address instanceof Inet4Address)) {
                throw new PyVpnProtocolException("pyvpn requires an IPv4 address");
            }
            byte[] bytes = address.getAddress();
            return ((bytes[0] & 0xff) << 24)
                    | ((bytes[1] & 0xff) << 16)
                    | ((bytes[2] & 0xff) << 8)
                    | (bytes[3] & 0xff);
        } catch (UnknownHostException exception) {
            throw new PyVpnProtocolException("invalid IPv4 address: " + value, exception);
        }
    }

    public static byte[] exactPacket(byte[] packet, int totalLength) {
        return packet.length == totalLength ? packet : Arrays.copyOf(packet, totalLength);
    }

    private static int addressAt(byte[] packet, int offset) {
        return ((packet[offset] & 0xff) << 24)
                | ((packet[offset + 1] & 0xff) << 16)
                | ((packet[offset + 2] & 0xff) << 8)
                | (packet[offset + 3] & 0xff);
    }

    public static final class Info {
        private final int source;
        private final int destination;
        private final int totalLength;

        private Info(int source, int destination, int totalLength) {
            this.source = source;
            this.destination = destination;
            this.totalLength = totalLength;
        }

        public int source() {
            return source;
        }

        public int destination() {
            return destination;
        }

        public int totalLength() {
            return totalLength;
        }
    }
}
