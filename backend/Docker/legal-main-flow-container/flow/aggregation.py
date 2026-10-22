from promptflow.core import tool


@tool
def my_python_tool(
    query_type: int,
    input1: object = None,
    input2: object = None,
    input3: object = None,
    input4: object = None,
    input5: object = None,
    input6: object = None,
) -> object:
    """Return only the branch requested by the caller, never another result."""
    outputs = {
        0: input2,  # Legacy document summary.
        1: input3,  # Full-document Summary with selected Policy Sets.
        2: input1,  # Review and mark-up.
        3: input4,  # Ask.
        98: input6,  # Local contract indexing.
        99: input5,  # Index status.
    }

    if query_type not in outputs:
        return {"error": f"Unsupported query_type: {query_type}"}

    result = outputs[query_type]
    if query_type == 99 and isinstance(result, bool):
        return {"Found": result}

    if result is not None:
        return result

    error: dict[str, object] = {"error": f"Workflow branch {query_type} returned no output."}
    if query_type == 1:
        error.update(Summary="", KeyPoints=[], Items=[])
    return error
