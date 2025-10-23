#!/usr/bin/env python3
"""
ICSI 516 – Project One (Part Two)
Client-side implementation of reliable file transfer using UDP (Stop-and-Wait ARQ).

Author: Haroun Moussa Hamza
Date: October 2025
"""

import os
import sys
import socket
import time

CHUNK_SIZE = 1000
TIMEOUT_S = 1.0

# ==============================================================
# Helper Functions
# ==============================================================

def send_len(sock, addr, nbytes):
    print(f"Sending message: LEN:{nbytes} to {addr}")
    sock.sendto(f"LEN:{nbytes}".encode(), addr)

def send_data(sock, addr, seq, payload: bytes):
    sock.sendto(b"DATA:%d|" % seq + payload, addr)

def send_ack(sock, addr, seq):
    print(f"Sending ACK:{seq} to {addr}")
    sock.sendto(f"ACK:{seq}".encode(), addr)

def send_fin(sock, addr):
    print(f"Sending FIN to {addr}")
    sock.sendto(b"FIN", addr)

def recv_with_timeout(sock, timeout_s):
    sock.settimeout(timeout_s)
    try:
        data, addr = sock.recvfrom(65535)
        return data, addr
    except socket.timeout:
        return None, None

def parse_data_packet(packet: bytes):
    if not packet.startswith(b"DATA:"):
        return None, None
    try:
        head, payload = packet.split(b"|", 1)
        seq = int(head.decode().split(":")[1])
        return seq, payload
    except Exception:
        return None, None


# ==============================================================
# Stop-and-Wait Roles
# ==============================================================

def receiver_receive_file(sock, peer_addr, save_path, expected_bytes):
    """Client as receiver (GET): receive data, send ACKs, write to file."""
    received = 0
    next_seq = 0

    pkt, _ = recv_with_timeout(sock, TIMEOUT_S)
    if pkt is None:
        # print("Did not receive data. Terminating.")
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
                    print("File delivered successfully.")
                    return True

                pkt, _ = recv_with_timeout(sock, TIMEOUT_S)
                # print(f"Received packet: {pkt}")
                if pkt is None:
                    print("Data transmission terminated prematurely.")
                    return False
            else:
                send_ack(sock, peer_addr, next_seq - 1)
                pkt, _ = recv_with_timeout(sock, TIMEOUT_S)
                if pkt is None:
                    print("Data transmission terminated prematurely.")
                    return False


def sender_send_file(sock, peer_addr, file_path):
    """Client as sender (PUT): send file with stop-and-wait and wait for ACKs."""
    filesize = os.path.getsize(file_path)
    print(f"File size: {filesize} bytes")
    print(f"socket: {sock}, peer_addr: {peer_addr}, file_path: {file_path}")
    send_len(sock, peer_addr, filesize)

    seq = 0
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break

            send_data(sock, peer_addr, seq, chunk)
            time.sleep(0.001)  # prevent ACK overlap

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
        print("Did not receive ACK. Terminating.")
        return False

    print("File successfully uploaded.")
    return True


# ==============================================================
# Client Command Interface
# ==============================================================

def main(server_ip, server_port):
    server_addr = (server_ip, server_port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    while True:
        cmdline = input("Enter command (put/get/quit): ").strip()
        if not cmdline:
            continue

        parts = cmdline.split(maxsplit=1)
        cmd = parts[0].lower()

        if cmd == "quit":
            sock.sendto(b"quit", server_addr)
            print("Connection closed.")
            break

        elif cmd == "put" and len(parts) == 2:
            print("WE ARE IN PUT")
            local_path = parts[1]
            print(f"File path: {local_path}")
            if not os.path.exists(local_path):
                print("File not found.")
                continue
            basename = os.path.basename(local_path)
            print(f"Basename: {basename}")
            sock.sendto(f"put {basename}".encode(), server_addr)
            sender_send_file(sock, server_addr, local_path)

        elif cmd == "get" and len(parts) == 2:
            print("WE ARE IN GET")
            filename = os.path.basename(parts[1])
            server_path = f"uploads/{server_ip}/{filename}"  # Auto path builder
            print(f"Sending Message: get {server_path} to {server_addr}")
            sock.sendto(f"get {server_path}".encode(), server_addr)

            len_pkt, _ = recv_with_timeout(sock, TIMEOUT_S)
            print(f"Received LEN packet: {len_pkt}")
            if len_pkt is None or not len_pkt.startswith(b"LEN:"):
                print("Did not receive data. Terminating.")
                continue

            try:
                total_bytes = int(len_pkt.decode().split(":")[1])
            except Exception:
                print("Did not receive data. Terminating.")
                continue

            if total_bytes == 0:
                print("Data transmission terminated prematurely.")
                continue

            save_dir = "downloads"
            os.makedirs(save_dir, exist_ok=True)
            save_path = os.path.join(save_dir, filename)
            receiver_receive_file(sock, server_addr, save_path, total_bytes)

        else:
            print("Invalid command or syntax.")

    sock.close()


# ==============================================================
# Entry Point
# ==============================================================

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 clientUDP.py <server_ip> <server_port>")
        sys.exit(1)
    main(sys.argv[1], int(sys.argv[2]))
