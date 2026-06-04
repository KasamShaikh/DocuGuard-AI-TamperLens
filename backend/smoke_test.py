import io
import json
import time
import http.client
import uuid

from PIL import Image

buf = io.BytesIO()
Image.new("RGB", (400, 300), (120, 140, 160)).save(buf, "JPEG")
img = buf.getvalue()

boundary = uuid.uuid4().hex


def field(name, value):
    return (
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
    ).encode()


def filefield(name, filename, content, ctype):
    return (
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
        f'filename="{filename}"\r\nContent-Type: {ctype}\r\n\r\n'
    ).encode() + content + b"\r\n"


body = field("doc_type", "kyc")
body += filefield("file", "test.jpg", img, "image/jpeg")
body += f"--{boundary}--\r\n".encode()

conn = http.client.HTTPConnection("127.0.0.1", 8000)
conn.request(
    "POST", "/api/analyze", body,
    {"Content-Type": f"multipart/form-data; boundary={boundary}"},
)
resp = conn.getresponse()
data = json.loads(resp.read())
print("submit", resp.status, data)
aid = data["analysis_id"]

for _ in range(25):
    time.sleep(0.8)
    c2 = http.client.HTTPConnection("127.0.0.1", 8000)
    c2.request("GET", f"/api/analyze/{aid}")
    d2 = json.loads(c2.getresponse().read())
    if d2["status"] in ("completed", "failed"):
        print("final status:", d2["status"])
        print("tamper_score:", d2["tamper_score"], "decision:", d2["decision"])
        print("llm:", json.dumps(d2["llm_summary"])[:400])
        print("detectors:", len(d2["detector_scores"].get("detectors", [])))
        break
else:
    print("did not complete")
