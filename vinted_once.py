"""
Alertes Vinted -> Telegram (GitHub Actions : une exécution = un tour).
Nike + Under Armour, running, 13 à 15 ans, avec photo + prix + lien.
Les identifiants viennent des Secrets GitHub (rien à écrire ici).
"""

import json
import os
import random
import re
import time

import requests

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# ---------- RÉGLAGES ----------
PRIX_MAX = 20.0        # prix maximum en euros
BONNE_AFFAIRE = 8.0    # en dessous, l'alerte est marquée 🚨
MARQUES_OK = ["nike", "under armour"]
TAILLES_ANS = ["13", "14", "15"]
TAILLES_CM = ["158", "164", "170"]
RECHERCHES = [
    "nike running", "nike dri-fit", "nike jogging", "nike legging",
    "nike tech fleece", "nike air max", "nike pegasus", "nike short",
    "nike t-shirt sport", "nike survêtement",
    "under armour running", "under armour heatgear", "under armour jogging",
    "under armour legging", "under armour short", "under armour t-shirt",
    "under armour sweat",
]
# ------------------------------

BASE = "https://www.vinted.fr"
API = f"{BASE}/api/v2/catalog/items"
FICHIER_VUS = "seen.json"

session = requests.Session()
session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9",
})


def prix_en_float(item):
    p = item.get("price")
    if isinstance(p, dict):
        p = p.get("amount")
    try:
        return float(p)
    except (TypeError, ValueError):
        return None


def taille_ok(taille):
    t = (taille or "").lower()
    for n in TAILLES_ANS:
        if re.search(rf"\b{n}\b", t):
            return True
    for n in TAILLES_CM:
        if re.search(rf"\b{n}\b", t):
            return True
    return False


def correspond(item):
    marque = (item.get("brand_title") or "").lower()
    prix = prix_en_float(item)
    if prix is None or prix > PRIX_MAX:
        return False
    if not any(m in marque for m in MARQUES_OK):
        return False
    return taille_ok(item.get("size_title"))


def chercher(texte):
    params = {
        "search_text": texte,
        "price_to": PRIX_MAX,
        "order": "newest_first",
        "per_page": 30,
        "page": 1,
    }
    r = session.get(API, params=params, timeout=15)
    if r.status_code in (401, 403):
        session.cookies.clear()
        session.get(BASE, timeout=15)
        r = session.get(API, params=params, timeout=15)
    r.raise_for_status()
    return r.json().get("items", [])


def legende(item):
    prix = prix_en_float(item)
    url = item.get("url") or f"{BASE}/items/{item['id']}"
    badge = "🚨 BONNE AFFAIRE\n" if prix <= BONNE_AFFAIRE else ""
    return (
        f"{badge}🔥 {item.get('title')}\n"
        f"💶 {prix:.2f} €\n"
        f"🏷 {item.get('brand_title')} — taille {item.get('size_title')}\n"
        f"👕 État : {item.get('status') or 'non précisé'}\n"
        f"{url}"
    )[:1000]


def envoyer_telegram(item):
    texte = legende(item)
    photo = (item.get("photo") or {}).get("url")
    api = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
    if photo:
        r = requests.post(
            f"{api}/sendPhoto",
            data={"chat_id": TELEGRAM_CHAT_ID, "photo": photo, "caption": texte},
            timeout=20,
        )
        if r.ok:
            return
    requests.post(
        f"{api}/sendMessage",
        data={"chat_id": TELEGRAM_CHAT_ID, "text": texte},
        timeout=20,
    )


def main():
    premier_tour = not os.path.exists(FICHIER_VUS)
    vus = set()
    if not premier_tour:
        with open(FICHIER_VUS) as f:
            vus = set(json.load(f))

    session.get(BASE, timeout=15)

    trouvees = {}
    for q in RECHERCHES:
        try:
            items = chercher(q)
        except Exception as e:
            print(f"Erreur sur '{q}': {e}")
            continue
        for it in items:
            if it["id"] in vus:
                continue
            vus.add(it["id"])
            if not premier_tour and correspond(it):
                trouvees[it["id"]] = it
        time.sleep(random.uniform(1, 2.5))

    a_envoyer = sorted(trouvees.values(), key=lambda i: prix_en_float(i) or 999)
    for it in a_envoyer[:15]:
        envoyer_telegram(it)
        print("Alerte :", it.get("title"), prix_en_float(it))
        time.sleep(1)

    with open(FICHIER_VUS, "w") as f:
        json.dump(sorted(vus)[-4000:], f)

    if premier_tour:
        print("Premier tour : annonces existantes mémorisées, aucune alerte.")


if __name__ == "__main__":
    main()
