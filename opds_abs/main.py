"""Routes for the OPDS feed"""
from urllib.parse import unquote
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from opds_abs.feeds.library_feed import LibraryFeedGenerator
from opds_abs.feeds.navigation_feed import NavigationFeedGenerator
from opds_abs.feeds.series_feed import SeriesFeedGenerator
from opds_abs.feeds.collection_feed import CollectionFeedGenerator
from opds_abs.feeds.author_feed import AuthorFeedGenerator
from opds_abs.feeds.search_feed import SearchFeedGenerator

# Create instances of our feed generators
library_feed = LibraryFeedGenerator()
navigation_feed = NavigationFeedGenerator()
series_feed = SeriesFeedGenerator()
collection_feed = CollectionFeedGenerator()
author_feed = AuthorFeedGenerator()
search_feed = SearchFeedGenerator()

# Create FastAPI app
app = FastAPI()

# Mount static files directory
app.mount("/static", StaticFiles(directory="opds_abs/static"), name="static")

# Setup templates
templates = Jinja2Templates(directory="opds_abs/templates")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """Base path loading page"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/opds/{username}/libraries/{library_id}/search.xml", response_class=HTMLResponse)
def search_xml(username: str, library_id: str, request: Request):
    """Search XML feed for a specific library"""
    params = dict(request.query_params)
    return templates.TemplateResponse("search.xml", {
        "request": request, 
        "username": username, 
        "library_id": library_id, 
        "searchTerms": params.get('q', '')
    })


@app.get("/opds/{username}")
async def opds_root(username: str):
    """Returns a list of libraries for a specific user"""
    return await library_feed.generate_root_feed(username)


@app.get("/opds/{username}/libraries/{library_id}")
async def opds_nav(username: str, library_id: str):
    """Returns navigation feed for a library"""
    return await navigation_feed.generate_nav_feed(username, library_id)


@app.get("/opds/{username}/libraries/{library_id}/search")
async def opds_search(username: str, library_id: str, request: Request):
    """Returns search results for a library"""
    params = dict(request.query_params)
    return await search_feed.generate_search_feed(username, library_id, params)


@app.get("/opds/{username}/libraries/{library_id}/items")
async def opds_library(username: str, library_id: str, request: Request):
    """List of books in a specific library for a specific user"""
    params = dict(request.query_params)
    return await library_feed.generate_library_items_feed(username, library_id, params)


@app.get("/opds/{username}/libraries/{library_id}/series")
async def opds_series(username: str, library_id: str):
    """List of series in a specific library for a specific user"""
    return await series_feed.generate_series_feed(username, library_id)


@app.get("/opds/{username}/libraries/{library_id}/collections")
async def opds_collections(username: str, library_id: str):
    """List of collections in a specific library for a specific user"""
    return await collection_feed.generate_collections_feed(username, library_id)


@app.get("/opds/{username}/libraries/{library_id}/authors")
async def opds_authors(username: str, library_id: str):
    """List of authors in a specific library for a specific user"""
    return await author_feed.generate_authors_feed(username, library_id)