package com.penghanli.pyvpn.protocol;

import java.util.Arrays;

public final class PacketCodec {
    public static final int DATA_VERSION = 1;
    public static final int TYPE_DATA = 1;
    public static final int TYPE_KEEPALIVE = 2;
    public static final int HEADER_SIZE = 22;
    public static final int TAG_SIZE = TunnelCipher.TAG_SIZE;
    private static final byte[] MAGIC = {'P', 'Y', 'V', 'N'};

    private PacketCodec() {}

    public static byte[] seal(
            int packetType,
            long sessionId,
            long sequence,
            byte[] plaintext,
            TunnelCipher cipher
    ) throws PyVpnProtocolException {
        return seal(
                packetType,
                sessionId,
                sequence,
                plaintext,
                0,
                plaintext.length,
                cipher
        );
    }

    public static byte[] seal(
            int packetType,
            long sessionId,
            long sequence,
            byte[] plaintext,
            int plaintextOffset,
            int plaintextLength,
            TunnelCipher cipher
    ) throws PyVpnProtocolException {
        requireRange(plaintext, plaintextOffset, plaintextLength);
        int resultLength = encryptedLength(plaintextLength);
        byte[] result = new byte[resultLength];
        int written = sealInto(
                packetType,
                sessionId,
                sequence,
                plaintext,
                plaintextOffset,
                plaintextLength,
                cipher,
                result,
                0
        );
        if (written != result.length) {
            throw new PyVpnProtocolException("unexpected encrypted packet length");
        }
        return result;
    }

    public static int sealInto(
            int packetType,
            long sessionId,
            long sequence,
            byte[] plaintext,
            int plaintextOffset,
            int plaintextLength,
            TunnelCipher cipher,
            byte[] output,
            int outputOffset
    ) throws PyVpnProtocolException {
        requireRange(plaintext, plaintextOffset, plaintextLength);
        int resultLength = encryptedLength(plaintextLength);
        requireRange(output, outputOffset, resultLength);
        encodeHeader(packetType, sessionId, sequence, output, outputOffset);
        int written = cipher.encryptInto(
                sequence,
                plaintext,
                plaintextOffset,
                plaintextLength,
                output,
                outputOffset,
                HEADER_SIZE,
                output,
                outputOffset + HEADER_SIZE
        );
        if (written != plaintextLength + TAG_SIZE) {
            throw new PyVpnProtocolException("unexpected encrypted packet length");
        }
        return HEADER_SIZE + written;
    }

    public static OpenedPacket open(byte[] packet, TunnelCipher cipher)
            throws PyVpnProtocolException {
        return open(packet, 0, packet.length, cipher);
    }

    public static OpenedPacket open(
            byte[] packet,
            int packetOffset,
            int packetLength,
            TunnelCipher cipher
    ) throws PyVpnProtocolException {
        Header header = parseHeader(packet, packetOffset, packetLength);
        if (packetLength < HEADER_SIZE + TAG_SIZE) {
            throw new PyVpnProtocolException("truncated encrypted tunnel packet");
        }
        byte[] plaintext = cipher.decrypt(
                header.sequence(),
                packet,
                packetOffset + HEADER_SIZE,
                packetLength - HEADER_SIZE,
                packet,
                packetOffset,
                HEADER_SIZE
        );
        return new OpenedPacket(header, plaintext);
    }

    public static OpenedPacket openInto(
            byte[] packet,
            int packetOffset,
            int packetLength,
            TunnelCipher cipher,
            byte[] plaintextOutput,
            int plaintextOffset
    ) throws PyVpnProtocolException {
        Header header = parseHeader(packet, packetOffset, packetLength);
        if (packetLength < HEADER_SIZE + TAG_SIZE) {
            throw new PyVpnProtocolException("truncated encrypted tunnel packet");
        }
        int ciphertextLength = packetLength - HEADER_SIZE;
        requireRange(plaintextOutput, plaintextOffset, ciphertextLength);
        int plaintextLength = cipher.decryptInto(
                header.sequence(),
                packet,
                packetOffset + HEADER_SIZE,
                ciphertextLength,
                packet,
                packetOffset,
                HEADER_SIZE,
                plaintextOutput,
                plaintextOffset
        );
        return new OpenedPacket(header, plaintextOutput, plaintextOffset, plaintextLength);
    }

    public static Header parseHeader(byte[] packet) throws PyVpnProtocolException {
        return parseHeader(packet, 0, packet.length);
    }

    public static Header parseHeader(byte[] packet, int packetOffset, int packetLength)
            throws PyVpnProtocolException {
        requireRange(packet, packetOffset, packetLength);
        if (packetLength < HEADER_SIZE) {
            throw new PyVpnProtocolException("truncated tunnel packet");
        }
        for (int index = 0; index < MAGIC.length; index++) {
            if (packet[packetOffset + index] != MAGIC[index]) {
                throw new PyVpnProtocolException("invalid tunnel packet magic");
            }
        }
        int version = packet[packetOffset + 4] & 0xff;
        int packetType = packet[packetOffset + 5] & 0xff;
        if (version != DATA_VERSION) {
            throw new PyVpnProtocolException("unsupported tunnel packet version");
        }
        requirePacketType(packetType);
        long sessionId = readLong(packet, packetOffset + 6);
        long sequence = readLong(packet, packetOffset + 14);
        if (sequence <= 0) {
            throw new PyVpnProtocolException("invalid packet sequence number");
        }
        return new Header(version, packetType, sessionId, sequence);
    }

    private static void encodeHeader(
            int packetType,
            long sessionId,
            long sequence,
            byte[] output,
            int outputOffset
    ) throws PyVpnProtocolException {
        requirePacketType(packetType);
        if (sequence <= 0) {
            throw new PyVpnProtocolException("invalid packet sequence number");
        }
        requireRange(output, outputOffset, HEADER_SIZE);
        System.arraycopy(MAGIC, 0, output, outputOffset, MAGIC.length);
        output[outputOffset + 4] = (byte) DATA_VERSION;
        output[outputOffset + 5] = (byte) packetType;
        writeLong(output, outputOffset + 6, sessionId);
        writeLong(output, outputOffset + 14, sequence);
    }

    private static long readLong(byte[] input, int offset) {
        long value = 0;
        for (int index = 0; index < Long.BYTES; index++) {
            value = (value << 8) | (input[offset + index] & 0xffL);
        }
        return value;
    }

    private static void writeLong(byte[] output, int offset, long value) {
        for (int index = Long.BYTES - 1; index >= 0; index--) {
            output[offset + index] = (byte) value;
            value >>>= 8;
        }
    }

    private static int encryptedLength(int plaintextLength) throws PyVpnProtocolException {
        try {
            return Math.addExact(HEADER_SIZE + TAG_SIZE, plaintextLength);
        } catch (ArithmeticException exception) {
            throw new PyVpnProtocolException("tunnel packet is too large", exception);
        }
    }

    private static void requireRange(byte[] value, int offset, int length)
            throws PyVpnProtocolException {
        if (value == null || offset < 0 || length < 0 || offset > value.length - length) {
            throw new PyVpnProtocolException("invalid tunnel packet range");
        }
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
        private final int plaintextOffset;
        private final int plaintextLength;

        private OpenedPacket(Header header, byte[] plaintext) {
            this(header, plaintext, 0, plaintext.length);
        }

        private OpenedPacket(
                Header header,
                byte[] plaintext,
                int plaintextOffset,
                int plaintextLength
        ) {
            this.header = header;
            this.plaintext = plaintext;
            this.plaintextOffset = plaintextOffset;
            this.plaintextLength = plaintextLength;
        }

        public Header header() {
            return header;
        }

        public byte[] plaintext() {
            if (plaintextOffset == 0 && plaintextLength == plaintext.length) {
                return plaintext;
            }
            return Arrays.copyOfRange(
                    plaintext,
                    plaintextOffset,
                    plaintextOffset + plaintextLength
            );
        }

        public byte[] plaintextBuffer() {
            return plaintext;
        }

        public int plaintextOffset() {
            return plaintextOffset;
        }

        public int plaintextLength() {
            return plaintextLength;
        }
    }
}
