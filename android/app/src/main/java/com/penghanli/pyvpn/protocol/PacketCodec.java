package com.penghanli.pyvpn.protocol;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.Arrays;

public final class PacketCodec {
    public static final int DATA_VERSION = 1;
    public static final int TYPE_DATA = 1;
    public static final int TYPE_KEEPALIVE = 2;
    public static final int HEADER_SIZE = 22;
    private static final byte[] MAGIC = {'P', 'Y', 'V', 'N'};

    private PacketCodec() {}

    public static byte[] seal(
            int packetType,
            long sessionId,
            long sequence,
            byte[] plaintext,
            TunnelCipher cipher
    ) throws PyVpnProtocolException {
        byte[] header = encodeHeader(packetType, sessionId, sequence);
        byte[] ciphertext = cipher.encrypt(sequence, plaintext, header);
        byte[] result = Arrays.copyOf(header, header.length + ciphertext.length);
        System.arraycopy(ciphertext, 0, result, header.length, ciphertext.length);
        return result;
    }

    public static OpenedPacket open(byte[] packet, TunnelCipher cipher)
            throws PyVpnProtocolException {
        Header header = parseHeader(packet);
        byte[] headerBytes = Arrays.copyOf(packet, HEADER_SIZE);
        byte[] ciphertext = Arrays.copyOfRange(packet, HEADER_SIZE, packet.length);
        byte[] plaintext = cipher.decrypt(header.sequence(), ciphertext, headerBytes);
        return new OpenedPacket(header, plaintext);
    }

    public static Header parseHeader(byte[] packet) throws PyVpnProtocolException {
        if (packet.length < HEADER_SIZE) {
            throw new PyVpnProtocolException("truncated tunnel packet");
        }
        for (int index = 0; index < MAGIC.length; index++) {
            if (packet[index] != MAGIC[index]) {
                throw new PyVpnProtocolException("invalid tunnel packet magic");
            }
        }
        int version = packet[4] & 0xff;
        int packetType = packet[5] & 0xff;
        if (version != DATA_VERSION) {
            throw new PyVpnProtocolException("unsupported tunnel packet version");
        }
        requirePacketType(packetType);
        ByteBuffer values = ByteBuffer.wrap(packet, 6, 16).order(ByteOrder.BIG_ENDIAN);
        long sessionId = values.getLong();
        long sequence = values.getLong();
        if (sequence <= 0) {
            throw new PyVpnProtocolException("invalid packet sequence number");
        }
        return new Header(version, packetType, sessionId, sequence);
    }

    private static byte[] encodeHeader(int packetType, long sessionId, long sequence)
            throws PyVpnProtocolException {
        requirePacketType(packetType);
        if (sequence <= 0) {
            throw new PyVpnProtocolException("invalid packet sequence number");
        }
        ByteBuffer result = ByteBuffer.allocate(HEADER_SIZE).order(ByteOrder.BIG_ENDIAN);
        result.put(MAGIC);
        result.put((byte) DATA_VERSION);
        result.put((byte) packetType);
        result.putLong(sessionId);
        result.putLong(sequence);
        return result.array();
    }

    private static void requirePacketType(int packetType) throws PyVpnProtocolException {
        if (packetType != TYPE_DATA && packetType != TYPE_KEEPALIVE) {
            throw new PyVpnProtocolException("invalid tunnel packet type");
        }
    }

    public static final class Header {
        private final int version;
        private final int packetType;
        private final long sessionId;
        private final long sequence;

        private Header(int version, int packetType, long sessionId, long sequence) {
            this.version = version;
            this.packetType = packetType;
            this.sessionId = sessionId;
            this.sequence = sequence;
        }

        public int version() {
            return version;
        }

        public int packetType() {
            return packetType;
        }

        public long sessionId() {
            return sessionId;
        }

        public long sequence() {
            return sequence;
        }
    }

    public static final class OpenedPacket {
        private final Header header;
        private final byte[] plaintext;

        private OpenedPacket(Header header, byte[] plaintext) {
            this.header = header;
            this.plaintext = plaintext;
        }

        public Header header() {
            return header;
        }

        public byte[] plaintext() {
            return plaintext;
        }
    }
}
