import os

OUTPUT = "output"

def generate_project(refactored):

    components_dir = os.path.join(OUTPUT, "components")
    hooks_dir = os.path.join(OUTPUT, "hooks")
    services_dir = os.path.join(OUTPUT, "services")

    os.makedirs(components_dir, exist_ok=True)
    os.makedirs(hooks_dir, exist_ok=True)
    os.makedirs(services_dir, exist_ok=True)

    with open(os.path.join(components_dir, "Component.jsx"), "w", encoding="utf-8") as f:
        f.write(refactored["components"])

    with open(os.path.join(hooks_dir, "useCustom.js"), "w", encoding="utf-8") as f:
        f.write(refactored["hooks"])

    with open(os.path.join(services_dir, "apiService.js"), "w", encoding="utf-8") as f:
        f.write(refactored["services"])