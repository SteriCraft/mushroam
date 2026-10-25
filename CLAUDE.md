# Prévision de poussées de champignons – Montpellier +100 km

## Objectif

Estimer, pour une espèce (ou un groupe) de champignons, **les secteurs et les périodes où la probabilité de la trouver est la plus élevée**, à partir :
- des observations historiques iNaturalist ;
- des conditions météo et d'humidité des sols récentes ;
- de la recherche de situations passées analogues (même saison, pluviométrie et humidité des sols proches).

L'outil est un projet personnel exploratoire. Priorité : une méthode simple, interprétable et validée, avant toute sophistication.

## Périmètre

- **Centre** : Montpellier (lat 43.6108, lng 3.8767).
- **Rayon** : 100 km à vol d'oiseau.
- Zone très contrastée : littoral et garrigue méditerranéenne, plaines viticoles, Causses et Larzac, Cévennes et massif de l'Aigoual (jusqu'à environ 1 500 m), contreforts de l'Espinouse et du Caroux. Les poussées n'y ont pas lieu au même moment selon l'altitude. **L'altitude est une variable de premier ordre.**
- Climat méditerranéen : sécheresse estivale marquée, pluies d'automne souvent concentrées (épisodes cévenols). La saison principale visée est l'automne ; le printemps est secondaire.

## Taxons visés

| Cible | Rang | Écologie | Conséquence pour le modèle |
|---|---|---|---|
| Coulemelle (*Macrolepiota procera*) | espèce | Saprotrophe. Prairies, lisières, clairières, bords de chemins. | Habitat ouvert ou semi-ouvert, pas lié à une essence d'arbre. |
| Boletaceae | famille | Ectomycorhiziens. Chênes (vert, pubescent), châtaigniers, hêtres, pins. | Habitat forestier, lié aux essences hôtes. Prévoir de descendre au genre ou à l'espèce (*Boletus edulis*, *B. aereus*, *B. aestivalis*, etc.), car les espèces n'ont pas toutes la même phénologie. |
| Troisième cible | à définir | – | – |

Les `taxon_id` iNaturalist ne doivent **pas** être codés en dur de mémoire. Les résoudre via `GET /v1/taxa?q=<nom>&rank=<rang>` et les stocker dans `config/taxa.yaml`. Référence connue : règne Fungi = `47170`.

## Sources de données

### Observations : iNaturalist API v1 (`https://api.inaturalist.org/v1/`)
- `/observations` : observations détaillées. `/observations/species_counts` : comptes par taxon. `/observations/histogram` : distribution temporelle.
- Filtres : `taxon_id`, `lat`/`lng`/`radius` (km), `d1`/`d2` (date d'observation), `quality_grade=research`, `geoprivacy`, `taxon_geoprivacy`.
- Limites : 200 résultats par page, **10 000 résultats maximum par jeu de paramètres** → paginer avec `order_by=id&order=asc&id_above=<dernier id>`, ou découper par période.
- Débit : **1 requête par seconde maximum**, avec un `User-Agent` explicite. Mettre toutes les réponses en cache local : ne jamais refaire une requête déjà faite.
- Bibliothèque Python : `pyinaturalist`.
- Alternative pour les gros volumes : téléchargement GBIF (dataset iNaturalist Research-grade Observations).

### Météo et humidité des sols (couche temporelle)
- **Prioritaire : ERA5-Land** (réanalyse Copernicus, environ 9 km, horaire, depuis 1950) : précipitations, température à 2 m, humidité volumétrique du sol par couche (`swvl1` 0–7 cm, `swvl2` 7–28 cm).
  - Accès simple : API historique Open-Meteo (pas de clé), qui expose ERA5-Land.
  - Accès complet : Copernicus Climate Data Store (`cdsapi`, compte requis).
- Complément possible : données ouvertes Météo-France (stations, réanalyse SAFRAN/SIM, plus fine).
- Humidité satellitaire (Sentinel-1, SMOS) : **non prioritaire**. Le radar mesure mal le sol sous couvert forestier dense. À n'envisager qu'en comparaison avec la réanalyse.

### Habitat (couche spatiale, statique)
- Essences forestières : BD Forêt v2 (IGN).
- Occupation du sol : OSO (Theia/CESBIO, dérivé de Sentinel-2) ou Corine Land Cover.
- Relief : RGE ALTI ou Copernicus DEM (altitude, pente, exposition).
- Géologie / pH : carte géologique BRGM (calcaire vs silice, déterminant pour plusieurs bolets).
- Sentinel-2 : utile pour l'habitat et l'état de la végétation (NDVI, NDMI), **pas** pour l'humidité du sol.

## Architecture du modèle

Deux couches combinées :

1. **Habitat favorable (« où »)** : carte statique de favorabilité par maille, construite à partir des observations passées et des variables d'habitat. Une maille de 1 km est un bon point de départ.
2. **Déclenchement météo (« quand »)** : indice dynamique, calculé chaque jour par maille météo, selon l'approche par analogues.

Probabilité finale ≈ favorabilité d'habitat × indice de déclenchement, sur une échelle relative (classement des secteurs), et non une probabilité absolue.

### Approche par analogues (couche temporelle)
1. Pour chaque date passée et chaque maille météo, construire un vecteur de variables avec décalage temporel :
   - cumul de pluie sur 7, 14, 21 et 30 jours ;
   - humidité du sol (`swvl1`, `swvl2`) moyenne et tendance ;
   - températures minimales et maximales moyennes sur 7 et 14 jours, présence de gel ;
   - jours écoulés depuis la dernière pluie de plus de 20 mm ;
   - jour de l'année, encodé en sinus et cosinus.
2. Pour la situation actuelle, chercher les k dates passées les plus proches (même fenêtre saisonnière, plus ou moins 30 jours), avec des variables standardisées.
3. Mesurer l'activité de fructification observée **dans les jours qui suivent** ces analogues (fenêtre de 0 à 21 jours), corrigée du biais d'observation (voir ci-dessous).
4. Agréger en indice de déclenchement.

## Biais d'observation : règle impérative

Les observations iNaturalist sont des **présences seules** et reflètent l'effort d'observation : week-ends, sentiers, proximité des villes, forte croissance de l'usage depuis 2020. **Ne jamais utiliser un nombre brut d'observations comme mesure d'abondance.**

- Mesure de référence : **proportion** = observations du taxon cible / observations de toutes les Fungi (méthode « target-group background »), pour la même maille et la même période.
- Exclure ou traiter à part les coordonnées floutées (`obscured`) et les observations peu précises (`positional_accuracy` élevée).
- Garder `quality_grade=research` par défaut. Prévoir une option pour inclure `needs_id`, utile pour la famille Boletaceae.
- Utiliser la date d'observation, pas la date de mise en ligne.

## Validation

- Validation par **saisons entières mises de côté** (par exemple entraîner sans l'automne 2024, puis tester dessus). Jamais de découpage aléatoire des observations, car elles sont corrélées dans le temps et l'espace.
- Référence de comparaison : la phénologie moyenne seule (jour de l'année). Le modèle doit faire mieux.
- Surveiller les effectifs : si un taxon a trop peu d'observations dans une maille, regrouper les mailles ou les taxons.

## Structure du dépôt (proposée)

```
config/          taxa.yaml, zone.yaml (centre, rayon, maille), paramètres
data/raw/        réponses brutes en cache (iNat, météo), non versionnées
data/processed/  tables nettoyées (parquet)
src/
  inat/          extraction et cache iNaturalist
  meteo/         extraction ERA5-Land / Open-Meteo, variables décalées
  habitat/       couches spatiales, grille
  model/         analogues, favorabilité, combinaison
  viz/           cartes et graphiques
notebooks/       exploration
tests/
```

## Conventions

- Python 3.11 ou plus récent. Environnement géré par `uv`, ou à défaut `venv` et `requirements.txt`.
- Bibliothèques : `pyinaturalist`, `requests`, `pandas` / `polars`, `geopandas`, `shapely`, `xarray`, `rasterio`, `scikit-learn`, `folium` ou `matplotlib`.
- Système de coordonnées : WGS84 (EPSG:4326) en entrée, Lambert-93 (EPSG:2154) pour les calculs de distance et de surface.
- `data/` est exclu de git. Aucune clé d'API dans le code : variables d'environnement via `.env`.
- Code et commentaires en français ou en anglais, mais de façon cohérente dans tout le dépôt.

## Feuille de route V1

1. Résoudre les `taxon_id`. Extraire toutes les observations de Fungi dans le rayon (fond de référence) et celles des taxons cibles, avec cache.
2. Analyse exploratoire : effectifs par année et par mois, répartition spatiale, part d'observations floutées, gradient d'altitude.
3. Extraire ERA5-Land sur la zone pour la période couverte par les observations. Calculer les variables décalées.
4. Pour chaque observation cible, afficher les conditions météo des 30 jours précédents. Comparer avec le fond de référence.
5. Premier modèle par analogues (couche temporelle seule), avec validation par saison mise de côté.
6. Ajouter ensuite la couche habitat.

## Questions ouvertes

- Troisième taxon cible.
- Boletaceae : travailler sur la famille entière ou sur quelques espèces prioritaires ?
- Format de sortie souhaité : carte web interactive, rapport hebdomadaire, alerte ?