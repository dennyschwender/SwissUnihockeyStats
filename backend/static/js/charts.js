/**
 * Chart.js Utilities for SwissUnihockey Statistics
 * Provides reusable chart creation functions with theme support
 */

class ChartManager {
    constructor() {
        this.charts = new Map();
        this.initThemeSupport();
    }

    /**
     * Initialize theme support for charts
     */
    initThemeSupport() {
        // Listen for theme changes
        document.addEventListener('theme-changed', (e) => {
            this.updateChartsForTheme(e.detail.theme);
        });
    }

    /**
     * Get chart colors based on current theme
     */
    getColors(theme = 'light') {
        if (theme === 'dark') {
            return {
                primary: '#ff3333',        // Lighter red for dark mode
                secondary: '#64748b',
                success: '#10b981',
                warning: '#f59e0b',
                danger: '#ef4444',
                grid: 'rgba(255, 255, 255, 0.1)',
                text: '#f9fafb',
                background: 'rgba(26, 26, 26, 0.8)'
            };
        }
        
        return {
            primary: '#E30613',        // Swiss red
            secondary: '#475569',
            success: '#059669',
            warning: '#d97706',
            danger: '#dc2626',
            grid: 'rgba(0, 0, 0, 0.1)',
            text: '#111827',
            background: 'rgba(255, 255, 255, 0.8)'
        };
    }

    /**
     * Get current theme
     */
    getCurrentTheme() {
        return document.documentElement.classList.contains('dark-mode') ? 'dark' : 'light';
    }

    /**
     * Update all charts for theme change
     */
    updateChartsForTheme(theme) {
        const colors = this.getColors(theme);
        
        this.charts.forEach((chart) => {
            // Update chart colors
            if (chart.options.scales) {
                Object.values(chart.options.scales).forEach(scale => {
                    if (scale.grid) scale.grid.color = colors.grid;
                    if (scale.ticks) scale.ticks.color = colors.text;
                });
            }
            
            if (chart.options.plugins?.legend?.labels) {
                chart.options.plugins.legend.labels.color = colors.text;
            }

            chart.update();
        });
    }

    /**
     * Create Top Scorers Bar Chart
     * @param {string} canvasId - Canvas element ID
     * @param {Array} scorers - Array of {name, goals, assists, points}
     */
    createTopScorersChart(canvasId, scorers) {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return null;

        const theme = this.getCurrentTheme();
        const colors = this.getColors(theme);

        // Take top 10
        const topScorers = scorers.slice(0, 10);
        
        const chart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: topScorers.map(s => s.name),
                datasets: [
                    {
                        label: 'Goals',
                        data: topScorers.map(s => s.goals),
                        backgroundColor: colors.primary + 'cc',
                        borderColor: colors.primary,
                        borderWidth: 2
                    },
                    {
                        label: 'Assists',
                        data: topScorers.map(s => s.assists),
                        backgroundColor: colors.secondary + 'cc',
                        borderColor: colors.secondary,
                        borderWidth: 2
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'top',
                        labels: { color: colors.text }
                    },
                    title: {
                        display: true,
                        text: 'Top 10 Scorers - Goals & Assists',
                        color: colors.text,
                        font: { size: 16, weight: 'bold' }
                    },
                    tooltip: {
                        callbacks: {
                            footer: (items) => {
                                const idx = items[0].dataIndex;
                                return `Total Points: ${topScorers[idx].points}`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        grid: { color: colors.grid },
                        ticks: { 
                            color: colors.text,
                            maxRotation: 45,
                            minRotation: 45
                        }
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: colors.grid },
                        ticks: { 
                            color: colors.text,
                            stepSize: 5
                        }
                    }
                }
            }
        });

        this.charts.set(canvasId, chart);
        return chart;
    }

    /**
     * Create Team Standings Chart (Points Distribution)
     * @param {string} canvasId - Canvas element ID
     * @param {Array} standings - Array of {team, points, games}
     */
    createStandingsChart(canvasId, standings) {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return null;

        const theme = this.getCurrentTheme();
        const colors = this.getColors(theme);

        // Take top 8 teams
        const topTeams = standings.slice(0, 8);
        
        const chart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: topTeams.map(s => s.team),
                datasets: [{
                    label: 'Points',
                    data: topTeams.map(s => s.points),
                    backgroundColor: topTeams.map((_, idx) => {
                        // Gradient from red to gray
                        const opacity = 1 - (idx * 0.08);
                        return colors.primary + Math.floor(opacity * 255).toString(16).padStart(2, '0');
                    }),
                    borderColor: colors.primary,
                    borderWidth: 2
                }]
            },
            options: {
                indexAxis: 'y', // Horizontal bar chart
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    title: {
                        display: true,
                        text: 'Top 8 Teams - Points',
                        color: colors.text,
                        font: { size: 16, weight: 'bold' }
                    },
                    tooltip: {
                        callbacks: {
                            label: (context) => {
                                const idx = context.dataIndex;
                                return `Points: ${context.parsed.x} (${topTeams[idx].games} games)`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        beginAtZero: true,
                        grid: { color: colors.grid },
                        ticks: { color: colors.text }
                    },
                    y: {
                        grid: { color: colors.grid },
                        ticks: { color: colors.text }
                    }
                }
            }
        });

        this.charts.set(canvasId, chart);
        return chart;
    }

    /**
     * Create Performance Line Chart (goals over time)
     * @param {string} canvasId - Canvas element ID
     * @param {Object} data - {labels: [], datasets: [{label, data}]}
     */
    createPerformanceChart(canvasId, data) {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return null;

        const theme = this.getCurrentTheme();
        const colors = this.getColors(theme);

        const chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: data.labels,
                datasets: data.datasets.map((dataset, idx) => ({
                    label: dataset.label,
                    data: dataset.data,
                    borderColor: idx === 0 ? colors.primary : colors.secondary,
                    backgroundColor: (idx === 0 ? colors.primary : colors.secondary) + '33',
                    borderWidth: 3,
                    tension: 0.4,
                    fill: true,
                    pointRadius: 4,
                    pointHoverRadius: 6
                }))
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'top',
                        labels: { color: colors.text }
                    },
                    title: {
                        display: true,
                        text: 'Performance Over Time',
                        color: colors.text,
                        font: { size: 16, weight: 'bold' }
                    }
                },
                scales: {
                    x: {
                        grid: { color: colors.grid },
                        ticks: { color: colors.text }
                    },
                    y: {
                        beginAtZero: true,
                        grid: { color: colors.grid },
                        ticks: { color: colors.text }
                    }
                },
                interaction: {
                    mode: 'index',
                    intersect: false
                }
            }
        });

        this.charts.set(canvasId, chart);
        return chart;
    }

    /**
     * Create Pie Chart (distribution)
     * @param {string} canvasId - Canvas element ID
     * @param {Object} data - {labels: [], values: []}
     * @param {string} title - Chart title
     */
    createPieChart(canvasId, data, title = 'Distribution') {
        const ctx = document.getElementById(canvasId);
        if (!ctx) return null;

        const theme = this.getCurrentTheme();
        const colors = this.getColors(theme);

        // Generate colors for each segment
        const backgroundColors = [
            colors.primary,
            colors.secondary,
            colors.success,
            colors.warning,
            colors.danger,
            '#8b5cf6',
            '#ec4899',
            '#14b8a6'
        ];

        const chart = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: data.labels,
                datasets: [{
                    data: data.values,
                    backgroundColor: backgroundColors.slice(0, data.labels.length),
                    borderWidth: 2,
                    borderColor: theme === 'dark' ? '#1a1a1a' : '#ffffff'
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'right',
                        labels: { 
                            color: colors.text,
                            padding: 10
                        }
                    },
                    title: {
                        display: true,
                        text: title,
                        color: colors.text,
                        font: { size: 16, weight: 'bold' }
                    },
                    tooltip: {
                        callbacks: {
                            label: (context) => {
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const percentage = ((context.parsed / total) * 100).toFixed(1);
                                return `${context.label}: ${context.parsed} (${percentage}%)`;
                            }
                        }
                    }
                }
            }
        });

        this.charts.set(canvasId, chart);
        return chart;
    }

    /**
     * Destroy a specific chart
     */
    destroyChart(canvasId) {
        const chart = this.charts.get(canvasId);
        if (chart) {
            chart.destroy();
            this.charts.delete(canvasId);
        }
    }

    /**
     * Destroy all charts
     */
    destroyAll() {
        this.charts.forEach(chart => chart.destroy());
        this.charts.clear();
    }
}

// Create global instance
window.chartManager = new ChartManager();

// Export helper functions
window.createTopScorersChart = (canvasId, scorers) => 
    window.chartManager.createTopScorersChart(canvasId, scorers);

window.createStandingsChart = (canvasId, standings) => 
    window.chartManager.createStandingsChart(canvasId, standings);

window.createPerformanceChart = (canvasId, data) => 
    window.chartManager.createPerformanceChart(canvasId, data);

window.createPieChart = (canvasId, data, title) => 
    window.chartManager.createPieChart(canvasId, data, title);
