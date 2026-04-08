# -*- coding: utf-8 -*-
"""
UDP Bridge -- Bidirectional UDP packet relay for SITL.

Sits between the test software (udpin) and the vehicle sim (udpin)
so that NEITHER side needs any code changes.

Architecture:
    Test Software  <-->  Bridge  <-->  Vehicle Sim
    udpin:PORT_A         relay         udpin:PORT_B

The bridge:
  1. Binds on PORT_A (the "vehicle port" the test software connects to)
  2. Forwards all packets FROM test software TO sim at PORT_B
  3. Forwards all packets FROM sim TO test software at PORT_A

This mirrors a real network where the vehicle has its own IP/port.
"""

import socket
import threading
import sys
import os

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


class UDPBridge:
    """
    Bidirectional UDP relay between two endpoints.

    Args:
        vehicle_port: Port the test software connects to (bridge binds here)
        sim_port: Port the sim vehicle listens on (bridge sends here)
        bind_ip: IP to bind on (default 127.0.0.1)
    """

    def __init__(self, vehicle_port, sim_port, bind_ip='127.0.0.1'):
        self.vehicle_port = vehicle_port
        self.sim_port     = sim_port
        self.bind_ip      = bind_ip
        self._running     = False

        # Socket that faces the test software
        self._sw_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sw_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Socket that faces the sim
        self._sim_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # Track the test software's address (learned from first packet)
        self._gcs_addr = None

    def start(self):
        """Start the bridge (spawns two forwarding threads)."""
        self._sw_sock.bind((self.bind_ip, self.vehicle_port))
        self._sw_sock.settimeout(0.5)
        self._sim_sock.settimeout(0.5)
        self._running = True

        print(f"[Bridge] {self.bind_ip}:{self.vehicle_port} <-> "
              f"{self.bind_ip}:{self.sim_port}")

        # Test software -> Sim
        t1 = threading.Thread(target=self._forward_sw_to_sim, daemon=True)
        t1.start()

        # Sim -> Test software
        t2 = threading.Thread(target=self._forward_sim_to_sw, daemon=True)
        t2.start()

    def stop(self):
        self._running = False
        try: self._sw_sock.close()
        except Exception: pass
        try: self._sim_sock.close()
        except Exception: pass

    def _forward_sw_to_sim(self):
        """Forward packets from test software to sim."""
        while self._running:
            try:
                data, addr = self._sw_sock.recvfrom(65535)
                self._gcs_addr = addr  # remember where to send sim replies
                self._sim_sock.sendto(data, (self.bind_ip, self.sim_port))
            except socket.timeout:
                continue
            except OSError:
                break

    def _forward_sim_to_sw(self):
        """Forward packets from sim to test software."""
        # Bind the sim-facing socket to a fixed port so the sim can reply
        self._sim_sock.bind((self.bind_ip, 0))
        sim_local_port = self._sim_sock.getsockname()[1]

        # Send an initial empty packet to the sim so it learns our address
        self._sim_sock.sendto(b'', (self.bind_ip, self.sim_port))

        while self._running:
            try:
                data, addr = self._sim_sock.recvfrom(65535)
                if self._gcs_addr:
                    self._sw_sock.sendto(data, self._gcs_addr)
            except socket.timeout:
                continue
            except OSError:
                break
