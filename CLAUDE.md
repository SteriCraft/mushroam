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
| Bolets : Boletaceae + Suillaceae + Gyroporaceae | 3 familles, modélisées ensemble | Ectomycorhiziens. Chênes (vert, pubescent), châtaigniers, hêtres, pins (*Suillus* : pins uniquement). | Habitat forestier, lié aux essences hôtes. Groupe unique (décision : le tri se fait sur le terrain). La famille de chaque observation est conservée (`membre_bolets`) pour une analyse séparée si besoin. |

Pas de troisième cible.

Les identifiants de taxons (iNaturalist `inat_id`, GBIF `gbif_key`) ne doivent **pas** être codés en dur de mémoire : `python -m mushroam.taxa` les résout (`/v1/taxa` iNat, `/species/match` GBIF) et les écrit dans `config/taxa.yaml`. Référence connue : règne Fungi = `47170` (iNat), `5` (GBIF).

**Fond de référence = Fungi hors lichens** (décision) : les lignées lichénisées sont listées dans `exclusions_fond` de `config/taxa.yaml`.

## Sources de données

### Observations : iNaturalist API (`https://api.inaturalist.org/`)
- **Extraction via l'API v2** (`/v2/observations?fields=...`) : on choisit les champs renvoyés, et les réponses sont environ 65 fois plus légères qu'en v1 (115 Ko contre 7,6 Mo par page de 200). La v1 sert à `/v1/taxa`.
- Client maison (`src/mushroam/inat/client.py`) plutôt que `pyinaturalist`, pour maîtriser le cache (`data/raw/inat/`, JSON gzip).
- `/observations` : observations détaillées. `/observations/species_counts` : comptes par taxon. `/observations/histogram` : distribution temporelle.
- Filtres : `taxon_id`, `lat`/`lng`/`radius` (km), `d1`/`d2` (date d'observation), `quality_grade=research`, `geoprivacy`, `taxon_geoprivacy`.
- Limites : 200 résultats par page, **10 000 résultats maximum par jeu de paramètres** → paginer avec `order_by=id&order=asc&id_above=<dernier id>`, ou découper par période.
- Débit : **1 requête par seconde maximum**, avec un `User-Agent` explicite. Mettre toutes les réponses en cache local : ne jamais refaire une requête déjà faite.

### Observations : GBIF (`https://api.gbif.org/v1/`)
- Ajouté en complément d'iNat (décision) : GBIF agrège SINP/INPN (Parc national des Cévennes, Conservatoires botaniques, ONF, ZNIEFF, Atlas de biodiversité…), Observation.org, herbiers, données mycologiques (FongiFrance / J.-C. Malaval). Environ 49 000 occurrences de Fungi dans la zone, surtout 2001–2022 : complémentaire d'iNat (2020+).
- Recherche `/occurrence/search` découpée par année (limite de 100 000 par requête). Années passées figées en cache, année en cours refaite.
- Le jeu GBIF « iNaturalist Research-grade Observations » est **exclu** (iNat est extrait directement). Règles de fusion : `config/sources.yaml`.
- **Attention à la précision** : beaucoup de jeux GBIF ramènent les observations à un site ou une commune (ex. : Malaval, 3 500 obs. sur 43 points ; Atlas départemental, incertitude 64 km). Précision inconnue = imprécise pour l'habitat.
- Observation.org n'expose pas d'API ouverte sans compte : on passe par sa copie GBIF (environ 300 obs. seulement).

### Météo et humidité des sols (couche temporelle)
- **Source retenue : SIM2 de Météo-France** (réanalyse SAFRAN-ISBA, maille de 8 km, quotidienne depuis 1958, mise à jour chaque jour, données ouvertes sans compte). Variables : pluie, neige, températures moyenne / min / max, humidité de l'air, ETP, indice d'humidité des sols `SWI` (zone racinaire), contenu en eau racinaire. Module `src/mushroam/meteo/sim2.py` : 428 mailles dans la zone (+10 km), de 1999 à la veille.
- Pourquoi pas ERA5-Land via Open-Meteo : l'offre gratuite compte une requête pour 14 jours et 1 lieu, ce qui ferait environ 200 000 requêtes pour 26 ans × 300 mailles, soit 3 semaines de quota. ERA5-Land reste possible via le Copernicus CDS (compte requis), à n'envisager qu'en comparaison.
- Limite connue : SAFRAN lisse les reliefs (maille de l'Aigoual ≈ 1 000 mm/an, contre ≈ 2 000 mm au sommet).
- ERA5-Land (pour mémoire) (réanalyse Copernicus, environ 9 km, horaire, depuis 1950) : précipitations, température à 2 m, humidité volumétrique du sol par couche (`swvl1` 0–7 cm, `swvl2` 7–28 cm).
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

## Structure du dépôt

```
config/          zone.yaml (centre, rayon, maille), taxa.yaml (généré), sources.yaml (règles de fusion)
data/raw/        réponses brutes en cache (iNat, météo), non versionnées
data/processed/  tables nettoyées (parquet), MNT
data/outputs/    rapports et cartes HTML générés
src/mushroam/    paquet Python (installé en mode éditable)
  config.py      chemins et lecture de config/
  http.py        client HTTP générique (cache gzip, 1 req/s, reprises)
  taxa.py        résolution des identifiants de taxons
  observations.py  fusion des sources, doublons, altitude
  inat/ gbif/    extraction et mise à plat par source
  meteo/         sim2.py (extraction SIM2), features.py (variables décalées)
  habitat/       dem.py (relief), landcover.py (WorldCover, part de bâti)
  model/         analogues, favorabilité, combinaison
  viz/           site.py (site à onglets), explore.py, meteo_page.py, map.py, theme.py
notebooks/       exploration
tests/
```

Les sous-dossiers sont regroupés sous un paquet `mushroam` pour éviter des noms de modules génériques (`model`, `viz`) au premier niveau.

## Conventions

- Python 3.11 ou plus récent (installé : 3.14). Environnement `venv` dans `.venv/`, dépendances dans `pyproject.toml`.
  - Installation : `py -3.14 -m venv .venv` puis `.venv/Scripts/python -m pip install -e ".[dev]"`.
  - Tests : `.venv/Scripts/python -m pytest`.
- Bibliothèques : `requests`, `pandas`, `pyarrow`, `pyyaml`, `numpy`, `rasterio`, `folium`, `plotly` ; à venir : `geopandas`, `xarray`, `scikit-learn`.
- Fonds de carte : **jamais les tuiles `tile.openstreetmap.org`**. Leurs serveurs bloquent les pages ouvertes en `file://` (pas d'en-tête Referer). Utiliser OpenTopoMap, Esri (World Imagery, Light/Dark Gray Canvas) ou un autre fournisseur sans clé qui accepte ce cas.
- Graphiques : une couleur fixe par entité (`src/mushroam/viz/theme.py`) : iNat bleu, GBIF jaune, coulemelle aqua, bolets orange. Jamais deux échelles sur un même graphique.
- Système de coordonnées : WGS84 (EPSG:4326) en entrée, Lambert-93 (EPSG:2154) pour les calculs de distance et de surface.
- `data/` est exclu de git. Aucune clé d'API dans le code : variables d'environnement via `.env`.
- **Langue : français** pour les commentaires, la documentation, les messages et les échanges. Identifiants Python en anglais, sauf pour les termes du domaine issus de la configuration (`cible_*`, `membre_*`, `fond`).

### Filtre de localisation (décision)
Observations saisies ailleurs que sur le lieu de récolte (bureau, laboratoire, domicile), exclues du fond comme des cibles (`retenue = False`) :
- `urbain` : au moins 30 % de bâti (ESA WorldCover) dans une fenêtre de 600 m autour du point ;
- `point_repete` (iNat seulement) : même observateur, même point à 50 m près, au moins 10 dates distinctes.
Paramètres dans `config/sources.yaml`. La carte des observations a une couche (masquée) des cibles exclues, pour contrôle.

## Commandes (dans l'ordre du pipeline)

```
.venv/Scripts/python -m mushroam.taxa            # identifiants iNat + GBIF -> config/taxa.yaml
.venv/Scripts/python -m mushroam.inat.extract    # Fungi iNat -> data/processed/inat.parquet
.venv/Scripts/python -m mushroam.gbif.extract    # Fungi GBIF -> data/processed/gbif.parquet
.venv/Scripts/python -m mushroam.habitat.dem     # MNT Copernicus 90 m -> data/processed/dem_90m.tif
.venv/Scripts/python -m mushroam.habitat.landcover  # WorldCover 40 m + part de bâti -> data/processed/
.venv/Scripts/python -m mushroam.meteo.sim2      # SIM2 de la zone -> data/raw/sim2/zone/ (année en cours refaite)
.venv/Scripts/python -m mushroam.meteo.features  # variables décalées -> data/processed/meteo_features.parquet
.venv/Scripts/python -m mushroam.inat.effort     # effort iNat quotidien (tous groupes / Fungi) -> data/processed/inat_effort.parquet
.venv/Scripts/python -m mushroam.observations    # table unifiée -> data/processed/observations.parquet
.venv/Scripts/python -m mushroam.viz.site        # site local -> data/outputs/site/index.html
```

Les extractions récupèrent **toutes** les Fungi du rayon (tous niveaux de qualité) : fond et cibles viennent de la même requête. `--refresh` retélécharge tout. Sous Windows, préfixer par `PYTHONUTF8=1` si la console affiche mal les accents.

### Table unifiée `observations.parquet`
Une ligne par observation datée au jour près, dans le rayon. Colonnes clés : `source` (inat / gbif), `quality` (research / needs_id / gbif), `precision_m`, `lichen`, `cible_<clé>`, `membre_<clé>`, `ok_habitat` (précision ≤ 1 km), `ok_meteo` (≤ 10 km ou inconnue), `doublon`, `altitude_m`, `bati`, `urbain`, `point_repete`, **`retenue`** (filtre par défaut), `cellule_meteo` (clé de jointure avec `meteo_features.parquet` sur `cellule` + `date`).
- **Unité d'observation** : un taxon, un jour, un lieu à environ 1 km près. Les doublons (copies entre jeux GBIF, relevés répétés, photos multiples) sont marqués `doublon` et doivent être écartés des comptages, pour les cibles comme pour le fond.
- Observations iNat « à confirmer » (`needs_id`) incluses (décision : le tri se fait sur le terrain). « casual » et captives exclues.

## Feuille de route V1

1. ~~Résoudre les `taxon_id`. Extraire toutes les observations de Fungi dans le rayon (fond de référence) et celles des taxons cibles, avec cache.~~ Fait.
2. ~~Analyse exploratoire : effectifs par année et par mois, répartition spatiale, part d'observations floutées, gradient d'altitude.~~ Fait (rapport `data/outputs/exploration/index.html`). Résultats principaux :
   - bolets : saison décalée d'environ −2,4 jours par 100 m d'altitude (médiane au 28/10 sous 400 m, au 30/09 au-dessus de 1 200 m) ; une poussée estivale existe (juin–août : *Neoboletus erythropus*, *B. reticulatus*) ;
   - 21 automnes avec au moins 20 observations de bolets (GBIF + iNat) ; seulement 5 avec au moins 10 coulemelles ;
   - effort : pic d'observations iNat le week-end, pic GBIF le vendredi (sorties de groupes / inventaires).
3. ~~Extraire la météo sur la zone pour la période couverte par les observations. Calculer les variables décalées.~~ Fait avec SIM2 (voir ci-dessus) : `meteo_features.parquet`, une ligne par maille et par jour (pluie 7/14/21/30 j, bilan pluie − ETP 30 j, SWI et tendances 7/14 j, Tmin/Tmax 7/14 j, jours de gel, jours depuis une pluie ≥ 20 mm, jour de l'année en sinus/cosinus). Fenêtres terminées le jour même, inclus.
4. ~~Pour chaque observation cible, afficher les conditions météo des 30 jours précédents. Comparer avec le fond de référence.~~ Fait (`src/mushroam/model/conditions.py`, section « Météo et poussées » de l'onglet Météo, météo du jour dans les fenêtres de la carte des observations).
   - **Méthode** : standardisation indirecte. Proportion attendue par strate (quinzaine × tranche d'altitude), puis rapport observé / attendu par classe de variable météo. Deux niveaux qui se multiplient :
     1. *activité des champignons* = Fungi / toutes observations iNat (plantes, oiseaux…, mesure de l'effort), au niveau de la zone, par jour, depuis 2019. **Indispensable** : la proportion cible / Fungi seule neutralise la réponse commune des champignons à la pluie ;
     2. *part de la cible* = cible / Fungi, par maille SIM2.
   - **Résultats** (rapports par rapport à la même période de l'année) :
     - Fungi : × 1,5 dans les 7 jours après une pluie ≥ 20 mm, × 1,25 de 7 à 21 jours, × 0,85 au-delà de 35 jours ; × 1,3 si SWI ≥ 0,73 ; × 0,64 si pluie 30 j < 26 mm ; × 0,8 si Tmax 7 j ≥ 27 °C ou Tmin 7 j < 5 °C ;
     - bolets : poussée **décalée**, part maximale 21 à 35 jours après la pluie (× 1,24) et faible juste après (× 0,87) ; sols plus humides que la normale 15 à 30 jours avant ;
     - coulemelle : plus précoce, part maximale 7 à 14 jours après la pluie (× 1,42) ; sols plus secs que la normale à J−30 puis remise en eau rapide les 15 derniers jours.
   - Limites : intervalles de confiance approchés et trop étroits (observations groupées par sortie) ; météo de la zone moyennée pour le niveau 1.
5. Premier modèle par analogues (couche temporelle seule), avec validation par saison mise de côté. Conséquences de l'étape 4 : garder les deux niveaux (activité des Fungi corrigée de l'effort × part de la cible) ; la fenêtre de 0 à 21 jours après l'analogue est trop courte pour les bolets (pic à 3–5 semaines) : la rendre propre à chaque cible.
6. Ajouter ensuite la couche habitat.
7. Sortie : **site local à onglets** (`data/outputs/site/index.html`) : Observations (carte puis données), Météo (carte par maille avec choix de variable et de date sur 90 jours, puis données et écarts aux normales), Prédiction (à venir).

## Questions ouvertes

- Coulemelle : trop peu de données par automne pour une validation saison par saison seule. Regrouper plusieurs saisons par pli, ou s'appuyer sur un modèle commun aux deux cibles ?
- Fond de référence GBIF : les inventaires d'associations (Malaval, CBN) ont un effort très différent d'iNat. Faut-il calculer les proportions par source puis les combiner ?
