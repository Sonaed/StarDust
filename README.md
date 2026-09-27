# StellarDust

StellarDust est l’univers de conception d’Existence : un atelier séparé où les outils et capacités sont construits, validés, versionnés puis publiés comme ressources partageables avec Nebula, Atlas et les autres univers.

## Utilisation (v0.4)

### Documents
`Fichier › Nouveau / Ouvrir / Enregistrer (sous)` — un fichier par outil :
`.csbr` (Brush Engine), `.csbl` (Fusion), et l'extension de chaque module Existence
(`.cspl` Palette, `.csgr` Dégradé). La session est aussi conservée automatiquement
dans `stardust_state.json`. `python3 main.py mon-outil.csbr` ouvre directement un fichier.

### Graphe (Brush Engine / Fusion)
- Les réglages principaux sont **sur les nœuds** : glisser une barre (Maj = précis, double-clic = défaut),
  clic sur ▾ pour un choix, clic sur la mini-courbe pour l'éditer dans l'onglet Nœud.
- Vraies courbes : points ajoutables/déplaçables, préréglages, inversions.
- Signaux : Entrée (pression, vitesse, inclinaison, direction, distance, aléatoire…), Constante,
  Courbe, Combiner (×, +, −, min, max, différence, écran), Condition (au-dessus / en-dessous /
  entre / hors de, transition douce, porte ou passage).
- Moteur : Dynamique (pilote n'importe quel paramètre CreativeCore), Paramètre moteur (le fixe).
  Glisser un paramètre de l'onglet Moteur sur le graphe pour le piloter.
- Tab / Espace : recherche de nœud · déposer un nœud sur une liaison l'insère · Ctrl+C/V/D ·
  aimantation à la grille (Alt pour la désactiver) · « Essai direct » à droite du graphe avec vumètres
  sur les nœuds.

### Modules Existence (existence.creator.v1)
Existence possède les modules **et leur interface** (`CS_Galaxy/modules/<module>/interface.py`).
StellarDust charge l'interface des modules branchés sur lui dans la carte d'Existence et adapte
ses étapes (Définition → Édition → Test → Publication), sa validation, ses fichiers et sa publication.
Débrancher le module le retire de l'atelier. Tout futur module qui déclare `interface`,
`interface_protocol="existence.creator.v1"`, `host_universe="stardust"` apparaît sans modifier StellarDust.

## Première tranche (historique)

- `Brush Engine Creator` avec graphe de conception et nœuds déplaçables ;
- inspecteur de propriétés et paramètres ;
- statut de brouillon et validation ;
- `Resource Dock` avec ressources, versions et consommateurs ;
- sauvegarde d’état locale dans `stardust_state.json`.

## Lancer

Compiler d’abord le moteur natif :

```bash
/StarDust/build_core.sh
```

Puis lancer StellarDust :

```bash
python3 /home/deanos/Documents/StarDust/main.py
```

Le graphe et son état critique sont portés par `StellarDustCore` en C++. Python/PySide6 ne fait que présenter et orchestrer l’éditeur. Si le moteur n’est pas compilé, l’interface reste en mode de secours et l’indique dans la barre d’état.

<img width="2559" height="1410" alt="image" src="https://github.com/user-attachments/assets/8e95e973-3056-4482-9560-9f5404d31116" />

<img width="439" height="282" alt="image" src="https://github.com/user-attachments/assets/c6349fcd-be42-4573-94c4-186a89efedf7" />
