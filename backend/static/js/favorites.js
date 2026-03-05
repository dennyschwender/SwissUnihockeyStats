/**
 * SwissUnihockey Favorites Manager
 * Uses Alpine.js and localStorage for client-side favorites.
 *
 * Requires: backend/static/css/toast.css (add to your base template)
 */

const _VALID_TYPES = new Set(['clubs', 'leagues', 'teams']);

// Global favorites store function for Alpine.js
function favoritesStore() {
    return {
        favorites: {
            clubs: [],
            leagues: [],
            teams: []
        },

        init() {
            this.loadFavorites();
        },

        loadFavorites() {
            try {
                const stored = localStorage.getItem('swissunihockey_favorites');
                if (stored) {
                    const parsed = JSON.parse(stored);
                    // Validate structure before using
                    if (parsed && typeof parsed === 'object') {
                        this.favorites = {
                            clubs:   Array.isArray(parsed.clubs)   ? parsed.clubs   : [],
                            leagues: Array.isArray(parsed.leagues) ? parsed.leagues : [],
                            teams:   Array.isArray(parsed.teams)   ? parsed.teams   : [],
                        };
                    }
                }
            } catch (e) {
                console.error('Error loading favorites:', e);
                this.favorites = { clubs: [], leagues: [], teams: [] };
            }
        },

        saveFavorites() {
            try {
                localStorage.setItem('swissunihockey_favorites', JSON.stringify(this.favorites));
            } catch (e) {
                // QuotaExceededError or similar
                console.warn('Could not save favorites to localStorage:', e);
                this.showToast('Could not save favorites (storage full)');
                return;
            }
            // Dispatch custom event for other components to listen
            window.dispatchEvent(new CustomEvent('favorites-updated', {
                detail: this.favorites
            }));
        },

        _assertValidType(type) {
            if (!_VALID_TYPES.has(type)) {
                console.error('Invalid favorites type:', type);
                return false;
            }
            return true;
        },

        isFavorite(type, id) {
            if (!this._assertValidType(type)) return false;
            return this.favorites[type].some(item => item.id === id);
        },

        toggleFavorite(type, id, name, extraData = {}) {
            if (!this._assertValidType(type)) return;
            if (this.isFavorite(type, id)) {
                this.removeFavorite(type, id);
            } else {
                this.addFavorite(type, id, name, extraData);
            }
        },

        addFavorite(type, id, name, extraData = {}) {
            if (!this._assertValidType(type)) return;
            if (!this.isFavorite(type, id)) {
                this.favorites[type].push({
                    id: id,
                    name: name,
                    addedAt: new Date().toISOString(),
                    ...extraData
                });
                this.saveFavorites();
                this.showToast(`Added ${name} to favorites`);
            }
        },

        removeFavorite(type, id) {
            if (!this._assertValidType(type)) return;
            const item = this.favorites[type].find(item => item.id === id);
            this.favorites[type] = this.favorites[type].filter(item => item.id !== id);
            this.saveFavorites();
            if (item) {
                this.showToast(`Removed ${item.name} from favorites`);
            }
        },

        getFavoritesCount() {
            return this.favorites.clubs.length +
                   this.favorites.leagues.length +
                   this.favorites.teams.length;
        },

        clearAll() {
            if (confirm('Are you sure you want to remove all favorites?')) {
                this.favorites = { clubs: [], leagues: [], teams: [] };
                this.saveFavorites();
                this.showToast('All favorites cleared');
            }
        },

        showToast(message) {
            const toast = document.createElement('div');
            toast.className = 'toast-notification toast-slide-in';
            // textContent prevents XSS — never use innerHTML here
            toast.textContent = message;
            document.body.appendChild(toast);

            setTimeout(() => {
                toast.className = 'toast-notification toast-slide-out';
                setTimeout(() => toast.remove(), 300);
            }, 2000);
        }
    };
}
