package com.penghanli.pyvpn.protocol;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.math.BigInteger;
import java.util.Arrays;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;
import org.junit.Test;

public final class ProtocolCompatibilityTest {
    @Test
    public void encryptedPacketMatchesPythonVector() throws Exception {
        byte[] key = new byte[32];
        for (int index = 0; index < key.length; index++) {
            key[index] = (byte) index;
        }
        DirectionKey direction = new DirectionKey(key, hex("a0a1a2a3"));
        TunnelCipher cipher = new TunnelCipher(direction);
        long sessionId = new BigInteger("fedcba9876543210", 16).longValue();
        byte[] plaintext = hex("4500001400010000400100000a08000208080808");

        byte[] sealed = PacketCodec.seal(
                PacketCodec.TYPE_DATA,
                sessionId,
                1,
                plaintext,
                cipher
        );

        assertEquals(
                "5059564e0101fedcba9876543210000000000000000162dc35da5ab45a704992cb1416c1c0accdcb06f82dd402a24db2ecb9c8eef0a0164386f8",
                toHex(sealed)
        );
        PacketCodec.OpenedPacket opened = PacketCodec.open(sealed, cipher);
        assertEquals(sessionId, opened.header().sessionId());
        assertEquals(1, opened.header().sequence());
        assertArrayEquals(plaintext, opened.plaintext());
    }

    @Test
    public void controlFramePreservesUnsignedSessionId() throws Exception {
        String json = "{\"session_id\":18364758544493064720,\"type\":\"accept\"}";
        Map<String, Object> parsed = MiniJson.parseObject(json);
        assertEquals(
                new BigInteger("18364758544493064720"),
                parsed.get("session_id")
        );

        LinkedHashMap<String, Object> message = new LinkedHashMap<>();
        message.put("type", "hello");
        message.put("version", 1);
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        FrameCodec.write(output, message);
        Map<String, Object> roundTrip = FrameCodec.read(
                new ByteArrayInputStream(output.toByteArray())
        );
        assertEquals("hello", roundTrip.get("type"));
        assertEquals(BigInteger.ONE, roundTrip.get("version"));
    }

    @Test
    public void replayWindowRejectsDuplicatesAndExpiredPackets() {
        ReplayWindow replay = new ReplayWindow(8);
        assertTrue(replay.accept(1));
        assertFalse(replay.accept(1));
        assertTrue(replay.accept(4));
        assertTrue(replay.accept(2));
        assertFalse(replay.accept(2));
        assertTrue(replay.accept(12));
        assertFalse(replay.accept(4));
    }

    @Test
    public void parsesPythonServerAcceptFrame() throws Exception {
        Map<String, Object> message = acceptFrame();

        SessionConfig session = SessionConfig.fromAccept(message, "203.0.113.10");

        assertEquals(new BigInteger("18364758544493064720").longValue(), session.sessionId());
        assertEquals("10.8.0.2", session.clientVip());
        assertEquals("10.8.0.1", session.serverVip());
        assertEquals("1.1.1.1", session.dns());
        assertEquals(1280, session.mtu());
        assertEquals("203.0.113.10", session.udpHost());
        assertEquals(8444, session.udpPort());
    }

    @Test
    public void rejectsAcceptFrameIntegerOutsideAndroidRange() {
        Map<String, Object> message = acceptFrame();
        message.put("mtu", BigInteger.ONE.shiftLeft(40));

        assertThrows(
                PyVpnProtocolException.class,
                () -> SessionConfig.fromAccept(message, "203.0.113.10")
        );
    }

    private static Map<String, Object> acceptFrame() {
        LinkedHashMap<String, Object> endpoint = new LinkedHashMap<>();
        endpoint.put("host", "0.0.0.0");
        endpoint.put("port", 8444);

        LinkedHashMap<String, Object> c2s = new LinkedHashMap<>();
        c2s.put("key", Base64.getEncoder().encodeToString(new byte[32]));
        c2s.put("salt", Base64.getEncoder().encodeToString(new byte[4]));
        LinkedHashMap<String, Object> s2c = new LinkedHashMap<>();
        s2c.put("key", Base64.getEncoder().encodeToString(new byte[32]));
        s2c.put("salt", Base64.getEncoder().encodeToString(new byte[4]));
        LinkedHashMap<String, Object> crypto = new LinkedHashMap<>();
        crypto.put("aead", "chacha20-poly1305");
        crypto.put("c2s", c2s);
        crypto.put("s2c", s2c);

        LinkedHashMap<String, Object> message = new LinkedHashMap<>();
        message.put("type", "accept");
        message.put("version", 1);
        message.put("session_id", new BigInteger("18364758544493064720"));
        message.put("client_vip", "10.8.0.2/24");
        message.put("server_vip", "10.8.0.1");
        message.put("dns", Arrays.asList("1.1.1.1"));
        message.put("mtu", 1280);
        message.put("udp_endpoint", endpoint);
        message.put("crypto", crypto);
        return message;
    }

    private static byte[] hex(String value) {
        byte[] result = new byte[value.length() / 2];
        for (int index = 0; index < result.length; index++) {
            result[index] = (byte) Integer.parseInt(value.substring(index * 2, index * 2 + 2), 16);
        }
        return result;
    }

    private static String toHex(byte[] value) {
        StringBuilder result = new StringBuilder();
        for (byte item : value) {
            result.append(String.format("%02x", item & 0xff));
        }
        return result.toString();
    }
}
