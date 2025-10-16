#!/usr/bin/env python3
import os
import sys
import socket
import time

CHUNK_SIZE = 1000
TIMEOUT_S = 1.0  # per spec

# ====== helpers ======
def send_len(sock, addr, nbytes):
    msg = f"LEN:{nbytes}".encode()
    sock.sendto(msg, addr)

def send_data(sock, addr, seq, payload: bytes):
    # DATA:<seq>|<bytes>
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
    # expect b"DATA:<seq>|<payload>"
    if not packet.startswith(b"DATA:"):
        return None, None
    try:
        head, payload = packet.split(b"|", 1)
        seq = int(head.decode().split(":")[1])
        return seq, payload
    except Exception:
        return None, None

# ====== RDT roles ======
def receiver_receive_file(sock, peer_addr, save_path, expected_bytes):
    """
    Receiver logic (server when handling PUT, client when handling GET).
    Implements:
      - Timeout after LEN: if first DATA not within 1s
      - Timeout after ACK: if next DATA not within 1s after ACK
      - FIN sending when all bytes received
    """
    received = 0
    next_seq = 0

    # wait for first DATA within 1s (timeout after LEN)
    pkt, addr = recv_with_timeout(sock, TIMEOUT_S)
    if pkt is None:
        print("Did not receive data. Terminating.")
        return False

    # open file to write
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    with open(save_path, "wb") as f:
        while True:
            # allow either DATA or (spurious) FIN
            if pkt == b"FIN":
                # if FIN arrives early, treat as premature termination
                print("Data transmission terminated prematurely.")
                return False

            seq, payload = parse_data_packet(pkt)
            if seq is None:
                # ignore non-DATA noise; wait for valid packet
                pkt, addr = recv_with_timeout(sock, TIMEOUT_S)
                if pkt is None:
                    print("Data transmission terminated prematurely.")
                    return False
                continue

            # only accept expected seq
            if seq == next_seq:
                f.write(payload)
                received += len(payload)
                send_ack(sock, peer_addr, seq)
                next_seq += 1

                # if finished, send FIN and return
                if received >= expected_bytes:
                    send_fin(sock, peer_addr)
                    return True

                # wait for next DATA (timeout after ACK)
                pkt, addr = recv_with_timeout(sock, TIMEOUT_S)
                if pkt is None:
                    print("Data transmission terminated prematurely.")
                    return False
            else:
                # out-of-order or duplicate; re-ACK last received
                send_ack(sock, peer_addr, next_seq - 1)
                pkt, addr = recv_with_timeout(sock, TIMEOUT_S)
                if pkt is None:
                    print("Data transmission terminated prematurely.")
                    return False

def sender_send_file(sock, peer_addr, file_path):
    """
    Sender logic (client on PUT, server on GET).
    Implements:
      - LEN first
      - DATA 1000-byte chunks
      - Timeout after DATA: if no ACK within 1s
      - Wait for receiver FIN upon completion
    """
    filesize = os.path.getsize(file_path)
    send_len(sock, peer_addr, filesize)

    seq = 0
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            send_data(sock, peer_addr, seq, chunk)

            # wait for ACK:<seq> within 1s
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
                # wrong ack -> treat as failure (simple stop-and-wait)
                print("Did not receive ACK. Terminating.")
                return False
            seq += 1

    # wait for FIN from receiver
    fin, _ = recv_with_timeout(sock, TIMEOUT_S)
    if fin != b"FIN":
        print("Did not receive ACK. Terminating.")
        return False
    return True

# ====== server main ======
def server_loop(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("", port))
    print(f"UDP server listening on port {port} ...")

    while True:
        # control plane: wait for a command
        data, addr = sock.recvfrom(65535)
        if not data:
            continue

        text = data.decode(errors="ignore")
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()

        # QUIT just ends the server process (optional convenience)
        if cmd == "quit":
            print(f"Quit received from {addr}.")
            break

        # PUT <filename>
        if cmd == "put" and len(parts) == 2:
            client_ip = addr[0]
            basename = os.path.basename(parts[1])
            save_dir = os.path.join("Server_dir", client_ip)
            os.makedirs(save_dir, exist_ok=True)
            save_path = os.path.join(save_dir, basename)

            # Expect LEN next
            len_pkt, _ = recv_with_timeout(sock, TIMEOUT_S)
            if len_pkt is None or not len_pkt.startswith(b"LEN:"):
                print("Did not receive data. Terminating.")
                continue
            try:
                total_bytes = int(len_pkt.decode().split(":")[1])
            except Exception:
                print("Did not receive data. Terminating.")
                continue

            ok = receiver_receive_file(sock, addr, save_path, total_bytes)
            if ok:
                # Inform client (user message parity with Part 1 is not required by spec here,
                # but we keep a friendly note in server logs)
                print(f"Received {basename} from {client_ip} ({total_bytes} bytes).")

        # GET <server_file_path>
        elif cmd == "get" and len(parts) == 2:
            server_path = parts[1]
            if not os.path.exists(server_path):
                # politely tell client it's missing (client will just time out per UDP spec,
                # but we add a small courtesy)
                sock.sendto(b"LEN:0", addr)  # 0 -> client will expect nothing and timeout
                continue

            ok = sender_send_file(sock, addr, server_path)
            if ok:
                print(f"Sent {os.path.basename(server_path)} to {addr[0]}")

        else:
            # ignore unknown commands
            pass

    sock.close()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 serverUDP.py <port>")
        sys.exit(1)
    server_loop(int(sys.argv[1]))
