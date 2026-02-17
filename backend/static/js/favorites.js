/**
 * SwissUnihockey Favorites Manager
 * Uses Alpine.js and localStorage for client-side favorites
 */

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
            const stored = localStorage.getItem('swissunihockey_favorites');
            if (stored) {
                try {
                    this.favorites = JSON.parse(stored);
                } catch (e) {
                    console.error('Error loading favorites:', e);
                    this.favorites = { clubs: [], leagues: [], teams: [] };
                }
            }
        },
        
        saveFavorites() {
            localStorage.setItem('swissunihockey_favorites', JSON.stringify(this.favorites));
            // Dispatch custom event for other components to listen
            window.dispatchEvent(new CustomEvent('favorites-updated', { 
                detail: this.favorites 
            }));
        },
        
        isFavorite(type, id) {
            return this.favorites[type].some(item => item.id === id);
        },
        
        toggleFavorite(type, id, name, extraData = {}) {
            if (this.isFavorite(type, id)) {
                this.removeFavorite(type, id);
            } else {
                this.addFavorite(type, id, name, extraData);
            }
        },
        
        addFavorite(type, id, name, extraData = {}) {
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
            // Simple toast notification
            const toast = document.createElement('div');
            toast.className = 'toast-notification';
            toast.textContent = message;
            toast.style.cssText = `
                position: fixed;
                bottom: 2rem;
                right: 2rem;
                background: var(--gray-900);
                color: white;
                padding: 1rem 1.5rem;
                border-radius: 8px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                z-index: 1000;
                animation: slideIn 0.3s ease-out;
            `;
            document.body.appendChild(toast);
            
            setTimeout(() => {
                toast.style.animation = 'slideOut 0.3s ease-out';
                setTimeout(() => toast.remove(), 300);
            }, 2000);
        }
    }
}

// Add CSS animations for toast
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from {
            transform: translateX(400px);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOut {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(400px);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);
