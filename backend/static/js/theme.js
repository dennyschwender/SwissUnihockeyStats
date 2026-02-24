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
            this._syncButtons(this.getCurrentTheme());
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

        // Update all theme toggle buttons (header + mobile menu)
        this._syncButtons(theme);

        // Dispatch custom event for other components
        window.dispatchEvent(new CustomEvent('themechange', { detail: { theme } }));
    }

    _syncButtons(theme) {
        const icon = theme === 'dark' ? '☀️' : '🌙';
        const title = theme === 'dark' ? 'Switch to Light Mode' : 'Switch to Dark Mode';
        document.querySelectorAll('.theme-toggle').forEach(btn => {
            btn.title = title;
        });
        // Update emoji spans separately so buttons can have a label text too
        document.querySelectorAll('.theme-toggle-icon').forEach(el => {
            el.textContent = icon;
        });
        // Fallback: plain theme-toggle buttons with no icon span
        const headerBtn = document.getElementById('theme-toggle-btn');
        if (headerBtn && !headerBtn.querySelector('.theme-toggle-icon')) {
            headerBtn.textContent = icon;
        }
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
