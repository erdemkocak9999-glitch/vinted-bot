"""
Alertes Vinted -> Telegram (GitHub Actions : une exécution = un tour).
Version 2 : lit les pages du catalogue Vinted (l'ancienne API est fermée).
Nike + Under Armour, 13 à 15 ans, avec photo + prix + lien.
"""

import json
import os
import random
import re
import subprocess
import sys
import time
from urllib.parse import quote_plus

import requests

try:
    from curl_cffi import requests as cffi
except ImportError:
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "curl_cffi"], check=False
    )
    try:
        from curl_cffi import requests as cffi
    except ImportError:
        cffi = None

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# ---------- RÉGLAGES ----------
PRIX_MAX = 20.0
BONNE_AFFAIRE = 8.0
MARQUES_OK = ["nike", "under armour"]
TAILLES_ANS = ["13", "14", "15"]
TAILLES_CM = ["158", "164", "170"]
RECHERCHES = [
    "nike running", "nike dri-fit", "nike jogging", "nike legging",
    "nike tech fleece", "nike short", "nike t-shirt sport",
    "under armour running", "under armour heatgear", "under armour jogging",
    "under armour legging", "under armour sweat",
]
# ------------------------------

BASE = "https://www.vinted.fr"
FICHIER_VUS = "seen.json"
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9",
}

if cffi is not None:
    session = cffi.Session(impersonate="chrome")
else:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        )
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
    return any(re.search(rf"\b{n}\b", t) for n in TAILLES_ANS + TAILLES_CM)


def correspond(item):
    marque = (item.get("brand_title") or "").lower()
    prix = prix_en_float(item)
    if prix is None or prix > PRIX_MAX:
        return False
    if not any(m in marque for m in MARQUES_OK):
        return False
    return taille_ok(item.get("size_title"))


def texte_charge_utile(html):
    """Rassemble le HTML brut + le contenu décodé des scripts Next.js."""
    morceaux = [html]
    for m in re.finditer(r'self\.__next_f\.push\(\[\d+,\s*("(?:[^"\\]|\\.)*")\s*\]\)', html):
        try:
            morceaux.append(json.loads(m.group(1)))
        except Exception:
            pass
    return "\n".join(morceaux)


def extraire_items(html):
    texte = texte_charge_utile(html)
    dec = json.JSONDecoder()
    trouves = {}
    for m in re.finditer(r'"brand_title"\s*:', texte):
        pos = m.start()
        debut_min = max(0, pos - 8000)
        i = texte.rfind("{", debut_min, pos)
        essais = 0
        while i != -1 and i >= debut_min and essais < 40:
            essais += 1
            try:
                obj, fin = dec.raw_decode(texte, i)
                if (
                    isinstance(obj, dict)
                    and fin > pos
                    and "id" in obj
                    and "title" in obj
                    and "brand_title" in obj
                ):
                    trouves[obj["id"]] = obj
                    break
            except Exception:
                pass
            i = texte.rfind("{", debut_min, i)
    return list(trouves.values())


def chercher(texte):
    url = (
        f"{BASE}/catalog?search_text={quote_plus(texte)}"
        f"&order=newest_first&price_to={PRIX_MAX}&currency=EUR"
    )
    r = session.get(url, headers=HEADERS, timeout=25)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    items = extraire_items(r.text)
    if not items:
        print(f"  (aucune annonce lue, page de {len(r.text)} caractères)")
        print("  début de la page :", r.text[:200].replace("\n", " "))
    return items


def url_photo(item):
    p = item.get("photo")
    if isinstance(p, dict) and p.get("url"):
        return p["url"]
    ps = item.get("photos")
    if isinstance(ps, list) and ps and isinstance(ps[0], dict):
        return ps[0].get("url")
    return None


def lien(item):
    u = item.get("url")
    if u:
        return u if u.startswith("http") else BASE + u
    if item.get("path"):
        return BASE + item["path"]
    return f"{BASE}/items/{item['id']}"


def legende(item):
    prix = prix_en_float(item)
    badge = "🚨 BONNE AFFAIRE\n" if prix <= BONNE_AFFAIRE else ""
    return (
        f"{badge}🔥 {item.get('title')}\n"
        f"💶 {prix:.2f} €\n"
        f"🏷 {item.get('brand_title')} — taille {item.get('size_title')}\n"
        f"👕 État : {item.get('status') or 'non précisé'}\n"
        f"{lien(item)}"
    )[:1000]


def envoyer_telegram(item):
    texte = legende(item)
    photo = url_photo(item)
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
    vus = set()
    if os.path.exists(FICHIER_VUS):
        with open(FICHIER_VUS) as f:
            vus = set(json.load(f))
    premier_tour = len(vus) == 0

    try:
        session.get(BASE, headers=HEADERS, timeout=25)
    except Exception as e:
        print("Erreur page d'accueil :", e)

    trouvees = {}
    reussies = 0
    for q in RECHERCHES:
        try:
            items = chercher(q)
        except Exception as e:
            print(f"Erreur sur '{q}': {e}")
            continue
        reussies += 1
        print(f"'{q}' : {len(items)} annonces lues")
        for it in items:
            if it["id"] in vus:
                continue
            vus.add(it["id"])
            if not premier_tour and correspond(it):
                trouvees[it["id"]] = it
        time.sleep(random.uniform(1.5, 3))

    a_envoyer = sorted(trouvees.values(), key=lambda i: prix_en_float(i) or 999)
    for it in a_envoyer[:15]:
        envoyer_telegram(it)
        print("Alerte :", it.get("title"), prix_en_float(it))
        time.sleep(1)

    if reussies:
        with open(FICHIER_VUS, "w") as f:
            json.dump(sorted(vus)[-4000:], f)
    else:
        print("Aucune recherche n'a marché : Vinted bloque probablement GitHub.")

    if premier_tour and reussies:
        print("Premier tour : annonces existantes mémorisées, aucune alerte.")


if __name__ == "__main__":
    main()
