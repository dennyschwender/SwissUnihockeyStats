/**
 * Theme Management - Dark Mode Support
 * Handles theme switching and persistence
 */

class ThemeManager {
    constructor() {
        this.STORAGE_KEY = 'swiss-unihockey-theme';
        this.DARK_CLASS = 'dark-mode';
        this.init();
    }

    init() {
        // Load saved theme or detect system preference
        const savedTheme = localStorage.getItem(this.STORAGE_KEY);
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        
        const theme = savedTheme || (prefersDark ? 'dark' : 'light');
        this.setTheme(theme, false);

        // Sync button icon once DOM is ready (script runs in <head>)
        document.addEventListener('DOMContentLoaded', () => {
            const btn = document.getElementById('theme-toggle-btn');
            if (btn) {
                btn.textContent = this.getCurrentTheme() === 'dark' ? '☀️' : '🌙';
            }
        });

        // Listen for system theme changes
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
            if (!localStorage.getItem(this.STORAGE_KEY)) {
                this.setTheme(e.matches ? 'dark' : 'light', false);
            }
        });
    }

    setTheme(theme, save = true) {
        if (theme === 'dark') {
            document.documentElement.classList.add(this.DARK_CLASS);
        } else {
            document.documentElement.classList.remove(this.DARK_CLASS);
        }

        if (save) {
            localStorage.setItem(this.STORAGE_KEY, theme);
        }

        // Update toggle button icon
        const btn = document.getElementById('theme-toggle-btn');
        if (btn) {
            btn.textContent = theme === 'dark' ? '☀️' : '🌙';
            btn.title = theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode';
        }

        // Dispatch custom event for other components
        window.dispatchEvent(new CustomEvent('themechange', { detail: { theme } }));
    }

    toggle() {
        const isDark = document.documentElement.classList.contains(this.DARK_CLASS);
        this.setTheme(isDark ? 'light' : 'dark');
        return !isDark ? 'dark' : 'light';
    }

    getCurrentTheme() {
        return document.documentElement.classList.contains(this.DARK_CLASS) ? 'dark' : 'light';
    }
}

// Initialize theme manager (exposed on window so inline onclick handlers can call it)
window.themeManager = new ThemeManager();

// Alpine.js component for theme toggle (kept for backward compat)
window.themeToggle = function() {
    return {
        theme: themeManager.getCurrentTheme(),
        
        toggle() {
            this.theme = themeManager.toggle();
        },
        
        init() {
            // Listen for theme changes from other sources
            window.addEventListener('themechange', (e) => {
                this.theme = e.detail.theme;
            });
        }
    };
};
