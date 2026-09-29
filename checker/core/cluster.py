"""Groups of submissions sharing rare content (plan.md §11)."""

from collections import defaultdict

import networkx as nx
from sqlalchemy import select

from checker.config import get_settings
from checker.core.db import Match, Submission


def clusters(db, assignment_id: int) -> list[dict]:
    """-> [{members:[sub ids], hub, edges:[{a, b, weight, items}]}], largest first.
    Edge weight = summed rarity weight of the shared items (from both sides' reports)."""
    s = get_settings()
    subs = {x.id: x for x in db.scalars(select(Submission).where(Submission.assignment_id == assignment_id,
                                                                  Submission.status == "done"))}
    weights = {}
    for x in subs.values():
        weights.update({int(k): v for k, v in ((x.report_json or {}).get("item_weights") or {}).items()})
    pair_items = defaultdict(set)
    for m in db.scalars(select(Match).where(Match.submission_id.in_(subs))):
        a, b = sorted((m.submission_id, m.other_submission_id))
        pair_items[(a, b)].add(m.item_id)
    g = nx.Graph()
    for (a, b), items in pair_items.items():
        w = sum(weights.get(i, 0) for i in items) / 2  # each shared item is counted from both sides
        if w >= s.cluster_min_edge:
            g.add_edge(a, b, weight=round(w, 2), items=len(items) // 2 or 1)
    out = []
    for comp in nx.connected_components(g):
        groups = [comp]
        if len(comp) > 10:
            groups = nx.community.louvain_communities(g.subgraph(comp), weight="weight", seed=0)
        for grp in groups:
            if len(grp) < 2:
                continue
            sg = g.subgraph(grp)
            hub = max(grp, key=lambda n: sg.degree(n, weight="weight"))
            out.append({"members": sorted(grp, key=lambda n: -sg.degree(n, weight="weight")), "hub": hub,
                        "edges": [{"a": a, "b": b, **d} for a, b, d in sg.edges(data=True)],
                        "subs": {n: subs[n] for n in grp}})
    return sorted(out, key=lambda c: -len(c["members"]))
