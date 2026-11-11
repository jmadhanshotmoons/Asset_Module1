"""HTTP API for Module 1 (no web page). Run: gunicorn server:app

Endpoints
  GET  /health              -> {"ok": true}            (for the host's health check)
  GET  /api/status          -> AI provider and whether a password is required
  POST /api/asset/clean     multipart form: file=<client .xlsx>, optional template=<.xlsx>, use_ai=1|0
                            -> the cleaned, highlighted .xlsx as a download (default)
                            -> JSON summary + base64 file with ?format=json

If APP_PASSWORD is set, send it in the X-App-Password header.
"""
from __future__ import annotations

import base64
import hmac
import io
import os

from flask import Flask, jsonify, request, send_file

from punctualiti import ai
from punctualiti.asset import clean_asset_file
from punctualiti.asset.cleaner import output_name
from punctualiti.env import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@app.after_request
def cors(resp):
    # Lets a separately hosted UI call this API. The password still protects the AI.
    origin = os.environ.get("CORS_ORIGIN")
    if origin:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Headers"] = "X-App-Password, Content-Type"
        resp.headers["Access-Control-Expose-Headers"] = "Content-Disposition, X-Rows, X-Red-Cells, X-Amber-Cells, X-AI-Status"
    return resp


def deployed_commit() -> str:
    """Git commit of the running deploy (set by Vercel / Render), for post-deploy checks."""
    return (os.environ.get("VERCEL_GIT_COMMIT_SHA") or os.environ.get("RENDER_GIT_COMMIT")
            or os.environ.get("GIT_COMMIT") or "unknown")


def _password_ok() -> bool:
    expected = os.environ.get("APP_PASSWORD", "")
    if not expected:
        return True
    return hmac.compare_digest(request.headers.get("X-App-Password", "").encode(), expected.encode())


@app.get("/")
@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "punctualiti-asset-module1", "commit": deployed_commit()})


@app.get("/api/status")
def status():
    return jsonify({"ai": ai.describe(), "ai_ready": ai.api_key_configured(),
                    "password_required": bool(os.environ.get("APP_PASSWORD")),
                    "commit": deployed_commit()})


@app.route("/api/asset/clean", methods=["POST", "OPTIONS"])
def clean():
    if request.method == "OPTIONS":
        return ("", 204)
    if not _password_ok():
        return jsonify({"error": "Wrong or missing X-App-Password."}), 401
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "Send the client's asset list as form field 'file' (.xlsx)."}), 400
    if not upload.filename.lower().endswith((".xlsx", ".xlsm")):
        return jsonify({"error": "Only .xlsx files are supported."}), 400
    template = request.files.get("template")
    use_ai = request.form.get("use_ai", "1") == "1"

    try:
        result = clean_asset_file(
            io.BytesIO(upload.read()),
            io.BytesIO(template.read()) if template and template.filename else None,
            use_ai=use_ai,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        app.logger.exception("clean failed")
        return jsonify({"error": f"Could not read that file ({type(e).__name__})."}), 422

    name = output_name(upload.filename)
    if request.args.get("format") == "json":
        return jsonify({
            "filename": name,
            "file_b64": base64.b64encode(result.content).decode("ascii"),
            "rows": result.rows, "red_cells": result.red_cells, "amber_cells": result.amber_cells,
            "ai_status": result.ai_status, "ai_provider": ai.describe(),
            "columns_report": result.column_report, "unmapped_columns": result.unmapped_columns,
            "issue_summary": result.issue_summary, "warnings": result.warnings,
        })

    resp = send_file(io.BytesIO(result.content), mimetype=XLSX, as_attachment=True, download_name=name)
    resp.headers["X-Rows"] = str(result.rows)
    resp.headers["X-Red-Cells"] = str(result.red_cells)
    resp.headers["X-Amber-Cells"] = str(result.amber_cells)
    resp.headers["X-AI-Status"] = result.ai_status.encode("ascii", "replace").decode()
    return resp


@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": "File is larger than 10 MB."}), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
