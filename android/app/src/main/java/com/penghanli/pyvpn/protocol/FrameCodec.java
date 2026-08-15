package com.penghanli.pyvpn.protocol;

import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.Map;

public final class FrameCodec {
    public static final int MAX_FRAME_BYTES = 1_048_576;

    private FrameCodec() {}

    public static void write(OutputStream output, Map<String, Object> message) throws IOException {
        byte[] payload = MiniJson.stringify(message).getBytes(StandardCharsets.UTF_8);
        if (payload.length > MAX_FRAME_BYTES) {
            throw new PyVpnProtocolException("control frame is too large");
        }
        byte[] header = ByteBuffer.allocate(4)
                .order(ByteOrder.BIG_ENDIAN)
                .putInt(payload.length)
                .array();
        output.write(header);
        output.write(payload);
        output.flush();
    }

    public static Map<String, Object> read(InputStream input) throws IOException {
        byte[] header = readExactly(input, 4);
        int length = ByteBuffer.wrap(header).order(ByteOrder.BIG_ENDIAN).getInt();
        if (length < 0 || length > MAX_FRAME_BYTES) {
            throw new PyVpnProtocolException("invalid control frame length");
        }
        byte[] payload = readExactly(input, length);
        return MiniJson.parseObject(new String(payload, StandardCharsets.UTF_8));
    }

    private static byte[] readExactly(InputStream input, int length) throws IOException {
        byte[] result = new byte[length];
        int offset = 0;
        while (offset < length) {
            int count = input.read(result, offset, length - offset);
            if (count < 0) {
                throw new EOFException("control connection closed");
            }
            offset += count;
        }
        return result;
    }
}
