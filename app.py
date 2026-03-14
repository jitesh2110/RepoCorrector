import os
from flask import Flask, render_template, request
from tree_sitter import Language, Parser
import tree_sitter_javascript as ts_js

app = Flask(__name__)

# Initialize Tree-sitter for JavaScript/JSX
JS_LANGUAGE = Language(ts_js.language())
parser = Parser(JS_LANGUAGE)


class RepoAnalyzer:
    def __init__(self, source_code):
        self.source_bytes = source_code.encode('utf8')
        self.tree = parser.parse(self.source_bytes)
        self.reports = []

    def scan_file(self):
        """Initial entry point to walk the tree."""
        self._walk_node(self.tree.root_node)
        return self.reports

    def _walk_node(self, node):
        """Recursively search for function/component containers."""
        # Focus on top-level structures that hold logic
        function_types = [
            'function_declaration',
            'arrow_function',
            'variable_declarator',
            'method_definition'
        ]

        if node.type in function_types:
            report = self.analyze_function_health(node)
            # Only report if at least one "messy" issue is found
            if report['issues']:
                self.reports.append(report)
                # After flagging a container, don't look inside it for more
                # This prevents duplicate sub-function reporting
                return

        for child in node.children:
            self._walk_node(child)

    def analyze_function_health(self, node):
        """The core engine that checks for 4 types of messy code."""
        issues = []

        # 1. CATEGORY: Data Coupling (API calls)
        api_count = self.count_identifiers(node, ['fetch', 'axios'])
        if api_count > 0:
            issues.append("Data Coupling")

        # 2. CATEGORY: State Bloat (Too many useStates)
        state_count = self.count_identifiers(node, ['useState'])
        if state_count > 4:
            issues.append("State Bloat")

        # 3. CATEGORY: Effect Tangle (Too many useEffects)
        effect_count = self.count_identifiers(node, ['useEffect'])
        if effect_count > 2:
            issues.append("Effect Tangle")

        # 4. CATEGORY: Deep Nesting (JSX Depth)
        max_nesting = self.get_max_jsx_depth(node, 0)
        if max_nesting >= 5:
            issues.append("Deep Nesting")

        # Determine Severity based on issue count
        severity = "Low"
        if len(issues) >= 3:
            severity = "Critical"
        elif len(issues) >= 2:
            severity = "High"
        elif len(issues) == 1:
            severity = "Medium"

        return {
            "code": self.source_bytes[node.start_byte:node.end_byte].decode('utf8'),
            "issues": issues,
            "severity": severity,
            "metrics": {
                "api_calls": api_count,
                "state_hooks": state_count,
                "effects": effect_count,
                "nesting_depth": max_nesting
            }
        }

    def count_identifiers(self, node, targets):
        """Helper to count occurrences of specific hooks/libraries."""
        count = 0
        if node.type == 'identifier':
            name = self.source_bytes[node.start_byte:node.end_byte].decode('utf8')
            if name in targets:
                return 1
        for child in node.children:
            count += self.count_identifiers(child, targets)
        return count

    def get_max_jsx_depth(self, node, current_depth):
        """Calculates the deepest level of JSX nesting."""
        if node.type in ['jsx_element', 'jsx_self_closing_element']:
            current_depth += 1

        max_d = current_depth
        for child in node.children:
            max_d = max(max_d, self.get_max_jsx_depth(child, current_depth))
        return max_d


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/analyze', methods=['POST'])
def analyze():
    if 'file' not in request.files:
        return "No file uploaded", 400

    file = request.files['file']
    source_code = file.read().decode('utf-8')

    # Execute Modern Analysis
    analyzer = RepoAnalyzer(source_code)
    reports = analyzer.scan_file()

    # We send 'reports' to the template instead of just 'blocks'
    return render_template('results.html', reports=reports)


if __name__ == '__main__':
    if not os.path.exists('templates'):
        os.makedirs('templates')
    app.run(debug=True)