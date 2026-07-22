from flask import Flask, request, jsonify
from curl_cffi import requests
from bs4 import BeautifulSoup
import time
import logging
import json

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)

def extract_data(soup, schema):
    result = {}
    for field in schema.get('fields', []):
        if field.get('type') == 'text':
            elements = soup.select(field.get('selector', ''))
            if elements:
                result[field['name']] = elements[0].get_text(strip=True)
            else:
                result[field['name']] = None
        elif field.get('type') == 'list':
            list_results = []
            elements = soup.select(field.get('selector', ''))
            for element in elements:
                item_data = {}
                for subfield in field.get('fields', []):
                    sub_elements = element.select(subfield.get('selector', ''))
                    if sub_elements:
                        item_data[subfield['name']] = sub_elements[0].get_text(strip=True)
                    else:
                        item_data[subfield['name']] = None
                list_results.append(item_data)
            result[field['name']] = list_results
    return result

import re

def extract_sellers_from_state(html_text, extracted_data):
    # Regex parser to find all sellers hidden in Noon's Javascript RSC payload
    matches = list(re.finditer(r'store_name:\s*\"([^\"]+)\"', html_text))
    
    sellers_found = []
    seen_sellers = set()
    
    # The first seller in the page is usually the recommended seller.
    # We will grab all of them anyway.
    for m in matches:
        name = m.group(1).strip()
        if not name or name in seen_sellers:
            continue
            
        idx = m.start()
        # Look behind the store_name string to find the price, and ahead to find the rating
        context = html_text[max(0, idx-2000):idx+1000]
        
        # Extract Price (usually before store_name)
        price_matches = list(re.finditer(r'price:\s*([\d\.]+)', context))
        if price_matches:
            price = price_matches[-1].group(1)
        else:
            sale_matches = list(re.finditer(r'sale_price:\s*([\d\.]+)', context))
            if sale_matches:
                price = sale_matches[-1].group(1)
            else:
                price = 'Unknown'
                
        # Format price with EGP
        if price != 'Unknown':
            price = f"EGP {price}"
            
        # Extract Rating (usually after store_name)
        rating_match = re.search(r'partner_rating:\s*([\d\.]+)', context)
        rating = rating_match.group(1) if rating_match else 'N/A'
        
        sellers_found.append({
            "seller_name": name,
            "price": price,
            "rating": rating
        })
        seen_sellers.add(name)
        
    if sellers_found:
        main_seller = extracted_data.get('recommended_seller_name', '')
        
        # Patch the recommended_seller_rating if we found it in the RSC state
        if main_seller:
            for s in sellers_found:
                if s['seller_name'] == main_seller and s['rating'] != 'N/A':
                    extracted_data['recommended_seller_rating'] = s['rating']
                    break
        
        # Filter out the main recommended seller from the "other_offers" list to avoid duplication
        if main_seller:
            sellers_found = [s for s in sellers_found if s['seller_name'] != main_seller]
            
        extracted_data['other_offers'] = sellers_found
        logging.info(f"Successfully extracted {len(sellers_found)} other sellers directly from RSC state!")
        
    return extracted_data

@app.route('/scrape', methods=['POST'])
def scrape():
    start_time = time.time()
    
    data = request.get_json()
    if not data:
         return jsonify({"error": "No JSON payload received"}), 400
         
    urls = data.get("urls")
    schema = data.get("schema")

    if not isinstance(urls, list) or not isinstance(schema, dict):
        return jsonify({"error": "Invalid input. 'urls' must be a list, 'schema' must be a dict."}), 400

    results = []
    
    # We will reuse the same session to keep connection pooling alive
    session = requests.Session(impersonate="chrome120")
    
    for url in urls:
        url_start_time = time.time()
        try:
            # 1. Fetch the raw HTML using curl_cffi (Bypasses Anti-Bot)
            res = session.get(
                url, 
                timeout=15,
                headers={
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8'
                }
            )
            html_fetch_time = time.time() - url_start_time
            
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'lxml')
                
                # 2. Extract standard fields via CSS Selectors
                extracted = extract_data(soup, schema)
                
                # 3. Inject the other offers directly from the React Server Component JS state!
                extracted = extract_sellers_from_state(res.text, extracted)
                
                results.append({
                    "url": url, 
                    "status": res.status_code, 
                    "data": extracted
                })
            else:
                results.append({
                    "url": url, 
                    "status": res.status_code, 
                    "error": f"HTTP Error {res.status_code}"
                })
                
        except Exception as e:
            results.append({
                "url": url, 
                "status": 500, 
                "error": str(e)
            })

    return jsonify(results)

if __name__ == '__main__':
    from waitress import serve
    print("Starting Noon CFFI production server with Waitress (Max 8 threads)...")
    serve(app, host='0.0.0.0', port=5000, threads=8)
