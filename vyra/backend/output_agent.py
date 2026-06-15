"""
Output Agent Module
Handles visualization generation tool calls and manages output visualization requests.
"""

import asyncio
from output_generator import (
    generate_bar_chart,
    generate_line_chart,
    generate_pie_chart,
    generate_heatmap,
    generate_flowchart,
    format_terminal_output
)


class OutputAgent:
    """Agent for handling visualization generation requests."""

    def __init__(self):
        """Initialize the output agent."""
        self.current_visualization = None

    async def generate_visualization(self, visualization_type, data, title, x_label=None, y_label=None):
        """
        Generate visualization based on type and data.

        Args:
            visualization_type: Type of visualization (bar_chart, line_chart, etc.)
            data: Data dictionary for the visualization
            title: Title for the visualization
            x_label: X-axis label (optional, for charts)
            y_label: Y-axis label (optional, for charts)

        Returns:
            Result dictionary with path, type, timestamp, etc.
        """
        try:
            print(f"[OutputAgent] Generating {visualization_type}: {title}")

            # Run generation in thread pool to avoid blocking
            if visualization_type == "bar_chart":
                result = await asyncio.to_thread(
                    generate_bar_chart,
                    data, title, x_label or "X", y_label or "Y"
                )
            elif visualization_type == "line_chart":
                result = await asyncio.to_thread(
                    generate_line_chart,
                    data, title, x_label or "X", y_label or "Y"
                )
            elif visualization_type == "pie_chart":
                result = await asyncio.to_thread(
                    generate_pie_chart,
                    data, title
                )
            elif visualization_type == "heatmap":
                result = await asyncio.to_thread(
                    generate_heatmap,
                    data, title
                )
            elif visualization_type == "flowchart":
                result = await asyncio.to_thread(
                    generate_flowchart,
                    data, title
                )
            elif visualization_type == "terminal":
                result = await asyncio.to_thread(
                    format_terminal_output,
                    data, title
                )
            else:
                return {"error": f"Unknown visualization type: {visualization_type}"}

            if 'error' in result:
                print(f"[OutputAgent] Error: {result['error']}")
                return result

            print(
                f"[OutputAgent] Successfully generated: {result.get('path', '')}")
            self.current_visualization = result
            return result

        except Exception as e:
            error_msg = f"Failed to generate visualization: {str(e)}"
            print(f"[OutputAgent] {error_msg}")
            return {"error": error_msg}

    def get_current_visualization(self):
        """Get the most recently generated visualization."""
        return self.current_visualization
