"""Turn a tool result into {nodes, edges} for the graph view.

Pure functions: no database calls. name_ids maps names that the result carries
(persons, services, tickets) to their graph ids. A name with no id gets a
placeholder id, so the node still shows.
"""


def _node(node_id: str, label: str, name: str) -> dict:
    return {"id": node_id, "label": label, "name": name}


def _edge(src: str, dst: str, kind: str, closed: bool = False) -> dict:
    return {"from": src, "to": dst, "type": kind, "closed": closed}


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
            for dep in r["dependents"]:
                # Dependents can be several hops away; the edge is drawn to the owned service.
                g.edge(g.by_name(dep, "Service"), owned, "DEPENDS_ON")
            for ticket in r["open_tickets"]:
                g.edge(g.by_name(ticket, "Ticket"), owned, "FOR")

    elif tool == "ticket_assignee":
        ticket = g.node(result["ticket_id"], "Ticket", result["ticket"])
        for r in rows:
            person = g.node(r["person_id"], "Person", r["person"])
            g.edge(ticket, person, "ASSIGNED_TO")
            if r.get("source"):
                msg = g.node(r["source"], "Message", r["source"])
                g.edge(msg, ticket, "ABOUT")

    return g.out()
