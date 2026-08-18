"""S3 lokal (moto) untuk environment PREVIEW saja — menggantikan MinIO yang tidak tersedia di pod ini.
Jalankan: nohup python /app/backend/tests/_preview_s3_server.py > /tmp/preview_s3.log 2>&1 &
"""
import os
import boto3
from moto.server import ThreadedMotoServer

PORT = int(os.environ.get("PREVIEW_S3_PORT", "9100"))
BUCKET = os.environ.get("PREVIEW_S3_BUCKET", "danatalang-test")

server = ThreadedMotoServer(port=PORT)
server.start()
boto3.client(
    "s3", endpoint_url=f"http://127.0.0.1:{PORT}",
    aws_access_key_id="testkey", aws_secret_access_key="testsecret", region_name="us-east-1",
).create_bucket(Bucket=BUCKET)
print(f"preview s3 ready on {PORT} bucket {BUCKET}", flush=True)
import threading
threading.Event().wait()
