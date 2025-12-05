

Présentation du projet

Ce système de gestion documentaire est conçu spécifiquement pour les cabinets d'avocats. Il permet d'organiser, d'indexer et de retrouver facilement tous vos documents juridiques.

Fonctionnalités principales

- Indexation complète des documents (PDF, Word, images, etc.)
- Recherche avancée par mots-clés, contenu ou métadonnées
- Gestion des métadonnées : spécialités juridiques et avocats responsables
- Interface web moderne et simple d'utilisation
- Extraction de texte à partir de documents scannés et images
- Gestion complète des documents : ajout, modification, suppression, téléchargement
- Hébergé localement et accès possible à d'autres appareils connectés sur le même réseau à partir de l'adresse serveur

Installation

Prérequis :
- Python 3.8 ou supérieur
- Elasticsearch (optionnel mais recommandé pour la recherche avancée)
- Tesseract OCR (pour l'extraction de texte depuis les images)

Installation :
Clonez le dépôt :
git clone https://github.com/ameo-coder/gestion-documentaire-avocats.git
cd gestion-documentaire-avocats

Installez les dépendances :
pip install -r requirements.txt

Lancez l'application :
server.py

Accès à l'application :
Ouvrez votre navigateur à l'adresse spécifiée par le serveur (par exemple : http://192.168.1.18:5000/)
