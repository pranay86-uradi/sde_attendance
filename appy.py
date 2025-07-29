import io
import datetime
import numpy as np
import requests
import cv2
import face_recognition
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
import boto3
import jwt  # PyJWT library required

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
CORS(app, supports_credentials=True)
app.secret_key = "6fbddac15a265c69d2eb00895189d4342e6bb0f48c74bf82fab0d"  # Keep this secure if used for sessions

# AWS config (move to env vars in production!)
S3_BUCKET = "attandanceuploadfiles"
S3_REGION = "ap-south-1"
S3_ACCESS_KEY = "AKIAVA5YK6M3PXJD7747"
S3_SECRET_KEY = "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"

LAMBDA_FACECAPTURE_URL = "https://qkklhv6xpa.execute-api.ap-south-1.amazonaws.com/Dev/api/employee/attendance/capture-image"
ATTENDANCE_API_URL = "https://qkklhv6xpa.execute-api.ap-south-1.amazonaws.com/Dev/api/employee/attendance/checkin-checkout"

s3_client = boto3.client(
    "s3",
    aws_access_key_id=S3_ACCESS_KEY,
    aws_secret_access_key=S3_SECRET_KEY,
    region_name=S3_REGION
)

def upload_to_s3(file_stream, user_id, file_extension='jpg'):
    filename = f"{user_id}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}.{file_extension}"
    try:
        s3_client.upload_fileobj(
            file_stream,
            S3_BUCKET,
            filename,
            ExtraArgs={'ContentType': 'image/jpeg'}
        )
        return f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{filename}"
    except Exception as e:
        logging.error(f"Failed to upload to S3: {e}")
        raise Exception(f"Failed to upload to S3: {str(e)}")

def decode_jwt(token):
    try:
        decoded = jwt.decode(token, options={"verify_signature": False})
        return decoded
    except Exception as e:
        logging.warning(f"JWT decoding failed: {e}")
        return None

def get_token_from_header():
    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth_header:
        return None
    parts = auth_header.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]

@app.route("/facecapture", methods=["POST"])
def face_capture():
    token = get_token_from_header()
    if not token:
        return jsonify({"success": False, "error": "Authorization header missing or malformed."}), 401

    decoded = decode_jwt(token)
    if not decoded:
        return jsonify({"success": False, "error": "Invalid or expired token."}), 401

    UserId = decoded.get("UserId") or decoded.get("userId")
    companyId = decoded.get("companyId")
    if not UserId or not companyId:
        return jsonify({"success": False, "error": "UserId or companyId missing in token."}), 400

    image = request.files.get("photo")
    if not image:
        return jsonify({"success": False, "error": "No image uploaded."}), 400

    try:
        if image.mimetype not in ["image/jpeg", "image/png"]:
            return jsonify({"success": False, "error": "Invalid image format."}), 400

        image_bytes = image.read()
        if len(image_bytes) > 2 * 1024 * 1024:
            return jsonify({"success": False, "error": "Image too large."}), 400

        image_stream = io.BytesIO(image_bytes)
        image_url = upload_to_s3(image_stream, UserId)

        nparr = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if frame is None:
            return jsonify({"success": False, "error": "Invalid image data."}), 400

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        encodings = face_recognition.face_encodings(rgb_frame)
        if len(encodings) != 1:
            return jsonify({"success": False, "error": "Ensure exactly one face is present in the image."}), 400

        encoding = encodings[0].tolist()
        payload = {
            "face_encoding": [float(x) for x in encoding],
            "image_url": image_url
        }
        headers = {
            "Authorization": f"Bearer {token}"
        }
        response = requests.post(LAMBDA_FACECAPTURE_URL, json=payload, headers=headers)
        data = response.json()
        if response.ok:
            return jsonify({"success": True, "data": data}), response.status_code
        else:
            return jsonify({"success": False, "error": data.get("error", "Lambda error"), "data": data}), response.status_code
    except Exception as e:
        logging.error(f"Face capture error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/mark_attendance", methods=["POST"])
def mark_attendance():
    action = request.form.get("action")
    image = request.files.get("photo")
    if not all([action, image]):
        return jsonify({"success": False, "error": "Missing required fields."}), 400

    token = get_token_from_header() or ""
    try:
        image_bytes = image.read()
        nparr = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if frame is None:
            return jsonify({"success": False, "error": "Invalid image data."}), 400

        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        encodings = face_recognition.face_encodings(rgb_frame)
        if len(encodings) != 1:
            return jsonify({"success": False, "error": "Please ensure exactly one face is visible."}), 400

        face_encoding = encodings[0].tolist()
        payload = {
            "action": action,
            "face_encoding": [float(x) for x in face_encoding]
        }
        headers = {
            "Authorization": f"Bearer {token}"
        }
        response = requests.post(ATTENDANCE_API_URL, json=payload, headers=headers)
        data = response.json()
        if response.ok:
            return jsonify({"success": True, "data": data}), response.status_code
        else:
            return jsonify({"success": False, "error": data.get("error", "Attendance API error"), "data": data}), response.status_code
    except Exception as e:
        logging.error(f"Error marking attendance: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="13.201.133.191", port=5000, debug=True)
