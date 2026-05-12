"""Tool definitions exposed to the LLM. The schema follows the OpenAI
function-calling format, which Ollama also implements for capable models.

Each tool maps to a real backend operation. The `create_order` tool is
intentionally split into two phases (propose + confirm) so the LLM can never
create an order without explicit user confirmation."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "semantic_search_products",
            "description": (
                "Find products matching a natural-language description. "
                "Use this for vague or descriptive queries like 'something quiet "
                "for typing' or 'gift for a coffee lover'. Returns up to 10 "
                "products with similarity scores."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language description of what the user is looking for",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of products to return (1-10)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_product",
            "description": (
                "Fetch full details (name, description, price, stock, category) for "
                "a specific product by its ID. Use after semantic_search to get "
                "more details, or when the user mentions a specific product."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_id": {
                        "type": "integer",
                        "description": "The numeric ID of the product",
                    },
                },
                "required": ["product_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_order",
            "description": (
                "Propose creating an order. This DOES NOT create the order — it "
                "stages a proposal that the user must explicitly confirm. After "
                "calling this, ALWAYS show the user a summary (items, prices, "
                "total) and ask them to confirm with 'yes' or 'confirm'. Only "
                "after they confirm should you call confirm_order."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "Items to include in the order",
                        "items": {
                            "type": "object",
                            "properties": {
                                "product_id": {"type": "integer"},
                                "quantity": {"type": "integer", "minimum": 1},
                            },
                            "required": ["product_id", "quantity"],
                        },
                    },
                },
                "required": ["items"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_order",
            "description": (
                "Place the order that was previously proposed via propose_order. "
                "ONLY call this when the user has explicitly confirmed (e.g. said "
                "'yes', 'confirm', 'place it', 'go ahead'). NEVER call this without "
                "first calling propose_order and getting user confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_orders",
            "description": (
                "Get the user's recent orders. Use when the user asks 'what did I "
                "order' or 'check my orders'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of recent orders to return",
                        "default": 5,
                    },
                },
            },
        },
    },
]
