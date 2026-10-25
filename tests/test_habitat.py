import numpy as np
import pandas as pd

from mushroam.habitat.grille import BLOCK, blocks, cell_id, class_fractions
from mushroam.habitat.vecteurs import forest_class, soil_class
from mushroam.model.meteo_classes import classify

RULES = {"defavorable": {"pluie_30j_max": 40, "tmax_7j_min": 27, "tmin_7j_max": 3},
         "favorable": {"pluie_30j_min": 100, "jours_depuis_20mm_max": 14}}


def test_classes_de_foret():
    assert forest_class({"tfv_g11": "Forêt fermée feuillus", "essence": "Chênes sempervirents"}) == 1
    assert forest_class({"tfv_g11": "Forêt fermée feuillus", "essence": "Feuillus"}) == 2
    assert forest_class({"tfv_g11": "Forêt fermée feuillus", "essence": "Châtaignier"}) == 3
    assert forest_class({"tfv_g11": "Forêt fermée conifères", "essence": "Pin d'Alep"}) == 4
    assert forest_class({"tfv_g11": "Forêt ouverte conifères", "essence": "Douglas"}) == 5
    assert forest_class({"tfv_g11": "Forêt fermée mixte", "essence": "Mixte"}) == 6
    assert forest_class({"tfv_g11": "Lande", "essence": "NC"}) == 7
    assert forest_class({"tfv_g11": "Forêt fermée sans couvert arboré", "essence": "NR"}) == 7


def test_classes_de_sols():
    assert soil_class({"ger_nom": "RENDISOL(70%)"}) == 1
    assert soil_class({"ger_nom": "ALOCRISOL(44%)"}) == 2
    assert soil_class({"ger_nom": "FLUVIOSOL(100%)"}) == 3
    assert soil_class({"ger_nom": None}) == 0


def test_grille_un_km():
    a = np.zeros((2 * BLOCK, 2 * BLOCK), np.uint8)
    a[:BLOCK, :BLOCK // 2] = 4  # moitié de la maille nord-ouest en pins
    f = class_fractions(a, [4])[4]
    assert f.shape == (2, 2) and f[0, 0] == 0.5 and f[1, 1] == 0
    assert blocks(a).shape == (2, 2, BLOCK * BLOCK)
    assert cell_id(np.array([770500.0]), np.array([6280999.0]))[0] == "770_6280"


def test_classes_meteo():
    df = pd.DataFrame({"pluie_30j": [10, 150, 60, 60, 150], "tmax_7j": [20, 20, 20, 30, 20],
                       "tmin_7j": [10, 10, 10, 10, 1], "jours_depuis_20mm": [100, 40, 5, 5, 5]})
    assert classify(df, RULES).tolist() == ["defavorable", "favorable", "favorable", "defavorable", "defavorable"]
