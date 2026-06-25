import subprocess

from pyvpn import routes


def _completed(stdout: str = ""):
    return subprocess.CompletedProcess([], 0, stdout=stdout, stderr="")


def test_macos_client_routes_split_default_via_tunnel_gateway(monkeypatch):
    commands = []

    def fake_run(args, *, check=True, input_text=None):
        commands.append(list(args))
        if args == ["route", "-n", "get", "default"]:
            return _completed(
                """
   route to: default
destination: default
    gateway: 192.168.1.1
  interface: en0
"""
            )
        if args == ["route", "-n", "get", "1.1.1.1"]:
            return _completed(
                """
   route to: 1.1.1.1
destination: 0.0.0.0
    gateway: 10.8.0.1
  interface: utun7
"""
            )
        if args == ["route", "-n", "get", "129.0.0.1"]:
            return _completed(
                """
   route to: 129.0.0.1
destination: 128.0.0.0
    gateway: 10.8.0.1
  interface: utun7
"""
            )
        if args == ["route", "-n", "get", "51.79.147.199"]:
            return _completed(
                """
   route to: 51.79.147.199
destination: 51.79.147.199
    gateway: 192.168.1.1
  interface: en0
"""
            )
        return _completed()

    monkeypatch.setattr(routes, "run", fake_run)

    network = routes.MacClientNetwork(
        tun_name="utun7",
        server_ips=["51.79.147.199"],
        gateway="10.8.0.1",
        dns="1.1.1.1",
        manage_dns=False,
    )
    network.setup()

    assert [
        "route",
        "-n",
        "add",
        "-net",
        "0.0.0.0",
        "-netmask",
        "128.0.0.0",
        "10.8.0.1",
    ] in commands
    assert [
        "route",
        "-n",
        "add",
        "-net",
        "128.0.0.0",
        "-netmask",
        "128.0.0.0",
        "10.8.0.1",
    ] in commands
