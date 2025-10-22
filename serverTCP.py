import socket
import os
import sys

def start_server(port):
    # Create TCP socket
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind(('', port))
    server_socket.listen(1)
    print(f"Server listening on port {port}...")

    while True:
        conn, addr = server_socket.accept()
        print(f"Connection established with {addr}")
        client_ip = addr[0]

        # Receive command from client
        command = conn.recv(1024).decode().strip()
        if not command:
            conn.close()
            continue

        parts = command.split()
        cmd = parts[0]

        # parts = command.split()
        # cmd = parts[0]
        # fake_ip = parts[-1] if len(parts) > 2 else None
        # client_ip = fake_ip if fake_ip else addr[0]

        # Handle PUT
        if cmd == "put" and len(parts) == 2:
            filename = os.path.basename(parts[1])
            client_folder = os.path.join("uploads", client_ip)
            os.makedirs(client_folder, exist_ok=True)
            filepath = os.path.join(client_folder, filename)

            with open(filepath, "wb") as f:
                print(f"Receiving file: {filename} from {client_ip}")
                while True:
                    data = conn.recv(4096)
                    if not data:
                        break
                    f.write(data)

            print(f"File {filename} saved to {filepath}")
            conn.sendall(b"File successfully uploaded.")
            conn.close()

        # Handle GET
        elif cmd == "get" and len(parts) == 2:
            filename = os.path.basename(parts[1])
            filepath = os.path.join("uploads", client_ip, filename)

            if os.path.exists(filepath):
                conn.sendall(b"FOUND")
                with open(filepath, "rb") as f:
                    while chunk := f.read(4096):
                        conn.sendall(chunk)
                conn.sendall(b"END")  # indicate end
                print(f"File {filename} sent to {client_ip}")

            else:
                conn.sendall(b"ERROR: File not found")
                print(f"File {filename} not found for {client_ip}")
            conn.close()

        # Handle QUIT
        elif cmd == "quit":
            print(f"Client {client_ip} disconnected.")
            conn.close()
            break

        else:
            conn.sendall(b"Invalid command.")
            conn.close()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 serverTCP.py <port>")
        sys.exit(1)

    port = int(sys.argv[1])
    start_server(port)
