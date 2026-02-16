import { apiClient } from './api-client';

// Types
export interface Club {
  text: string;
  set_in_context: {
    club_id: number;
    [key: string]: any;
  };
  [key: string]: any;
}

export interface League {
  text: string;
  set_in_context: {
    league_id: number;
    game_class_id?: number;
    [key: string]: any;
  };
  [key: string]: any;
}

export interface Team {
  text: string;
  set_in_context: {
    team_id: number;
    club_id?: number;
    league_id?: number;
    [key: string]: any;
  };
  [key: string]: any;
}

export interface Game {
  [key: string]: any;
}

export interface GameEvent {
  [key: string]: any;
}

export interface Ranking {
  [key: string]: any;
}

export interface TopScorer {
  [key: string]: any;
}

export interface ClubsResponse {
  total: number;
  clubs: Club[];
  filters?: {
    name?: string;
    limit?: number;
  };
}

export interface LeaguesResponse {
  total: number;
  leagues: League[];
  filters?: {
    mode?: string;
    limit?: number;
  };
}

export interface TeamsResponse {
  total: number;
  teams: Team[];
  filters?: {
    club?: string;
    league?: string;
    season?: string;
    limit?: number;
  };
}

export interface GamesResponse {
  total: number;
  games: Game[];
  filters?: {
    league?: string;
    team?: string;
    from_date?: string;
    to_date?: string;
    limit?: number;
  };
}

export interface RankingsResponse {
  total: number;
  rankings: Ranking[];
  filters?: {
    league?: string;
    game_class?: string;
    group?: string;
    season?: string;
    mode?: string;
  };
}

export interface TopScorersResponse {
  total: number;
  topscorers: TopScorer[];
  limit?: number;
}

// API Service
export const swissunihockeyApi = {
  // Clubs
  getClubs: async (params?: { name?: string; limit?: number }): Promise<ClubsResponse> => {
    return apiClient.get<ClubsResponse>('/api/v1/clubs/', { params });
  },

  getClub: async (clubId: number): Promise<Club> => {
    return apiClient.get<Club>(`/api/v1/clubs/${clubId}`);
  },

  // Leagues
  getLeagues: async (params?: { mode?: string; limit?: number }): Promise<LeaguesResponse> => {
    return apiClient.get<LeaguesResponse>('/api/v1/leagues/', { params });
  },

  getLeague: async (leagueId: number): Promise<League> => {
    return apiClient.get<League>(`/api/v1/leagues/${leagueId}`);
  },

  // Teams
  getTeams: async (params?: {
    club?: string;
    league?: string;
    season?: string;
    limit?: number;
  }): Promise<TeamsResponse> => {
    return apiClient.get<TeamsResponse>('/api/v1/teams/', { params });
  },

  getTeam: async (teamId: number): Promise<Team> => {
    return apiClient.get<Team>(`/api/v1/teams/${teamId}`);
  },

  // Games
  getGames: async (params?: {
    league?: string;
    team?: string;
    from_date?: string;
    to_date?: string;
    limit?: number;
  }): Promise<GamesResponse> => {
    return apiClient.get<GamesResponse>('/api/v1/games/', { params });
  },

  getGame: async (gameId: number): Promise<Game> => {
    return apiClient.get<Game>(`/api/v1/games/${gameId}`);
  },

  getGameEvents: async (gameId: number): Promise<{ total: number; events: GameEvent[] }> => {
    return apiClient.get(`/api/v1/games/${gameId}/events`);
  },

  // Rankings
  getRankings: async (params?: {
    league?: string;
    game_class?: string;
    group?: string;
    season?: string;
    mode?: string;
  }): Promise<RankingsResponse> => {
    return apiClient.get<RankingsResponse>('/api/v1/rankings/', { params });
  },

  getTopScorers: async (params?: { limit?: number }): Promise<TopScorersResponse> => {
    return apiClient.get<TopScorersResponse>('/api/v1/rankings/topscorers', { params });
  },
};
