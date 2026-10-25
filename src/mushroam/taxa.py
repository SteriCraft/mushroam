"""Résolution des identifiants de taxons (iNaturalist et GBIF) dans config/taxa.yaml.

Usage : python -m mushroam.taxa
"""

from __future__ import annotations

import yaml

from mushroam.config import CONFIG_DIR, load_taxa
from mushroam.gbif.client import GBIFClient
from mushroam.inat.client import INatClient

INAT_FUNGI_ID = 47170  # règne Fungi dans iNaturalist, référence connue

HEADER = """\
# Taxons du projet. Les identifiants (inat_id, gbif_key) sont résolus par API :
#   python -m mushroam.taxa
# Ne pas les saisir à la main (ce fichier est réécrit : les commentaires hors
# de cet en-tête sont perdus).
#
# fond            : fond de référence (toutes les Fungi).
# cibles          : espèces ou familles recherchées. fenetre_jours = fenêtre de
#                   poussée après une situation météo analogue, en jours
#                   (d'après l'étape 4 : pics à 7-14 j pour la coulemelle,
#                   28-35 j pour les bolets des feuillus, 21-60 j pour ceux des pins).
# exclusions_fond : lignées lichénisées, retirées du fond.
# indicateurs     : espèces témoins (document synthese_champignons_indicateurs) :
#                   même milieu ou mêmes arbres hôtes que leur cible.
"""


def resolve_inat(client: INatClient, name: str, rank: str) -> int:
    data = client.get("/v1/taxa", {"q": name, "rank": rank, "per_page": 30})
    exact = [
        t for t in data["results"]
        if t["name"].lower() == name.lower() and t["rank"] == rank and t.get("is_active", True)
    ]
    if len(exact) != 1:
        found = [(t["id"], t["name"], t["rank"]) for t in data["results"][:5]]
        raise ValueError(f"iNat {name} ({rank}) : {len(exact)} correspondance(s). Candidats : {found}")
    t = exact[0]
    if t["id"] != INAT_FUNGI_ID and INAT_FUNGI_ID not in t.get("ancestor_ids", []):
        raise ValueError(f"iNat {name} ({t['id']}) n'appartient pas aux Fungi")
    return t["id"]


def resolve_gbif(client: GBIFClient, name: str, rank: str) -> int:
    m = client.get("/species/match", {"name": name, "rank": rank.upper(), "strict": "true"})
    if m.get("matchType") != "EXACT" or m.get("rank", "").lower() != rank:
        raise ValueError(f"GBIF {name} ({rank}) : pas de correspondance exacte ({m.get('matchType')})")
    if m.get("kingdom") != "Fungi":
        raise ValueError(f"GBIF {name} n'appartient pas aux Fungi ({m.get('kingdom')})")
    # Un synonyme renvoie vers le nom accepté.
    return m.get("acceptedUsageKey") or m["usageKey"]


def resolve_entry(entry: dict, inat: INatClient, gbif: GBIFClient, strict: bool = True) -> dict:
    out = {"name": entry["name"], "rank": entry["rank"]}
    for key, fn, client in (("inat_id", resolve_inat, inat), ("gbif_key", resolve_gbif, gbif)):
        try:
            out[key] = fn(client, entry["name"], entry["rank"])
        except ValueError as e:
            if strict:
                raise
            print(f"  avertissement : {e}")
            out[key] = None
    return out


def resolve_all() -> dict:
    inat, gbif = INatClient(), GBIFClient()
    cfg = load_taxa()
    cfg["fond"] = resolve_entry(cfg["fond"], inat, gbif)
    for cible in cfg["cibles"].values():
        cible["membres"] = [resolve_entry(m, inat, gbif) for m in cible["membres"]]
    for groupe in cfg.get("indicateurs", {}).values():
        groupe["membres"] = [resolve_entry(m, inat, gbif, strict=False) for m in groupe["membres"]]
    # Les exclusions tolèrent un taxon absent d'un des deux référentiels.
    for group, entries in cfg.get("exclusions_fond", {}).items():
        cfg["exclusions_fond"][group] = [resolve_entry(e, inat, gbif, strict=False) for e in entries]
    return cfg


def main() -> None:
    cfg = resolve_all()
    with open(CONFIG_DIR / "taxa.yaml", "w", encoding="utf-8") as f:
        f.write(HEADER)
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)

    def show(label, e):
        print(f"{label:12s} {e['name']:25s} {e['rank']:8s} iNat={e['inat_id']}  GBIF={e['gbif_key']}")

    show("fond", cfg["fond"])
    for key, cible in cfg["cibles"].items():
        for m in cible["membres"]:
            show(key, m)
    for group, entries in cfg.get("exclusions_fond", {}).items():
        for e in entries:
            show(group, e)
    for key, groupe in cfg.get("indicateurs", {}).items():
        for m in groupe["membres"]:
            show(key, m)


if __name__ == "__main__":
    main()
