package com.penghanli.pyvpn;

import android.annotation.SuppressLint;
import android.os.ParcelFileDescriptor;
import com.penghanli.pyvpn.protocol.FrameCodec;
import com.penghanli.pyvpn.protocol.Ipv4Packet;
import com.penghanli.pyvpn.protocol.PacketCodec;
import com.penghanli.pyvpn.protocol.PyVpnProtocolException;
import com.penghanli.pyvpn.protocol.ReplayWindow;
import com.penghanli.pyvpn.protocol.SessionConfig;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.security.cert.CertificateException;
import java.security.cert.X509Certificate;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;
import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocket;
import javax.net.ssl.SSLSocketFactory;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

final class PyVpnConnection {
    interface Listener {
        void onStage(String message);
        void onConnected(SessionConfig session);
    }

    private static final int CONNECT_TIMEOUT_MS = 10_000;
    private static final int CONTROL_TIMEOUT_MS = 10_000;
    private static final int HEARTBEAT_INTERVAL_MS = 15_000;
    private static final int KEEPALIVE_INTERVAL_MS = 10_000;

    private final PyVpnService service;
    private final NodeProfile node;
    private final String clientId;
    private final Listener listener;
    private final AtomicBoolean running = new AtomicBoolean(false);
    private final AtomicBoolean stopRequested = new AtomicBoolean(false);
    private final AtomicLong transmitSequence = new AtomicLong(0);
    private final AtomicReference<Throwable> workerFailure = new AtomicReference<>();
    private final ReplayWindow replayWindow = new ReplayWindow();
    private final Object controlWriteLock = new Object();
    private final Object udpWriteLock = new Object();
    private final Object closeLock = new Object();
    private final List<Thread> workers = new ArrayList<>();

    private volatile Thread runnerThread;
    private volatile SSLSocket controlSocket;
    private volatile InputStream controlInput;
    private volatile OutputStream controlOutput;
    private volatile DatagramSocket udpSocket;
    private volatile ParcelFileDescriptor tunnel;
    private volatile FileInputStream tunnelInput;
    private volatile FileOutputStream tunnelOutput;
    private volatile SessionConfig session;
    private volatile int clientAddress;

    PyVpnConnection(
            PyVpnService service,
            NodeProfile node,
            String clientId,
            Listener listener
    ) {
        this.service = service;
        this.node = node;
        this.clientId = clientId;
        this.listener = listener;
    }

    void run() throws Exception {
        runnerThread = Thread.currentThread();
        try {
            listener.onStage("正在解析 " + node.serverHost());
            Inet4Address controlAddress = resolveIpv4(node.serverHost());
            requireNotStopped();
            openControlSocket(controlAddress);
            requireNotStopped();

            listener.onStage("正在验证服务器");
            sendHello();
            Map<String, Object> response = FrameCodec.read(controlInput);
            if ("error".equals(response.get("type"))) {
                String message = response.get("message") instanceof String
                        ? (String) response.get("message") : "server rejected client";
                if ("authentication failed".equals(message)) {
                    throw new PyVpnProtocolException("Token 不正确，服务端拒绝认证");
                }
                throw new PyVpnProtocolException("服务端拒绝连接：" + message);
            }
            session = SessionConfig.fromAccept(response, node.serverHost());
            clientAddress = Ipv4Packet.parseAddress(session.clientVip());
            requireNotStopped();

            listener.onStage("正在建立加密隧道");
            Inet4Address udpAddress = resolveIpv4(session.udpHost());
            requireNotStopped();
            openUdpSocket(udpAddress, session.udpPort());
            running.set(true);
            sendUdp(PacketCodec.TYPE_KEEPALIVE, new byte[0]);

            tunnel = service.establishTunnel(node, session);
            if (tunnel == null) {
                throw new PyVpnProtocolException("Android 未能创建 VPN 接口");
            }
            tunnelInput = new FileInputStream(tunnel.getFileDescriptor());
            tunnelOutput = new FileOutputStream(tunnel.getFileDescriptor());
            listener.onConnected(session);

            startWorker("pyvpn-tun-reader", this::tunnelToUdpLoop);
            startWorker("pyvpn-udp-reader", this::udpToTunnelLoop);
            startWorker("pyvpn-keepalive", this::keepaliveLoop);
            try {
                heartbeatLoop();
            } catch (InterruptedException exception) {
                Throwable failure = workerFailure.get();
                if (failure != null && !stopRequested.get()) {
                    throwAsException(failure);
                }
                if (!stopRequested.get()) {
                    throw exception;
                }
            }

            Throwable failure = workerFailure.get();
            if (failure != null && !stopRequested.get()) {
                throwAsException(failure);
            }
        } finally {
            closeResources(false);
            runnerThread = null;
        }
    }

    void stop() {
        stopRequested.set(true);
        closeResources(true);
        Thread runner = runnerThread;
        if (runner != null) {
            runner.interrupt();
        }
    }

    private void sendHello() throws IOException {
        LinkedHashMap<String, Object> hello = new LinkedHashMap<>();
        hello.put("type", "hello");
        hello.put("version", 1);
        hello.put("token", node.token());
        hello.put("client_id", clientId);
        hello.put("mtu", 1280);
        hello.put("capabilities", Arrays.asList("ipv4", "dns", "chacha20-poly1305"));
        synchronized (controlWriteLock) {
            FrameCodec.write(controlOutput, hello);
        }
    }

    @SuppressLint("CustomX509TrustManager")
    private void openControlSocket(Inet4Address address)
            throws IOException, GeneralSecurityException {
        TrustManager[] trustManagers = {
                new PinnedCertificateTrustManager(node.certificateFingerprint())
        };
        SSLContext context = SSLContext.getInstance("TLS");
        context.init(null, trustManagers, new SecureRandom());

        Socket rawSocket = new Socket();
        if (!service.protect(rawSocket)) {
            rawSocket.close();
            throw new IOException("无法将控制连接排除在 VPN 路由之外");
        }
        rawSocket.connect(new InetSocketAddress(address, node.controlPort()), CONNECT_TIMEOUT_MS);
        rawSocket.setTcpNoDelay(true);

        SSLSocketFactory factory = context.getSocketFactory();
        SSLSocket sslSocket = (SSLSocket) factory.createSocket(
                rawSocket,
                node.serverHost(),
                node.controlPort(),
                true
        );
        controlSocket = sslSocket;
        sslSocket.setEnabledProtocols(supportedTlsProtocols(sslSocket.getSupportedProtocols()));
        sslSocket.setSoTimeout(CONTROL_TIMEOUT_MS);
        sslSocket.startHandshake();
        controlInput = sslSocket.getInputStream();
        controlOutput = sslSocket.getOutputStream();
    }

    private void openUdpSocket(Inet4Address address, int port) throws IOException {
        DatagramSocket socket = new DatagramSocket();
        if (!service.protect(socket)) {
            socket.close();
            throw new IOException("无法将 UDP 隧道排除在 VPN 路由之外");
        }
        socket.connect(address, port);
        udpSocket = socket;
    }

    private static String certificateFingerprint(X509Certificate certificate)
            throws CertificateException {
        byte[] digest;
        try {
            digest = MessageDigest.getInstance("SHA-256").digest(certificate.getEncoded());
        } catch (GeneralSecurityException exception) {
            throw new CertificateException("无法计算服务器证书指纹", exception);
        }
        StringBuilder actual = new StringBuilder("sha256:");
        for (byte value : digest) {
            actual.append(String.format(Locale.ROOT, "%02x", value & 0xff));
        }
        return actual.toString();
    }

    private static String[] supportedTlsProtocols(String[] supported)
            throws GeneralSecurityException {
        ArrayList<String> result = new ArrayList<>();
        for (String protocol : supported) {
            if ("TLSv1.3".equals(protocol) || "TLSv1.2".equals(protocol)) {
                result.add(protocol);
            }
        }
        if (result.isEmpty()) {
            throw new GeneralSecurityException("TLS 1.2 or newer is unavailable");
        }
        return result.toArray(new String[0]);
    }

    private void heartbeatLoop() throws Exception {
        while (running.get()) {
            sleepWhileRunning(HEARTBEAT_INTERVAL_MS);
            if (!running.get()) {
                break;
            }
            LinkedHashMap<String, Object> heartbeat = new LinkedHashMap<>();
            heartbeat.put("type", "heartbeat");
            synchronized (controlWriteLock) {
                FrameCodec.write(controlOutput, heartbeat);
            }
            Map<String, Object> response = FrameCodec.read(controlInput);
            if ("error".equals(response.get("type"))) {
                throw new PyVpnProtocolException(String.valueOf(response.get("message")));
            }
            if (!"heartbeat".equals(response.get("type"))) {
                throw new PyVpnProtocolException("服务端心跳响应无效");
            }
        }
    }

    private void keepaliveLoop() throws Exception {
        while (running.get()) {
            sleepWhileRunning(KEEPALIVE_INTERVAL_MS);
            if (running.get()) {
                sendUdp(PacketCodec.TYPE_KEEPALIVE, new byte[0]);
            }
        }
    }

    private void tunnelToUdpLoop() throws Exception {
        byte[] buffer = new byte[65_535];
        while (running.get()) {
            int length = tunnelInput.read(buffer);
            if (length < 0) {
                throw new IOException("Android VPN 接口已关闭");
            }
            try {
                Ipv4Packet.Info info = Ipv4Packet.inspect(buffer, length);
                if (info.source() != clientAddress) {
                    continue;
                }
                byte[] packet = Arrays.copyOf(buffer, info.totalLength());
                sendUdp(PacketCodec.TYPE_DATA, packet);
            } catch (PyVpnProtocolException ignored) {
                // Ignore malformed or non-IPv4 packets from the TUN interface.
            }
        }
    }

    private void udpToTunnelLoop() throws Exception {
        byte[] buffer = new byte[65_535];
        DatagramPacket datagram = new DatagramPacket(buffer, buffer.length);
        while (running.get()) {
            datagram.setLength(buffer.length);
            udpSocket.receive(datagram);
            byte[] encrypted = Arrays.copyOfRange(
                    datagram.getData(),
                    datagram.getOffset(),
                    datagram.getOffset() + datagram.getLength()
            );
            try {
                PacketCodec.Header header = PacketCodec.parseHeader(encrypted);
                if (header.sessionId() != session.sessionId()) {
                    continue;
                }
                PacketCodec.OpenedPacket opened = PacketCodec.open(
                        encrypted,
                        session.serverToClientCipher()
                );
                if (!replayWindow.accept(opened.header().sequence())) {
                    continue;
                }
                if (opened.header().packetType() == PacketCodec.TYPE_KEEPALIVE) {
                    continue;
                }
                byte[] plaintext = opened.plaintext();
                Ipv4Packet.Info info = Ipv4Packet.inspect(plaintext, plaintext.length);
                if (info.destination() != clientAddress) {
                    continue;
                }
                tunnelOutput.write(plaintext, 0, info.totalLength());
            } catch (PyVpnProtocolException ignored) {
                // Invalid, replayed, or unauthenticated datagrams are dropped.
            }
        }
    }

    private void sendUdp(int packetType, byte[] plaintext) throws IOException {
        SessionConfig activeSession = session;
        DatagramSocket socket = udpSocket;
        if (activeSession == null || socket == null || socket.isClosed()) {
            return;
        }
        long sequence = transmitSequence.incrementAndGet();
        if (sequence <= 0) {
            throw new PyVpnProtocolException("隧道数据包序号已耗尽");
        }
        byte[] encrypted = PacketCodec.seal(
                packetType,
                activeSession.sessionId(),
                sequence,
                plaintext,
                activeSession.clientToServerCipher()
        );
        synchronized (udpWriteLock) {
            socket.send(new DatagramPacket(encrypted, encrypted.length));
        }
    }

    private void startWorker(String name, ThrowingRunnable action) {
        Thread worker = new Thread(() -> {
            try {
                action.run();
            } catch (Throwable failure) {
                failWorker(failure);
            }
        }, name);
        worker.setDaemon(true);
        synchronized (workers) {
            workers.add(worker);
        }
        worker.start();
    }

    private void failWorker(Throwable failure) {
        if (stopRequested.get() || !running.get()) {
            return;
        }
        if (workerFailure.compareAndSet(null, failure)) {
            closeResources(false);
            Thread runner = runnerThread;
            if (runner != null) {
                runner.interrupt();
            }
        }
    }

    private void closeResources(boolean sendDisconnect) {
        synchronized (closeLock) {
            boolean wasRunning = running.getAndSet(false);
            if (sendDisconnect && wasRunning && controlOutput != null) {
                LinkedHashMap<String, Object> message = new LinkedHashMap<>();
                message.put("type", "disconnect");
                try {
                    synchronized (controlWriteLock) {
                        FrameCodec.write(controlOutput, message);
                    }
                } catch (IOException ignored) {
                    // The connection may already be gone.
                }
            }
            closeQuietly(tunnel);
            tunnel = null;
            DatagramSocket datagram = udpSocket;
            udpSocket = null;
            if (datagram != null) {
                datagram.close();
            }
            SSLSocket ssl = controlSocket;
            controlSocket = null;
            if (ssl != null) {
                try {
                    ssl.close();
                } catch (IOException ignored) {
                    // Closing is best-effort during shutdown.
                }
            }
            synchronized (workers) {
                for (Thread worker : workers) {
                    if (worker != Thread.currentThread()) {
                        worker.interrupt();
                    }
                }
                workers.clear();
            }
        }
    }

    private static void closeQuietly(ParcelFileDescriptor descriptor) {
        if (descriptor == null) {
            return;
        }
        try {
            descriptor.close();
        } catch (IOException ignored) {
            // Closing is best-effort during shutdown.
        }
    }

    private void sleepWhileRunning(int milliseconds) throws InterruptedException {
        if (running.get()) {
            Thread.sleep(milliseconds);
        }
    }

    private static Inet4Address resolveIpv4(String host) throws IOException {
        for (InetAddress address : InetAddress.getAllByName(host)) {
            if (address instanceof Inet4Address ipv4) {
                return ipv4;
            }
        }
        throw new IOException("服务器没有可用的 IPv4 地址：" + host);
    }

    private static void throwAsException(Throwable failure) throws Exception {
        if (failure instanceof Exception exception) {
            throw exception;
        }
        throw new IOException("VPN worker stopped unexpectedly", failure);
    }

    private void requireNotStopped() throws InterruptedException {
        if (stopRequested.get()) {
            throw new InterruptedException("VPN connection was cancelled");
        }
    }

    private interface ThrowingRunnable {
        void run() throws Exception;
    }

    @SuppressLint("CustomX509TrustManager")
    private static final class PinnedCertificateTrustManager implements X509TrustManager {
        private final String expectedFingerprint;

        private PinnedCertificateTrustManager(String expectedFingerprint) {
            this.expectedFingerprint = expectedFingerprint;
        }

        @Override
        public void checkClientTrusted(X509Certificate[] chain, String authType)
                throws CertificateException {
            throw new CertificateException("客户端证书验证不适用于 pyvpn 客户端");
        }

        @Override
        public void checkServerTrusted(X509Certificate[] chain, String authType)
                throws CertificateException {
            if (chain == null || chain.length == 0) {
                throw new CertificateException("server did not provide a certificate");
            }
            if (authType == null || authType.isEmpty()) {
                throw new CertificateException("server certificate auth type is missing");
            }
            String actualFingerprint = certificateFingerprint(chain[0]);
            byte[] expected = expectedFingerprint.getBytes(StandardCharsets.US_ASCII);
            byte[] actual = actualFingerprint.getBytes(StandardCharsets.US_ASCII);
            if (!MessageDigest.isEqual(expected, actual)) {
                throw new CertificateException(
                        "服务器证书指纹不匹配，实际指纹为 " + actualFingerprint
                );
            }
        }

        @Override
        public X509Certificate[] getAcceptedIssuers() {
            return new X509Certificate[0];
        }
    }
}
