import os
import time
from urllib.parse import urlparse

import requests
from flask import Flask, request, jsonify
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


def unique_domains_from_websites(websites):
    result = []
    seen = set()
    for item in websites:
        raw = str(item).strip()
        domain = clean_domain(raw)
        if domain and domain not in seen:
            result.append({"original_website": raw, "domain": domain})
            seen.add(domain)
    return result


def hunter_domain_search(domain):
    endpoint = "https://api.hunter.io/v2/domain-search"
    params = {"domain": domain, "api_key": HUNTER_API_KEY, "limit": 100}
    return requests.get(endpoint, params=params, timeout=45)


def collect_contacts(websites):
    unique_sites = unique_domains_from_websites(websites)
    results = []

    for idx, site in enumerate(unique_sites, start=1):
        website = site["original_website"]
        domain = site["domain"]

        try:
            response = hunter_domain_search(domain)

            if response.status_code == 200:
                data = response.json()
                info = data.get("data", {})
                company = info.get("organization", "")
                emails = info.get("emails", [])

                if emails:
                    for e in emails:
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
                            "Phone Number": e.get("phone_number", "")
                        }
                        score, priority, reason = priority_score(row)
                        row["Priority Score"] = score
                        row["Priority"] = priority
                        row["Priority Reason"] = reason
                        results.append(row)
                else:
                    results.append({
                        "No": idx, "Original Website": website, "Domain": domain,
                        "Status": "NO EMAIL FOUND", "Company": company, "Email": "",
                        "Type": "", "Confidence": "", "First Name": "", "Last Name": "",
                        "Position": "", "Department": "", "Seniority": "", "LinkedIn": "",
                        "Twitter": "", "Phone Number": "", "Priority Score": 0,
                        "Priority": "Exclude", "Priority Reason": "No email found"
                    })

            else:
                results.append({
                    "No": idx, "Original Website": website, "Domain": domain,
                    "Status": "API ERROR", "Company": "", "Email": "", "Type": "",
                    "Confidence": "", "First Name": "", "Last Name": "", "Position": "",
                    "Department": "", "Seniority": "", "LinkedIn": "", "Twitter": "",
                    "Phone Number": "", "Priority Score": 0, "Priority": "Exclude",
                    "Priority Reason": f"HTTP {response.status_code}"
                })

        except Exception as exc:
            results.append({
                "No": idx, "Original Website": website, "Domain": domain,
                "Status": "ERROR", "Company": "", "Email": "", "Type": "",
                "Confidence": "", "First Name": "", "Last Name": "", "Position": "",
                "Department": "", "Seniority": "", "LinkedIn": "", "Twitter": "",
                "Phone Number": "", "Priority Score": 0, "Priority": "Exclude",
                "Priority Reason": str(exc)
            })

        time.sleep(0.25)

    priority_contacts = [
        row for row in results
        if row.get("Status") == "FOUND"
        and "@" in str(row.get("Email", ""))
        and row.get("Priority") in ["A - Send First", "B - Send If Needed"]
    ]

    priority_contacts = sorted(
        priority_contacts,
        key=lambda x: (
            0 if x.get("Priority") == "A - Send First" else 1,
            str(x.get("Domain", "")),
            -int(x.get("Priority Score") or 0),
            -int(x.get("Confidence") or 0)
        )
    )

    return unique_sites, results, priority_contacts


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "service": "Hunter Email Server",
        "status": "running",
        "mode": "json_action",
        "endpoints": ["/health", "/extract-priority-emails-json", "/openapi.json"]
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "hunter_api_key_loaded": bool(HUNTER_API_KEY)})


@app.route("/extract-priority-emails-json", methods=["POST"])
def extract_priority_emails_json():
    if not HUNTER_API_KEY:
        return jsonify({"error": "HUNTER_API_KEY environment variable is missing."}), 500

    body = request.get_json(silent=True) or {}
    websites = body.get("websites", [])

    if not isinstance(websites, list) or len(websites) == 0:
        return jsonify({
            "error": "Please provide websites as a JSON array.",
            "example": {"websites": ["https://example.com", "example2.com"]}
        }), 400

    unique_sites, all_results, priority_contacts = collect_contacts(websites)

    status_counts = {}
    for row in all_results:
        status = row.get("Status", "UNKNOWN")
        status_counts[status] = status_counts.get(status, 0) + 1

    return jsonify({
        "input_website_count": len(unique_sites),
        "all_result_count": len(all_results),
        "priority_contact_count": len(priority_contacts),
        "status_counts": status_counts,
        "priority_contacts": priority_contacts,
        "all_results": all_results
    })


@app.route("/openapi.json", methods=["GET"])
def openapi():
    server_url = request.url_root.rstrip("/")
    return jsonify({
        "openapi": "3.1.0",
        "info": {
            "title": "Hunter Priority Email Extraction API",
            "version": "2.0.0",
            "description": "Send website URLs as JSON and receive priority sales contacts extracted via Hunter."
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
            "/extract-priority-emails-json": {
                "post": {
                    "operationId": "extractPriorityEmailsJson",
                    "summary": "Extract priority sales emails from website URL list",
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
                            "description": "Priority sales contacts in JSON format",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "input_website_count": {"type": "integer"},
                                            "all_result_count": {"type": "integer"},
                                            "priority_contact_count": {"type": "integer"},
                                            "status_counts": {"type": "object", "properties": {}},
                                            "priority_contacts": {"type": "array", "items": {"type": "object", "properties": {}}},
                                            "all_results": {"type": "array", "items": {"type": "object", "properties": {}}}
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
