"""
CareerIQ - Career Intelligence Platform
Powered by Groq (FREE) + Scrapling

Run:  python3 app.py
Open: http://localhost:5000
"""

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import json, io, re

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

# ── Paste your FREE Groq API key here ─────────────────────────────────────
# Get it free at: console.groq.com (no credit card needed)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_URL   = "https://api.groq.com/openai/v1/chat/completions"


@app.route("/")
def index():
    return app.send_static_file("index.html")


# ── Main research endpoint ─────────────────────────────────────────────────
@app.route("/research", methods=["POST"])
def research():
    data     = request.get_json()
    job_role = (data or {}).get("role", "").strip()
    location = (data or {}).get("location", "Global").strip()

    if not job_role:
        return jsonify({"error": "No job role provided"}), 400

    try:
        scraped = scrape_salary_data(job_role, location)
        ai      = generate_ai_intelligence(job_role, location, scraped)
        return jsonify({**scraped, **ai, "role": job_role, "location": location})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Scrape salary + company data ───────────────────────────────────────────
def scrape_salary_data(role, location):
    results = {"companies": [], "salaries": [], "source_urls": [], "linkedin_people": []}

    try:
        from scrapling.fetchers import Fetcher, StealthyFetcher

        # Indeed
        try:
            query = role.replace(" ", "+")
            loc   = location.replace(" ", "+")
            url   = f"https://www.indeed.com/jobs?q={query}&l={loc}"
            page  = Fetcher.get(url, stealthy_headers=True, impersonate="chrome")
            for job in page.css(".job_seen_beacon, .tapItem, [class*='job-card']")[:20]:
                company = job.css(".companyName::text, [class*='company']::text").get(default="").strip()
                salary  = job.css(".salary-snippet::text, [class*='salary']::text").get(default="").strip()
                title   = job.css(".jobTitle::text, h2 a::text, [class*='title']::text").get(default="").strip()
                if company and title:
                    results["companies"].append({"company": company, "title": title, "salary": salary or "Not listed", "source": "Indeed"})
            results["source_urls"].append(url)
        except Exception as e:
            app.logger.info(f"Indeed: {e}")

        # Glassdoor
        try:
            query = role.replace(" ", "-").lower()
            url   = f"https://www.glassdoor.com/Job/{query}-jobs-SRCH_KO0,{len(query)}.htm"
            page  = StealthyFetcher.fetch(url, headless=True, network_idle=True)
            for job in page.css("[class*='JobCard'], [class*='job-listing'], article")[:15]:
                company = job.css("[class*='employer']::text, [class*='company']::text").get(default="").strip()
                salary  = job.css("[class*='salary']::text, [class*='pay']::text").get(default="").strip()
                title   = job.css("[class*='job-title']::text, h2::text, h3::text").get(default="").strip()
                if company:
                    results["companies"].append({"company": company, "title": title or role, "salary": salary or "Not listed", "source": "Glassdoor"})
            results["source_urls"].append(url)
        except Exception as e:
            app.logger.info(f"Glassdoor: {e}")

        # LinkedIn Jobs
        try:
            query = role.replace(" ", "%20")
            url   = f"https://www.linkedin.com/jobs/search/?keywords={query}&location={location.replace(' ','%20')}"
            page  = Fetcher.get(url, stealthy_headers=True, impersonate="chrome")
            for job in page.css(".base-card, [class*='job-search-card']")[:15]:
                company = job.css(".base-search-card__subtitle::text, [class*='company']::text").get(default="").strip()
                title   = job.css(".base-search-card__title::text, h3::text").get(default="").strip()
                loc_txt = job.css(".job-search-card__location::text").get(default="").strip()
                if company:
                    results["companies"].append({"company": company, "title": title or role, "salary": "See listing", "source": "LinkedIn", "location": loc_txt})
            results["source_urls"].append(url)
        except Exception as e:
            app.logger.info(f"LinkedIn jobs: {e}")

        # LinkedIn People
        try:
            query = role.replace(" ", "%20")
            url   = f"https://www.linkedin.com/search/results/people/?keywords={query}"
            page  = Fetcher.get(url, stealthy_headers=True, impersonate="chrome")
            for p in page.css(".entity-result, [class*='search-result']")[:10]:
                name    = p.css(".entity-result__title-text::text, [class*='actor-name']::text").get(default="").strip()
                title   = p.css(".entity-result__primary-subtitle::text").get(default="").strip()
                company = p.css(".entity-result__secondary-subtitle::text").get(default="").strip()
                link    = p.css("a.app-aware-link::attr(href), a::attr(href)").get(default="").strip()
                if name:
                    results["linkedin_people"].append({"name": name, "title": title, "company": company, "url": link})
        except Exception as e:
            app.logger.info(f"LinkedIn people: {e}")

    except ImportError:
        app.logger.warning("Scrapling not available — AI-only mode")

    # Deduplicate companies
    seen, unique = set(), []
    for c in results["companies"]:
        key = c["company"].lower()
        if key not in seen and c["company"]:
            seen.add(key)
            unique.append(c)
    results["companies"] = unique[:25]
    return results


# ── Groq AI: generate career intelligence ─────────────────────────────────
def generate_ai_intelligence(role, location, scraped_data):
    import urllib.request, urllib.error

    companies_text = "\n".join([
        f"- {c['company']}: {c['title']} ({c['salary']})"
        for c in scraped_data.get("companies", [])[:15]
    ]) or "No scraped data — use your knowledge"

    prompt = f"""You are a world-class career intelligence analyst. Generate a comprehensive career report for: "{role}" in {location}.

Real scraped company data:
{companies_text}

Return ONLY raw JSON — no markdown, no backticks, no explanation. Start directly with {{ and end with }}.

{{
  "salary_overview": {{
    "entry_level": "e.g. $45,000 - $65,000",
    "mid_level": "e.g. $70,000 - $100,000",
    "senior_level": "e.g. $110,000 - $160,000",
    "currency_note": "note about location and currency",
    "avg_salary": "e.g. $85,000",
    "trend": "growing or stable or declining",
    "trend_reason": "one clear sentence"
  }},
  "top_companies": [
    {{"name": "Company", "salary_range": "$X - $Y", "culture": "one word", "rating": "4.2/5", "hiring": true}}
  ],
  "required_skills": [
    {{"skill": "Skill name", "level": "Expert or Advanced or Intermediate or Beginner", "demand": "Very High or High or Medium or Low", "category": "Technical or Soft or Tool or Domain"}}
  ],
  "learning_resources": [
    {{"title": "Resource title", "platform": "Coursera or YouTube or Udemy or edX or freeCodeCamp or Documentation or Book", "url": "https://real-url.com", "free": true, "duration": "X hours", "type": "Course or Video or Book or Documentation"}}
  ],
  "interview_questions": [
    {{"question": "Role-specific interview question", "category": "Technical or Behavioral or Situational", "difficulty": "Easy or Medium or Hard", "sample_answer": "Helpful 2-3 sentence answer guide"}}
  ],
  "negotiation_scripts": {{
    "opening_line": "Word-for-word script to open negotiation",
    "counter_offer": "Word-for-word counter offer script",
    "handling_lowball": "Word-for-word script for low offers",
    "closing": "Word-for-word closing script",
    "email_template": "Full professional salary negotiation email"
  }},
  "market_insights": {{
    "demand_score": 85,
    "future_outlook": "2-3 sentences about future of this role",
    "top_industries": ["Industry1", "Industry2", "Industry3"],
    "remote_friendly": true,
    "avg_job_postings_monthly": "5,000+",
    "years_to_senior": "3-5 years"
  }},
  "linkedin_search_tips": [
    "Actionable tip for finding people in this role on LinkedIn"
  ],
  "certifications": [
    {{"name": "Cert name", "provider": "AWS/Google/etc", "value": "High or Medium", "cost": "$X", "duration": "X months"}}
  ],
  "day_in_life": "2-3 vivid sentences about daily work in this role",
  "red_flags": ["Specific warning sign to watch out for"]
}}

Rules:
- 8+ skills, 10+ interview questions, 6+ learning resources, 5+ companies, 3+ certs, 3+ red flags
- Salary data realistic for {location}
- Interview questions MUST be specific to "{role}" not generic
- Real working URLs for learning resources
- Output raw JSON only — nothing else"""

    payload = json.dumps({
        "model":       GROQ_MODEL,
        "messages":    [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens":  4000,
    }).encode()

    req = urllib.request.Request(
        GROQ_URL,
        data=payload,
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {GROQ_API_KEY}",
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise Exception(f"Groq API error {e.code}: {body}")

    raw = result["choices"][0]["message"]["content"].strip()

    # Clean up any markdown fences Groq might add
    raw = re.sub(r"^```json\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"^```\s*",     "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```$",        "", raw, flags=re.MULTILINE)
    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try to extract JSON from anywhere in the response
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise Exception("Could not parse Groq response as JSON. Please try again.")


# ── PDF Report export ──────────────────────────────────────────────────────
@app.route("/download/report", methods=["POST"])
def download_report():
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.colors import HexColor, white
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.units import cm
    except ImportError:
        return jsonify({"error": "Run: pip3 install reportlab"}), 500

    data = request.get_json() or {}
    role = data.get("role", "Career Report")
    loc  = data.get("location", "Global")
    buf  = io.BytesIO()
    doc  = SimpleDocTemplate(buf, pagesize=A4,
                              leftMargin=2*cm, rightMargin=2*cm,
                              topMargin=2*cm,  bottomMargin=2*cm)

    BLUE  = HexColor("#1d4ed8")
    DARK  = HexColor("#0f172a")
    MUTED = HexColor("#64748b")
    h1   = ParagraphStyle("h1",   fontSize=22, textColor=DARK,  spaceAfter=6,  fontName="Helvetica-Bold")
    h2   = ParagraphStyle("h2",   fontSize=14, textColor=BLUE,  spaceAfter=4,  spaceBefore=14, fontName="Helvetica-Bold")
    body = ParagraphStyle("body", fontSize=10, textColor=DARK,  spaceAfter=4,  leading=16)
    sub  = ParagraphStyle("sub",  fontSize=9,  textColor=MUTED, spaceAfter=3,  leading=14)

    story = []
    story.append(Paragraph("Career Intelligence Report", h1))
    story.append(Paragraph(f"{role} · {loc} · CareerIQ + Groq AI (Free)", sub))
    story.append(Spacer(1, 0.4*cm))

    sal = data.get("salary_overview", {})
    if sal:
        story.append(Paragraph("Salary Overview", h2))
        for label, key in [("Entry Level","entry_level"),("Mid Level","mid_level"),("Senior Level","senior_level")]:
            story.append(Paragraph(f"<b>{label}:</b> {sal.get(key,'—')}", body))
        story.append(Paragraph(f"Trend: {sal.get('trend','—')} — {sal.get('trend_reason','')}", sub))

    skills = data.get("required_skills", [])
    if skills:
        story.append(Paragraph("Required Skills", h2))
        tdata = [["Skill", "Level", "Demand", "Category"]]
        for s in skills:
            tdata.append([s.get("skill",""), s.get("level",""), s.get("demand",""), s.get("category","")])
        t = Table(tdata, colWidths=[4.5*cm, 3*cm, 3*cm, 4*cm])
        t.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,0), BLUE),
            ("TEXTCOLOR",     (0,0),(-1,0), white),
            ("FONTNAME",      (0,0),(-1,0), "Helvetica-Bold"),
            ("FONTSIZE",      (0,0),(-1,-1), 9),
            ("ROWBACKGROUNDS",(0,1),(-1,-1), [HexColor("#f8fafc"), white]),
            ("GRID",          (0,0),(-1,-1), 0.5, HexColor("#e2e8f0")),
            ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
            ("TOPPADDING",    (0,0),(-1,-1), 5),
            ("BOTTOMPADDING", (0,0),(-1,-1), 5),
        ]))
        story.append(t)

    questions = data.get("interview_questions", [])
    if questions:
        story.append(Paragraph("Interview Questions & Answers", h2))
        for i, q in enumerate(questions[:10], 1):
            story.append(Paragraph(
                f"<b>Q{i}. {q.get('question','')}</b> "
                f"<font color='#64748b'>[{q.get('category','')} · {q.get('difficulty','')}]</font>", body))
            story.append(Paragraph(f"→ {q.get('sample_answer','')}", sub))

    neg = data.get("negotiation_scripts", {})
    if neg:
        story.append(Paragraph("Negotiation Scripts", h2))
        for label, key in [("Opening","opening_line"),("Counter Offer","counter_offer"),
                            ("Low Offer Response","handling_lowball"),("Closing","closing")]:
            story.append(Paragraph(f"<b>{label}:</b> {neg.get(key,'—')}", body))
        if neg.get("email_template"):
            story.append(Paragraph("<b>Email Template:</b>", body))
            story.append(Paragraph(neg["email_template"].replace("\n","<br/>"), sub))

    certs = data.get("certifications", [])
    if certs:
        story.append(Paragraph("Recommended Certifications", h2))
        for c in certs:
            story.append(Paragraph(
                f"<b>{c.get('name','')}</b> — {c.get('provider','')} · {c.get('value','')} value · {c.get('cost','')} · {c.get('duration','')}", body))

    flags = data.get("red_flags", [])
    if flags:
        story.append(Paragraph("Red Flags to Watch Out For", h2))
        for f in flags:
            story.append(Paragraph(f"⚠ {f}", body))

    doc.build(story)
    buf.seek(0)
    return send_file(buf, mimetype="application/pdf",
                     as_attachment=True,
                     download_name=f"{role.replace(' ','_')}_CareerIQ_Report.pdf")


if __name__ == "__main__":
    print("\n🎯 CareerIQ running at http://localhost:5000")
    print("🆓 Powered by Groq — llama-3.3-70b-versatile (FREE)")
    if GROQ_API_KEY == "YOUR_GROQ_API_KEY_HERE":
        print("⚠️  Paste your Groq API key on line 17 of this file!\n")
    else:
        print("✅ Groq API key found — ready to go!\n")
    app.run(debug=True, port=5000)
