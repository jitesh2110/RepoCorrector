from tree_sitter import Parser, Language
import tree_sitter_javascript as tsjs

# Convert capsule → Language object
JS_LANGUAGE = Language(tsjs.language())

parser = Parser()
parser.language = JS_LANGUAGE


def analyze_code_ast(code):

    tree = parser.parse(bytes(code, "utf8"))
    root = tree.root_node

    result = {
        "hooks": [],
        "api_calls": [],
        "jsx_elements": 0
    }

    def traverse(node):

        # Detect function calls
        if node.type == "call_expression":

            func_node = node.child_by_field_name("function")

            if func_node:
                name = code[func_node.start_byte:func_node.end_byte]

                if name in ["useState", "useEffect", "useReducer"]:
                    result["hooks"].append(name)

                if name in ["fetch", "axios"]:
                    result["api_calls"].append(name)

        # Detect JSX
        if node.type == "jsx_element":
            result["jsx_elements"] += 1

        for child in node.children:
            traverse(child)

    traverse(root)

    return result