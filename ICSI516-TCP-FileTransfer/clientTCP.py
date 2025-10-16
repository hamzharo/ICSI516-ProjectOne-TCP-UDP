import socket
import sys
import os

def client_program(server_ip, server_port):
    while True:
        command = input("Enter command (put/get/quit): ").strip()
        parts = command.split()

        if not parts:
            continue
        cmd = parts[0]

        # QUIT
        if cmd == "quit":
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((server_ip, server_port))
                s.sendall(command.encode())
            print("Connection closed.")
            break

        # PUT
        elif cmd == "put" and len(parts) == 2:
            filepath = parts[1]
            if not os.path.exists(filepath):
                print("File not found.")
                continue

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((server_ip, server_port))
                s.sendall(command.encode())

                with open(filepath, "rb") as f:
                    while chunk := f.read(4096):
                        s.sendall(chunk)

                s.shutdown(socket.SHUT_WR)
                msg = s.recv(1024).decode()
                print(msg)

        # GET
        elif cmd == "get" and len(parts) == 2:
            filename = os.path.basename(parts[1])

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((server_ip, server_port))
                s.sendall(command.encode())

                status = s.recv(1024).decode()

                if status.startswith("ERROR"):
                    print(status)
                    # Don’t use “continue” outside the loop context of socket
                    # Just skip the rest by using `pass`
                    pass

                elif status == "FOUND":
                    os.makedirs("Client_dir", exist_ok=True)
                    save_path = os.path.join("Client_dir", filename)

                    with open(save_path, "wb") as f:
                        while True:
                            data = s.recv(4096)
                            if not data or b"END" in data:
                                break
                            f.write(data)
                    print("File delivered from server.")
                else:
                    print("Invalid response from server.")

        else:
            print("Invalid command or syntax.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 clientTCP.py <server_ip> <server_port>")
        sys.exit(1)

    client_program(sys.argv[1], int(sys.argv[2]))
