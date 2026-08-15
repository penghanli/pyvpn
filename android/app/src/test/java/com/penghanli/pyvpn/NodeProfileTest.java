package com.penghanli.pyvpn;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThrows;

import java.math.BigInteger;
import java.util.LinkedHashMap;
import java.util.Map;
import org.junit.Test;

public final class NodeProfileTest {
    @Test
    public void normalizesCopiedTokenAndFingerprint() {
        NodeProfile profile = NodeProfile.create(
                "",
                " 203.0.113.10 ",
                8443,
                " PYVPN_TOKEN='sample-token' ",
                "SHA256:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:"
                        + "AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA:AA"
        );

        assertEquals("203.0.113.10", profile.name());
        assertEquals("sample-token", profile.token());
        assertEquals("sha256:" + "aa".repeat(32), profile.certificateFingerprint());
    }

    @Test
    public void rejectsInvalidPortAndFingerprint() {
        assertThrows(IllegalArgumentException.class, () -> NodeProfile.create(
                "bad",
                "203.0.113.10",
                0,
                "token",
                "sha256:bad"
        ));
    }

    @Test
    public void rejectsStoredPortOutsideAndroidIntegerRange() {
        NodeProfile profile = NodeProfile.create(
                "node",
                "203.0.113.10",
                8443,
                "token",
                "sha256:" + "aa".repeat(32)
        );
        Map<String, Object> stored = new LinkedHashMap<>(profile.toMap());
        stored.put("control_port", BigInteger.ONE.shiftLeft(40));

        assertThrows(IllegalArgumentException.class, () -> NodeProfile.fromMap(stored));
    }
}
