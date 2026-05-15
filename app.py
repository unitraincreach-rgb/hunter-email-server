import os
import io
import time
from urllib.parse import urlparse

import pandas as pd
import requests
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
HUNTER_API_KEY = os.environ.get("HUNTER_API_KEY", "")


def clean_domain(value):
    value = str(value).strip()
    if not value or value.lower() == "nan":
        return ""
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    parsed = urlparse(value)
    domain = parsed.netloc or parsed.path
    return domain.replace("www.", "").split("/")[0].strip()


def priority_score(row):
    email = str(row.get("Email", "")).lower()
    position = str(row.get("Position", "")).lower()
    department = str(row.get("Department", "")).lower()
    seniority = str(row.get("Seniority", "")).lower()
    typ = str(row.get("Type", "")).lower()
    text = " ".join([email, position, department, seniority, typ])

    high_keywords = ["sales", "account", "business development", "bdm", "commercial", "parts", "spare", "procurement", "purchasing", "purchase", "sourcing", "supply", "supplier", "buyer", "import", "export", "product manager", "category manager"]
    decision_keywords = ["manager", "director", "head", "chief", "general manager", "owner", "founder", "ceo", "president", "operations"]
    exclude_keywords = ["hr", "human resources", "recruit", "career", "finance", "accounts payable", "accounts receivable", "invoice", "billing", "marketing", "brand", "graphic", "designer", "webmaster", "software", "developer", "technician", "service technician", "mechanic", "admin", "reception"]
    generic_priority_emails = ["sales@", "parts@", "purchasing@", "procurement@", "buying@", "imports@", "import@", "exports@", "export@", "enquiries@", "inquiries@", "info@"]
    generic_exclude_emails = ["careers@", "jobs@", "hr@", "accounts@", "invoice@", "billing@", "marketing@", "webmaster@", "support@"]

    score, reasons = 0, []
    for k in high_keywords:
        if k in text:
            score += 30; reasons.append(k)
    for k in decision_keywords:
        if k in text:
            score += 15; reasons.append(k)
    for k in generic_priority_emails:
        if k in email:
            score += 25; reasons.append(k)
    for k in generic_exclude_emails:
        if k in email:
            score -= 40; reasons.append("exclude:" + k)
    for k in exclude_keywords:
        if k in text:
            score -= 30; reasons.append("exclude:" + k)
    if typ == "personal":
        score += 5
    try:
        confidence = int(float(row.get("Confidence", 0) or 0))
        if confidence >= 90: score += 10
        elif confidence >= 70: score += 5
    except Exception:
        pass

    if score >= 55: priority = "A - Send First"
    elif score >= 30: priority = "B - Send If Needed"
    else: priority = "C - Low / Exclude"
    return score, priority, ", ".join(dict.fromkeys(reasons))


def normalize_websites(websites):
    rows, seen = [], set()
    for item in websites:
        raw = str(item).strip()
        domain = clean_domain(raw)
        if domain and domain not in seen:
            rows.append({"Original Website": raw, "Domain": domain})
            seen.add(domain)
    return rows


def hunter_domain_search_all(domain):
    all_emails, company, errors = [], "", []
    limit, offset, max_pages = 100, 0, 20
    for _ in range(max_pages):
        response = requests.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": HUNTER_API_KEY, "limit": limit, "offset": offset},
            timeout=60,
        )
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


def build_results(websites):
    input_sites = normalize_websites(websites)
    all_rows = []
    for idx, item in enumerate(input_sites, start=1):
        website, domain = item["Original Website"], item["Domain"]
        try:
            company, emails, errors = hunter_domain_search_all(domain)
            if errors:
                all_rows.append({"No": idx, "Original Website": website, "Domain": domain, "Status": "API ERROR", "Company": company, "Email": "", "Message": " / ".join(errors)})
                continue
            if not emails:
                all_rows.append({"No": idx, "Original Website": website, "Domain": domain, "Status": "NO EMAIL FOUND", "Company": company, "Email": "", "Message": "No email found by Hunter"})
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
                    "Message": "",
                }
                score, priority, reason = priority_score(row)
                row["Priority Score"] = score
                row["Priority"] = priority
                row["Priority Reason"] = reason
                all_rows.append(row)
        except Exception as exc:
            all_rows.append({"No": idx, "Original Website": website, "Domain": domain, "Status": "ERROR", "Company": "", "Email": "", "Message": str(exc)})
        time.sleep(0.25)
    return input_sites, all_rows


def make_excel(input_sites, all_rows):
    result_df = pd.DataFrame(all_rows)
    input_df = pd.DataFrame(input_sites)
    if result_df.empty:
        found_df = pd.DataFrame()
        priority_df = pd.DataFrame()
    else:
        found_df = result_df[(result_df["Status"] == "FOUND") & (result_df["Email"].astype(str).str.contains("@", na=False))].copy()
        priority_df = found_df[found_df.get("Priority", "").isin(["A - Send First", "B - Send If Needed"])].copy() if not found_df.empty else pd.DataFrame()
    summary = result_df.groupby("Status", dropna=False).size().reset_index(name="Count") if not result_df.empty else pd.DataFrame(columns=["Status", "Count"])
    by_domain = found_df.groupby("Domain", dropna=False).size().reset_index(name="Email Count") if not found_df.empty else pd.DataFrame(columns=["Domain", "Email Count"])
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        found_df.to_excel(writer, index=False, sheet_name="All Found Emails")
        priority_df.to_excel(writer, index=False, sheet_name="Priority Contacts")
        result_df.to_excel(writer, index=False, sheet_name="Raw Results")
        by_domain.to_excel(writer, index=False, sheet_name="Email Count by Domain")
        summary.to_excel(writer, index=False, sheet_name="Status Summary")
        input_df.to_excel(writer, index=False, sheet_name="Input Domains")
    output.seek(0)
    return output


@app.route("/", methods=["GET"])
def home():
    return jsonify({"service": "Hunter Full Email XLSX Server", "status": "running"})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "hunter_api_key_loaded": bool(HUNTER_API_KEY)})


@app.route("/extract-all-emails-xlsx", methods=["POST"])
def extract_all_emails_xlsx():
    if not HUNTER_API_KEY:
        return jsonify({"error": "HUNTER_API_KEY environment variable is missing."}), 500
    body = request.get_json(silent=True) or {}
    websites = body.get("websites", [])
    if not isinstance(websites, list) or not websites:
        return jsonify({"error": "Please provide websites as a JSON array."}), 400
    input_sites, all_rows = build_results(websites)
    excel_file = make_excel(input_sites, all_rows)
    return send_file(excel_file, as_attachment=True, download_name="hunter_all_emails.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/openapi.json", methods=["GET"])
def openapi():
    server_url = request.url_root.rstrip("/")
    return jsonify({
        "openapi": "3.1.0",
        "info": {"title": "Hunter Full Email Extraction API", "version": "3.0.0", "description": "Send website URLs as JSON. Server queries Hunter with pagination and returns all discovered emails as XLSX."},
        "servers": [{"url": server_url}],
        "paths": {
            "/health": {"get": {"operationId": "healthCheck", "summary": "Check server status", "responses": {"200": {"description": "Server health status", "content": {"application/json": {"schema": {"type": "object", "properties": {"status": {"type": "string"}, "hunter_api_key_loaded": {"type": "boolean"}}}}}}}}},
            "/extract-all-emails-xlsx": {"post": {"operationId": "extractAllEmailsXlsx", "summary": "Extract all discovered emails and return XLSX", "requestBody": {"required": True, "content": {"application/json": {"schema": {"type": "object", "properties": {"websites": {"type": "array", "items": {"type": "string"}}}, "required": ["websites"]}}}}, "responses": {"200": {"description": "XLSX file containing all discovered emails", "content": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {"schema": {"type": "string", "format": "binary"}}}}, "400": {"description": "Invalid request"}, "500": {"description": "Server error"}}}}
        }
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
