import pytest

from app.parse import ean_aus_article_id, finde_ean, grundpreis, gtin_gueltig, parse_groesse, parse_naehrwerte


@pytest.mark.parametrize("text, erwartet", [
    ("250g (1 kg = 19,96 €)", (250, "g")),
    ("1kg", (1000, "g")),
    ("1 kg", (1000, "g")),
    ("0,75l (1 l = 2,65 €)", (750, "ml")),
    ("6 x 1,5 l", (9000, "ml")),
    ("6x1,5l", (9000, "ml")),
    ("4 x 125g", (500, "g")),
    ("33cl", (330, "ml")),
    ("10 Stück", (10, "Stück")),
    ("10er", (10, "Stück")),
    ("1 Stk.", (1, "Stück")),
])
def test_groesse(text, erwartet):
    assert parse_groesse(text) == erwartet


def test_groesse_unbekannt():
    assert parse_groesse("ca. Bund") == (None, None)
    assert parse_groesse("") == (None, None)


def test_naehrwerte_pro_100_statt_portion():
    # REWE liefert oft zwei Tabellen ohne preparationState: pro 100 g und pro Portion
    portion = {"servingSize": {"value": 10.0, "uomShortText": "g"}, "nutrientInformation": [
        {"nutrientType": "Energie", "quantityContained": {"value": 59.0, "uomShortText": "kcal"}}]}
    je100 = {"servingSize": {"value": 100.0, "uomShortText": "g"}, "nutrientInformation": [
        {"nutrientType": "Energie", "quantityContained": {"value": 589.0, "uomShortText": "kcal"}},
        {"nutrientType": "Fett", "quantityContained": {"value": 65.0, "uomShortText": "g"}},
        {"nutrientType": "Fett, davon gesättigte Fettsäuren", "quantityContained": {"value": 35.6, "uomShortText": "g"}},
        {"nutrientType": "Kohlenhydrate, davon Zucker", "quantityContained": {"value": 0.5, "uomShortText": "g"}},
        {"nutrientType": "Ballaststoffe", "quantityContained": {"value": 0.1, "uomShortText": "g"}},
        {"nutrientType": "Salz", "quantityContained": {"value": 0.02, "uomShortText": "g"}}]}
    assert parse_naehrwerte([portion, je100]) == {"kcal": 589, "fett": 65, "zucker": 0.5, "ballaststoffe": 0.1, "salz": 0.02}


def test_grundpreis():
    assert grundpreis(4.99, 250, "g") == 19.96
    assert grundpreis(1.99, 750, "ml") == 2.65
    assert grundpreis(2.49, 10, "Stück") is None
    assert grundpreis(2.19, 400, "g") == 5.48  # wie im REWE-Shop angezeigt


FAKTEN = [{
    "preparationState": "Unzubereitet",
    "nutrientInformation": [
        {"nutrientType": "Energie", "quantityContained": {"value": 2440.0, "uomShortText": "kJ"}},
        {"nutrientType": "Energie", "quantityContained": {"value": 589.0, "uomShortText": "kcal"}},
        {"nutrientType": "Fett", "quantityContained": {"value": 46.0, "uomShortText": "g"}},
        {"nutrientType": "Fett, davon gesättigte Fettsäuren", "quantityContained": {"value": 5.9, "uomShortText": "g"}},
        {"nutrientType": "Kohlenhydrate", "quantityContained": {"value": 15.0, "uomShortText": "g"}},
        {"nutrientType": "Kohlenhydrate, davon Zucker", "quantityContained": {"value": 5.0, "uomShortText": "g"}},
        {"nutrientType": "Eiweiß", "quantityContained": {"value": 25.0, "uomShortText": "g"}},
    ],
    "servingSize": {"value": 100.0, "uomShortText": "g"},
}]


def test_naehrwerte_aus_rewe_mitschnitt():
    assert parse_naehrwerte(FAKTEN) == {"kcal": 589.0, "fett": 46.0, "kh": 15.0, "zucker": 5.0, "protein": 25.0}


def test_naehrwerte_nur_kj_und_andere_bezugsgroesse():
    facts = [{"preparationState": "Unzubereitet", "servingSize": {"value": 50, "uomShortText": "g"},
              "nutrientInformation": [{"nutrientType": "Energie", "quantityContained": {"value": 418.4, "uomShortText": "kJ"}},
                                      {"nutrientType": "Eiweiß", "quantityContained": {"value": 5, "uomShortText": "g"}}]}]
    assert parse_naehrwerte(facts) == {"kcal": 200.0, "protein": 10.0}


def test_naehrwerte_leer():
    assert parse_naehrwerte(None) is None
    assert parse_naehrwerte([]) is None


def test_ean():
    assert finde_ean({"data": {"product": [{"productId": "7535400", "gtin": "4008400401621"}]}}) == "4008400401621"
    assert finde_ean({"productId": "7535400", "nan": "7772669"}) is None


def test_ean_aus_article_id():
    # echte articleIds aus Markt 1940430 (per Open Food Facts bestätigt)
    assert ean_aus_article_id("4016241030603") == "4016241030603"  # Arla Skyr Natur 450 g
    assert ean_aus_article_id("5411188128588") == "5411188128588"  # Alpro Skyr-Style 400 g
    assert ean_aus_article_id("4H27HYFW") is None
    assert ean_aus_article_id("4016241030604") is None  # falsche Prüfziffer
    assert ean_aus_article_id(None) is None
    assert gtin_gueltig("96385074")  # EAN-8
