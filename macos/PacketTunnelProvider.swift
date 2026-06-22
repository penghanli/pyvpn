import Foundation
import NetworkExtension

struct PyVpnProviderConfig {
    let serverHost: String
    let controlPort: Int
    let token: String
    let certFingerprint: String

    init(providerConfiguration: [String: Any]?) throws {
        guard
            let config = providerConfiguration,
            let serverHost = config["serverHost"] as? String,
            let token = config["token"] as? String,
            let certFingerprint = config["certFingerprint"] as? String
        else {
            throw NSError(domain: "pyvpn", code: 1, userInfo: [
                NSLocalizedDescriptionKey: "Missing pyvpn provider configuration"
            ])
        }

        self.serverHost = serverHost
        self.controlPort = config["controlPort"] as? Int ?? 8443
        self.token = token
        self.certFingerprint = certFingerprint
    }
}

final class PacketTunnelProvider: NEPacketTunnelProvider {
    private var config: PyVpnProviderConfig?
    private var isRunning = false

    override func startTunnel(
        options: [String: NSObject]?,
        completionHandler: @escaping (Error?) -> Void
    ) {
        do {
            guard let tunnelProtocol = protocolConfiguration as? NETunnelProviderProtocol else {
                throw NSError(domain: "pyvpn", code: 2, userInfo: [
                    NSLocalizedDescriptionKey: "Invalid tunnel protocol configuration"
                ])
            }

            let parsed = try PyVpnProviderConfig(
                providerConfiguration: tunnelProtocol.providerConfiguration
            )
            config = parsed

            let settings = NEPacketTunnelNetworkSettings(tunnelRemoteAddress: parsed.serverHost)
            let ipv4 = NEIPv4Settings(addresses: ["10.8.0.2"], subnetMasks: ["255.255.255.255"])
            ipv4.includedRoutes = [NEIPv4Route.default()]
            settings.ipv4Settings = ipv4
            settings.dnsSettings = NEDNSSettings(servers: ["1.1.1.1"])
            settings.mtu = 1280

            setTunnelNetworkSettings(settings) { [weak self] error in
                if let error = error {
                    completionHandler(error)
                    return
                }
                self?.isRunning = true
                self?.readPackets()
                completionHandler(nil)
            }
        } catch {
            completionHandler(error)
        }
    }

    override func stopTunnel(
        with reason: NEProviderStopReason,
        completionHandler: @escaping () -> Void
    ) {
        isRunning = false
        completionHandler()
    }

    private func readPackets() {
        guard isRunning else { return }
        packetFlow.readPackets { [weak self] packets, protocols in
            guard let self = self, self.isRunning else { return }
            _ = protocols

            for packet in packets {
                self.forwardPacketToPyVpnUdpTunnel(packet)
            }

            self.readPackets()
        }
    }

    private func forwardPacketToPyVpnUdpTunnel(_ packet: Data) {
        _ = packet
        // Connect this hook to the shared pyvpn control and UDP protocol:
        // 1. TLS control hello with token and certificate fingerprint pinning.
        // 2. UDP packet seal/open using the same header and ChaCha20-Poly1305 keys.
        // 3. Write decrypted server packets back with packetFlow.writePackets.
    }
}
