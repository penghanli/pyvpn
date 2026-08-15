package com.penghanli.pyvpn;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import java.net.Socket;
import org.junit.Test;

public final class SocketProtectionCompatibilityTest {
    @Test
    public void bindForVpnProtectionCreatesSocketFileDescriptor() throws Exception {
        try (Socket socket = new Socket()) {
            assertFalse(socket.isBound());

            PyVpnConnection.bindForVpnProtection(socket);

            assertTrue(socket.isBound());
        }
    }
}
