import json
from typing import Any


def clean_explain_output(text: str) -> list[str]:
    cleaned = []
    for line in text.split("\n"):
        for ch in ["┌", "┐", "└", "┘", "│", "─", "┬", "┴"]:
            line = line.replace(ch, "")
        line = line.strip()
        if line:
            cleaned.append(line)
    return cleaned


def _make_node(op_type: str) -> dict[str, Any]:
    return {
        "type": op_type,
        "columns": [],
        "aggregates": [],
        "rows": None,
        "children": [],
    }


def _assemble_tree(nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    root = None
    last_projection = None
    for node in nodes:
        if node["type"] == "UNGROUPED_AGGREGATE":
            root = node
        elif node["type"] == "PROJECTION":
            if root:
                root["children"].append(node)
            last_projection = node
        elif node["type"] in ("SEQ_SCAN", "READ_CSV_AUTO"):
            if last_projection:
                last_projection["children"].append(node)
    return root


def _build_operator_tree(lines: list[str]) -> dict[str, Any] | None:
    ops = []
    current = None

    for line in lines:
        if "UNGROUPED_AGGREGATE" in line:
            current = _make_node("UNGROUPED_AGGREGATE")
            ops.append(current)
        elif "PROJECTION" in line:
            current = _make_node("PROJECTION")
            ops.append(current)
        elif "SEQ_SCAN" in line:
            current = _make_node("SEQ_SCAN")
            ops.append(current)
        elif "READ_CSV_AUTO" in line:
            current = _make_node("READ_CSV_AUTO")
            ops.append(current)

        if current is None:
            continue

        if "Aggregates:" in line:
            current["aggregates"] = [line.replace("Aggregates:", "").strip()]

        if "rows" in line and "~" in line:
            try:
                num = line.split("~")[1].split("rows")[0].strip()
                current["rows"] = int(num)
            except Exception:
                pass

    return _assemble_tree(ops)


def explain_tree(node: dict[str, Any] | None) -> str:
    if not node:
        return "Could not parse query plan."

    t = node["type"]
    if t == "UNGROUPED_AGGREGATE":
        return f"Computes aggregate: {', '.join(node['aggregates'])}."
    if t == "PROJECTION":
        return f"Selects columns: {', '.join(node['columns'])}."
    if t == "SEQ_SCAN":
        return f"Sequential scan over table (~{node['rows']} rows)."
    return f"Executes operator: {t}."


def _from_postgres_node(node: dict[str, Any]) -> dict[str, Any]:
    node_type = str(node.get("Node Type", "UNKNOWN")).upper().replace(" ", "_")
    children = [_from_postgres_node(child) for child in node.get("Plans", [])]

    columns: list[str] = []
    output = node.get("Output")
    if isinstance(output, list):
        columns = [str(v) for v in output]

    aggregates: list[str] = []
    if "Group Key" in node and isinstance(node["Group Key"], list):
        aggregates = ["GROUP BY " + ", ".join(str(v) for v in node["Group Key"])]

    rows = node.get("Actual Rows", node.get("Plan Rows"))
    try:
        rows = int(rows) if rows is not None else None
    except Exception:
        rows = None

    return {
        "type": node_type,
        "columns": columns,
        "aggregates": aggregates,
        "rows": rows,
        "children": children,
    }


def parse_plan(raw_plan: Any) -> dict[str, Any]:
    if isinstance(raw_plan, list):
        if raw_plan and isinstance(raw_plan[0], tuple) and len(raw_plan[0]) > 1:
            lines = [str(r[1]) for r in raw_plan]
            cleaned = clean_explain_output("\n".join(lines))
            tree = _build_operator_tree(cleaned)
            return {"format": "duckdb_text", "plan_tree": tree, "explanation": explain_tree(tree)}

        if raw_plan and isinstance(raw_plan[0], dict):
            pg_root = raw_plan[0].get("Plan", raw_plan[0])
            tree = _from_postgres_node(pg_root)
            return {"format": "json", "plan": raw_plan, "plan_tree": tree, "explanation": explain_tree(tree)}

        return {"format": "json", "plan": raw_plan}

    if isinstance(raw_plan, dict):
        pg_root = raw_plan.get("Plan", raw_plan)
        if isinstance(pg_root, dict):
            tree = _from_postgres_node(pg_root)
            return {"format": "json", "plan": raw_plan, "plan_tree": tree, "explanation": explain_tree(tree)}
        return {"format": "json", "plan": raw_plan}

    if isinstance(raw_plan, str):
        text = raw_plan.strip()
        if text.startswith("{") or text.startswith("["):
            try:
                return {"format": "json", "plan": json.loads(text)}
            except json.JSONDecodeError:
                pass
        cleaned = clean_explain_output(text)
        tree = _build_operator_tree(cleaned)
        return {"format": "text", "plan_tree": tree, "explanation": explain_tree(tree)}

    return {"format": "unknown", "plan": raw_plan}
