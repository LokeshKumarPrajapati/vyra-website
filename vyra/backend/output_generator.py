"""
Output Generator Module
Generates various types of visualizations including charts, diagrams, and terminal outputs.
"""

import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
import os
from datetime import datetime
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend

# Set style
sns.set_style("whitegrid")
plt.rcParams['figure.facecolor'] = 'white'
plt.rcParams['axes.facecolor'] = '#f8f9fa'
plt.rcParams['font.size'] = 10
plt.rcParams['axes.labelsize'] = 11
plt.rcParams['axes.titlesize'] = 13
plt.rcParams['xtick.labelsize'] = 9
plt.rcParams['ytick.labelsize'] = 9


class OutputGenerator:
    def __init__(self, output_dir="projects/outputs"):
        """Initialize the output generator with output directory."""
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def _generate_filename(self, prefix):
        """Generate a unique filename with timestamp."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{prefix}_{timestamp}.png"

    def generate_bar_chart(self, data, title="Bar Chart", x_label="X", y_label="Y"):
        """
        Generate a bar chart.

        Args:
            data: dict with 'labels' and 'values' keys
                  e.g., {'labels': ['A', 'B', 'C'], 'values': [10, 20, 15]}
            title: Chart title
            x_label: X-axis label
            y_label: Y-axis label

        Returns:
            dict with path, type, timestamp, title
        """
        try:
            labels = data.get('labels', [])
            values = data.get('values', [])

            if not labels or not values:
                raise ValueError("Data must contain 'labels' and 'values'")

            fig, ax = plt.subplots(figsize=(10, 6))
            colors = sns.color_palette("husl", len(labels))

            bars = ax.bar(labels, values, color=colors, alpha=0.8,
                          edgecolor='black', linewidth=1.2)

            # Add value labels on bars
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height,
                        f'{height:.1f}',
                        ha='center', va='bottom', fontweight='bold')

            ax.set_xlabel(x_label, fontweight='bold')
            ax.set_ylabel(y_label, fontweight='bold')
            ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
            ax.grid(axis='y', alpha=0.3)

            plt.tight_layout()

            filename = self._generate_filename("bar_chart")
            filepath = os.path.join(self.output_dir, filename)
            plt.savefig(filepath, dpi=150, bbox_inches='tight')
            plt.close()

            return {
                'path': filepath,
                'type': 'bar_chart',
                'timestamp': datetime.now().isoformat(),
                'title': title,
                'format': 'image'
            }
        except Exception as e:
            print(f"[OutputGen] Error generating bar chart: {e}")
            return {'error': str(e)}

    def generate_line_chart(self, data, title="Line Chart", x_label="X", y_label="Y"):
        """
        Generate a line chart.

        Args:
            data: dict with 'x' and 'y' keys (and optional 'series' for multiple lines)
                  e.g., {'x': [1,2,3,4], 'y': [2,4,6,8]}
                  or {'x': [1,2,3], 'series': {'A': [1,2,3], 'B': [3,2,1]}}
            title: Chart title
            x_label: X-axis label
            y_label: Y-axis label

        Returns:
            dict with path, type, timestamp, title
        """
        try:
            fig, ax = plt.subplots(figsize=(10, 6))

            if 'series' in data:
                # Multiple lines
                x = data.get('x', [])
                series = data.get('series', {})

                for i, (name, y_values) in enumerate(series.items()):
                    ax.plot(x, y_values, marker='o', linewidth=2.5,
                            label=name, markersize=8, alpha=0.9)

                ax.legend(loc='best', frameon=True, fancybox=True, shadow=True)
            else:
                # Single line
                x = data.get('x', [])
                y = data.get('y', [])

                if not x or not y:
                    raise ValueError("Data must contain 'x' and 'y'")

                ax.plot(x, y, marker='o', linewidth=2.5, markersize=8,
                        color='#2E86AB', alpha=0.9)

            ax.set_xlabel(x_label, fontweight='bold')
            ax.set_ylabel(y_label, fontweight='bold')
            ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
            ax.grid(True, alpha=0.3)

            plt.tight_layout()

            filename = self._generate_filename("line_chart")
            filepath = os.path.join(self.output_dir, filename)
            plt.savefig(filepath, dpi=150, bbox_inches='tight')
            plt.close()

            return {
                'path': filepath,
                'type': 'line_chart',
                'timestamp': datetime.now().isoformat(),
                'title': title,
                'format': 'image'
            }
        except Exception as e:
            print(f"[OutputGen] Error generating line chart: {e}")
            return {'error': str(e)}

    def generate_pie_chart(self, data, title="Pie Chart"):
        """
        Generate a pie chart.

        Args:
            data: dict with 'labels' and 'values' keys
                  e.g., {'labels': ['A', 'B', 'C'], 'values': [30, 50, 20]}
            title: Chart title

        Returns:
            dict with path, type, timestamp, title
        """
        try:
            labels = data.get('labels', [])
            values = data.get('values', [])

            if not labels or not values:
                raise ValueError("Data must contain 'labels' and 'values'")

            fig, ax = plt.subplots(figsize=(10, 8))
            colors = sns.color_palette("pastel", len(labels))

            wedges, texts, autotexts = ax.pie(values, labels=labels, autopct='%1.1f%%',
                                              colors=colors, startangle=90,
                                              textprops={
                                                  'fontsize': 11, 'weight': 'bold'},
                                              explode=[0.05] * len(labels))

            # Make percentage text more visible
            for autotext in autotexts:
                autotext.set_color('black')
                autotext.set_fontsize(11)
                autotext.set_weight('bold')

            ax.set_title(title, fontsize=14, fontweight='bold', pad=20)

            plt.tight_layout()

            filename = self._generate_filename("pie_chart")
            filepath = os.path.join(self.output_dir, filename)
            plt.savefig(filepath, dpi=150, bbox_inches='tight')
            plt.close()

            return {
                'path': filepath,
                'type': 'pie_chart',
                'timestamp': datetime.now().isoformat(),
                'title': title,
                'format': 'image'
            }
        except Exception as e:
            print(f"[OutputGen] Error generating pie chart: {e}")
            return {'error': str(e)}

    def generate_heatmap(self, data, title="Heatmap"):
        """
        Generate a heatmap.

        Args:
            data: dict with 'matrix' (2D array) and optional 'x_labels', 'y_labels'
                  e.g., {'matrix': [[1,2,3],[4,5,6],[7,8,9]], 
                         'x_labels': ['A','B','C'], 'y_labels': ['X','Y','Z']}
            title: Chart title

        Returns:
            dict with path, type, timestamp, title
        """
        try:
            matrix = data.get('matrix', [])
            x_labels = data.get('x_labels', None)
            y_labels = data.get('y_labels', None)

            if not matrix:
                raise ValueError("Data must contain 'matrix'")

            fig, ax = plt.subplots(figsize=(10, 8))

            sns.heatmap(matrix, annot=True, fmt='.1f', cmap='YlOrRd',
                        cbar_kws={'label': 'Value'}, linewidths=0.5,
                        xticklabels=x_labels, yticklabels=y_labels, ax=ax)

            ax.set_title(title, fontsize=14, fontweight='bold', pad=20)

            plt.tight_layout()

            filename = self._generate_filename("heatmap")
            filepath = os.path.join(self.output_dir, filename)
            plt.savefig(filepath, dpi=150, bbox_inches='tight')
            plt.close()

            return {
                'path': filepath,
                'type': 'heatmap',
                'timestamp': datetime.now().isoformat(),
                'title': title,
                'format': 'image'
            }
        except Exception as e:
            print(f"[OutputGen] Error generating heatmap: {e}")
            return {'error': str(e)}

    def generate_flowchart(self, data, title="Flowchart"):
        """
        Generate a simple flowchart diagram using matplotlib.

        Args:
            data: dict with 'nodes' and 'edges'
                  e.g., {'nodes': ['Start', 'Process', 'End'],
                         'edges': [['Start', 'Process'], ['Process', 'End']]}
            title: Chart title

        Returns:
            dict with path, type, timestamp, title
        """
        try:
            nodes = data.get('nodes', [])
            edges = data.get('edges', [])

            if not nodes:
                raise ValueError("Data must contain 'nodes'")

            fig, ax = plt.subplots(figsize=(12, 8))

            # Simple vertical layout
            num_nodes = len(nodes)
            y_positions = np.linspace(0.9, 0.1, num_nodes)

            # Draw nodes
            for i, node in enumerate(nodes):
                # Determine node shape based on type hints
                if 'start' in node.lower() or 'end' in node.lower():
                    bbox = dict(boxstyle='round,pad=0.5', facecolor='#A8DADC',
                                edgecolor='black', linewidth=2)
                elif 'decision' in node.lower() or '?' in node:
                    bbox = dict(boxstyle='round,pad=0.5', facecolor='#F1FAEE',
                                edgecolor='black', linewidth=2)
                else:
                    bbox = dict(boxstyle='square,pad=0.5', facecolor='#E63946',
                                edgecolor='black', linewidth=2, alpha=0.7)

                ax.text(0.5, y_positions[i], node, ha='center', va='center',
                        fontsize=12, fontweight='bold', bbox=bbox, color='black')

            # Draw edges (simple arrows)
            for edge in edges:
                if len(edge) >= 2:
                    from_node = edge[0]
                    to_node = edge[1]

                    if from_node in nodes and to_node in nodes:
                        from_idx = nodes.index(from_node)
                        to_idx = nodes.index(to_node)

                        ax.annotate('', xy=(0.5, y_positions[to_idx] + 0.05),
                                    xytext=(0.5, y_positions[from_idx] - 0.05),
                                    arrowprops=dict(arrowstyle='->', lw=2, color='black'))

            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis('off')
            ax.set_title(title, fontsize=14, fontweight='bold', pad=20)

            plt.tight_layout()

            filename = self._generate_filename("flowchart")
            filepath = os.path.join(self.output_dir, filename)
            plt.savefig(filepath, dpi=150, bbox_inches='tight')
            plt.close()

            return {
                'path': filepath,
                'type': 'flowchart',
                'timestamp': datetime.now().isoformat(),
                'title': title,
                'format': 'image'
            }
        except Exception as e:
            print(f"[OutputGen] Error generating flowchart: {e}")
            return {'error': str(e)}

    def format_terminal_output(self, data, title="Terminal Output"):
        """
        Format text as terminal output.

        Args:
            data: dict with 'lines' (list of strings) or 'text' (single string)
                  e.g., {'lines': ['$ ls', 'file1.txt', 'file2.txt']}
            title: Output title

        Returns:
            dict with text, type, timestamp, title
        """
        try:
            if 'lines' in data:
                text = '\n'.join(data['lines'])
            elif 'text' in data:
                text = data['text']
            else:
                raise ValueError("Data must contain 'lines' or 'text'")

            # Save to text file
            filename = self._generate_filename(
                "terminal_output").replace('.png', '.txt')
            filepath = os.path.join(self.output_dir, filename)

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(text)

            return {
                'path': filepath,
                'text': text,
                'type': 'terminal',
                'timestamp': datetime.now().isoformat(),
                'title': title,
                'format': 'text'
            }
        except Exception as e:
            print(f"[OutputGen] Error formatting terminal output: {e}")
            return {'error': str(e)}


# Singleton instance
_generator = None


def get_generator():
    """Get or create the singleton OutputGenerator instance."""
    global _generator
    if _generator is None:
        _generator = OutputGenerator()
    return _generator


# Convenience functions
def generate_bar_chart(data, title="Bar Chart", x_label="X", y_label="Y"):
    return get_generator().generate_bar_chart(data, title, x_label, y_label)


def generate_line_chart(data, title="Line Chart", x_label="X", y_label="Y"):
    return get_generator().generate_line_chart(data, title, x_label, y_label)


def generate_pie_chart(data, title="Pie Chart"):
    return get_generator().generate_pie_chart(data, title)


def generate_heatmap(data, title="Heatmap"):
    return get_generator().generate_heatmap(data, title)


def generate_flowchart(data, title="Flowchart"):
    return get_generator().generate_flowchart(data, title)


def format_terminal_output(data, title="Terminal Output"):
    return get_generator().format_terminal_output(data, title)
