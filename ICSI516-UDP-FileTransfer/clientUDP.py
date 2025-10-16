#!/usr/bin/env python3
import os
import sys
import socket

CHUNK_SIZE = 1000
TIMEOUT_S = 1.0

# ====== helpers ======
def send_len(sock, addr, nbytes):
    sock.sendto(f"LEN:{nbytes}".encode(), addr)

def send_data(sock, addr, seq, payload: bytes):
    sock.sendto(b"DATA:%d|" % seq + payload, addr)

def send_ack(sock, addr, seq):
    sock.sendto(f"ACK:{seq}".encode(), addr)

def send_fin(sock, addr):
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

# ====== RDT roles (same logic as server, reused) ======
def receiver_receive_file(sock, peer_addr, save_path, expected_bytes):
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
                    send_fin(sock, peer_addr)
                    print("File delivered from server.")
                    return True

                pkt, _ = recv_with_timeout(sock, TIMEOUT_S)
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
    filesize = os.path.getsize(file_path)
    send_len(sock, peer_addr, filesize)

    seq = 0
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            send_data(sock, peer_addr, seq, chunk)

            ack, _ = recv_with_timeout(sock, TIMEOUT_S)
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
    if fin != b"FIN":
        print("Did not receive ACK. Terminating.")
        return False
    print("File successfully uploaded.")
    return True

# ====== client UI ======
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

        # PUT <local_file_path>
        elif cmd == "put" and len(parts) == 2:
            local_path = parts[1]
            if not os.path.exists(local_path):
                print("File not found.")
                continue
            basename = os.path.basename(local_path)

            # Tell server we want to PUT and the filename it should store
            sock.sendto(f"put {basename}".encode(), server_addr)

            # Sender role (client): stream file → server
            ok = sender_send_file(sock, server_addr, local_path)
            # message printed inside on success/failure

        # GET <server_file_path>
        elif cmd == "get" and len(parts) == 2:
            server_path = parts[1]  # full path on server (e.g., Server_dir/<ip>/file1.txt)
            sock.sendto(f"get {server_path}".encode(), server_addr)

            # Receiver role (client): expect LEN first
            len_pkt, _ = recv_with_timeout(sock, TIMEOUT_S)
            if len_pkt is None or not len_pkt.startswith(b"LEN:"):
                print("Did not receive data. Terminating.")
                continue

            try:
                total_bytes = int(len_pkt.decode().split(":")[1])
            except Exception:
                print("Did not receive data. Terminating.")
                continue

            if total_bytes == 0:
                # server indicated file missing (courtesy)
                print("Data transmission terminated prematurely.")
                continue

            save_dir = "Client_dir"
            os.makedirs(save_dir, exist_ok=True)
            save_path = os.path.join(save_dir, os.path.basename(server_path))
            receiver_receive_file(sock, server_addr, save_path, total_bytes)

        else:
            print("Invalid command or syntax.")

    sock.close()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 clientUDP.py <server_ip> <server_port>")
        sys.exit(1)
    main(sys.argv[1], int(sys.argv[2]))
