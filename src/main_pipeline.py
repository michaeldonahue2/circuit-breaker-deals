import os
import yaml
import feedparser
import requests
import json
import re
import urllib.parse
import textwrap
from datetime import datetime
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from io import BytesIO

# --- CONFIG ---
def load_config():
    with open("config/config.yaml", "r") as f:
        return yaml.safe_load(f)

config = load_config()
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
AMAZON_TAG = "circuitbrea0c-20"

# --- ASSETS ---
FALLBACK_IMGS = {
    "Tech": "https://images.unsplash.com/photo-1519389950473-47ba0277781c?w=800&q=80",
    "Home": "https://images.unsplash.com/photo-1556909114-f6e7ad7d3136?w=800&q=80",
    "Audio": "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=800&q=80",
    "Default": "https://images.unsplash.com/photo-1526738549149-8e07eca6c147?w=800&q=80"
}

# --- IMAGE GENERATOR (THE "PHOTOSHOP" BOT) ---
def generate_social_card(deal):
    """
    Downloads the product image and overlays price/discount text.
    Saves it to the /assets/ folder.
    """
    try:
        # 1. Download the Product Image
        response = requests.get(deal['img'])
        img = Image.open(BytesIO(response.content)).convert("RGBA")
        
        # 2. Resize and Crop to Square (1080x1080 for Insta/Pinterest)
        img = img.resize((1080, 1080))
        
        # 3. Create Overlay
        overlay = Image.new("RGBA", (1080, 1080), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        
        # Dark gradient at bottom for text readability
        # (Simplified as a semi-transparent black box for reliability)
        draw.rectangle([(0, 700), (1080, 1080)], fill=(0, 0, 0, 200))
        
        # 4. Add Text (Discount Badge)
        # Yellow Circle
        draw.ellipse([(850, 50), (1030, 230)], fill="#f59e0b")
        # Discount Text
        # Note: GitHub Actions doesn't have custom fonts, using default
        draw.text((880, 110), deal['discount_guess'], fill="black", font_size=40)
        
        # 5. Add Title & Call to Action
        # We wrap text so it doesn't go off screen
        title_lines = textwrap.wrap(deal['headline'], width=25)
        y_text = 750
        for line in title_lines:
            draw.text((50, y_text), line, fill="white", font_size=60)
            y_text += 70
            
        draw.text((50, y_text + 20), "Check Price on BetterAmazonPrices.com", fill="#38bdf8", font_size=30)
        
        # 6. Combine
        out = Image.alpha_composite(img, overlay)
        
        # 7. Save
        filename = f"assets/card_{deal['id'][-5:]}.png"
        os.makedirs("assets", exist_ok=True)
        out.save(filename, "PNG")
        return filename
        
    except Exception as e:
        print(f"Image Gen Failed for {deal['headline']}: {e}")
        return None

# --- STANDARD HELPERS ---
def extract_image(entry):
    content = str(entry.get('summary', '')) + str(entry.get('content', ''))
    match = re.search(r'<img[^>]+src="([^">]+)"', content)
    if match: return match.group(1)
    return None

def find_asin(text):
    if not text: return None
    patterns = [r'/dp/([A-Z0-9]{10})', r'/gp/product/([A-Z0-9]{10})', r'amazon\.com.*/([A-Z0-9]{10})', r'%2Fdp%2F([A-Z0-9]{10})']
    for pattern in patterns:
        match = re.search(pattern, text)
        if match: return match.group(1)
    return None

def create_amazon_search_link(title):
    junk = ["sale", "deal", "price", "drop", "off", "coupon", "amazon", "at", "for", "only", "$", "lowest"]
    words = title.lower().split()
    clean_words = [w for w in words if w not in junk and not w.isdigit()]
    search_query = " ".join(clean_words[:5])
    encoded_query = urllib.parse.quote(search_query)
    return f"https://www.amazon.com/s?k={encoded_query}&tag={AMAZON_TAG}"

# --- PIPELINE STEPS ---
def fetch_deals():
    print("Fetching deals...")
    raw_deals = []
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
    
    for source in config['sources']:
        try:
            resp = requests.get(source['url'], headers=headers, timeout=10)
            feed = feedparser.parse(resp.content)
            for entry in feed.entries[:6]:
                blob = str(entry.link) + str(entry.get('summary', ''))
                asin = find_asin(blob)
                if asin:
                    final_link = f"https://www.amazon.com/dp/{asin}?tag={AMAZON_TAG}"
                else:
                    final_link = create_amazon_search_link(entry.title)
                
                img_url = extract_image(entry)
                raw_deals.append({
                    "title": entry.title,
                    "link": final_link,
                    "img": img_url,
                    "source": source['name'],
                    "id": asin if asin else entry.link
                })
        except Exception as e:
            print(f"Error reading {source['name']}: {e}")
            
    seen = set()
    unique = []
    for d in raw_deals:
        if d['title'] not in seen:
            seen.add(d['title'])
            unique.append(d)
    return list(unique)[:15]

def ai_enrich(deals):
    print("AI Rewriting & Designing...")
    enriched = []
    for deal in deals:
        try:
            prompt = f"Analyze deal: '{deal['title']}'. JSON: headline (max 6 words), why_good (6 words), discount_guess, category, social_caption (hashtags included)."
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            data = json.loads(resp.choices[0].message.content)
            deal.update(data)
            
            if not deal['img']:
                deal['img'] = FALLBACK_IMGS.get(deal.get('category'), FALLBACK_IMGS['Default'])
            
            # Generate the Social Media Image
            card_path = generate_social_card(deal)
            deal['social_image_path'] = card_path
            
            enriched.append(deal)
        except:
            deal['headline'] = deal['title'][:50]
            deal['why_good'] = "Check price."
            deal['discount_guess'] = "DEAL"
            deal['social_caption'] = f"Check out this deal on {deal['headline']}! #TechDeals"
            if not deal.get('img'): deal['img'] = FALLBACK_IMGS['Default']
            enriched.append(deal)
    return enriched

def generate_rss(deals):
    print("Generating feed.xml...")
    # We include the Social Caption and Social Image in the RSS so automated tools can find them
    rss = """<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
<channel>
 <title>Better Amazon Prices</title>
 <description>Daily AI-Curated Deals</description>
 <link>https://betteramazonprices.com</link>
"""
    for deal in deals:
        # Safe image link (pointing to raw original for now to ensure tools pick it up)
        rss += f"""
 <item>
  <title>{deal['headline']} {deal['discount_guess']}</title>
  <description>{deal['social_caption']} - Grab it here: {deal['link']}</description>
  <link>{deal['link']}</link>
  <guid>{deal['link']}</guid>
  <media:content url="{deal['img']}" medium="image" />
  <pubDate>{datetime.now().strftime("%a, %d %b %Y %H:%M:%S GMT")}</pubDate>
 </item>
"""
    rss += "</channel>\n</rss>"
    with open("feed.xml", "w") as f:
        f.write(rss)
    print("RSS Feed generated.")

def generate_site(deals):
    print("Building Website...")
    # (Same HTML structure as before, just ensuring it uses the new data)
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Better Amazon Prices | AI Deal Hunter</title>
        <link rel="icon" href="https://fav.farm/⚡" />
        <meta name="description" content="AI-powered daily Amazon deal finder. Stop overpaying for tech.">
        <style>
            :root {{ --bg: #111827; --card: #1f2937; --text: #f3f4f6; --accent: #f59e0b; --btn-text: #111827; }}
            body {{ font-family: system-ui, sans-serif; background: var(--bg); color: var(--text); margin: 0; }}
            .nav {{ padding: 20px; text-align: center; border-bottom: 1px solid #374151; }}
            .logo {{ font-size: 1.8rem; font-weight: 900; color: white; letter-spacing: -1px; text-decoration: none; }}
            .logo span {{ color: var(--accent); }}
            .hero {{ text-align: center; padding: 80px 20px; background: radial-gradient(circle at top, #374151 0%, #111827 100%); }}
            h1 {{ font-size: 2.8rem; margin-bottom: 15px; line-height: 1.1; }}
            .highlight {{ color: var(--accent); }}
            .subtitle {{ color: #9ca3af; font-size: 1.2rem; max-width: 700px; margin: 0 auto; line-height: 1.5; }}
            .container {{ max-width: 1200px; margin: 0 auto; padding: 40px 20px; }}
            .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 30px; }}
            .card {{ background: var(--card); border-radius: 12px; overflow: hidden; border: 1px solid #374151; transition: transform 0.2s; position: relative; display: flex; flex-direction: column; }}
            .card:hover {{ transform: translateY(-5px); border-color: var(--accent); }}
            .badge {{ position: absolute; top: 10px; left: 10px; background: var(--accent); color: var(--btn-text); padding: 4px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 800; }}
            .card-img {{ width: 100%; height: 200px; object-fit: cover; background: #000; }}
            .card-body {{ padding: 20px; display: flex; flex-direction: column; flex-grow: 1; }}
            .headline {{ font-size: 1.1rem; font-weight: 700; margin: 0 0 10px 0; line-height: 1.3; }}
            .why {{ color: #d1d5db; font-size: 0.9rem; margin-bottom: 20px; flex-grow: 1; }}
            .btn {{ background: var(--accent); color: var(--btn-text); text-decoration: none; padding: 12px; border-radius: 6px; text-align: center; font-weight: 800; display: block; transition: opacity 0.2s; text-transform: uppercase; font-size: 0.9rem; }}
            .btn:hover {{ opacity: 0.9; }}
            footer {{ text-align: center; margin-top: 80px; padding: 40px; color: #6b7280; border-top: 1px solid #374151; font-size: 0.85rem; }}
        </style>
    </head>
    <body>
        <div class="nav">
            <a href="/" class="logo">BETTER<span>AMAZON</span>PRICES</a>
        </div>
        <div class="hero">
            <h1>Stop Overpaying on <span class="highlight">Amazon</span>.</h1>
            <p class="subtitle">We leverage AI to find you the best deals on Amazon so you don't have to. <br>Updated daily.</p>
        </div>
        <div class="container">
            <div class="grid">
    """
    
    if not deals:
        html += "<p style='grid-column: 1/-1; text-align: center;'>AI is scanning Amazon inventory... Updates arriving shortly.</p>"
        
    for deal in deals:
        html += f"""
        <div class="card">
            <div class="badge">{deal['discount_guess']}</div>
            <img src="{deal['img']}" class="card-img" loading="lazy" alt="{deal['headline']}">
            <div class="card-body">
                <div class="headline">{deal['headline']}</div>
                <div class="why">"{deal['why_good']}"</div>
                <a href="{deal['link']}" class="btn" target="_blank">View on Amazon &rarr;</a>
            </div>
        </div>
        """
        
    html += """
            </div>
        </div>
        <footer>
            <p>BetterAmazonPrices.com is a participant in the Amazon Services LLC Associates Program.<br>
            We use AI to aggregate publicly available deals.</p>
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
        generate_rss(final)
    else:
        generate_site([])
