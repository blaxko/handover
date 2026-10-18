"""Turn a tool result into {nodes, edges} for the graph view.

build() is pure: no database calls. name_ids maps names that the result carries
(persons, services, tickets) to their graph ids. A name with no id gets a
placeholder id, so the node still shows. neighbourhood() is the one function that reads the graph.
"""
from app import queries


def _node(node_id: str, label: str, name: str) -> dict:
    return {"id": node_id, "label": label, "name": name}


def _edge(src: str, dst: str, kind: str, closed: bool = False) -> dict:
    return {"from": src, "to": dst, "type": kind, "closed": closed}


def neighbourhood(graph, focus: str, depth: int) -> dict | None:
    """Graph view around one node, both directions. Closed edges come back with closed: true.
    Returns None when the focus node does not exist."""
    found = queries.focus_node(graph, focus)
    if not found:
        return None
    nodes = {focus: _node(focus, found[0]["label"], found[0]["name"])}
    edges = []
    for r in queries.neighbourhood(graph, focus, depth):
        for node_id, label, name in ((r["src"], r["src_label"], r["src_name"]),
                                     (r["dst"], r["dst_label"], r["dst_name"])):
            nodes.setdefault(node_id, _node(node_id, label, name))
        edges.append({"from": r["src"], "to": r["dst"], "type": r["type"],
                      "closed": r["valid_to"] is not None,
                      "valid_from": r["valid_from"], "valid_to": r["valid_to"], "source": r.get("source")})
    return {"nodes": list(nodes.values()), "edges": edges}


def whole_graph(graph) -> dict:
    """Every node and edge, closed edges included. Used by the "Show full graph" toggle."""
    nodes: dict[str, dict] = {}
    edges = []
    for r in queries.graph_all(graph):
        for node_id, label, name in ((r["src"], r["src_label"], r["src_name"]),
                                     (r["dst"], r["dst_label"], r["dst_name"])):
            nodes.setdefault(node_id, _node(node_id, label, name))
        edges.append({"from": r["src"], "to": r["dst"], "type": r["type"],
                      "closed": r["valid_to"] is not None,
                      "valid_from": r["valid_from"], "valid_to": r["valid_to"], "source": r.get("source")})
    return {"nodes": list(nodes.values()), "edges": edges}


class _Graph:
    def __init__(self, name_ids: dict):
        self.name_ids = name_ids
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []

    def node(self, node_id: str, label: str, name: str) -> str:
        self.nodes.setdefault(node_id, _node(node_id, label, name))
        return node_id

    def by_name(self, name: str, label: str) -> str:
        node_id = self.name_ids.get(name) or f"{label.lower()}:{name}"
        return self.node(node_id, label, name)

    def edge(self, src: str, dst: str, kind: str, closed: bool = False) -> None:
        self.edges.append(_edge(src, dst, kind, closed))

    def out(self) -> dict:
        return {"nodes": list(self.nodes.values()), "edges": self.edges}


def build(tool: str, result: dict, name_ids: dict) -> dict:
    g = _Graph(name_ids)
    rows = result["rows"]

    if tool == "who_owns":
        svc = g.node(result["service_id"], "Service", result["service"])
        for r in rows:
            person = g.node(r["person_id"], "Person", r["person"])
            g.edge(person, svc, "OWNS", closed=r["valid_to"] is not None)
            if r.get("source"):
                msg = g.node(r["source"], "Message", r["source"])
                g.edge(msg, svc, "ABOUT")

    elif tool == "who_knows":
        svc = g.node(result["service_id"], "Service", result["service"])
        for r in rows:
            person = g.by_name(r["person"], "Person")
            g.edge(person, svc, "WORKED_ON")

    elif tool == "what_changed":
        labels = {"OWNS": ("Person", "Service"), "MEMBER_OF": ("Person", "Team"),
                  "ASSIGNED_TO": ("Ticket", "Person")}
        for r in rows:
            src_label, dst_label = labels.get(r["rel"], ("Entity", "Entity"))
            src = g.by_name(r["from"], src_label)
            dst = g.by_name(r["to"], dst_label)
            g.edge(src, dst, r["rel"], closed=r["closed"] is not None)

    elif tool == "blast_radius":
        person = g.node(result["person_id"], "Person", result["person"])
        for r in rows:
            owned = g.by_name(r["owned"], "Service")
            g.edge(person, owned, "OWNS")
            for ticket in r["open_tickets"]:
                g.edge(g.by_name(ticket, "Ticket"), owned, "FOR")
        # Each DEPENDS_ON hop is an actual stored edge, src -> dst.
        for hop in result["hops"]:
            src = g.node(hop["src"], "Service", hop["src_name"])
            dst = g.node(hop["dst"], "Service", hop["dst_name"])
            g.edge(src, dst, "DEPENDS_ON")

    elif tool == "ticket_assignee":
        ticket = g.node(result["ticket_id"], "Ticket", result["ticket"])
        for r in rows:
            person = g.node(r["person_id"], "Person", r["person"])
            g.edge(ticket, person, "ASSIGNED_TO")
            if r.get("source"):
                msg = g.node(r["source"], "Message", r["source"])
                g.edge(msg, ticket, "ABOUT")

    return g.out()
