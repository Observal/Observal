def generate_graphrag_config(graphrag_listing, ide: str, server_url: str = "http://localhost:8000") -> dict:
    """Generate config snippet that routes GraphRAG traffic through observal-graphrag-proxy."""
    graphrag_id = str(graphrag_listing.id)
    endpoint_url = str(graphrag_listing.endpoint_url)

    return {
        "graphrag": {
            "proxy_url": "http://localhost:0",  # 0 = auto-assign port
            "original_endpoint": endpoint_url,
            "start_command": f"observal-graphrag-proxy --graphrag-id {graphrag_id} --target {endpoint_url}",
        },
        "env": {
            "OBSERVAL_KEY": "$OBSERVAL_API_KEY",
            "OBSERVAL_SERVER": server_url,
        },
        "ide": ide,
        "listing_id": graphrag_id,
    }
