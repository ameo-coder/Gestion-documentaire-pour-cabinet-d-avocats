from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import json
import os
import uuid
from datetime import datetime
import mimetypes
from pathlib import Path
import shutil
from elasticsearch import Elasticsearch
import logging
from werkzeug.utils import secure_filename
import re
import subprocess

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

CONFIG = {
    "dossier_donnees": "donnees_cabinet",
    "dossier_index": "index_fichiers",
    "dossiers_a_indexer": [],
    "extensions_autorisees": {'.pdf', '.doc', '.docx', '.txt', '.rtf', '.odt', '.xls', '.xlsx', '.ppt', '.pptx', '.png', '.jpg', '.jpeg', '.tiff', '.bmp'},
    "elasticsearch_host": "localhost:9200",
    "index_name": "documents_cabinet",
    "specialites_juridiques": [
        "Droit civil", "Droit pénal", "Droit commercial", "Droit du travail",
        "Droit de la famille", "Droit immobilier", "Droit administratif",
        "Droit fiscal", "Droit des sociétés", "Droit de la propriété intellectuelle",
        "Droit international", "Droit européen", "Droit des assurances",
        "Droit rural", "Droit de la santé", "Droit de l'environnement"
    ]
}

try:
    es = Elasticsearch([CONFIG["elasticsearch_host"]])
    if not es.ping():
        raise Exception("Elasticsearch non disponible")
    logger.info("Connecté à Elasticsearch")
except Exception as e:
    logger.warning(f"Elasticsearch non disponible: {e}")
    es = None

def configurer_tesseract_auto():
    OCR_DISPONIBLE = False
    tesseract_path = None
    message = "Non configuré"
    
    try:
        import pytesseract
        from PIL import Image
        
        common_paths = [
            r'C:\Program Files\Tesseract-OCR\tesseract.exe',
            r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
            r'C:\Users\{}\AppData\Local\Tesseract-OCR\tesseract.exe'.format(os.getenv('USERNAME')),
        ]
        
        for path in common_paths:
            if os.path.exists(path):
                try:
                    pytesseract.pytesseract.tesseract_cmd = path
                    version = pytesseract.get_tesseract_version()
                    OCR_DISPONIBLE = True
                    tesseract_path = path
                    message = f"Activé ({path})"
                    break
                except Exception:
                    continue
        
        if not OCR_DISPONIBLE:
            try:
                result = subprocess.run(['where', 'tesseract'], capture_output=True, text=True, timeout=10)
                if result.returncode == 0 and result.stdout.strip():
                    path = result.stdout.strip().split('\n')[0]
                    pytesseract.pytesseract.tesseract_cmd = path
                    version = pytesseract.get_tesseract_version()
                    OCR_DISPONIBLE = True
                    tesseract_path = path
                    message = f"Activé (PATH: {path})"
            except Exception:
                pass
                
    except ImportError:
        message = "Bibliothèques non installées"
    
    return OCR_DISPONIBLE, tesseract_path, message

OCR_DISPONIBLE, TESSERACT_PATH, OCR_MESSAGE = configurer_tesseract_auto()

if OCR_DISPONIBLE:
    import pytesseract
    from PIL import Image
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
    logger.info(f"OCR Tesseract configuré: {TESSERACT_PATH}")

try:
    import PyPDF2
    PYPDF2_DISPONIBLE = True
except ImportError:
    PYPDF2_DISPONIBLE = False

try:
    from pdf2image import convert_from_path
    PDF2IMAGE_DISPONIBLE = True
except ImportError:
    PDF2IMAGE_DISPONIBLE = False

for dossier in [CONFIG["dossier_donnees"], CONFIG["dossier_index"]]:
    os.makedirs(dossier, exist_ok=True)

FICHIER_INDEX = os.path.join(CONFIG["dossier_index"], "index.json")
FICHIER_STATS = os.path.join(CONFIG["dossier_index"], "statistiques.json")
FICHIER_SPECIALITES = os.path.join(CONFIG["dossier_index"], "specialites.json")
FICHIER_AVOCATS = os.path.join(CONFIG["dossier_index"], "avocats.json")

def charger_donnees(fichier):
    try:
        with open(fichier, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

def sauvegarder_donnees(fichier, donnees):
    with open(fichier, 'w', encoding='utf-8') as f:
        json.dump(donnees, f, ensure_ascii=False, indent=2)

def extraire_texte_pdf(chemin_fichier):
    if not PYPDF2_DISPONIBLE:
        return "[PyPDF2 non disponible]"
    
    try:
        texte = ""
        with open(chemin_fichier, 'rb') as fichier:
            lecteur_pdf = PyPDF2.PdfReader(fichier)
            for page_num, page in enumerate(lecteur_pdf.pages):
                try:
                    texte_page = page.extract_text()
                    if texte_page and texte_page.strip():
                        texte += f"--- Page {page_num + 1} ---\n{texte_page}\n\n"
                except Exception as e:
                    continue
        return texte.strip()
    except Exception as e:
        return f"[Erreur PDF: {str(e)}]"

def extraire_texte_simple(chemin_fichier):
    try:
        texte = ""
        extension = os.path.splitext(chemin_fichier)[1].lower()
        
        if extension == '.pdf':
            texte = extraire_texte_pdf(chemin_fichier)
        
        elif extension == '.txt':
            try:
                with open(chemin_fichier, 'r', encoding='utf-8') as f:
                    texte = f.read()
            except UnicodeDecodeError:
                with open(chemin_fichier, 'r', encoding='latin-1') as f:
                    texte = f.read()
        
        elif extension == '.docx':
            try:
                import docx
                doc = docx.Document(chemin_fichier)
                for paragraph in doc.paragraphs:
                    if paragraph.text.strip():
                        texte += paragraph.text + "\n"
            except ImportError:
                texte = "[Document Word - python-docx non installé]"
        
        return texte.strip() if texte else "[Aucun contenu textuel extrait]"
    
    except Exception as e:
        return f"[Erreur extraction: {str(e)}]"

def extraire_texte_ocr(chemin_fichier):
    if not OCR_DISPONIBLE:
        return extraire_texte_simple(chemin_fichier)
    
    try:
        texte = ""
        extension = os.path.splitext(chemin_fichier)[1].lower()
        
        if extension == '.pdf':
            texte = extraire_texte_pdf(chemin_fichier)
            
            if not texte or len(texte.strip()) < 100:
                if PDF2IMAGE_DISPONIBLE:
                    try:
                        images = convert_from_path(chemin_fichier, dpi=200)
                        texte_ocr = ""
                        for i, image in enumerate(images):
                            texte_page = pytesseract.image_to_string(image, lang='fra+eng')
                            texte_ocr += f"--- Page {i+1} (OCR) ---\n{texte_page}\n\n"
                        
                        if texte_ocr.strip():
                            texte = texte_ocr
                    except Exception as e:
                        if not texte:
                            texte = f"[OCR échoué: {str(e)}]"
        
        elif extension in ['.png', '.jpg', '.jpeg', '.tiff', '.bmp']:
            try:
                image = Image.open(chemin_fichier)
                texte = pytesseract.image_to_string(image, lang='fra+eng')
                if not texte.strip():
                    texte = "[OCR n'a pu extraire de texte]"
            except Exception as e:
                texte = f"[Erreur OCR: {str(e)}]"
        
        else:
            texte = extraire_texte_simple(chemin_fichier)
        
        return texte.strip() if texte else "[Aucun contenu textuel détecté]"
    
    except Exception as e:
        return extraire_texte_simple(chemin_fichier)

def recherche_flexible(terme):
    logger.info(f"Recherche flexible pour: '{terme}'")
    
    return {
        "multi_match": {
            "query": terme,
            "fields": [
                "nom^4",
                "contenu_textuel^2",
                "mots_cles^3",
                "specialite^2",
                "avocat^2",
                "categorie^2"
            ],
            "fuzziness": "AUTO",
            "operator": "and"
        }
    }

def analyser_requete_avancee(terme):
    if not terme or not terme.strip():
        return {"match_all": {}}
    
    terme = terme.strip()
    logger.info(f"Analyse requête: '{terme}'")
    
    has_advanced_operators = any(op in terme for op in [':', '"', '-']) or ' OR ' in terme.upper() or ' AND ' in terme.upper()
    
    if not has_advanced_operators:
        logger.info("Utilisation recherche flexible")
        return recherche_flexible(terme)
    
    logger.info("Utilisation recherche avancée")
    query = {"bool": {"must": [], "should": [], "must_not": [], "filter": []}}
    
    champ_pattern = r'(\w+):"([^"]+)"|(\w+):(\S+)'
    champs_trouves = re.findall(champ_pattern, terme)
    
    terme_restant = terme
    for champ in champs_trouves:
        champ_nom = champ[0] or champ[2]
        champ_valeur = champ[1] or champ[3]
        
        terme_restant = terme_restant.replace(f'{champ_nom}:"{champ_valeur}"', '').replace(f'{champ_nom}:{champ_valeur}', '').strip()
        
        mapping_champs = {
            'titre': 'nom', 'nom': 'nom',
            'contenu': 'contenu_textuel', 'texte': 'contenu_textuel',
            'avocat': 'avocat', 'specialite': 'specialite',
            'categorie': 'categorie', 'categ': 'categorie',
            'motcle': 'mots_cles', 'tag': 'mots_cles'
        }
        
        champ_es = mapping_champs.get(champ_nom.lower(), champ_nom.lower())
        
        query["bool"]["must"].append({
            "match_phrase" if ' ' in champ_valeur else "match": {
                champ_es: champ_valeur
            }
        })
    
    if terme_restant.strip():
        has_remaining_operators = any(op in terme_restant for op in ['"', '-']) or ' OR ' in terme_restant.upper() or ' AND ' in terme_restant.upper()
        
        if not has_remaining_operators:
            query["bool"]["must"].append(recherche_flexible(terme_restant))
        else:
            parties_or = [part.strip() for part in terme_restant.split(' OR ') if part.strip()]
            
            for partie in parties_or:
                termes_positifs = []
                termes_negatifs = []
                
                phrases_exactes = re.findall(r'"([^"]*)"', partie)
                for phrase in phrases_exactes:
                    termes_positifs.append(f'"{phrase}"')
                    partie = partie.replace(f'"{phrase}"', '')
                
                mots = partie.split()
                for mot in mots:
                    if mot.startswith('-') and len(mot) > 1:
                        termes_negatifs.append(mot[1:])
                    elif mot not in ['OR', 'AND', '']:
                        termes_positifs.append(mot)
                
                if termes_positifs:
                    for terme_pos in termes_positifs:
                        if terme_pos.startswith('"') and terme_pos.endswith('"'):
                            phrase = terme_pos[1:-1]
                            query["bool"]["must"].append({
                                "multi_match": {
                                    "query": phrase,
                                    "fields": ["nom^3", "contenu_textuel^2", "mots_cles^2", "specialite", "avocat", "categorie"],
                                    "type": "phrase"
                                }
                            })
                        else:
                            query["bool"]["must"].append({
                                "multi_match": {
                                    "query": terme_pos,
                                    "fields": ["nom^3", "contenu_textuel^2", "mots_cles^2", "specialite", "avocat", "categorie"],
                                    "fuzziness": "AUTO"
                                }
                            })
                
                for terme_neg in termes_negatifs:
                    query["bool"]["must_not"].append({
                        "multi_match": {
                            "query": terme_neg,
                            "fields": ["nom", "contenu_textuel", "mots_cles", "specialite", "avocat", "categorie"]
                        }
                    })
    
    if not query["bool"]["must"] and not query["bool"]["must_not"] and not query["bool"]["should"]:
        query["bool"]["must"].append({"match_all": {}})
    
    return query

def rechercher_dans_elasticsearch(terme, specialite=None, avocat=None, categorie=None):
    if not es:
        return []
    
    try:
        query = analyser_requete_avancee(terme)
        
        filtres = []
        if specialite:
            filtres.append({"term": {"specialite": specialite}})
        if avocat:
            filtres.append({"term": {"avocat": avocat}})
        if categorie:
            filtres.append({"term": {"categorie": categorie}})
        
        if filtres:
            query["bool"]["filter"] = filtres
        
        resultat = es.search(index=CONFIG["index_name"], body={
            "query": query,
            "highlight": {
                "pre_tags": ["<mark>"],
                "post_tags": ["</mark>"],
                "fields": {
                    "nom": {"number_of_fragments": 2, "fragment_size": 100},
                    "contenu_textuel": {"number_of_fragments": 3, "fragment_size": 150},
                    "mots_cles": {"number_of_fragments": 1, "fragment_size": 50},
                    "specialite": {},
                    "avocat": {},
                    "categorie": {}
                }
            },
            "size": 100
        })
        
        logger.info(f"Résultats Elasticsearch: {len(resultat['hits']['hits'])} documents")
        return resultat['hits']['hits']
    except Exception as e:
        logger.error(f"Erreur recherche Elasticsearch: {e}")
        return []

def indexer_dans_elasticsearch(fichier_info):
    if not es:
        return
    
    try:
        doc = {
            'id': fichier_info['id'],
            'nom': fichier_info['nom'],
            'chemin': fichier_info['chemin'],
            'dossier': fichier_info['dossier'],
            'extension': fichier_info['extension'],
            'taille': fichier_info['taille'],
            'date_modification': fichier_info['date_modification'],
            'date_indexation': fichier_info['date_indexation'],
            'type_mime': fichier_info['type_mime'],
            'mots_cles': fichier_info['mots_cles'],
            'categorie': fichier_info['categorie'],
            'specialite': fichier_info.get('specialite', 'Non spécifiée'),
            'avocat': fichier_info.get('avocat', 'Non attribué'),
            'statut': fichier_info['statut'],
            'contenu_textuel': fichier_info.get('contenu_textuel', ''),
            'type_fichier': fichier_info.get('type_fichier', 'standard')
        }
        
        es.index(index=CONFIG["index_name"], id=fichier_info['id'], body=doc)
    except Exception as e:
        logger.error(f"Erreur indexation Elasticsearch: {e}")

def indexer_fichiers(chemin_dossier, specialite="Non spécifiée", avocat="Non attribué"):
    index = []
    total_fichiers = 0
    
    for root, dirs, files in os.walk(chemin_dossier):
        for file in files:
            chemin_complet = os.path.join(root, file)
            extension = os.path.splitext(file)[1].lower()
            
            if extension in CONFIG["extensions_autorisees"]:
                try:
                    stat = os.stat(chemin_complet)
                    
                    contenu_textuel = ""
                    type_fichier = "standard"
                    
                    contenu_textuel = extraire_texte_ocr(chemin_complet)
                    
                    if contenu_textuel and not contenu_textuel.startswith("["):
                        if OCR_DISPONIBLE and extension in ['.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.bmp']:
                            type_fichier = "OCR"
                        else:
                            type_fichier = "texte"
                    
                    fichier_info = {
                        "id": str(uuid.uuid4())[:8],
                        "nom": file,
                        "chemin": chemin_complet,
                        "dossier": root,
                        "extension": extension,
                        "taille": stat.st_size,
                        "date_modification": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "date_indexation": datetime.now().isoformat(),
                        "type_mime": mimetypes.guess_type(file)[0] or "inconnu",
                        "mots_cles": extraire_mots_cles(chemin_complet, file),
                        "categorie": deviner_categorie(root, file),
                        "specialite": specialite,
                        "avocat": avocat,
                        "statut": "indexé",
                        "contenu_textuel": contenu_textuel,
                        "type_fichier": type_fichier
                    }
                    index.append(fichier_info)
                    total_fichiers += 1
                    
                    indexer_dans_elasticsearch(fichier_info)
                    
                except Exception as e:
                    logger.error(f"Erreur indexation {chemin_complet}: {e}")
    
    return index, total_fichiers

def extraire_mots_cles(chemin, nom_fichier):
    texte = f"{chemin} {nom_fichier}".lower()
    mots = set()
    
    mots_ignorer = {'dossier', 'fichier', 'document', 'pdf', 'doc', 'docx', 'txt', 'rtf', 'odt', 'png', 'jpg', 'jpeg'}
    
    for mot in texte.split():
        mot_clean = ''.join(c for c in mot if c.isalnum())
        if mot_clean and len(mot_clean) > 2 and mot_clean not in mots_ignorer:
            mots.add(mot_clean)
    
    return list(mots)

def deviner_categorie(chemin, nom_fichier):
    chemin_lower = chemin.lower()
    nom_lower = nom_fichier.lower()
    
    if any(mot in chemin_lower for mot in ['contrat', 'agreement', 'convention']):
        return "Contrats"
    elif any(mot in chemin_lower for mot in ['facture', 'invoice', 'paiement']):
        return "Factures"
    elif any(mot in chemin_lower for mot in ['courrier', 'mail', 'email', 'lettre']):
        return "Correspondance"
    elif any(mot in chemin_lower for mot in ['jugement', 'tribunal', 'audience']):
        return "Décisions"
    elif any(mot in nom_lower for mot in ['contrat', 'agreement']):
        return "Contrats"
    elif any(mot in nom_lower for mot in ['facture', 'invoice']):
        return "Factures"
    else:
        return "Divers"

def charger_specialites():
    try:
        with open(FICHIER_SPECIALITES, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return CONFIG["specialites_juridiques"]

def sauvegarder_specialites(specialites):
    with open(FICHIER_SPECIALITES, 'w', encoding='utf-8') as f:
        json.dump(specialites, f, ensure_ascii=False, indent=2)

def charger_avocats():
    try:
        with open(FICHIER_AVOCATS, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return ["Maître Dupont", "Maître Martin", "Maître Dubois"]

def sauvegarder_avocats(avocats):
    with open(FICHIER_AVOCATS, 'w', encoding='utf-8') as f:
        json.dump(avocats, f, ensure_ascii=False, indent=2)

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/api/status')
def status():
    return jsonify({
        "message": "Système d'indexation de fichiers locaux avec Elasticsearch",
        "statut": "online",
        "elasticsearch": "connecté" if es else "non disponible",
        "ocr": OCR_MESSAGE,
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/specialites', methods=['GET'])
def get_specialites():
    specialites = charger_specialites()
    return jsonify({"specialites": specialites})

@app.route('/api/specialites', methods=['POST'])
def ajouter_specialite():
    try:
        if not request.is_json:
            return jsonify({"success": False, "erreur": "Content-Type must be application/json"}), 400
            
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "erreur": "Données JSON manquantes"}), 400
            
        nouvelle_specialite = data.get('specialite', '').strip()
        
        if not nouvelle_specialite:
            return jsonify({"success": False, "erreur": "Spécialité vide"}), 400
        
        specialites = charger_specialites()
        if nouvelle_specialite not in specialites:
            specialites.append(nouvelle_specialite)
            sauvegarder_specialites(specialites)
        
        return jsonify({"success": True, "specialites": specialites})
    except Exception as e:
        logger.error(f"Erreur ajout spécialité: {e}")
        return jsonify({"success": False, "erreur": str(e)}), 500

@app.route('/api/specialites/<ancien_nom>', methods=['PUT'])
def modifier_specialite(ancien_nom):
    try:
        if not request.is_json:
            return jsonify({"success": False, "erreur": "Content-Type must be application/json"}), 400
            
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "erreur": "Données JSON manquantes"}), 400
            
        nouveau_nom = data.get('nouveau_nom', '').strip()
        
        if not nouveau_nom:
            return jsonify({"success": False, "erreur": "Nouveau nom vide"}), 400
        
        specialites = charger_specialites()
        if ancien_nom in specialites:
            index = specialites.index(ancien_nom)
            specialites[index] = nouveau_nom
            
            index_documents = charger_donnees(FICHIER_INDEX)
            for doc in index_documents:
                if doc.get('specialite') == ancien_nom:
                    doc['specialite'] = nouveau_nom
            
            sauvegarder_donnees(FICHIER_INDEX, index_documents)
            sauvegarder_specialites(specialites)
            
            return jsonify({
                "success": True, 
                "specialites": specialites, 
                "message": f"Spécialité modifiée: {ancien_nom} → {nouveau_nom}"
            })
        else:
            return jsonify({"success": False, "erreur": "Spécialité non trouvée"}), 404
            
    except Exception as e:
        logger.error(f"Erreur modification spécialité: {e}")
        return jsonify({"success": False, "erreur": str(e)}), 500

@app.route('/api/specialites', methods=['DELETE'])
def supprimer_specialite():
    try:
        if not request.is_json:
            return jsonify({"success": False, "erreur": "Content-Type must be application/json"}), 400
            
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "erreur": "Données JSON manquantes"}), 400
            
        specialite = data.get('specialite', '').strip()
        
        if not specialite:
            return jsonify({"success": False, "erreur": "Spécialité vide"}), 400
        
        specialites = charger_specialites()
        if specialite in specialites:
            index_documents = charger_donnees(FICHIER_INDEX)
            documents_associes = [doc for doc in index_documents if doc.get('specialite') == specialite]
            count_documents = len(documents_associes)
            
            if count_documents > 0:
                return jsonify({
                    "success": False, 
                    "erreur": f"Impossible de supprimer: {count_documents} document(s) associé(s)",
                    "count": count_documents
                }), 400
            
            specialites.remove(specialite)
            sauvegarder_specialites(specialites)
            return jsonify({"success": True, "specialites": specialites, "message": "Spécialité supprimée avec succès"})
        else:
            return jsonify({"success": False, "erreur": "Spécialité non trouvée"}), 404
            
    except Exception as e:
        logger.error(f"Erreur suppression spécialité: {e}")
        return jsonify({"success": False, "erreur": str(e)}), 500

@app.route('/api/avocats', methods=['GET'])
def get_avocats():
    avocats = charger_avocats()
    return jsonify({"avocats": avocats})

@app.route('/api/avocats', methods=['POST'])
def ajouter_avocat():
    try:
        if not request.is_json:
            return jsonify({"success": False, "erreur": "Content-Type must be application/json"}), 400
            
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "erreur": "Données JSON manquantes"}), 400
            
        nouvel_avocat = data.get('nom', '').strip()
        
        if not nouvel_avocat:
            return jsonify({"success": False, "erreur": "Nom d'avocat vide"}), 400
        
        avocats = charger_avocats()
        if nouvel_avocat not in avocats:
            avocats.append(nouvel_avocat)
            sauvegarder_avocats(avocats)
        
        return jsonify({"success": True, "avocats": avocats, "message": "Avocat ajouté avec succès"})
    except Exception as e:
        logger.error(f"Erreur ajout avocat: {e}")
        return jsonify({"success": False, "erreur": str(e)}), 500

@app.route('/api/avocats/<nom_avocat>', methods=['PUT'])
def modifier_avocat_detail(nom_avocat):
    try:
        if not request.is_json:
            return jsonify({"success": False, "erreur": "Content-Type must be application/json"}), 400
            
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "erreur": "Données JSON manquantes"}), 400
            
        nouveau_nom = data.get('nouveau_nom', '').strip()
        
        if not nouveau_nom:
            return jsonify({"success": False, "erreur": "Nouveau nom vide"}), 400
        
        avocats = charger_avocats()
        if nom_avocat in avocats:
            index = avocats.index(nom_avocat)
            avocats[index] = nouveau_nom
            
            index_documents = charger_donnees(FICHIER_INDEX)
            for doc in index_documents:
                if doc.get('avocat') == nom_avocat:
                    doc['avocat'] = nouveau_nom
            
            sauvegarder_donnees(FICHIER_INDEX, index_documents)
            sauvegarder_avocats(avocats)
            
            return jsonify({
                "success": True, 
                "avocats": avocats, 
                "message": f"Avocat modifié: {nom_avocat} → {nouveau_nom}"
            })
        else:
            return jsonify({"success": False, "erreur": "Avocat non trouvé"}), 404
            
    except Exception as e:
        logger.error(f"Erreur modification avocat: {e}")
        return jsonify({"success": False, "erreur": str(e)}), 500

@app.route('/api/avocats/<nom_avocat>', methods=['DELETE'])
def supprimer_avocat_detail(nom_avocat):
    try:
        avocats = charger_avocats()
        if nom_avocat in avocats:
            index_documents = charger_donnees(FICHIER_INDEX)
            documents_associes = [doc for doc in index_documents if doc.get('avocat') == nom_avocat]
            count_documents = len(documents_associes)
            
            if count_documents > 0:
                return jsonify({
                    "success": False, 
                    "erreur": f"Impossible de supprimer: {count_documents} document(s) associé(s)",
                    "count": count_documents
                }), 400
            
            avocats.remove(nom_avocat)
            sauvegarder_avocats(avocats)
            
            return jsonify({
                "success": True, 
                "avocats": avocats, 
                "message": "Avocat supprimé avec succès"
            })
        else:
            return jsonify({"success": False, "erreur": "Avocat non trouvé"}), 404
            
    except Exception as e:
        logger.error(f"Erreur suppression avocat: {e}")
        return jsonify({"success": False, "erreur": str(e)}), 500

@app.route('/indexer/lancer', methods=['POST'])
def lancer_indexation():
    try:
        if not request.is_json:
            return jsonify({"success": False, "erreur": "Content-Type must be application/json"}), 400
            
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "erreur": "Données JSON manquantes"}), 400
            
        dossiers_a_indexer = data.get('dossiers', CONFIG["dossiers_a_indexer"])
        specialite = data.get('specialite', 'Non spécifiée')
        avocat = data.get('avocat', 'Non attribué')
        
        if not dossiers_a_indexer:
            return jsonify({"success": False, "erreur": "Aucun dossier configuré"}), 400
        
        index_complet = []
        statistiques = {
            "date_indexation": datetime.now().isoformat(),
            "dossiers_indexes": [],
            "total_fichiers": 0,
            "specialite": specialite,
            "avocat": avocat,
            "ocr_utilise": False,
            "ocr_disponible": OCR_DISPONIBLE
        }
        
        for dossier in dossiers_a_indexer:
            if os.path.exists(dossier):
                index_dossier, total = indexer_fichiers(dossier, specialite, avocat)
                index_complet.extend(index_dossier)
                
                ocr_utilise = any(doc.get('type_fichier') == 'OCR' for doc in index_dossier)
                if ocr_utilise:
                    statistiques["ocr_utilise"] = True
                
                statistiques["dossiers_indexes"].append({
                    "chemin": dossier,
                    "fichiers_indexes": total,
                    "specialite": specialite,
                    "avocat": avocat,
                    "ocr_utilise": ocr_utilise
                })
                statistiques["total_fichiers"] += total
        
        sauvegarder_donnees(FICHIER_INDEX, index_complet)
        sauvegarder_donnees(FICHIER_STATS, statistiques)
        
        return jsonify({
            "success": True,
            "statistiques": statistiques,
            "fichiers_indexes": len(index_complet)
        })
        
    except Exception as e:
        logger.error(f"Erreur indexation: {e}")
        return jsonify({"success": False, "erreur": str(e)}), 500

@app.route('/recherche/avancee')
def recherche_avancee():
    try:
        terme = request.args.get('q', '').strip()
        specialite = request.args.get('specialite', '')
        avocat = request.args.get('avocat', '')
        categorie = request.args.get('categorie', '')
        
        logger.info(f"Recherche: '{terme}' - Spécialité: {specialite} - Avocat: {avocat} - Catégorie: {categorie}")
        
        if es:
            resultats_es = rechercher_dans_elasticsearch(terme, specialite, avocat, categorie)
            resultats = []
            for hit in resultats_es:
                doc = hit['_source']
                doc['score'] = hit['_score']
                if 'highlight' in hit:
                    doc['highlight'] = hit['highlight']
                resultats.append(doc)
        else:
            index = charger_donnees(FICHIER_INDEX)
            resultats = []
            
            for fichier in index:
                if specialite and fichier.get('specialite') != specialite:
                    continue
                if avocat and fichier.get('avocat') != avocat:
                    continue
                if categorie and fichier.get('categorie') != categorie:
                    continue
                
                score = 0
                
                if terme:
                    termes_recherche = terme.lower().split()
                    termes_trouves = 0
                    
                    nom_lower = fichier.get('nom', '').lower()
                    for mot in termes_recherche:
                        if mot in nom_lower:
                            score += 3
                            termes_trouves += 1
                    
                    mots_cles = [mot.lower() for mot in fichier.get('mots_cles', [])]
                    for mot in termes_recherche:
                        if any(mot in mot_cle for mot_cle in mots_cles):
                            score += 2
                            termes_trouves += 1
                    
                    contenu_lower = fichier.get('contenu_textuel', '').lower()
                    for mot in termes_recherche:
                        if mot in contenu_lower:
                            score += 1
                            termes_trouves += 1
                    
                    if termes_trouves == len(termes_recherche):
                        score += 5
                    elif termes_trouves >= len(termes_recherche) / 2:
                        score += 2
                        
                    if score == 0:
                        continue
                else:
                    score = 1
                
                fichier['score'] = score
                resultats.append(fichier)
            
            resultats.sort(key=lambda x: x.get('score', 0), reverse=True)
        
        logger.info(f"{len(resultats)} résultats trouvés")
        return jsonify({
            "terme": terme,
            "resultats": resultats,
            "total": len(resultats),
            "moteur_recherche": "elasticsearch" if es else "basique"
        })
        
    except Exception as e:
        logger.error(f"Erreur recherche: {e}")
        return jsonify({"erreur": str(e)}), 500

@app.route('/api/documents')
def get_all_documents():
    try:
        index = charger_donnees(FICHIER_INDEX)
        return jsonify({"documents": index})
    except Exception as e:
        logger.error(f"Erreur chargement documents: {e}")
        return jsonify({"erreur": str(e)}), 500

@app.route('/api/document/<document_id>', methods=['PUT'])
def modifier_document(document_id):
    try:
        if not request.is_json:
            return jsonify({"success": False, "erreur": "Content-Type must be application/json"}), 400
            
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "erreur": "Données JSON manquantes"}), 400
            
        index = charger_donnees(FICHIER_INDEX)
        document = next((doc for doc in index if doc['id'] == document_id), None)
        
        if not document:
            return jsonify({"success": False, "erreur": "Document non trouvé"}), 404
        
        modifications = []
        if 'titre' in data and data['titre'] and data['titre'].strip():
            document['nom'] = data['titre'].strip()
            modifications.append("titre")
        
        if 'avocat' in data and data['avocat'] and data['avocat'].strip():
            document['avocat'] = data['avocat'].strip()
            modifications.append("avocat")
        
        if 'specialite' in data and data['specialite'] and data['specialite'].strip():
            document['specialite'] = data['specialite'].strip()
            modifications.append("spécialité")
        
        if not modifications:
            return jsonify({"success": False, "erreur": "Aucune modification fournie"}), 400
        
        document['date_modification'] = datetime.now().isoformat()
        
        sauvegarder_donnees(FICHIER_INDEX, index)
        
        if es:
            try:
                es.index(index=CONFIG["index_name"], id=document_id, body=document)
            except Exception as e:
                logger.warning(f"Erreur mise à jour Elasticsearch: {e}")
        
        return jsonify({
            "success": True, 
            "message": f"Document modifié: {', '.join(modifications)}"
        })
        
    except Exception as e:
        logger.error(f"Erreur modification document: {e}")
        return jsonify({"success": False, "erreur": str(e)}), 500

@app.route('/api/document/<document_id>', methods=['DELETE'])
def supprimer_document(document_id):
    try:
        index = charger_donnees(FICHIER_INDEX)
        document = next((doc for doc in index if doc['id'] == document_id), None)
        
        if not document:
            return jsonify({"success": False, "erreur": "Document non trouvé"}), 404
        
        try:
            if os.path.exists(document['chemin']):
                os.remove(document['chemin'])
        except Exception as e:
            logger.warning(f"Impossible de supprimer le fichier physique: {e}")
        
        index = [doc for doc in index if doc['id'] != document_id]
        sauvegarder_donnees(FICHIER_INDEX, index)
        
        if es:
            try:
                es.delete(index=CONFIG["index_name"], id=document_id)
            except Exception as e:
                logger.warning(f"Impossible de supprimer d'Elasticsearch: {e}")
        
        return jsonify({"success": True, "message": "Document supprimé avec succès"})
        
    except Exception as e:
        logger.error(f"Erreur suppression document: {e}")
        return jsonify({"success": False, "erreur": str(e)}), 500

@app.route('/api/upload', methods=['POST'])
def upload_file():
    try:
        if 'file' not in request.files:
            return jsonify({"success": False, "erreur": "Aucun fichier"}), 400
        
        file = request.files['file']
        titre = request.form.get('titre', file.filename)
        avocat = request.form.get('avocat', 'Non attribué')
        specialite = request.form.get('specialite', 'Non spécifiée')
        
        if file.filename == '':
            return jsonify({"success": False, "erreur": "Aucun fichier sélectionné"}), 400
        
        filename = secure_filename(file.filename)
        extension = os.path.splitext(filename)[1].lower()
        
        if extension not in CONFIG["extensions_autorisees"]:
            extensions_str = ', '.join(CONFIG["extensions_autorisees"])
            return jsonify({
                "success": False, 
                "erreur": f"Type de fichier non supporté. Extensions autorisées: {extensions_str}"
            }), 400
        
        filepath = os.path.join(CONFIG["dossier_donnees"], filename)
        file.save(filepath)
        
        contenu_textuel = ""
        type_fichier = "standard"
        
        contenu_textuel = extraire_texte_ocr(filepath)
        
        if contenu_textuel and not contenu_textuel.startswith("["):
            if OCR_DISPONIBLE and extension in ['.pdf', '.png', '.jpg', '.jpeg', '.tiff', '.bmp']:
                type_fichier = "OCR"
            else:
                type_fichier = "texte"
        
        fichier_info = {
            "id": str(uuid.uuid4())[:8],
            "nom": titre,
            "chemin": filepath,
            "dossier": CONFIG["dossier_donnees"],
            "extension": extension,
            "taille": os.path.getsize(filepath),
            "date_modification": datetime.now().isoformat(),
            "date_indexation": datetime.now().isoformat(),
            "type_mime": mimetypes.guess_type(filename)[0] or "inconnu",
            "mots_cles": extraire_mots_cles(filepath, filename),
            "categorie": deviner_categorie(CONFIG["dossier_donnees"], filename),
            "specialite": specialite,
            "avocat": avocat,
            "statut": "uploadé",
            "contenu_textuel": contenu_textuel,
            "type_fichier": type_fichier
        }
        
        index = charger_donnees(FICHIER_INDEX)
        index.append(fichier_info)
        sauvegarder_donnees(FICHIER_INDEX, index)
        
        indexer_dans_elasticsearch(fichier_info)
        
        return jsonify({
            "success": True,
            "message": "Fichier uploadé avec succès" + (" (OCR appliqué)" if type_fichier == "OCR" else " (texte extrait)" if contenu_textuel and not contenu_textuel.startswith("[") else ""),
            "fichier": fichier_info,
            "ocr_used": type_fichier == "OCR",
            "texte_extrait": bool(contenu_textuel and not contenu_textuel.startswith("["))
        })
        
    except Exception as e:
        logger.error(f"Erreur upload: {e}")
        return jsonify({"success": False, "erreur": str(e)}), 500

@app.route('/download/<fichier_id>')
def download_file(fichier_id):
    try:
        index = charger_donnees(FICHIER_INDEX)
        fichier = next((f for f in index if f['id'] == fichier_id), None)
        
        if fichier and os.path.exists(fichier['chemin']):
            return send_from_directory(
                os.path.dirname(fichier['chemin']),
                os.path.basename(fichier['chemin']),
                as_attachment=True
            )
        else:
            return jsonify({"success": False, "erreur": "Fichier non trouvé"}), 404
    except Exception as e:
        logger.error(f"Erreur téléchargement: {e}")
        return jsonify({"success": False, "erreur": str(e)}), 500

@app.route('/statistiques')
def statistiques():
    try:
        index = charger_donnees(FICHIER_INDEX)
        stats = charger_donnees(FICHIER_STATS)
        
        categories = {}
        extensions = {}
        specialites = {}
        avocats = {}
        types_fichier = {}
        tailles_total = 0
        
        for fichier in index:
            cat = fichier.get('categorie', 'Inconnu')
            categories[cat] = categories.get(cat, 0) + 1
            
            ext = fichier.get('extension', 'sans')
            extensions[ext] = extensions.get(ext, 0) + 1
            
            spec = fichier.get('specialite', 'Non spécifiée')
            specialites[spec] = specialites.get(spec, 0) + 1
            
            avocat = fichier.get('avocat', 'Non attribué')
            avocats[avocat] = avocats.get(avocat, 0) + 1
            
            type_fichier = fichier.get('type_fichier', 'standard')
            types_fichier[type_fichier] = types_fichier.get(type_fichier, 0) + 1
            
            tailles_total += fichier.get('taille', 0)
        
        return jsonify({
            "indexation": stats,
            "categories": categories,
            "extensions": extensions,
            "specialites": specialites,
            "avocats": avocats,
            "types_fichier": types_fichier,
            "tailles_total": f"{tailles_total / (1024*1024):.1f} Mo",
            "fichiers_total": len(index),
            "dossiers_uniques": len(set(f.get('dossier') for f in index)),
            "elasticsearch": "connecté" if es else "non disponible",
            "ocr": OCR_MESSAGE
        })
        
    except Exception as e:
        logger.error(f"Erreur statistiques: {e}")
        return jsonify({"erreur": str(e)}), 500

@app.route('/api/debug-search')
def debug_search():
    terme = request.args.get('q', '')
    query = analyser_requete_avancee(terme)
    
    return jsonify({
        "terme": terme,
        "query_elasticsearch": query,
        "has_operators": any(op in terme for op in [':', '"', '-']) or ' OR ' in terme.upper() or ' AND ' in terme.upper()
    })

if __name__ == '__main__':
    print("=" * 60)
    print("CABINET AVOCATS - Gestion Documentaire")
    print("http://localhost:5000")
    print("Elasticsearch:", "Connecté" if es else "Non disponible")
    print("OCR Tesseract:", OCR_MESSAGE)
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=False)