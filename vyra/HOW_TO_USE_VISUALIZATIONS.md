# How to Use Visualization Feature

## ✅ The Feature is Working!

Backend tests passed: All 6 visualization types generate correctly.

## The Issue

The AI is calling the wrong tool - it's using `write_file` to generate code instead of `generate_visualization` to create charts.

## How to Request Visualizations

### ✅ GOOD Requests (Clear visualization keywords)

**For Charts:**
- "Show me a bar chart of sales: 100, 200, 150"
- "Create a line graph comparing revenue and expenses over 6 months"
- "Generate a pie chart of my daily activities"
- "Display a heatmap of temperature data"

**For Flowcharts:**
- "Draw a flowchart of the login process"
- "Visualize the workflow as a flowchart"

**For Terminal Output:**
- "Show this as terminal output: [your text]"
- "Display these commands in a terminal window"

### ❌ BAD Requests (Too vague)

- "Generate code for a chart" → Will write code
- "Create visualization code" → Will write code
- "Make a program that shows data" → Will write code

## Test Commands

Try these exact phrases:

1. **"Show me a bar chart with values 10, 20, 15, 25 and labels A, B, C, D"**
2. **"Create a pie chart showing: Sleep 8 hours, Work 8 hours, Free time 8 hours"**
3. **"Display a line chart of temperatures: Monday 20, Tuesday 22, Wednesday 19"**

## Expected Behavior

When you give a visualization request:
1. AI says "I'll generate that visualization for you"
2. You see `[TOOL] generate_visualization` in the backend logs
3. A modal window opens showing your chart
4. You can download, navigate history, etc.

## Debugging

If still writing files instead of visualizations:
- Restart the app (the tool might need a fresh session)
- Use very explicit keywords: "visualize", "chart", "graph", "diagram"
- Avoid words like "code", "program", "script"

## Files Generated

Check `projects/outputs/` folder - test files were created:
- bar_chart_20260208_172935.png
- line_chart_20260208_172935.png
- pie_chart_20260208_172936.png
- heatmap_20260208_172936.png
- flowchart_20260208_172936.png
- terminal_output_20260208_172936.txt

These prove the backend works!
