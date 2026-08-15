package com.penghanli.pyvpn.protocol;

import java.io.IOException;

public final class PyVpnProtocolException extends IOException {
    private static final long serialVersionUID = 1L;

    public PyVpnProtocolException(String message) {
        super(message);
    }

    public PyVpnProtocolException(String message, Throwable cause) {
        super(message, cause);
    }
}
