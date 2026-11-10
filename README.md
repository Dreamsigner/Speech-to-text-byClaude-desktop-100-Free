# Speech-to-text byClaude desktop(100%Free)

Prototype Windows de dictée utilisant la fonction de dictée de Claude Desktop. Appuyez sur **Ctrl+I** pour commencer, puis de nouveau pour terminer et transférer le texte vers l'application cible. Aucun message n'est envoyé dans Claude. Le champ de Claude doit être vide avant de commencer.

## Prérequis

- Windows avec Windows PowerShell 5.1 et Python 3 installé ; `python.exe` et `pythonw.exe` doivent être accessibles dans le PATH.
- Claude Desktop installé, connecté à un compte disposant de la fonction de dictée, et une connexion Internet. Les contrôles recherchés portent actuellement les noms français « Dicter » et « Terminer la dictée ».
- Un microphone fonctionnel et une application cible compatible avec les contrôles d'accessibilité Windows.

Le script utilise la bibliothèque standard de Python et ne demande aucune clé API. **L'audio et sa transcription sont traités par Claude à distance** : ils ne restent donc pas exclusivement sur votre ordinateur. Le titre exprime l'objectif de gratuité du projet ; la disponibilité, les limites et le coût éventuel du compte ou du service Claude dépendent des conditions d'Anthropic et ne sont pas garantis par ce projet.

## Utilisation

Dans PowerShell, depuis le dossier du projet :

```powershell
.\Start-ClaudeDictationHeadless.ps1 -Check
.\Start-ClaudeDictationHeadless.ps1 -Diagnose
.\Start-ClaudeDictationHeadless.ps1
```

Les deux premières commandes contrôlent la disponibilité et l'état de Claude sans démarrer le microphone. La dernière lance le service en arrière-plan. Placez le curseur dans le champ cible, puis utilisez Ctrl+I deux fois. Pour arrêter le service lorsqu'il est au repos :

```powershell
.\Stop-ClaudeDictationHeadless.ps1
```

Le script d'arrêt refuse d'interrompre une opération en cours ou dont l'état est incertain. Vérifiez alors Claude avant de réessayer.

Le résultat non vide remplace le presse-papiers. Une copie de récupération en clair est conservée dans `claude_headless/recovery/` avant l'extraction ; protégez et supprimez ces fichiers selon vos besoins. En cas d'erreur, l'état `blocked` exige une vérification de Claude avant la reprise. Le journal `claude_headless/stop-events.jsonl` contient des diagnostics sans transcription.

## Démarrage automatique Windows (facultatif)

Pour lancer la dictée après chaque redémarrage, à l'ouverture de votre session Windows :

```powershell
.\Install-ClaudeDictationHeadlessAutostart.ps1 -Check
.\Install-ClaudeDictationHeadlessAutostart.ps1
```

Si votre stratégie PowerShell bloque ces scripts, utilisez `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\Install-ClaudeDictationHeadlessAutostart.ps1` (ajoutez `-Check` pour vérifier sans installer). Cette option concerne uniquement le processus lancé et ne change pas la stratégie permanente de Windows.

La tâche `CodexClaudeDictationHeadless` lance le service en arrière-plan 15 secondes après l'ouverture de session, avec vos droits habituels. Elle fonctionne aussi sur batterie. Aucune connexion Windows ni élévation administrateur n'est automatisée ; Claude Desktop doit rester installé et connecté. Les lancements multiples sont empêchés par la tâche et par le service.

L'option `-Check` ne modifie rien. L'installation détecte les anciens démarrages automatiques connus qui pourraient utiliser le même raccourci et préserve toute tâche existante différente. Relancer l'installation sur une tâche déjà conforme ne la remplace pas.

Pour désactiver les prochains démarrages automatiques, sans interrompre la dictée actuellement lancée :

```powershell
.\Disable-ClaudeDictationHeadlessAutostart.ps1 -Check
.\Disable-ClaudeDictationHeadlessAutostart.ps1
```

La tâche désactivée est conservée. Pour réactiver le démarrage automatique, activez-la dans le Planificateur de tâches. Si vous déplacez le dossier du projet, supprimez d'abord l'ancienne tâche depuis le Planificateur puis relancez l'installation depuis le nouvel emplacement.

## Limites et tests

Il s'agit d'un prototype : la reconnaissance d'une voix réelle et le cycle complet sans intervention restent à valider. Le comportement dépend de la version de Claude Desktop, du focus et de l'accessibilité de l'application cible ; la compatibilité universelle n'est pas établie. Vérifiez le texte inséré.

Les tests automatisés simulent les interactions et n'activent pas le microphone :

```powershell
python -X utf8 -B -m unittest discover -s claude_headless -p 'test_*.py' -v
powershell.exe -NoProfile -File .\claude_headless\test_identity_control.ps1
powershell.exe -NoProfile -File .\claude_headless\test_stop_control.ps1
powershell.exe -NoProfile -File .\claude_headless\test_stabilization.ps1
```
