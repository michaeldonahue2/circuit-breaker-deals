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

# --- IMAGES & ASSETS ---
FALLBACK_IMGS = {
    "Tech": "https://images.unsplash.com/photo-1519389950473-47ba0277781c?w=600&q=80",
    "Audio": "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=600&q=80",
    "Home": "https://images.unsplash.com/photo-1556909114-f6e7ad7d3136?w=600&q=80",
    "Default": "https://images.unsplash.com/photo-1518770660439-4636190af475?w=600&q=80"
}

# --- HELPER: EXTRACT IMAGE ---
def extract_image(entry):
    """Finds an image URL inside the RSS entry HTML."""
    content = str(entry.get('summary', '')) + str(entry.get('content', ''))
    # Look for <img src="...">
    match = re.search(r'<img[^>]+src="([^">]+)"', content)
    if match:
        return match.group(1)
    return None

# --- HELPER: FIND ASIN ---
def find_asin(text):
    if not text: return None
    patterns = [
        r'/dp/([A-Z0-9]{10})',
        r'/gp/product/([A-Z0-9]{10})',
        r'%2Fdp%2F([A-Z0-9]{10})',
        r'amazon\.com.*/([A-Z0-9]{10})'
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match: return match.group(1)
    return None

# --- 1. INGEST ---
def fetch_deals():
    print("Fetching deals...")
    valid_deals = []
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
    
    for source in config['sources']:
        try:
            resp = requests.get(source['url'], headers=headers, timeout=10)
            feed = feedparser.parse(resp.content)
            
            for entry in feed.entries:
                content_blob = str(entry.link) + str(entry.get('summary', ''))
                asin = find_asin(content_blob)
                
                if asin:
                    img_url = extract_image(entry)
                    money_link = f"https://www.amazon.com/dp/{asin}?tag={AMAZON_TAG}"
                    
                    valid_deals.append({
                        "title": entry.title,
                        "link": money_link,
                        "img": img_url, 
                        "source": "Amazon",
                        "date": datetime.now().strftime("%Y-%m-%d")
                    })
        except Exception as e:
            print(f"Skipping {source['name']}: {e}")
            
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
            - 'headline': Catchy title (max 5 words).
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
            
            # Assign fallback image if none found
            if not deal['img']:
                cat = deal.get('category', 'Default')
                deal['img'] = FALLBACK_IMGS.get(cat, FALLBACK_IMGS['Default'])
                
            enriched.append(deal)
        except:
            deal['headline'] = deal['title'][:40]
            deal['why_good'] = "Great price detected."
            deal['category'] = "Tech"
            deal['img'] = FALLBACK_IMGS['Tech']
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
        <title>CircuitBreaker | AI Deal Hunter</title>
        <style>
            :root {{ --bg: #0f172a; --card: #1e293b; --text: #f1f5f9; --accent: #0ea5e9; }}
            body {{ font-family: 'Inter', system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 0; }}
            
            /* Hero Section */
            .hero {{ text-align: center; padding: 80px 20px; background: radial-gradient(circle at top, #1e293b 0%, #0f172a 100%); border-bottom: 1px solid #334155; }}
            h1 {{ font-size: 3.5rem; margin: 0; letter-spacing: -2px; background: linear-gradient(to right, #38bdf8, #818cf8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
            .subtitle {{ font-size: 1.2rem; color: #94a3b8; margin-top: 15px; font-weight: 300; }}
            
            /* Grid */
            .container {{ max-width: 1200px; margin: 40px auto; padding: 0 20px; }}
            .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 30px; }}
            
            /* Cards */
            .card {{ background: var(--card); border-radius: 16px; overflow: hidden; border: 1px solid #334155; transition: all 0.3s ease; display: flex; flex-direction: column; }}
            .card:hover {{ transform: translateY(-8px); box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.3); border-color: var(--accent); }}
            
            .card-img {{ width: 100%; height: 200px; object-fit: cover; background: #334155; }}
            .card-content {{ padding: 20px; flex-grow: 1; display: flex; flex-direction: column; }}
            
            .tag {{ font-size: 0.75rem; color: var(--accent); text-transform: uppercase; letter-spacing: 1px; font-weight: 700; margin-bottom: 10px; display: block; }}
            .headline {{ font-size: 1.25rem; font-weight: 700; margin: 0 0 10px 0; line-height: 1.4; }}
            .why {{ color: #94a3b8; font-size: 0.95rem; line-height: 1.6; margin-bottom: 20px; flex-grow: 1; }}
            
            .btn {{ display: block; width: 100%; padding: 12px; background: var(--accent); color: white; text-align: center; text-decoration: none; font-weight: 600; border-radius: 8px; transition: background 0.2s; }}
            .btn:hover {{ background: #0284c7; }}
            
            footer {{ text-align: center; padding: 50px; color: #64748b; font-size: 0.9rem; border-top: 1px solid #334155; margin-top: 50px; }}
        </style>
    </head>
    <body>
        <div class="hero">
            <h1>⚡ CircuitBreaker</h1>
            <p class="subtitle">Let AI search the web for you to find the best deals.</p>
        </div>
        
        <div class="container">
            <div class="grid">
    """
    
    if not deals:
        html += "<p style='grid-column: 1/-1; text-align: center;'>Scanning for new inventory... Update coming shortly.</p>"
        
    for deal in deals:
        html += f"""
        <div class="card">
            <img src="{deal['img']}" class="card-img" alt="Deal Image">
            <div class="card-content">
                <span class="tag">{deal['category']}</span>
                <h3 class="headline">{deal['headline']}</h3>
                <p class="why">{deal['why_good']}</p>
                <a href="{deal['link']}" class="btn" target="_blank">Check Price on Amazon</a>
            </div>
        </div>
        """
        
    html += """
            </div>
        </div>
        <footer>
            <p>Powered by CircuitBreaker AI. As an Amazon Associate we earn from qualifying purchases.</p>
        </footer>
    </body>
    </html>
    """
    
    with open("index.html", "w") as f:
        f.write(html)
    print("Website generated.")

if __name__ == "__main__":
    raw = fetch_deals()
    if raw:
        final = ai_enrich(raw)
        generate_site(final)
    else:
        generate_site([])
