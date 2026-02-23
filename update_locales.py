import json

BASE = '/home/denny/Development/SwissUnihockeyStats/backend/locales'

new_keys = {
    'de': {
        'home_extra': {
            'recent_games': 'Letzte Spiele',
            'upcoming_games': 'Bevorstehende Spiele',
            'top_scorers': 'Beste Torschützen',
            'view_all_players': 'Alle Spieler anzeigen →',
            'all_leagues': 'Alle Ligen',
            'search_placeholder': 'Vereine, Ligen, Teams suchen...',
        },
        'players_extra': {
            'leaderboard': 'Spieler-Rangliste',
            'order_points': 'Punkte',
            'order_goals': 'Tore',
            'order_assists': 'Assists',
            'search_placeholder': 'Nach Name suchen…',
        },
        'errors': {
            'not_found_title': 'Seite nicht gefunden',
            'not_found_desc': 'Die gesuchte Seite existiert leider nicht. Vielleicht wurde sie verschoben oder gelöscht.',
            'server_error_title': 'Interner Serverfehler',
            'server_error_desc': 'Entschuldigung! Etwas ist schiefgelaufen. Unser Team wurde automatisch benachrichtigt.',
            'notify_team': 'Falls das Problem weiterhin besteht, bitte kontaktieren Sie uns mit dieser Fehler-ID.',
            'go_home': 'Zur Startseite',
            'reload_page': 'Seite neu laden',
            'popular_pages': 'Beliebte Seiten',
            'error_id_label': 'Fehler-ID:',
            'error_time_label': 'Zeitpunkt:',
        },
        'table': {
            'player': 'Spieler', 'team': 'Team', 'league': 'Liga',
            'season': 'Saison', 'position': 'Position', 'pos': 'Pos',
            'period': 'Abschnitt', 'time': 'Zeit', 'type': 'Typ',
            'score': 'Stand', 'score_penalty': 'Stand / Strafe',
        },
        'player': {
            'born': 'Geboren:',
            'season_history': 'Saisonverlauf',
            'career_totals': 'Karriere gesamt',
            'show_less': 'Weniger anzeigen ▲',
            'show_all': 'Alle anzeigen',
        },
        'team_tabs': {
            'tab_roster': 'Kader & Statistiken',
            'tab_results': 'Letzte Spiele',
            'tab_upcoming': 'Bevorstehend',
        },
        'game': {
            'best_player': 'Bester Spieler',
            'best_players': 'Beste Spieler',
            'event_all': 'Alle',
            'event_goals': '🥅 Tore',
            'event_penalties': '🟨 Strafen',
            'no_events': 'Keine Ereignisdaten für dieses Spiel verfügbar.',
            'no_roster': 'Keine Kaderdaten verfügbar. Führen Sie einen Ereignis-Indexjob durch.',
            'tab_events': 'Ereignisse',
            'tab_roster': 'Kader',
        },
        'league_detail': {
            'tab_standings': 'Tabelle',
            'tab_topscorers': 'Topscorer',
            'tab_penalties': 'Strafen',
            'tab_results': 'Ergebnisse',
            'tab_upcoming': 'Bevorstehend',
        },
        'pwa': {
            'install_title': '📱 Unihockey Stats installieren',
            'install_desc': 'Offline-Zugriff, schnelleres Laden',
            'install_btn': 'Installieren',
        },
    },
    'en': {
        'home_extra': {
            'recent_games': 'Recent Games',
            'upcoming_games': 'Upcoming Games',
            'top_scorers': 'Overall Top Scorers',
            'view_all_players': 'View all players →',
            'all_leagues': 'All Leagues',
            'search_placeholder': 'Search clubs, leagues, teams...',
        },
        'players_extra': {
            'leaderboard': 'Player Leaderboard',
            'order_points': 'Points',
            'order_goals': 'Goals',
            'order_assists': 'Assists',
            'search_placeholder': 'Search by name…',
        },
        'errors': {
            'not_found_title': 'Page Not Found',
            'not_found_desc': "The page you're looking for doesn't exist. It may have been moved or deleted.",
            'server_error_title': 'Internal Server Error',
            'server_error_desc': 'Sorry! Something went wrong. Our team has been notified and is working on a fix.',
            'notify_team': 'If the problem persists, please contact us with this error ID.',
            'go_home': 'Go Home',
            'reload_page': 'Reload Page',
            'popular_pages': 'Popular Pages',
            'error_id_label': 'Error ID:',
            'error_time_label': 'Time:',
        },
        'table': {
            'player': 'Player', 'team': 'Team', 'league': 'League',
            'season': 'Season', 'position': 'Position', 'pos': 'Pos',
            'period': 'Period', 'time': 'Time', 'type': 'Type',
            'score': 'Score', 'score_penalty': 'Score / Penalty',
        },
        'player': {
            'born': 'Born:',
            'season_history': 'Season History',
            'career_totals': 'Career Totals',
            'show_less': 'Show less ▲',
            'show_all': 'Show all',
        },
        'team_tabs': {
            'tab_roster': 'Roster & Stats',
            'tab_results': 'Recent Results',
            'tab_upcoming': 'Upcoming',
        },
        'game': {
            'best_player': 'Best Player',
            'best_players': 'Best Players',
            'event_all': 'All',
            'event_goals': '🥅 Goals',
            'event_penalties': '🟨 Penalties',
            'no_events': 'No event data available for this game.',
            'no_roster': 'No roster data available. Run an events index job to fetch lineups.',
            'tab_events': 'Events',
            'tab_roster': 'Roster',
        },
        'league_detail': {
            'tab_standings': 'Standings',
            'tab_topscorers': 'Top Scorers',
            'tab_penalties': 'Penalties',
            'tab_results': 'Results',
            'tab_upcoming': 'Upcoming',
        },
        'pwa': {
            'install_title': '📱 Install Unihockey Stats',
            'install_desc': 'Access stats offline, faster loading',
            'install_btn': 'Install',
        },
    },
    'fr': {
        'home_extra': {
            'recent_games': 'Matchs récents',
            'upcoming_games': 'Prochains matchs',
            'top_scorers': 'Meilleurs buteurs globaux',
            'view_all_players': 'Voir tous les joueurs →',
            'all_leagues': 'Toutes les ligues',
            'search_placeholder': 'Rechercher clubs, ligues, équipes...',
        },
        'players_extra': {
            'leaderboard': 'Classement des joueurs',
            'order_points': 'Points',
            'order_goals': 'Buts',
            'order_assists': 'Passes décisives',
            'search_placeholder': 'Rechercher par nom…',
        },
        'errors': {
            'not_found_title': 'Page introuvable',
            'not_found_desc': "La page que vous cherchez n'existe pas. Elle a peut-être été déplacée ou supprimée.",
            'server_error_title': 'Erreur interne du serveur',
            'server_error_desc': "Désolé ! Quelque chose s'est mal passé. Notre équipe a été notifiée.",
            'notify_team': "Si le problème persiste, veuillez nous contacter avec cet identifiant d'erreur.",
            'go_home': 'Accueil',
            'reload_page': 'Recharger la page',
            'popular_pages': 'Pages populaires',
            'error_id_label': "ID d'erreur :",
            'error_time_label': 'Heure :',
        },
        'table': {
            'player': 'Joueur', 'team': 'Équipe', 'league': 'Ligue',
            'season': 'Saison', 'position': 'Position', 'pos': 'Pos',
            'period': 'Période', 'time': 'Temps', 'type': 'Type',
            'score': 'Score', 'score_penalty': 'Score / Pénalité',
        },
        'player': {
            'born': 'Né(e) :',
            'season_history': 'Historique des saisons',
            'career_totals': 'Total carrière',
            'show_less': 'Voir moins ▲',
            'show_all': 'Voir tout',
        },
        'team_tabs': {
            'tab_roster': 'Effectif & Statistiques',
            'tab_results': 'Résultats récents',
            'tab_upcoming': 'À venir',
        },
        'game': {
            'best_player': 'Meilleur joueur',
            'best_players': 'Meilleurs joueurs',
            'event_all': 'Tous',
            'event_goals': '🥅 Buts',
            'event_penalties': '🟨 Pénalités',
            'no_events': 'Aucune donnée disponible pour ce match.',
            'no_roster': "Aucune donnée d'effectif disponible.",
            'tab_events': 'Événements',
            'tab_roster': 'Effectif',
        },
        'league_detail': {
            'tab_standings': 'Classement',
            'tab_topscorers': 'Meilleurs buteurs',
            'tab_penalties': 'Pénalités',
            'tab_results': 'Résultats',
            'tab_upcoming': 'À venir',
        },
        'pwa': {
            'install_title': '📱 Installer Unihockey Stats',
            'install_desc': 'Accès hors ligne, chargement plus rapide',
            'install_btn': 'Installer',
        },
    },
    'it': {
        'home_extra': {
            'recent_games': 'Partite recenti',
            'upcoming_games': 'Prossime partite',
            'top_scorers': 'Migliori marcatori complessivi',
            'view_all_players': 'Vedi tutti i giocatori →',
            'all_leagues': 'Tutti i campionati',
            'search_placeholder': 'Cerca club, campionati, squadre...',
        },
        'players_extra': {
            'leaderboard': 'Classifica giocatori',
            'order_points': 'Punti',
            'order_goals': 'Gol',
            'order_assists': 'Assist',
            'search_placeholder': 'Cerca per nome…',
        },
        'errors': {
            'not_found_title': 'Pagina non trovata',
            'not_found_desc': 'La pagina che cerchi non esiste. Potrebbe essere stata spostata o eliminata.',
            'server_error_title': 'Errore interno del server',
            'server_error_desc': 'Spiacenti! Qualcosa è andato storto. Il nostro team è stato avvisato.',
            'notify_team': 'Se il problema persiste, contattaci con questo ID errore.',
            'go_home': 'Vai alla home',
            'reload_page': 'Ricarica la pagina',
            'popular_pages': 'Pagine popolari',
            'error_id_label': 'ID errore:',
            'error_time_label': 'Ora:',
        },
        'table': {
            'player': 'Giocatore', 'team': 'Squadra', 'league': 'Campionato',
            'season': 'Stagione', 'position': 'Posizione', 'pos': 'Pos',
            'period': 'Periodo', 'time': 'Tempo', 'type': 'Tipo',
            'score': 'Punteggio', 'score_penalty': 'Punteggio / Penalità',
        },
        'player': {
            'born': 'Nato:',
            'season_history': 'Storico stagioni',
            'career_totals': 'Totale carriera',
            'show_less': 'Mostra meno ▲',
            'show_all': 'Mostra tutto',
        },
        'team_tabs': {
            'tab_roster': 'Rosa & Statistiche',
            'tab_results': 'Risultati recenti',
            'tab_upcoming': 'In programma',
        },
        'game': {
            'best_player': 'Miglior giocatore',
            'best_players': 'Migliori giocatori',
            'event_all': 'Tutti',
            'event_goals': '🥅 Gol',
            'event_penalties': '🟨 Penalità',
            'no_events': 'Nessun dato disponibile per questa partita.',
            'no_roster': 'Nessun dato di rosa disponibile.',
            'tab_events': 'Eventi',
            'tab_roster': 'Rosa',
        },
        'league_detail': {
            'tab_standings': 'Classifica',
            'tab_topscorers': 'Migliori marcatori',
            'tab_penalties': 'Penalità',
            'tab_results': 'Risultati',
            'tab_upcoming': 'In programma',
        },
        'pwa': {
            'install_title': '📱 Installa Unihockey Stats',
            'install_desc': 'Accesso offline, caricamento più veloce',
            'install_btn': 'Installa',
        },
    },
}

for lang, keys in new_keys.items():
    path = f'{BASE}/{lang}/messages.json'
    with open(path) as f:
        data = json.load(f)

    data['home'].update(keys['home_extra'])
    data['players'].update(keys['players_extra'])
    data['errors'] = keys['errors']
    data['table'] = keys['table']
    data['player'] = keys['player']
    data['team_tabs'] = keys['team_tabs']
    data['game'] = keys['game']
    data['league_detail'] = keys['league_detail']
    data['pwa'] = keys['pwa']

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'Updated {lang}/messages.json')

print('Done.')
