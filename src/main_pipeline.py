import os
import yaml
import feedparser
import requests
import json
import time
from datetime import datetime
from openai import OpenAI

# --- SETUP ---
def load_config():
    with open("config/config.yaml", "r") as f:
        return yaml.safe_load(f)

config = load_config()
# Switch to gpt-4o-mini (cheaper, wider availability)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
BEEHIIV_API_KEY = os.environ.get("BEEHIIV_API_KEY")
BEEHIIV_PUB_ID = os.environ.get("BEEHIIV_PUB_ID")

# --- HELPER: AUTO-FIND ID ---
def get_publication_id():
    if BEEHIIV_PUB_ID != "auto":
        return BEEHIIV_PUB_ID
    
    print("Attempting to auto-detect Publication ID...")
    url = "https://api.beehiiv.com/v2/publications"
    headers = {"Authorization": f"Bearer {BEEHIIV_API_KEY}"}
    
    try:
        resp = requests.get(url, headers=headers)
        data = resp.json()
        found_id = data['data'][0]['id']
        print(f"Auto-detected ID: {found_id}")
        return found_id
    except Exception as e:
        print(f"Could not auto-detect ID. Error: {e}")
        return None

# --- STEP 1: INGEST (With Anti-Block Headers) ---
def fetch_deals():
    print("--- Step 1: Fetching Deals ---")
    raw_deals = []
    # Fake being a browser to avoid blocks
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
    
    for source in config['sources']:
        print(f"Checking {source['name']}...")
        try:
            # Download feed manually first to pass headers
            response = requests.get(source['url'], headers=headers, timeout=10)
            feed = feedparser.parse(response.content)
            
            print(f"  - Found {len(feed.entries)} entries in feed.")
            
            for entry in feed.entries[:5]: # Limit to top 5 per source
                raw_deals.append({
                    "title": entry.title,
                    "link": entry.link,
                    "summary": entry.get('summary', ''),
                    "source": source['name']
                })
        except Exception as e:
            print(f"Error fetching {source['name']}: {e}")
            
    print(f"Total raw deals found: {len(raw_deals)}")
    return raw_deals

# --- STEP 2: FILTER ---
def filter_deals(deals):
    print("--- Step 2: Filtering ---")
    filtered = []
    excludes = [x.lower() for x in config['filters']['keywords_exclude']]
    
    for deal in deals:
        title_lower = deal['title'].lower()
        if any(bad_word in title_lower for bad_word in excludes):
            continue
        filtered.append(deal)
        
    # Deduplicate
    unique_deals = {v['link']:v for v in filtered}.values()
    final_list = list(unique_deals)[:config['content']['deals_per_issue']]
    print(f"Deals passing filter: {len(final_list)}")
    return final_list

# --- STEP 3: AI ENRICHMENT ---
def ai_rewrite(deals):
    print("--- Step 3: AI Writing ---")
    enriched = []
    for deal in deals:
        print(f"Rewriting: {deal['title']}...")
        prompt = f"""
        Rewrite this tech deal for a newsletter.
        Title: {deal['title']}
        Link: {deal['link']}
        
        Output JSON with keys: "headline", "body", "cta".
        Keep it short.
        """
        
        try:
            # Using gpt-4o-mini is safer for new accounts
            response = client.chat.completions.create(
                model="gpt-4o-mini", 
                messages=[{"role": "user", "content": prompt}],
                response_format={ "type": "json_object" }
            )
            content = json.loads(response.choices[0].message.content)
            deal.update(content)
            enriched.append(deal)
        except Exception as e:
            print(f"AI Error for '{deal['title']}': {e}")
            # Fallback: Use original title if AI fails
            deal['headline'] = deal['title']
            deal['body'] = "Check out this deal."
            deal['cta'] = "View Deal"
            enriched.append(deal)
            
    return enriched

# --- STEP 4: PUBLISH TO BEEHIIV ---
def publish_draft(deals):
    print("--- Step 4: Publishing to Beehiiv ---")
    
    if not deals:
        print("No deals to publish. Aborting.")
        return

    pub_id = get_publication_id()
    if not pub_id: return

    date_str = datetime.now().strftime('%B %d, %Y')
    
    # BUILD HTML
    html_content = f"<p>Top Tech Drops for {date_str}</p><br>"
    for deal in deals:
        html_content += f"""
        <h3><a href="{deal['link']}">{deal['headline']}</a></h3>
        <p>{deal['body']}</p>
        <p><a href="{deal['link']}">{deal['cta']} &rarr;</a></p>
        <br>
        """
    html_content += f"<p><small>{config['footer_text']}</small></p>"

    # PRINT HTML TO LOGS FOR DEBUGGING
    print("GENERATED HTML PREVIEW:")
    print(html_content[:500] + "...") 

    url = f"https://api.beehiiv.com/v2/publications/{pub_id}/posts"
    headers = {
        "Authorization": f"Bearer {BEEHIIV_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "title": f"CircuitBreaker: {date_str}",
        "content": {
            "body": html_content,
            "thumbnail": "" 
        },
        "audience": "all",
        "platform": "both",
        "status": "draft"
    }
    
    resp = requests.post(url, json=payload, headers=headers)
    if resp.status_code in [200, 201]:
        print("SUCCESS: Draft created in Beehiiv!")
    else:
        print(f"FAILED: {resp.text}")

if __name__ == "__main__":
    raw = fetch_deals()
    if raw:
        selected = filter_deals(raw)
        final = ai_rewrite(selected) # Run even if selected is empty to see logs
        publish_draft(final)
    else:
        print("No raw deals found.")
