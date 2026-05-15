import os
import io
import re
import time
from urllib.parse import urlparse

import pandas as pd
import requests
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

HUNTER_API_KEY = os.environ.get("HUNTER_API_KEY", "")

HIGH_KEYWORDS = [
    "sales", "account", "business development", "bdm", "commercial",
    "parts", "spare", "procurement", "purchasing", "purchase",
    "sourcing", "supply", "supplier", "buyer", "import", "export",
    "product manager", "category manager"
]

DECISION_KEYWORDS = [
    "manager", "director", "head", "chief", "general manager",
    "owner", "founder", "ceo", "president", "operations"
]

EXCLUDE_KEYWORDS = [
    "hr", "human resources", "recruit", "career", "finance",
    "accounts payable", "accounts receivable", "invoice", "billing",
    "marketing", "brand", "graphic", "designer", "webmaster",
    "software", "developer", "technician", "service technician",
    "mechanic", "admin", "reception"
]

GENERIC_PRIORITY_EMAILS = [
    "sales@", "parts@", "purchasing@", "procurement@", "buying@",
    "imports@", "import@", "exports@", "export@", "enquiries@",
    "inquiries@", "info@"
]

GENERIC_EXCLUDE_EMAILS = [
    "careers@", "jobs@", "hr@", "accounts@", "invoice@", "billing@",
    "marketing@", "webmaster@", "support@"
]


def clean_domain(value):
    value = str(value).strip()
    if not value or value.lower() == "nan":
        return ""
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    parsed = urlparse(value)
    domain = parsed.netloc or parsed.path
    domain = domain.replace("www.", "").split("/")[0].strip()
    return domain


def priority_score(row):
    email = str(row.get("Email", "")).lower()
    position = str(row.get("Position", "")).lower()
    department = str(row.get("Department", "")).lower()
    seniority = str(row.get("Seniority", "")).lower()
    type_ = str(row.get("Type", "")).lower()
    text = " ".join([email, position, department, seniority, type_])

    score = 0
    reasons = []

    for keyword in HIGH_KEYWORDS:
        if keyword in text:
            score += 30
            reasons.append(keyword)

    for keyword in DECISION_KEYWORDS:
        if keyword in text:
            score += 15
            reasons.append(keyword)

    for keyword in GENERIC_PRIORITY_EMAILS:
        if keyword in email:
            score += 25
            reasons.append(keyword)

    for keyword in GENERIC_EXCLUDE_EMAILS:
        if keyword in email:
            score -= 40
            reasons.append("exclude:" + keyword)

    for keyword in EXCLUDE_KEYWORDS:
        if keyword in text:
            score -= 30
            reasons.append("exclude:" + keyword)

    if type_ == "personal":
        score += 5

    try:
        confidence = int(float(row.get("Confidence", 0) or 0))
        if confidence >= 90:
            score += 10
        elif confidence >= 70:
            score += 5
    except Exception:
        pass

    if score >= 55:
        priority = "A - Send First"
    elif score >= 30:
        priority = "B - Send If Needed"
    else:
        priority = "Exclude"

    return score, priority, ", ".join(dict.fromkeys(reasons))


def read_domains_from_excel(file_storage):
    df = pd.read_excel(file_storage, header=None)
    websites = []

    for value in df.iloc[:, 0].dropna().tolist():
        raw = str(value).strip()
        domain = clean_domain(raw)
        if domain:
            websites.append((raw, domain))

    seen = set()
    unique_sites = []
    for raw, domain in websites:
        if domain not in seen:
            unique_sites.append((raw, domain))
            seen.add(domain)

    return unique_sites


def hunter_domain_search(domain):
    endpoint = "https://api.hunter.io/v2/domain-search"
    params = {
        "domain": domain,
        "api_key": HUNTER_API_KEY,
        "limit": 100
    }
    response = requests.get(endpoint, params=params, timeout=45)
    return response


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "service": "Hunter Email Server",
        "status": "running",
        "endpoints": ["/health", "/extract-priority-emails", "/openapi.json"]
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "hunter_api_key_loaded": bool(HUNTER_API_KEY)
    })


@app.route("/extract-priority-emails", methods=["POST"])
def extract_priority_emails():
    if not HUNTER_API_KEY:
        return jsonify({"error": "HUNTER_API_KEY environment variable is missing."}), 500

    if "file" not in request.files:
        return jsonify({"error": "Please upload an Excel file using form field name 'file'."}), 400

    uploaded_file = request.files["file"]

    try:
        unique_sites = read_domains_from_excel(uploaded_file)
    except Exception as exc:
        return jsonify({"error": f"Failed to read Excel file: {str(exc)}"}), 400

    results = []

    for idx, (website, domain) in enumerate(unique_sites, start=1):
        try:
            response = hunter_domain_search(domain)

            if response.status_code == 200:
                data = response.json()
                info = data.get("data", {})
                company = info.get("organization", "")
                emails = info.get("emails", [])

                if emails:
                    for e in emails:
                        sources = e.get("sources", [])
                        source_urls = ", ".join([
                            s.get("uri", "") for s in sources[:5] if isinstance(s, dict)
                        ])

                        results.append({
                            "No": idx,
                            "Original Website": website,
                            "Domain": domain,
                            "Status": "FOUND",
                            "Company": company,
                            "Email": e.get("value", ""),
                            "Type": e.get("type", ""),
                            "Confidence": e.get("confidence", ""),
                            "First Name": e.get("first_name", ""),
                            "Last Name": e.get("last_name", ""),
                            "Position": e.get("position", ""),
                            "Department": e.get("department", ""),
                            "Seniority": e.get("seniority", ""),
                            "LinkedIn": e.get("linkedin", ""),
                            "Twitter": e.get("twitter", ""),
                            "Phone Number": e.get("phone_number", ""),
                            "Source URLs": source_urls,
                            "Message": ""
                        })
                else:
                    results.append({
                        "No": idx,
                        "Original Website": website,
                        "Domain": domain,
                        "Status": "NO EMAIL FOUND",
                        "Company": company,
                        "Email": "",
                        "Type": "",
                        "Confidence": "",
                        "First Name": "",
                        "Last Name": "",
                        "Position": "",
                        "Department": "",
                        "Seniority": "",
                        "LinkedIn": "",
                        "Twitter": "",
                        "Phone Number": "",
                        "Source URLs": "",
                        "Message": "No email found by Hunter"
                    })

            else:
                results.append({
                    "No": idx,
                    "Original Website": website,
                    "Domain": domain,
                    "Status": "API ERROR",
                    "Company": "",
                    "Email": "",
                    "Type": "",
                    "Confidence": "",
                    "First Name": "",
                    "Last Name": "",
                    "Position": "",
                    "Department": "",
                    "Seniority": "",
                    "LinkedIn": "",
                    "Twitter": "",
                    "Phone Number": "",
                    "Source URLs": "",
                    "Message": f"HTTP {response.status_code}: {response.text[:300]}"
                })

        except Exception as exc:
            results.append({
                "No": idx,
                "Original Website": website,
                "Domain": domain,
                "Status": "ERROR",
                "Company": "",
                "Email": "",
                "Type": "",
                "Confidence": "",
                "First Name": "",
                "Last Name": "",
                "Position": "",
                "Department": "",
                "Seniority": "",
                "LinkedIn": "",
                "Twitter": "",
                "Phone Number": "",
                "Source URLs": "",
                "Message": str(exc)
            })

        time.sleep(0.25)

    result_df = pd.DataFrame(results)

    if not result_df.empty:
        priority_data = result_df.apply(priority_score, axis=1, result_type="expand")
        result_df["Priority Score"] = priority_data[0]
        result_df["Priority"] = priority_data[1]
        result_df["Priority Reason"] = priority_data[2]

    priority_df = result_df[
        (result_df["Status"] == "FOUND") &
        (result_df["Email"].astype(str).str.contains("@", na=False)) &
        (result_df["Priority"].isin(["A - Send First", "B - Send If Needed"]))
    ].copy()

    if not priority_df.empty:
        priority_order = {"A - Send First": 1, "B - Send If Needed": 2}
        priority_df["Priority Order"] = priority_df["Priority"].map(priority_order)
        priority_df = priority_df.sort_values(
            by=["Priority Order", "Domain", "Priority Score", "Confidence"],
            ascending=[True, True, False, False]
        ).drop(columns=["Priority Order"])

    summary = result_df.groupby("Status", dropna=False).size().reset_index(name="Count") if not result_df.empty else pd.DataFrame(columns=["Status", "Count"])
    priority_summary = priority_df.groupby("Priority", dropna=False).size().reset_index(name="Count") if not priority_df.empty else pd.DataFrame(columns=["Priority", "Count"])
    input_df = pd.DataFrame(unique_sites, columns=["Original Website", "Domain"])

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        priority_df.to_excel(writer, index=False, sheet_name="Priority Contacts")
        result_df.to_excel(writer, index=False, sheet_name="All Hunter Results")
        priority_summary.to_excel(writer, index=False, sheet_name="Priority Summary")
        summary.to_excel(writer, index=False, sheet_name="Summary")
        input_df.to_excel(writer, index=False, sheet_name="Input Domains")

    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="hunter_priority_sales_contacts.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@app.route("/openapi.json", methods=["GET"])
def openapi():
    server_url = request.url_root.rstrip("/")
    schema = {
        "openapi": "3.1.0",
        "info": {
            "title": "Hunter Priority Email Extraction API",
            "version": "1.0.0",
            "description": "Upload an Excel file containing website URLs and receive an Excel file with priority sales contacts extracted via Hunter."
        },
        "servers": [
            {"url": server_url}
        ],
        "paths": {
            "/health": {
                "get": {
                    "operationId": "healthCheck",
                    "summary": "Check server status",
                    "responses": {
                        "200": {
                            "description": "Server health status",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object"
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/extract-priority-emails": {
                "post": {
                    "operationId": "extractPriorityEmails",
                    "summary": "Extract priority sales emails from uploaded Excel website list",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "multipart/form-data": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "file": {
                                            "type": "string",
                                            "format": "binary",
                                            "description": "Excel file containing website URLs or domains in the first column."
                                        }
                                    },
                                    "required": ["file"]
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Excel file containing priority sales contacts",
                            "content": {
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {
                                    "schema": {
                                        "type": "string",
                                        "format": "binary"
                                    }
                                }
                            }
                        },
                        "400": {
                            "description": "Invalid request"
                        },
                        "500": {
                            "description": "Server error"
                        }
                    }
                }
            }
        }
    }
    return jsonify(schema)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
