import os
import yaml
import feedparser
import requests
import json
from datetime import datetime
from openai import OpenAI

# --- CONFIG ---
def load_config():
    with open("config/config.yaml", "r") as f:
        return yaml.safe_load(f)

config = load_config()
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# --- AFFILIATE SETTINGS ---
# This is your specific Amazon ID. The script will stamp this on every Amazon link.
AMAZON_TAG = "circuitbrea0c-20" 

# --- HELPER: MONETIZE LINKS ---
def monetize_url(url):
    """If it's an Amazon link, add our affiliate tag."""
    if "amazon.com" in url and AMAZON_TAG:
        # Check if URL already has parameters (use & or ?)
        if "?" in url:
            return url + f"&tag={AMAZON_TAG}"
        else:
            return url + f"?tag={AMAZON_TAG}"
    return url

# --- 1. INGEST ---
def fetch_deals():
    print("Fetching deals...")
    raw_deals = []
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
    
    for source in config['sources']:
        try:
            resp = requests.get(source['url'], headers=headers, timeout=10)
            feed = feedparser.parse(resp.content)
            # Get top 3 from each source
            for entry in feed.entries[:3]:
                raw_deals.append({
                    "title": entry.title,
                    "link": entry.link,
                    "source": source['name'],
                    "date": datetime.now().strftime("%Y-%m-%d")
                })
        except Exception as e:
            print(f"Skipping {source['name']}: {e}")
    return raw_deals

# --- 2. FILTER ---
def filter_deals(deals):
    seen = set()
    unique = []
    for d in deals:
        if d['link'] not in seen:
            seen.add(d['link'])
            unique.append(d)
    return unique[:9] # Max 9 deals on homepage

# --- 3. AI ENRICHMENT ---
def ai_enrich(deals):
    print("AI rewriting...")
    enriched = []
    for deal in deals:
        # 1. Monetize the link BEFORE we show it
        deal['link'] = monetize_url(deal['link'])
        
        # 2. AI Processing
        try:
            prompt = f"""
            Analyze this deal: '{deal['title']}'.
            Return JSON with:
            - 'headline': Short, punchy title (max 6 words).
            - 'why_good': One sentence on why it's a steal.
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
        except Exception as e:
            print(f"AI Failed: {e}")
            deal['headline'] = deal['title'][:50] + "..."
            deal['why_good'] = "Price drop detected."
            deal['category'] = "Deal"
            enriched.append(deal)
    return enriched

# --- 4. GENERATE WEBSITE ---
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
    
    for deal in deals:
        html += f"""
        <div class="card">
            <span class="tag">{deal['category']}</span>
            <a href="{deal['link']}" class="headline" target="_blank">{deal['headline']}</a>
            <p class="why">{deal['why_good']}</p>
            <a href="{deal['link']}" class="btn" target="_blank">Check Price &rarr;</a>
        </div>
        """
        
    html += """
            </div>
            <footer>
                <p>Managed by AI. Links may earn commission.</p>
            </footer>
        </div>
    </body>
    </html>
    """
    
    with open("index.html", "w") as f:
        f.write(html)
    print("Website generated successfully.")

if __name__ == "__main__":
    raw = fetch_deals()
    if raw:
        filtered = filter_deals(raw)
        final = ai_enrich(filtered)
        generate_site(final)
    else:
        print("No deals found today.")
