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
| Bolets des feuillus (`bolets_feuillus`) : Boletaceae + Gyroporaceae | 2 familles | Ectomycorhiziens. Chênes (vert, pubescent), châtaigniers, hêtres (quelques Boletaceae sous pins). | Habitat forestier feuillu. Poussée d'été et d'automne, pic 28–35 jours après une pluie ≥ 20 mm. Fenêtre de poussée : 14–40 jours. |
| Bolets des pins (`bolets_pins`) : Suillaceae | famille | Ectomycorhiziens des pins. | Pinèdes (garrigue, littoral, reboisements). Saison plus tardive (pic en novembre), poussée 21–60 jours après une pluie ≥ 20 mm. Fenêtre : 21–50 jours. |

Les bolets sont séparés en deux cibles (décision d'octobre 2026) : leurs géographies ne sont pas corrélées et leurs saisons diffèrent. Sur le terrain, ils peuvent être cherchés ensemble. La famille de chaque observation reste dans `membre_<cible>`.

Pas de troisième cible.

Les identifiants de taxons (iNaturalist `inat_id`, GBIF `gbif_key`) ne doivent **pas** être codés en dur de mémoire : `python -m mushroam.taxa` les résout (`/v1/taxa` iNat, `/species/match` GBIF) et les écrit dans `config/taxa.yaml`. Référence connue : règne Fungi = `47170` (iNat), `5` (GBIF).

**Fond de référence = Fungi hors lichens** (décision) : les lignées lichénisées sont listées dans `exclusions_fond` de `config/taxa.yaml`.

### Espèces témoins (document `synthese_champignons_indicateurs.docx`, non versionné)
Espèces partageant le milieu ou les arbres hôtes d'une cible, sans être la cible. Section `indicateurs` de `config/taxa.yaml`, colonnes `indic_<groupe>` dans `observations.parquet` :
- `prairie` (pour la coulemelle) : *Agaricus campestris*, *Coprinus comatus*, *Marasmius oreades*, *Infundibulicybe geotropa* (≈ 200 obs.) ;
- `feuillus` (pour les bolets) : *Russula cyanoxantha*, *Amanita rubescens* (≈ 190 obs.) ;
- `pinede` (pour les Suillus) : *Lactarius deliciosus*, *Tricholoma terreum* (≈ 170 obs.).

Évaluation sur nos données (octobre 2026) :
- **feuillus ↔ bolets des feuillus (Boletaceae)** : géographie corrélée (Spearman 0,53 entre mailles), même réponse décalée à la pluie, même poussée d'été. Un témoin vu dans la même maille dans les 10 jours précédents multiplie la part des bolets par 1,5 (IC 1,2–1,9). **Utile.**
- **pinède ↔ bolets des pins (Suillaceae)** : géographie corrélée (0,40), même saison tardive (pic en novembre). Pas lié aux Boletaceae. **Utile pour les Suillus seulement.**
- **prairie ↔ coulemelle** : aucune corrélation géographique (0,00), témoins de basse altitude (médiane 180 m contre 640 m), pas de réponse à la pluie. **Peu utile ici.** La coulemelle est corrélée aux témoins de feuillus (0,46) : dans la zone, c'est une espèce de lisière et de clairière (73 % des points précis sous couvert arboré dans WorldCover).
- **Suillaceae et Boletaceae ne se ressemblent pas** : géographie non corrélée (0,05), saison décalée (Suillus : 36 % en novembre, contre 14 %).

Règle (reprise du document) : un témoin n'est gardé que s'il améliore la prédiction hors échantillon (saisons mises de côté).

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
Retenu (étape 6), sans compte, via le WFS de la Géoplateforme (`https://data.geopf.fr/wfs/ows`) :
- **BD Forêt v2** (IGN, couche `LANDCOVER.FORESTINVENTORY.V2:formation_vegetale`) : environ 162 000 polygones dans la zone. Regroupés en 7 classes : chênes verts, feuillus, châtaignier et hêtre, pins, autres conifères, forêt mixte, lande.
- **Carte des sols INRAE** (Référentiels régionaux pédologiques au 1/250 000, couche `INRA.CARTE.SOLS:geoportail_vf`) : type de sol dominant de chaque unité, regroupé en calcaire (calcosol, rendisol, dolomitosol…), acide (alocrisol, podzosol, rankosol, brunisol…) et autre. Environ 9 000 polygones.
- Le WFS renvoie au plus 5 000 polygones par requête (environ 66 Mo de GeoJSON pour la BD Forêt). Chaque page est rasterisée aussitôt à 50 m ; seul ce résultat est mis en cache (`data/raw/wfs/`).
- Copernicus DEM (altitude, relief) et ESA WorldCover (cultures, prairies), déjà utilisés aux étapes 2 et 3.

Non retenus pour l'instant :
- OSO ou Corine Land Cover, qui doublonnent WorldCover ;
- carte géologique BRGM, remplacée par la carte des sols ;
- Sentinel-2 (NDVI, NDMI), utile pour l'état de la végétation mais **pas** pour l'humidité du sol.

## Architecture du modèle

**Version en service (étapes 5 et 6, octobre 2026)**, par maille de 1 km :

potentiel = favorabilité d'habitat × saison normale × facteur de la météo actuelle

- **habitat** (`model/habitat.py`) : régression logistique cible / Fungi sur les observations précises. Variables : parts de végétation, sols, cultures, prairies, altitude, relief. Saison et source servent de variables de nuisance, retirées de la carte. Favorabilité bornée à la plage des lieux prospectés (pas d'extrapolation).
- **saison** (`model/analogues.py: seasonal_level`) : activité normale des Fungi × part normale de la cible, par quinzaine et tranche d'altitude, moyennée sur les 14 jours à venir.
- **météo** (`model/meteo_classes.py`) : classe de la maille SIM2 selon des seuils simples (`config/modele.yaml`). Facteurs validés hors échantillon : défavorable × 0,75, normale × 1, favorable × 1,2.

L'approche par analogues ci-dessous a été testée (étape 5) puis **écartée pour l'instant** : elle ne bat pas la phénologie seule. Elle reste une piste pour plus tard.

Conception initiale, deux couches combinées :

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
config/          zone.yaml (centre, rayon, maille), taxa.yaml (généré), sources.yaml (règles de fusion), modele.yaml (réglages des modèles)
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
  habitat/       dem.py (relief), landcover.py (WorldCover, part de bâti), vecteurs.py (BD Forêt, sols), grille.py (1 km)
  model/         conditions.py (étape 4), analogues.py (écarté), meteo_classes.py, habitat.py, prediction.py
  viz/           site.py (site à onglets), explore.py, meteo_page.py, prediction_page.py, map.py, theme.py
notebooks/       exploration
tests/
```

Les sous-dossiers sont regroupés sous un paquet `mushroam` pour éviter des noms de modules génériques (`model`, `viz`) au premier niveau.

## Conventions

- Python 3.11 ou plus récent (installé : 3.14). Environnement `venv` dans `.venv/`, dépendances dans `pyproject.toml`.
  - Installation : `py -3.14 -m venv .venv` puis `.venv/Scripts/python -m pip install -e ".[dev]"`.
  - Tests : `.venv/Scripts/python -m pytest`.
- Bibliothèques : `requests`, `pandas`, `pyarrow`, `pyyaml`, `numpy`, `rasterio`, `folium`, `plotly`, `scikit-learn`.
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
.venv/Scripts/python -m mushroam.habitat.vecteurs   # BD Forêt + sols INRAE (WFS) -> foret_50m.tif, sols_50m.tif (~1 h la 1re fois)
.venv/Scripts/python -m mushroam.habitat.grille     # grille d'habitat 1 km -> habitat_1km.parquet
.venv/Scripts/python -m mushroam.model.habitat      # favorabilité + validation spatiale -> habitat_*.parquet
.venv/Scripts/python -m mushroam.model.meteo_classes  # contrôle des classes météo -> classes_meteo_validation.parquet
.venv/Scripts/python -m mushroam.model.prediction   # habitat × saison × météo du jour -> prediction_1km.parquet
.venv/Scripts/python -m mushroam.model.analogues    # (facultatif, piste écartée) -> analogues_validation.parquet
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
     - bolets (avant séparation) : poussée **décalée**, part maximale 21 à 35 jours après la pluie (× 1,24) et faible juste après (× 0,87) ; sols plus humides que la normale 15 à 30 jours avant. Après séparation : feuillus plus étalés (pic × 1,32 à 28–35 j), pins très en retrait juste après la pluie (× 0,65) puis × 1,2–1,5 de 21 à 60 jours ;
     - coulemelle : plus précoce, part maximale 7 à 14 jours après la pluie (× 1,42) ; sols plus secs que la normale à J−30 puis remise en eau rapide les 15 derniers jours.
   - Limites : intervalles de confiance approchés et trop étroits (observations groupées par sortie) ; météo de la zone moyennée pour le niveau 1.
5. ~~Premier modèle par analogues, validé sur saisons mises de côté.~~ Fait, **résultat négatif** (`model/analogues.py`, `config/modele.yaml`).
   - Méthode : k plus proches situations (6 variables standardisées, ± 30 jours de l'année), observations des analogues dans la fenêtre de poussée de chaque cible. Deux niveaux : activité des Fungi, et part de la cible rapportée à la normale de sa maille. Chaque pli d'années est prédit sans lui.
   - Résultat : aucune variante ne bat la phénologie seule, ni avec moins de variables, ni avec un autre k (30 à 3 000), ni à l'horizon de 0 à 7 jours. Seules les situations sèches se détectent (× 0,65–0,85). Les effets de l'étape 4 étaient mesurés sans mettre d'années de côté.
   - **Piste 1, gardée pour plus tard** : une régression simple sur 2 ou 3 variables (jours depuis une forte pluie, SWI par rapport à la normale).
   - **Piste 2, retenue** : classe météo actuelle par seuils simples (`model/meteo_classes.py`), contrôlée année par année. Sur 0 à 14 jours : défavorable × 0,75 (sous 1 les 8 années 2019–2026) et favorable × 1,20 (au-dessus de 1 les 8 années). Limite : contrôle sur la météo moyenne de la zone, car l'effort iNat n'est connu qu'à cette échelle.
6. ~~Couche habitat.~~ Fait (`habitat/vecteurs.py`, `habitat/grille.py`, `model/habitat.py`, `model/prediction.py`). Validation par blocs de 20 km (5 plis), AUC hors bloc :

   | Cible | Saison + source | + altitude | + habitat |
   |---|---|---|---|
   | Coulemelle | 0,77 | 0,80 | 0,83 |
   | Bolets des feuillus | 0,70 | 0,71 | 0,72 |
   | Bolets des pins | 0,65 | 0,71 | 0,78 |

   Effets principaux, quand le milieu passe de 0 à 50 % de la maille :
   - pins → bolets des pins × 2,7 ;
   - prairies → coulemelle × 6, plus les lisières (pins, feuillus) ;
   - forêt mixte et feuillus → bolets des feuillus × 1,5 à 2.

   Le gain des bolets des feuillus est faible : l'essence seule les distingue mal des autres champignons forestiers.
7. Sortie : **site local à onglets** (`data/outputs/site/index.html`) :
   - Observations : carte, puis données ;
   - Météo : carte par maille avec choix de variable et de date sur 90 jours, puis données et écarts aux normales ;
   - Prédiction : carte à 1 km (potentiel, habitat, saison, classe météo ; avis du dernier jour météo pour les 14 jours suivants), meilleurs secteurs et validations.

Pistes suivantes :
- piste 1 (régression météo simple) ;
- effort iNat par sous-zone, pour contrôler la classe météo à l'échelle locale ;
- relevés de terrain avec absences ;
- espèces témoins comme signal récent (bolets des feuillus, × 1,5).

## Questions ouvertes

- Aucune pour l'instant.

Décisions prises :
- Bolets séparés en deux cibles : bolets des feuillus, bolets des pins.
- Coulemelle : validation en regroupant plusieurs saisons par pli ; fiabilité moindre que pour les bolets, acceptée.
- Proportions cible / fond calculées par source (iNat, GBIF), puis combinées.
- Seuil urbain : 30 % de bâti, validé.
- Prévision par analogues écartée pour l'instant (ne bat pas la phénologie) ; classe météo actuelle par seuils simples retenue (piste 2), régression simple gardée pour plus tard (piste 1).
- Habitat validé par blocs géographiques de 20 km (le « où »), la météo par années mises de côté (le « quand »).
