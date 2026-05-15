import os
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

HUNTER_API_KEY = os.environ.get("HUNTER_API_KEY", "")
DOWNLOAD_DIR = Path("/tmp/hunter_downloads")
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

def clean_domain(value):
    value = str(value).strip()
    if not value or value.lower() == "nan":
        return ""
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    parsed = urlparse(value)
    domain = parsed.netloc or parsed.path
    return domain.replace("www.", "").split("/")[0].strip()

def normalize_websites(websites):
    rows, seen = [], set()
    for item in websites:
        raw = str(item).strip()
        domain = clean_domain(raw)
        if domain and domain not in seen:
            rows.append({"Original Website": raw, "Domain": domain})
            seen.add(domain)
    return rows

def priority_score(row):
    email = str(row.get("Email", "")).lower()
    position = str(row.get("Position", "")).lower()
    department = str(row.get("Department", "")).lower()
    seniority = str(row.get("Seniority", "")).lower()
    type_ = str(row.get("Type", "")).lower()
    text = " ".join([email, position, department, seniority, type_])

    high = ["sales","account","business development","bdm","commercial","parts","spare","procurement","purchasing","purchase","sourcing","supply","supplier","buyer","import","export","product manager","category manager"]
    decision = ["manager","director","head","chief","general manager","owner","founder","ceo","president","operations"]
    exclude = ["hr","human resources","recruit","career","finance","accounts payable","accounts receivable","invoice","billing","marketing","brand","graphic","designer","webmaster","software","developer","technician","service technician","mechanic","admin","reception"]
    generic_good = ["sales@","parts@","purchasing@","procurement@","buying@","imports@","import@","exports@","export@","enquiries@","inquiries@","info@"]
    generic_bad = ["careers@","jobs@","hr@","accounts@","invoice@","billing@","marketing@","webmaster@","support@"]

    score, reasons = 0, []
    for k in high:
        if k in text:
            score += 30; reasons.append(k)
    for k in decision:
        if k in text:
            score += 15; reasons.append(k)
    for k in generic_good:
        if k in email:
            score += 25; reasons.append(k)
    for k in generic_bad:
        if k in email:
            score -= 40; reasons.append("exclude:" + k)
    for k in exclude:
        if k in text:
            score -= 30; reasons.append("exclude:" + k)
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
        priority = "C - Low / Exclude"

    return score, priority, ", ".join(dict.fromkeys(reasons))

def hunter_domain_search_all(domain):
    all_emails, company, errors = [], "", []
    limit, offset, max_pages = 100, 0, 20

    for _ in range(max_pages):
        params = {
            "domain": domain,
            "api_key": HUNTER_API_KEY,
            "limit": limit,
            "offset": offset
        }
        response = requests.get("https://api.hunter.io/v2/domain-search", params=params, timeout=60)

        if response.status_code != 200:
            errors.append(f"HTTP {response.status_code}: {response.text[:300]}")
            break

        data = response.json()
        info = data.get("data", {})
        company = info.get("organization", company)
        emails = info.get("emails", []) or []
        all_emails.extend(emails)

        if len(emails) < limit:
            break

        offset += limit
        time.sleep(0.2)

    return company, all_emails, errors

def build_rows(websites):
    input_sites = normalize_websites(websites)
    rows = []

    for idx, item in enumerate(input_sites, start=1):
        website, domain = item["Original Website"], item["Domain"]
        try:
            company, emails, errors = hunter_domain_search_all(domain)

            if errors:
                rows.append({"No": idx, "Original Website": website, "Domain": domain, "Status": "API ERROR", "Company": company, "Email": "", "Message": " / ".join(errors)})
                continue

            if not emails:
                rows.append({"No": idx, "Original Website": website, "Domain": domain, "Status": "NO EMAIL FOUND", "Company": company, "Email": "", "Message": "No email found by Hunter"})
                continue

            for e in emails:
                sources = e.get("sources", []) or []
                source_urls = ", ".join([str(s.get("uri", "")) for s in sources if isinstance(s, dict) and s.get("uri")])
                row = {
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
                    "Source Count": len(sources),
                    "Source URLs": source_urls,
                    "Message": ""
                }
                score, priority, reason = priority_score(row)
                row["Priority Score"] = score
                row["Priority"] = priority
                row["Priority Reason"] = reason
                rows.append(row)

        except Exception as exc:
            rows.append({"No": idx, "Original Website": website, "Domain": domain, "Status": "ERROR", "Company": "", "Email": "", "Message": str(exc)})

        time.sleep(0.25)

    return input_sites, rows

def create_excel_file(input_sites, rows):
    result_df = pd.DataFrame(rows)

    for col in ["Status", "Email", "Domain", "Priority"]:
        if col not in result_df.columns:
            result_df[col] = ""

    found_df = result_df[
        (result_df["Status"] == "FOUND") &
        (result_df["Email"].astype(str).str.contains("@", na=False))
    ].copy()

    priority_df = found_df[
        found_df["Priority"].isin(["A - Send First", "B - Send If Needed"])
    ].copy()

    summary_df = result_df.groupby("Status", dropna=False).size().reset_index(name="Count") if not result_df.empty else pd.DataFrame(columns=["Status", "Count"])
    domain_count_df = found_df.groupby("Domain", dropna=False).size().reset_index(name="Email Count") if not found_df.empty else pd.DataFrame(columns=["Domain", "Email Count"])
    input_df = pd.DataFrame(input_sites)

    filename = f"hunter_all_emails_{uuid.uuid4().hex[:10]}.xlsx"
    filepath = DOWNLOAD_DIR / filename

    with pd.ExcelWriter(filepath, engine="openpyxl") as writer:
        found_df.to_excel(writer, index=False, sheet_name="All Found Emails")
        priority_df.to_excel(writer, index=False, sheet_name="Priority Contacts")
        result_df.to_excel(writer, index=False, sheet_name="Raw Results")
        domain_count_df.to_excel(writer, index=False, sheet_name="Email Count by Domain")
        summary_df.to_excel(writer, index=False, sheet_name="Status Summary")
        input_df.to_excel(writer, index=False, sheet_name="Input Domains")

    return filename, filepath, len(input_sites), len(rows), len(found_df)

@app.route("/", methods=["GET"])
def home():
    return jsonify({"service": "Hunter Download URL Server", "status": "running"})

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "hunter_api_key_loaded": bool(HUNTER_API_KEY)})

@app.route("/extract-all-emails-file", methods=["POST"])
def extract_all_emails_file():
    if not HUNTER_API_KEY:
        return jsonify({"error": "HUNTER_API_KEY environment variable is missing."}), 500

    body = request.get_json(silent=True) or {}
    websites = body.get("websites", [])

    if not isinstance(websites, list) or len(websites) == 0:
        return jsonify({"error": "Please provide websites as a JSON array."}), 400

    input_sites, rows = build_rows(websites)
    filename, filepath, site_count, row_count, found_count = create_excel_file(input_sites, rows)

    base_url = request.url_root.rstrip("/")
    return jsonify({
        "status": "success",
        "message": "Excel file created successfully.",
        "input_website_count": site_count,
        "raw_result_count": row_count,
        "found_email_count": found_count,
        "download_url": f"{base_url}/download/{filename}",
        "filename": filename
    })

@app.route("/download/<filename>", methods=["GET"])
def download_file(filename):
    filepath = DOWNLOAD_DIR / filename
    if not filepath.exists():
        return jsonify({"error": "File not found or expired. Please run extraction again."}), 404
    return send_file(
        filepath,
        as_attachment=True,
        download_name="hunter_all_emails.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route("/openapi.json", methods=["GET"])
def openapi():
    server_url = request.url_root.rstrip("/")
    return jsonify({
        "openapi": "3.1.0",
        "info": {
            "title": "Hunter Full Email Download API",
            "version": "4.0.0",
            "description": "Send website URLs as JSON. The server creates an XLSX file and returns a download URL."
        },
        "servers": [{"url": server_url}],
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
                                        "type": "object",
                                        "properties": {
                                            "status": {"type": "string"},
                                            "hunter_api_key_loaded": {"type": "boolean"}
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/extract-all-emails-file": {
                "post": {
                    "operationId": "extractAllEmailsFile",
                    "summary": "Extract all discovered emails and return an XLSX download URL",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "websites": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                            "description": "Website URLs or domains extracted from the uploaded Excel file."
                                        }
                                    },
                                    "required": ["websites"]
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "JSON response containing download URL",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "status": {"type": "string"},
                                            "message": {"type": "string"},
                                            "input_website_count": {"type": "integer"},
                                            "raw_result_count": {"type": "integer"},
                                            "found_email_count": {"type": "integer"},
                                            "download_url": {"type": "string"},
                                            "filename": {"type": "string"}
                                        }
                                    }
                                }
                            }
                        },
                        "400": {"description": "Invalid request"},
                        "500": {"description": "Server error"}
                    }
                }
            }
        }
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
