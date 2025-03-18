from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.responses import Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import requests
import os
from lxml import etree

app = FastAPI()
security = HTTPBasic()

# Načtení konfigurace z prostředí
# Load configuration from environment variables
AUDIOBOOKSHELF_URL = os.getenv("AUDIOBOOKSHELF_URL", "http://localhost:13378")
AUDIOBOOKSHELF_API = f"{AUDIOBOOKSHELF_URL}/api"

# Načteme API klíče uživatelů z prostředí
# Load user API keys from environment variables
USER_KEYS = {}
users_env = os.getenv("USERS", "")
for pair in users_env.split(","):
    if ":" in pair:
        username, api_key = pair.split(":", 1)
        USER_KEYS[username] = api_key

# Načtení jazyka z prostředí (cs nebo en)
# Load language from environment variables (cs or en)
LANGUAGE = os.getenv("LANGUAGE", "cs")

def get_message(cs_message, en_message):
    """Return the message based on the selected language"""
    return cs_message if LANGUAGE == "cs" else en_message

def fetch_from_api(endpoint: str, api_key: str):
    """Obecná funkce pro volání API s uživatelským API klíčem"""
    """General function to call API with user's API key"""
    headers = {"Authorization": f"Bearer {api_key}"}
    url = f"{AUDIOBOOKSHELF_API}{endpoint}"
    print(get_message(f"📡 Načítání: {url}", f"📡 Fetching: {url}"))  # Debugging

    try:
        response = requests.get(url, headers=headers, timeout=10)  # Timeout 10s
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail="API Timeout")
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=get_message(f"Chyba API: {str(e)}", f"API Error: {str(e)}"))

def get_download_urls(id: str, api_key: str):
    """Získejte adresu URL ke stažení z ID položky"""
    item = fetch_from_api(f"/items/{id}", api_key)
    ebook_inos = [{"ino":file.get("ino"),"filename":file.get("metadata").get("filename")} for file in item.get("libraryFiles", []) if "ebook" in file.get("fileType", "")]
    return ebook_inos

@app.get("/opds/{username}")
def opds_root(username: str):
    """Vrátí seznam knihoven pro konkrétního uživatele"""
    """Returns a list of libraries for a specific user"""
    if username not in USER_KEYS:
        raise HTTPException(status_code=404, detail="User not found")

    api_key = USER_KEYS[username]
    data = fetch_from_api("/libraries", api_key)
    feed = etree.Element("feed", xmlns="http://www.w3.org/2005/Atom", nsmap={"opds": "http://opds-spec.org/2010/catalog"})
    title = etree.SubElement(feed, "title")
    title.text = f"{username}'s Libraries"

    for library in data.get("libraries", []):
        entry = etree.SubElement(feed, "entry")
        entry_title = etree.SubElement(entry, "title")
        entry_title.text = library["name"]
        link = etree.SubElement(entry, "link", href=f"/opds/{username}/library/{library['id']}", rel="subsection", type="application/atom+xml")

    feed_xml = etree.tostring(feed, pretty_print=True, xml_declaration=False, encoding="UTF-8")
    return Response(content=feed_xml, media_type="application/atom+xml")

@app.get("/opds/{username}/library/{library_id}")
def opds_library(username: str, library_id: str):
    """Seznam knih v konkrétní knihovně pro konkrétního uživatele"""
    """List of books in a specific library for a specific user"""
    if username not in USER_KEYS:
        raise HTTPException(status_code=404, detail="User not found")

    api_key = USER_KEYS[username]
    data = fetch_from_api(f"/libraries/{library_id}/items", api_key)

    print(get_message(f"📥 API odpověď obsahuje {len(data.get('results', []))} položek", f"📥 API response contains {len(data.get('results', []))} items"))

    feed = etree.Element("feed", xmlns="http://www.w3.org/2005/Atom", nsmap={"opds": "http://opds-spec.org/2010/catalog"})
    title = etree.SubElement(feed, "title")
    title.text = f"{username}'s books"

    for book in data.get("results", []):
        print(get_message(f"🔍 Zpracovávám: {book.get('id')}", f"🔍 Processing: {book.get('id')}"))

        ebook_format = book.get("media", {}).get("ebookFormat", None)
        if not ebook_format:
            print(get_message(f"⏭ Přeskakuji: {book.get('id')} (chybí ebookFormat)", f"⏭ Skipping: {book.get('id')} (missing ebookFormat)"))
            continue
            
        book_id = book.get("id", "")
        ebook_inos = get_download_urls(book_id, api_key)
        for ebook in ebook_inos:
            ino, filename = ebook.get("ino"), ebook.get("filename")
            entry_title_text = book.get("media", {}).get("metadata", {}).get("title", "Neznámý název")
            
            download_path = f"{AUDIOBOOKSHELF_API}/items/{book_id}/file/{ino}/download?token={api_key}" 
            cover_url = f"{AUDIOBOOKSHELF_API}/items/{book_id}/cover?format=jpeg"

            print(f"✅ Přidávám knihu: {entry_title_text} ({ebook_format})")

            entry = etree.SubElement(feed, "entry")
            entry_title = etree.SubElement(entry, "title")
            entry_title.text = entry_title_text
            entry_id = etree.SubElement(entry, "id")
            entry_id.text = book_id
            entry_filename = etree.SubElement(entry, "content", type="text")
            entry_filename.text = filename
            link_download = etree.SubElement(entry, "link", href=download_path, rel="http://opds-spec.org/acquisition/open-access", type=f"application/{ebook_format}")
            link_cover = etree.SubElement(entry, "link", href=cover_url, rel="http://opds-spec.org/image", type="image/jpeg")

    feed_xml = etree.tostring(feed, pretty_print=True, xml_declaration=False, encoding="UTF-8")
    return Response(content=feed_xml, media_type="application/atom+xml")

@app.get("/")
def index():
    content_cs = """
    <!DOCTYPE html>
    <html lang='cs'>
    <head>
        <meta charset='UTF-8'>
        <title>OPDS Přihlášení</title>
    </head>
    <body>
        <h1>Vítejte v OPDS serveru</h1>
    </body>
    </html>
    """
    
    content_en = """
    <!DOCTYPE html>
    <html lang='en'>
    <head>
        <meta charset='UTF-8'>
        <title>OPDS Login</title>
    </head>
    <body>
        <h1>Welcome to the OPDS server</h1>
    </body>
    </html>
    """
    
    return Response(content=get_message(content_cs, content_en), media_type="text/html")


# Dockerfile
DOCKERFILE = """
FROM python:3.10
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
"""

# docker-compose.yml
docker_compose = """
version: '3.8'
services:
  opds:
    image: ghcr.io/petr-prikryl/opds-abs:latest
    ports:
      - "8000:8000"
    environment:
      - AUDIOBOOKSHELF_URL=http://audiobookshelf:13378
      - USERS=John:API_KEY_1,Jan:API_KEY_2,guest:API_KEY_3
      - LANGUAGE=cs  # Set the language to Czech (cs) or English (en)
"""

# Uložení souborů
# Save files
with open("Dockerfile", "w") as f:
    f.write(DOCKERFILE)

with open("docker-compose.yml", "w") as f:
    f.write(docker_compose)
