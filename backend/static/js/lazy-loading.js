/**
 * Image Lazy Loading Utilities
 * Provides blur-up loading, intersection observer, and WebP support detection
 */

class ImageLazyLoader {
    constructor(options = {}) {
        this.options = {
            threshold: 0.1,
            rootMargin: '50px',
            blurUpEnabled: true,
            webpEnabled: true,
            ...options
        };
        
        this.isWebPSupported = false;
        this.init();
    }

    /**
     * Initialize lazy loading
     */
    init() {
        // Check WebP support
        this.checkWebPSupport().then(supported => {
            this.isWebPSupported = supported;
            if (supported) {
                document.documentElement.classList.add('webp-supported');
            }
        });

        // Initialize  Intersection Observer
        if ('IntersectionObserver' in window) {
            this.observer = new IntersectionObserver(
                this.handleIntersection.bind(this),
                {
                    threshold: this.options.threshold,
                    rootMargin: this.options.rootMargin
                }
            );

            // Observe all lazy images
            this.observeImages();
        } else {
            // Fallback: load all images immediately
            this.loadAllImages();
        }
    }

    /**
     * Check if browser supports WebP
     */
    async checkWebPSupport() {
        if (!self.createImageBitmap) return false;

        const webpData = 'data:image/webp;base64,UklGRiQAAABXRUJQVlA4IBgAAAAwAQCdASoBAAEAAwA0JaQAA3AA/vuUAAA=';
        
        try {
            const blob = await fetch(webpData).then(r => r.blob());
            return await createImageBitmap(blob).then(() => true, () => false);
        } catch (e) {
            return false;
        }
    }

    /**
     * Observe all lazy images
     */
    observeImages() {
        const lazyImages = document.querySelectorAll('img[loading="lazy"], .lazy-image');
        lazyImages.forEach(img => this.observer.observe(img));
    }

    /**
     * Handle intersection (image enters viewport)
     */
    handleIntersection(entries) {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const img = entry.target;
                this.loadImage(img);
                this.observer.unobserve(img);
            }
        });
    }

    /**
     * Load a specific image
     */
    loadImage(img) {
        // Get the source URL
        const src = img.dataset.src || img.getAttribute('src');
        if (!src) return;

        // For WebP support, try to load WebP version first
        let finalSrc = src;
        if (this.isWebPSupported && this.options.webpEnabled) {
            const webpSrc = img.dataset.srcWebp || src.replace(/\.(jpg|jpeg|png)$/, '.webp');
            if (webpSrc !== src) {
                // Try to load WebP, fallback to original
                this.tryLoadWebP(img, webpSrc, src);
                return;
            }
        }

        // Load regular image
        this.loadImageSrc(img, finalSrc);
    }

    /**
     * Try to load WebP image with fallback
     */
    tryLoadWebP(img, webpSrc, fallbackSrc) {
        const testImg = new Image();
        
        testImg.onload = () => {
            this.loadImageSrc(img, webpSrc);
        };
        
        testImg.onerror = () => {
            this.loadImageSrc(img, fallbackSrc);
        };
        
        testImg.src = webpSrc;
    }

    /**
     * Load image source and handle completion
     */
    loadImageSrc(img, src) {
        // Set up load handler
        img.onload = () => {
            img.classList.add('loaded');
            img.classList.add('fade-in-image');
            
            // Hide blur-up placeholder if exists
            if (this.options.blurUpEnabled) {
                const placeholder = img.previousElementSibling;
                if (placeholder && placeholder.classList.contains('lazy-image-placeholder')) {
                    placeholder.classList.add('hidden');
                }
            }
            
            // Remove loading indicator
            const container = img.parentElement;
            if (container && container.classList.contains('image-loading')) {
                container.classList.remove('image-loading');
}
        };

        // Set source (triggers loading)
        if (img.dataset.src) {
            img.src = img.dataset.src;
            img.removeAttribute('data-src');
        }
        
        if (img.dataset.srcset) {
            img.srcset = img.dataset.srcset;
            img.removeAttribute('data-srcset');
        }
    }

    /**
     * Load all images immediately (fallback)
     */
    loadAllImages() {
        const lazyImages = document.querySelectorAll('img[loading="lazy"], .lazy-image');
        lazyImages.forEach(img => this.loadImage(img));
    }

    /**
     * Dynamically add new images to observe
     */
    observe(img) {
        if (this.observer) {
            this.observer.observe(img);
        } else {
            this.loadImage(img);
        }
    }

    /**
     * Stop observing an image
     */
    unobserve(img) {
        if (this.observer) {
            this.observer.unobserve(img);
        }
    }

    /**
     * Disconnect observer
     */
    disconnect() {
        if (this.observer) {
            this.observer.disconnect();
        }
    }
}

// Create global instance
window.imageLazyLoader = new ImageLazyLoader({
    threshold: 0.1,
    rootMargin: '100px',
    blurUpEnabled: true,
    webpEnabled: true
});

// Export helper functions
window.observeLazyImage = (img) => window.imageLazyLoader.observe(img);
window.unobserveLazyImage = (img) => window.imageLazyLoader.unobserve(img);

// Reinitialize when new content is added (e.g., via htmx)
// Guard against document.body being null if script loads in <head>
if (document.body) {
    document.body.addEventListener('htmx:afterSwap', () => {
        window.imageLazyLoader.observeImages();
    });
} else {
    document.addEventListener('DOMContentLoaded', () => {
        document.body.addEventListener('htmx:afterSwap', () => {
            window.imageLazyLoader.observeImages();
        });
    });
}

// Also observe on DOM content loaded
document.addEventListener('DOMContentLoaded', () => {
    window.imageLazyLoader.observeImages();
});
