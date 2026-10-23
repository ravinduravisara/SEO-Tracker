import socket
import threading

def forward(src, dst):
    try:
        while True:
            data = src.recv(4096)
            if not data:
                break
            dst.sendall(data)
    except Exception:
        pass
    finally:
        try:
            src.close()
        except Exception:
            pass
        try:
            dst.close()
        except Exception:
            pass

def handle_client(client_sock):
    try:
        backend_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        backend_sock.connect(('127.0.0.1', 8001))
        t1 = threading.Thread(target=forward, args=(client_sock, backend_sock), daemon=True)
        t2 = threading.Thread(target=forward, args=(backend_sock, client_sock), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
    except Exception:
        try:
            client_sock.close()
        except Exception:
            pass

def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(('127.0.0.1', 8000))
        server.listen(128)
        print("Proxy running on port 8000 -> 8001")
        while True:
            client_sock, _ = server.accept()
            threading.Thread(target=handle_client, args=(client_sock,), daemon=True).start()
    except Exception as e:
        print("Proxy failed to bind port 8000:", e)

if __name__ == '__main__':
    main()
