import os
import textwrap
import zipfile
import io
from flask import Flask, render_template, request
from tree_sitter import Language, Parser
import tree_sitter_javascript as ts_js

app = Flask(__name__)

# Initialize Tree-sitter
JS_LANGUAGE = Language(ts_js.language())
parser = Parser(JS_LANGUAGE)


class RepoAnalyzer:
    def __init__(self, source_code, file_path="Unknown"):
        self.source_bytes = source_code.encode('utf8') if isinstance(source_code, str) else source_code
        self.tree = parser.parse(self.source_bytes)
        self.file_path = file_path
        self.reports = []
        self.imports = []
        self.exports = []

    def scan_file(self, global_import_map=None):
        self.extract_imports()
        self.extract_exports()
        self._walk_node(self.tree.root_node)

        if global_import_map:
            self.check_for_unused_exports(global_import_map)

        return {
            "path": self.file_path,
            "reports": self.reports,
            "metadata": {"imports": self.imports, "exports": self.exports}
        }

    # --- ARCHITECTURAL METADATA ---
    def extract_imports(self):
        nodes = self.find_nodes_by_type(self.tree.root_node, 'import_statement')
        for node in nodes:
            source_node = node.child_by_field_name('source')
            if source_node:
                path = self.get_text(source_node).strip("'\"")
                symbols = []
                clause = node.child_by_field_name('clause')
                if clause: symbols.append(self.get_text(clause))
                self.imports.append({"path": path, "symbols": symbols})

    def extract_exports(self):
        nodes = self.find_nodes_by_type(self.tree.root_node, 'export_statement')
        for node in nodes:
            text = self.get_text(node)
            if any(k in text for k in ["const", "function", "class"]):
                parts = text.replace("export", "").strip().split(" ")
                for i, part in enumerate(parts):
                    if part in ["const", "function", "class", "default"] and i + 1 < len(parts):
                        name = parts[i + 1].split("(")[0].split("{")[0].strip()
                        if name: self.exports.append(name)

    # --- UPDATED MESS DETECTION LOGIC ---
    def _walk_node(self, node):
        top_types = ['class_declaration', 'function_declaration', 'variable_declarator', 'method_definition']
        if node.type in top_types:
            node_text = self.get_text(node)
            is_service = any(x in self.file_path.lower() for x in ['service', 'api', 'lib', 'util'])
            ui_markers = ['<', 'useState', 'useEffect', 'useReducer']

            if is_service or any(marker in node_text for marker in ui_markers):
                report = self.analyze_function_health(node)
                if report['issues']:
                    self.reports.append(report)
                    return

        for child in node.children:
            self._walk_node(child)

    def analyze_function_health(self, node):
        issues, candidates = [], []
        node_text = self.get_text(node)
        all_calls = self.find_nodes_by_type(node, 'call_expression')
        seen_ranges = []

        is_service_context = any(x in self.file_path.lower() for x in ['service', 'api', 'lib', 'util'])

        # Helper to generate candidate with line numbers
        def create_candidate(target_node, type_name, reason):
            return {
                "type": type_name,
                "reason": reason,
                "snippet": self.clean_snippet(self.get_text(target_node)),
                "start_line": target_node.start_point[0] + 1,
                "end_line": target_node.end_point[0] + 1
            }

        # === ROBUST UPGRADE 1 & 2: Identifier Guards & Magic Strings ===

        # Rule A: Magic Strings (Finds hardcoded URLs even in template literals)
        all_strings = self.find_nodes_by_type(node, 'string') + self.find_nodes_by_type(node, 'template_string')
        for str_node in all_strings:
            val = self.get_text(str_node).strip('"`\'')
            if any(url_type in val for url_type in ['http://', 'https://', 'ws://', 'wss://', 'localhost']):
                issues.append("Configuration Leak")
                candidates.append(create_candidate(str_node, "Magic String", "Hardcoded Network URL found. Move to environment variables (.env)."))

        # Rule B: Network Coupling (Uses AST Function Identification, ignores comments)
        if not is_service_context:
            for call in all_calls:
                func_name = self.get_call_name(call)
                if func_name in ['fetch'] or 'axios' in func_name.lower():
                    if not any(call.start_byte >= s and call.end_byte <= e for s, e in seen_ranges):
                        issues.append("Data Coupling")
                        candidates.append(create_candidate(call, "Network Island", f"Direct API logic in UI component ({self.file_path}). Decouple into a service."))
                        seen_ranges.append((call.start_byte, call.end_byte))

        # === ROBUST UPGRADE 3: State Signal Accuracy ===
        state_calls = [c for c in all_calls if self.get_call_name(c) in ['useState', 'useReducer']]
        if len(state_calls) > 5:
            issues.append("State Bloat")
            candidates.append({
                "type": "State Management",
                "reason": f"Managing {len(state_calls)} independent states. Consider consolidating into useReducer.",
                "snippet": f"Structural Issue: {len(state_calls)} state signals detected.",
                "start_line": node.start_point[0] + 1,
                "end_line": node.start_point[0] + 3 # Just highlighting the start of the block
            })

        # Logic Leak (Precise AST matching for array methods)
        math_logic = [c for c in all_calls if
                      any(op in self.get_call_name(c) for op in ['.filter', '.sort', '.reduce'])]
        if len(math_logic) >= 3:
            issues.append("Logic Leak")
            candidates.append(create_candidate(math_logic[0], "Data Transformation", "Heavy processing detected in render cycle."))

        # Sub-component Extraction (ONLY for UI files)
        if not is_service_context:
            for call in all_calls:
                if '.map' in self.get_call_name(call):
                    lines = call.end_point[0] - call.start_point[0]
                    if lines > 15:
                        issues.append("Sub-component Extraction")
                        candidates.append(create_candidate(call, "JSX Bloat", f"Large .map() block ({lines} lines)."))

        severity = "Critical" if len(set(issues)) >= 3 else "High" if len(set(issues)) >= 2 else "Medium"
        return {"name": self.get_node_name(node), "full_code": node_text, "issues": list(set(issues)),
                "severity": severity, "candidates": candidates}

    # --- CROSS-FILE LOGIC: UNUSED EXPORTS ---
    def check_for_unused_exports(self, global_map):
        for export_name in self.exports:
            is_used = False
            for path, imports in global_map.items():
                if path == self.file_path: continue
                if any(export_name in str(imp['symbols']) for imp in imports):
                    is_used = True
                    break

            if not is_used and export_name != "default":
                self.reports.append({
                    "name": export_name,
                    "issues": ["Dead Code"],
                    "severity": "Medium",
                    "candidates": [{
                        "type": "Unused Export",
                        "reason": f"'{export_name}' is exported but never imported by any other file.",
                        "snippet": f"export const {export_name} ...",
                        "start_line": None,
                        "end_line": None
                    }]
                })

    # --- HELPERS ---
    def find_nodes_by_type(self, node, node_type):
        results = []
        def traverse(n):
            if n.type == node_type: results.append(n)
            for child in n.children: traverse(child)
        traverse(node)
        return results

    def get_text(self, node):
        return self.source_bytes[node.start_byte:node.end_byte].decode('utf8') if node else ""

    def get_call_name(self, call_node):
        func_node = call_node.child_by_field_name('function')
        if not func_node: return ""
        return self.get_text(func_node)

    def get_node_name(self, node):
        text = self.get_text(node)
        try:
            if "const" in text: return text.split("const")[1].split("=")[0].strip()
            if "function" in text: return text.split("function")[1].split("(")[0].strip()
        except:
            pass
        return "Component"

    def clean_snippet(self, text):
        return textwrap.dedent(text).strip()


# --- FLASK SERVER ENGINE ---
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/analyze', methods=['POST'])
def analyze():
    if 'file' not in request.files: return "No file uploaded", 400
    uploaded_file = request.files['file']
    project_files = {}

    if uploaded_file.filename.endswith('.zip'):
        with zipfile.ZipFile(io.BytesIO(uploaded_file.read())) as z:
            for info in z.infolist():
                if info.filename.endswith(('.js', '.jsx', '.ts', '.tsx')) and 'node_modules' not in info.filename:
                    try:
                        project_files[info.filename] = z.read(info).decode('utf-8')
                    except:
                        continue
    else:
        project_files[uploaded_file.filename] = uploaded_file.read().decode('utf-8')

    global_import_map = {}
    temp_analyzers = []
    for path, content in project_files.items():
        ana = RepoAnalyzer(content, file_path=path)
        ana.extract_imports()
        global_import_map[path] = ana.imports
        temp_analyzers.append(ana)

    all_reports = []
    for ana in temp_analyzers:
        all_reports.append(ana.scan_file(global_import_map=global_import_map))

    return render_template('results.html', reports=all_reports, clean=(len(all_reports) == 0))


if __name__ == '__main__':
    app.run(debug=True, port=5000)