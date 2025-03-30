"""Used tp find ebooks and sort them before returning them"""
def filter_ebook_items(data, json_path="media.metadata.title", sort_reverse=False):
    """Find items in a library that have an ebook file, sorted by a field in a specific order"""
    # Filter results to include only items with an ebook file
    filtered_results = []
    for result in data.get("results", []):
        media = result.get("media", {})
        if "ebookFormat" in media and media.get("ebookFormat", None):
            filtered_results.append(result)

    # Function to extract value based on json_path
    def extract_value(item, path):
        keys = path.split('.')
        for key in keys:
            item = item.get(key, None)
            if item is None:
                break
        return item

    # Sort the filtered results based on the extracted value and sort_reverse flag
    sorted_results = sorted(
            filtered_results,
            key=lambda x: extract_value(x, json_path),
            reverse=sort_reverse
        )

    return sorted_results
