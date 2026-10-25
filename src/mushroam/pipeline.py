"""Enchaîne les étapes du pipeline, de l'extraction au site.

Deux modes :
- quotidien (par défaut) : nouvelles observations iNat et GBIF (incrémental, ~20 s),
  météo SIM2, effort iNat, table unifiée, prédiction du jour, site. Les modèles
  (habitat, listes de sortie) ne sont pas réentraînés.
- complet (--complet) : toutes les étapes, dans l'ordre, modèles compris. Les extractions
  iNat et GBIF sont refaites en entier (--refresh), pour récupérer les observations
  modifiées (identifications, qualité), que l'incrémental ne voit pas. Les autres
  téléchargements en cache ne sont pas refaits. Premier passage : environ 30 min.

Les identifiants de taxons (config/taxa.yaml) sont versionnés : `mushroam.taxa`
n'est pas relancé ici.

Usage : python -m mushroam.pipeline [--complet]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time

QUOTIDIEN = [
    "mushroam.inat.extract",
    "mushroam.gbif.extract",
    "mushroam.meteo.sim2",
    "mushroam.meteo.features",
    "mushroam.inat.effort",
    "mushroam.observations",
    "mushroam.model.prediction",
    "mushroam.viz.site",
]

COMPLET = [
    "mushroam.inat.extract --refresh",
    "mushroam.gbif.extract --refresh",
    "mushroam.habitat.dem",
    "mushroam.habitat.landcover",
    "mushroam.meteo.sim2",
    "mushroam.meteo.features",
    "mushroam.inat.effort",
    "mushroam.observations",
    "mushroam.habitat.vecteurs",
    "mushroam.habitat.grille",
    "mushroam.model.habitat",
    "mushroam.model.meteo_classes",
    "mushroam.model.sorties",
    "mushroam.model.prediction",
    "mushroam.viz.site",
]


def run(modules: list[str]) -> None:
    for m in modules:
        print(f"\n=== {m} ===", flush=True)
        t0 = time.time()
        subprocess.run([sys.executable, "-m", *m.split()], check=True)
        print(f"--- {m} : {time.time() - t0:.0f} s", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--complet", action="store_true", help="toutes les étapes (sinon : mise à jour quotidienne)")
    args = parser.parse_args()
    run(COMPLET if args.complet else QUOTIDIEN)


if __name__ == "__main__":
    main()
