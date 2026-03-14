def refactor_code(code, analysis):

    components = ""
    hooks = ""
    services = ""

    lines = code.split("\n")

    for line in lines:

        if "fetch(" in line or "axios" in line:
            services += line + "\n"

        elif "useState" in line or "useEffect" in line:
            hooks += line + "\n"

        else:
            components += line + "\n"

    return {
        "components": components,
        "hooks": hooks,
        "services": services
    }
