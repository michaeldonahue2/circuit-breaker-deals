import os
import yaml
import feedparser
import requests
import json
import re
from datetime import datetime
from openai import OpenAI

# --- CONFIG ---
def load_config():
    with open("config/config.yaml", "r") as f:
        return yaml.safe_load(f)

config = load_config()
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
AMAZON_TAG = "circuitbrea0c-20"

# --- HELPER: FIND AMAZON ID (ASIN) ---
def find_asin(text):
    """
    Hunts for an Amazon Product ID (ASIN) inside text or URLs.
    Works even if the URL is encoded (common in RSS feeds).
    """
    if not text: return None
    
    # Pattern A: Standard URL (/dp/B012345678)
    # Pattern B: Encoded URL (%2Fdp%2FB012345678)
    patterns = [
        r'/dp/([A-Z0-9]{10})',
        r'/gp/product/([A-Z0-9]{10})',
        r'%2Fdp%2F([A-Z0-9]{10})',
        r'%2Fgp%2Fproduct%2F([A-Z0-9]{10})',
        r'amazon\.com.*/([A-Z0-9]{10})'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1) # Return just the ID (e.g. B08XYZ123)
    return None

# --- 1. INGEST & FILTER (STRICT) ---
def fetch_deals():
    print("Fetching deals (Strict Amazon Mode)...")
    valid_deals = []
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
    
    for source in config['sources']:
        try:
            resp = requests.get(source['url'], headers=headers, timeout=10)
            feed = feedparser.parse(resp.content)
            
            for entry in feed.entries:
                # 1. Search for ASIN in the Link AND the Description
                content_blob = str(entry.link) + str(entry.get('summary', '')) + str(entry.get('content', ''))
                asin = find_asin(content_blob)
                
                if asin:
                    # WE FOUND ONE! Build the money link.
                    money_link = f"https://www.amazon.com/dp/{asin}?tag={AMAZON_TAG}"
                    
                    valid_deals.append({
                        "title": entry.title,
                        "link": money_link, # Direct to Amazon
                        "source": "Amazon",
                        "date": datetime.now().strftime("%Y-%m-%d")
                    })
                    print(f"  [+] Found Amazon Deal: {asin}")
                else:
                    # Skip it. No money, no post.
                    pass
                    
        except Exception as e:
            print(f"Skipping {source['name']}: {e}")
            
    # Remove duplicates
    unique_deals = {d['link']:d for d in valid_deals}.values()
    return list(unique_deals)[:9]

# --- 2. AI ENRICHMENT ---
def ai_enrich(deals):
    print("AI rewriting...")
    enriched = []
    for deal in deals:
        try:
            prompt = f"""
            Analyze deal title: '{deal['title']}'.
            Return JSON:
            - 'headline': Catchy title (max 6 words).
            - 'why_good': 1 sentence benefit.
            - 'category': Tech, Home, or Audio.
            """
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            data = json.loads(resp.choices[0].message.content)
            deal.update(data)
            enriched.append(deal)
        except:
            deal['headline'] = deal['title'][:50]
            deal['why_good'] = "Great price detected."
            deal['category'] = "Tech"
            enriched.append(deal)
    return enriched

# --- 3. GENERATE WEBSITE ---
def generate_site(deals):
    print("Generating index.html...")
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>CircuitBreaker | Daily Tech Drops</title>
        <style>
            :root {{ --bg: #0f172a; --card: #1e293b; --text: #e2e8f0; --accent: #38bdf8; }}
            body {{ font-family: system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 20px; }}
            .container {{ max-width: 1000px; margin: 0 auto; }}
            header {{ text-align: center; padding: 60px 0; border-bottom: 1px solid #334155; margin-bottom: 40px; }}
            h1 {{ font-size: 3rem; margin: 0; background: linear-gradient(to right, #38bdf8, #818cf8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
            .date {{ color: #94a3b8; margin-top: 10px; }}
            .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 25px; }}
            .card {{ background: var(--card); padding: 25px; border-radius: 12px; border: 1px solid #334155; transition: transform 0.2s; }}
            .card:hover {{ transform: translateY(-5px); border-color: var(--accent); }}
            .tag {{ background: #0f172a; padding: 5px 10px; border-radius: 20px; font-size: 0.8rem; color: var(--accent); text-transform: uppercase; letter-spacing: 1px; }}
            .headline {{ font-size: 1.4rem; margin: 15px 0; font-weight: 700; color: white; text-decoration: none; display: block; }}
            .why {{ color: #94a3b8; line-height: 1.6; font-size: 0.95rem; }}
            .btn {{ display: inline-block; margin-top: 20px; background: var(--accent); color: #0f172a; padding: 10px 20px; text-decoration: none; border-radius: 6px; font-weight: bold; width: 100%; text-align: center; box-sizing: border-box; }}
            footer {{ text-align: center; margin-top: 80px; color: #64748b; font-size: 0.9rem; }}
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <h1>⚡ CircuitBreaker</h1>
                <p class="date">Fresh Drops for {datetime.now().strftime("%B %d, %Y")}</p>
            </header>
            <div class="grid">
    """
    
    if not deals:
        html += "<p style='text-align:center; width:100%;'>Scanning for Amazon deals... Check back in 1 hour.</p>"
    
    for deal in deals:
        html += f"""
        <div class="card">
            <span class="tag">{deal['category']}</span>
            <a href="{deal['link']}" class="headline" target="_blank">{deal['headline']}</a>
            <p class="why">{deal['why_good']}</p>
            <a href="{deal['link']}" class="btn" target="_blank">Buy on Amazon &rarr;</a>
        </div>
        """
        
    html += """
            </div>
            <footer>
                <p>Managed by AI. Affiliate links earn support.</p>
            </footer>
        </div>
    </body>
    </html>
    """
    
    with open("index.html", "w") as f:
        f.write(html)
    print("Website generated.")

if __name__ == "__main__":
    # Run pipeline
    final_deals = fetch_deals()
    if final_deals:
        final_deals = ai_enrich(final_deals)
    generate_site(final_deals)
