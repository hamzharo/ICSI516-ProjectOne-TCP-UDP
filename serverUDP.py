#!/usr/bin/env python3
"""
ICSI 516 – Project One (Part Two)
Server-side implementation of reliable file transfer using UDP and Stop-and-Wait ARQ.

Author: Haroun Moussa Hamza
Date: October 2025
"""

import os
import sys
import socket
import time

CHUNK_SIZE = 1000
TIMEOUT_S = 1.0  # Allow more tolerance on macOS

# ==============================================================
# Helper Functions
# ==============================================================

def send_len(sock, addr, nbytes):
    """Send the total file size to receiver."""
    print(f"Sending message: LEN:{nbytes} to {addr}")
    sock.sendto(f"LEN:{nbytes}".encode(), addr)

def send_data(sock, addr, seq, payload: bytes):
    """Send data packet containing sequence number and chunk."""
    sock.sendto(b"DATA:%d|" % seq + payload, addr)

def send_ack(sock, addr, seq):
    """Acknowledge the successful receipt of a data packet."""
    print(f"Sending ACK:{seq} to {addr}")
    sock.sendto(f"ACK:{seq}".encode(), addr)

def send_fin(sock, addr):
    """Send final termination (FIN) message to signal end of transmission."""
    print(f"Sending FIN to {addr}")
    sock.sendto(b"FIN", addr)

def recv_with_timeout(sock, timeout_s):
    """Wait for data with timeout protection."""
    sock.settimeout(timeout_s)
    try:
        data, addr = sock.recvfrom(65535)
        return data, addr
    except socket.timeout:
        return None, None

def parse_data_packet(packet: bytes):
    """Parse packet of format DATA:<seq>|<payload>."""
    if not packet.startswith(b"DATA:"):
        return None, None
    try:
        head, payload = packet.split(b"|", 1)
        seq = int(head.decode().split(":")[1])
        return seq, payload
    except Exception:
        return None, None


# ==============================================================
# Receiver Role (Server during PUT)
# ==============================================================

def receiver_receive_file(sock, peer_addr, save_path, expected_bytes):
    """
    Receives a file using Stop-and-Wait ARQ.
    Implements timeout, ACKs, and final FIN acknowledgment.
    """
    received = 0
    next_seq = 0

    pkt, _ = recv_with_timeout(sock, TIMEOUT_S)
    if pkt is None:
        print("Did not receive data. Terminating.")
        return False

    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with open(save_path, "wb") as f:
        while True:
            if pkt == b"FIN":
                if received >= expected_bytes:
                    print("File delivered successfully.")
                    return True
                else:
                    print("Data transmission terminated prematurely.")
                    return False

            seq, payload = parse_data_packet(pkt)
            print(f"Parsed seq: {seq}, expected seq: {next_seq}")
            if seq is None:
                pkt, _ = recv_with_timeout(sock, TIMEOUT_S)
                if pkt is None:
                    print("Data transmission terminated prematurely.")
                    return False
                continue

            if seq == next_seq:
                f.write(payload)
                received += len(payload)
                send_ack(sock, peer_addr, seq)
                next_seq += 1

                if received >= expected_bytes:
                    time.sleep(0.2)
                    send_fin(sock, peer_addr)
                    print(f"File received: {os.path.basename(save_path)} ({received} bytes)")
                    return True

                pkt, _ = recv_with_timeout(sock, TIMEOUT_S)
                if pkt is None:
                    print("Data transmission terminated prematurely.")
                    return False
            else:
                # Duplicate/out-of-order → re-ACK last valid
                send_ack(sock, peer_addr, next_seq - 1)
                pkt, _ = recv_with_timeout(sock, TIMEOUT_S)
                if pkt is None:
                    print("Data transmission terminated prematurely.")
                    return False


# ==============================================================
# Sender Role (Server during GET)
# ==============================================================

def sender_send_file(sock, peer_addr, file_path):
    """Send file using Stop-and-Wait protocol."""
    filesize = os.path.getsize(file_path)
    print(f"Sending file: {os.path.basename(file_path)} ({filesize} bytes) to {peer_addr}")
    send_len(sock, peer_addr, filesize)

    seq = 0
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break

            send_data(sock, peer_addr, seq, chunk)
            time.sleep(0.001)  # Small delay to stabilize ACK timing

            ack, _ = recv_with_timeout(sock, TIMEOUT_S)
            print(f"Received ACK: {ack}")
            if ack is None or not ack.startswith(b"ACK:"):
                print("Did not receive ACK. Terminating.")
                return False

            try:
                ack_seq = int(ack.decode().split(":")[1])
            except Exception:
                print("Did not receive ACK. Terminating.")
                return False

            if ack_seq != seq:
                print("Did not receive ACK. Terminating.")
                return False

            seq += 1

    fin, _ = recv_with_timeout(sock, TIMEOUT_S)
    print(f"Received FIN: {fin}")
    if fin != b"FIN":
        print("Did not receive final FIN. Terminating.")
        return False

    time.sleep(0.2)
    print(f"File sent: {os.path.basename(file_path)} ({filesize} bytes)")
    return True


# ==============================================================
# Main Server Loop
# ==============================================================

def server_loop(port):
    """Main server: listens for PUT, GET, and QUIT commands."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", port))
    print(f"UDP server listening on port {port} ...")

    while True:
        try:
            data, addr = sock.recvfrom(65535)
            print(f"Received packet from {addr}")
        except TimeoutError:
            continue  # Ignore timeouts and keep waiting
        except Exception as e:
            print(f"Socket error: {e}")
            continue

        if not data:
            continue

        text = data.decode(errors="ignore")
        parts = text.split(maxsplit=1)
        print(f"Received command: {text}")
        print(f"Parts: {parts}")
        cmd = parts[0].lower()

        if cmd == "quit":
            print(f"Quit received from {addr}.")
            break

        # PUT command → client uploads to server
        if cmd == "put" and len(parts) == 2:
            print("WE ARE IN PUT")
            client_ip = addr[0]
            basename = os.path.basename(parts[1])
            save_dir = os.path.join("uploads", client_ip)
            os.makedirs(save_dir, exist_ok=True)
            save_path = os.path.join(save_dir, basename)
            print(f"client_ip: {client_ip}, basename: {basename}, save_path: {save_path}")

            len_pkt, _ = recv_with_timeout(sock, TIMEOUT_S)
            print(f"Received length packet: {len_pkt}")
            if len_pkt is None or not len_pkt.startswith(b"LEN:"):
                print("Did not receive file length. Terminating.")
                continue
            try:
                total_bytes = int(len_pkt.decode().split(":")[1])
            except Exception:
                print("Did not receive valid file length.")
                continue

            ok = receiver_receive_file(sock, addr, save_path, total_bytes)
            if ok:
                print(f"Received {basename} from {client_ip} ({total_bytes} bytes).")

        # GET command → send file to client
        elif cmd == "get" and len(parts) == 2:
            print("WE ARE IN GET")
            server_path = parts[1]
            print(f"server_path: {server_path}")
            if not os.path.exists(server_path):
                sock.sendto(b"LEN:0", addr)
                continue

            ok = sender_send_file(sock, addr, server_path)
            if ok:
                print(f"Sent {os.path.basename(server_path)} to {addr[0]}")

        else:
            print(f"Ignored invalid command from {addr}: {text}")

    sock.close()


# ==============================================================
# Entry Point
# ==============================================================

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 serverUDP.py <port>")
        sys.exit(1)
    server_loop(int(sys.argv[1]))
