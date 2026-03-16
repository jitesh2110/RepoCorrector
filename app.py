import os
import textwrap
from flask import Flask, render_template, request
from tree_sitter import Language, Parser
import tree_sitter_javascript as ts_js

app = Flask(__name__)

# Initialize Tree-sitter
JS_LANGUAGE = Language(ts_js.language())
parser = Parser(JS_LANGUAGE)


class RepoAnalyzer:
    def __init__(self, source_code):
        self.source_bytes = source_code.encode('utf8')
        self.tree = parser.parse(self.source_bytes)
        self.reports = []

    def scan_file(self):
        self._walk_node(self.tree.root_node)
        return self.reports

    def _walk_node(self, node):
        # Anchor point: We search for component-like structures
        top_level_types = ['class_declaration', 'function_declaration', 'variable_declarator', 'method_definition']

        if node.type in top_level_types:
            node_text = self.get_text(node)
            # Heuristic to identify a React Component
            if any(marker in node_text for marker in ['<', 'useState', 'useEffect', 'useReducer', 'return']):
                report = self.analyze_function_health(node)
                if report['issues']:
                    self.reports.append(report)
                    # Once a component is analyzed, we don't need to scan its children for more components
                    return

        for child in node.children:
            self._walk_node(child)

    def analyze_function_health(self, node):
        issues = []
        candidates = []
        node_text = self.get_text(node)
        seen_ranges = []

        # PRE-FETCH ALL CALLS (Used for multiple checks)
        all_calls = self.find_nodes_by_type(node, 'call_expression')

        # --- SECTOR 1: NETWORK COUPLING (Surgical) ---
        network_keywords = ['Axios.', 'axios.', 'fetch(', 'http', 'api/']
        for call in all_calls:
            call_text = self.get_text(call)
            if any(k in call_text for k in network_keywords):
                if not any(call.start_byte >= s and call.end_byte <= e for s, e in seen_ranges):
                    issues.append("Data Coupling")
                    candidates.append({
                        "type": "Network Island (Surgical)",
                        "reason": "Direct API logic found in UI. Decouple into a service or custom hook.",
                        "snippet": self.clean_snippet(call_text)
                    })
                    seen_ranges.append((call.start_byte, call.end_byte))

        # --- SECTOR 2: STATE BLOAT (AST Counting) ---
        # We count actual Hook calls, not just strings in comments
        hook_count = sum(1 for c in all_calls if 'useState' in self.get_text(c))
        reducer_count = sum(1 for c in all_calls if 'useReducer' in self.get_text(c))
        legacy_count = node_text.count('this.setState')

        total_state_signals = hook_count + reducer_count + legacy_count
        if total_state_signals > 5:
            issues.append("State Bloat")
            candidates.append({
                "type": "State Management",
                "reason": f"Managing {total_state_signals} state signals. This exceeds the recommended complexity for a single component.",
                "snippet": f"Structural Issue: {total_state_signals} state signals detected."
            })

        # --- SECTOR 3: LOGIC LEAK (Data Transformation) ---
        # Detect if the component is doing heavy data processing (filter/sort/reduce) inside the body
        transform_logic = [c for c in all_calls if any(x in self.get_text(c) for x in ['.filter', '.sort', '.reduce'])]
        if len(transform_logic) >= 2:  # Multiple transformations usually mean a leak
            issues.append("Logic Leak")
            leak_sample = self.get_text(transform_logic[0])
            candidates.append({
                "type": "Data Transformation",
                "reason": "Complex data processing found in render path. Move this logic to a Selector or Memoized Utility.",
                "snippet": self.clean_snippet(leak_sample)
            })

        # --- SECTOR 4: SUB-COMPONENT CANDIDATES (JSX Bloat) ---
        # Check for large .map() blocks that render complex UI
        for call in all_calls:
            call_text = self.get_text(call)
            if '.map' in call_text:
                line_count = call.end_point[0] - call.start_point[0]
                if line_count > 15:  # An iteration block longer than 15 lines is a component
                    issues.append("Sub-component Extraction")
                    candidates.append({
                        "type": "Sub-component Extraction",
                        "reason": f"Large mapping block ({line_count} lines). Extract the item renderer into its own component.",
                        "snippet": self.clean_snippet(call_text[:200] + "...")  # Snippet shortened for UI
                    })

        # Final Severity Score
        unique_issues = list(set(issues))
        severity = "Critical" if len(unique_issues) >= 3 else "High" if len(unique_issues) >= 2 else "Medium"

        return {
            "name": self.get_node_name(node),
            "full_code": node_text,
            "issues": unique_issues,
            "severity": severity,
            "candidates": candidates
        }

    # --- HELPERS ---
    def clean_snippet(self, text):
        """Fixes indentation for display in the results UI."""
        return textwrap.dedent(text).strip()

    def get_node_name(self, node):
        text = self.get_text(node)
        try:
            if "const" in text: return text.split("const")[1].split("=")[0].strip()
            if "class" in text: return text.split("class")[1].split("{")[0].strip()
            if "function" in text: return text.split("function")[1].split("(")[0].strip()
        except:
            pass
        return "React Component"

    def find_nodes_by_type(self, node, node_type):
        results = []

        def traverse(n):
            if n.type == node_type: results.append(n)
            for child in n.children: traverse(child)

        traverse(node)
        return results

    def find_complex_deep_jsx(self, node, threshold, current_depth=0):
        # Recursive depth check for JSX elements
        results = []
        if node.type in ['jsx_element', 'jsx_expression_container']:
            current_depth += 1
            if current_depth >= threshold:
                if any(x in self.get_text(node) for x in ['.map', 'onClick', '<button']):
                    return [node]
        for child in node.children:
            results.extend(self.find_complex_deep_jsx(child, threshold, current_depth))
        return results

    def get_text(self, node):
        return self.source_bytes[node.start_byte:node.end_byte].decode('utf8')


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/analyze', methods=['POST'])
def analyze():
    if 'file' not in request.files:
        return "No file uploaded", 400
    file = request.files['file']
    source_code = file.read().decode('utf-8')
    reports = RepoAnalyzer(source_code).scan_file()
    return render_template('results.html', reports=reports, clean=(len(reports) == 0))


if __name__ == '__main__':
    app.run(debug=True, port=5000)