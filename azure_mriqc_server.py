#!/usr/bin/env python3

"""
azure_mriqc_server.py

This Flask API receives a POST request with:
  - 'bids_zip': A zip file containing a BIDS dataset
  - 'participant_label': (optional) subject ID (default: '01')

It unzips the data, finds the first directory, assumes it's the BIDS root,
runs `docker run nipreps/mriqc:<version>` to perform MRIQC,
and returns a zip of the results.
"""

from flask import Flask, request, send_file, jsonify
import subprocess
import os
import shutil
import zipfile
from pathlib import Path

app = Flask(__name__)

UPLOAD_FOLDER = "/tmp/mriqc_upload"
OUTPUT_FOLDER = "/tmp/mriqc_output"

# Ensure these directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

@app.route("/run-mriqc", methods=["POST"])
def run_mriqc():
    """
    Expects a POST with:
      - 'bids_zip': The BIDS dataset as a ZIP file
      - 'participant_label': The subject ID (optional, defaults to '01')

    Returns a ZIP of MRIQC derivatives if successful.
    """

    # 1) Parse incoming form data
    bids_zip = request.files.get("bids_zip")
    subj_id  = request.form.get("participant_label", "01")

    if not bids_zip:
        return jsonify({"error": "No BIDS zip provided"}), 400

    # 2) Clean up old data
    shutil.rmtree(UPLOAD_FOLDER, ignore_errors=True)
    shutil.rmtree(OUTPUT_FOLDER, ignore_errors=True)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    # 3) Save the uploaded zip
    zip_path = os.path.join(UPLOAD_FOLDER, "bids_data.zip")
    bids_zip.save(zip_path)

    # 4) Unzip BIDS data
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(UPLOAD_FOLDER)

    # 5) Dynamically find the first directory in UPLOAD_FOLDER
    #    That is assumed to be our BIDS root
    bids_root = None
    for item in Path(UPLOAD_FOLDER).iterdir():
        if item.is_dir():
            bids_root = item
            break

    if not bids_root:
        return jsonify({"error": "No BIDS directory found after unzipping."}), 400

    # 6) Run MRIQC in Docker
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{bids_root.absolute()}:/data:ro",   # mount BIDS as read-only
        "-v", f"{Path(OUTPUT_FOLDER).absolute()}:/out",  # mount output folder
        "nipreps/mriqc:22.0.6",  # or whichever version you use
        "/data", "/out",
        "participant",
        "--participant_label", subj_id,
        "-m", "T1w", "T2w", "bold"
    ]

    run_result = subprocess.run(cmd, capture_output=True, text=True)

    if run_result.returncode != 0:
        return jsonify({
            "error": "MRIQC failed",
            "stderr": run_result.stderr
        }), 500

    # 7) Zip the OUTPUT_FOLDER to return
    result_zip_path = "/tmp/mriqc_results.zip"
    shutil.make_archive(
        base_name=result_zip_path.replace(".zip",""),
        format="zip",
        root_dir=OUTPUT_FOLDER
    )

    # 8) Send results as a file
    return send_file(result_zip_path, as_attachment=True)


if __name__ == "__main__":
    # Bind to 0.0.0.0:8000 so it's externally accessible
    app.run(host="0.0.0.0", port=8000)
