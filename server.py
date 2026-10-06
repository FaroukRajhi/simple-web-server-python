#!/usr/bin/env python3
import socket
import os
import mimetypes
from urllib.parse import unquote, urlparse
from datetime import datetime

# ---------- Configuration ----------
HOST = "0.0.0.0"
PORT = 8080
DOCUMENT_ROOT = os.path.join(os.path.dirname(__file__), "public")
BUFFER_SIZE = 8192

# Make sure the public dir exists
os.makedirs(DOCUMENT_ROOT, exist_ok=True)


def parse_request(raw: bytes):
    """Parse the HTTP request line and headers."""
    text = raw.decode("iso-8859-1")  # HTTP headers are latin-1 per RFC 7230
    head, _, _body = text.partition("\r\n\r\n")
    lines = head.split("\r\n")

    if not lines or not lines[0]:
        return None

    method, uri, version = (lines[0].split(" ") + ["", ""])[:3]

    headers = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()

    return {
        "method": method,
        "uri": uri,
        "version": version,
        "headers": headers,
    }


def build_response(status: str, body: bytes, content_type: str, method: str):
    """Construct a raw HTTP/1.1 response."""
    headers = [
        f"HTTP/1.1 {status}",
        f"Content-Type: {content_type}",
        f"Content-Length: {len(body)}",
        "Connection: close",
        f"Date: {datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')}",
        "Server: PyPureServer/1.0",
    ]
    head = ("\r\n".join(headers) + "\r\n\r\n").encode("iso-8859-1")
    if method == "HEAD":
        return head
    return head + body


def handle_client(conn: socket.socket):
    """Read one request, send one response, close."""
    conn.settimeout(5.0)

    # ---------- 1. Read until we see the end of headers ----------
    raw = b""
    try:
        while b"\r\n\r\n" not in raw and len(raw) < 65536:
            chunk = conn.recv(BUFFER_SIZE)
            if not chunk:
                break
            raw += chunk
    except socket.timeout:
        conn.close()
        return

    if not raw:
        conn.close()
        return

    # ---------- 2. Parse ----------
    req = parse_request(raw)
    if req is None:
        conn.close()
        return

    print(f"[{datetime.now():%H:%M:%S}] {req['method']} {req['uri']}")

    method = req["method"]
    uri = req["uri"]

    # ---------- 3. Map URI -> file path ----------
    path = unquote(urlparse(uri).path or "/")

    # Prevent directory traversal
    path = path.replace("\x00", "")
    safe_path = os.path.normpath(path).lstrip("/\\")
    file_path = os.path.join(DOCUMENT_ROOT, safe_path)

    # If a directory, default to index.html
    if os.path.isdir(file_path):
        file_path = os.path.join(file_path, "index.html")

    # ---------- 4. Build the response ----------
    if method not in ("GET", "HEAD"):
        body = b"<h1>405 Method Not Allowed</h1>"
        response = build_response("405 Method Not Allowed", body, "text/html; charset=utf-8", method)

    elif os.path.isfile(file_path):
        with open(file_path, "rb") as f:
            body = f.read()
        mime, _ = mimetypes.guess_type(file_path)
        mime = mime or "application/octet-stream"
        if mime.startswith("text/"):
            mime += "; charset=utf-8"
        response = build_response("200 OK", body, mime, method)

    else:
        body = f"<h1>404 Not Found</h1><p>{safe_path!r} not found.</p>".encode()
        response = build_response("404 Not Found", body, "text/html; charset=utf-8", method)

    # ---------- 5. Send and close ----------
    try:
        conn.sendall(response)
    except (BrokenPipeError, ConnectionResetError):
        pass
    finally:
        conn.close()


def serve():
    """Main accept loop."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((HOST, PORT))
        sock.listen(64)
        print(f"Server running on http://{HOST}:{PORT}")

        while True:
            try:
                client, addr = sock.accept()
            except KeyboardInterrupt:
                print("\nShutting down.")
                break
            handle_client(client)


if __name__ == "__main__":
    serve()