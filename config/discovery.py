import socket
import threading

DISCOVERY_PORT = 45678
_REQUEST  = b'TAWATUR_DISCOVER'
_RESPONSE = 'TAWATUR_BACKEND:{ip}'


def _subnet_broadcast(lan_ip: str) -> str:
    """Return the subnet broadcast address for a /24 LAN IP (e.g. 192.168.1.255)."""
    parts = lan_ip.split('.')
    parts[-1] = '255'
    return '.'.join(parts)


def start_udp_discovery(lan_ip: str) -> None:
    """
    Listen for UDP discovery requests on the LAN interface and reply with the
    current LAN IP.  Listens on both the LAN IP (unicast) and subnet broadcast
    so the iOS app can reach it either way.
    Runs in a daemon thread — dies automatically when the server stops.
    """
    def _serve() -> None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            # Bind to all interfaces — receives unicast to LAN IP and subnet broadcast
            sock.bind(('', DISCOVERY_PORT))
            sock.settimeout(1.0)
            response = _RESPONSE.format(ip=lan_ip).encode()
            while True:
                try:
                    data, addr = sock.recvfrom(256)
                    if data.strip() == _REQUEST:
                        sock.sendto(response, addr)
                except socket.timeout:
                    continue
                except OSError:
                    break
        except Exception:
            pass

    t = threading.Thread(target=_serve, daemon=True, name='tawatur-discovery')
    t.start()
