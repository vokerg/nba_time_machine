/** Team preferences affect presentation only; canonical scores and order never change. */
import type { GameCard } from "./dashboard";

export const NBA_TEAMS = [
  "Atlanta Hawks", "Boston Celtics", "Brooklyn Nets", "Charlotte Hornets",
  "Chicago Bulls", "Cleveland Cavaliers", "Dallas Mavericks", "Denver Nuggets",
  "Detroit Pistons", "Golden State Warriors", "Houston Rockets", "Indiana Pacers",
  "Los Angeles Clippers", "Los Angeles Lakers", "Memphis Grizzlies", "Miami Heat",
  "Milwaukee Bucks", "Minnesota Timberwolves", "New Orleans Pelicans",
  "New York Knicks", "Oklahoma City Thunder", "Orlando Magic",
  "Philadelphia 76ers", "Phoenix Suns", "Portland Trail Blazers",
  "Sacramento Kings", "San Antonio Spurs", "Toronto Raptors", "Utah Jazz",
  "Washington Wizards",
] as const;

const knownTeams = new Set<string>(NBA_TEAMS);
export function favoriteKey(profileId: string): string {
  return `nba-time-machine:favorites:v1:${profileId}`;
}

export function readFavorites(storage: Pick<Storage, "getItem">, profileId: string): string[] {
  try {
    const value: unknown = JSON.parse(storage.getItem(favoriteKey(profileId)) ?? "[]");
    return Array.isArray(value) ? [...new Set(value.filter(
      (team): team is string => typeof team === "string" && knownTeams.has(team),
    ))] : [];
  } catch {
    return [];
  }
}

export function writeFavorites(storage: Pick<Storage, "setItem">, profileId: string, favorites: readonly string[]): void {
  storage.setItem(favoriteKey(profileId), JSON.stringify(
    [...new Set(favorites.filter((team) => knownTeams.has(team)))],
  ));
}

export function isFavoriteGame(game: Pick<GameCard, "home_team" | "away_team">, favorites: readonly string[]): boolean {
  return favorites.includes(game.home_team ?? "") || favorites.includes(game.away_team ?? "");
}

export function visibleWatchOrder(games: readonly GameCard[], favorites: readonly string[], includeFavorites: boolean): GameCard[] {
  // Filtering the verified server order must not recompute, distort, or personalize scores.
  return includeFavorites ? [...games] : games.filter((game) => !isFavoriteGame(game, favorites));
}
