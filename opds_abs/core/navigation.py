"""This module provides navigation menu items for the OPDS feed."""
navigation = [
        {
            "name":   "Items",
            "desc":   "View all items in your library",
            "path":   "items",
            "params": "sort=media.metadata.title"
        },
        {
            "name":   "Recent",
            "desc":   "View recently added items",
            "path":   "items",
            "params": "sort=addedAt&desc=1"
        },
        {
            "name":   "Series",
            "desc":   "Browse by series",
            "path":   "series",
            "params": ""
        },
        {
            "name":   "Collections",
            "desc":   "Browse by collection",
            "path":   "collections",
            "params": ""
        },
        {
            "name":   "Authors",
            "desc":   "Browse by author",
            "path":   "authors",
            "params": ""
        }
]
