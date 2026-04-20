# Copyright (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

"""
MCP Server for Route Planning Agent

Exposes live traffic data as an MCP tool, allowing route-planner to call
get_live_traffic via MCP protocol instead of directly instantiating the controller.

Usage:
    python mcp_server.py
"""

import asyncio
import json
import sys
import logging
import os
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from controllers import LiveTrafficController
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Log to file in the src directory (absolute path)
src_dir = os.path.dirname(os.path.abspath(__file__))
log_file = os.path.join(src_dir, "mcp_server.log")
file_handler = logging.FileHandler(log_file)
file_handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
logging.getLogger().addHandler(file_handler)

logger.info("="*60)
logger.info(f"MCP Server started (logging to {log_file})")
logger.info("="*60)



async def main():
    """Main entry point for MCP server."""
    logger.info("Starting MCP Server for Route Planning Agent")
    logger.info("Server: route-traffic-server (version 1.0.0)")
    logger.info("Available tools: get_live_traffic")
    logger.info("Transport: stdio")

    # Create MCP server instance
    server = Server("route-traffic-server", version="1.0.0")

    @server.list_tools()
    async def list_tools():
        """List available tools."""
        logger.debug("MCP: list_tools() called")
        return [
            Tool(
                name="get_live_traffic",
                description="Fetch real-time live traffic data from all configured intersections",
                inputSchema={
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            )
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]):
        """Handle tool calls."""
        logger.debug(f"MCP: call_tool({name}) called")

        if name == "get_live_traffic":
            try:
                logger.info("MCP Tool: get_live_traffic called")

                # Instantiate controller and fetch live traffic data
                live_traffic_controller = LiveTrafficController()
                all_routes_data = await live_traffic_controller.fetch_route_status()

                logger.info(
                    f"MCP Tool: Successfully fetched {len(all_routes_data)} traffic records"
                )

                # Convert Pydantic models to dictionaries for JSON serialization
                traffic_data_dicts = [
                    json.loads(record.model_dump_json())
                    for record in all_routes_data
                ]

                response_dict = {
                    "success": True,
                    "traffic_data": traffic_data_dicts,
                    "count": len(traffic_data_dicts)
                }

                # Return as TextContent (wrapped in list for ContentBlock)
                return [TextContent(
                    type="text",
                    text=json.dumps(response_dict)
                )]

            except Exception as e:
                logger.error(f"MCP Tool: Error fetching live traffic data: {e}")
                error_response = {
                    "success": False,
                    "error": str(e),
                    "traffic_data": [],
                    "count": 0
                }
                return [TextContent(
                    type="text",
                    text=json.dumps(error_response)
                )]
        else:
            raise ValueError(f"Unknown tool: {name}")

    # Run server with stdio transport
    # stdio_server() yields (read_stream, write_stream) tuple
    async with stdio_server() as (read_stream, write_stream):
        logger.info("MCP Server ready and waiting for requests on stdio")
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )
        logger.info("MCP Server shutting down")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("MCP Server stopped by user")
    except Exception as e:
        logger.error(f"MCP Server fatal error: {e}", exc_info=True)
