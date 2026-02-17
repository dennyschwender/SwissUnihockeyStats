import { useTranslations } from 'next-intl';
import Link from 'next/link';

export default function HomePage() {
  const t = useTranslations();

  return (
    <main className="min-h-screen bg-gradient-to-br from-swiss-red/5 via-white to-swiss-red/10">
      <div className="container mx-auto px-4 py-16">
        {/* Hero Section */}
        <div className="text-center mb-16 animate-fade-in">
          <h1 className="text-6xl font-bold mb-4 text-swiss-red">
            {t('common.appName')}
          </h1>
          <p className="text-2xl text-swiss-gray.600 mb-8">
            {t('common.welcome')}
          </p>
          <p className="text-lg text-swiss-gray.500 max-w-2xl mx-auto">
            Explore Swiss Unihockey leagues, teams, games, and statistics in a modern,
            multi-language web application.
          </p>
        </div>

        {/* Navigation Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 max-w-6xl mx-auto">
          <NavigationCard
            title={t('nav.clubs')}
            description={t('clubs.subtitle')}
            href="/clubs"
            icon="🏒"
          />
          <NavigationCard
            title={t('nav.leagues')}
            description={t('leagues.subtitle')}
            href="/leagues"
            icon="🏆"
          />
          <NavigationCard
            title={t('nav.teams')}
            description={t('teams.subtitle')}
            href="/teams"
            icon="👥"
          />
          <NavigationCard
            title={t('nav.games')}
            description={t('games.subtitle')}
            href="/games"
            icon="🎯"
          />
          <NavigationCard
            title={t('nav.rankings')}
            description={t('rankings.subtitle')}
            href="/rankings"
            icon="📊"
          />
          <NavigationCard
            title={t('nav.players')}
            description={t('players.subtitle')}
            href="/players"
            icon="⭐"
          />
        </div>

        {/* Language Selector Hint */}
        <div className="text-center mt-16 text-swiss-gray.500">
          <p>🌐 Available in: DE | EN | FR | IT</p>
        </div>
      </div>
    </main>
  );
}

function NavigationCard({
  title,
  description,
  href,
  icon,
}: {
  title: string;
  description: string;
  href: string;
  icon: string;
}) {
  return (
    <Link
      href={href}
      className="group block p-6 bg-white rounded-lg shadow-md hover:shadow-xl transition-all duration-300 border-2 border-transparent hover:border-swiss-red"
    >
      <div className="text-4xl mb-4">{icon}</div>
      <h3 className="text-xl font-bold mb-2 text-swiss-gray.800 group-hover:text-swiss-red transition-colors">
        {title}
      </h3>
      <p className="text-swiss-gray.600">{description}</p>
    </Link>
  );
}
