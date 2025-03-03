from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.responses import Response
import requests
import os

app = FastAPI()

# Načtení konfigurace z prostředí
AUDIOBOOKSHELF_URL = os.getenv("AUDIOBOOKSHELF_URL", "http://localhost:13378")
AUDIOBOOKSHELF_API = f"{AUDIOBOOKSHELF_URL}/api"
API_KEY = os.getenv("AUDIOBOOKSHELF_API_KEY", "")  # API klíč, pokud je potřeba


def fetch_from_api(endpoint: str):
    """Obecná funkce pro volání API"""
    headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}
    try:
        url = f"{AUDIOBOOKSHELF_API}{endpoint}"
        print(f"Fetching: {url}")  # Debug: zobrazí URL požadavku
        response = requests.get(url, headers=headers)
        print("Response:", response.text)  # Debug: zobrazí odpověď API
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Chyba API: {str(e)}")



@app.get("/opds")
def opds_root():
    """Hlavní OPDS feed"""
    return Response(content="""
    <feed xmlns="http://www.w3.org/2005/Atom" xmlns:opds="http://opds-spec.org/2010/catalog">
        <title>Audiobookshelf OPDS</title>
        <entry>
            <title>Knihovna</title>
            <link href="/opds/catalog" rel="subsection" type="application/atom+xml"/>
        </entry>
    </feed>
    """, media_type="application/atom+xml")


@app.get("/opds/catalog")
def opds_catalog():
    """Seznam knihoven"""
    data = fetch_from_api("/libraries")
    feed = """
    <feed xmlns="http://www.w3.org/2005/Atom" xmlns:opds="http://opds-spec.org/2010/catalog">
        <title>Seznam knihoven</title>
    """

    for library in data.get("libraries", []):
        feed += f"""
        <entry>
            <title>{library['name']}</title>
            <link href="/opds/library/{library['id']}" rel="subsection" type="application/atom+xml"/>
        </entry>
        """

    feed += "</feed>"
    return Response(content=feed, media_type="application/atom+xml")


@app.get("/opds/library/{library_id}")
def opds_library(library_id: str):
    """Seznam knih v konkrétní knihovně"""
    data = fetch_from_api(f"/libraries/{library_id}/items")

    # Debug: Výpis přijatých dat
    print(f"📥 API odpověď obsahuje {len(data.get('results', []))} položek")

    feed = """
    <feed xmlns="http://www.w3.org/2005/Atom" xmlns:opds="http://opds-spec.org/2010/catalog">
        <title>Knihy v knihovně</title>
    """

    for book in data.get("results", []):
        print(f"🔍 Zpracovávám: {book.get('id')}")

        # Zjistíme, zda má kniha platný formát (EPUB/PDF/atd.)
        ebook_format = book.get("media", {}).get("ebookFormat", None)
        if not ebook_format:
            print(f"⏭ Přeskakuji: {book.get('id')} (chybí ebookFormat)")
            continue

        title = book.get("media", {}).get("metadata", {}).get("title", "Neznámý název")
        book_id = book.get("id", "")
        api_key_param = f"?token={API_KEY}" if API_KEY else ""
        cover_path = book.get("media", {}).get("coverPath", "")
        download_path = f"{AUDIOBOOKSHELF_API}/items/{book_id}/download{api_key_param}"

        cover_url = f"{AUDIOBOOKSHELF_API}{cover_path}{api_key_param}" if cover_path else ""

        print(f"✅ Přidávám knihu: {title} ({ebook_format})")

        feed += f"""
        <entry>
            <title>{title}</title>
            <id>{book_id}</id>
            <link href="{download_path}" rel="http://opds-spec.org/acquisition/open-access" type="application/{ebook_format}"/>
            <link href="{cover_url}" rel="http://opds-spec.org/image" type="image/jpeg"/>
        </entry>
        """

    feed += "</feed>"
    return Response(content=feed, media_type="application/atom+xml")


# Jednoduché HTML rozhraní pro výběr knihovny
@app.get("/")
def index():
    return Response(content="""
    <!DOCTYPE html>
    <html lang='cs'>
    <head>
        <meta charset='UTF-8'>
        <title>OPDS Přihlášení</title>
    </head>
    <body>
        <h1>Vítejte v OPDS serveru</h1>
        <form action="/opds/catalog">
            <button type='submit'>Zobrazit knihovny</button>
        </form>
    </body>
    </html>
    """, media_type="text/html")


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
    build: .
    ports:
      - "8000:8000"
    environment:
      - AUDIOBOOKSHELF_URL=http://audiobookshelf:13378
      - AUDIOBOOKSHELF_API_KEY=your_api_key_here

"""

# Uložení souborů
with open("Dockerfile", "w") as f:
    f.write(DOCKERFILE)

with open("docker-compose.yml", "w") as f:
    f.write(docker_compose)
