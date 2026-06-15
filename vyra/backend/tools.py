generate_cad_prototype_tool = {
    "name": "generate_cad_prototype",
    "description": "Generates a 3D wireframe prototype based on a user's description. Use this when the user asks to 'visualize', 'prototype', 'create a wireframe', or 'design' something in 3D.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "prompt": {
                "type": "STRING",
                "description": "The user's description of the object to prototype."
            }
        },
        "required": ["prompt"]
    }
}


write_file_tool = {
    "name": "write_file",
    "description": "Writes content to a file at the specified path. Overwrites if exists.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "path": {
                "type": "STRING",
                "description": "The path of the file to write to."
            },
            "content": {
                "type": "STRING",
                "description": "The content to write to the file."
            }
        },
        "required": ["path", "content"]
    }
}

read_directory_tool = {
    "name": "read_directory",
    "description": "Lists the contents of a directory.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "path": {
                "type": "STRING",
                "description": "The path of the directory to list."
            }
        },
        "required": ["path"]
    }
}

read_file_tool = {
    "name": "read_file",
    "description": "Reads the content of a file.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "path": {
                "type": "STRING",
                "description": "The path of the file to read."
            }
        },
        "required": ["path"]
    }
}

generate_visualization_tool = {
    "name": "generate_visualization",
    "description": "IMPORTANT: Use this tool WHENEVER the user asks to see, show, display, create, or generate ANY chart, graph, diagram, or visualization. This tool creates visual output that appears in the UI. Examples: 'show me a bar chart', 'create a pie chart', 'visualize this data', 'display a line graph'. DO NOT write code or respond conversationally - USE THIS TOOL to actually create and display the visualization.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "visualization_type": {
                "type": "STRING",
                "description": "Type of visualization: 'bar_chart' (for comparing values), 'line_chart' (for trends over time), 'pie_chart' (for proportions/percentages), 'heatmap' (for matrix data), 'flowchart' (for process flows), or 'terminal' (for code/terminal output)",
                "enum": ["bar_chart", "line_chart", "pie_chart", "heatmap", "flowchart", "terminal"]
            },
            "data": {
                "type": "OBJECT",
                "description": "Data for visualization. Format depends on type: bar_chart/pie_chart needs {labels:[], values:[]}, line_chart needs {x:[], y:[]} or {x:[], series:{}}, heatmap needs {matrix:[[]]}, flowchart needs {nodes:[], edges:[]}, terminal needs {lines:[]} or {text:''}"
            },
            "title": {
                "type": "STRING",
                "description": "Title for the visualization"
            },
            "x_label": {
                "type": "STRING",
                "description": "X-axis label (for bar/line charts only)"
            },
            "y_label": {
                "type": "STRING",
                "description": "Y-axis label (for bar/line charts only)"
            }
        },
        "required": ["visualization_type", "data", "title"]
    }
}

spotify_get_playlists_tool = {
    "name": "spotify_get_playlists",
    "description": "Gets the list of Spotify playlists for the connected user. Useful for answering 'how many playlists do I have?' or 'what playlists do I have?'. Returns an array of playlist names and their total track counts.",
    "parameters": {"type": "OBJECT", "properties": {}},
    "behavior": "NON_BLOCKING"
}

spotify_play_tool = {
    "name": "spotify_play",
    "description": "Starts or resumes Spotify playback.",
    "parameters": {"type": "OBJECT", "properties": {}},
    "behavior": "NON_BLOCKING"
}

analyze_current_view_tool = {
    "name": "analyze_current_view",
    "description": "Uses the Vision-Language Model to closely examine the current webcam frame. Use this when the user asks 'what is this', 'what am I holding', 'what is in front of the camera', or 'can you see this'. The tool returns a detailed description of the current view.",
    "parameters": {"type": "OBJECT", "properties": {}}
}

spotify_pause_tool = {
    "name": "spotify_pause",
    "description": "Pauses Spotify playback.",
    "parameters": {"type": "OBJECT", "properties": {}},
    "behavior": "NON_BLOCKING"
}

tools_list = [{"function_declarations": [
    generate_cad_prototype_tool,
    write_file_tool,
    read_directory_tool,
    read_file_tool,
    generate_visualization_tool,
    spotify_get_playlists_tool,
    spotify_play_tool,
    spotify_pause_tool,
    analyze_current_view_tool
]}]
