from flask import Flask, render_template, send_from_directory
import os
import requests
from bs4 import BeautifulSoup
import re
import pdfplumber
from pdf2image import convert_from_path
from datetime import datetime

app = Flask(__name__)

KEYWORDS = ['Schreiner', 'Steckersolargeräte', 'Wegner', 'Wilmersdorf', 'Senatsverwaltung für Mobilität, Verkehr, Klimaschutz und Umwelt']

def fetch_article(url, retries=3):
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response
    except requests.exceptions.RequestException as e:
        if retries > 0:
            time.sleep(3)
            return fetch_article(url, retries - 1)
        else:
            print(f"Fehler beim Abrufen von {url}: {e}")
            return None

def check_website_for_news():
    url = 'https://www.berlin.de/presse/'
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')
    articles = soup.find_all('a', href=re.compile(r'pressemitteilung.*\.php'))

    found_articles = []

    for article in articles:
        title = article.text.strip()
        link = article['href']
        article_url = f'https://www.berlin.de{link}'
        
        category_span = article.find_next('span', class_='category')
        if category_span:
            category_text = category_span.get_text(strip=True)
            if any(keyword.lower() in category_text.lower() for keyword in KEYWORDS):
                article_response = fetch_article(article_url)
                if article_response:
                    article_soup = BeautifulSoup(article_response.content, 'html.parser')
                    content_block = article_soup.find('div', class_='textile')
                    if content_block:
                        content = content_block.get_text(strip=True, separator='\n')
                        found_articles.append((title, content, article_url))
                continue

        article_response = fetch_article(article_url)
        if article_response:
            article_soup = BeautifulSoup(article_response.content, 'html.parser')
            content_block = article_soup.find('div', class_='textile')
            if content_block:
                content = content_block.get_text(strip=True, separator='\n')
                for keyword in KEYWORDS:
                    if re.search(r'\b{}\b'.format(keyword), content, re.IGNORECASE):
                        found_articles.append((title, content, article_url))
                        break

    return found_articles

def find_latest_pdf_link_and_metadata():
    url = 'https://www.berlin.de/landesverwaltungsamt/logistikservice/amtsblatt-fuer-berlin/'
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')
    pdf_tag = soup.find('a', href=re.compile(r'.*\.pdf'))
    pdf_url = pdf_tag['href'] if pdf_tag else None

    if pdf_url and not pdf_url.startswith('http'):
        pdf_url = 'https://www.berlin.de' + pdf_url

    metadata_tag = pdf_tag.find_parent('li')
    metadata_text = metadata_tag.get_text(strip=True) if metadata_tag else "Amtsblatt"
    metadata_text = clean_metadata(metadata_text)

    return pdf_url, metadata_text

def clean_metadata(metadata):
    metadata = re.sub(r'PDF-Dokument.*$', '', metadata)
    metadata = metadata.strip()
    return metadata.replace(" ", "_")

def download_pdf(url, path):
    response = requests.get(url)
    content_type = response.headers['Content-Type']
    if 'application/pdf' in content_type:
        with open(path, 'wb') as file:
            file.write(response.content)

def highlight_and_extract_pages(pdf_path, keywords, output_dir):
    found_pages = set()
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            text = page.extract_text()
            if not text:
                continue
            for keyword in keywords:
                if re.search(r'\b{}\b'.format(keyword), text, re.IGNORECASE):
                    found_pages.update([page_num - 1, page_num, page_num + 1])
                    break

    found_pages = {p for p in found_pages if 0 <= p < len(pdf.pages)}

    if not found_pages:
        return

    images = convert_from_path(pdf_path)
    os.makedirs(output_dir, exist_ok=True)

    for page_num in sorted(found_pages):
        image_path = os.path.join(output_dir, f"page_{page_num + 1}.png")
        images[page_num].save(image_path, 'PNG')

@app.route('/')
def index():
    # Check for news
    news_articles = check_website_for_news()

    # Check for latest Amtsblatt
    pdf_url, metadata = find_latest_pdf_link_and_metadata()
    if pdf_url:
        output_dir = os.path.join('static', 'downloads', metadata)
        os.makedirs(output_dir, exist_ok=True)
        
        complete_pdf_path = os.path.join(output_dir, f"{metadata}.pdf")
        download_pdf(pdf_url, complete_pdf_path)
        
        highlight_and_extract_pages(complete_pdf_path, KEYWORDS, output_dir)
    
    return render_template('index.html', articles=news_articles, pdf_metadata=metadata)

@app.route('/download/<path:filename>')
def download(filename):
    directory = os.path.join(app.root_path, 'static', 'downloads')
    return send_from_directory(directory, filename)

if __name__ == '__main__':
    app.run(debug=True)
