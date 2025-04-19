"""Utility functions for translating Python dictionaries to XML elements for OPDS feeds."""
# Standard library imports
from typing import Dict, Any

# Third-party imports
from lxml import etree


def dict_to_xml(parent_element, data: Dict[str, Any]) -> None:
    """Convert a dictionary structure to XML elements and add them to the parent element.

    The dictionary should have element names as keys and their content/attributes as values.
    Special keys:
    - "_text": The text content of the element
    - "_attrs": A dictionary of attribute name-value pairs
    - Any other keys are treated as child elements

    Example:
    {
        "entry": {
            "_attrs": {"id": "123"},
            "title": {"_text": "Book Title"},
            "author": {
                "name": {"_text": "Author Name"}
            },
            "link": [
                {"_attrs": {"href": "/path1", "rel": "subsection", "type": "application/atom+xml"}},
                {"_attrs": {"href": "/path2", "rel": "image", "type": "image/jpeg"}}
            ]
        }
    }

    Args:
        parent_element: The parent XML element to add children to
        data: Dictionary containing the element structure
    """
    for key, value in data.items():
        if isinstance(value, dict):
            # Extract attributes and text if present
            attrs = value.pop("_attrs", {})
            text = value.pop("_text", None)

            # Create the element with attributes
            element = etree.SubElement(parent_element, key, **attrs)

            # Set text content if provided
            if text is not None:
                element.text = str(text)

            # Process child elements recursively
            dict_to_xml(element, value)

        elif isinstance(value, list):
            # Handle lists of elements with the same tag name
            for item in value:
                # Create a new dict with the current key and the list item as value
                dict_to_xml(parent_element, {key: item})

        else:
            # Simple case: element with just text content
            element = etree.SubElement(parent_element, key)
            if value is not None:
                element.text = str(value)
