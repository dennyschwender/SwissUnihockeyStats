# SwissUnihockey Web Application

**Modern Next.js 14 frontend for the SwissUnihockey API**

## 🌟 Features

### Multi-Language Support
- **German (DE)** - Default
- **English (EN)**
- **French (FR)**
- **Italian (IT)**

Powered by `next-intl` for seamless internationalization.

### Swiss Theme
- Red and white color scheme inspired by the Swiss flag
- Modern, responsive design with Tailwind CSS
- Smooth animations and transitions
- Mobile-first approach

### Technology Stack
- **Framework**: Next.js 14 (App Router)
- **Language**: TypeScript
- **Styling**: Tailwind CSS
- **State Management**: Zustand
- **Data Fetching**: TanStack Query (React Query)
- **API Client**: Axios
- **Internationalization**: next-intl
- **Icons**: Lucide React
- **Form Validation**: React Hook Form + Zod

## 🚀 Getting Started

### Prerequisites

- Node.js 18.0.0 or higher
- npm 9.0.0 or higher
- Backend API running at `http://localhost:8000` (see `../backend/`)

### Installation

```bash
# Install dependencies
npm install

# Copy environment variables
cp .env.example .env

# Start development server
npm run dev
```

The application will be available at [http://localhost:3000](http://localhost:3000)

### Build for Production

```bash
# Create optimized production build
npm run build

# Start production server
npm start
```

## 📁 Project Structure

```
web/
├── src/
│   ├── app/                    # Next.js App Router
│   │   └── [locale]/          # Localized routes
│   │       ├── layout.tsx     # Root layout with i18n
│   │       ├── page.tsx       # Home page
│   │       ├── clubs/         # Clubs pages
│   │       ├── leagues/       # Leagues pages
│   │       ├── teams/         # Teams pages
│   │       ├── games/         # Games pages
│   │       ├── rankings/      # Rankings pages
│   │       └── players/       # Players pages
│   ├── components/            # Reusable React components
│   │   ├── Header.tsx
│   │   ├── Footer.tsx
│   │   ├── LanguageSwitcher.tsx
│   │   └── ...
│   ├── lib/                   # Utilities and configurations
│   │   ├── api.ts            # API service layer
│   │   ├── api-client.ts     # Axios client
│   │   ├── i18n.ts           # i18n configuration
│   │   └── utils.ts          # Helper functions
│   └── locales/              # Translation files
│       ├── de/common.json    # German translations
│       ├── en/common.json    # English translations
│       ├── fr/common.json    # French translations
│       └── it/common.json    # Italian translations
├── public/                   # Static assets
├── tailwind.config.js       # Tailwind CSS configuration
├── tsconfig.json            # TypeScript configuration
├── next.config.js           # Next.js configuration
└── package.json             # Dependencies
```

## 🌐 Internationalization

### Adding a New Language

1. Add locale to `src/lib/i18n.ts`:
```typescript
export const locales = ['de', 'en', 'fr', 'it', 'es'] as const;
```

2. Create translation file:
```bash
mkdir src/locales/es
cp src/locales/en/common.json src/locales/es/common.json
# Translate the content
```

3. Update `next.config.js`:
```javascript
i18n: {
  locales: ['de', 'en', 'fr', 'it', 'es'],
  defaultLocale: 'de',
}
```

### Using Translations

```tsx
import { useTranslations } from 'next-intl';

export default function Component() {
  const t = useTranslations();
  
  return <h1>{t('nav.home')}</h1>;
}
```

## 🎨 Theming

The Swiss theme uses the following color palette:

```css
/* Primary Swiss Red */
--swiss-red: #FF0000

/* Gradients */
from-swiss-red/5 via-white to-swiss-red/10

/* Text colors */
text-swiss-gray.600
text-swiss-gray.800
```

### Customizing Colors

Edit `tailwind.config.js`:
```javascript
theme: {
  extend: {
    colors: {
      swiss: {
        red: '#FF0000',
        // Add more colors
      }
    }
  }
}
```

## 🔌 API Integration

### API Service

All API calls go through `src/lib/api.ts`:

```typescript
import { swissunihockeyApi } from '@/lib/api';

// Get clubs
const clubs = await swissunihockeyApi.getClubs({ limit: 10 });

// Get specific club
const club = await swissunihockeyApi.getClub(clubId);
```

### Environment Variables

```bash
# Backend API URL
NEXT_PUBLIC_API_URL=http://localhost:8000

# Default locale
NEXT_PUBLIC_DEFAULT_LOCALE=de
```

## 🧪 Testing

```bash
# Run tests
npm test

# Run tests in watch mode
npm run test:watch

# Generate coverage report
npm run test:coverage
```

## 📝 Scripts

```bash
npm run dev          # Start development server
npm run build        # Build for production
npm start            # Start production server
npm run lint         # Lint code
npm run type-check   # TypeScript type checking
npm run format       # Format code with Prettier
```

## 🐳 Docker Support

See root `docker-compose.yml` for running the full stack (backend + frontend).

## 📄 License

MIT License - see LICENSE file in root directory

## 🤝 Contributing

1. Follow TypeScript and ESLint rules
2. Use Prettier for code formatting
3. Write meaningful commit messages
4. Add translations for all new text
5. Test on multiple screen sizes

## 📚 Documentation

- [Next.js Documentation](https://nextjs.org/docs)
- [Tailwind CSS](https://tailwindcss.com/docs)
- [next-intl](https://next-intl-docs.vercel.app/)
- [React Query](https://tanstack.com/query/latest)
- [Zustand](https://github.com/pmndrs/zustand)
